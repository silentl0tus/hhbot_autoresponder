import pytest
from unittest.mock import AsyncMock, patch
import httpx
from app.ai.claude import claude_ai
from app.config import settings


@pytest.mark.asyncio
async def test_generate_cover_letter_api_error_notifies_user():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post, \
         patch("app.utils.notifier.send", new_callable=AsyncMock) as mock_send, \
         patch.object(settings, "ai_enabled", True), \
         patch.object(settings, "llm_api_key", "test_key"):
        
        # Simulate 429 Too Many Requests
        mock_response = AsyncMock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests: Rate limit exceeded"
        mock_post.side_effect = httpx.HTTPStatusError("Rate Limit", request=AsyncMock(), response=mock_response)

        letter, inp, out = await claude_ai.generate_cover_letter("Python Dev", "Description")

        # Verify fallback letter is returned
        assert letter == settings.cover_letter
        
        # Verify user was notified via Telegram notifier
        assert mock_send.called
        sent_text = mock_send.call_args[0][0]
        assert "Внимание: Использована заглушка" in sent_text
        assert "HTTP 429" in sent_text
