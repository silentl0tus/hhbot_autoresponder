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

    with patch("app.bot.handlers._send_balance", new_callable=AsyncMock) as mock_send_balance:
        await cb_set_model(mock_callback)
        
        # Verify model was set in settings & claude_ai
        assert settings.llm_model == "gemini-3.6-flash"
        assert mock_callback.answer.called
        assert "gemini-3.6-flash" in mock_callback.answer.call_args[0][0]
        assert mock_send_balance.called
