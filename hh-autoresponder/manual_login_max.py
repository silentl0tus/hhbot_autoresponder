"""
Ручной вход в мессенджер MAX (web.max.ru) для прохождения скринеров вакансий.

Открывает окно Chromium на странице https://web.max.ru.
Вы авторизуетесь руками (номер телефона, SMS/код или QR-код).
Скрипт сохраняет сессию в data/browser_sessions/max_state.json.
"""
import asyncio
import json
from pathlib import Path


async def main():
    from playwright.async_api import async_playwright

    storage_path = Path("data/browser_sessions/max_state.json")

    pw = await async_playwright().start()

    launch_args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
    ]

    print("\n" + "=" * 60)
    print("Запуск браузера для авторизации в мессенджере MAX...")
    print("=" * 60)

    browser = await pw.chromium.launch(headless=False, args=launch_args)

    ctx_opts = {
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "viewport": {"width": 1280, "height": 720},
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }
    if storage_path.exists():
        try:
            ctx_opts["storage_state"] = str(storage_path)
            print(f"Загрузил сохраненную сессию из {storage_path}")
        except Exception as e:
            print(f"Не удалось загрузить сессию: {e}")

    ctx = await browser.new_context(**ctx_opts)
    await ctx.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = {runtime: {}};
        """
    )

    page = await ctx.new_page()
    await page.goto("https://web.max.ru", wait_until="domcontentloaded")

    print("\n" + "-" * 60)
    print("Пожалуйста, выполните вход в свой аккаунт MAX в открывшемся окне.")
    print("После успешного входа скрипт автоматически сохранит сессию.")
    print("Если вход уже выполнен, подождите несколько секунд.")
    print("-" * 60 + "\n")

    # Ждем признаков авторизации: наличие списка чатов, поля поиска или профиля
    logged_in = False
    for _ in range(120):  # Ждем до 10 минут (120 * 5 сек)
        await asyncio.sleep(5)
        try:
            # Проверяем типовые элементы авторизованного интерфейса web.max.ru
            chat_list = await page.query_selector(
                '[class*="chat"], [class*="dialog"], [data-testid*="chat"], [class*="avatar"], input[type="search"], textarea'
            )
            # Проверяем отсутствие формы логина / ввода телефона
            login_inputs = await page.query_selector_all('input[type="tel"], input[placeholder*="телефон"], input[placeholder*="код"]')
            
            # Проверяем наличие cookies сессии
            cookies = await ctx.cookies()
            auth_cookies = [c for c in cookies if "token" in c["name"].lower() or "auth" in c["name"].lower() or "session" in c["name"].lower() or "max" in c["name"].lower()]

            if (chat_list and len(login_inputs) == 0) or len(auth_cookies) > 0:
                # Дополнительная пауза для синхронизации локального хранилища
                await asyncio.sleep(3)
                state = await ctx.storage_state()
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                storage_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"✅ Сессия успешно сохранена в: {storage_path}")
                logged_in = True
                break
        except Exception as e:
            pass

    if not logged_in:
        print("⚠️ Время ожидания истекло или вход не был завершен. Попробуйте еще раз.")

    await asyncio.sleep(2)
    await browser.close()
    await pw.stop()
    print("Браузер закрыт.")


if __name__ == "__main__":
    asyncio.run(main())
