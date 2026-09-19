import asyncio
import sys, os, json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app.parsers.hh_playwright import HHPlaywright

async def run():
    hh = HHPlaywright()
    await hh.login()
    page = await hh._get_page()
    await page.goto("https://hh.ru/applicant/negotiations?state=DECLINED")
    await page.wait_for_selector('[data-qa="negotiations-item"]', timeout=10000)
    
    js = """() => {
        const item = document.querySelector('[data-qa="negotiations-item"]');
        if (!item) return null;
        return {
            text: item.innerText,
            html: item.innerHTML
        };
    }"""
    data = await page.evaluate(js)
    print("TEXT:")
    print(data["text"])
    print("---")
    print("HTML:")
    print(data["html"])

if __name__ == "__main__":
    asyncio.run(run())
