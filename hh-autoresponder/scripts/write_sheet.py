import asyncio
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.services.google_sheets import gc
from app.config import settings

def run():
    sh = gc.open_by_url(settings.google_sheet_url)
    worksheet = sh.get_worksheet(0)
    # Just update the very first one to verify
    # First, let's read the current value
    val = worksheet.acell('H14').value
    print(f"Current H14: {val}")
    
    # Write a new value
    worksheet.update('H14', 'Отказ', value_input_option='USER_ENTERED')
    print("Updated H14 with USER_ENTERED.")
    
    val = worksheet.acell('H14').value
    print(f"New H14: {val}")

if __name__ == "__main__":
    run()
