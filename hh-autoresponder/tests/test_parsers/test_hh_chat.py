import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.parsers.hh_chat import HHChatParser


def test_is_session_available():
    parser = HHChatParser(storage_path="non_existent_file.json")
    assert parser.is_session_available() is False


@pytest.mark.asyncio
async def test_get_unread_or_active_chats():
    parser = HHChatParser(storage_path="dummy.json")
    parser._page = AsyncMock()
    parser._page.is_closed = MagicMock(return_value=False)
    parser._page.url = "https://hh.ru/chat"

    mock_chats_data = [
        {
            "chat_id": "12345",
            "title": "Разработчик Python",
            "company": "ООО Тест",
            "last_message": "Здравствуйте! Ответьте на вопрос",
            "unread_count": 1,
            "has_unread": True,
        }
    ]
    parser._page.evaluate = AsyncMock(return_value=mock_chats_data)

    chats = await parser.get_unread_or_active_chats()
    assert len(chats) == 1
    assert chats[0]["chat_id"] == "12345"
    assert chats[0]["company"] == "ООО Тест"
    assert chats[0]["has_unread"] is True


@pytest.mark.asyncio
async def test_inspect_chat():
    parser = HHChatParser(storage_path="dummy.json")
    parser._page = AsyncMock()
    parser._page.is_closed = MagicMock(return_value=False)
    parser._page.url = "https://hh.ru/chat/12345"

    mock_inspect_data = {
        "chat_id": "12345",
        "vacancy": "Python Developer",
        "company": "Мустанг",
        "last_incoming_text": "Какой у вас опыт в Python?",
        "last_incoming_author": "Робот-рекрутер",
        "is_last_from_me": False,
        "options": ["Более 3 лет"],
        "history": "Вопрос рекрутера...",
    }
    parser._page.evaluate = AsyncMock(return_value=mock_inspect_data)

    details = await parser.inspect_chat("12345")
    assert details["chat_id"] == "12345"
    assert details["is_last_from_me"] is False
    assert details["last_incoming_text"] == "Какой у вас опыт в Python?"
    assert details["options"] == ["Более 3 лет"]
