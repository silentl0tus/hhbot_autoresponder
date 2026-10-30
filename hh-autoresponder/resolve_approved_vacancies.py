"""Скрипт разрешения и актуализации застрявших APPROVED вакансий."""

import asyncio
import httpx
from bs4 import BeautifulSoup
import structlog
from sqlalchemy import select

from app.database import async_session
from app.models.vacancy import Vacancy, VacancyStatus

log = structlog.get_logger()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}


async def resolve_approved():
    async with async_session() as session:
        approved_vacancies = (
            (await session.execute(select(Vacancy).where(Vacancy.status == VacancyStatus.APPROVED))).scalars().all()
        )

    print(f"Найдено {len(approved_vacancies)} вакансий со статусом APPROVED.")
    if not approved_vacancies:
        return

    archived_count = 0
    rejected_count = 0

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
        for vac in approved_vacancies:
            new_status = None
            reason_suffix = ""

            try:
                resp = await client.get(vac.url)
                if resp.status_code == 404:
                    new_status = VacancyStatus.ARCHIVED
                    reason_suffix = "[Вакансия удалена / 404]"
                elif resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "lxml")
                    text = soup.get_text()
                    if any(
                        m in text
                        for m in ("Ошибка 404", "закрыла свой профиль", "Вакансия в архиве", "вакансия закрыта")
                    ):
                        new_status = VacancyStatus.ARCHIVED
                        reason_suffix = "[Вакансия в архиве]"
                    elif bool(soup.find("a", href=lambda h: h and "external_response" in h)):
                        new_status = VacancyStatus.REJECTED
                        reason_suffix = "[Внешний отклик на сайте компании]"
            except Exception as e:
                print(f"Ошибка проверки URL {vac.url}: {e}")

            # Если статус не определен по странице, но уже было 3+ неудачных попыток:
            if not new_status:
                new_status = VacancyStatus.REJECTED
                reason_suffix = "[3+ неудачных попыток отклика]"

            async with async_session() as session:
                v = await session.get(Vacancy, vac.id)
                if v:
                    v.status = new_status
                    v.ai_reason = f"{v.ai_reason or ''} {reason_suffix}".strip()
                    await session.commit()

            if new_status == VacancyStatus.ARCHIVED:
                archived_count += 1
                print(f"-> ID {vac.id} '{vac.title}': переведён в ARCHIVED {reason_suffix}")
            else:
                rejected_count += 1
                print(f"-> ID {vac.id} '{vac.title}': переведён в REJECTED {reason_suffix}")

    print(f"\nГотово! Переведено в ARCHIVED: {archived_count}, в REJECTED: {rejected_count}.")


if __name__ == "__main__":
    asyncio.run(resolve_approved())
