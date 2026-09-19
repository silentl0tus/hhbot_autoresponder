import asyncio
import os
import sys

# Добавляем корневую папку в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from app.database import async_session
from app.models.application import Application, ApplicationStatus
from app.services.google_sheets import append_application

from app.models.vacancy import Vacancy

async def backfill():
    print("Starting Google Sheets backfill...")
    async with async_session() as session:
        # Получаем все успешные или ошибочные отклики
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy).selectinload(Vacancy.company))
            .where(Application.status.in_([ApplicationStatus.SENT, ApplicationStatus.FAILED]))
            .order_by(Application.created_at.asc())
        )
        
        result = await session.execute(stmt)
        applications = result.scalars().all()
        
        print(f"Found {len(applications)} applications to backfill.")
        
        for app in applications:
            vacancy = app.vacancy
            if not vacancy:
                continue
                
            date_str = app.created_at.strftime("%Y-%m-%d")
            company_name = vacancy.company.name if vacancy.company else "Неизвестно"
            
            # Статус
            if app.status == ApplicationStatus.SENT:
                status_str = "Успешно (backfill)"
            else:
                status_str = f"Ошибка: {app.error_message}"
                
            print(f"Exporting: {date_str} - {vacancy.title} - {company_name}")
            
            await append_application(
                date_str=date_str,
                title=vacancy.title or "",
                company=company_name,
                url=vacancy.url or "",
                status=status_str,
                cover_letter=app.cover_letter or "",
                ai_score=vacancy.ai_score
            )
            
            # Небольшая пауза чтобы не словить Rate Limit от Google API
            await asyncio.sleep(1)

    print("Backfill completed!")

if __name__ == "__main__":
    asyncio.run(backfill())
