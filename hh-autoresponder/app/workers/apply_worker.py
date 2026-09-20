import asyncio
import re
import structlog
from sqlalchemy import select, func, case
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import async_session
from app.models.vacancy import Vacancy, VacancyStatus
from app.models.application import Application, ApplicationStatus
from app.parsers.hh import HHParser
from app.utils.anti_detect import random_delay
from app.services.google_sheets import append_application

log = structlog.get_logger()


async def sync_applied_from_hh() -> int:
    """Fetch list of vacancies already applied to on hh.ru via API and
    mark them as APPLIED in DB so the bot doesn't waste time re-applying."""
    from app.parsers.hh_api import hh_api_client
    try:
        ids = await asyncio.wait_for(hh_api_client.fetch_applied_vacancy_ids(), timeout=30)
    except asyncio.TimeoutError:
        log.warning("sync_applied_timeout")
        return 0
    if not ids:
        return 0
    marked = 0
    async with async_session() as session:
        result = await session.execute(
            select(Vacancy).where(
                Vacancy.platform == "hh",
                Vacancy.external_id.in_(ids),
                Vacancy.status != VacancyStatus.APPLIED,
            )
        )
        for v in result.scalars().all():
            v.status = VacancyStatus.APPLIED
            marked += 1
        if marked:
            await session.commit()
    log.info("sync_applied_complete", marked=marked, fetched=len(ids))
    return marked


async def run_auto_apply(auto_mode: bool = False, min_score: float = 70):
    log.info("auto_apply_started", auto_mode=auto_mode, min_score=min_score)

    # Платформы на паузе (из scheduler_state.json) — для них пропускаем
    # выборку. Объединяем auto-pause (login_health) и manual-pause (юзер).
    paused_platforms: set[str] = set()
    pass_tests = True  # флаг «проходить тесты вакансий» (галочка в боте)
    ai_cover_letters = False
    humanize_letters = False
    limit_hh_dynamic = settings.max_applies_per_day_hh_max
    limit_habr_dynamic = settings.max_applies_per_day_habr_max
    try:
        import json as _json
        from pathlib import Path as _Path
        _sf = _Path("data/scheduler_state.json")
        if _sf.exists():
            _st = _json.loads(_sf.read_text())
            paused_platforms = set(_st.get("paused_platforms", []))
            paused_platforms |= set(_st.get("manual_paused_platforms", []))
            pass_tests = _st.get("pass_tests", True)
            ai_cover_letters = _st.get("ai_cover_letters", False)
            humanize_letters = _st.get("humanize_letters", False)
            limit_hh_dynamic = _st.get("max_applies_per_day_hh", settings.max_applies_per_day_hh_max)
            limit_habr_dynamic = _st.get("max_applies_per_day_habr", settings.max_applies_per_day_habr_max)
    except Exception as e:
        log.warning("read_paused_platforms_error", error=str(e))

    # Pre-sync from HH negotiations to skip already-applied vacancies (только если hh не на паузе)
    if "hh" not in paused_platforms:
        try:
            await sync_applied_from_hh()
        except Exception as e:
            log.warning("sync_applied_skip", error=str(e))
    applied = 0

    # Тиринг день/ночь (МСК):
    #  День 9–22 — откликаемся на ВСЁ реальное (score>=1), от высокого score
    #  к низкому (ORDER BY score DESC ниже задаёт порядок тиров
    #  100→80→60→40→30→20→15→…), чтобы добить дневной лимит до 200.
    #  Ночь 22–9 — только высокоценные (score>=50): на них реагируем сразу,
    #  остальное ждёт утра.
    #  score=0 (дисквалифицированные 1С/junior/qa/не-аналитик) не берём никогда.
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo as _ZI
    _hour = _dt.now(_ZI("Europe/Moscow")).hour
    _is_daytime = 9 <= _hour < 22
    effective_min_score = 1 if _is_daytime else 50
    log.info("apply_window", daytime=_is_daytime, min_score=effective_min_score)

    # Дневной лимит (hh и habr)
    platform_caps = {
        "hh": limit_hh_dynamic,
        "habr": limit_habr_dynamic,
    }
    # Платформы на паузе исключаем целиком
    for p in list(platform_caps.keys()):
        if p in paused_platforms:
            log.info("apply_skip_paused_platform", platform=p)
            del platform_caps[p]
    async with async_session() as session:
        today_rows = (await session.execute(
            select(Application.platform, func.count(Application.id))
            .where(
                Application.status == ApplicationStatus.SENT,
                func.date(Application.created_at) == func.current_date(),
            )
            .group_by(Application.platform)
        )).all()
        today_by_plat = {p: c for p, c in today_rows}

        remaining_by_plat: dict[str, int] = {}
        for plat, cap in platform_caps.items():
            done = today_by_plat.get(plat, 0)
            left = max(0, cap - done)
            if left > 0:
                remaining_by_plat[plat] = left

        if not remaining_by_plat:
            log.info("daily_limit_reached", today=today_by_plat)
            return 0

        # Берём одобренные вакансии по платформам с лимитом per-platform
        # Исключаем те, что уже падали 3+ раз (бессмысленно ретраить)
        from sqlalchemy import select as _select
        failed_3plus = _select(Application.vacancy_id).where(
            Application.status == ApplicationStatus.FAILED,
        ).group_by(Application.vacancy_id).having(func.count(Application.id) >= 3)

        # Приоритет формата: удалёнка (0) → гибрид (1) → офис/прочее (2).
        # Внутри формата — по убыванию score. Так сначала отрабатываем удалёнку.
        fmt_priority = case(
            (Vacancy.work_format == "remote", 0),
            (Vacancy.work_format == "hybrid", 1),
            else_=2,
        )
        all_vacs = []
        for plat, limit in remaining_by_plat.items():
            result = await session.execute(
                select(Vacancy)
                .options(joinedload(Vacancy.company))
                .where(
                    Vacancy.platform == plat,
                    Vacancy.status == VacancyStatus.APPROVED,
                    Vacancy.ai_score >= effective_min_score,
                    Vacancy.id.notin_(failed_3plus),
                )
                .order_by(fmt_priority, Vacancy.ai_score.desc())
                .limit(limit)
            )
            all_vacs.extend(result.scalars().all())
        # Mix platforms a bit: interleave
        vacancies = all_vacs

    # Письмо собирается из шаблона с вариациями (render_letter) под каждую
    # вакансию: каждое письмо чуть разное и упоминает название. Токены не
    # тратятся. AI-письмо включается только в Playwright-fallback для вакансий
    # с обязательным тестом/анкетой.
    from app.parsers.letter_template import render_letter
    STATIC_LETTER = render_letter()  # запасной вариант без названия

    # Глобальные ошибки (daily_limit, истёкший токен, нет резюме) одинаково
    # бьют по всем вакансиям платформы — нет смысла ретраить и засорять БД
    # фейлами. Прерываем платформу до следующего запуска.
    aborted_platforms: set[str] = set()
    GLOBAL_ERRORS = {"daily_limit", "auth_required", "auth_expired", "no_oauth_token", "no_resume_id"}

    from app.utils import notifier
    if vacancies:
        await notifier.vlog(
            f"🚀 <b>Цикл откликов</b>: в очереди {len(vacancies)} "
            f"(порог score ≥ {effective_min_score})"
        )

    for vacancy in vacancies:
        if vacancy.platform in aborted_platforms:
            continue
        try:
            if ai_cover_letters and settings.ai_enabled and settings.llm_api_key:
                from app.ai.claude import claude_ai
                cname = vacancy.company.name if vacancy.company else ""
                letter, _, _ = await claude_ai.generate_cover_letter(
                    vacancy_title=vacancy.title,
                    vacancy_description=vacancy.description or "",
                    company_name=cname,
                    humanize=humanize_letters
                )
            else:
                letter = render_letter(vacancy.title)

            # HH через Playwright (эмуляция браузера для обхода блокировок API)
            result = False
            skip_record = False  # True для глобальных ошибок — не пишем FAILED
            if vacancy.platform == "hh":
                parser = HHParser()
                try:
                    await asyncio.wait_for(parser.login(), timeout=60)
                    res = await asyncio.wait_for(
                        parser.apply_to_vacancy(vacancy.url, letter),
                        timeout=300,
                    )
                    result = res
                    
                    if res is not True and res != "already":
                        if res in GLOBAL_ERRORS:
                            log.warning(
                                "hh_apply_run_aborted",
                                reason=res,
                                vacancy_id=vacancy.id,
                            )
                            aborted_platforms.add(vacancy.platform)
                            skip_record = True
                        elif res == "needs_test" and not pass_tests:
                            log.info("hh_skip_test_disabled", vacancy_id=vacancy.id)
                            skip_record = True
                except asyncio.TimeoutError:
                    log.error("hh_playwright_timeout", vacancy_id=vacancy.id)
                    result = False
            elif vacancy.platform == "habr":
                from app.parsers.habr import HabrParser
                parser = HabrParser()
                try:
                    result = await asyncio.wait_for(
                        parser.apply_to_vacancy(vacancy.url, letter),
                        timeout=300,
                    )
                except asyncio.TimeoutError:
                    log.error("habr_apply_timeout", vacancy_id=vacancy.id)
                    result = False
                    
            if skip_record:
                # Глобальная ошибка платформы — не пишем фейк-FAILED, идём дальше.
                # Цикл пропустит остальные вакансии этой платформы через aborted_platforms.
                continue

            success = result is True  # True != "already"
            already = result == "already"

            # Записываем результат
            async with async_session() as session:
                if not already:
                    # Don't log application if already applied
                    app = Application(
                        vacancy_id=vacancy.id,
                        platform=vacancy.platform,
                        cover_letter=letter,
                        status=ApplicationStatus.SENT if success else ApplicationStatus.FAILED,
                        attempt_count=1,
                    )
                    session.add(app)

                v = await session.get(Vacancy, vacancy.id)
                if success:
                    v.status = VacancyStatus.APPLIED
                    applied += 1
                elif already:
                    v.status = VacancyStatus.APPLIED
                await session.commit()
                
                # Fetch date formatting
                from datetime import datetime
                from zoneinfo import ZoneInfo
                date_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
                
                # Append to Google Sheets if it's a new application attempt (not already applied)
                if not already:
                    company_name = vacancy.company.name if vacancy.company else ""
                    salary_str = ""
                    if vacancy.salary_from and vacancy.salary_to:
                        salary_str = f"{vacancy.salary_from} - {vacancy.salary_to} {vacancy.salary_currency}"
                    elif vacancy.salary_from:
                        salary_str = f"от {vacancy.salary_from} {vacancy.salary_currency}"
                    elif vacancy.salary_to:
                        salary_str = f"до {vacancy.salary_to} {vacancy.salary_currency}"
                        
                    asyncio.create_task(append_application(
                        date_str=date_str,
                        title=vacancy.title or "",
                        company=company_name,
                        url=vacancy.url or "",
                        status="Ждем ответа" if success else "Ошибка",
                        cover_letter=letter,
                        ai_score=vacancy.ai_score
                    ))

            log.info(
                "apply_result",
                vacancy_id=vacancy.id,
                platform=vacancy.platform,
                success=success,
            )

            # Детальный лог отклика в Telegram
            _plat_label = {"hh": "hh.ru", "habr": "Хабр Карьера"}.get(vacancy.platform, vacancy.platform)
            if success:
                _emoji, _word = "✅", "Отклик отправлен"
            elif already:
                _emoji, _word = "↩️", "Уже откликались"
            else:
                _emoji, _word = "❌", "Не удалось откликнуться"
            _score_str = f"{int(vacancy.ai_score)}%" if vacancy.ai_score is not None else "—"
            await notifier.vlog(
                f"{_emoji} <b>{_word}</b> · {_plat_label} · score {_score_str}\n"
                f"{(vacancy.title or '')[:90]}\n"
                f"{vacancy.url}"
            )

            # Пауза между откликами (антибан), из настроек.
            await random_delay(settings.apply_delay_min, settings.apply_delay_max)

        except Exception as e:
            log.error("apply_error", vacancy_id=vacancy.id, error=str(e))
            await notifier.vlog(
                f"❌ <b>Ошибка отклика</b>: {(vacancy.title or '')[:70]}\n{str(e)[:120]}"
            )
            async with async_session() as session:
                session.add(Application(
                    vacancy_id=vacancy.id,
                    platform=vacancy.platform,
                    status=ApplicationStatus.FAILED,
                    error_message=str(e),
                    attempt_count=1,
                ))
                await session.commit()

    log.info("auto_apply_complete", applied=applied)
    if vacancies:
        await notifier.vlog(f"🏁 <b>Цикл откликов завершён</b>: отправлено {applied}")
    return applied
