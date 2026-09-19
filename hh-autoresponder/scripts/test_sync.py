import asyncio
import os
import sys

# Добавляем корневую папку в sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.parsers.hh_playwright import HHPlaywright
from app.services.google_sheets import sync_statuses_to_sheets

async def test_sync():
    print("Testing sync...")
    hh = HHPlaywright()
    statuses = await hh.check_negotiations_status()
    print(f"Found {len(statuses)} statuses on hh.ru.")
    
    if statuses:
        await sync_statuses_to_sheets(statuses)
        print("Sync finished.")

if __name__ == "__main__":
    asyncio.run(test_sync())
