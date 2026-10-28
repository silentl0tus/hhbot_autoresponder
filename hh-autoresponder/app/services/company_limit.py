import structlog
from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.company import Company
from app.models.vacancy import Vacancy, VacancyStatus

log = structlog.get_logger()

APPLIED_VACANCY_STATUSES = (
    VacancyStatus.APPLIED,
    VacancyStatus.RESPONSE_RECEIVED,
    VacancyStatus.INTERVIEW,
)

APPLICATION_SUCCESS_STATUSES = (
    ApplicationStatus.SENT,
    ApplicationStatus.VIEWED,
    ApplicationStatus.INVITED,
    ApplicationStatus.REJECTED,
)


def get_applied_vacancy_condition():
    """SQL-условие для определения вакансий, на которые уже был отправлен отклик."""
    return or_(
        Vacancy.status.in_(APPLIED_VACANCY_STATUSES),
        Vacancy.id.in_(select(Application.vacancy_id).where(Application.status.in_(APPLICATION_SUCCESS_STATUSES))),
    )


async def get_capped_companies(
    session: AsyncSession,
    max_applies: int | None = None,
) -> tuple[set[int], set[str]]:
    """Возвращает (capped_company_ids, capped_company_names_normalized).

    Компания считается исчерпавшей лимит, если количество уникальных вакансий с
    откликом для неё >= max_applies.
    """
    if max_applies is None:
        max_applies = settings.max_applies_per_company
    if max_applies <= 0:
        return set(), set()

    applied_cond = get_applied_vacancy_condition()

    # 1. Группировка по нормализованному названию компании
    query_by_name = (
        select(
            func.lower(func.trim(Company.name)).label("norm_name"),
            func.count(distinct(Vacancy.id)).label("cnt"),
        )
        .select_from(Vacancy)
        .join(Company, Vacancy.company_id == Company.id)
        .where(
            Company.name.is_not(None),
            func.trim(Company.name) != "",
            applied_cond,
        )
        .group_by(func.lower(func.trim(Company.name)))
        .having(func.count(distinct(Vacancy.id)) >= max_applies)
    )
    result_names = await session.execute(query_by_name)
    capped_names: set[str] = {row[0] for row in result_names.all() if row[0]}

    # 2. Группировка напрямую по Vacancy.company_id
    query_by_id = (
        select(
            Vacancy.company_id,
            func.count(distinct(Vacancy.id)),
        )
        .where(
            Vacancy.company_id.is_not(None),
            applied_cond,
        )
        .group_by(Vacancy.company_id)
        .having(func.count(distinct(Vacancy.id)) >= max_applies)
    )
    result_ids = await session.execute(query_by_id)
    capped_ids: set[int] = {row[0] for row in result_ids.all() if row[0] is not None}

    # 3. Добавляем ID всех компаний, чьё нормализованное название в capped_names
    if capped_names:
        ids_for_names_query = select(Company.id).where(func.lower(func.trim(Company.name)).in_(capped_names))
        name_ids_res = await session.execute(ids_for_names_query)
        for row in name_ids_res.scalars().all():
            capped_ids.add(row)

    return capped_ids, capped_names


async def count_company_applications(
    session: AsyncSession,
    company_id: int | None = None,
    company_name: str | None = None,
) -> int:
    """Возвращает число уникальных вакансий с откликом для конкретной компании."""
    if not company_id and not company_name:
        return 0

    if company_id and not company_name:
        company_name = await session.scalar(select(Company.name).where(Company.id == company_id))

    applied_cond = get_applied_vacancy_condition()
    conditions = []
    if company_id:
        conditions.append(Vacancy.company_id == company_id)
    if company_name and company_name.strip():
        norm_name = company_name.strip().lower()
        conditions.append(
            Vacancy.company_id.in_(select(Company.id).where(func.lower(func.trim(Company.name)) == norm_name))
        )

    query = select(func.count(distinct(Vacancy.id))).where(
        or_(*conditions),
        applied_cond,
    )
    return (await session.scalar(query)) or 0


async def is_company_capped(
    session: AsyncSession,
    company_id: int | None = None,
    company_name: str | None = None,
    max_applies: int | None = None,
) -> bool:
    """Проверяет, исчерпан ли лимит откликов для указанной компании."""
    if max_applies is None:
        max_applies = settings.max_applies_per_company
    if max_applies <= 0:
        return False
    cnt = await count_company_applications(session, company_id=company_id, company_name=company_name)
    return cnt >= max_applies


async def reject_remaining_company_vacancies(
    session: AsyncSession,
    company_id: int | None = None,
    company_name: str | None = None,
    max_applies: int | None = None,
) -> int:
    """Отклоняет оставшиеся APPROVED вакансии компании с указанием причины достижения лимита."""
    if max_applies is None:
        max_applies = settings.max_applies_per_company
    if not company_id and not company_name:
        return 0

    if company_id and not company_name:
        company_name = await session.scalar(select(Company.name).where(Company.id == company_id))

    conditions = []
    if company_id:
        conditions.append(Vacancy.company_id == company_id)
    if company_name and company_name.strip():
        norm_name = company_name.strip().lower()
        conditions.append(
            Vacancy.company_id.in_(select(Company.id).where(func.lower(func.trim(Company.name)) == norm_name))
        )

    stmt = select(Vacancy).where(
        or_(*conditions),
        Vacancy.status == VacancyStatus.APPROVED,
    )
    res = await session.execute(stmt)
    vacancies = res.scalars().all()
    count = 0
    reason_tag = f"Лимит откликов в компанию (максимум {max_applies})"
    for v in vacancies:
        v.status = VacancyStatus.REJECTED
        v.ai_reason = f"{v.ai_reason or ''} [{reason_tag}]".strip()
        count += 1
    if count:
        await session.commit()
    return count


async def cleanup_capped_companies_vacancies(
    session: AsyncSession,
    max_applies: int | None = None,
) -> int:
    """Находит все исчерпавшие лимит компании и переводит их оставшиеся APPROVED вакансии в REJECTED."""
    if max_applies is None:
        max_applies = settings.max_applies_per_company
    if max_applies <= 0:
        return 0

    capped_ids, _ = await get_capped_companies(session, max_applies=max_applies)
    if not capped_ids:
        return 0

    stmt = select(Vacancy).where(
        Vacancy.company_id.in_(capped_ids),
        Vacancy.status == VacancyStatus.APPROVED,
    )
    res = await session.execute(stmt)
    vacancies = res.scalars().all()
    count = 0
    reason_tag = f"Лимит откликов в компанию (максимум {max_applies})"
    for v in vacancies:
        v.status = VacancyStatus.REJECTED
        v.ai_reason = f"{v.ai_reason or ''} [{reason_tag}]".strip()
        count += 1
    if count:
        await session.commit()
    return count
