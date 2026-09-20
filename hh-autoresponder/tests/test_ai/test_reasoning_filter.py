import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.config import settings
from app.ai.claude import ClaudeAI


@pytest.mark.asyncio
async def test_reasoning_is_not_used_when_content_empty():
    ai = ClaudeAI()
    settings.ai_enabled = True
    settings.llm_api_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Имитируем reasoning-модель, которая вернула мысли в поле reasoning, но контент пуст
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning": "We need answer Russian cover letter. Candidate has Python...",
            }
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }

    with patch.object(ai._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        text, inp, out = await ai._call(
            system="System",
            user_message="User",
            model="some-reasoning-model",
        )
        # reasoning категорически не должен попадать в text
        assert text == ""
        assert inp == 0
        assert out == 0
        assert "вернула пустой контент" in (ai.last_error or "")


@pytest.mark.asyncio
async def test_think_tags_are_stripped():
    ai = ClaudeAI()
    settings.ai_enabled = True
    settings.llm_api_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "<think>Let me think about this candidate...</think>Здравствуйте! Откликаюсь на вакансию.",
            }
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 15},
    }

    with patch.object(ai._client, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp
        text, inp, out = await ai._call(
            system="System",
            user_message="User",
            model="some-reasoning-model",
        )
        assert text == "Здравствуйте! Откликаюсь на вакансию."
        assert inp == 10
        assert out == 15


@pytest.mark.asyncio
async def test_cover_letter_rejects_english_reasoning_leak():
    ai = ClaudeAI()
    settings.ai_enabled = True
    settings.llm_api_key = "test-key"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Модель вывела рассуждения прямо в content на английском
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "We need answer Russian cover letter. Candidate has Python, FastAPI...",
            }
        }],
        "usage": {"prompt_tokens": 50, "completion_tokens": 50},
    }

    with patch.object(ai._client, "post", new_callable=AsyncMock) as mock_post, \
         patch("app.utils.notifier.send", new_callable=AsyncMock) as mock_notify:
        mock_post.return_value = mock_resp
        letter, inp, out = await ai.generate_cover_letter(
            vacancy_title="Python Dev",
            vacancy_description="Requirements...",
        )
        # Должен сработать fallback на шаблон из settings.cover_letter
        assert letter == settings.cover_letter
        assert mock_notify.called


def test_clean_cover_letter_removes_intro_phrases():
    from app.ai.claude import clean_cover_letter

    raw_text = (
        "Откликаюсь на вакансию Python-разработчика в ООО «АФЛТ-Системс».\n\n"
        "- 6 лет опыта в системной интеграции и Linux CLI.\n"
        "- Разрабатывал сервисы на FastAPI и Docker.\n\n"
        "Готов обсудить детали на техническом интервью."
    )
    cleaned = clean_cover_letter(raw_text)
    assert "Откликаюсь на вакансию" not in cleaned
    assert "- 6 лет опыта" in cleaned
    assert "Готов обсудить детали" in cleaned


def test_clean_cover_letter_removes_greeting_with_intro():
    from app.ai.claude import clean_cover_letter

    raw_text = (
        "Здравствуйте! Откликаюсь на вакансию AI Engineer в Сбер.\n\n"
        "- Опыт работы с Qdrant и LangGraph.\n"
        "- Контейнеризация в Docker Compose."
    )
    cleaned = clean_cover_letter(raw_text)
    assert "Откликаюсь на вакансию" not in cleaned
    assert "- Опыт работы с Qdrant" in cleaned

