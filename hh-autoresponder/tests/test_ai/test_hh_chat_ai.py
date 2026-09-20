import pytest
from unittest.mock import AsyncMock, patch
from app.ai.claude import claude_ai


@pytest.mark.asyncio
async def test_generate_hh_answer_with_options():
    mock_llm_response = (
        "RECOMMENDED_OPTION: Только учебные проекты\n"
        "В коммерческой разработке с n8n не работал, но проектировал локальные конвейеры автоматизации "
        "на Python и FastAPI в связке с RAG и Qdrant."
    )

    with patch("app.ai.claude._ai_ready", return_value=True):
        with patch.object(claude_ai, "_call", new=AsyncMock(return_value=(mock_llm_response, 50, 40))):
            answer, rec_opt, inp, out = await claude_ai.generate_hh_answer(
                question="Какой у вас коммерческий опыт с n8n?",
                options=["Нет опыта", "Только учебные проекты", "Более 1 года", "Более 3 лет"],
                vacancy_title="Integration / AI Developer",
                company_name="Мустанг",
                humanize=False,
            )

            assert rec_opt == "Только учебные проекты"
            assert "В коммерческой разработке с n8n не работал" in answer


@pytest.mark.asyncio
async def test_generate_hh_answer_fallback():
    with patch("app.ai.claude._ai_ready", return_value=False):
        answer, rec_opt, inp, out = await claude_ai.generate_hh_answer(
            question="Какой у вас опыт?",
            options=["Опыт 1", "Опыт 2"],
        )
        assert rec_opt == "Опыт 1"
        assert len(answer) > 0
