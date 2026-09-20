from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔍 Вакансии"), KeyboardButton(text="📊 Статистика")],
            [KeyboardButton(text="📩 Сообщения"), KeyboardButton(text="⚙️ Настройки")],
            [KeyboardButton(text="📝 Создать сопроводительное"), KeyboardButton(text="📋 Логи")],
        ],
        resize_keyboard=True,
    )


def vacancy_keyboard(vacancy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Откликнуться", callback_data=f"apply:{vacancy_id}"),
            InlineKeyboardButton(text="❌ Пропустить", callback_data=f"skip:{vacancy_id}"),
        ],
        [
            InlineKeyboardButton(text="📄 Подробнее", callback_data=f"details:{vacancy_id}"),
            InlineKeyboardButton(text="🚫 В ЧС", callback_data=f"blacklist:{vacancy_id}"),
        ],
    ])


def vacancy_list_keyboard(vacancy_ids: list[int], page: int, total_pages: int, prefix: str = "") -> InlineKeyboardMarkup:
    rows = []
    for i, vid in enumerate(vacancy_ids):
        rows.append([
            InlineKeyboardButton(text=f"📄 Подробнее #{i+1}", callback_data=f"details:{vid}"),
            InlineKeyboardButton(text="✅", callback_data=f"apply:{vid}"),
            InlineKeyboardButton(text="❌", callback_data=f"skip:{vid}"),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"{prefix}page:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"{prefix}page:{page+1}"))
    rows.append(nav)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def message_keyboard(message_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤖 AI-ответ", callback_data=f"ai_reply:{message_id}"),
            InlineKeyboardButton(text="✅ Прочитано", callback_data=f"mark_read:{message_id}"),
        ],
    ])


def confirm_apply_keyboard(vacancy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📨 Да, отправить", callback_data=f"confirm_apply:{vacancy_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data=f"cancel_apply:{vacancy_id}"),
        ],
    ])


def settings_keyboard(is_paused: bool = False, auto_apply: bool = False, limit: int = 0, paused_platforms: set = None) -> InlineKeyboardMarkup:
    pause_text = "▶️ Возобновить" if is_paused else "⏸ Пауза (все)"
    auto_text = "🟢 Авто-отклик ВКЛ" if auto_apply else "⚪ Авто-отклик ВЫКЛ"
    
    paused_platforms = paused_platforms or set()
    hh_text = "🔴 hh.ru (выкл)" if "hh" in paused_platforms else "🟢 hh.ru (вкл)"
    habr_text = "🔴 Хабр (выкл)" if "habr" in paused_platforms else "🟢 Хабр (вкл)"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=pause_text, callback_data="toggle_pause"),
            InlineKeyboardButton(text=auto_text, callback_data="toggle_auto"),
        ],
        [
            InlineKeyboardButton(text=hh_text, callback_data="toggle_plat:hh"),
            InlineKeyboardButton(text=habr_text, callback_data="toggle_plat:habr"),
        ],
        [
            InlineKeyboardButton(text="🔄 Искать сейчас", callback_data="force_search"),
            InlineKeyboardButton(text="💎 Баланс AI", callback_data="show_balance"),
        ],
        [
            InlineKeyboardButton(text="⬆️ Поднять резюме", callback_data="bump_resume"),
            InlineKeyboardButton(text=f"📊 Лимит: {limit}", callback_data="limits_menu"),
        ],
        [
            InlineKeyboardButton(text="🧹 Очистить отклики", callback_data="clear_neg"),
            InlineKeyboardButton(text="💬 Скринер MAX", callback_data="screener_menu"),
        ],
        [
            InlineKeyboardButton(text="💬 Чат hh.ru (Бета)", callback_data="hh_chat_menu"),
            InlineKeyboardButton(text="🎛 Настройка функций", callback_data="behavior_menu"),
        ],
    ])


_FLAG_LABELS = {
    "auto_apply": "Авто-отклики",
    "pass_tests": "Проходить тесты вакансий",
    "ai_cover_letters": "Писать письма через AI",
    "humanize_letters": "Гуманизатор текста (Анти-ИИ)",
    "notify_messages": "Сообщать о рекрутёрах",
    "thank_rejections": "Говорить спасибо за отказ",
    "bump_resume": "Поднимать резюме",
}


def behavior_keyboard(flags: dict) -> InlineKeyboardMarkup:
    """Меню с галочками: что бот делает. Нажатие переключает флаг."""
    rows = []
    for name, label in _FLAG_LABELS.items():
        mark = "✅" if flags.get(name, True) else "⬜️"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"bflag:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def clear_neg_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Убрать отказы", callback_data="clearneg:discard")],
        [InlineKeyboardButton(text="🗓 Старше 14 дней", callback_data="clearneg:old14")],
        [InlineKeyboardButton(text="🗓 Старше 30 дней", callback_data="clearneg:old30")],
        [InlineKeyboardButton(text="👀 Показать без удаления", callback_data="clearneg:dry")],
    ])

def limits_keyboard(current: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="-10", callback_data="set_limit:-10"),
            InlineKeyboardButton(text="+10", callback_data="set_limit:+10"),
        ],
        [
            InlineKeyboardButton(text="50", callback_data="set_limit:50_abs"),
            InlineKeyboardButton(text="100", callback_data="set_limit:100_abs"),
            InlineKeyboardButton(text="150", callback_data="set_limit:150_abs"),
            InlineKeyboardButton(text="200", callback_data="set_limit:200_abs"),
        ],
        [
            InlineKeyboardButton(text="◀️ Назад", callback_data="settings_back"),
        ]
    ])


GEMINI_MODELS = [
    ("gemini-3.6-flash", "⚡️ gemini-3.6-flash (Основная)"),
    ("gemini-3.8-flash", "🚀 gemini-3.8-flash (Новейшая)"),
    ("gemini-3.5-flash", "🔹 gemini-3.5-flash (Быстрая)"),
]

OPENROUTER_FREE_MODELS = [
    ("nex-agi/nex-n2.5-pro:free", "⚡️ NEX N2.5 Pro (Free, быстрая)"),
    ("nex-agi/nex-n2.5-mini:free", "🚀 NEX N2.5 Mini (Free, легковесная)"),
    ("liquid/lfm-2.5-2.6b:free", "💧 Liquid LFM 2.5 (Free)"),
    ("inclusionai/ling-3.0-flash-vl:free", "⚡️ Ling 3.0 Flash (Free)"),
    ("qwen/qwen3.8-27b:free", "🧠 Qwen 3.8 27B (Free)"),
    ("google/gemma-4-31b-it:free", "🔹 Gemma 4 31B (Free)"),
    ("google/gemma-4-26b-a4b-it:free", "🔹 Gemma 4 26B (Free)"),
    ("nvidia/nemotron-3.5-lightning:free", "⚡️ Nemotron 3.5 (Free)"),
    ("z-ai/glm-5.2:free", "🌐 GLM 5.2 (Free)"),
    ("deepseek/deepseek-v4-flash-0731:free", "🤖 DeepSeek v4 (Free)"),
]

OPENROUTER_MODELS = [
    *OPENROUTER_FREE_MODELS,
    ("deepseek/deepseek-chat", "💎 DeepSeek V3 (Платная)"),
    ("deepseek/deepseek-r1", "🧠 DeepSeek R1 (Reasoning, платная)"),
]

KNOWN_MODELS = GEMINI_MODELS


def ai_models_keyboard(current_model: str, ai_enabled: bool = True, is_openrouter: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура для полного управления AI: выбор моделей, пресеты, смена ключей и прокси."""
    rows = []
    toggle_text = "🔴 Выключить AI" if ai_enabled else "🟢 Включить AI"
    rows.append([
        InlineKeyboardButton(text=toggle_text, callback_data="ai_toggle"),
        InlineKeyboardButton(text="⚡️ Тест связи с AI", callback_data="ai_test_conn"),
    ])

    models_list = OPENROUTER_MODELS if is_openrouter else GEMINI_MODELS
    for model_id, label in models_list:
        mark = "✅ " if current_model == model_id else ""
        rows.append([InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"set_model:{model_id}")])
    
    rows.append([
        InlineKeyboardButton(text="✏️ Ввести свою модель", callback_data="ai_edit:model"),
    ])
    rows.append([
        InlineKeyboardButton(text="🌐 Пресет: Gemini", callback_data="ai_preset:gemini"),
        InlineKeyboardButton(text="🚀 Пресет: OpenRouter", callback_data="ai_preset:openrouter"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔑 Сменить API-ключ", callback_data="ai_edit:key"),
        InlineKeyboardButton(text="🌐 Сменить Base URL", callback_data="ai_edit:url"),
    ])
    rows.append([
        InlineKeyboardButton(text="🛡 Прокси для LLM", callback_data="ai_edit:proxy"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="settings_back"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

def stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Принудительное обновление статусов", callback_data="force_sync_sheets")]
    ])


def screener_card_keyboard(has_pending: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура карточки вопроса от скринера вакансий."""
    rows = []
    if has_pending:
        rows.append([
            InlineKeyboardButton(text="📨 Отправить в чат", callback_data="screener_send"),
            InlineKeyboardButton(text="✏️ Отредактировать", callback_data="screener_edit"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔄 Другой вариант", callback_data="screener_regen"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="screener_skip"),
        ])
    rows.append([
        InlineKeyboardButton(text="🔄 Проверить новые вопросы", callback_data="screener_poll"),
        InlineKeyboardButton(text="🛑 Закрыть скринер", callback_data="screener_stop"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def screener_menu_keyboard(is_running: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура меню управления скринером MAX."""
    toggle_text = "⏹ Остановить скринер" if is_running else "▶️ Запустить скринер MAX"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="screener_toggle")],
        [InlineKeyboardButton(text="🔄 Проверить чат сейчас", callback_data="screener_poll")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings_back")],
    ])


def hh_chat_card_keyboard(options: list[str] | None = None, recommended_option: str | None = None, has_pending: bool = True) -> InlineKeyboardMarkup:
    """Клавиатура для ответа на вопрос в чате HeadHunter."""
    rows = []
    
    # Кнопки быстрых вариантов выбора (если рекрутер задал опрос с выбором)
    if options and has_pending:
        opt_buttons = []
        for i, opt in enumerate(options):
            is_rec = recommended_option and (opt.lower() in recommended_option.lower() or recommended_option.lower() in opt.lower())
            mark = "⭐️ " if is_rec else ""
            btn = InlineKeyboardButton(text=f"{mark}{opt}", callback_data=f"hh_opt:{i}")
            opt_buttons.append(btn)
        
        # Разбиваем по 2 кнопки в ряд
        for i in range(0, len(opt_buttons), 2):
            rows.append(opt_buttons[i:i+2])

    if has_pending:
        rows.append([
            InlineKeyboardButton(text="📨 Отправить AI-ответ", callback_data="hh_send_ai"),
            InlineKeyboardButton(text="✏️ Редактировать", callback_data="hh_edit"),
        ])
        rows.append([
            InlineKeyboardButton(text="🔄 Другой вариант", callback_data="hh_regen"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="hh_skip"),
        ])
    
    rows.append([
        InlineKeyboardButton(text="🔄 Проверить чаты hh.ru", callback_data="hh_poll"),
        InlineKeyboardButton(text="🛑 Закрыть", callback_data="hh_stop"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def hh_chat_menu_keyboard(is_running: bool = False) -> InlineKeyboardMarkup:
    """Меню управления автоответами в чатах HeadHunter."""
    toggle_text = "⏹ Остановить мониторинг" if is_running else "▶️ Запустить автомониторинг hh.ru"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_text, callback_data="hh_chat_toggle")],
        [InlineKeyboardButton(text="🔍 Проверить чаты сейчас", callback_data="hh_poll")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="settings_back")],
    ])


