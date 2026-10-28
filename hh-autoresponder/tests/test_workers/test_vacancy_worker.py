from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.company import Company
from app.models.vacancy import Vacancy, VacancyStatus
from app.workers.vacancy_worker import run_vacancy_analysis


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
async def test_run_vacancy_analysis_rejects_capped_company(test_session, mocker):
    mocker.patch("app.workers.vacancy_worker.async_session", test_session)
    mocker.patch("app.workers.vacancy_worker.random_delay", new_callable=AsyncMock)
    mocker.patch("app.utils.notifier.vlog", new_callable=AsyncMock)
    mocker.patch("app.workers.vacancy_worker.HHParser.get_vacancy_details", new_callable=AsyncMock, return_value=None)
    mocker.patch(
        "app.workers.vacancy_worker.rule_analyze",
        return_value={"score": 85, "reason": "Good match", "matched_target": ["developer"]},
    )

    async with test_session() as session:
        comp = Company(name="Megacorp", platform="hh")
        session.add(comp)
        await session.flush()

        # 2 vacancies already applied
        v1 = Vacancy(
            platform="hh",
            external_id="mc1",
            title="Dev 1",
            url="u1",
            company_id=comp.id,
            status=VacancyStatus.APPLIED,
        )
        v2 = Vacancy(
            platform="hh",
            external_id="mc2",
            title="Dev 2",
            url="u2",
            company_id=comp.id,
            status=VacancyStatus.APPLIED,
        )
        # 1 new vacancy to analyze
        v3 = Vacancy(
            platform="hh",
            external_id="mc3",
            title="Dev 3",
            url="u3",
            company_id=comp.id,
            status=VacancyStatus.NEW,
        )
        session.add_all([v1, v2, v3])
        await session.commit()

    analyzed = await run_vacancy_analysis()
    assert analyzed == 1

    async with test_session() as session:
        v3_db = await session.scalar(select(Vacancy).where(Vacancy.external_id == "mc3"))
        assert v3_db.status == VacancyStatus.REJECTED
        assert "Лимит откликов в компанию (максимум 2)" in v3_db.ai_reason
