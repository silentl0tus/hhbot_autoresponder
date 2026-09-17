import json
import re

import structlog
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.models.vacancy import Vacancy, VacancyStatus
from app.models.company import Company
from app.models.blacklist import Blacklist
from app.parsers.base import ParsedVacancy
from app.parsers.hh import HHParser
from app.ai.rule_analyzer import analyze_vacancy as rule_analyze
from app.utils.anti_detect import random_delay

log = structlog.get_logger()

# Поисковые запросы задаются в .env (SEARCH_QUERIES_RAW), через запятую.
SEARCH_QUERIES = settings.search_queries


def _build_parsers() -> dict:
    """Активные площадки. В паблик-версии — только hh.ru."""
    return {"hh": HHParser()}


PARSERS = _build_parsers()


async def run_vacancy_search():
    log.info("vacancy_search_started")
    total_new = 0

    for platform_name, parser in PARSERS.items():
        try:
            logged_in = await parser.login()
            if not logged_in:
                log.warning("parser_login_failed", platform=platform_name)
                continue

            for query in SEARCH_QUERIES:
                try:
                    # remote=False → НЕ ставим фильтр schedule=remote, ищем ВСЁ:
                    # удалёнка, гибрид, офис, по всей России (по запросу пользователя).
                    vacancies = await parser.search_vacancies(
                        query,
                        remote=False,
                    )
                    saved = await _save_vacancies(vacancies)
                    total_new += saved
                    log.info("search_batch_done", platform=platform_name, query=query, new=saved)
                    await random_delay(5, 15)
                except Exception as e:
                    log.error("search_query_error", platform=platform_name, query=query, error=str(e))
                    continue

        except Exception as e:
            log.error("parser_error", platform=platform_name, error=str(e))

    log.info("vacancy_search_complete", total_new=total_new)
    if total_new:
        from app.utils import notifier
        await notifier.vlog(f"🔍 <b>Поиск</b>: найдено новых вакансий — {total_new}")
    return total_new


async def _save_vacancies(parsed: list[ParsedVacancy]) -> int:
    saved = 0
    async with async_session() as session:
        blacklisted = await _get_blacklist(session)

        for pv in parsed:
            # Дедупликация по external_id (стандартная)
            existing = await session.scalar(
                select(Vacancy.id).where(
                    Vacancy.platform == pv.platform,
                    Vacancy.external_id == pv.external_id,
                )
            )
            if existing:
                continue

            # Дедупликация по title + company: одна вакансия в N городах
            # = N записей с разными external_id. Оставляем только первую.
            if pv.company_name and pv.title:
                title_norm = re.sub(r'\s+', ' ', pv.title.strip().lower())
                company_norm = re.sub(r'\s+', ' ', pv.company_name.strip().lower())
                dup = await session.scalar(
                    select(Vacancy.id).where(
                        Vacancy.platform == pv.platform,
                        func.lower(func.trim(Vacancy.title)) == title_norm,
                    ).join(Company, Vacancy.company_id == Company.id).where(
                        func.lower(func.trim(Company.name)) == company_norm,
                    ).limit(1)
                )
                if dup:
                    log.debug("dedup_title_company", title=pv.title[:60], company=pv.company_name[:40])
                    continue

            # Чёрный список
            if _is_blacklisted(pv, blacklisted):
                continue

            # Гео-фильтр: только Москва/МО или удалёнка
            if not _is_geo_allowed(pv):
                log.debug("geo_filtered", title=pv.title, location=pv.location)
                continue

            # Компания
            company = None
            if pv.company_name:
                company = await session.scalar(
                    select(Company).where(
                        Company.name == pv.company_name,
                        Company.platform == pv.platform,
                    )
                )
                if not company:
                    company = Company(
                        name=pv.company_name,
                        url=pv.company_url,
                        platform=pv.platform,
                    )
                    session.add(company)
                    await session.flush()

                if company.is_blacklisted:
                    continue

            vacancy = Vacancy(
                platform=pv.platform,
                external_id=pv.external_id,
                url=pv.url,
                title=pv.title,
                description=pv.description,
                salary_from=pv.salary_from,
                salary_to=pv.salary_to,
                salary_currency=pv.salary_currency,
                location=pv.location,
                is_remote=pv.is_remote,
                experience=pv.experience,
                employment_type=pv.employment_type,
                skills=json.dumps(pv.skills, ensure_ascii=False) if pv.skills else None,
                company_id=company.id if company else None,
                status=VacancyStatus.NEW,
            )
            session.add(vacancy)
            saved += 1

        await session.commit()
    return saved


async def _get_blacklist(session: AsyncSession) -> dict[str, set[str]]:
    result = await session.execute(select(Blacklist))
    items = result.scalars().all()
    bl: dict[str, set[str]] = {"company": set(), "keyword": set(), "vacancy": set()}
    for item in items:
        bl.setdefault(item.entry_type, set()).add(item.value.lower())
    return bl


def _is_blacklisted(pv: ParsedVacancy, blacklist: dict[str, set[str]]) -> bool:
    if pv.company_name.lower() in blacklist.get("company", set()):
        return True
    if pv.external_id in blacklist.get("vacancy", set()):
        return True
    title_lower = pv.title.lower()
    for kw in blacklist.get("keyword", set()):
        if kw in title_lower:
            return True
    return False


def _is_geo_allowed(pv: ParsedVacancy) -> bool:
    """Фильтр по геолокации.

    Правила:
    - Если geo_filter_enabled=False — пропускаем все.
    - Если вакансия полностью удалённая (is_remote=True или слово удалён / remote в location) — пропускаем.
    - Если location пустой — пропускаем (нет данных — риск отсека нужной вакансии).
    - Иначе location должно содержать хотя бы одну из allowed_regions.
    """
    if not settings.geo_filter_enabled:
        return True

    loc = (pv.location or "").lower()

    # Полная удалёнка — принимаем всегда
    if pv.is_remote:
        return True
    if "удалён" in loc or "удален" in loc or "remote" in loc:
        return True

    # Пустой location — не отсеиваем
    if not loc:
        return True

    # Проверяем разрешённые регионы
    for region in settings.allowed_regions:
        if region.lower() in loc:
            return True

    return False


async def run_vacancy_analysis():
    log.info("vacancy_analysis_started")
    analyzed = 0
    desc_loaded = 0
    scored: list[tuple[str, int]] = []  # (title, score) для лога в TG

    # Парсер для подгрузки описания вакансий
    detail_parser = HHParser()

    async with async_session() as session:
        result = await session.execute(
            select(Vacancy)
            .where(Vacancy.status == VacancyStatus.NEW)
            .order_by(Vacancy.created_at.desc())
            .limit(300)
        )
        vacancies = result.scalars().all()

    for vacancy in vacancies:
        try:
            # Шаг 1: Предварительный скоринг по заголовку (быстро, без сети)
            pre_analysis = rule_analyze(
                title=vacancy.title,
                description="",
                skills=vacancy.skills or "",
                salary_from=vacancy.salary_from,
                salary_to=vacancy.salary_to,
                is_remote=bool(vacancy.is_remote),
                salary_currency=vacancy.salary_currency or "",
                desired_salary_min=settings.desired_salary_min,
                desired_salary_max=settings.desired_salary_max,
            )
            pre_score = pre_analysis.get("score", 0)

            # Шаг 2: Если заголовок прошёл (score > 0) и описания нет —
            # подгружаем описание через HH API для точного stack-скоринга.
            description = vacancy.description or ""
            skills_str = vacancy.skills or ""
            if pre_score > 0 and not description and vacancy.url:
                try:
                    details = await detail_parser.get_vacancy_details(vacancy.url)
                    if details:
                        description = details.description or ""
                        if details.skills:
                            skills_str = json.dumps(details.skills, ensure_ascii=False)
                        # Сохраняем описание в БД чтобы не подгружать повторно
                        async with async_session() as session:
                            v = await session.get(Vacancy, vacancy.id)
                            if v:
                                v.description = description
                                if details.skills:
                                    v.skills = skills_str
                                if details.experience:
                                    v.experience = details.experience
                                await session.commit()
                        desc_loaded += 1
                        await random_delay(2, 5)
                except Exception as e:
                    log.warning("desc_load_error", vacancy_id=vacancy.id, error=str(e)[:120])

            # Шаг 3: Финальный скоринг с описанием (stack_keywords заработают)
            analysis = rule_analyze(
                title=vacancy.title,
                description=description,
                skills=skills_str,
                salary_from=vacancy.salary_from,
                salary_to=vacancy.salary_to,
                is_remote=bool(vacancy.is_remote),
                salary_currency=vacancy.salary_currency or "",
                desired_salary_min=settings.desired_salary_min,
                desired_salary_max=settings.desired_salary_max,
            )

            # Формат работы для приоритета откликов: удалёнка → гибрид → офис
            _fmt = f"{vacancy.title or ''} {description}".lower()
            if bool(vacancy.is_remote) or "удалён" in _fmt or "удален" in _fmt or "remote" in _fmt:
                _work_format = "remote"
            elif "гибрид" in _fmt or "hybrid" in _fmt:
                _work_format = "hybrid"
            else:
                _work_format = "office"

            async with async_session() as session:
                v = await session.get(Vacancy, vacancy.id)
                v.ai_score = analysis.get("score", 0)
                v.ai_reason = analysis.get("reason", "")
                v.work_format = _work_format
                v.status = VacancyStatus.ANALYZED

                score = analysis.get("score", 0)

                # Применяем порог: если score ниже минимума — пропускаем.
                # SCORE_THRESHOLD=0 в .env отключает порог (откликаться на всё).
                if score <= 0 or (settings.score_threshold > 0 and score < settings.score_threshold):
                    v.status = VacancyStatus.REJECTED
                    v.ai_reason = (v.ai_reason or "") + f" [порог {settings.score_threshold}]"
                else:
                    v.status = VacancyStatus.APPROVED

                await session.commit()

            analyzed += 1
            scored.append((vacancy.title or "", int(analysis.get("score", 0))))

        except Exception as e:
            log.error("vacancy_analysis_error", vacancy_id=vacancy.id, error=str(e))

    log.info("vacancy_analysis_complete", analyzed=analyzed, desc_loaded=desc_loaded)
    if analyzed:
        from app.utils import notifier
        lines = [f"🧠 <b>Анализ</b>: оценено вакансий — {analyzed} (описаний загружено: {desc_loaded})"]
        for title, sc in sorted(scored, key=lambda x: -x[1])[:8]:
            lines.append(f"  • {sc} — {title[:55]}")
        await notifier.vlog("\n".join(lines))
    return analyzed
