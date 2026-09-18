import os
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.models.base import Base

# Устанавливаем переменные окружения ДО импорта настроек
os.environ["BOT_TOKEN"] = "test:token"
os.environ["TG_ADMIN_CHAT_ID"] = "12345"

@pytest_asyncio.fixture
async def db_session():
    # Создаем in-memory SQLite базу для тестов
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    
    async with session_maker() as session:
        yield session
        
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

from unittest.mock import AsyncMock, MagicMock
from aiogram.types import Message, Chat
from app.config import settings

@pytest.fixture
def mock_message(mocker):
    """Создает мок объекта Message от лица администратора."""
    msg = AsyncMock(spec=Message)
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = int(settings.tg_admin_chat_id) if settings.tg_admin_chat_id else 12345
    msg.answer = AsyncMock()
    return msg

@pytest.fixture
def mock_unauth_message(mocker):
    """Создает мок объекта Message от лица чужого пользователя."""
    msg = AsyncMock(spec=Message)
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = 999999999
    msg.answer = AsyncMock()
    return msg
