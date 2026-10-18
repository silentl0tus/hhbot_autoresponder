from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers import cb_set_model
from app.config import settings


@pytest.mark.asyncio
async def test_cb_set_model():
    mock_callback = AsyncMock()
    mock_callback.data = "set_model:gemini-3.6-flash"
    mock_callback.message = AsyncMock()
    mock_callback.message.chat.id = settings.tg_admin_chat_id

    with patch("app.bot.handlers._send_balance", new_callable=AsyncMock) as mock_send_balance:
        await cb_set_model(mock_callback)

        # Verify model was set in settings & claude_ai
        assert settings.llm_model == "gemini-3.6-flash"
        assert mock_callback.answer.called
        assert "gemini-3.6-flash" in mock_callback.answer.call_args[0][0]
        assert mock_send_balance.called


@pytest.mark.asyncio
async def test_ai_toggle_and_presets():
    from app.bot.handlers import cb_ai_preset, cb_ai_toggle

    mock_callback = AsyncMock()
    mock_callback.message = AsyncMock()
    mock_callback.message.chat.id = settings.tg_admin_chat_id

    with patch("app.bot.handlers._send_balance", new_callable=AsyncMock), patch("app.bot.handlers.save_env_variable"):
        # Test toggle
        old_val = settings.ai_enabled
        await cb_ai_toggle(mock_callback)
        assert settings.ai_enabled == (not old_val)

        # Setup dummy keys
        settings.gemini_api_key = "AIzaSyDummyGeminiKey"
        settings.openrouter_api_key = "sk-or-v1-DummyOpenRouterKey"

        # Test Gemini preset
        mock_callback.data = "ai_preset:gemini"
        await cb_ai_preset(mock_callback)
        assert "generativelanguage.googleapis.com" in settings.llm_base_url
        assert settings.llm_model == "gemini-3.6-flash"
        assert settings.llm_api_key == "AIzaSyDummyGeminiKey"

        # Test OpenRouter preset
        mock_callback.data = "ai_preset:openrouter"
        await cb_ai_preset(mock_callback)
        assert "openrouter.ai" in settings.llm_base_url
        assert settings.llm_model == "openrouter/auto"
        assert settings.llm_api_key == "sk-or-v1-DummyOpenRouterKey"


@pytest.mark.asyncio
async def test_ai_settings_keyboard_and_callbacks():
    from app.bot.handlers import cb_show_balance
    from app.bot.keyboards import settings_keyboard

    kb = settings_keyboard()
    all_buttons = [btn for row in kb.inline_keyboard for btn in row]

    # Check that button is renamed to clear text and callback is show_balance
    ai_btn = next((b for b in all_buttons if b.callback_data == "show_balance"), None)
    assert ai_btn is not None
    assert "Модели" in ai_btn.text and "Настройки ИИ" in ai_btn.text

    # Check that there is no orphan models_menu button in settings_keyboard
    broken_btn = next((b for b in all_buttons if b.callback_data == "models_menu"), None)
    assert broken_btn is None

    # Verify both show_balance and models_menu callbacks invoke _send_balance
    for cb_data in ["show_balance", "models_menu"]:
        mock_cb = AsyncMock()
        mock_cb.data = cb_data
        mock_cb.message = AsyncMock()
        mock_cb.message.chat.id = settings.tg_admin_chat_id
        with patch("app.bot.handlers._send_balance", new_callable=AsyncMock) as mock_send:
            await cb_show_balance(mock_cb)
            assert mock_send.called
