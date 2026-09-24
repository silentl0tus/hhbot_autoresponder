"""Tests for chat enrichment logic in _job_sync_sheets and
last_message flow through to Google Sheets."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.google_sheets import sync_statuses_to_sheets


# ── Unit tests: enrichment logic (inline, no scheduler needed) ────────


def _enrich_statuses(statuses: list[dict], chats: list[dict]) -> int:
    """Replicate the enrichment logic from scheduler._job_sync_sheets
    so we can test it in isolation without starting APScheduler."""
    chat_map_exact: dict[tuple[str, str], str] = {}
    chat_map_company: dict[str, str] = {}
    for c in chats:
        comp = (c.get("company") or "").lower().strip()
        title = (c.get("title") or "").lower().strip()
        msg = (c.get("last_message") or "").strip()
        if not msg:
            continue
        if comp and title:
            chat_map_exact[(comp, title)] = msg
        if comp:
            chat_map_company[comp] = msg

    enriched = 0
    for s in statuses:
        comp = (s.get("company") or "").lower().strip()
        title = (s.get("title") or "").lower().strip()
        chat_msg = (
            chat_map_exact.get((comp, title))
            or chat_map_company.get(comp)
        )
        if chat_msg:
            s["last_message"] = chat_msg
            enriched += 1
    return enriched


class TestChatEnrichment:
    """Tests for the chat-to-negotiation matching logic."""

    def test_exact_company_title_match(self):
        statuses = [
            {"company": "Яндекс", "title": "Backend Developer", "last_message": ""},
            {"company": "Яндекс", "title": "Frontend Developer", "last_message": ""},
        ]
        chats = [
            {"company": "Яндекс", "title": "Backend Developer",
             "last_message": "Приглашаем на собеседование!"},
            {"company": "Яндекс", "title": "Frontend Developer",
             "last_message": "К сожалению, отказ."},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 2
        assert statuses[0]["last_message"] == "Приглашаем на собеседование!"
        assert statuses[1]["last_message"] == "К сожалению, отказ."

    def test_company_only_fallback(self):
        """When title doesn't match, falls back to company-only match."""
        statuses = [
            {"company": "Сбер", "title": "Python разработчик", "last_message": ""},
        ]
        chats = [
            {"company": "Сбер", "title": "Другая вакансия",
             "last_message": "Здравствуйте, когда вам удобно?"},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 1
        assert statuses[0]["last_message"] == "Здравствуйте, когда вам удобно?"

    def test_case_insensitive_matching(self):
        statuses = [
            {"company": "ООО Рога И Копыта", "title": "Dev", "last_message": ""},
        ]
        chats = [
            {"company": "ооо рога и копыта", "title": "dev",
             "last_message": "Тестовое задание"},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 1

    def test_overwrites_existing_last_message(self):
        """Chat data should overwrite the negotiations page preview
        (which is often the user's own cover letter)."""
        statuses = [
            {"company": "Acme", "title": "QA",
             "last_message": "Моё сопроводительное письмо"},
        ]
        chats = [
            {"company": "Acme", "title": "QA",
             "last_message": "Мы рассмотрели вашу кандидатуру"},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 1
        assert statuses[0]["last_message"] == "Мы рассмотрели вашу кандидатуру"

    def test_empty_chat_message_skipped(self):
        statuses = [
            {"company": "X", "title": "Y", "last_message": "old msg"},
        ]
        chats = [
            {"company": "X", "title": "Y", "last_message": ""},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 0
        assert statuses[0]["last_message"] == "old msg"

    def test_no_matching_company(self):
        statuses = [
            {"company": "CompanyA", "title": "Dev", "last_message": ""},
        ]
        chats = [
            {"company": "CompanyB", "title": "Dev",
             "last_message": "Привет!"},
        ]
        enriched = _enrich_statuses(statuses, chats)
        assert enriched == 0
        assert statuses[0]["last_message"] == ""


# ── Integration test: last_message -> Google Sheets ──────────────────


@pytest.mark.asyncio
@patch("app.services.google_sheets.gspread")
@patch("app.services.google_sheets.Credentials")
@patch("app.services.google_sheets.Path")
@patch("app.services.google_sheets.settings")
async def test_last_message_written_to_sheet(
    mock_settings, mock_path, mock_credentials, mock_gspread
):
    """Verify that last_message from parsed_statuses ends up as a
    batch_update call targeting the 'Последнее сообщение' column."""
    from app.services.google_sheets import reset_client, LOG_HEADER
    reset_client()

    mock_settings.google_sheet_url = "https://docs.google.com/spreadsheets/d/test"
    mock_settings.google_sheets_credentials_path = "test_creds.json"

    mock_path_instance = MagicMock()
    mock_path_instance.exists.return_value = True
    mock_path.return_value = mock_path_instance

    mock_gc = MagicMock()
    mock_sh = MagicMock()
    mock_worksheet = MagicMock()

    mock_gspread.authorize.return_value = mock_gc
    mock_gc.open_by_url.return_value = mock_sh
    mock_sh.get_worksheet.return_value = mock_worksheet

    # Sheet already has the full header and one row
    header = list(LOG_HEADER)
    mock_worksheet.get_all_values.return_value = [
        header,
        [
            "2026-09-20",                       # Дата
            "https://hh.ru/vacancy/555",         # Ссылка
            "Python Dev",                        # Позиция
            "TestCorp",                          # Компания
            "",                                  # Контакт
            "",                                  # CV
            "",                                  # CL
            "Ждем ответа",                       # Статус
            "",                                  # Комментарий
            "555",                               # Vacancy ID
            "hh",                                # Платформа
            "",                                  # Зарплата
            "",                                  # Последнее сообщение
        ],
    ]

    parsed = [
        {
            "vacancy_url": "https://hh.ru/vacancy/555",
            "vacancy_id": "555",
            "tab": "invitations",
            "last_message": "Приглашаем вас на интервью в понедельник!",
        },
    ]

    result = await sync_statuses_to_sheets(parsed)
    assert result.updated >= 1

    updates = mock_worksheet.batch_update.call_args[0][0]
    # Find the update that targets the last_message column (M = column 13)
    msg_col_letter = "M"  # 13th column = "Последнее сообщение"
    msg_updates = [u for u in updates if u["range"].startswith(msg_col_letter)]
    assert len(msg_updates) == 1
    assert msg_updates[0]["values"] == [["Приглашаем вас на интервью в понедельник!"]]
