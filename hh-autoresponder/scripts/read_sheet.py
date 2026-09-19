import sys, os
from pathlib import Path
from google.oauth2.service_account import Credentials
import gspread

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.config import settings

creds_path = Path(settings.google_sheets_credentials_path)
credentials = Credentials.from_service_account_file(str(creds_path), scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
gc = gspread.authorize(credentials)
sh = gc.open_by_url(settings.google_sheet_url)
worksheet = sh.get_worksheet(0)
data = worksheet.get_all_values()
for i, row in enumerate(data[:15]):
    if i == 0: continue
    url = row[1] if len(row) > 1 else ""
    status = row[7] if len(row) > 7 else ""
    print(f"Row {i+1}: URL={url}, Status='{status}'")
