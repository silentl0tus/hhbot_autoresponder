"""Bridge module: sends CAPTCHA screenshots to the admin chat via Telegram bot.

Lifecycle
---------
1. ``configure(bot, chat_id)`` is called once at startup from ``app.main``.
2. ``send_captcha_to_user(screenshot_path)`` is called from
   ``app.parsers.hh_playwright`` whenever a manual CAPTCHA resolution is
   needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import structlog
from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup

log = structlog.get_logger()

_bot: Optional[Bot] = None
_chat_id: Optional[int] = None


def configure(bot: Bot, chat_id: int) -> None:
    """Store bot instance and admin chat id for later use."""
    global _bot, _chat_id
    _bot = bot
    _chat_id = chat_id
    log.debug("captcha_notify_configured", chat_id=chat_id)


async def send_captcha_to_user(screenshot_path: str) -> None:
    """Send the CAPTCHA screenshot to the admin Telegram chat with action buttons."""
    if _bot is None or _chat_id is None:
        log.warning("captcha_notify_not_configured")
        return

    path = Path(screenshot_path)
    if not path.exists():
        log.warning("captcha_screenshot_not_found", path=str(path))
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Ввести текст", callback_data="captcha_enter"),
            InlineKeyboardButton(text="⏭ Пропустить", callback_data="captcha_skip"),
        ]
    ])

    photo = BufferedInputFile(path.read_bytes(), filename=path.name)
    await _bot.send_photo(
        chat_id=_chat_id,
        photo=photo,
        caption="🔒 <b>CAPTCHA</b> — введите текст с картинки или пропустите.",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    log.info("captcha_screenshot_sent_to_user", chat_id=_chat_id)
    log.info("captcha_screenshot_sent_to_user", chat_id=_chat_id)

async def send_error_screenshot(screenshot_path: str, caption: str) -> None:
    """Send a generic error screenshot to the admin Telegram chat."""
    if _bot is None or _chat_id is None:
        return

    path = Path(screenshot_path)
    if not path.exists():
        return

    photo = BufferedInputFile(path.read_bytes(), filename=path.name)
    try:
        await _bot.send_photo(
            chat_id=_chat_id,
            photo=photo,
            caption=caption,
            parse_mode="HTML",
        )
    except Exception as e:
        log.warning("error_screenshot_send_failed", error=str(e))
