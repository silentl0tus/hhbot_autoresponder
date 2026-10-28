from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from app.config import Settings
from app.parsers.hh_playwright import HHPlaywright


@pytest.mark.asyncio
async def test_dynamic_prompts_radio_buttons():
    """Проверяем, что в ai_system для радиокнопок используются данные из settings, а не хардкод."""
    parser = HHPlaywright()

    mock_page = AsyncMock()
    mock_page.query_selector_all.return_value = []
    # Задаем группу радиокнопок без очевидных триггеров ("все", "удален"), чтобы сработал AI fallback
    mock_page.evaluate.return_value = {
        "travel": {
            "question": "Готовность к разъездной работе",
            "options": [
                {"label": "Готов 100% времени", "id": "opt1", "value": "1"},
                {"label": "Категорически не согласен", "id": "opt2", "value": "2"},
            ],
        }
    }
    mock_page.query_selector.return_value = None
    mock_handle = AsyncMock()
    mock_handle.evaluate.return_value = False
    mock_page.evaluate_handle.return_value = mock_handle

    custom_settings = {
        "desired_position": "Golang Backend Developer",
        "desired_salary_min": 220000,
        "english_level": "C1",
        "relocation_ready": True,
        "business_trips_ready": False,
        "notice_period": "3 недели",
        "resume_text": "Опыт Golang 5 лет, PostgreSQL, Kubernetes.",
    }

    ai_calls = []

    async def mock_call(system, user, max_tokens=20, model=None):
        ai_calls.append((system, user))
        return ("1", None, None)

    with (
        patch("app.ai.claude.claude_ai._call", side_effect=mock_call),
        patch("app.config.settings.desired_position", custom_settings["desired_position"]),
        patch("app.config.settings.desired_salary_min", custom_settings["desired_salary_min"]),
        patch("app.config.settings.english_level", custom_settings["english_level"]),
        patch("app.config.settings.relocation_ready", custom_settings["relocation_ready"]),
        patch("app.config.settings.business_trips_ready", custom_settings["business_trips_ready"]),
        patch("app.config.settings.notice_period", custom_settings["notice_period"]),
        patch.object(Settings, "resume_text", new_callable=PropertyMock, return_value=custom_settings["resume_text"]),
    ):
        await parser._fill_response_form(mock_page, "letter", "https://hh.ru/vacancy/111", pass_tests=True)

    assert len(ai_calls) == 1
    system_prompt, _ = ai_calls[0]

    # Проверяем динамические данные
    assert "Golang Backend Developer" in system_prompt
    assert "220 тыс. руб." in system_prompt
    assert "C1" in system_prompt
    assert "Готов к переезду" in system_prompt
    assert "НЕ готов к командировкам" in system_prompt
    assert "3 недели" in system_prompt
    assert "Опыт Golang 5 лет" in system_prompt

    # Проверяем, что хардкод старого профиля полностью отсутствует
    assert "НИИАС" not in system_prompt
    assert "СамГУПС" not in system_prompt
    assert "Эльбрус" not in system_prompt
    assert "7.5+" not in system_prompt


@pytest.mark.asyncio
async def test_dynamic_prompts_textarea_questions():
    """Проверяем, что в user_msg для текстовых анкет используются данные из settings, а не хардкод."""
    parser = HHPlaywright()

    mock_ta = AsyncMock()
    mock_ta.is_visible.return_value = True
    mock_ta.get_attribute.side_effect = lambda attr: ""
    mock_ta.evaluate.return_value = "Какой у вас опыт работы и последнее место?"

    mock_page = AsyncMock()
    # query_selector_all("textarea") возвращает один вопрос
    mock_page.query_selector_all.return_value = [mock_ta]
    mock_page.evaluate.return_value = {}  # no radios
    mock_page.query_selector.return_value = None
    mock_handle = AsyncMock()
    mock_handle.evaluate.return_value = False
    mock_page.evaluate_handle.return_value = mock_handle

    custom_settings = {
        "desired_position": "Product Manager",
        "desired_salary_min": 180000,
        "english_level": "B1",
        "relocation_ready": False,
        "business_trips_ready": True,
        "notice_period": "готов выйти завтра",
        "resume_text": "Управление продуктами в FinTech, рост конверсий в 2 раза.",
    }

    ai_calls = []

    async def mock_call(system, user, max_tokens=2000, model=None):
        ai_calls.append((system, user))
        return ('{"1": "Мой опыт в FinTech..."}', None, None)

    with (
        patch("app.ai.claude.claude_ai._call", side_effect=mock_call),
        patch("app.config.settings.desired_position", custom_settings["desired_position"]),
        patch("app.config.settings.desired_salary_min", custom_settings["desired_salary_min"]),
        patch("app.config.settings.english_level", custom_settings["english_level"]),
        patch("app.config.settings.relocation_ready", custom_settings["relocation_ready"]),
        patch("app.config.settings.business_trips_ready", custom_settings["business_trips_ready"]),
        patch("app.config.settings.notice_period", custom_settings["notice_period"]),
        patch.object(Settings, "resume_text", new_callable=PropertyMock, return_value=custom_settings["resume_text"]),
    ):
        await parser._fill_response_form(mock_page, "letter", "https://hh.ru/vacancy/222", pass_tests=True)

    assert len(ai_calls) == 1
    system_prompt, user_prompt = ai_calls[0]

    # В user_msg должны быть динамические параметры
    assert "180 тыс. руб." in user_prompt
    assert "НЕ готов к переезду" in user_prompt
    assert "готов к командировкам" in user_prompt
    assert "B1" in user_prompt
    assert "готов выйти завтра" in user_prompt

    # В system должно передаваться резюме
    assert "Управление продуктами в FinTech" in system_prompt

    # Проверяем, что в промптах нет хардкода прежнего кандидата
    assert "НИИАС" not in user_prompt
    assert "СамГУПС" not in user_prompt
    assert "Эльбрус" not in user_prompt
    assert "7.5+" not in user_prompt
    mock_ta.fill.assert_called_once_with("Мой опыт в FinTech...")
