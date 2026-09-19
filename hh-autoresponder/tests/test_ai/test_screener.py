import pytest
from unittest.mock import AsyncMock, patch
from pathlib import Path
from app.ai.claude import claude_ai
from app.config import settings
from app.parsers.max_screener import MaxScreenerParser


@pytest.mark.asyncio
async def test_generate_screener_answer_fallback():
    with patch.object(settings, "ai_enabled", False):
        answer, inp, out = await claude_ai.generate_screener_answer("Какой у вас опыт с FastAPI?")
        assert "Подтверждаю интерес" in answer
        assert inp == 0
        assert out == 0


@pytest.mark.asyncio
async def test_generate_screener_answer_success():
    with patch.object(settings, "ai_enabled", True), \
         patch.object(settings, "llm_api_key", "test_key"), \
         patch.object(claude_ai, "_call", new_callable=AsyncMock) as mock_call:
        
        mock_call.return_value = ("Более 3 лет коммерческой разработки на FastAPI и PostgreSQL.", 50, 20)
        
        answer, inp, out = await claude_ai.generate_screener_answer(
            question="Какой у вас опыт с FastAPI?",
            humanize=False
        )
        assert "FastAPI" in answer
        assert inp == 50
        assert out == 20


def test_max_screener_session_check(tmp_path: Path):
    parser = MaxScreenerParser(storage_path=tmp_path / "non_existent.json")
    assert parser.is_session_available() is False

    valid_file = tmp_path / "valid_state.json"
    valid_file.write_text('{"cookies": []}', encoding="utf-8")
    parser_valid = MaxScreenerParser(storage_path=valid_file)
    assert parser_valid.is_session_available() is True


def test_clean_screener_answer():
    from app.ai.claude import clean_screener_answer

    raw_output = (
        "Вот вариант, как это мог бы написать живой человек:\n\n"
        "Нет, с кампаниями и uplift-моделированием не работал. Мой опыт в ML — это Computer Vision, "
        "RAG-системы и классификация на PyTorch и scikit-learn.\n\n"
        "---\n\n"
        "**Ещё вариант, если нужно короче и разговорнее:**\n\n"
        "Нет, с uplift и кампейнингом дел не имел."
    )

    cleaned = clean_screener_answer(raw_output)
    assert "Вот вариант" not in cleaned
    assert "Ещё вариант" not in cleaned
    assert "---" not in cleaned
    assert cleaned.startswith("Нет, с кампаниями и uplift-моделированием не работал.")
    assert "scikit-learn." in cleaned

