import asyncio
import sys, os, re
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright
STATUS_MAPPING = {
    "discard": "Отказ",
    "invitations": "Приглашение",
    "pending": "Ждем ответа",
}

async def debug_sync():
    hh = HHPlaywright()
    parsed_statuses = await hh.check_negotiations_status()
    update_map = {}
    for s in parsed_statuses:
        tab = s.get("tab")
        new_status = STATUS_MAPPING.get(tab)
        if not new_status: continue
        href = s.get("vacancy_url", "")
        m = re.search(r"vacancy(?:Id=|/)(\d+)", href)
        if m:
            update_map[m.group(1)] = new_status
            print(f"Update map: {m.group(1)} -> {new_status}")
    
    from google.oauth2.service_account import Credentials
    import gspread
    from app.config import settings
    from pathlib import Path
    
    creds_path = Path(settings.google_sheets_credentials_path)
    credentials = Credentials.from_service_account_file(str(creds_path), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(credentials)
    sh = gc.open_by_url(settings.google_sheet_url)
    worksheet = sh.get_worksheet(0)
    all_values = worksheet.get_all_values()
    
    updates = []
    for i, row in enumerate(all_values):
        if i == 0: continue
        url_col = row[1] if len(row) > 1 else ""
        current_status = row[7] if len(row) > 7 else ""
        
        # In case the row had < 8 columns, it was skipped by the original code!
        if len(row) >= 8:
            m = re.search(r"vacancy/(\d+)", url_col)
            if m:
                vac_id = m.group(1)
                new_status = update_map.get(vac_id)
                if vac_id in update_map:
                    print(f"Row {i+1} [len={len(row)}]: vac_id={vac_id}, cur='{current_status}', new='{new_status}'")
                if new_status and new_status != current_status:
                    updates.append(f"H{i+1} -> {new_status}")
    print(f"Updates: {updates}")

if __name__ == "__main__":
    asyncio.run(debug_sync())
