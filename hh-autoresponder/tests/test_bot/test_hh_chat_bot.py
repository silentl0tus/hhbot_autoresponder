import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiogram.types import CallbackQuery, Message, User, Chat
from app.bot.keyboards import hh_chat_card_keyboard, hh_chat_menu_keyboard
from app.bot.handlers import (
    cb_hh_chat_menu,
    cb_hh_skip,
    cb_hh_stop,
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
