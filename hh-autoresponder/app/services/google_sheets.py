import asyncio
import gspread
import structlog
from pathlib import Path
from google.oauth2.service_account import Credentials

from app.config import settings

log = structlog.get_logger()

# Scopes needed for Google Sheets and Drive
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def _append_row_sync(row_data: list):
    """Synchronous function to append a row to Google Sheets."""
    if not settings.google_sheet_url:
        return

    creds_path = Path(settings.google_sheets_credentials_path)
    if not creds_path.exists():
        log.warning("google_sheets_credentials_not_found", path=str(creds_path))
        return

    try:
        credentials = Credentials.from_service_account_file(
            str(creds_path), scopes=SCOPES
        )
        gc = gspread.authorize(credentials)
        
        # Open spreadsheet by URL
        sh = gc.open_by_url(settings.google_sheet_url)
        worksheet = sh.get_worksheet(0)  # Use the first worksheet
        
        # Append the row
        worksheet.append_row(row_data)
        log.info("google_sheets_row_appended", url=settings.google_sheet_url)
    except Exception as e:
        log.error("google_sheets_append_error", error=str(e))

async def append_application(
    date_str: str,
    title: str,
    company: str,
    url: str,
    status: str,
    cover_letter: str,
    ai_score: float = 0.0
):
    """
    Asynchronously appends an application record to Google Sheets.
    """
    if not settings.google_sheet_url:
        return
        
    score_str = f"AI Score: {int(ai_score)}" if ai_score is not None else ""
    row_data = [
        date_str,             # Дата
        url,                  # Ссылка на описание
        title,                # Позиция
        company,              # Компания
        "",                   # Контакт
        "Автоотклик (hh)",    # CV (ссылка)
        cover_letter,         # CL (ссылка)
        status,               # Статус
        score_str             # Комментарий
    ]
    
    # Run the synchronous network call in a separate thread
    await asyncio.to_thread(_append_row_sync, row_data)

def _sync_statuses_sync(parsed_statuses: list[dict]):
    """Synchronous function to update statuses in Google Sheets using batch_update."""
    if not settings.google_sheet_url:
        return

    creds_path = Path(settings.google_sheets_credentials_path)
    if not creds_path.exists():
        return

    import re

    STATUS_MAPPING = {
        "discard": "Отказ",
        "invitations": "Приглашение",
        "pending": "Ждем ответа"
    }

    try:
        credentials = Credentials.from_service_account_file(
            str(creds_path), scopes=SCOPES
        )
        gc = gspread.authorize(credentials)
        sh = gc.open_by_url(settings.google_sheet_url)
        worksheet = sh.get_worksheet(0)
        
        # Build mapping of vacancy_id -> status
        update_map = {}
        for s in parsed_statuses:
            tab = s.get("tab")
            new_status = STATUS_MAPPING.get(tab)
            if not new_status:
                continue
                
            href = s.get("vacancy_url", "")
            m = re.search(r"vacancy(?:Id=|/)(\d+)", href)
            if m:
                vac_id = m.group(1)
                update_map[vac_id] = new_status

        if not update_map:
            return

        # Fetch all rows to find matches
        all_values = worksheet.get_all_values()
        
        updates = []
        for i, row in enumerate(all_values):
            if i == 0:  # Header
                continue
            
            url_col = row[1] if len(row) > 1 else ""
            current_status = row[7] if len(row) > 7 else ""
                
            m = re.search(r"vacancy(?:Id=|/)(\d+)", url_col)
            if m:
                vac_id = m.group(1)
                new_status = update_map.get(vac_id)
                
                if new_status and new_status != current_status:
                    # Row is i+1 (1-based index)
                    # Column is H (8th column)
                    cell_label = f"H{i+1}"
                    updates.append({
                        'range': cell_label,
                        'values': [[new_status]]
                    })

        if updates:
            worksheet.batch_update(updates)
            log.info("google_sheets_statuses_synced", count=len(updates))

    except Exception as e:
        log.error("google_sheets_sync_error", error=str(e))

async def sync_statuses_to_sheets(parsed_statuses: list[dict]):
    """
    Asynchronously syncs parsed HH.ru statuses to Google Sheets.
    parsed_statuses: list of dicts from hh_playwright.check_negotiations_status()
    """
    await asyncio.to_thread(_sync_statuses_sync, parsed_statuses)
