import asyncio
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


async def run_auto_apply(auto_mode: bool = False, min_score: float = 70, target_count: int | None = None):
    log.info("auto_apply_started", auto_mode=auto_mode, min_score=min_score, target_count=target_count)

    # Платформы на паузе (из scheduler_state.json) — для них пропускаем
    # выборку. Объединяем auto-pause (login_health) и manual-pause (юзер).
    paused_platforms: set[str] = set()
    pass_tests = True  # флаг «проходить тесты вакансий» (галочка в боте)
    ai_cover_letters = False
    humanize_letters = True
    limit_hh_dynamic = settings.max_applies_per_day_hh_max
    limit_habr_dynamic = settings.max_applies_per_day_habr_max
    cycle_target = target_count if target_count is not None else settings.applies_per_cycle

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
            humanize_letters = _st.get("humanize_letters", True)
            limit_hh_dynamic = _st.get("max_applies_per_day_hh", settings.max_applies_per_day_hh_max)
            limit_habr_dynamic = _st.get("max_applies_per_day_habr", settings.max_applies_per_day_habr_max)
            if target_count is None:
                cycle_target = _st.get("applies_per_cycle", settings.applies_per_cycle)
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
    effective_min_score = max(settings.score_threshold, 1) if _is_daytime else max(50, settings.score_threshold)
    log.info("apply_window", daytime=_is_daytime, min_score=effective_min_score, target=cycle_target)

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

    from app.parsers.letter_template import render_letter
    from app.utils import notifier
    from sqlalchemy import select as _select

    # Исключаем те, что уже падали 3+ раз (бессмысленно ретраить)
    failed_3plus = (
        _select(Application.vacancy_id)
        .where(
            Application.status == ApplicationStatus.FAILED,
        )
        .group_by(Application.vacancy_id)
        .having(func.count(Application.id) >= 3)
    )

    # Приоритет формата: удалёнка (0) → гибрид (1) → офис/прочее (2).
    # Внутри формата — по убыванию score. Так сначала отрабатываем удалёнку.
    fmt_priority = case(
        (Vacancy.work_format == "remote", 0),
        (Vacancy.work_format == "hybrid", 1),
        else_=2,
    )

    async with async_session() as session:
        queue_count = (
            await session.execute(
                select(func.count(Vacancy.id)).where(
                    Vacancy.platform.in_(list(platform_caps.keys())),
                    Vacancy.status == VacancyStatus.APPROVED,
                    Vacancy.ai_score >= effective_min_score,
                    Vacancy.id.notin_(failed_3plus),
                )
            )
        ).scalar() or 0

    target_desc = f"цель: {cycle_target}" if cycle_target > 0 else "цель: до дневного лимита"
    await notifier.vlog(
        f"🚀 <b>Цикл откликов</b> ({target_desc}): в очереди {queue_count} " f"(порог score ≥ {effective_min_score})"
    )

    aborted_platforms: set[str] = set()
    GLOBAL_ERRORS = {"daily_limit", "auth_required", "auth_expired", "no_oauth_token", "no_resume_id"}
    attempted_vacancy_ids: set[int] = set()
    replenish_searches_left = 1 if auto_mode else 0

    while True:
        if cycle_target > 0 and applied >= cycle_target:
            log.info("auto_apply_cycle_target_reached", applied=applied, target=cycle_target)
            break

        # Dynamic mid-cycle check for pause and limits
        try:
            import json as _json
            from pathlib import Path as _Path

            _sf = _Path("data/scheduler_state.json")
            if _sf.exists():
                _st = _json.loads(_sf.read_text())
                if _st.get("is_paused", False):
                    log.info("auto_apply_paused_mid_cycle")
                    break
                if not _st.get("auto_apply", False) and auto_mode:
                    log.info("auto_apply_disabled_mid_cycle")
                    break

                # Check if platforms were paused manually
                paused_plats = set(_st.get("paused_platforms", [])) | set(_st.get("manual_paused_platforms", []))
                paused_platforms.update(paused_plats)

                # Update dynamic limit
                platform_caps["hh"] = _st.get(
                    "max_applies_per_day_hh", platform_caps.get("hh", settings.max_applies_per_day_hh_max)
                )
                platform_caps["habr"] = _st.get(
                    "max_applies_per_day_habr", platform_caps.get("habr", settings.max_applies_per_day_habr_max)
                )

                # Update AI flags
                humanize_letters = _st.get("humanize_letters", True)
                ai_cover_letters = _st.get("ai_cover_letters", False)
                pass_tests = _st.get("pass_tests", True)
        except Exception:
            pass

        # Check daily limits per platform
        async with async_session() as session:
            today_rows = (
                await session.execute(
                    select(Application.platform, func.count(Application.id))
                    .where(
                        Application.status == ApplicationStatus.SENT,
                        func.date(Application.created_at) == func.current_date(),
                    )
                    .group_by(Application.platform)
                )
            ).all()
            today_by_plat = {p: c for p, c in today_rows}

            remaining_by_plat: dict[str, int] = {}
            for plat, cap in platform_caps.items():
                if plat in paused_platforms or plat in aborted_platforms:
                    continue
                left = max(0, cap - today_by_plat.get(plat, 0))
                if left > 0:
                    remaining_by_plat[plat] = left

        if not remaining_by_plat:
            log.info("daily_limit_reached", today=today_by_plat)
            break

        # Select next best approved vacancy
        async with async_session() as session:
            query = (
                select(Vacancy)
                .options(joinedload(Vacancy.company))
                .where(
                    Vacancy.platform.in_(list(remaining_by_plat.keys())),
                    Vacancy.status == VacancyStatus.APPROVED,
                    Vacancy.ai_score >= effective_min_score,
                    Vacancy.id.notin_(failed_3plus),
                )
            )
            if attempted_vacancy_ids:
                query = query.where(Vacancy.id.notin_(attempted_vacancy_ids))
            query = query.order_by(fmt_priority, Vacancy.ai_score.desc()).limit(1)
            vacancy = (await session.execute(query)).scalar_one_or_none()

        if not vacancy:
            if replenish_searches_left > 0:
                replenish_searches_left -= 1
                log.info("queue_empty_running_replenish")
                await notifier.vlog("🔍 В очереди закончились одобренные вакансии. Запускаю поиск и анализ...")
                try:
                    from app.workers.vacancy_worker import run_vacancy_search, run_vacancy_analysis

                    await run_vacancy_search()
                    await run_vacancy_analysis()
                except Exception as e:
                    log.error("replenish_search_error", error=str(e))
                continue
            else:
                log.info("no_more_approved_vacancies_available")
                break

        attempted_vacancy_ids.add(vacancy.id)

        try:
            letter = None
            letter_box = {"text": ""}
            async with async_session() as session:
                prev_app = (
                    await session.execute(
                        select(Application)
                        .where(Application.vacancy_id == vacancy.id)
                        .order_by(Application.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if prev_app and prev_app.cover_letter:
                    letter = prev_app.cover_letter

            if not letter:

                async def generate_letter():
                    if letter_box["text"]:
                        return letter_box["text"]
                    if ai_cover_letters and settings.ai_enabled and settings.llm_api_key:
                        from app.ai.claude import claude_ai

                        claude_ai.last_error = None
                        cname = vacancy.company.name if vacancy.company else ""
                        ai_letter, _, _ = await claude_ai.generate_cover_letter(
                            vacancy_title=vacancy.title,
                            vacancy_description=vacancy.description or "",
                            company_name=cname,
                            humanize=humanize_letters,
                        )
                        letter_box["text"] = ai_letter
                        return ai_letter
                    else:
                        text = render_letter(vacancy.title)
                        letter_box["text"] = text
                        return text

                letter = generate_letter

            # HH через Playwright (эмуляция браузера для обхода блокировок API)
            result = False
            skip_record = False  # True для глобальных ошибок — не пишем FAILED
            if vacancy.platform == "hh":
                parser = HHParser()
                try:
                    await asyncio.wait_for(parser.login(), timeout=60)
                    res = await asyncio.wait_for(
                        parser.apply_to_vacancy(vacancy.url, letter, pass_tests=pass_tests),
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
                            # Do NOT set skip_record = True — we record this vacancy as REJECTED
                            # and notify the user with a direct link, avoiding infinite loops.
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
                continue

            success = result is True  # True != "already"
            already = result == "already"
            needs_test_skipped = (result == "needs_test") and (not pass_tests)

            # Записываем результат
            final_letter = letter_box["text"] if callable(letter) else letter
            async with async_session() as session:
                if not already:
                    # Don't log application if already applied
                    app = Application(
                        vacancy_id=vacancy.id,
                        platform=vacancy.platform,
                        cover_letter=final_letter,
                        status=ApplicationStatus.SENT if success else ApplicationStatus.FAILED,
                        error_message="needs_test: авто-прохождение тестов отключено" if needs_test_skipped else None,
                        attempt_count=1,
                    )
                    session.add(app)

                v = await session.get(Vacancy, vacancy.id)
                if success:
                    v.status = VacancyStatus.APPLIED
                    applied += 1
                elif already:
                    v.status = VacancyStatus.APPLIED
                elif needs_test_skipped:
                    v.status = VacancyStatus.REJECTED
                    v.ai_reason = f"{v.ai_reason or ''} [Требуется тест/анкета, автотесты отключены]".strip()
                await session.commit()

            # Append to Google Sheets if it's a new application attempt (not already applied)
            if not already:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                date_str = datetime.now(ZoneInfo("Europe/Moscow")).strftime("%Y-%m-%d %H:%M:%S")
                company_name = vacancy.company.name if vacancy.company else ""
                salary_str = ""
                if vacancy.salary_from and vacancy.salary_to:
                    salary_str = f"{vacancy.salary_from} - {vacancy.salary_to} {vacancy.salary_currency}"
                elif vacancy.salary_from:
                    salary_str = f"от {vacancy.salary_from} {vacancy.salary_currency}"
                elif vacancy.salary_to:
                    salary_str = f"до {vacancy.salary_to} {vacancy.salary_currency}"

                sheets_status = (
                    "Ждем ответа" if success else ("Требуется тест (вручную)" if needs_test_skipped else "Ошибка")
                )

                await append_application(
                    date_str=date_str,
                    title=vacancy.title or "",
                    company=company_name,
                    url=vacancy.url or "",
                    status=sheets_status,
                    cover_letter=final_letter,
                    ai_score=vacancy.ai_score,
                    platform=vacancy.platform or "",
                    salary=salary_str,
                    vacancy_id=str(vacancy.external_id or ""),
                )

            log.info(
                "apply_result",
                vacancy_id=vacancy.id,
                platform=vacancy.platform,
                success=success,
                applied_so_far=applied,
                target=cycle_target,
            )

            # Детальный лог отклика в Telegram
            _plat_label = {"hh": "hh.ru", "habr": "Хабр Карьера"}.get(vacancy.platform, vacancy.platform)
            _score_str = f"{int(vacancy.ai_score)}%" if vacancy.ai_score is not None else "—"
            if success:
                _prog = f" [{applied}/{cycle_target}]" if cycle_target > 0 else f" [#{applied}]"
                _emoji, _word = "✅", f"Отклик отправлен{_prog}"
                await notifier.vlog(
                    f"{_emoji} <b>{_word}</b> · {_plat_label} · score {_score_str}\n"
                    f"{(vacancy.title or '')[:90]}\n"
                    f"{vacancy.url}"
                )
            elif already:
                _emoji, _word = "↩️", "Уже откликались"
                await notifier.vlog(
                    f"{_emoji} <b>{_word}</b> · {_plat_label} · score {_score_str}\n"
                    f"{(vacancy.title or '')[:90]}\n"
                    f"{vacancy.url}"
                )
            elif needs_test_skipped:
                company_name = vacancy.company.name if vacancy.company else ""
                await notifier.send(
                    f"📝 <b>Вакансия требует тест / анкету</b> · {_plat_label} · score {_score_str}\n"
                    f"<b>{(vacancy.title or '')[:90]}</b>\n"
                    f"{company_name}\n\n"
                    f"⚠️ Автопрохождение тестов выключено в настройках (<code>pass_tests=False</code>). "
                    f"Вакансия снята с авто-очереди бота, чтобы не зацикливать цикл откликов.\n\n"
                    f"👉 <b>Вы можете пройти тест и откликнуться вручную:</b>\n"
                    f"{vacancy.url}"
                )
            else:
                _emoji, _word = "❌", "Не удалось откликнуться"
                if isinstance(result, str) and result.startswith("error:"):
                    _word += f" ({result[6:].strip()})"
                await notifier.vlog(
                    f"{_emoji} <b>{_word}</b> · {_plat_label} · score {_score_str}\n"
                    f"{(vacancy.title or '')[:90]}\n"
                    f"{vacancy.url}"
                )

            # Пауза между откликами (антибан) только если цикл продолжается
            if cycle_target <= 0 or applied < cycle_target:
                if success:
                    await random_delay(settings.apply_delay_min, settings.apply_delay_max)
                else:
                    await random_delay(settings.min_delay_sec, settings.max_delay_sec)

        except Exception as e:
            log.error("apply_error", vacancy_id=vacancy.id, error=str(e))
            await notifier.vlog(f"❌ <b>Ошибка отклика</b>: {(vacancy.title or '')[:70]}\n{str(e)[:120]}")
            async with async_session() as session:
                session.add(
                    Application(
                        vacancy_id=vacancy.id,
                        platform=vacancy.platform,
                        status=ApplicationStatus.FAILED,
                        error_message=str(e),
                        attempt_count=1,
                    )
                )
                await session.commit()
            await random_delay(settings.min_delay_sec, settings.max_delay_sec)

    log.info("auto_apply_complete", applied=applied, target=cycle_target)
    await notifier.vlog(f"🏁 <b>Цикл откликов завершён</b>: успешно отправлено {applied}")
    return applied
