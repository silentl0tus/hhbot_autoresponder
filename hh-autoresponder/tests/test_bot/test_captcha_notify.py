"""Tests for app.bot.captcha_notify bridge module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.captcha_notify import configure, send_captcha_to_user


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level globals before each test."""
    import app.bot.captcha_notify as mod
    mod._bot = None
    mod._chat_id = None
    yield
    mod._bot = None
    mod._chat_id = None


class TestConfigure:
    def test_stores_bot_and_chat_id(self):
        bot = MagicMock()
        configure(bot, 123456)

        import app.bot.captcha_notify as mod
        assert mod._bot is bot
        assert mod._chat_id == 123456


class TestSendCaptchaToUser:
    @pytest.mark.asyncio
    async def test_returns_early_when_not_configured(self):
        """Should not raise when bot/chat_id are not set."""
        await send_captcha_to_user("some/path.png")

    @pytest.mark.asyncio
    async def test_returns_early_when_screenshot_missing(self):
        bot = AsyncMock()
        configure(bot, 123)
        # non-existent path — should not crash
        await send_captcha_to_user("/nonexistent/captcha.png")
        bot.send_photo.assert_not_called()

    @pytest.mark.asyncio
    async def test_sends_photo_with_keyboard(self, tmp_path: Path):
        bot = AsyncMock()
        chat_id = 987654
        configure(bot, chat_id)

        # Create a fake screenshot file
        screenshot = tmp_path / "captcha.png"
        screenshot.write_bytes(b"\x89PNG_fake_data")

        await send_captcha_to_user(str(screenshot))

        bot.send_photo.assert_awaited_once()
        call_kwargs = bot.send_photo.call_args.kwargs
        assert call_kwargs["chat_id"] == chat_id
        assert "CAPTCHA" in call_kwargs["caption"]
        assert call_kwargs["reply_markup"] is not None

        # Verify inline keyboard has two buttons
        kb = call_kwargs["reply_markup"]
        buttons = kb.inline_keyboard[0]
        assert len(buttons) == 2
        assert buttons[0].callback_data == "captcha_enter"
        assert buttons[1].callback_data == "captcha_skip"
