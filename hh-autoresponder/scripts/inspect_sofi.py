#!/usr/bin/env python3
"""Скрипт для интерактивного изучения личного кабинета Sofi Assistant.

1. Открывает окно Chromium на экране пользователя (DISPLAY=:0).
2. Пользователь входит в свой аккаунт.
3. Скрипт сохраняет скриншоты ключевых разделов (профиль, настройки, аналитика, автоотклики)
   в папку data/sofi_inspect/ и сохраняет HTML для детального анализа агентом.
"""

import asyncio
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = PROJECT_ROOT / "data" / "sofi_inspect"


async def main():
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]

    print("\n" + "=" * 60)
    print("🚀 Открываю браузер на странице Sofi Assistant...")
    print("Пожалуйста, войдите в свой аккаунт в открывшемся окне.")
    print("=" * 60 + "\n")

    browser = await pw.chromium.launch(headless=False, args=launch_args)
    ctx = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="ru-RU",
    )
    page = await ctx.new_page()

    await page.goto("https://sofi-assistant.com/profile", wait_until="domcontentloaded")

    print("\n" + "-" * 60)
    print("Когда вы войдёте и окажетесь в личном кабинете / настройках,")
    print("нажмите [ENTER] здесь в терминале, чтобы скрипт сделал снимки и изучил интерфейс.")
    print("-" * 60 + "\n")

    # Ждём нажатия Enter от пользователя в терминале
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "Нажмите Enter после входа в аккаунт...")

    print("\n📸 Начинаю фиксацию разделов кабинета...")
    await page.wait_for_timeout(2000)

    # 1. Текущая страница
    current_url = page.url
    print(f"Фиксирую текущую страницу: {current_url}")
    await page.screenshot(path=str(OUT_DIR / "01_current_page.png"), full_page=True)
    html = await page.content()
    (OUT_DIR / "01_current_page.html").write_text(html, encoding="utf-8")

    # Ищем ссылки и вкладки внутри кабинета
    nav_links = await page.query_selector_all("a[href], button")
    found_urls = set()
    for el in nav_links:
        href = await el.get_attribute("href")
        if href and (
            "profile" in href or "settings" in href or "dashboard" in href or "vacancy" in href or "response" in href
        ):
            if href.startswith("/"):
                found_urls.add("https://sofi-assistant.com" + href)
            elif href.startswith("http"):
                found_urls.add(href)

    print(f"Найдено внутренних ссылок кабинета: {len(found_urls)}")

    # Обходим найденные разделы
    idx = 2
    for target in list(found_urls)[:6]:
        if target == current_url:
            continue
        try:
            print(f"Переход в раздел: {target}")
            await page.goto(target, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2500)
            safe_name = target.rstrip("/").split("/")[-1] or f"page_{idx}"
            await page.screenshot(path=str(OUT_DIR / f"{idx:02d}_{safe_name}.png"), full_page=True)
            p_html = await page.content()
            (OUT_DIR / f"{idx:02d}_{safe_name}.html").write_text(p_html, encoding="utf-8")
            idx += 1
        except Exception as e:  # noqa: BLE001
            print(f"Не удалось открыть {target}: {e}")

    print("\n" + "=" * 60)
    print(f"✅ Анализ завершён! Все снимки и разметка сохранены в {OUT_DIR}")
    print("=" * 60 + "\n")

    await browser.close()
    await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
