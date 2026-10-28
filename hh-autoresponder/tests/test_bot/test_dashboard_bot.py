from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message, User

from app.bot.handlers import btn_dashboard, cb_dashboard_refresh
from app.bot.keyboards import dashboard_keyboard, main_menu
from app.config import settings


def test_main_menu_contains_dashboard_button():
    kb = main_menu()
    texts = [btn.text for row in kb.keyboard for btn in row]
    assert "🌐 Дашборд" in texts


def test_dashboard_keyboard_with_url():
    kb = dashboard_keyboard(url="https://abc.trycloudflare.com")
    flat = [btn for row in kb.inline_keyboard for btn in row]
    url_btn = next((b for b in flat if b.url == "https://abc.trycloudflare.com"), None)
    assert url_btn is not None
    assert url_btn.text == "🚀 Открыть дашборд"

    refresh_btn = next((b for b in flat if b.callback_data == "dash_refresh"), None)
    assert refresh_btn is not None


@pytest.mark.asyncio
async def test_btn_dashboard_handler():
    msg = AsyncMock(spec=Message)
    msg.chat = MagicMock()
    msg.chat.id = settings.tg_admin_chat_id
    msg.from_user = User(id=123, is_bot=False, first_name="Admin")
    wait_msg = AsyncMock()
    msg.answer = AsyncMock(return_value=wait_msg)

    with (
        patch(
            "app.bot.handlers.tunnel_manager.get_or_start_tunnel",
            AsyncMock(return_value="https://test.trycloudflare.com"),
        ),
        patch("app.bot.handlers.tunnel_manager.get_local_url", return_value="http://localhost:8080"),
    ):
        await btn_dashboard(msg)

        msg.answer.assert_called_once()
        wait_msg.edit_text.assert_called_once()
        call_args = wait_msg.edit_text.call_args[0][0]
        assert "https://test.trycloudflare.com" in call_args
        assert "http://localhost:8080" in call_args


@pytest.mark.asyncio
async def test_cb_dashboard_refresh_handler():
    call = AsyncMock()
    call.message = AsyncMock()
    call.message.chat = MagicMock()
    call.message.chat.id = settings.tg_admin_chat_id
    call.from_user = User(id=123, is_bot=False, first_name="Admin")

    with (
        patch(
            "app.bot.handlers.tunnel_manager.get_or_start_tunnel",
            AsyncMock(return_value="https://new-url.trycloudflare.com"),
        ),
        patch("app.bot.handlers.tunnel_manager.get_local_url", return_value="http://localhost:8080"),
    ):
        await cb_dashboard_refresh(call)

        call.answer.assert_called_once()
        call.message.edit_text.assert_called_once()
        call_args = call.message.edit_text.call_args[0][0]
        assert "https://new-url.trycloudflare.com" in call_args
