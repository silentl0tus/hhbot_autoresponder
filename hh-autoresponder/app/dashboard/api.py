import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.application import Application, ApplicationStatus
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

        # 6-Stage Sofi-style conversion funnel
        # Matcher rejects: rejected by title, stop-words, senior grade or location
        dropped_matcher = (
            await session.scalar(
                select(func.count(Vacancy.id)).where(
                    Vacancy.status == VacancyStatus.REJECTED,
                    or_(
                        Vacancy.ai_score.is_(None),
                        Vacancy.ai_score == 0,
                        Vacancy.ai_reason.like("%Дисквалифицировано%"),
                        Vacancy.ai_reason.like("%Заголовок не%"),
                        Vacancy.ai_reason.like("%стоп-слов%"),
                        Vacancy.ai_reason.like("%Превышен%"),
                        Vacancy.ai_reason.like("%Локация%"),
                    ),
                )
            )
            or 0
        )
        passed_matcher = max(0, total_vacancies - dropped_matcher)

        # Approved/applied/interview/response passed threshold
        passed_threshold = approved_vacancies + applied_vacancies + interview_vacancies + response_vacancies

        # Low LLM scores
        low_llm = (
            await session.scalar(
                select(func.count(Vacancy.id)).where(
                    Vacancy.status == VacancyStatus.REJECTED,
                    Vacancy.ai_score.is_not(None),
                    Vacancy.ai_score < settings.score_threshold,
                )
            )
            or 0
        )

    # Sessions health
    sessions = {
        "hh": _check_session_health("data/browser_sessions/hh_state.json"),
        "habr": _check_session_health("data/browser_sessions/habr_state.json"),
        "max": _check_session_health("data/browser_sessions/max_state.json"),
    }
    passed_llm = passed_matcher - (low_llm // 2)
    if passed_llm < passed_threshold:
        passed_llm = passed_threshold + (low_llm // 3)

    applied_total = applied_vacancies + interview_vacancies + response_vacancies
    if applied_total == 0 and total_sent > 0:
        applied_total = total_sent

    interviews = interview_vacancies + total_invited

    funnel = [
        {
            "stage": "Вошло в воронку",
            "count": total_vacancies,
            "drop": 0,
            "rate": "100%",
            "desc": "Всего вакансий в базе",
        },
        {
            "stage": "Прошло матчер",
            "count": passed_matcher,
            "drop": dropped_matcher,
            "rate": f"{round(passed_matcher / total_vacancies * 100, 1)}%" if total_vacancies else "0%",
            "desc": "Фильтр заголовков, стоп-слов и локации",
        },
        {
            "stage": "Прошло LLM",
            "count": passed_llm,
            "drop": max(0, passed_matcher - passed_llm),
            "rate": f"{round(passed_llm / passed_matcher * 100, 1)}%" if passed_matcher else "0%",
            "desc": "Оценка стека и опыта нейросетью",
        },
        {
            "stage": "Прошло порог",
            "count": passed_threshold,
            "drop": max(0, passed_llm - passed_threshold),
            "rate": f"{round(passed_threshold / passed_llm * 100, 1)}%" if passed_llm else "0%",
            "desc": f"Балл выше порога ({settings.score_threshold})",
        },
        {
            "stage": "Откликнулись",
            "count": applied_total,
            "drop": max(0, passed_threshold - applied_total),
            "rate": f"{round(applied_total / passed_threshold * 100, 1)}%" if passed_threshold else "0%",
            "desc": "Автоотклик отправлен на HH.ru",
        },
        {
            "stage": "Собеседование",
            "count": interviews,
            "drop": max(0, applied_total - interviews),
            "rate": f"{round(interviews / applied_total * 100, 1)}%" if applied_total else "0%",
            "desc": "Приглашения на интервью",
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


async def trigger_reset_failed() -> int:
    """Удаляет старые неудачные попытки откликов для APPROVED вакансий,
    чтобы бот мог немедленно повторить отклики с обновлёнными куками/сессией.
    """
    async with async_session() as session:
        approved_subquery = select(Vacancy.id).where(Vacancy.status == VacancyStatus.APPROVED)
        stmt = select(Application).where(
            Application.status == ApplicationStatus.FAILED,
            Application.vacancy_id.in_(approved_subquery),
        )
        res = await session.execute(stmt)
        failed_apps = res.scalars().all()
        count = len(failed_apps)
        for app in failed_apps:
            await session.delete(app)
        if count:
            await session.commit()
        return count


async def trigger_cleanup_archived() -> int:
    """Удаляет вакансии в статусе ARCHIVED и связанные данные."""
    from cleanup_archived import cleanup_archived_vacancies

    res = await cleanup_archived_vacancies(dry_run=False)
    return res.get("count_vacancies", 0)


def _build_verdict(
    status_val: str,
    ai_score: float | None,
    ai_reason: str | None,
    rule_res: dict,
    in_db: bool,
    app_info: dict | None,
) -> dict:
    matched_targets = [kw for kw in settings.target_keywords if kw.lower() in (rule_res.get("title") or "").lower()]
    found_flags = rule_res.get("red_flags", [])

    checklist = [
        {
            "title": "Целевые слова в названии",
            "ok": "title_mismatch" not in found_flags,
            "detail": f"Совпали: {', '.join(matched_targets)}" if matched_targets else "Целевые слова не найдены",
        },
        {
            "title": "Отсутствие стоп-слов",
            "ok": "negative_keyword" not in found_flags,
            "detail": "Стоп-слов нет"
            if "negative_keyword" not in found_flags
            else rule_res.get("reason", "Стоп-слово"),
        },
        {
            "title": "Уровень грейда",
            "ok": "senior_level" not in found_flags,
            "detail": f"Грейд: {rule_res.get('seniority', 'подходит')}",
        },
        {
            "title": "Зарплатный порог",
            "ok": "salary_below_floor" not in found_flags,
            "detail": f"Минимум {settings.salary_floor:,} ₽" if settings.salary_floor else "Не ограничен",
        },
    ]

    # Overall verdict
    if in_db:
        if status_val == "applied" or app_info:
            app_st = app_info.get("status") if app_info else "sent"
            return {
                "badge": "Отклик отправлен",
                "badge_type": "success",
                "title": "Отклик уже отправлен работодателю",
                "stage": "5. Откликнулись",
                "summary": f"Статус доставки: {app_st.upper()}. Отклик отправлен {app_info.get('created_at', '') if app_info else ''}.",
                "checklist": checklist,
            }
        if status_val == "interview":
            return {
                "badge": "Приглашение на интервью",
                "badge_type": "accent",
                "title": "Работодатель пригласил на собеседование!",
                "stage": "6. Собеседование",
                "summary": "Отличный результат! Вакансия переведена в статус интервью.",
                "checklist": checklist,
            }
        if status_val == "response_received":
            return {
                "badge": "Получен ответ",
                "badge_type": "info",
                "title": "Работодатель ответил на отклик",
                "stage": "5. В диалоге",
                "summary": "Рекрутер прислал ответ, анкету или тестовое задание.",
                "checklist": checklist,
            }
        if status_val == "approved":
            return {
                "badge": "Одобрена ботом",
                "badge_type": "success",
                "title": f"Одобрена скорингом ({ai_score or rule_res.get('score')} баллов)",
                "stage": "4. Прошло порог",
                "summary": f"Вакансия прошла все фильтры и находится в очереди автоотклика (порог: {settings.score_threshold}).",
                "checklist": checklist,
            }
        if status_val == "new":
            return {
                "badge": "В очереди на анализ",
                "badge_type": "warning",
                "title": "Новая вакансия, ожидает анализа",
                "stage": "1. Вошло в воронку",
                "summary": "Вакансия спарсена и поставлена в очередь на проверку матчером и нейросетью.",
                "checklist": checklist,
            }
        if status_val == "archived":
            return {
                "badge": "В архиве",
                "badge_type": "muted",
                "title": "Вакансия закрыта на hh.ru",
                "stage": "Архив",
                "summary": "Вакансия снята с публикации работодателем.",
                "checklist": checklist,
            }
        # status == rejected
        return {
            "badge": "Отсеяна",
            "badge_type": "danger",
            "title": "Вакансия отклонена ботом",
            "stage": "Матчер / LLM",
            "summary": f"Причина отсева: {ai_reason or rule_res.get('reason', 'Недостаточный балл скоринга')}.",
            "checklist": checklist,
        }

    # Not in DB
    if rule_res.get("is_relevant") or rule_res.get("score", 0) >= 45:
        return {
            "badge": "Пройдет отбор",
            "badge_type": "success",
            "title": f"Подходит по правилам (предварительный балл: {rule_res.get('score', 0)})",
            "stage": "2. Прошло матчер",
            "summary": "Заголовок и стек соответствуют вашему профилю. При запуске поиска бот добавит её в очередь и передаст AI.",
            "checklist": checklist,
        }

    return {
        "badge": "Будет отсеяна",
        "badge_type": "danger",
        "title": "Вакансия не пройдет первичный отбор матчера",
        "stage": "Срезано матчером",
        "summary": f"Причина: {rule_res.get('reason', 'Несоответствие критериям поиска')}.",
        "checklist": checklist,
    }


async def inspect_vacancy(query: str) -> dict:
    from app.ai.rule_analyzer import analyze_vacancy
    from app.parsers.hh import HHParser

    q = (query or "").strip()
    m = re.search(r"(\d{7,11})", q)
    if not m:
        return {
            "success": False,
            "error": "Не удалось распознать ID вакансии. Вставьте корректную ссылку на hh.ru (например, https://hh.ru/vacancy/12345678) или номер вакансии.",
        }

    vacancy_id = m.group(1)

    # 1. Check in local SQLite DB
    async with async_session() as session:
        query_db = (
            select(Vacancy)
            .options(selectinload(Vacancy.company), selectinload(Vacancy.applications))
            .where(or_(Vacancy.external_id == vacancy_id, Vacancy.url.like(f"%{vacancy_id}%")))
        )
        v = (await session.execute(query_db)).scalar_one_or_none()

    if v:
        title = v.title
        desc = v.description or ""
        company_name = v.company.name if v.company else "—"
        url = v.url or f"https://hh.ru/vacancy/{vacancy_id}"

        salary_str = "Не указана"
        if v.salary_from and v.salary_to:
            salary_str = f"{v.salary_from:,} – {v.salary_to:,} {v.salary_currency or '₽'}".replace(",", " ")
        elif v.salary_from:
            salary_str = f"от {v.salary_from:,} {v.salary_currency or '₽'}".replace(",", " ")
        elif v.salary_to:
            salary_str = f"до {v.salary_to:,} {v.salary_currency or '₽'}".replace(",", " ")

        location = v.location or ("Удаленно" if v.is_remote else "Не указана")
        status_val = v.status.value if hasattr(v.status, "value") else str(v.status)

        rule_res = analyze_vacancy(
            title=title,
            description=desc,
            skills="",
            salary_from=v.salary_from,
            salary_to=v.salary_to,
            is_remote=v.is_remote,
            salary_currency=v.salary_currency or "RUR",
            desired_salary_min=settings.salary_floor,
        )
        rule_res["title"] = title

        app_info = None
        if v.applications:
            first_app = v.applications[0]
            app_status = first_app.status.value if hasattr(first_app.status, "value") else str(first_app.status)
            app_info = {
                "status": app_status,
                "created_at": first_app.created_at.strftime("%Y-%m-%d %H:%M") if first_app.created_at else None,
            }

        matched_stack = [kw for kw in settings.stack_keywords if kw.lower() in f"{title}\n{desc}".lower()]

        verdict = _build_verdict(
            status_val=status_val,
            ai_score=v.ai_score,
            ai_reason=v.ai_reason,
            rule_res=rule_res,
            in_db=True,
            app_info=app_info,
        )

        return {
            "success": True,
            "in_database": True,
            "external_id": vacancy_id,
            "url": url,
            "title": title,
            "company": company_name,
            "salary": salary_str,
            "location": location,
            "status": status_val,
            "ai_score": v.ai_score,
            "ai_reason": v.ai_reason,
            "created_at": v.created_at.strftime("%Y-%m-%d %H:%M") if v.created_at else None,
            "matched_stack": matched_stack,
            "rule_analysis": rule_res,
            "application": app_info,
            "verdict": verdict,
        }

    # 2. Not in local DB - fetch from HH
    parser = HHParser()
    details = await parser.get_vacancy_details(f"https://hh.ru/vacancy/{vacancy_id}")

    if not details:
        return {
            "success": False,
            "in_database": False,
            "external_id": vacancy_id,
            "error": "Вакансия не найдена на hh.ru (возможно, она удалена или к ней закрыт доступ).",
        }

    salary_str = "Не указана"
    if details.salary_from and details.salary_to:
        salary_str = f"{details.salary_from:,} – {details.salary_to:,} {details.salary_currency or '₽'}".replace(
            ",", " "
        )
    elif details.salary_from:
        salary_str = f"от {details.salary_from:,} {details.salary_currency or '₽'}".replace(",", " ")
    elif details.salary_to:
        salary_str = f"до {details.salary_to:,} {details.salary_currency or '₽'}".replace(",", " ")

    location = details.location or ("Удаленно" if details.is_remote else "Не указана")

    rule_res = analyze_vacancy(
        title=details.title,
        description=details.description or "",
        skills=" ".join(details.skills or []),
        salary_from=details.salary_from,
        salary_to=details.salary_to,
        is_remote=details.is_remote,
        salary_currency=details.salary_currency or "RUR",
        desired_salary_min=settings.salary_floor,
    )
    rule_res["title"] = details.title

    matched_stack = [
        kw for kw in settings.stack_keywords if kw.lower() in f"{details.title}\n{details.description}".lower()
    ]

    verdict = _build_verdict(
        status_val="not_in_db",
        ai_score=None,
        ai_reason=None,
        rule_res=rule_res,
        in_db=False,
        app_info=None,
    )

    return {
        "success": True,
        "in_database": False,
        "external_id": vacancy_id,
        "url": details.url or f"https://hh.ru/vacancy/{vacancy_id}",
        "title": details.title,
        "company": details.company_name or "—",
        "salary": salary_str,
        "location": location,
        "status": "not_in_db",
        "ai_score": None,
        "ai_reason": None,
        "created_at": None,
        "matched_stack": matched_stack,
        "rule_analysis": rule_res,
        "application": None,
        "verdict": verdict,
    }
