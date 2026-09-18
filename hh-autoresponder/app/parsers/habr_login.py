import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

HABR_STATE_PATH = Path("data/browser_sessions/habr_state.json")

async def run_habr_login():
    HABR_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("Открываем браузер для входа на Хабр Карьеру...")
    print("Пожалуйста, войдите в свой аккаунт вручную.")
    print("Браузер сам закроется через 180 секунд или когда вы нажмёте Ctrl+C в терминале.")
    print("=" * 60)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        await page.goto("https://career.habr.com/login")
        
        try:
            # Wait for user to login
            await page.wait_for_timeout(180000)
        except KeyboardInterrupt:
            pass
        finally:
            await context.storage_state(path=HABR_STATE_PATH)
            print("Сессия сохранена в", HABR_STATE_PATH)
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_habr_login())
