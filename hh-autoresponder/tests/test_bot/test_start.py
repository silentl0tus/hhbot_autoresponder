import pytest
from app.bot.handlers import cmd_start

@pytest.mark.asyncio
async def test_cmd_start_handler(mock_message, mocker):
    """Тест: Команда /start выводит меню и статистику."""
    # Мокаем работу с базой для статистики
    mocker.patch("app.bot.handlers.async_session")
    
    await cmd_start(mock_message)
    
    # Бот должен отправить меню
    mock_message.answer.assert_called_once()
    
    # Проверяем, что в ответе есть приветствие
    call_args = mock_message.answer.call_args[0][0]
    assert "👋 <b>Job Hunter Bot v1.5.1</b>" in call_args
