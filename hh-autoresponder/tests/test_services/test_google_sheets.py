import pytest
from unittest.mock import patch, MagicMock

from app.services.google_sheets import append_application, sync_statuses_to_sheets

@pytest.mark.asyncio
@patch("app.services.google_sheets.gspread")
@patch("app.services.google_sheets.Credentials")
@patch("app.services.google_sheets.Path")
@patch("app.services.google_sheets.settings")
async def test_append_application(mock_settings, mock_path, mock_credentials, mock_gspread):
    # Setup mocks
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
    
    # Run test
    await append_application(
        date_str="2026-09-19",
        title="Python Developer",
        company="Test Company",
        url="https://hh.ru/vacancy/123",
        status="Ждем ответа",
        cover_letter="My cover letter",
        ai_score=45.0
    )
    
    # Verify
    mock_worksheet.append_row.assert_called_once()
    called_args = mock_worksheet.append_row.call_args[0][0]
    
    assert called_args[0] == "2026-09-19"
    assert called_args[1] == "https://hh.ru/vacancy/123"
    assert called_args[2] == "Python Developer"
    assert called_args[3] == "Test Company"
    assert called_args[4] == ""  # Контакт
    assert called_args[5] == "Автоотклик (hh)"
    assert called_args[6] == "My cover letter"
    assert called_args[7] == "Ждем ответа"
    assert called_args[8] == "AI Score: 45"

@pytest.mark.asyncio
@patch("app.services.google_sheets.gspread")
@patch("app.services.google_sheets.Credentials")
@patch("app.services.google_sheets.Path")
@patch("app.services.google_sheets.settings")
async def test_sync_statuses_to_sheets(mock_settings, mock_path, mock_credentials, mock_gspread):
    # Setup mocks
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
    
    # Mock worksheet data
    mock_worksheet.get_all_values.return_value = [
        ["Дата", "Ссылка", "Позиция", "Компания", "Контакт", "CV", "CL", "Статус", "Коммент"],
        ["2026-09-18", "https://hh.ru/vacancy/111", "Dev", "Co", "", "CV", "CL", "Ждем ответа", ""],
        ["2026-09-19", "https://hh.ru/vacancy/222", "Dev", "Co", "", "CV", "CL", "Ждем ответа", ""]
    ]
    
    parsed_statuses = [
        {"href": "https://hh.ru/vacancy/111", "tab": "discard"},       # Should be Отказ
        {"href": "https://hh.ru/vacancy/222", "tab": "invitations"},   # Should be Приглашение
        {"href": "https://hh.ru/vacancy/333", "tab": "pending"}        # Not in sheet, skipped
    ]
    
    # Run test
    await sync_statuses_to_sheets(parsed_statuses)
    
    # Verify
    mock_worksheet.batch_update.assert_called_once()
    called_updates = mock_worksheet.batch_update.call_args[0][0]
    
    assert len(called_updates) == 2
    
    # Row 1 is index 0 in list but row 2 in Sheets API
    assert called_updates[0]['range'] == "H2"
    assert called_updates[0]['values'] == [["Отказ"]]
    
    assert called_updates[1]['range'] == "H3"
    assert called_updates[1]['values'] == [["Приглашение"]]
