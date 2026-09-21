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


@pytest.mark.asyncio
async def test_cover_letter_refusal_pattern_rejected():
    """Тест: Если LLM возвращает сервисное сообщение «не могу обработать» — используется дефолтный шаблон."""
    refusal_text = (
        "К сожалению, я не могу обработать это резюме и создать сопроводительное письмо. "
        "Пожалуйста, укажите конкретную вакансию."
    )
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = AsyncMock()
    mock_response.json = lambda: {
        "choices": [{"message": {"content": refusal_text}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }
    with patch.object(claude_ai._client, "post", return_value=mock_response) as mock_post, \
         patch("app.utils.notifier.send", new_callable=AsyncMock), \
         patch.object(settings, "ai_enabled", True), \
         patch.object(settings, "llm_api_key", "test_key"):

        letter, inp, out = await claude_ai.generate_cover_letter(
            vacancy_title="Performance маркетолог", vacancy_description="Описание"
        )

        # Должен вернуться дефолтный шаблон из .env, а не сервисный текст LLM
        assert letter == settings.cover_letter
        assert refusal_text not in letter


@pytest.mark.asyncio
async def test_cover_letter_valid_letter_not_rejected():
    """Тест: Нормальное письмо проходит все фильтры и отправляется."""
    good_letter = (
        "Имею опыт в performance-маркетинге более 5 лет, работал с Google Ads, Яндекс.Директ и Facebook Ads. "
        "Реализовывал проекты с DRR < 10%. Готов к собеседованию."
    )
    mock_response = AsyncMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = AsyncMock()
    mock_response.json = lambda: {
        "choices": [{"message": {"content": good_letter}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 80},
    }
    with patch.object(claude_ai._client, "post", return_value=mock_response), \
         patch("app.utils.notifier.send", new_callable=AsyncMock), \
         patch.object(settings, "ai_enabled", True), \
         patch.object(settings, "llm_api_key", "test_key"):

        letter, inp, out = await claude_ai.generate_cover_letter(
            vacancy_title="Performance маркетолог", vacancy_description="Описание"
        )

        # Хорошее письмо должно вернуться без изменений
        assert letter == good_letter.strip()
