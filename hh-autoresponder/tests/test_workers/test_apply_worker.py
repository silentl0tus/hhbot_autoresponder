from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.company import Company
from app.models.vacancy import Vacancy, VacancyStatus
from app.workers.apply_worker import run_auto_apply


@pytest.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    yield session_maker

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_auto_apply_stops_at_target_count(test_session, mocker):
    """Тест: цикл откликов останавливается ровно по достижении target_count."""
    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    # Mock HHParser
    mock_apply = AsyncMock(return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.apply_to_vacancy", mock_apply)

    # Seed 5 approved vacancies
    async with test_session() as session:
        company = Company(name="TechCorp", platform="hh", platform_id="101")
        session.add(company)
        await session.flush()
        for i in range(5):
            vac = Vacancy(
                platform="hh",
                external_id=f"vac_{i}",
                title=f"QA Automation Engineer {i}",
                url=f"https://hh.ru/vacancy/{i}",
                company_id=company.id,
                status=VacancyStatus.APPROVED,
                ai_score=80.0 - i,
                work_format="remote",
            )
            session.add(vac)
        await session.commit()

    # Target 2 applications
    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=2)

    assert applied == 2
    assert mock_apply.call_count == 2

    # Check statuses in DB
    async with test_session() as session:
        from sqlalchemy import select

        res = await session.execute(select(Vacancy).where(Vacancy.status == VacancyStatus.APPLIED))
        applied_vacs = res.scalars().all()
        assert len(applied_vacs) == 2


@pytest.mark.asyncio
async def test_run_auto_apply_skips_already_applied_without_counting(test_session, mocker):
    """Тест: если вакансия уже была с откликом (already), она отмечается APPLIED,
    но не считается успешным новым откликом, и цикл продолжается до target_count."""
    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    # First returns "already", second returns True
    mock_apply = AsyncMock(side_effect=["already", True])
    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.apply_to_vacancy", mock_apply)

    async with test_session() as session:
        company = Company(name="TechCorp", platform="hh", platform_id="102")
        session.add(company)
        await session.flush()
        for i in range(2):
            vac = Vacancy(
                platform="hh",
                external_id=f"vac_already_{i}",
                title=f"DevOps Engineer {i}",
                url=f"https://hh.ru/vacancy/al_{i}",
                company_id=company.id,
                status=VacancyStatus.APPROVED,
                ai_score=90.0 - i,
                work_format="remote",
            )
            session.add(vac)
        await session.commit()

    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=1)

    assert applied == 1
    assert mock_apply.call_count == 2


@pytest.mark.asyncio
async def test_run_auto_apply_replenishes_when_queue_empty(test_session, mocker):
    """Тест: если в auto_mode одобренные вакансии закончились, вызывается поиск и анализ."""
    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    mock_search = AsyncMock()
    mock_analyze = AsyncMock()
    mocker.patch("app.workers.vacancy_worker.run_vacancy_search", mock_search)
    mocker.patch("app.workers.vacancy_worker.run_vacancy_analysis", mock_analyze)

    # Queue is completely empty
    applied = await run_auto_apply(auto_mode=True, min_score=50, target_count=2)

    assert applied == 0
    mock_search.assert_awaited_once()
    mock_analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_auto_apply_appends_to_sheets_after_db_commit(test_session, mocker):
    """Тест: append_application вызывается уже ПОСЛЕ того, как статус вакансии зафиксирован в БД."""
    from sqlalchemy import select

    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    status_during_append = None

    async def mock_append(**kwargs):
        nonlocal status_during_append
        # В момент вызова append_application статус в БД уже должен быть закоммичен как APPLIED
        async with test_session() as session:
            v = await session.scalar(select(Vacancy).where(Vacancy.external_id == "vac_sheets_1"))
            status_during_append = v.status if v else None

    mocker.patch("app.workers.apply_worker.append_application", side_effect=mock_append)
    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.apply_to_vacancy", new_callable=AsyncMock, return_value=True)

    async with test_session() as session:
        company = Company(name="SheetsCorp", platform="hh", platform_id="201")
        session.add(company)
        await session.flush()
        vac = Vacancy(
            platform="hh",
            external_id="vac_sheets_1",
            title="Python Architect",
            url="https://hh.ru/vacancy/sheets_1",
            company_id=company.id,
            status=VacancyStatus.APPROVED,
            ai_score=95.0,
            work_format="remote",
        )
        session.add(vac)
        await session.commit()

    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=1)

    assert applied == 1
    assert status_during_append == VacancyStatus.APPLIED


@pytest.mark.asyncio
async def test_run_auto_apply_marks_needs_test_as_rejected_and_notifies_user(test_session, mocker):
    """Тест: если вакансия требует тест, а pass_tests=False, вакансия помечается REJECTED,
    создается запись в Google Таблице со статусом 'Требуется тест (вручную)' и отправляется
    уведомление с прямой ссылкой пользователю."""
    import json

    from sqlalchemy import select

    from app.models.application import Application, ApplicationStatus

    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mock_append = mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mock_notify_send = mocker.patch("app.utils.notifier.send", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    # Mock scheduler_state to have pass_tests = False
    fake_state = json.dumps({"pass_tests": False, "is_paused": False, "auto_apply": True})
    mocker.patch("pathlib.Path.exists", return_value=True)
    mocker.patch("pathlib.Path.read_text", return_value=fake_state)

    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch(
        "app.workers.apply_worker.HHParser.apply_to_vacancy",
        new_callable=AsyncMock,
        return_value="needs_test",
    )

    async with test_session() as session:
        company = Company(name="TestCorp", platform="hh", platform_id="301")
        session.add(company)
        await session.flush()
        vac = Vacancy(
            platform="hh",
            external_id="vac_needs_test_1",
            title="Senior QA Engineer",
            url="https://hh.ru/vacancy/test_1",
            company_id=company.id,
            status=VacancyStatus.APPROVED,
            ai_score=88.0,
            ai_reason="Отличный стек",
            work_format="remote",
        )
        session.add(vac)
        await session.commit()

    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=1)

    assert applied == 0

    async with test_session() as session:
        v = await session.scalar(select(Vacancy).where(Vacancy.external_id == "vac_needs_test_1"))
        assert v is not None
        assert v.status == VacancyStatus.REJECTED
        assert "Требуется тест/анкета" in v.ai_reason

        app = await session.scalar(select(Application).where(Application.vacancy_id == v.id))
        assert app is not None
        assert app.status == ApplicationStatus.FAILED
        assert "needs_test" in app.error_message

    mock_append.assert_awaited_once()
    assert mock_append.call_args.kwargs["status"] == "Требуется тест (вручную)"

    mock_notify_send.assert_awaited_once()
    notify_text = mock_notify_send.call_args[0][0]
    assert "https://hh.ru/vacancy/test_1" in notify_text
    assert "Senior QA Engineer" in notify_text


@pytest.mark.asyncio
async def test_run_auto_apply_respects_company_limit_of_two(test_session, mocker):
    """Тест: бот не откликается больше чем на 2 вакансии в одну компанию,
    а оставшиеся вакансии этой компании отклоняются с указанием лимита."""
    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    mock_apply = AsyncMock(return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.apply_to_vacancy", mock_apply)

    async with test_session() as session:
        # Company 1: 4 approved vacancies
        comp1 = Company(name="BigTech", platform="hh")
        # Company 2: 2 approved vacancies
        comp2 = Company(name="SmallTech", platform="hh")
        session.add_all([comp1, comp2])
        await session.flush()

        for i in range(4):
            v = Vacancy(
                platform="hh",
                external_id=f"bt_{i}",
                title=f"Engineer BigTech {i}",
                url=f"https://hh.ru/vacancy/bt_{i}",
                company_id=comp1.id,
                status=VacancyStatus.APPROVED,
                ai_score=95.0 - i,
                work_format="remote",
            )
            session.add(v)

        for i in range(2):
            v = Vacancy(
                platform="hh",
                external_id=f"st_{i}",
                title=f"Engineer SmallTech {i}",
                url=f"https://hh.ru/vacancy/st_{i}",
                company_id=comp2.id,
                status=VacancyStatus.APPROVED,
                ai_score=80.0 - i,
                work_format="remote",
            )
            session.add(v)
        await session.commit()

    # Target 10 (more than available)
    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=10)

    # BigTech: 2, SmallTech: 2 -> Total: 4
    assert applied == 4
    assert mock_apply.call_count == 4

    async with test_session() as session:
        from sqlalchemy import select

        bt_applied = (
            (
                await session.execute(
                    select(Vacancy).where(Vacancy.company_id == comp1.id, Vacancy.status == VacancyStatus.APPLIED)
                )
            )
            .scalars()
            .all()
        )
        assert len(bt_applied) == 2

        bt_rejected = (
            (
                await session.execute(
                    select(Vacancy).where(Vacancy.company_id == comp1.id, Vacancy.status == VacancyStatus.REJECTED)
                )
            )
            .scalars()
            .all()
        )
        assert len(bt_rejected) == 2
        for r in bt_rejected:
            assert "Лимит откликов в компанию (максимум 2)" in (r.ai_reason or "")

        st_applied = (
            (
                await session.execute(
                    select(Vacancy).where(Vacancy.company_id == comp2.id, Vacancy.status == VacancyStatus.APPLIED)
                )
            )
            .scalars()
            .all()
        )
        assert len(st_applied) == 2


@pytest.mark.asyncio
async def test_run_auto_apply_skips_already_capped_company_on_start(test_session, mocker):
    """Тест: если компания уже имеет 2 отклика до запуска run_auto_apply,
    ее оставшиеся APPROVED вакансии отклоняются на старте и не отбираются."""
    mocker.patch("app.workers.apply_worker.async_session", test_session)
    mocker.patch("app.workers.apply_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.append_application", new_callable=AsyncMock)
    mocker.patch("app.workers.apply_worker.sync_applied_from_hh", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)

    mock_apply = AsyncMock(return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.login", new_callable=AsyncMock, return_value=True)
    mocker.patch("app.workers.apply_worker.HHParser.apply_to_vacancy", mock_apply)

    async with test_session() as session:
        comp_capped = Company(name="CappedCorp", platform="hh")
        comp_fresh = Company(name="FreshCorp", platform="hh")
        session.add_all([comp_capped, comp_fresh])
        await session.flush()

        # 2 already applied vacancies for CappedCorp
        v_app1 = Vacancy(
            platform="hh",
            external_id="cc_app1",
            title="Dev 1",
            url="u1",
            company_id=comp_capped.id,
            status=VacancyStatus.APPLIED,
            ai_score=90.0,
        )
        v_app2 = Vacancy(
            platform="hh",
            external_id="cc_app2",
            title="Dev 2",
            url="u2",
            company_id=comp_capped.id,
            status=VacancyStatus.APPLIED,
            ai_score=89.0,
        )
        # 1 lingering approved vacancy for CappedCorp
        v_cc_lingering = Vacancy(
            platform="hh",
            external_id="cc_lingering",
            title="Dev 3",
            url="u3",
            company_id=comp_capped.id,
            status=VacancyStatus.APPROVED,
            ai_score=88.0,
            work_format="remote",
        )
        # 1 approved vacancy for FreshCorp
        v_fc = Vacancy(
            platform="hh",
            external_id="fc_1",
            title="Fresh Dev",
            url="u4",
            company_id=comp_fresh.id,
            status=VacancyStatus.APPROVED,
            ai_score=80.0,
            work_format="remote",
        )
        session.add_all([v_app1, v_app2, v_cc_lingering, v_fc])
        await session.commit()

    applied = await run_auto_apply(auto_mode=False, min_score=50, target_count=5)

    assert applied == 1
    assert mock_apply.call_count == 1

    async with test_session() as session:
        v_ling = await session.scalar(select(Vacancy).where(Vacancy.external_id == "cc_lingering"))
        assert v_ling.status == VacancyStatus.REJECTED
        assert "Лимит откликов в компанию (максимум 2)" in v_ling.ai_reason

        v_fresh_db = await session.scalar(select(Vacancy).where(Vacancy.external_id == "fc_1"))
        assert v_fresh_db.status == VacancyStatus.APPLIED
