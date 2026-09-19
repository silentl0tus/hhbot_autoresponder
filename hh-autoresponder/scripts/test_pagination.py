import asyncio
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright

async def run():
    hh = HHPlaywright()
    await hh.login()
    page = await hh._get_page()
    
    # Check page=1
    await page.goto("https://hh.ru/applicant/negotiations?page=1")
    await page.wait_for_timeout(3000)
    
    items1 = await page.query_selector_all('[data-qa="negotiations-item"], .negotiations-list-item')
    print(f"Items on page 1: {len(items1)}")
    
    if items1:
        text1 = await items1[0].inner_text()
        print(f"First item on page 1 snippet: {text1[:50]}")
    
    # Check page 0 to see if it's different
    await page.goto("https://hh.ru/applicant/negotiations?page=0")
    await page.wait_for_timeout(3000)
    
    items0 = await page.query_selector_all('[data-qa="negotiations-item"], .negotiations-list-item')
    print(f"Items on page 0: {len(items0)}")
    
    if items0:
        text0 = await items0[0].inner_text()
        print(f"First item on page 0 snippet: {text0[:50]}")

if __name__ == "__main__":
    asyncio.run(run())
