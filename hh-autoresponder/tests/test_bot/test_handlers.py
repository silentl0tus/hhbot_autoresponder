import pytest
from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, Chat
from app.config import settings

# Импортируем обработчики напрямую
from app.bot.handlers import btn_settings, btn_messages, admin_only, cmd_start

@pytest.mark.asyncio
async def test_admin_only_decorator_allow(mock_message):
    """Тест: Декоратор admin_only пропускает админа."""
    # Создадим простую тестовую функцию
    @admin_only
    async def dummy_handler(message: Message, **kw):
        await message.answer("OK")

    await dummy_handler(mock_message)
    mock_message.answer.assert_called_once_with("OK")


@pytest.mark.asyncio
async def test_admin_only_decorator_deny(mock_unauth_message):
    """Тест: Декоратор admin_only блокирует посторонних."""
    @admin_only
    async def dummy_handler(message: Message, **kw):
        await message.answer("OK")

    await dummy_handler(mock_unauth_message)
    # Бот должен промолчать (не вызывать оригинальную функцию)
    mock_unauth_message.answer.assert_not_called()


@pytest.mark.asyncio
async def test_btn_settings_handler(mock_message, mocker):
    """Тест: Кнопка 'Настройки' выводит корректный статус."""
    # Мокаем планировщик
    mock_sched = MagicMock()
    mock_sched.is_paused = False
    mock_sched.auto_apply = True
    mocker.patch("app.bot.handlers._scheduler", mock_sched)

    await btn_settings(mock_message)

    # Проверяем, что ответ отправлен
    mock_message.answer.assert_called_once()
    
    # Проверяем содержимое ответа
    call_args = mock_message.answer.call_args[0][0]
    assert "⚙️ <b>Настройки</b>" in call_args
    assert "▶️ Работает" in call_args
    assert "🟢 Авто-отклик ВКЛ" in call_args


@pytest.mark.asyncio
async def test_btn_messages_handler(mock_message, mocker, db_session):
    """Тест: Кнопка 'Сообщения' объединяет данные из API HH и локальной БД (Хабр)."""
    # Мокаем ответ от hh_oauth API
    mock_hh_status = mocker.patch("app.parsers.hh_oauth.hh_oauth.negotiations_status", new_callable=AsyncMock)
    mock_hh_status.return_value = [
        {"tab": "invitations", "company": "Yandex", "title": "Developer"}
    ]

    # Добавляем фейковое сообщение Хабра в базу данных (фикстура db_session)
    from app.models.message import RecruiterMessage
    msg = RecruiterMessage(platform="habr", sender_company="HabrCompany", text="Привет с Хабра")
    db_session.add(msg)
    await db_session.commit()

    # В handlers.py используется async_session() -> context manager
    import contextlib
    @contextlib.asynccontextmanager
    async def mock_async_session():
        yield db_session

    mocker.patch("app.database.async_session", side_effect=mock_async_session)

    # Так как btn_messages шлет несколько сообщений, сбросим счетчик вызовов на моке
    mock_message.answer.reset_mock()

    await btn_messages(mock_message)

    # Проверяем вызовы
    assert mock_message.answer.call_count == 2
    
    # Первое сообщение: "🔄 Проверяю приглашения на hh.ru..."
    first_call = mock_message.answer.call_args_list[0][0][0]
    assert "Проверяю приглашения" in first_call

    # Второе сообщение: основной текст со статистикой
    second_call = mock_message.answer.call_args_list[1][0][0]
    assert "📩 <b>Приглашения от работодателей</b>" in second_call
    assert "Yandex" in second_call  # Из HH API
    assert "HabrCompany" in second_call  # Из БД Хабра
