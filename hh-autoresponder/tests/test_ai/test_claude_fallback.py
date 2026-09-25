import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx
from app.config import settings
from app.ai.claude import ClaudeAI, OPENROUTER_FALLBACK_MODELS


@pytest.mark.asyncio
async def test_claude_ai_fallback_on_http_error():
    ai = ClaudeAI()
    original_model = settings.llm_model
    settings.llm_base_url = "https://openrouter.ai/api/v1"
    settings.llm_api_key = "sk-or-dummy-key"
    settings.ai_enabled = True

    # Имитируем падение первой модели (503) и успех второй модели (200)
    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 503
    mock_resp_fail.text = '{"error": "Internal server error"}'
    error_503 = httpx.HTTPStatusError("503 Server Error", request=MagicMock(), response=mock_resp_fail)

    mock_resp_success = MagicMock()
    mock_resp_success.status_code = 200
    mock_resp_success.json.return_value = {
        "choices": [{"message": {"content": "Успешный ответ от резервной модели"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    call_count = 0

    async def mock_post(url, json=None, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise error_503
        return mock_resp_success

    with patch.object(ai._client, "post", side_effect=mock_post):
        text, inp, out = await ai._call(
            system="System prompt",
            user_message="User message",
            model="broken-model:free",
        )

        # Должен автоматически переключиться на первую доступную резервную модель
        assert call_count >= 2
        assert text == "Успешный ответ от резервной модели"
        assert inp == 10
        assert out == 5
        # Проверяем, что активная модель обновилась на рабочую
        assert settings.llm_model == OPENROUTER_FALLBACK_MODELS[0]


@pytest.mark.asyncio
async def test_claude_ai_fallback_all_failed():
    ai = ClaudeAI()
    settings.llm_base_url = "https://openrouter.ai/api/v1"
    settings.llm_api_key = "sk-or-dummy-key"
    settings.ai_enabled = True

    mock_resp_fail = MagicMock()
    mock_resp_fail.status_code = 429
    mock_resp_fail.text = '{"error": "Too Many Requests"}'
    error_429 = httpx.HTTPStatusError("429 Rate Limit", request=MagicMock(), response=mock_resp_fail)

    with patch.object(ai._client, "post", side_effect=error_429):
        text, inp, out = await ai._call(
            system="System prompt",
            user_message="User message",
            model="broken-model:free",
        )
        assert text == ""
        assert inp == 0
        assert out == 0
        assert "HTTP 429" in (ai.last_error or "")
