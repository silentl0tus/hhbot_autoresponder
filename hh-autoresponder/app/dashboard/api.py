from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.application import Application
from app.models.blacklist import Blacklist
from app.models.company import Company
from app.models.message import RecruiterMessage
from app.models.vacancy import Vacancy, VacancyStatus


def _check_session_health(path_str: str) -> dict:
    p = Path(path_str)
    if not p.exists():
        return {"exists": False, "status": "missing", "updated_at": None, "age_hours": None}

    mtime = p.stat().st_mtime
    dt = datetime.fromtimestamp(mtime, tz=ZoneInfo("Europe/Moscow"))
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    age_hours = round((now - dt).total_seconds() / 3600, 1)

    # If updated in the last 24 hours, usually valid unless error in logs
    status = "valid" if age_hours < 24 else "warning" if age_hours < 48 else "expired"
    return {
        "exists": True,
        "status": status,
        "updated_at": dt.strftime("%Y-%m-%d %H:%M"),
        "age_hours": age_hours,
    }


async def get_dashboard_stats() -> dict:
    async with async_session() as session:
        # Vacancies count by status
        v_rows = (await session.execute(select(Vacancy.status, func.count(Vacancy.id)).group_by(Vacancy.status))).all()
        vac_by_status = {str(st.value if hasattr(st, "value") else st): count for st, count in v_rows}

        total_vacancies = sum(vac_by_status.values())
        new_vacancies = vac_by_status.get("new", 0)
        approved_vacancies = vac_by_status.get("approved", 0)
        rejected_vacancies = vac_by_status.get("rejected", 0)
        applied_vacancies = vac_by_status.get("applied", 0)
        archived_vacancies = vac_by_status.get("archived", 0)
        interview_vacancies = vac_by_status.get("interview", 0)
        response_vacancies = vac_by_status.get("response_received", 0)

        # Applications by status (all time)
        app_rows = (
            await session.execute(select(Application.status, func.count(Application.id)).group_by(Application.status))
        ).all()
        app_by_status = {str(st.value if hasattr(st, "value") else st): count for st, count in app_rows}

        total_sent = app_by_status.get("sent", 0)
        total_viewed = app_by_status.get("viewed", 0)
        total_invited = app_by_status.get("invited", 0)
        total_rejected_by_emp = app_by_status.get("rejected", 0)
        total_failed = app_by_status.get("failed", 0)

        # Applications today
        today_app_rows = (
            await session.execute(
                select(Application.status, func.count(Application.id))
                .where(func.date(Application.created_at) == func.current_date())
                .group_by(Application.status)
            )
        ).all()
        today_apps = {str(st.value if hasattr(st, "value") else st): count for st, count in today_app_rows}
        sent_today = today_apps.get("sent", 0)
        failed_today = today_apps.get("failed", 0)

        # Average AI Score
        avg_score = await session.scalar(select(func.avg(Vacancy.ai_score)).where(Vacancy.ai_score.is_not(None)))

        # Total recruiter messages
        total_messages = await session.scalar(select(func.count(RecruiterMessage.id))) or 0

        # Timeline (last 14 days)
        timeline_rows = (
            await session.execute(
                select(
                    func.date(Application.created_at).label("day"),
                    Application.status,
                    func.count(Application.id),
                )
                .where(Application.created_at >= func.date("now", "-14 day"))
                .group_by(func.date(Application.created_at), Application.status)
                .order_by(func.date(Application.created_at).asc())
            )
        ).all()

        timeline_dict: dict[str, dict[str, int]] = {}
        for day, status, count in timeline_rows:
            day_str = str(day)
            st_str = str(status.value if hasattr(status, "value") else status).lower()
            if day_str not in timeline_dict:
                timeline_dict[day_str] = {"sent": 0, "viewed": 0, "invited": 0, "failed": 0, "rejected": 0}
            timeline_dict[day_str][st_str] = count

        timeline = [{"date": d, **counts} for d, counts in timeline_dict.items()]

        # Rejection reasons breakdown
        reasons_rows = (
            await session.execute(
                select(Vacancy.ai_reason, func.count(Vacancy.id))
                .where(Vacancy.status == VacancyStatus.REJECTED)
                .group_by(Vacancy.ai_reason)
                .order_by(func.count(Vacancy.id).desc())
                .limit(8)
            )
        ).all()

        reasons_breakdown = []
        for r_text, count in reasons_rows:
            label = r_text or "Не указана"
            if len(label) > 60:
                label = label[:60] + "..."
            reasons_breakdown.append({"reason": label, "count": count})

    # Sessions health
    sessions = {
        "hh": _check_session_health("data/browser_sessions/hh_state.json"),
        "habr": _check_session_health("data/browser_sessions/habr_state.json"),
        "max": _check_session_health("data/browser_sessions/max_state.json"),
    }

    # Funnel computation
    delivered = total_sent + total_viewed + total_invited + total_rejected_by_emp
    funnel = [
        {"stage": "Найдено вакансий", "count": total_vacancies, "rate": "100%"},
        {
            "stage": "Одобрено скорингом",
            "count": approved_vacancies + applied_vacancies + interview_vacancies + response_vacancies,
            "rate": f"{round(((approved_vacancies + applied_vacancies + interview_vacancies + response_vacancies) / total_vacancies * 100), 1)}%"
            if total_vacancies
            else "0%",
        },
        {
            "stage": "Отправлено откликов",
            "count": delivered,
            "rate": f"{round((delivered / (approved_vacancies + applied_vacancies + interview_vacancies + response_vacancies) * 100), 1)}%"
            if (approved_vacancies + applied_vacancies + interview_vacancies + response_vacancies)
            else "0%",
        },
        {
            "stage": "Просмотрено рекрутером",
            "count": total_viewed + total_invited,
            "rate": f"{round(((total_viewed + total_invited) / delivered * 100), 1)}%" if delivered else "0%",
        },
        {
            "stage": "Приглашения на интервью",
            "count": total_invited,
            "rate": f"{round((total_invited / delivered * 100), 1)}%" if delivered else "0%",
        },
    ]

    return {
        "summary": {
            "total_vacancies": total_vacancies,
            "new_vacancies": new_vacancies,
            "approved_vacancies": approved_vacancies,
            "rejected_vacancies": rejected_vacancies,
            "applied_vacancies": applied_vacancies,
            "archived_vacancies": archived_vacancies,
            "interview_vacancies": interview_vacancies,
            "response_vacancies": response_vacancies,
            "total_sent": total_sent,
            "total_viewed": total_viewed,
            "total_invited": total_invited,
            "total_rejected_by_emp": total_rejected_by_emp,
            "total_failed": total_failed,
            "sent_today": sent_today,
            "failed_today": failed_today,
            "avg_ai_score": round(avg_score, 1) if avg_score else 0,
            "total_messages": total_messages,
        },
        "funnel": funnel,
        "timeline": timeline,
        "reasons": reasons_breakdown,
        "sessions": sessions,
        "config": {
            "desired_position": settings.desired_position,
            "score_threshold": settings.score_threshold,
            "salary_floor": settings.salary_floor,
            "geo_filter_enabled": settings.geo_filter_enabled,
            "search_queries_count": len(settings.search_queries),
            "target_keywords_count": len(settings.target_keywords),
        },
    }


async def get_vacancies_list(
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    limit: int = 25,
    sort: str = "date",
) -> dict:
    async with async_session() as session:
        query = select(Vacancy).options(selectinload(Vacancy.company))

        if status and status.upper() != "ALL":
            try:
                st_enum = VacancyStatus(status.lower())
                query = query.where(Vacancy.status == st_enum)
            except ValueError:
                pass

        if search:
            s_term = f"%{search.strip().lower()}%"
            query = query.outerjoin(Company).where(
                or_(
                    func.lower(Vacancy.title).like(s_term),
                    func.lower(Company.name).like(s_term),
                    func.lower(Vacancy.location).like(s_term),
                )
            )

        # Count total matching
        count_query = select(func.count()).select_from(query.subquery())
        total_count = await session.scalar(count_query) or 0

        # Order by
        if sort == "score":
            query = query.order_by(Vacancy.ai_score.desc().nullslast(), Vacancy.created_at.desc())
        else:
            query = query.order_by(Vacancy.created_at.desc())

        offset = (page - 1) * limit
        query = query.offset(offset).limit(limit)

        result = await session.execute(query)
        vacancies = result.scalars().all()

        items = []
        for v in vacancies:
            items.append(
                {
                    "id": v.id,
                    "platform": v.platform,
                    "external_id": v.external_id,
                    "url": v.url,
                    "title": v.title,
                    "company_name": v.company.name if v.company else "—",
                    "salary_from": v.salary_from,
                    "salary_to": v.salary_to,
                    "salary_currency": v.salary_currency,
                    "location": v.location,
                    "is_remote": v.is_remote,
                    "work_format": v.work_format,
                    "status": str(v.status.value if hasattr(v.status, "value") else v.status),
                    "ai_score": v.ai_score,
                    "ai_reason": v.ai_reason,
                    "created_at": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else None,
                }
            )

        return {
            "items": items,
            "total": total_count,
            "page": page,
            "limit": limit,
            "pages": (total_count + limit - 1) // limit if limit else 1,
        }


async def get_applications_list(limit: int = 50) -> list[dict]:
    async with async_session() as session:
        query = (
            select(Application)
            .options(selectinload(Application.vacancy).selectinload(Vacancy.company))
            .order_by(Application.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        apps = result.scalars().all()

        items = []
        for a in apps:
            items.append(
                {
                    "id": a.id,
                    "vacancy_id": a.vacancy_id,
                    "vacancy_title": a.vacancy.title if a.vacancy else "—",
                    "company_name": a.vacancy.company.name if (a.vacancy and a.vacancy.company) else "—",
                    "vacancy_url": a.vacancy.url if a.vacancy else "#",
                    "platform": a.platform,
                    "status": str(a.status.value if hasattr(a.status, "value") else a.status),
                    "error_message": a.error_message,
                    "attempt_count": a.attempt_count,
                    "created_at": a.created_at.strftime("%Y-%m-%d %H:%M") if a.created_at else None,
                    "updated_at": a.updated_at.strftime("%Y-%m-%d %H:%M") if a.updated_at else None,
                }
            )
        return items


async def get_messages_list(limit: int = 40) -> list[dict]:
    async with async_session() as session:
        query = (
            select(RecruiterMessage)
            .options(selectinload(RecruiterMessage.vacancy))
            .order_by(RecruiterMessage.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        msgs = result.scalars().all()

        items = []
        for m in msgs:
            items.append(
                {
                    "id": m.id,
                    "platform": m.platform,
                    "sender_name": m.sender_name or "Рекрутер",
                    "sender_company": m.sender_company or "Компания",
                    "text": m.text,
                    "is_read": m.is_read,
                    "ai_suggested_reply": m.ai_suggested_reply,
                    "created_at": m.created_at.strftime("%Y-%m-%d %H:%M") if m.created_at else None,
                }
            )
        return items


def get_recent_logs(lines_count: int = 100, level_filter: str | None = None) -> list[dict]:
    log_path = Path("logs/log.txt")
    if not log_path.exists():
        return []

    try:
        # Read last chunk
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-lines_count * 2 :]
    except OSError:
        return []

    results = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue

        level = "info"
        if "[error" in line.lower() or "error" in line.lower() and "traceback" in line.lower():
            level = "error"
        elif "[warning" in line.lower() or "warn" in line.lower():
            level = "warning"
        elif "[debug" in line.lower():
            level = "debug"

        if level_filter and level_filter.lower() != "all" and level != level_filter.lower():
            continue

        results.append({"text": line, "level": level})
        if len(results) >= lines_count:
            break

    return results


async def trigger_reset_rejected() -> int:
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
        return len(vacancies)
