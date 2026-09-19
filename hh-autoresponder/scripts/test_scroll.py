import asyncio
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright

async def run():
    hh = HHPlaywright()
    await hh.login()
    page = await hh._get_page()
    await page.goto("https://hh.ru/applicant/negotiations")
    await page.wait_for_selector('.negotiations-list-item, [data-qa="negotiations-item"]')
    
    items = await page.locator('.negotiations-list-item, [data-qa="negotiations-item"]').count()
    print(f"Items before scroll: {items}")
    
    # Try to hover over the list and scroll the mouse
    await page.locator('.negotiations-list-item, [data-qa="negotiations-item"]').first.hover()
    for _ in range(5):
        await page.mouse.wheel(0, 5000)
        await page.wait_for_timeout(2000)
        items = await page.locator('.negotiations-list-item, [data-qa="negotiations-item"]').count()
        print(f"Items after scroll: {items}")

if __name__ == "__main__":
    asyncio.run(run())
