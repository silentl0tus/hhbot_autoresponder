from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message

# Импортируем обработчики напрямую
from app.bot.handlers import admin_only, btn_messages, btn_settings
from app.config import settings


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
    mock_hh_status.return_value = [{"tab": "invitations", "company": "Yandex", "title": "Developer"}]

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


@pytest.mark.asyncio
async def test_cb_apply_blocks_when_company_limit_reached(mocker, db_session):
    """Тест: cb_apply блокирует генерацию письма и отклик, если лимит в компанию исчерпан."""
    import contextlib

    from aiogram.types import CallbackQuery, User

    from app.bot.handlers import cb_apply
    from app.models.company import Company
    from app.models.vacancy import Vacancy, VacancyStatus

    comp = Company(name="CapCorp", platform="hh")
    db_session.add(comp)
    await db_session.flush()

    v1 = Vacancy(
        platform="hh", external_id="h1", title="V1", url="u1", company_id=comp.id, status=VacancyStatus.APPLIED
    )
    v2 = Vacancy(
        platform="hh", external_id="h2", title="V2", url="u2", company_id=comp.id, status=VacancyStatus.APPLIED
    )
    v3 = Vacancy(
        platform="hh", external_id="h3", title="V3", url="u3", company_id=comp.id, status=VacancyStatus.APPROVED
    )
    db_session.add_all([v1, v2, v3])
    await db_session.commit()

    @contextlib.asynccontextmanager
    async def mock_async_session():
        yield db_session

    mocker.patch("app.bot.handlers.async_session", side_effect=mock_async_session)
    mock_cl = mocker.patch("app.ai.claude.claude_ai.generate_cover_letter", new_callable=AsyncMock)

    cb = AsyncMock(spec=CallbackQuery)
    cb.data = f"apply:{v3.id}"
    admin_id = int(settings.tg_admin_chat_id) if settings.tg_admin_chat_id else 12345
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = admin_id
    cb.message = AsyncMock()
    cb.message.chat = MagicMock(spec=Chat)
    cb.message.chat.id = admin_id
    cb.answer = AsyncMock()

    await cb_apply(cb)

    cb.answer.assert_called_once()
    assert "уже отправлено 2 отклика" in cb.answer.call_args[0][0]
    assert cb.answer.call_args.kwargs.get("show_alert") is True
    mock_cl.assert_not_called()


@pytest.mark.asyncio
async def test_cb_confirm_apply_blocks_when_company_limit_reached(mocker, db_session):
    """Тест: cb_confirm_apply блокирует отправку отклика, если лимит в компанию исчерпан."""
    import contextlib

    from aiogram.types import CallbackQuery, Chat, User

    from app.bot.handlers import cb_confirm_apply
    from app.models.company import Company
    from app.models.vacancy import Vacancy, VacancyStatus

    comp = Company(name="CapCorp2", platform="hh")
    db_session.add(comp)
    await db_session.flush()

    v1 = Vacancy(
        platform="hh", external_id="c1", title="V1", url="u1", company_id=comp.id, status=VacancyStatus.APPLIED
    )
    v2 = Vacancy(
        platform="hh", external_id="c2", title="V2", url="u2", company_id=comp.id, status=VacancyStatus.APPLIED
    )
    v3 = Vacancy(
        platform="hh", external_id="c3", title="V3", url="u3", company_id=comp.id, status=VacancyStatus.APPROVED
    )
    db_session.add_all([v1, v2, v3])
    await db_session.commit()

    @contextlib.asynccontextmanager
    async def mock_async_session():
        yield db_session

    mocker.patch("app.bot.handlers.async_session", side_effect=mock_async_session)

    cb = AsyncMock(spec=CallbackQuery)
    cb.data = f"confirm_apply:{v3.id}"
    admin_id = int(settings.tg_admin_chat_id) if settings.tg_admin_chat_id else 12345
    cb.from_user = MagicMock(spec=User)
    cb.from_user.id = admin_id
    cb.message = AsyncMock()
    cb.message.chat = MagicMock(spec=Chat)
    cb.message.chat.id = admin_id
    cb.answer = AsyncMock()

    await cb_confirm_apply(cb)

    cb.answer.assert_called_once()
    assert "Лимит откликов в компанию" in cb.answer.call_args[0][0]
    assert cb.answer.call_args.kwargs.get("show_alert") is True
