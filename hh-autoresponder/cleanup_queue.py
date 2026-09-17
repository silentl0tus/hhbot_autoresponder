import asyncio
import structlog
from sqlalchemy import select
from app.database import async_session
from app.models.vacancy import Vacancy, VacancyStatus

log = structlog.get_logger()

async def reset_approved_vacancies():
    async with async_session() as session:
        result = await session.execute(
            select(Vacancy).where(Vacancy.status == VacancyStatus.APPROVED)
        )
        vacancies = result.scalars().all()
        
        count = 0
        for v in vacancies:
            v.status = VacancyStatus.NEW
            v.ai_score = None
            v.ai_reason = None
            count += 1
            
        await session.commit()
        log.info("reset_approved_vacancies_complete", count=count)
        print(f"Reset {count} APPROVED vacancies to NEW status for re-scoring.")

if __name__ == "__main__":
    asyncio.run(reset_approved_vacancies())
