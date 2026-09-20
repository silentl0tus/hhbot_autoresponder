import asyncio
import os
import sys

# Добавляем корневую папку в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.parsers.hh_oauth import hh_oauth
from app.services.google_sheets import sync_statuses_to_sheets

async def test_sync():
    print("Testing sync...")
    statuses = []
    if await hh_oauth.get_token():
        try:
            statuses = await hh_oauth.negotiations_status()
            print(f"Found {len(statuses)} statuses via HH OAuth API.")
        except Exception as e:
            print(f"OAuth failed: {e}")

    if not statuses:
        from app.parsers.hh_playwright import HHPlaywright
        hh = HHPlaywright()
        statuses = await hh.check_negotiations_status()
        print(f"Found {len(statuses)} statuses via Playwright.")
    
    if statuses:
        count = await sync_statuses_to_sheets(statuses)
        print(f"Sync finished. Updated {count} rows in Google Sheets.")

if __name__ == "__main__":
    asyncio.run(test_sync())
