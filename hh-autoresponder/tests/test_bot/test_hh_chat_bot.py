import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery, Message, User, Chat
from app.bot.keyboards import hh_chat_card_keyboard, hh_chat_menu_keyboard
from app.bot.handlers import (
    cb_hh_chat_menu,
    cb_hh_skip,
    cb_hh_stop,
    cb_hh_poll,
    _hh_chat_state,
    _build_hh_card_text,
)


def test_hh_chat_keyboards():
    kb_menu = hh_chat_menu_keyboard(is_running=False)
    assert any(b.callback_data == "hh_chat_toggle" for row in kb_menu.inline_keyboard for b in row)
    assert any(b.callback_data == "hh_poll" for row in kb_menu.inline_keyboard for b in row)

    kb_card = hh_chat_card_keyboard(options=["Да", "Нет"], recommended_option="Да", has_pending=True)
    flat_callbacks = [b.callback_data for row in kb_card.inline_keyboard for b in row]
    assert "hh_opt:0" in flat_callbacks
    assert "hh_opt:1" in flat_callbacks
    assert "hh_send_ai" in flat_callbacks
    assert "hh_edit" in flat_callbacks


def test_build_hh_card_text():
    state = {
        "company": "Мустанг Технологии Кормления",
        "vacancy": "Integration Developer",
        "question": "Какой опыт с n8n?",
        "recommended_option": "Только учебные проекты",
        "suggested_answer": "Работал с автоматизацией на Python.",
    }
    text = _build_hh_card_text(state)
    assert "Мустанг" in text
    assert "Только учебные проекты" in text
    assert "Работал с автоматизацией" in text


@pytest.mark.asyncio
async def test_cb_hh_skip_and_stop():
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = User(id=123, is_bot=False, first_name="Test")
    callback.message = AsyncMock()
    callback.message.chat = Chat(id=123, type="private")
    callback.answer = AsyncMock()

    with patch("app.bot.handlers.settings.tg_admin_chat_id", "123"):
        _hh_chat_state["question"] = "Тестовый вопрос"
        _hh_chat_state["waiting_for_user_action"] = True

        await cb_hh_skip(callback)
        assert _hh_chat_state["waiting_for_user_action"] is False
        assert _hh_chat_state["question"] == ""

        _hh_chat_state["is_monitoring"] = True
        with patch("app.bot.handlers.hh_chat_parser.close", new=AsyncMock()):
            await cb_hh_stop(callback)
            assert _hh_chat_state["is_monitoring"] is False


@pytest.mark.asyncio
async def test_cb_hh_poll_skips_rejection():
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = User(id=123, is_bot=False, first_name="Test")
    status_msg = AsyncMock()
    callback.message = AsyncMock()
    callback.message.chat = Chat(id=123, type="private")
    callback.message.answer = AsyncMock(return_value=status_msg)
    callback.answer = AsyncMock()

    mock_chats = [
        {
            "chat_id": "999",
            "title": "Data Engineer",
            "company": "Банк",
            "has_unread": True,
            "is_rejection": True,
            "last_message": "К сожалению, мы вынуждены отказать",
        }
    ]

    with patch("app.bot.handlers.settings.tg_admin_chat_id", "123"):
        with patch("app.bot.handlers.hh_chat_parser.is_session_available", return_value=True):
            with patch("app.bot.handlers.hh_chat_parser.get_unread_or_active_chats", new=AsyncMock(return_value=mock_chats)):
                await cb_hh_poll(callback)
                # Ensure it did not treat rejection as a question
                assert _hh_chat_state.get("waiting_for_user_action") is False
                status_msg.edit_text.assert_called_with("✅ Все активные чаты проверены. Ожидающих вопросов нет (отказы и закрытые диалоги пропущены).")
