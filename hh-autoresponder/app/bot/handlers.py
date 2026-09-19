import asyncio
import json
import functools
import structlog

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.config import settings, save_env_variable
from app.database import async_session
from app.models.vacancy import Vacancy, VacancyStatus
from app.models.application import Application, ApplicationStatus
from app.models.blacklist import Blacklist
from app.models.message import RecruiterMessage
from app.ai.claude import claude_ai, clean_screener_answer
from app.bot.keyboards import (
    main_menu,
    vacancy_keyboard,
    vacancy_list_keyboard,
    message_keyboard,
    confirm_apply_keyboard,
    settings_keyboard,
    clear_neg_keyboard,
    behavior_keyboard,
    limits_keyboard,
    stats_keyboard,
    ai_models_keyboard,
    screener_card_keyboard,
    screener_menu_keyboard,
)
from app.parsers.max_screener import max_screener

router = Router()
log = structlog.get_logger()

PAGE_SIZE = 5

_scheduler = None


def set_scheduler(scheduler):
    global _scheduler
    _scheduler = scheduler


def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(event, **kwargs):
        chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
        if str(chat_id) != settings.tg_admin_chat_id:
            return
        return await fn(event, **kwargs)
    return wrapper


def _company_name(vacancy) -> str:
    if vacancy.company and vacancy.company.name:
        return vacancy.company.name
    return ""

class ManualCoverLetter(StatesGroup):
    waiting_for_url_or_text = State()


class MaxScreenerSG(StatesGroup):
    waiting_edited_answer = State()


_screener_state = {
    "question": "",
    "suggested_answer": "",
    "is_monitoring": False,
    "waiting_for_user_action": False,
    "chat_id": None,
}
_screener_task: asyncio.Task | None = None




# ══════════════════════════════════════════════════════════════
#  КОМАНДЫ И КНОПКИ МЕНЮ
# ══════════════════════════════════════════════════════════════

@router.message(Command("start"))
@admin_only
async def cmd_start(message: Message, **kw):
    await message.answer(
        "👋 <b>Job Hunter Bot v1.2</b>\n\n"
        "Автоматический поиск вакансий и отклики на hh.ru\n"
        "Используй кнопки ниже 👇",
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


@router.message(F.text == "📊 Статистика")
@router.message(Command("stats"))
@admin_only
async def btn_stats(message: Message, **kw):
    async with async_session() as session:
        # By-platform vacancy counts
        platform_rows = (await session.execute(
            select(Vacancy.platform, func.count(Vacancy.id))
            .group_by(Vacancy.platform)
        )).all()
        platform_vac = {p: c for p, c in platform_rows}

        # By-platform application counts (today + total sent)
        app_today_rows = (await session.execute(
            select(Application.platform, func.count(Application.id))
            .where(
                Application.status == ApplicationStatus.SENT,
                func.date(Application.created_at) == func.current_date(),
            )
            .group_by(Application.platform)
        )).all()
        app_today = {p: c for p, c in app_today_rows}

        app_total_rows = (await session.execute(
            select(Application.platform, func.count(Application.id))
            .where(Application.status == ApplicationStatus.SENT)
            .group_by(Application.platform)
        )).all()
        app_total = {p: c for p, c in app_total_rows}

        failed_today = await session.scalar(
            select(func.count(Application.id)).where(
                Application.status == ApplicationStatus.FAILED,
                func.date(Application.created_at) == func.current_date(),
            )
        ) or 0

        new = await session.scalar(
            select(func.count(Vacancy.id)).where(Vacancy.status == VacancyStatus.NEW)
        ) or 0
        analyzed = await session.scalar(
            select(func.count(Vacancy.id)).where(Vacancy.status == VacancyStatus.ANALYZED)
        ) or 0
        approved = await session.scalar(
            select(func.count(Vacancy.id)).where(Vacancy.status == VacancyStatus.APPROVED)
        ) or 0

        # Recruiter messages by platform
        msg_rows = (await session.execute(
            select(RecruiterMessage.platform, func.count(RecruiterMessage.id))
            .group_by(RecruiterMessage.platform)
        )).all()
        msg_by_plat = {p: c for p, c in msg_rows}

        avg_score = await session.scalar(
            select(func.avg(Vacancy.ai_score)).where(Vacancy.ai_score.is_not(None))
        )

    score_text = f"{avg_score:.0f}" if avg_score else "—"

    PLATFORMS = [
        ("hh", "hh.ru", _scheduler.max_applies_per_day_hh if _scheduler else settings.max_applies_per_day_hh_max),
        ("habr", "Хабр Карьера", getattr(_scheduler, "max_applies_per_day_habr", settings.max_applies_per_day_habr_max) if _scheduler else settings.max_applies_per_day_habr_max),
    ]
    by_plat_lines = []
    for code, label, cap in PLATFORMS:
        v = platform_vac.get(code, 0)
        t = app_today.get(code, 0)
        tt = app_total.get(code, 0)
        m = msg_by_plat.get(code, 0)
        if cap == 0 and v == 0 and tt == 0:
            by_plat_lines.append(f"<b>{label}</b> — (отключено)")
            continue
        cap_txt = f"/{cap}" if cap else ""
        by_plat_lines.append(
            f"<b>{label}</b>\n"
            f"  📦 Вакансий в БД: {v}\n"
            f"  📨 Отклики сегодня: <b>{t}{cap_txt}</b>\n"
            f"  📨 Откликов всего: {tt}\n"
            f"  💬 Сообщений рекрутеров: {m}"
        )

    total_vac = sum(platform_vac.values())
    total_today = sum(app_today.values())
    total_all = sum(app_total.values())
    total_cap = sum([cap for _, _, cap in PLATFORMS])

    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"📦 Всего вакансий: <b>{total_vac}</b>\n"
        f"🆕 Новые: <b>{new}</b>\n"
        f"🤖 Проанализировано: <b>{analyzed}</b>\n"
        f"⭐ Одобрено AI: <b>{approved}</b>\n"
        f"📈 Средний AI-скор: <b>{score_text}</b>\n\n"
        f"📨 <b>Отклики (всего):</b>\n"
        f"  • Сегодня: <b>{total_today}/{total_cap}</b>\n"
        f"  • Ошибок сегодня: <b>{failed_today}</b>\n"
        f"  • Всего отправлено: <b>{total_all}</b>\n\n"
        "🏷 <b>По платформам:</b>\n\n"
        + "\n\n".join(by_plat_lines),
        parse_mode="HTML",
        reply_markup=stats_keyboard(),
    )


@router.message(F.text == "🔍 Вакансии")
@router.message(Command("vacancies"))
@admin_only
async def btn_vacancies(message: Message, **kw):
    await _send_vacancy_page(message, page=0)


@router.message(F.text == "⭐ Топ вакансии")
@admin_only
async def btn_top(message: Message, **kw):
    await _send_vacancy_page(message, page=0, top_only=True)


@router.message(F.text == "📝 Создать сопроводительное")
@admin_only
async def btn_manual_cover(message: Message, state: FSMContext, **kw):
    await message.answer("Отправьте ссылку на вакансию (hh.ru) или вставьте текст описания вакансии:")
    await state.set_state(ManualCoverLetter.waiting_for_url_or_text)


@router.message(ManualCoverLetter.waiting_for_url_or_text)
@admin_only
async def process_manual_cover(message: Message, state: FSMContext, **kw):
    await state.clear()
    text = message.text.strip()
    
    if text.startswith("http"):
        await message.answer("🔄 Загружаю вакансию по ссылке...")
        from app.parsers.hh import HHParser
        parser = HHParser()
        vacancy = await parser.get_vacancy_details(text)
        if not vacancy:
            await message.answer("❌ Не удалось получить данные по ссылке.")
            return
        
        title = vacancy.title
        description = vacancy.description
        company = vacancy.company_name
    else:
        lines = text.split("\n", 1)
        title = lines[0]
        description = text
        company = ""

    await message.answer("⏳ Генерирую сопроводительное письмо...")
    
    try:
        cover_text, _, _ = await claude_ai.generate_cover_letter(
            vacancy_title=title,
            vacancy_description=description,
            company_name=company,
            humanize=settings.humanize_letters
        )
        
        if claude_ai.last_error:
            await message.answer(
                f"⚠️ <b>Ошибка LLM API:</b>\n<code>{claude_ai.last_error}</code>\n\n"
                f"📝 Использован шаблон по умолчанию:\n\n{cover_text}",
                parse_mode="HTML"
            )
        elif cover_text:
            await message.answer(f"✅ <b>Готово:</b>\n\n{cover_text}", parse_mode="HTML")
        else:
            err = claude_ai.last_error or "LLM вернула пустой ответ"
            await message.answer(f"❌ <b>Ошибка при генерации письма:</b>\n<code>{err}</code>", parse_mode="HTML")
    except Exception as e:
        log.error("manual_cover_error", error=str(e))
        await message.answer(f"❌ <b>Ошибка при генерации письма:</b>\n<code>{str(e)}</code>", parse_mode="HTML")


@router.message(F.text == "📩 Сообщения")
@router.message(Command("messages"))
@admin_only
async def btn_messages(message: Message, **kw):
    import html as _html
    await message.answer("🔄 Проверяю приглашения на hh.ru...")
    from app.parsers.hh_oauth import hh_oauth
    statuses = await hh_oauth.negotiations_status()

    if not statuses:
        await message.answer("📭 Нет активных откликов")
        return

    invites = [s for s in statuses if s.get("tab") == "invitations"]
    discards = [s for s in statuses if s.get("tab") == "discard"]
    pending = [s for s in statuses if s.get("tab") == "pending"]

    header = (
        "📩 <b>Приглашения от работодателей</b>\n"
        f"🎉 Приглашений: <b>{len(invites)}</b>  •  ❌ Отказы: {len(discards)}  •  "
        f"⏳ Без ответа: {len(pending)}"
    )

    if not invites:
        await message.answer(
            header + "\n\nПока никто не позвал. Как появится приглашение — покажу здесь.",
            parse_mode="HTML",
        )
        return

    # Показываем сами приглашения (компания + вакансия), новые сверху.
    lines = [header, "\n<b>Кто позвал:</b>"]
    for s in invites[-25:][::-1]:
        company = _html.escape((s.get("company") or "").strip() or "—")
        title = _html.escape((s.get("title") or "").strip() or "вакансия")
        lines.append(f"• <b>{company}</b> — {title}")
    if len(invites) > 25:
        lines.append(f"…и ещё {len(invites) - 25}. Полная переписка — в чатах на hh.ru.")

    # Подгружаем последние сообщения с Хабра из локальной БД
    from app.database import async_session
    from app.models.message import RecruiterMessage
    from sqlalchemy import select, desc
    
    habr_lines = []
    try:
        async with async_session() as session:
            recent_habr = await session.scalars(
                select(RecruiterMessage)
                .where(RecruiterMessage.platform == "habr")
                .order_by(desc(RecruiterMessage.created_at))
                .limit(10)
            )
            recent_habr = recent_habr.all()
            
            if recent_habr:
                habr_lines.append("\n🔵 <b>Хабр Карьера (последние сообщения):</b>")
                for m in recent_habr:
                    company = _html.escape(m.sender_company or m.sender_name or "Неизвестно")
                    text = _html.escape((m.text or "").replace("\n", " ")[:100])
                    habr_lines.append(f"• <b>{company}</b>: {text}...")
    except Exception as e:
        log.warning("habr_messages_fetch_error", error=str(e))

    text = "\n".join(lines + habr_lines)
    if len(text) > 3900:
        text = text[:3900] + "\n…"
    await message.answer(text, parse_mode="HTML")


def _settings_text(paused: bool, auto: bool, limit: int = 0) -> str:
    status_pause = "⏸ Пауза" if paused else "▶️ Работает"
    status_auto = "🟢 Авто-отклик ВКЛ" if auto else "⚪ Авто-отклик ВЫКЛ"
    return f"""⚙️ <b>Настройки</b>

📍 Позиция: {settings.desired_position}
💰 Зарплата: {settings.desired_salary_min:,}–{settings.desired_salary_max:,}
⏱ Интервал поиска: {settings.check_interval_sec // 60} мин
🎯 Лимит откликов/день (на сегодня): <b>{limit or settings.max_applies_per_day_hh_max}</b>
⏱ Задержка между откликами: {settings.apply_delay_min}–{settings.apply_delay_max} сек
⌨️ Скорость печати: {settings.type_delay_min}–{settings.type_delay_max} мс/символ
🔔 Уведомления: {settings.notify_hour_start}:00–{settings.notify_hour_end}:00 МСК

{status_pause} | {status_auto}"""


@router.message(F.text == "⚙️ Настройки")
@router.message(Command("settings"))
@admin_only
async def btn_settings(message: Message, **kw):
    paused = _scheduler.is_paused if _scheduler else False
    auto = _scheduler.auto_apply if _scheduler else False
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    plats = _scheduler.manual_paused_platforms if _scheduler else set()
    await message.answer(
        _settings_text(paused, auto, limit),
        parse_mode="HTML",
        reply_markup=settings_keyboard(paused, auto, limit, plats),
    )


@router.message(F.text == "📋 Логи")
@router.message(Command("logs"))
@admin_only
async def btn_logs(message: Message, **kw):
    enabled = ["hh"]
    async with async_session() as session:
        result = await session.execute(
            select(Application)
            .where(Application.platform.in_(enabled))
            .order_by(Application.created_at.desc())
            .limit(10)
        )
        apps = result.scalars().all()

    if not apps:
        await message.answer("📋 Пока нет записей")
        return

    lines = []
    for a in apps:
        emoji = {"sent": "✅", "failed": "❌", "pending": "⏳"}.get(a.status.value, "❓")
        lines.append(f"{emoji} [{a.platform}] ID:{a.vacancy_id} — {a.status.value}")

    await message.answer(
        "📋 <b>Последние отклики</b>\n\n" + "\n".join(lines),
        parse_mode="HTML",
    )


@router.message(Command("blacklist"))
@admin_only
async def cmd_blacklist(message: Message, **kw):
    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        async with async_session() as session:
            result = await session.execute(select(Blacklist).limit(20))
            items = result.scalars().all()

        if not items:
            await message.answer("🚫 Чёрный список пуст\n\nДобавить: /blacklist <company|keyword> <значение>")
            return

        lines = [f"• [{b.entry_type}] {b.value}" for b in items]
        await message.answer("🚫 <b>Чёрный список:</b>\n\n" + "\n".join(lines), parse_mode="HTML")
        return

    entry_type = args[1] if args[1] in ("company", "keyword", "vacancy") else "keyword"
    value = args[2] if len(args) > 2 else args[1]

    async with async_session() as session:
        session.add(Blacklist(entry_type=entry_type, value=value))
        await session.commit()

    await message.answer(f"✅ Добавлено в ЧС: [{entry_type}] {value}")


@router.message(Command("pause"))
@admin_only
async def cmd_pause(message: Message, **kw):
    if _scheduler:
        _scheduler.pause()
    await message.answer("⏸ Пауза. /resume — возобновить", reply_markup=main_menu())


@router.message(Command("resume"))
@admin_only
async def cmd_resume(message: Message, **kw):
    if _scheduler:
        _scheduler.resume()
    await message.answer("▶️ Возобновлено", reply_markup=main_menu())


@router.message(Command("balance"))
@admin_only
async def cmd_balance(message: Message, **kw):
    await _send_balance(message)


async def _fetch_balance(base_url: str, api_key: str) -> dict | None:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url}/v1/balance",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if resp.status_code != 200:
                return None
            return resp.json()
    except Exception:
        return None


# Providers that don't expose /v1/balance — only dashboard
_DASHBOARD_URLS = {
    "api.tonwave.dev": "https://tonwave.dev/dashboard",
    "waveapi.tonvarex.ru": "https://wave.tonvarex.ru/dashboard",
}


def _provider_name(base_url: str) -> str:
    if "tonwave" in base_url:
        return "TonWave"
    if "tonvarex" in base_url or "waveapi" in base_url:
        return "WaveAPI"
    return base_url


def _dashboard_for(base_url: str) -> str | None:
    for host, url in _DASHBOARD_URLS.items():
        if host in base_url:
            return url
    return None


def _format_provider(label: str, base_url: str, data: dict | None) -> str:
    name = _provider_name(base_url)
    dash = _dashboard_for(base_url)
    if not data:
        if dash:
            return f"<b>{label} — {name}</b>\n  ℹ️ Баланс через API недоступен.\n  🔗 <a href=\"{dash}\">Открыть дашборд</a>"
        return f"<b>{label} — {name}</b>\n  ❌ нет ответа от {base_url}"
    balance = data.get("balance_cents", 0)
    inp = data.get("total_input_tokens", 0)
    out = data.get("total_output_tokens", 0)
    total = data.get("total_tokens_used", 0)
    return (
        f"<b>{label} — {name}</b>\n"
        f"  💰 {balance} центов (${balance/100:.2f})\n"
        f"  📥 in: <b>{inp:,}</b>\n"
        f"  📤 out: <b>{out:,}</b>\n"
        f"  📊 total: <b>{total:,}</b>"
    )


class AISettingsSG(StatesGroup):
    waiting_for_key = State()
    waiting_for_url = State()
    waiting_for_proxy = State()
    waiting_for_model = State()


def _mask_key(key: str) -> str:
    if not key:
        return "<i>Не задан</i>"
    if len(key) <= 10:
        return "***"
    return f"<code>{key[:7]}...{key[-5:]}</code>"


async def _send_balance(target):
    """Показать состояние AI, активную модель и кнопки полного управления настройками."""
    key_masked = _mask_key(settings.llm_api_key)
    status_str = "🟢 Включён" if (settings.ai_enabled and settings.llm_api_key) else "🔴 Выключен"
    proxy_str = f"<code>{settings.llm_proxy}</code>" if settings.llm_proxy else "<i>Прямое (без прокси)</i>"

    gemini_k = _mask_key(settings.gemini_api_key)
    openrouter_k = _mask_key(settings.openrouter_api_key)

    is_openrouter = "openrouter" in settings.llm_base_url
    if is_openrouter:
        models_info = "• <code>deepseek/deepseek-v4-flash-0731:free</code> — ⚡️ 100% Free (DeepSeek)"
    else:
        models_info = (
            "• <code>gemini-3.6-flash</code> — ⚡️ Основная Flash (Google)\n"
            "• <code>gemini-3.8-flash</code> — 🚀 Новейшая Flash (Google)\n"
            "• <code>gemini-3.5-flash</code> — 🔹 Быстрая Flash (Google)"
        )

    text = (
        "💎 <b>Настройка и Статус AI (LLM)</b>\n\n"
        f"⚡️ <b>Статус:</b> {status_str}\n"
        f"📌 <b>Активная модель:</b> <code>{settings.llm_model}</code>\n"
        f"🌐 <b>Base URL:</b> <code>{settings.llm_base_url}</code>\n"
        f"🔑 <b>Активный API-ключ:</b> {key_masked}\n"
        f"🛡 <b>Прокси:</b> {proxy_str}\n\n"
        "💾 <b>Сохранённые ключи провайдеров:</b>\n"
        f"• 🌐 Google Gemini: {gemini_k}\n"
        f"• 🚀 OpenRouter: {openrouter_k}\n\n"
        f"📊 <b>Модели ({'OpenRouter' if is_openrouter else 'Gemini'}):</b>\n"
        f"{models_info}\n\n"
        "👇 <b>Управление настройками:</b>"
    )
    reply_kb = ai_models_keyboard(settings.llm_model, ai_enabled=settings.ai_enabled, is_openrouter=is_openrouter)

    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_kb)
            except Exception:
                await target.message.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_kb)
        else:
            await target.answer(text, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=reply_kb)


@router.callback_query(F.data == "ai_toggle")
@admin_only
async def cb_ai_toggle(callback: CallbackQuery, **kw):
    settings.ai_enabled = not settings.ai_enabled
    save_env_variable("AI_ENABLED", str(settings.ai_enabled).lower())
    st = "🟢 AI включён" if settings.ai_enabled else "🔴 AI выключен"
    await callback.answer(st)
    await _send_balance(callback)


@router.callback_query(F.data.startswith("ai_preset:"))
@admin_only
async def cb_ai_preset(callback: CallbackQuery, **kw):
    preset = callback.data.split(":", 1)[1]
    if preset == "gemini":
        settings.llm_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
        settings.llm_model = "gemini-3.6-flash"
        save_env_variable("LLM_BASE_URL", settings.llm_base_url)
        save_env_variable("LLM_MODEL", settings.llm_model)

        if settings.gemini_api_key:
            settings.llm_api_key = settings.gemini_api_key
            save_env_variable("LLM_API_KEY", settings.gemini_api_key)
            msg_text = "✅ Установлен пресет Google Gemini (ключ Gemini применён)!"
        else:
            msg_text = "✅ Установлен пресет Google Gemini! Задайте API-ключ через кнопку."

        try:
            from pathlib import Path
            import json
            sf = Path("data/scheduler_state.json")
            st = json.loads(sf.read_text()) if sf.exists() else {}
            st["selected_llm_model"] = settings.llm_model
            sf.write_text(json.dumps(st))
        except Exception:
            pass

        claude_ai.reinit_client()
        await callback.answer(msg_text, show_alert=True)
    elif preset == "openrouter":
        settings.llm_base_url = "https://openrouter.ai/api/v1"
        settings.llm_model = "deepseek/deepseek-v4-flash-0731:free"
        save_env_variable("LLM_BASE_URL", settings.llm_base_url)
        save_env_variable("LLM_MODEL", settings.llm_model)

        if settings.openrouter_api_key:
            settings.llm_api_key = settings.openrouter_api_key
            save_env_variable("LLM_API_KEY", settings.openrouter_api_key)
            msg_text = "✅ Установлен пресет OpenRouter (ключ OpenRouter применён)!"
        else:
            msg_text = "✅ Установлен пресет OpenRouter! Задайте API-ключ через кнопку."

        try:
            from pathlib import Path
            import json
            sf = Path("data/scheduler_state.json")
            st = json.loads(sf.read_text()) if sf.exists() else {}
            st["selected_llm_model"] = settings.llm_model
            sf.write_text(json.dumps(st))
        except Exception:
            pass

        claude_ai.reinit_client()
        await callback.answer(msg_text, show_alert=True)
    else:
        await callback.answer("Неизвестный пресет")
    await _send_balance(callback)


@router.callback_query(F.data == "ai_test_conn")
@admin_only
async def cb_ai_test_conn(callback: CallbackQuery, **kw):
    await callback.answer("⏳ Проверяю связь с AI...")
    ok, msg = await claude_ai.test_connection()
    if ok:
        await callback.message.answer(
            f"✅ <b>Связь с AI успешна!</b>\n\n"
            f"📌 Модель: <code>{settings.llm_model}</code>\n"
            f"🌐 Провайдер: <code>{settings.llm_base_url}</code>\n"
            f"💬 Ответ: <i>{msg}</i>",
            parse_mode="HTML",
        )
    else:
        await callback.message.answer(
            f"❌ <b>Ошибка связи с AI!</b>\n\n"
            f"📌 Модель: <code>{settings.llm_model}</code>\n"
            f"🌐 Провайдер: <code>{settings.llm_base_url}</code>\n"
            f"⚠️ Ошибка:\n<code>{msg}</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith("ai_edit:"))
@admin_only
async def cb_ai_edit(callback: CallbackQuery, state: FSMContext, **kw):
    action = callback.data.split(":", 1)[1]
    await callback.answer()
    if action == "key":
        await state.set_state(AISettingsSG.waiting_for_key)
        await callback.message.answer(
            "🔑 <b>Смена API-ключа LLM</b>\n\n"
            f"Текущий ключ: {_mask_key(settings.llm_api_key)}\n\n"
            "Пришлите новый API-ключ сообщением в чат (например <code>sk-or-v1-...</code> или <code>AIzaSy...</code>).\n\n"
            "Для отмены отправьте /cancel",
            parse_mode="HTML",
        )
    elif action == "url":
        await state.set_state(AISettingsSG.waiting_for_url)
        await callback.message.answer(
            "🌐 <b>Смена Base URL (провайдера)</b>\n\n"
            f"Текущий URL: <code>{settings.llm_base_url}</code>\n\n"
            "Примеры:\n"
            "• <code>https://openrouter.ai/api/v1</code>\n"
            "• <code>https://generativelanguage.googleapis.com/v1beta/openai</code>\n"
            "• <code>https://api.polza.ai/api/v1</code>\n\n"
            "Пришлите новый Base URL в чат или /cancel для отмены.",
            parse_mode="HTML",
        )
    elif action == "proxy":
        await state.set_state(AISettingsSG.waiting_for_proxy)
        cur = settings.llm_proxy or "Не задан (прямое подключение)"
        await callback.message.answer(
            "🛡 <b>Настройка прокси для LLM</b>\n\n"
            f"Текущий прокси: <code>{cur}</code>\n\n"
            "Используется для обхода гео-блокировок LLM провайдеров.\n"
            "Форматы:\n"
            "• <code>http://user:pass@host:port</code>\n"
            "• <code>socks5://user:pass@host:port</code>\n"
            "• Отправьте <code>none</code>, чтобы отключить прокси.\n\n"
            "Пришлите адрес прокси в чат или /cancel для отмены.",
            parse_mode="HTML",
        )
    elif action == "model":
        await state.set_state(AISettingsSG.waiting_for_model)
        await callback.message.answer(
            "✏️ <b>Ввод названия модели</b>\n\n"
            f"Текущая модель: <code>{settings.llm_model}</code>\n\n"
            "Примеры:\n"
            "• <code>deepseek/deepseek-v4-flash-0731:free</code>\n"
            "• <code>google/gemini-2.0-flash-001</code>\n"
            "• <code>gemini-3.6-flash</code>\n\n"
            "Пришлите точное название модели в чат или /cancel для отмены.",
            parse_mode="HTML",
        )


@router.message(AISettingsSG.waiting_for_key)
@admin_only
async def msg_ai_key(message: Message, state: FSMContext, **kw):
    key = (message.text or "").strip()
    if not key or len(key) < 5:
        await message.answer("Слишком короткий ключ. Пришлите валидный API-ключ или /cancel.")
        return
    settings.llm_api_key = key
    settings.ai_enabled = True
    save_env_variable("LLM_API_KEY", key)
    save_env_variable("AI_ENABLED", "true")

    if key.startswith("sk-or-") or "openrouter" in settings.llm_base_url:
        settings.openrouter_api_key = key
        save_env_variable("OPENROUTER_API_KEY", key)
        provider_hint = " (сохранён для OpenRouter)"
    elif key.startswith("AIza") or key.startswith("AQ.") or "google" in settings.llm_base_url:
        settings.gemini_api_key = key
        save_env_variable("GEMINI_API_KEY", key)
        provider_hint = " (сохранён для Google Gemini)"
    else:
        provider_hint = ""

    claude_ai.reinit_client()
    await state.clear()
    await message.answer(f"✅ API-ключ сохранён{provider_hint} и AI активирован!", parse_mode="HTML")
    await _send_balance(message)


@router.message(AISettingsSG.waiting_for_url)
@admin_only
async def msg_ai_url(message: Message, state: FSMContext, **kw):
    url = (message.text or "").strip().rstrip("/")
    if not url.startswith("http"):
        await message.answer("URL должен начинаться с http:// или https://. Попробуйте снова или /cancel.")
        return
    settings.llm_base_url = url
    save_env_variable("LLM_BASE_URL", url)
    claude_ai.reinit_client()
    await state.clear()
    await message.answer(f"✅ Base URL обновлён на <code>{url}</code>!", parse_mode="HTML")
    await _send_balance(message)


@router.message(AISettingsSG.waiting_for_proxy)
@admin_only
async def msg_ai_proxy(message: Message, state: FSMContext, **kw):
    val = (message.text or "").strip()
    if val.lower() in ("none", "off", "0", "нет", "выкл"):
        settings.llm_proxy = ""
        save_env_variable("LLM_PROXY", "")
        claude_ai.reinit_client()
        await state.clear()
        await message.answer("✅ Прокси для LLM отключён (используется прямое подключение).")
        await _send_balance(message)
        return

    if not (val.startswith("http://") or val.startswith("https://") or val.startswith("socks5://")):
        await message.answer("Прокси должен начинаться с http://, https:// или socks5://. Отправьте адрес или /cancel.")
        return

    settings.llm_proxy = val
    save_env_variable("LLM_PROXY", val)
    claude_ai.reinit_client()
    await state.clear()
    await message.answer("✅ Прокси для LLM сохранён и применён!", parse_mode="HTML")
    await _send_balance(message)


@router.message(AISettingsSG.waiting_for_model)
@admin_only
async def msg_ai_model(message: Message, state: FSMContext, **kw):
    val = (message.text or "").strip()
    if not val:
        await message.answer("Название модели не может быть пустым. Попробуйте снова или /cancel.")
        return
    claude_ai.set_model(val)
    await state.clear()
    await message.answer(f"✅ Модель переключена на <code>{val}</code>!", parse_mode="HTML")
    await _send_balance(message)


@router.callback_query(F.data.startswith("set_model:"))
@admin_only
async def cb_set_model(callback: CallbackQuery, **kw):
    model_name = callback.data.split(":", 1)[1]
    claude_ai.set_model(model_name)

    # Сохраняем в scheduler_state.json
    try:
        from pathlib import Path
        import json
        sf = Path("data/scheduler_state.json")
        st = json.loads(sf.read_text()) if sf.exists() else {}
        st["selected_llm_model"] = model_name
        sf.parent.mkdir(parents=True, exist_ok=True)
        sf.write_text(json.dumps(st))
    except Exception as e:
        log.warning("save_selected_model_error", error=str(e))

    await callback.answer(f"✅ Модель AI переключена на {model_name}!", show_alert=True)
    await _send_balance(callback)



# ══════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════

async def _send_vacancy_page(target, page: int = 0, top_only: bool = False):
    async with async_session() as session:
        base_filter = Vacancy.status.in_([VacancyStatus.NEW, VacancyStatus.ANALYZED, VacancyStatus.APPROVED])

        count_q = select(func.count(Vacancy.id)).where(base_filter)
        if top_only:
            count_q = count_q.where(Vacancy.ai_score >= 60)
        total = await session.scalar(count_q) or 0

        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, total_pages - 1)

        query = (
            select(Vacancy)
            .options(selectinload(Vacancy.company))
            .where(base_filter)
        )
        if top_only:
            query = query.where(Vacancy.ai_score >= 60)

        query = query.order_by(Vacancy.ai_score.desc().nullslast(), Vacancy.created_at.desc())
        result = await session.execute(query.offset(page * PAGE_SIZE).limit(PAGE_SIZE))
        vacancies = result.scalars().all()

    if not vacancies:
        label = "⭐ топ-вакансий" if top_only else "🔍 вакансий"
        if isinstance(target, CallbackQuery):
            await target.message.edit_text(f"Нет {label}")
            await target.answer()
        else:
            await target.answer(f"Нет {label}")
        return

    lines = []
    ids = []
    for i, v in enumerate(vacancies):
        num = page * PAGE_SIZE + i + 1
        salary = ""
        if v.salary_from or v.salary_to:
            parts = []
            if v.salary_from:
                parts.append(f"от {v.salary_from:,}")
            if v.salary_to:
                parts.append(f"до {v.salary_to:,}")
            salary = f" | 💰 {' '.join(parts)} {v.salary_currency or ''}"

        score = f" | 🤖 {v.ai_score:.0f}" if v.ai_score else ""
        remote = " 🏠" if v.is_remote else ""
        cname = _company_name(v)
        company = f"\n   🏢 {cname}" if cname else ""

        lines.append(
            f"<b>{num}. {v.title}</b>{remote}{company}"
            f"\n   📍 {v.location or '—'}{salary}{score}"
            f"\n   🔗 <a href='{v.url}'>Открыть</a>"
        )
        ids.append(v.id)

    header = "⭐ <b>Топ вакансии</b>" if top_only else "🔍 <b>Вакансии</b>"
    prefix = "top_" if top_only else ""
    text = f"{header} ({total} шт.)\n\n" + "\n\n".join(lines)
    kb = vacancy_list_keyboard(ids, page, total_pages, prefix)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        await target.answer()
    else:
        await target.answer(text, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════
#  CALLBACK-ХЭНДЛЕРЫ
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data.startswith("page:"))
@admin_only
async def cb_page(callback: CallbackQuery, **kw):
    page = int(callback.data.split(":")[1])
    await _send_vacancy_page(callback, page=page)


@router.callback_query(F.data.startswith("top_page:"))
@admin_only
async def cb_top_page(callback: CallbackQuery, **kw):
    page = int(callback.data.split(":")[1])
    await _send_vacancy_page(callback, page=page, top_only=True)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery, **kw):
    await callback.answer()


@router.callback_query(F.data.startswith("apply:"))
@admin_only
async def cb_apply(callback: CallbackQuery, **kw):
    vacancy_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        vacancy = await session.get(Vacancy, vacancy_id)
        if not vacancy:
            await callback.answer("Вакансия не найдена")
            return
        title = vacancy.title
        desc = vacancy.description or ""

    await callback.answer("🤖 Генерирую письмо...")

    humanize = _scheduler.humanize_letters if _scheduler else False
    letter, _, _ = await claude_ai.generate_cover_letter(title, desc, "", humanize=humanize)

    await callback.message.answer(
        letter,
        reply_markup=confirm_apply_keyboard(vacancy_id),
    )


@router.callback_query(F.data.startswith("confirm_apply:"))
@admin_only
async def cb_confirm_apply(callback: CallbackQuery, **kw):
    vacancy_id = int(callback.data.split(":")[1])

    async with async_session() as session:
        vacancy = await session.get(Vacancy, vacancy_id)
        if not vacancy:
            await callback.answer("Вакансия не найдена")
            return

    # Check if Playwright is available
    from app.parsers.hh import HHParser
    parser = HHParser()
    pw = parser._get_playwright()
    if not pw:
        await callback.answer("❌ Playwright не доступен (только на VPS)")
        return

    await callback.answer("📨 Отправляю отклик...")

    # Get the cover letter from the previous message
    cover_letter = ""
    if callback.message and callback.message.reply_to_message:
        cover_letter = callback.message.reply_to_message.text or ""
    elif callback.message:
        # Extract letter from the message text
        text = callback.message.text or ""
        if "\n\n" in text:
            parts = text.split("\n\n", 2)
            if len(parts) > 1:
                cover_letter = parts[-1]

    result = await parser.apply_to_vacancy(vacancy.url, cover_letter)

    from pathlib import Path
    from aiogram.types import FSInputFile

    if result == "already":
        # Vacancy already had a response (from before or some other source)
        async with async_session() as session:
            v = await session.get(Vacancy, vacancy_id)
            if v:
                v.status = VacancyStatus.APPLIED
                await session.commit()
        await callback.message.answer(
            "ℹ️ На эту вакансию уже есть отклик (новый не отправлен).\n"
            "Возможно, ты откликался раньше с этого аккаунта."
        )
        p = Path("data/debug_already_applied.png")
        if p.exists():
            try:
                await callback.message.answer_photo(FSInputFile(p), caption="🖼 Что видит бот")
            except Exception:
                pass
    elif result:
        async with async_session() as session:
            v = await session.get(Vacancy, vacancy_id)
            if v:
                v.status = VacancyStatus.APPLIED
                from app.models.application import Application, ApplicationStatus
                session.add(Application(
                    vacancy_id=vacancy_id,
                    platform=v.platform,
                    cover_letter=cover_letter,
                    status=ApplicationStatus.SENT,
                    attempt_count=1,
                ))
                await session.commit()
        await callback.message.answer("✅ Отклик отправлен!")
    else:
        await callback.message.answer("❌ Не удалось отправить отклик")
        for name in ("debug_apply_fail.png", "debug_apply_timeout.png", "debug_apply_no_btn.png"):
            p = Path(f"data/{name}")
            if p.exists():
                try:
                    await callback.message.answer_photo(FSInputFile(p), caption=f"🖼 {name}")
                except Exception:
                    pass


@router.callback_query(F.data.startswith("skip:"))
@admin_only
async def cb_skip(callback: CallbackQuery, **kw):
    vacancy_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        vacancy = await session.get(Vacancy, vacancy_id)
        if vacancy:
            vacancy.status = VacancyStatus.REJECTED
            await session.commit()
    await callback.answer("❌ Пропущена")


@router.callback_query(F.data.startswith("details:"))
@admin_only
async def cb_details(callback: CallbackQuery, **kw):
    vacancy_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        vacancy = await session.get(Vacancy, vacancy_id, options=[selectinload(Vacancy.company)])
        if not vacancy:
            await callback.answer("Не найдена")
            return

        desc = vacancy.description or "Описание не загружено"
        if len(desc) > 3000:
            desc = desc[:3000] + "..."

        ai_info = ""
        if vacancy.ai_score is not None:
            ai_info = f"\n\n🤖 <b>AI-скор: {vacancy.ai_score:.0f}/100</b>\n{vacancy.ai_reason or '—'}"

        salary = ""
        if vacancy.salary_from or vacancy.salary_to:
            parts = []
            if vacancy.salary_from:
                parts.append(f"от {vacancy.salary_from:,}")
            if vacancy.salary_to:
                parts.append(f"до {vacancy.salary_to:,}")
            salary = f"\n💰 {' '.join(parts)} {vacancy.salary_currency or ''}"

        cname = _company_name(vacancy)
        company = f"\n🏢 {cname}" if cname else ""

    await callback.message.answer(
        f"<b>{vacancy.title}</b>{company}{salary}{ai_info}\n\n"
        f"{desc}\n\n"
        f"🔗 <a href='{vacancy.url}'>Открыть</a>",
        parse_mode="HTML",
        reply_markup=vacancy_keyboard(vacancy_id),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("blacklist:"))
@admin_only
async def cb_blacklist(callback: CallbackQuery, **kw):
    vacancy_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        vacancy = await session.get(Vacancy, vacancy_id)
        if vacancy:
            vacancy.status = VacancyStatus.REJECTED
            session.add(Blacklist(entry_type="vacancy", value=str(vacancy.external_id), reason="Manual blacklist"))
            await session.commit()
    await callback.answer("🚫 В чёрном списке")


@router.callback_query(F.data.startswith("ai_reply:"))
@admin_only
async def cb_ai_reply(callback: CallbackQuery, **kw):
    msg_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        msg = await session.get(RecruiterMessage, msg_id)
        if not msg:
            await callback.answer("Не найдено")
            return
        msg_text = msg.text

    await callback.answer("🤖 Генерирую ответ...")
    async with async_session() as session:
        m = await session.get(RecruiterMessage, msg_id)
        plat = m.platform if m else ""
    reply, _, _ = await claude_ai.generate_reply(msg_text, platform=plat)

    async with async_session() as session:
        msg = await session.get(RecruiterMessage, msg_id)
        if msg:
            msg.ai_suggested_reply = reply
            await session.commit()

    await callback.message.answer(f"🤖 <b>AI-ответ:</b>\n\n{reply}", parse_mode="HTML")


@router.callback_query(F.data.startswith("mark_read:"))
@admin_only
async def cb_mark_read(callback: CallbackQuery, **kw):
    msg_id = int(callback.data.split(":")[1])
    async with async_session() as session:
        msg = await session.get(RecruiterMessage, msg_id)
        if msg:
            msg.is_read = True
            await session.commit()
    await callback.answer("✅ Прочитано")
    await callback.message.delete()


@router.callback_query(F.data == "toggle_pause")
@admin_only
async def cb_toggle_pause(callback: CallbackQuery, **kw):
    if not _scheduler:
        await callback.answer("Scheduler не найден")
        return
    if _scheduler.is_paused:
        _scheduler.resume()
        await callback.answer("▶️ Возобновлено")
    else:
        _scheduler.pause()
        await callback.answer("⏸ На паузе")
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    plats = _scheduler.manual_paused_platforms if _scheduler else set()
    await callback.message.edit_text(
        _settings_text(_scheduler.is_paused, _scheduler.auto_apply, limit),
        parse_mode="HTML",
        reply_markup=settings_keyboard(_scheduler.is_paused, _scheduler.auto_apply, limit, plats),
    )


@router.callback_query(F.data.startswith("toggle_plat:"))
@admin_only
async def cb_toggle_plat(callback: CallbackQuery, **kw):
    if not _scheduler:
        await callback.answer("Scheduler не найден")
        return
    plat = callback.data.split(":")[1]
    
    if plat in _scheduler.manual_paused_platforms:
        _scheduler.manual_paused_platforms.remove(plat)
        await callback.answer(f"▶️ Платформа {plat} включена")
    else:
        _scheduler.manual_paused_platforms.add(plat)
        await callback.answer(f"⏸ Платформа {plat} отключена")
        
    _scheduler._save_state()
    
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    plats = _scheduler.manual_paused_platforms
    await callback.message.edit_reply_markup(
        reply_markup=settings_keyboard(_scheduler.is_paused, _scheduler.auto_apply, limit, plats)
    )


@router.callback_query(F.data == "toggle_auto")
@admin_only
async def cb_toggle_auto(callback: CallbackQuery, **kw):
    if not _scheduler:
        await callback.answer("Scheduler не найден")
        return
    _scheduler.set_auto_apply(not _scheduler.auto_apply)
    status = "🟢 ВКЛ" if _scheduler.auto_apply else "⚪ ВЫКЛ"
    await callback.answer(f"Авто-отклик: {status}")
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    await callback.message.edit_text(
        _settings_text(_scheduler.is_paused, _scheduler.auto_apply, limit),
        parse_mode="HTML",
        reply_markup=settings_keyboard(_scheduler.is_paused, _scheduler.auto_apply, limit),
    )


@router.callback_query(F.data == "force_search")
@admin_only
async def cb_force_search(callback: CallbackQuery, **kw):
    await callback.answer("🔄 Запускаю поиск...")
    from app.workers.vacancy_worker import run_vacancy_search
    count = await run_vacancy_search()
    await callback.message.answer(f"🔍 Найдено <b>{count}</b> новых вакансий", parse_mode="HTML")


@router.callback_query(F.data == "show_balance")
@admin_only
async def cb_show_balance(callback: CallbackQuery, **kw):
    await _send_balance(callback)


@router.callback_query(F.data == "bump_resume")
@admin_only
async def cb_bump_resume(callback: CallbackQuery, **kw):
    await callback.answer("⬆️ Поднимаю резюме...")
    from app.parsers.hh_oauth import hh_oauth
    res = await hh_oauth.bump_resumes()
    if res.get("error") == "no_oauth_token":
        await callback.message.answer(
            "❌ Нет токена hh API. Сначала войди: /login."
        )
        return
    if res.get("error"):
        await callback.message.answer(f"❌ Не получилось поднять резюме: {res['error']}")
        return
    bumped = res.get("bumped", 0)
    blocked = res.get("blocked", 0)
    if bumped > 0:
        titles = res.get("titles") or []
        lst = "\n".join(f"• {t}" for t in titles)
        await callback.message.answer(f"✅ Поднято резюме: {bumped}\n{lst}")
    elif blocked > 0:
        await callback.message.answer(
            f"ℹ️ Пока нельзя поднять ({blocked} шт). hh разрешает раз в 4 часа, попробуй позже."
        )
    else:
        await callback.message.answer("ℹ️ Резюме не найдены в аккаунте hh.")


_BEHAVIOR_DEFAULTS = {
    "auto_apply": False, "pass_tests": True, "ai_cover_letters": False,
    "humanize_letters": False, "notify_messages": True, 
    "thank_rejections": True, "bump_resume": True,
}


@router.callback_query(F.data == "behavior_menu")
@admin_only
async def cb_behavior_menu(callback: CallbackQuery, **kw):
    await callback.answer()
    flags = _scheduler.get_flags() if _scheduler else dict(_BEHAVIOR_DEFAULTS)
    await callback.message.answer(
        "🎛 <b>Настройка функций</b>\n\n"
        "Нажми на пункт, чтобы включить (✅) или выключить (⬜️):\n"
        "• <b>Авто-отклики</b> — сам откликается на вакансии\n"
        "• <b>Проходить тесты</b> — AI отвечает на вопросы/тесты работодателя\n"
        "• <b>Писать письма через AI</b> — ИИ генерирует текст под вакансию (тратит токены)\n"
        "• <b>Гуманизатор текста (Анти-ИИ)</b> — второй проход нейросети (detectai) для маскировки ИИ-штампов\n"
        "• <b>Сообщать о рекрутёрах</b> — уведомления о реальных ответах (приглашения, интервью)\n"
        "• <b>Говорить спасибо за отказ</b> — авто-сообщение спасибо при отказе\n"
        "• <b>Поднимать резюме</b> — авто-поднятие резюме каждые 4 часа",
        parse_mode="HTML",
        reply_markup=behavior_keyboard(flags),
    )


@router.callback_query(F.data.startswith("bflag:"))
@admin_only
async def cb_bflag(callback: CallbackQuery, **kw):
    name = callback.data.split(":", 1)[1]
    if not _scheduler:
        await callback.answer("Планировщик ещё не готов", show_alert=True)
        return
    cur = bool(getattr(_scheduler, name, True))
    _scheduler.set_flag(name, not cur)
    await callback.answer("Включено" if not cur else "Выключено")
    try:
        await callback.message.edit_reply_markup(reply_markup=behavior_keyboard(_scheduler.get_flags()))
    except Exception:
        pass



@router.callback_query(F.data == "clear_neg")
@admin_only
async def cb_clear_neg_menu(callback: CallbackQuery, **kw):
    await callback.answer()
    await callback.message.answer(
        "🧹 <b>Очистка откликов на hh.ru</b>\n\n"
        "Что убрать:\n"
        "• <b>Отказы</b> — отклики, где работодатель уже ответил отказом\n"
        "• <b>Старше N дней</b> — старые отклики без ответа\n\n"
        "Идёт через официальный API, отклики просто скрываются из списка.",
        parse_mode="HTML",
        reply_markup=clear_neg_keyboard(),
    )


@router.callback_query(F.data.startswith("clearneg:"))
@admin_only
async def cb_clear_neg_run(callback: CallbackQuery, **kw):
    mode = callback.data.split(":", 1)[1]
    from app.parsers.hh_oauth import hh_oauth

    if mode == "discard":
        await callback.answer("🚫 Убираю отказы...")
        res = await hh_oauth.clear_negotiations(older_than_days=None)
        title = "Отказы"
    elif mode == "old14":
        await callback.answer("🗓 Чищу старше 14 дней...")
        res = await hh_oauth.clear_negotiations(older_than_days=14)
        title = "Старше 14 дней"
    elif mode == "old30":
        await callback.answer("🗓 Чищу старше 30 дней...")
        res = await hh_oauth.clear_negotiations(older_than_days=30)
        title = "Старше 30 дней"
    elif mode == "dry":
        await callback.answer("👀 Смотрю что попадёт под отказы...")
        res = await hh_oauth.clear_negotiations(older_than_days=None, dry_run=True)
        title = "Предпросмотр (отказы)"
    else:
        await callback.answer("Неизвестный режим")
        return

    if res.get("error") == "no_oauth_token":
        await callback.message.answer(
            "❌ Нет токена hh API. Сначала войди через OAuth (тест-отклик или /login)."
        )
        return

    verb = "Под удаление попадёт" if mode == "dry" else "Убрано"
    text = (
        f"✅ <b>{title}</b>\n"
        f"Просмотрено откликов: {res.get('scanned', 0)}\n"
        f"{verb}: <b>{res.get('deleted', 0)}</b>"
    )
    names = res.get("names") or []
    if names:
        listed = "\n".join(f"• {n}" for n in names[:15])
        more = f"\n…и ещё {len(names) - 15}" if len(names) > 15 else ""
        text += f"\n\n{listed}{more}"
    await callback.message.answer(text, parse_mode="HTML")


@router.callback_query(F.data == "thank_rejections")
@admin_only
async def cb_thank_rejections(callback: CallbackQuery, **kw):
    await callback.answer("💬 Отправляю благодарности...")
    from app.workers.message_worker import process_rejection_thanks
    count = await process_rejection_thanks(max_count=3)
    await callback.message.answer(f"Отправлено сообщений: {count}")
    # Always send diagnostic screenshots so we can see what hh.ru showed
    from pathlib import Path
    from aiogram.types import FSInputFile
    for name in (
        "debug_thanks_step1_home.png",
        "debug_thanks_step2_no_activator.png",
        "debug_thanks_step2_widget_open.png",
        "debug_thanks_step3_no_chats.png",
        "debug_thanks_step3_chat_open.png",
        "debug_thanks_step3_no_input.png",
        "debug_thanks_step4_filled.png",
        "debug_thanks_step5_no_send_btn.png",
        "debug_thanks_step6_after_send.png",
        "debug_thanks_overall_error.png",
    ):
        p = Path(f"data/{name}")
        if p.exists():
            try:
                await callback.message.answer_photo(FSInputFile(p), caption=name[6:-4])
            except Exception:
                pass


@router.callback_query(F.data.startswith("cancel_apply:"))
@admin_only
async def cb_cancel_apply(callback: CallbackQuery, **kw):
    await callback.answer("Отменено")
    await callback.message.delete()


# ══════════════════════════════════════════════════════════════
#  PLAYWRIGHT / HH.RU LOGIN
# ══════════════════════════════════════════════════════════════

class LoginSG(StatesGroup):
    phone = State()
    code = State()


@router.message(Command("login"))
@admin_only
async def cmd_login(message: Message, state: FSMContext, **kw):
    """Вход на hh.ru по одноразовому коду (телефон → код)."""
    await state.clear()
    default = settings.hh_login or ""
    hint = (
        f"\n\nЛогин из настроек: <code>{default}</code> — можешь прислать его же."
        if default else ""
    )
    await message.answer(
        "🔐 <b>Вход на hh.ru по коду</b>\n\n"
        "Пришли номер телефона, привязанный к hh (например <code>+79991234567</code>). "
        "hh отправит код, его потом введёшь здесь." + hint
        + "\n\nОтмена: /cancel",
        parse_mode="HTML",
    )
    await state.set_state(LoginSG.phone)


@router.message(Command("cancel"))
@admin_only
async def cmd_cancel(message: Message, state: FSMContext, **kw):
    from app.parsers.hh_login import drop_session
    await drop_session(message.chat.id)
    await state.clear()
    await message.answer("Отменено.")


@router.message(LoginSG.phone)
@admin_only
async def login_phone(message: Message, state: FSMContext, **kw):
    phone = (message.text or "").strip()
    if not phone or len(phone) < 5:
        await message.answer("Не похоже на номер. Пришли телефон ещё раз или /cancel.")
        return
    await message.answer("⏳ Открываю вход на hh и запрашиваю код...")
    from app.parsers.hh_login import OTPLoginSession, set_session
    sess = OTPLoginSession()
    res = await sess.start(phone)
    if res.get("status") == "code_sent":
        set_session(message.chat.id, sess)
        await state.set_state(LoginSG.code)
        await message.answer("📩 hh отправил код (SMS или почта). Пришли его сюда одним сообщением.")
    elif res.get("status") == "captcha":
        from pathlib import Path
        from aiogram.types import FSInputFile
        p = Path("data/hh_login_captcha.png")
        await sess.cancel()
        await state.clear()
        if p.exists():
            await message.answer_photo(
                FSInputFile(p),
                caption="hh просит капчу — автоматом сейчас не пройти. Попробуй /login чуть позже.",
            )
        else:
            await message.answer("hh просит капчу. Попробуй /login позже.")
    else:
        await sess.cancel()
        await state.clear()
        await message.answer(
            f"❌ Не удалось начать вход: {res.get('error')}\nПопробуй /login ещё раз."
        )


@router.message(LoginSG.code)
@admin_only
async def login_code(message: Message, state: FSMContext, **kw):
    code = (message.text or "").strip()
    from app.parsers.hh_login import get_session, drop_session
    sess = get_session(message.chat.id)
    if not sess:
        await state.clear()
        await message.answer("Сессия входа потеряна. Начни заново: /login")
        return
    await message.answer("⏳ Проверяю код...")
    res = await sess.submit_code(code)
    await drop_session(message.chat.id)
    await state.clear()
    if res.get("status") == "ok":
        await message.answer(
            "✅ Вход выполнен. Токен hh и браузерная сессия обновлены.\n"
            "Теперь работают отклики, прохождение тестов и поднятие резюме."
        )
    else:
        await message.answer(
            f"❌ Код не подошёл: {res.get('error')}\nПопробуй /login заново."
        )


@router.message(Command("test_apply"))
@admin_only
async def cmd_test_apply(message: Message, **kw):
    """Run N test applies on hh with full screenshots in TG.
    Usage: /test_apply [count]   default 10
    """
    parts = (message.text or "").split()
    n = 10
    if len(parts) > 1:
        try:
            n = max(1, min(int(parts[1]), 20))
        except ValueError:
            pass

    await message.answer(f"🧪 Запускаю тест-отклики hh: {n} штук со скриншотами. Это займёт ~{n*2} мин.")

    async with async_session() as session:
        result = await session.execute(
            select(Vacancy)
            .options(selectinload(Vacancy.company))
            .where(
                Vacancy.platform == "hh",
                Vacancy.status == VacancyStatus.APPROVED,
                Vacancy.ai_score >= 70,
            )
            .order_by(Vacancy.ai_score.desc())
            .limit(n)
        )
        vacancies = result.scalars().all()

    if not vacancies:
        await message.answer("❌ Нет одобренных вакансий hh для теста")
        return

    from app.parsers.hh_oauth import hh_oauth
    from app.parsers.hh_api import hh_api_client
    from app.ai.claude import claude_ai
    import asyncio as _async
    import re as _re
    from app.utils.anti_detect import random_delay
    from app.models.application import Application, ApplicationStatus

    # Pre-sync applied list so we don't re-try the same ones
    from app.workers.apply_worker import sync_applied_from_hh
    marked = await sync_applied_from_hh()
    if marked:
        await message.answer(f"🔄 Помечено уже-откликнутых: {marked}. Беру новые.")

    # Verify OAuth token works
    token = await hh_oauth.get_token()
    if not token:
        await message.answer("❌ Не удалось получить OAuth токен. Нужен VNC-логин в hh.")
        return

    stats = {"sent": 0, "already": 0, "failed": 0}
    for i, v in enumerate(vacancies, 1):
        tag = f"{i:02d}"
        title = (v.title or "")[:60]
        company = _company_name(v) or "—"

        await message.answer(f"<b>[{tag}]</b> {title}\n🏢 {company}\n🤖 Генерирую письмо...", parse_mode="HTML")

        try:
            humanize = _scheduler.humanize_letters if _scheduler else False
            letter, _, _ = await claude_ai.generate_cover_letter(v.title, v.description or "", humanize=humanize)
        except Exception as e:
            await message.answer(f"❌ AI ошибка: {e}")
            stats["failed"] += 1
            continue

        m_id = _re.search(r"/vacancy/(\d+)", v.url)
        vid = m_id.group(1) if m_id else v.external_id
        try:
            res, info = await _async.wait_for(hh_oauth.apply(vid, letter), timeout=20)
        except _async.TimeoutError:
            res, info = False, {"error": "timeout"}

        # Fallback to Playwright for vacancies requiring questionnaire
        if res is False and (info or {}).get("error") == "needs_test":
            await message.answer(f"📋 <b>[{tag}]</b> Опросник — переключаюсь на Playwright…", parse_mode="HTML")
            try:
                humanize = _scheduler.humanize_letters if _scheduler else False
                ai_letter, _, _ = await claude_ai.generate_cover_letter(v.title, v.description or "", humanize=humanize)
            except Exception:
                ai_letter = letter
            from app.parsers.hh import HHParser
            pw_parser = HHParser()
            try:
                await _async.wait_for(pw_parser.login(), timeout=60)
                res = await _async.wait_for(
                    pw_parser.apply_to_vacancy(v.url, ai_letter, screenshot_name=tag),
                    timeout=300,
                )
                info = {"path": "playwright", "result": str(res)}
            except _async.TimeoutError:
                res = False
                info = {"error": "playwright_timeout"}

        status_emoji = "✅" if res is True else ("ℹ️" if res == "already" else "❌")
        result_label = {True: "ОТПРАВЛЕНО", "already": "Уже откликались", False: "ОШИБКА"}.get(res, "ОШИБКА")
        info_str = ""
        if res is not True and info:
            short = str(info)[:200]
            info_str = f"\n<i>{short}</i>"
        await message.answer(
            f"{status_emoji} <b>[{tag}]</b> {result_label}\n🔗 {v.url}{info_str}",
            parse_mode="HTML",
        )
        # If Playwright was used — send screenshots
        if info and info.get("path") == "playwright":
            from pathlib import Path as _Path
            from aiogram.types import FSInputFile as _FSI
            for stage in ("before", "after"):
                p = _Path(f"data/test_apply_{tag}_{stage}.png")
                if p.exists():
                    try:
                        await message.answer_photo(_FSI(p), caption=f"[{tag}] {stage}")
                    except Exception:
                        pass

        if res is True:
            stats["sent"] += 1
            # Record real application
            async with async_session() as session:
                vv = await session.get(Vacancy, v.id)
                if vv:
                    vv.status = VacancyStatus.APPLIED
                    session.add(Application(
                        vacancy_id=v.id, platform="hh",
                        cover_letter=letter,
                        status=ApplicationStatus.SENT,
                        attempt_count=1,
                    ))
                    await session.commit()
        elif res == "already":
            stats["already"] += 1
            async with async_session() as session:
                vv = await session.get(Vacancy, v.id)
                if vv:
                    vv.status = VacancyStatus.APPLIED
                    await session.commit()
        else:
            stats["failed"] += 1
            async with async_session() as session:
                session.add(Application(
                    vacancy_id=v.id, platform="hh",
                    cover_letter=letter,
                    status=ApplicationStatus.FAILED,
                    attempt_count=1,
                ))
                await session.commit()

        if i < len(vacancies):
            await random_delay(settings.apply_delay_min, settings.apply_delay_max)

    await message.answer(
        f"📊 <b>Итоги теста ({len(vacancies)} попыток):</b>\n"
        f"✅ Отправлено: {stats['sent']}\n"
        f"ℹ️ Уже откликались: {stats['already']}\n"
        f"❌ Ошибки: {stats['failed']}",
        parse_mode="HTML",
    )


@router.message(Command("negotiations"))
@admin_only
async def cmd_negotiations(message: Message, **kw):
    """Проверить статусы откликов на hh.ru."""
    from app.parsers.hh import HHParser
    parser = HHParser()
    pw = parser._get_playwright()

    if not pw:
        await message.answer("❌ Playwright не доступен")
        return

    await message.answer("🔄 Проверяю отклики...")
    statuses = await parser.check_negotiations()

    if not statuses:
        await message.answer("📭 Нет активных откликов или не удалось загрузить")
        return

    # Group by tab
    invites = [s for s in statuses if s.get("tab") == "invitations"]
    discards = [s for s in statuses if s.get("tab") == "discard"]
    active = [s for s in statuses if s.get("tab") == "active"]

    text_parts = ["📋 <b>Статусы откликов hh.ru</b>\n"]

    if invites:
        text_parts.append(f"\n🎉 <b>Приглашения ({len(invites)}):</b>")
        for s in invites[:5]:
            text_parts.append(f"  • {s['title'][:50]} — {s['company']}")

    if active:
        text_parts.append(f"\n📨 <b>Активные ({len(active)}):</b>")
        for s in active[:5]:
            text_parts.append(f"  • {s['title'][:50]} — {s['status']}")

    if discards:
        text_parts.append(f"\n❌ <b>Отказы ({len(discards)}):</b>")
        for s in discards[:5]:
            text_parts.append(f"  • {s['title'][:50]} — {s['company']}")

    await message.answer("\n".join(text_parts), parse_mode="HTML")

@router.callback_query(F.data == "limits_menu")
@admin_only
async def cb_limits_menu(callback: CallbackQuery, **kw):
    await callback.answer()
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    await callback.message.edit_text(
        f"📊 <b>Настройка дневного лимита откликов (hh.ru)</b>\n\n"
        f"Текущий лимит: <b>{limit}</b> в день\n\n"
        f"Выберите новое значение из пресетов или используйте кнопки +/- для точной настройки:",
        parse_mode="HTML",
        reply_markup=limits_keyboard(limit),
    )

@router.callback_query(F.data.startswith("set_limit:"))
@admin_only
async def cb_set_limit(callback: CallbackQuery, **kw):
    if not _scheduler:
        await callback.answer("Scheduler не найден")
        return
    action = callback.data.split(":")[1]
    current = _scheduler.max_applies_per_day_hh
    new_limit = current
    
    if action == "-10":
        new_limit = max(1, current - 10)
    elif action == "+10":
        new_limit = current + 10
    elif action.endswith("_abs"):
        new_limit = int(action.replace("_abs", ""))
        
    if new_limit != current:
        _scheduler.set_max_applies(new_limit)
        await callback.answer(f"Лимит изменён: {new_limit}")
        await callback.message.edit_text(
            f"📊 <b>Настройка дневного лимита откликов (hh.ru)</b>\n\n"
            f"Текущий лимит: <b>{new_limit}</b> в день\n\n"
            f"Выберите новое значение из пресетов или используйте кнопки +/- для точной настройки:",
            parse_mode="HTML",
            reply_markup=limits_keyboard(new_limit),
        )
    else:
        await callback.answer("Уже установлено")

@router.callback_query(F.data == "settings_back")
@admin_only
async def cb_settings_back(callback: CallbackQuery, **kw):
    await callback.answer()
    limit = _scheduler.max_applies_per_day_hh if _scheduler else 0
    await callback.message.edit_text(
        _settings_text(_scheduler.is_paused, _scheduler.auto_apply, limit),
        parse_mode="HTML",
        reply_markup=settings_keyboard(_scheduler.is_paused, _scheduler.auto_apply, limit),
    )

@router.callback_query(F.data == "force_sync_sheets")
@admin_only
async def cb_force_sync_sheets(callback: CallbackQuery, **kw):
    await callback.message.answer("🔄 Начинаю проверку свежих статусов на hh.ru и синхронизацию с таблицей. Это займет около 1-2 минут...")
    await callback.answer()
    
    if _scheduler:
        try:
            await _scheduler._job_sync_sheets(force=True)
            await callback.message.answer("✅ Синхронизация статусов с Google Таблицей успешно завершена!")
        except Exception as e:
            await callback.message.answer(f"❌ Произошла ошибка при синхронизации: {e}")
    else:
        await callback.message.answer("❌ Внутренняя ошибка: планировщик не инициализирован.")


# ══════════════════════════════════════════════════════════════
#  СКРИНЕР ВАКАНСИЙ (MAX / GIGARECRUITER)
# ══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "screener_menu")
@admin_only
async def cb_screener_menu(callback: CallbackQuery, **kw):
    await callback.answer()
    is_running = max_screener._page is not None
    status_text = "🟢 Активен (автоотслеживание чата)" if is_running else "⚪ Не запущен"
    session_text = "✅ Найдена (max_state.json)" if max_screener.is_session_available() else "❌ Отсутствует (нужен login_max_linux.sh)"
    
    text = (
        f"💬 <b>Ассистент скринеров вакансий (MAX / ГигаРекрутер)</b>\n\n"
        f"Статус службы: <b>{status_text}</b>\n"
        f"Сессия MAX Web: <b>{session_text}</b>\n\n"
        f"Бот непрерывно в фоне сканирует диалог (@giga_recruiter_bot). При поступлении вопроса он автоматически "
        f"генерирует ответ по резюме и мгновенно присылает карточку для подтверждения отправки."
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=screener_menu_keyboard(is_running),
    )


async def _screener_background_monitor(bot):
    """Фоновый непрерывный цикл отслеживания новых сообщений от рекрутера в чате MAX."""
    log.info("screener_monitor_loop_started")
    poll_interval = 5.0  # Проверка каждые 5 секунд

    while _screener_state.get("is_monitoring", False):
        try:
            # Если сейчас уже ожидается действие пользователя по текущему вопросу — не дублируем карточки
            if not _screener_state.get("waiting_for_user_action", False):
                q = await max_screener.get_latest_screener_question()
                if q:
                    _screener_state["waiting_for_user_action"] = True
                    _screener_state["question"] = q
                    answer, _, _ = await claude_ai.generate_screener_answer(q)
                    answer = clean_screener_answer(answer)
                    _screener_state["suggested_answer"] = answer

                    card_text = (
                        f"🎯 <b>Новый вопрос от скринера вакансий:</b>\n"
                        f"<i>«{q}»</i>\n\n"
                        f"🤖 <b>Предлагаемый ответ (на основе резюме):</b>\n"
                        f"<blockquote>{answer}</blockquote>\n\n"
                        f"Отправить этот ответ в чат рекрутеру или отредактировать?"
                    )
                    chat_id = _screener_state.get("chat_id") or settings.tg_admin_chat_id
                    if chat_id:
                        await bot.send_message(
                            chat_id=int(chat_id),
                            text=card_text,
                            parse_mode="HTML",
                            reply_markup=screener_card_keyboard(has_pending=True),
                        )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.warning("screener_monitor_loop_error", error=str(e))

        await asyncio.sleep(poll_interval)

    log.info("screener_monitor_loop_finished")


@router.callback_query(F.data == "screener_toggle")
@admin_only
async def cb_screener_toggle(callback: CallbackQuery, **kw):
    global _screener_task
    if max_screener._page is not None:
        _screener_state["is_monitoring"] = False
        _screener_state["waiting_for_user_action"] = False
        if _screener_task and not _screener_task.done():
            _screener_task.cancel()
            _screener_task = None
        await max_screener.close()
        await callback.answer("⏹ Скринер остановлен")
        await cb_screener_menu(callback, **kw)
        return

    if not max_screener.is_session_available():
        await callback.answer("❌ Нет сессии MAX! Запустите login_max_linux.sh", show_alert=True)
        return

    await callback.answer("🚀 Запуск браузера...")
    await callback.message.edit_text("⏳ <i>Подключение к веб-мессенджеру MAX и открытие чата со скринером...</i>", parse_mode="HTML")
    ok = await max_screener.start(headless=True)
    if not ok:
        await callback.message.edit_text(
            "❌ <b>Не удалось подключиться к MAX Web.</b>\nУбедитесь, что сессия актуальна (при необходимости запустите login_max_linux.sh).",
            parse_mode="HTML",
            reply_markup=screener_menu_keyboard(False),
        )
        return

    _screener_state["is_monitoring"] = True
    _screener_state["waiting_for_user_action"] = False
    _screener_state["chat_id"] = callback.message.chat.id

    if _screener_task and not _screener_task.done():
        _screener_task.cancel()
    _screener_task = asyncio.create_task(_screener_background_monitor(callback.bot))

    await callback.message.edit_text(
        "✅ <b>Скринер успешно запущен на автоотслеживание!</b>\n\n"
        "⚡️ <i>Бот сканирует диалог каждые 5 секунд.</i>\n"
        "Как только рекрутер пришлет вопрос, бот сразу пришлет вам карточку с готовым вариантом ответа для отправки.",
        parse_mode="HTML",
        reply_markup=screener_menu_keyboard(True),
    )


@router.callback_query(F.data == "screener_poll")
@admin_only
async def cb_screener_poll(callback: CallbackQuery, **kw):
    if max_screener._page is None:
        await callback.answer("Скринер не запущен. Сначала нажмите 'Запустить'", show_alert=True)
        return

    await callback.answer("🔍 Проверяю чат...")
    q = await max_screener.get_latest_screener_question()
    if q and not _screener_state.get("waiting_for_user_action", False):
        _screener_state["waiting_for_user_action"] = True
        _screener_state["question"] = q
        answer, _, _ = await claude_ai.generate_screener_answer(q)
        answer = clean_screener_answer(answer)
        _screener_state["suggested_answer"] = answer

        card_text = (
            f"🎯 <b>Вопрос от скринера вакансий:</b>\n"
            f"<i>«{q}»</i>\n\n"
            f"🤖 <b>Предлагаемый ответ (на основе резюме):</b>\n"
            f"<blockquote>{answer}</blockquote>\n\n"
            f"Отправить этот ответ в чат рекрутеру или отредактировать?"
        )
        await callback.message.answer(card_text, parse_mode="HTML", reply_markup=screener_card_keyboard(has_pending=True))
    elif q:
        await callback.answer("У вас уже есть ожидающий вопрос выше.")
    else:
        await callback.answer("Новых вопросов в чате пока нет.")


@router.callback_query(F.data == "screener_send")
@admin_only
async def cb_screener_send(callback: CallbackQuery, **kw):
    answer = clean_screener_answer(_screener_state.get("suggested_answer") or "")
    if not answer:
        await callback.answer("Нет ответа для отправки", show_alert=True)
        return

    await callback.answer("📨 Отправляю в чат MAX...")
    ok = await max_screener.send_answer(answer)
    if ok:
        await callback.message.edit_text(
            f"✅ <b>Ответ успешно отправлен в чат рекрутеру:</b>\n\n"
            f"<blockquote>{answer}</blockquote>\n\n"
            f"⚡️ <i>Ожидаем следующий вопрос от скринера (автоотслеживание активно)...</i>",
            parse_mode="HTML",
            reply_markup=screener_card_keyboard(has_pending=False),
        )
        _screener_state["suggested_answer"] = ""
        _screener_state["waiting_for_user_action"] = False
    else:
        await callback.answer("❌ Ошибка при вводе в чат браузера", show_alert=True)


@router.callback_query(F.data == "screener_regen")
@admin_only
async def cb_screener_regen(callback: CallbackQuery, **kw):
    question = _screener_state.get("question")
    if not question:
        await callback.answer("Вопрос не найден")
        return

    await callback.answer("🔄 Генерирую альтернативный вариант...")
    answer, _, _ = await claude_ai.generate_screener_answer(question, humanize=True)
    answer = clean_screener_answer(answer)
    _screener_state["suggested_answer"] = answer

    card_text = (
        f"🎯 <b>Вопрос от скринера вакансий:</b>\n"
        f"<i>«{question}»</i>\n\n"
        f"🤖 <b>Новый вариант ответа:</b>\n"
        f"<blockquote>{answer}</blockquote>\n\n"
        f"Отправить этот ответ в чат рекрутеру или отредактировать?"
    )
    await callback.message.edit_text(card_text, parse_mode="HTML", reply_markup=screener_card_keyboard(has_pending=True))


@router.callback_query(F.data == "screener_edit")
@admin_only
async def cb_screener_edit(callback: CallbackQuery, state: FSMContext, **kw):
    await callback.answer()
    await state.set_state(MaxScreenerSG.waiting_edited_answer)
    await callback.message.answer(
        "✏️ <b>Редактирование ответа:</b>\n\n"
        "Отправьте в этот чат ваш окончательный вариант текста для рекрутера. "
        "Бот немедленно введет его в диалог в мессенджере MAX.",
        parse_mode="HTML",
    )


@router.message(MaxScreenerSG.waiting_edited_answer)
@admin_only
async def msg_screener_custom_answer(message: Message, state: FSMContext, **kw):
    custom_text = message.text.strip()
    await state.clear()
    await message.answer("📨 <i>Отправляю ваш вариант текста в чат MAX...</i>", parse_mode="HTML")
    ok = await max_screener.send_answer(custom_text)
    if ok:
        await message.answer(
            f"✅ <b>Ваш ответ успешно отправлен рекрутеру:</b>\n\n"
            f"<blockquote>{custom_text}</blockquote>\n\n"
            f"⚡️ <i>Ожидаем следующий вопрос от скринера (автоотслеживание активно)...</i>",
            parse_mode="HTML",
            reply_markup=screener_card_keyboard(has_pending=False),
        )
        _screener_state["suggested_answer"] = ""
        _screener_state["waiting_for_user_action"] = False
    else:
        await message.answer("❌ Ошибка при отправке через браузер. Проверьте, открыта ли страница.", reply_markup=screener_card_keyboard(has_pending=True))


@router.callback_query(F.data == "screener_skip")
@admin_only
async def cb_screener_skip(callback: CallbackQuery, **kw):
    _screener_state["question"] = ""
    _screener_state["suggested_answer"] = ""
    _screener_state["waiting_for_user_action"] = False
    await callback.answer("Вопрос пропущен")
    await callback.message.edit_text("⏭ <b>Вопрос пропущен.</b> Ожидаем новые сообщения...", parse_mode="HTML", reply_markup=screener_card_keyboard(has_pending=False))


@router.callback_query(F.data == "screener_stop")
@admin_only
async def cb_screener_stop(callback: CallbackQuery, **kw):
    global _screener_task
    _screener_state["is_monitoring"] = False
    _screener_state["waiting_for_user_action"] = False
    if _screener_task and not _screener_task.done():
        _screener_task.cancel()
        _screener_task = None
    await max_screener.close()
    _screener_state["question"] = ""
    _screener_state["suggested_answer"] = ""
    await callback.answer("🛑 Сессия закрыта")
    await callback.message.edit_text("🛑 <b>Сессия скринера закрыта.</b> Браузер и автоотслеживание остановлены.", parse_mode="HTML")


