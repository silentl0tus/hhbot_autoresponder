import pytest
from app.parsers.habr import HabrParser

@pytest.mark.asyncio
async def test_habr_check_messages(mocker):
    """Тест: HabrParser проксирует вызов в Playwright и возвращает сообщения."""
    parser = HabrParser()
    
    mock_messages = [
        {"platform": "habr", "sender": "Yandex", "text": "Приходите на собес"}
    ]
    
    # Мокаем habr_playwright.check_messages
    mock_pw_check = mocker.patch(
        "app.parsers.habr_playwright.habr_playwright.check_messages",
        return_value=mock_messages
    )
    
    result = await parser.check_messages()
    
    assert len(result) == 1
    assert result[0]["sender"] == "Yandex"
    mock_pw_check.assert_called_once()
