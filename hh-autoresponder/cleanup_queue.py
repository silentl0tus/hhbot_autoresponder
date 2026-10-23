import argparse
import asyncio

import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.application import Application
from app.models.blacklist import Blacklist
from app.models.vacancy import Vacancy, VacancyStatus

log = structlog.get_logger()


async def reset_rejected_vacancies() -> int:
    """Сбросить отклоненные роботом вакансии (REJECTED) в статус NEW для повторного скоринга.

    Исключает:
    - Вакансии, по которым уже были отклики (есть в таблице applications);
    - Вакансии, добавленные в черный список (blacklist).
    """
    async with async_session() as session:
        applied_subquery = select(Application.vacancy_id).where(Application.vacancy_id.isnot(None))
        applied_ids = set((await session.execute(applied_subquery)).scalars().all())

        bl_subquery = select(Blacklist.value).where(Blacklist.entry_type == "vacancy")
        bl_vac_ids = set((await session.execute(bl_subquery)).scalars().all())

        query = select(Vacancy).where(
            Vacancy.status == VacancyStatus.REJECTED,
            Vacancy.id.not_in(applied_ids),
            Vacancy.external_id.not_in(bl_vac_ids),
        )
        vacancies = (await session.execute(query)).scalars().all()

        for v in vacancies:
            v.status = VacancyStatus.NEW
            v.ai_score = None
            v.ai_reason = None

        await session.commit()
        log.info("reset_rejected_vacancies_complete", count=len(vacancies))
        print(f"✅ Сброшено {len(vacancies)} отклоненных вакансий в статус NEW (очередь на переоценку).")
        return len(vacancies)


async def reset_approved_vacancies() -> int:
    """Сбросить одобренные вакансии (APPROVED) в статус NEW."""
    async with async_session() as session:
        result = await session.execute(select(Vacancy).where(Vacancy.status == VacancyStatus.APPROVED))
        vacancies = result.scalars().all()

        for v in vacancies:
            v.status = VacancyStatus.NEW
            v.ai_score = None
            v.ai_reason = None

        await session.commit()
        log.info("reset_approved_vacancies_complete", count=len(vacancies))
        print(f"✅ Сброшено {len(vacancies)} одобренных (APPROVED) вакансий в статус NEW.")
        return len(vacancies)


async def main():
    parser = argparse.ArgumentParser(description="Сброс статусов вакансий в jobhunter.db")
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Сбросить APPROVED вакансии в NEW",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Сбросить и REJECTED (без откликов), и APPROVED в NEW",
    )
    args = parser.parse_args()

    if args.approved:
        await reset_approved_vacancies()
    elif args.all:
        await reset_rejected_vacancies()
        await reset_approved_vacancies()
    else:
        # По умолчанию сбрасываем отклоненные роботом вакансии
        await reset_rejected_vacancies()


if __name__ == "__main__":
    asyncio.run(main())
