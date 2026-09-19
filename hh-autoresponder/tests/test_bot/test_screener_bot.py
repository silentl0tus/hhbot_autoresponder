import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery
from app.bot.handlers import cb_screener_menu, cb_screener_skip, cb_screener_stop, _screener_state
from app.bot.keyboards import screener_card_keyboard, screener_menu_keyboard


def test_screener_keyboards_structure():
    card_kb = screener_card_keyboard(has_pending=True)
    assert any(btn.callback_data == "screener_send" for row in card_kb.inline_keyboard for btn in row)
    assert any(btn.callback_data == "screener_edit" for row in card_kb.inline_keyboard for btn in row)

    menu_kb = screener_menu_keyboard(is_running=False)
    assert any(btn.callback_data == "screener_toggle" for row in menu_kb.inline_keyboard for btn in row)


@pytest.mark.asyncio
async def test_cb_screener_menu():
    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.chat.id = 123456789

    with patch("app.config.settings.tg_admin_chat_id", "123456789"):
        await cb_screener_menu(callback)
        callback.answer.assert_called_once()
        callback.message.edit_text.assert_called_once()
        call_args = callback.message.edit_text.call_args[0][0]
        assert "Ассистент скринеров вакансий" in call_args


@pytest.mark.asyncio
async def test_cb_screener_skip():
    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.chat.id = 123456789

    _screener_state["question"] = "Тестовый вопрос"
    _screener_state["suggested_answer"] = "Тестовый ответ"

    with patch("app.config.settings.tg_admin_chat_id", "123456789"):
        await cb_screener_skip(callback)
        assert _screener_state["question"] == ""
        assert _screener_state["suggested_answer"] == ""
        callback.answer.assert_called_once_with("Вопрос пропущен")


@pytest.mark.asyncio
async def test_cb_screener_stop():
    callback = MagicMock(spec=CallbackQuery)
    callback.answer = AsyncMock()
    callback.message = MagicMock()
    callback.message.edit_text = AsyncMock()
    callback.message.chat.id = 123456789

    with patch("app.config.settings.tg_admin_chat_id", "123456789"), \
         patch("app.bot.handlers.max_screener.close", new_callable=AsyncMock) as mock_close:
        await cb_screener_stop(callback)
        mock_close.assert_called_once()
        callback.answer.assert_called_once_with("🛑 Сессия закрыта")
