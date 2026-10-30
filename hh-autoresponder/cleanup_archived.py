"""Скрипт и утилита очистки архивных (ARCHIVED) вакансий из базы данных jobhunter.db."""

import argparse
import asyncio

import structlog
from sqlalchemy import delete, select

from app.database import async_session, engine
from app.models.ai_generation import AIGeneration
from app.models.application import Application
from app.models.message import RecruiterMessage
from app.models.vacancy import Vacancy, VacancyStatus

log = structlog.get_logger()


async def cleanup_archived_vacancies(dry_run: bool = False) -> dict:
    """Удаляет вакансии со статусом ARCHIVED и связанные с ними записи.

    Returns:
        dict со статистикой: count, count_vacancies, count_apps, count_messages, count_ai, dry_run
    """
    async with async_session() as session:
        archived_subquery = select(Vacancy.id).where(Vacancy.status == VacancyStatus.ARCHIVED)
        archived_ids = (await session.execute(archived_subquery)).scalars().all()
        count_vac = len(archived_ids)

        if count_vac == 0:
            return {
                "count": 0,
                "count_vacancies": 0,
                "count_apps": 0,
                "count_messages": 0,
                "count_ai": 0,
                "dry_run": dry_run,
            }

        app_cnt_q = select(Application.id).where(Application.vacancy_id.in_(archived_ids))
        count_apps = len((await session.execute(app_cnt_q)).scalars().all())

        msg_cnt_q = select(RecruiterMessage.id).where(RecruiterMessage.vacancy_id.in_(archived_ids))
        count_msgs = len((await session.execute(msg_cnt_q)).scalars().all())

        ai_cnt_q = select(AIGeneration.id).where(AIGeneration.vacancy_id.in_(archived_ids))
        count_ai = len((await session.execute(ai_cnt_q)).scalars().all())

        if dry_run:
            return {
                "count": count_vac,
                "count_vacancies": count_vac,
                "count_apps": count_apps,
                "count_messages": count_msgs,
                "count_ai": count_ai,
                "dry_run": True,
            }

        if count_apps > 0:
            await session.execute(delete(Application).where(Application.vacancy_id.in_(archived_ids)))
        if count_msgs > 0:
            await session.execute(delete(RecruiterMessage).where(RecruiterMessage.vacancy_id.in_(archived_ids)))
        if count_ai > 0:
            await session.execute(delete(AIGeneration).where(AIGeneration.vacancy_id.in_(archived_ids)))

        await session.execute(delete(Vacancy).where(Vacancy.id.in_(archived_ids)))
        await session.commit()

        # Сжатие SQLite файла (освобождение дискового пространства)
        try:
            async with engine.connect() as conn:
                sync_conn = await conn.get_raw_connection()
                await sync_conn.driver_connection.execute("VACUUM")
        except Exception as e:  # noqa: BLE001
            log.warning("sqlite_vacuum_skipped", error=str(e))

        log.info(
            "cleanup_archived_vacancies_complete",
            vacancies=count_vac,
            applications=count_apps,
            messages=count_msgs,
            ai_generations=count_ai,
        )

        return {
            "count": count_vac,
            "count_vacancies": count_vac,
            "count_apps": count_apps,
            "count_messages": count_msgs,
            "count_ai": count_ai,
            "dry_run": False,
        }


async def main():
    parser = argparse.ArgumentParser(description="Очистка архивных вакансий (ARCHIVED) в базе данных")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Выполнить фактическое удаление архивных вакансий (по умолчанию безопасный dry-run)",
    )
    args = parser.parse_args()

    dry_run = not args.delete
    if dry_run:
        print("🔍 Запуск в режиме предварительного просмотра (--dry-run)...")
    else:
        print("🗑️ Запуск фактического удаления архивных вакансий...")

    res = await cleanup_archived_vacancies(dry_run=dry_run)

    if res["count"] == 0:
        print("ℹ️ В базе данных нет архивных вакансий.")
        return

    if dry_run:
        print(f"📦 Найдено архивных вакансий для удаления: {res['count_vacancies']}")
        print(f"   • Связанных откликов: {res['count_apps']}")
        print(f"   • Связанных сообщений рекрутеров: {res['count_messages']}")
        print(f"   • Связанных AI-генераций: {res['count_ai']}")
        print("\nЧтобы удалить эти записи из базы, запустите:")
        print("   python cleanup_archived.py --delete")
    else:
        print(f"✅ Успешно удалено архивных вакансий: {res['count_vacancies']}")
        if res["count_messages"]:
            print(f"   • Очищено сообщений: {res['count_messages']}")
        if res["count_apps"]:
            print(f"   • Очищено откликов: {res['count_apps']}")
        print("✨ База данных сжата (VACUUM).")


if __name__ == "__main__":
    asyncio.run(main())
