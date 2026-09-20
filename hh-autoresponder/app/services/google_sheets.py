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
        "invitation": "Приглашение",
        "pending": "Ждем ответа",
        "response": "Ждем ответа",
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
        log.info("google_sheets_sync_input", raw_count=len(parsed_statuses))
        
        for s in parsed_statuses:
            tab = (s.get("tab") or "").lower()
            status = (s.get("status") or "").lower()
            new_status = STATUS_MAPPING.get(tab) or STATUS_MAPPING.get(status)
            if not new_status:
                log.debug("google_sheets_sync_ignored_status", tab=tab, status=status)
                continue
                
            vac_id = str(s.get("vacancy_id") or "")
            if not vac_id:
                href = s.get("vacancy_url", "")
                m = re.search(r"vacancy(?:Id=|/)(\d+)", href)
                if m:
                    vac_id = m.group(1)
            if vac_id:
                update_map[vac_id] = new_status

        log.info("google_sheets_sync_mapped", mapped_count=len(update_map))

        if not update_map:
            return 0

        # Fetch all rows to find matches
        all_values = worksheet.get_all_values()
        if not all_values:
            return 0
            
        header = all_values[0]
        # Попробуем найти колонки по названию, иначе используем старые индексы (1 и 7)
        try:
            url_idx = next(i for i, v in enumerate(header) if "ссылка" in v.lower() and "описание" in v.lower())
        except StopIteration:
            url_idx = 1
            
        try:
            status_idx = next(i for i, v in enumerate(header) if "статус" in v.lower())
        except StopIteration:
            status_idx = 7
            
        log.info("google_sheets_sync_columns", url_col=url_idx, status_col=status_idx)
        
        updates = []
        matched_in_sheet = 0
        
        for i, row in enumerate(all_values):
            if i == 0:  # Header
                continue
            
            url_col = row[url_idx] if len(row) > url_idx else ""
            current_status = row[status_idx] if len(row) > status_idx else ""
                
            m = re.search(r"vacancy(?:Id=|/)(\d+)", url_col)
            if m:
                vac_id = m.group(1)
                new_status = update_map.get(vac_id)
                
                if new_status:
                    matched_in_sheet += 1
                    if new_status != current_status:
                        # Row is i+1 (1-based index)
                        # Column is letter (A=1, B=2, etc.)
                        # Convert status_idx to Excel column letter
                        def col_num_to_letter(n):
                            string = ""
                            while n > 0:
                                n, remainder = divmod(n - 1, 26)
                                string = chr(65 + remainder) + string
                            return string
                            
                        col_letter = col_num_to_letter(status_idx + 1)
                        cell_label = f"{col_letter}{i+1}"
                        updates.append({
                            'range': cell_label,
                            'values': [[new_status]]
                        })

        log.info("google_sheets_sync_sheet_matches", matched=matched_in_sheet, to_update=len(updates))

        if updates:
            worksheet.batch_update(updates, value_input_option='USER_ENTERED')
            log.info("google_sheets_statuses_synced", count=len(updates))
            return len(updates)
        else:
            log.info("google_sheets_statuses_synced", count=0, message="No changes needed")
        return 0

    except Exception as e:
        log.error("google_sheets_sync_error", error=str(e))
        return 0

async def sync_statuses_to_sheets(parsed_statuses: list[dict]) -> int:
    """
    Asynchronously syncs parsed HH.ru statuses to Google Sheets.
    parsed_statuses: list of dicts from hh_oauth.negotiations_status() or hh_playwright.check_negotiations_status()
    Returns count of updated rows.
    """
    return await asyncio.to_thread(_sync_statuses_sync, parsed_statuses)
