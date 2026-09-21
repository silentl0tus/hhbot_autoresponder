import re

with open("/mnt/new_volume/VS_code_base/hh_autoresponder/hh-autoresponder/app/bot/handlers.py", "r") as f:
    content = f.read()

target = """@router.callback_query(F.data == "hh_chat_list")
@admin_only
async def cb_hh_chat_list(callback: CallbackQuery, **kw):
    log.info("hh_chat_list_requested", user_id=callback.from_user.id)
    await callback.answer("Загружаю список чатов...")
    status_msg = await callback.message.edit_text("⏳ <i>Получаю список последних чатов с hh.ru...</i>", parse_mode="HTML")

    if not hh_chat_parser.is_session_available():
        await status_msg.edit_text("❌ Нет сохраненной сессии hh.ru. Сначала пройдите авторизацию.")
        return

    chats = await hh_chat_parser.get_unread_or_active_chats()
    if not chats:
        await status_msg.edit_text(
            "📭 У вас пока нет активных чатов или произошла ошибка при загрузке.",
            reply_markup=hh_chat_menu_keyboard(_hh_chat_state.get("is_monitoring", False))
        )
        return

    # Отбрасываем чаты с явными отказами
    active_chats = [c for c in chats if not c.get("is_rejection")]
    if not active_chats:
        await status_msg.edit_text(
            "📭 У вас нет активных диалогов (везде найден отказ).",
            reply_markup=hh_chat_menu_keyboard(_hh_chat_state.get("is_monitoring", False))
        )
        return

    await status_msg.edit_text(
        "🗂 <b>Выберите диалог для ответа:</b>\\n"
        "<i>Показаны последние диалоги (без отказов)</i>",
        parse_mode="HTML",
        reply_markup=hh_chat_list_keyboard(active_chats)
    )"""

replacement = """@router.callback_query(F.data.startswith("hh_chat_list"))
@admin_only
async def cb_hh_chat_list(callback: CallbackQuery, **kw):
    parts = callback.data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 0

    log.info("hh_chat_list_requested", user_id=callback.from_user.id, page=page)
    await callback.answer("Загружаю список чатов...")
    status_msg = await callback.message.edit_text("⏳ <i>Получаю список последних чатов с hh.ru...</i>", parse_mode="HTML")

    if not hh_chat_parser.is_session_available():
        await status_msg.edit_text("❌ Нет сохраненной сессии hh.ru. Сначала пройдите авторизацию.")
        return

    chats = await hh_chat_parser.get_unread_or_active_chats()
    if not chats:
        await status_msg.edit_text(
            "📭 У вас пока нет активных чатов или произошла ошибка при загрузке.",
            reply_markup=hh_chat_menu_keyboard(_hh_chat_state.get("is_monitoring", False))
        )
        return

    # Отбрасываем чаты с явными отказами
    active_chats = [c for c in chats if not c.get("is_rejection")]
    if not active_chats:
        await status_msg.edit_text(
            "📭 У вас нет активных диалогов (везде найден отказ).",
            reply_markup=hh_chat_menu_keyboard(_hh_chat_state.get("is_monitoring", False))
        )
        return

    await status_msg.edit_text(
        "🗂 <b>Выберите диалог для ответа:</b>\\n"
        f"<i>Страница {page + 1}. Показаны диалоги без отказов.</i>",
        parse_mode="HTML",
        reply_markup=hh_chat_list_keyboard(active_chats, page=page)
    )"""

new_content = content.replace(target.replace("\\n", "\n"), replacement.replace("\\n", "\n"))

with open("/mnt/new_volume/VS_code_base/hh_autoresponder/hh-autoresponder/app/bot/handlers.py", "w") as f:
    f.write(new_content)

print(content == new_content)
