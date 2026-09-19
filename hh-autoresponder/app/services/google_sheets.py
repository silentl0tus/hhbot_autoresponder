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
    salary: str,
    work_format: str,
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
        
    row_data = [
        date_str,
        title,
        company,
        salary,
        work_format,
        url,
        status,
        cover_letter,
        str(int(ai_score)) if ai_score is not None else ""
    ]
    
    # Run the synchronous network call in a separate thread
    await asyncio.to_thread(_append_row_sync, row_data)
