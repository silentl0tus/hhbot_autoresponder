from unittest.mock import AsyncMock, patch

import pytest

from app.ai.claude import ClaudeAI, clean_cover_letter
from app.ai.humanizer import _clean_skill_prompt, get_humanizer_prompt
from app.config import settings


def test_clean_skill_prompt():
    raw_with_yaml = "---\nname: test-skill\nversion: 1.0\n---\nActual prompt content"
    assert _clean_skill_prompt(raw_with_yaml) == "Actual prompt content"

    raw_without_yaml = "Simple prompt without frontmatter"
    assert _clean_skill_prompt(raw_without_yaml) == "Simple prompt without frontmatter"


def test_get_humanizer_prompt_loads_file():
    prompt = get_humanizer_prompt()
    assert prompt
    # Проверяем, что загружен файл скилла с правилами редактирования
    assert "канцеляр" in prompt.lower() or "редактор" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_cover_letter_uses_humanizer_by_default():
    ai = ClaudeAI()

    # Мокаем _call: первый вызов — генерация письма (канцелярского), второй — очеловечивание
    call_mock = AsyncMock()
    first_draft = (
        "В рамках текущей деятельности являюсь Python-разработчиком. "
        "Осуществлял разработку сервисов на FastAPI и PostgreSQL."
    )
    humanized_draft = (
        "Разрабатываю бэкенд на Python: пишу сервисы на FastAPI и проектирую схемы в PostgreSQL. "
        "Готов к техническому интервью."
    )
    call_mock.side_effect = [
        (first_draft, 100, 50),
        (humanized_draft, 80, 40),
    ]

    with (
        patch.object(settings, "ai_enabled", True),
        patch.object(settings, "llm_api_key", "test_key"),
        patch.object(ai, "_call", call_mock),
    ):
        letter, inp, out = await ai.generate_cover_letter("Python Dev", "Description")

        # Должно быть два вызова _call: черновик + очеловечивание
        assert call_mock.call_count == 2
        # Финальный текст должен быть очеловеченным
        assert "Разрабатываю бэкенд на Python" in letter
        assert "В рамках текущей деятельности" not in letter
        assert inp == 180
        assert out == 90


@pytest.mark.asyncio
async def test_generate_cover_letter_explicit_humanize_false():
    ai = ClaudeAI()

    call_mock = AsyncMock()
    first_draft = "Канцелярский черновик письма."
    call_mock.return_value = (first_draft, 100, 50)

    with (
        patch.object(settings, "ai_enabled", True),
        patch.object(settings, "llm_api_key", "test_key"),
        patch.object(ai, "_call", call_mock),
    ):
        letter, inp, out = await ai.generate_cover_letter("Python Dev", "Description", humanize=False)

        # При явном humanize=False вызывается только 1 раз
        assert call_mock.call_count == 1
        assert letter == first_draft
        assert inp == 100
        assert out == 50


@pytest.mark.asyncio
async def test_generate_reply_uses_humanizer():
    ai = ClaudeAI()

    call_mock = AsyncMock()
    first_draft = "В ответ на ваше обращение сообщаю, что готов явиться на собеседование."
    humanized_draft = "Здравствуйте! Готов обсудить детали, в четверг после 15:00 удобно."
    call_mock.side_effect = [
        (first_draft, 50, 20),
        (humanized_draft, 40, 20),
    ]

    with (
        patch.object(settings, "ai_enabled", True),
        patch.object(settings, "llm_api_key", "test_key"),
        patch.object(ai, "_call", call_mock),
    ):
        reply, inp, out = await ai.generate_reply("Приглашаем на интервью", "Backend", "hh")
        assert call_mock.call_count == 2
        assert "Готов обсудить детали" in reply
        assert inp == 90
        assert out == 40


def test_clean_cover_letter_strips_code_blocks_and_preambles():
    raw = "```markdown\nВот очеловеченный текст:\nПривет, пишу по стеку FastAPI.\n```"
    cleaned = clean_cover_letter(raw)
    assert "```" not in cleaned
    assert "Вот очеловеченный текст:" not in cleaned
    assert "Привет, пишу по стеку FastAPI." in cleaned
