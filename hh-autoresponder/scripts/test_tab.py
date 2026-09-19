import asyncio
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright

async def run():
    hh = HHPlaywright()
    await hh.login()
    page = await hh._get_page()
    await page.goto("https://hh.ru/applicant/negotiations?state=DECLINED")
    await page.wait_for_selector('.negotiations-list-item, [data-qa="negotiations-item"]', timeout=10000)
    
    items = await page.locator('.negotiations-list-item, [data-qa="negotiations-item"]').count()
    print(f"Items in DECLINED tab: {items}")
    
    html = await page.content()
    with open("declined.html", "w") as f:
        f.write(html)

if __name__ == "__main__":
    asyncio.run(run())
