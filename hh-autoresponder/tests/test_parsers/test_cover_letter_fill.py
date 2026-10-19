from unittest.mock import AsyncMock

import pytest

from app.parsers.hh_playwright import HHPlaywright


@pytest.mark.asyncio
async def test_fill_response_form_resolves_callable_cover_letter():
    """Тест: _fill_response_form безусловно вызывает callable cover_letter и заполняет textarea."""
    parser = HHPlaywright()

    mock_page = AsyncMock()
    # No question textareas
    mock_page.query_selector_all.return_value = []
    # No radio groups
    mock_page.evaluate.return_value = {}

    mock_letter_area = AsyncMock()
    mock_letter_area.is_visible.return_value = True

    # When querying for cover letter selectors, return mock_letter_area
    mock_page.query_selector.return_value = mock_letter_area

    called = False

    async def sample_letter():
        nonlocal called
        called = True
        return "Привет, вот моё сопроводительное письмо!"

    await parser._fill_response_form(mock_page, sample_letter, "https://hh.ru/vacancy/123456")

    # Проверяем, что генератор письма БЫЛ вызван
    assert called is True
    # Проверяем, что textarea была заполнена
    mock_letter_area.fill.assert_called_once_with("Привет, вот моё сопроводительное письмо!")


@pytest.mark.asyncio
async def test_fill_response_form_handles_callable_error():
    """Тест: ошибка при генерации письма не ломает заполнение формы."""
    parser = HHPlaywright()

    mock_page = AsyncMock()
    mock_page.query_selector_all.return_value = []
    mock_page.evaluate.return_value = {}
    mock_page.query_selector.return_value = None
    mock_handle = AsyncMock()
    mock_handle.evaluate.return_value = False
    mock_page.evaluate_handle.return_value = mock_handle

    async def failing_letter():
        raise RuntimeError("LLM API failed")

    # Не должно бросать исключение
    await parser._fill_response_form(mock_page, failing_letter, "https://hh.ru/vacancy/123456")
