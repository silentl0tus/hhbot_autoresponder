from unittest.mock import AsyncMock

import pytest
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
