#!/usr/bin/env python3
"""
Скрипт ручной авторизации на hh.ru с ноутбука и автоматической отправки сессии на смартфон.

Как работает:
1. Запускает окно Chromium на ноутбуке.
2. Вы входите в аккаунт (телефон/пароль/SMS/капча).
3. Скрипт перехватывает cookies и сохраняет в hh_state.json.
4. Автоматически вызывает sync_session_to_phone.sh для передачи сессии на смартфон.

Требования:
    pip install playwright
    playwright install chromium
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_STATE = SCRIPT_DIR / "hh_state.json"
SYNC_SCRIPT = SCRIPT_DIR / "sync_session_to_phone.sh"


async def main():
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("=" * 60)
        print("❌ Playwright не установлен в текущем Python-окружении.")
        print("Для установки выполните команды:")
        print("    python3 -m pip install playwright")
        print("    python3 -m playwright install chromium")
        print("=" * 60)
        sys.exit(1)

    print("=" * 60)
    print("🌐 Открываю браузер для авторизации на hh.ru...")
    print("=" * 60)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
        ],
    )

    ctx_opts = {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 720},
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }
    if LOCAL_STATE.exists():
        ctx_opts["storage_state"] = str(LOCAL_STATE)

    ctx = await browser.new_context(**ctx_opts)
    await ctx.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        """
    )

    page = await ctx.new_page()
    await page.goto("https://hh.ru/account/login", wait_until="domcontentloaded")

    print("\n👉 Войдите в свой аккаунт в открывшемся окне браузера.")
    print("   (при необходимости решите капчу или введите SMS-код)")
    print("⏳ Ожидание успешного входа...")

    while True:
        await asyncio.sleep(2)
        try:
            check_url = page.url
            if "/account/login" in check_url:
                continue

            # Ищем маркеры залогиненного пользователя
            avatar = await page.query_selector(
                '[data-qa="mainmenu-user"], button[data-qa*="user"]'
            )
            resumes_link = await page.query_selector('[data-qa="mainmenu_myResumes"]')
            applicant_profile = await page.query_selector(
                '[data-qa="mainmenu_applicantProfile"]'
            )

            if avatar or resumes_link or applicant_profile:
                print("\n✅ Авторизация успешно обнаружена!")
                print("⏳ Сохраняю cookies и состояние сессии...")
                state = await ctx.storage_state()
                LOCAL_STATE.write_text(
                    json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"📁 Сессия сохранена в: {LOCAL_STATE.name}")
                break
        except Exception:
            pass

    await browser.close()
    await pw.stop()

    # Запуск скрипта синхронизации на смартфон
    if SYNC_SCRIPT.exists() and os.access(SYNC_SCRIPT, os.X_OK):
        print("\n📲 Запуск автоматической отправки сессии на смартфон...")
        subprocess.run([str(SYNC_SCRIPT), str(LOCAL_STATE)])
    else:
        print(
            f"\n💡 Чтобы отправить сессию на телефон, выполните:\n   ./sync_session_to_phone.sh {LOCAL_STATE}"
        )


if __name__ == "__main__":
    asyncio.run(main())
