import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.parsers.hh_chat import HHChatParser, is_rejection_text


def test_is_session_available():
    parser = HHChatParser(storage_path="non_existent_file.json")
    assert parser.is_session_available() is False


def test_is_rejection_text():
    assert is_rejection_text("К сожалению, в настоящий момент мы не готовы пригласить вас") is True
    assert is_rejection_text("Вынуждены отказать по вашей кандидатуре") is True
    assert is_rejection_text("Здравствуйте! Какой у вас опыт в Python?") is False
    assert is_rejection_text("") is False


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
            "is_rejection": False,
        },
        {
            "chat_id": "67890",
            "title": "Data Scientist",
            "company": "Банк",
            "last_message": "К сожалению, мы вынуждены отказать",
            "unread_count": 1,
            "has_unread": True,
            "is_rejection": True,
        }
    ]
    parser._page.evaluate = AsyncMock(return_value=mock_chats_data)

    chats = await parser.get_unread_or_active_chats()
    assert len(chats) == 2
    assert chats[0]["chat_id"] == "12345"
    assert chats[0]["is_rejection"] is False
    assert chats[1]["chat_id"] == "67890"
    assert chats[1]["is_rejection"] is True


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
        "is_closed": False,
        "is_rejection": False,
    }
    parser._page.evaluate = AsyncMock(return_value=mock_inspect_data)

    details = await parser.inspect_chat("12345")
    assert details["chat_id"] == "12345"
    assert details["is_last_from_me"] is False
    assert details["last_incoming_text"] == "Какой у вас опыт в Python?"
    assert details["options"] == ["Более 3 лет"]
    assert details["is_rejection"] is False
    assert details["is_closed"] is False


@pytest.mark.asyncio
async def test_inspect_chat_with_rejection():
    parser = HHChatParser(storage_path="dummy.json")
    parser._page = AsyncMock()
    parser._page.is_closed = MagicMock(return_value=False)
    parser._page.url = "https://hh.ru/chat/99999"

    mock_inspect_data = {
        "chat_id": "99999",
        "vacancy": "Python Developer",
        "company": "Компания",
        "last_incoming_text": "К сожалению, в настоящий момент мы не готовы сделать вам предложение.",
        "last_incoming_author": "Рекрутер",
        "is_last_from_me": False,
        "options": [],
        "history": [],
        "is_closed": True,
        "is_rejection": True,
    }
    parser._page.evaluate = AsyncMock(return_value=mock_inspect_data)

    details = await parser.inspect_chat("99999")
    assert details["is_rejection"] is True
    assert details["is_closed"] is True
