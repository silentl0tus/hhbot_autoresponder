import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.bot.handlers import cb_set_model
from app.config import settings
from app.ai.claude import claude_ai


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
    from app.bot.handlers import cb_ai_toggle, cb_ai_preset
    mock_callback = AsyncMock()
    mock_callback.message = AsyncMock()
    mock_callback.message.chat.id = settings.tg_admin_chat_id

    with patch("app.bot.handlers._send_balance", new_callable=AsyncMock), \
         patch("app.bot.handlers.save_env_variable"):
        # Test toggle
        old_val = settings.ai_enabled
        await cb_ai_toggle(mock_callback)
        assert settings.ai_enabled == (not old_val)

        # Test Gemini preset
        mock_callback.data = "ai_preset:gemini"
        await cb_ai_preset(mock_callback)
        assert "generativelanguage.googleapis.com" in settings.llm_base_url
        assert settings.llm_model == "gemini-3.6-flash"

        # Test OpenRouter preset
        mock_callback.data = "ai_preset:openrouter"
        await cb_ai_preset(mock_callback)
        assert "openrouter.ai" in settings.llm_base_url
        assert settings.llm_model == "deepseek/deepseek-v4-flash-0731:free"
