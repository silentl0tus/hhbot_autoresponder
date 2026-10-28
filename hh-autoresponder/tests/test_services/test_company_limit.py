import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.application import Application, ApplicationStatus
from app.models.base import Base
from app.models.company import Company
from app.models.vacancy import Vacancy, VacancyStatus
from app.services.company_limit import (
    cleanup_capped_companies_vacancies,
    count_company_applications,
    get_capped_companies,
    is_company_capped,
    reject_remaining_company_vacancies,
)


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
async def test_get_capped_companies_empty_db(test_session):
    async with test_session() as session:
        capped_ids, capped_names = await get_capped_companies(session, max_applies=2)
        assert capped_ids == set()
        assert capped_names == set()


@pytest.mark.asyncio
async def test_get_capped_companies_threshold(test_session):
    async with test_session() as session:
        comp1 = Company(name="Yandex", platform="hh")
        comp2 = Company(name="Sber", platform="hh")
        session.add_all([comp1, comp2])
        await session.flush()

        # comp1 has 2 applied vacancies (limit reached)
        v1 = Vacancy(
            platform="hh", external_id="1", title="Dev1", url="u1", company_id=comp1.id, status=VacancyStatus.APPLIED
        )
        v2 = Vacancy(
            platform="hh", external_id="2", title="Dev2", url="u2", company_id=comp1.id, status=VacancyStatus.APPROVED
        )
        session.add_all([v1, v2])
        await session.flush()

        app2 = Application(vacancy_id=v2.id, platform="hh", status=ApplicationStatus.SENT)
        session.add(app2)

        # comp2 has 1 applied vacancy (limit not reached)
        v3 = Vacancy(
            platform="hh", external_id="3", title="Dev3", url="u3", company_id=comp2.id, status=VacancyStatus.APPLIED
        )
        session.add(v3)
        await session.commit()

        capped_ids, capped_names = await get_capped_companies(session, max_applies=2)
        assert comp1.id in capped_ids
        assert "yandex" in capped_names
        assert comp2.id not in capped_ids
        assert "sber" not in capped_names


@pytest.mark.asyncio
async def test_get_capped_companies_dedup_by_normalized_name(test_session):
    async with test_session() as session:
        # Two company rows with same name in different case/spaces
        comp_hh = Company(name=" Ozon ", platform="hh")
        comp_habr = Company(name="ozon", platform="habr")
        session.add_all([comp_hh, comp_habr])
        await session.flush()

        v1 = Vacancy(
            platform="hh", external_id="10", title="QA", url="u10", company_id=comp_hh.id, status=VacancyStatus.APPLIED
        )
        v2 = Vacancy(
            platform="habr",
            external_id="11",
            title="QA 2",
            url="u11",
            company_id=comp_habr.id,
            status=VacancyStatus.APPLIED,
        )
        session.add_all([v1, v2])
        await session.commit()

        capped_ids, capped_names = await get_capped_companies(session, max_applies=2)
        assert "ozon" in capped_names
        # Both IDs should be capped
        assert comp_hh.id in capped_ids
        assert comp_habr.id in capped_ids


@pytest.mark.asyncio
async def test_failed_applications_do_not_count(test_session):
    async with test_session() as session:
        comp = Company(name="Tinkoff", platform="hh")
        session.add(comp)
        await session.flush()

        v1 = Vacancy(
            platform="hh",
            external_id="20",
            title="Python",
            url="u20",
            company_id=comp.id,
            status=VacancyStatus.APPROVED,
        )
        session.add(v1)
        await session.flush()
        app1 = Application(vacancy_id=v1.id, platform="hh", status=ApplicationStatus.FAILED)
        session.add(app1)
        await session.commit()

        capped_ids, capped_names = await get_capped_companies(session, max_applies=1)
        assert capped_ids == set()
        assert capped_names == set()

        cnt = await count_company_applications(session, company_id=comp.id)
        assert cnt == 0
        assert not await is_company_capped(session, company_id=comp.id, max_applies=1)


@pytest.mark.asyncio
async def test_reject_remaining_company_vacancies(test_session):
    async with test_session() as session:
        comp = Company(name="VK", platform="hh")
        session.add(comp)
        await session.flush()

        v1 = Vacancy(
            platform="hh", external_id="30", title="V1", url="u30", company_id=comp.id, status=VacancyStatus.APPLIED
        )
        v2 = Vacancy(
            platform="hh", external_id="31", title="V2", url="u31", company_id=comp.id, status=VacancyStatus.APPLIED
        )
        v3 = Vacancy(
            platform="hh",
            external_id="32",
            title="V3",
            url="u32",
            company_id=comp.id,
            status=VacancyStatus.APPROVED,
            ai_score=85.0,
        )
        v4 = Vacancy(
            platform="hh",
            external_id="33",
            title="V4",
            url="u33",
            company_id=comp.id,
            status=VacancyStatus.APPROVED,
            ai_score=75.0,
        )
        session.add_all([v1, v2, v3, v4])
        await session.commit()

        rejected = await reject_remaining_company_vacancies(session, company_id=comp.id, max_applies=2)
        assert rejected == 2

        v3_db = await session.get(Vacancy, v3.id)
        v4_db = await session.get(Vacancy, v4.id)
        assert v3_db.status == VacancyStatus.REJECTED
        assert "Лимит откликов в компанию (максимум 2)" in v3_db.ai_reason
        assert v4_db.status == VacancyStatus.REJECTED
        assert "Лимит откликов в компанию (максимум 2)" in v4_db.ai_reason


@pytest.mark.asyncio
async def test_cleanup_capped_companies_vacancies(test_session):
    async with test_session() as session:
        comp = Company(name="Avito", platform="hh")
        session.add(comp)
        await session.flush()

        v1 = Vacancy(
            platform="hh", external_id="40", title="A1", url="u40", company_id=comp.id, status=VacancyStatus.APPLIED
        )
        v2 = Vacancy(
            platform="hh", external_id="41", title="A2", url="u41", company_id=comp.id, status=VacancyStatus.APPLIED
        )
        v3 = Vacancy(
            platform="hh", external_id="42", title="A3", url="u42", company_id=comp.id, status=VacancyStatus.APPROVED
        )
        session.add_all([v1, v2, v3])
        await session.commit()

        cleaned = await cleanup_capped_companies_vacancies(session, max_applies=2)
        assert cleaned == 1

        v3_db = await session.get(Vacancy, v3.id)
        assert v3_db.status == VacancyStatus.REJECTED
