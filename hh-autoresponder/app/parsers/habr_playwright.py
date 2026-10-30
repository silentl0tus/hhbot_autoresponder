import asyncio
import typing
from pathlib import Path

import structlog
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from app.utils.anti_detect import random_delay

log = structlog.get_logger()
HABR_STATE_PATH = Path("data/browser_sessions/habr_state.json")


class HabrPlaywright:
    async def apply_to_vacancy(self, url: str, cover_letter: str | typing.Callable) -> bool | str:
        if not HABR_STATE_PATH.exists():
            log.error("habr_apply_error", reason="No session state", path=str(HABR_STATE_PATH))
            return False

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(storage_state=HABR_STATE_PATH)
                page = await context.new_page()

                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                except Exception as e:
                    log.warning("habr_goto_timeout", url=url, error=str(e))
                    return False

                if resp and resp.status == 404:
                    log.info("habr_apply_vacancy_404", url=url)
                    return "archived"

                content = await page.content()
                if any(
                    marker in content
                    for marker in ("Ошибка 404", "закрыла свой профиль", "Вакансия в архиве", "вакансия закрыта")
                ):
                    log.info("habr_apply_vacancy_archived", url=url)
                    return "archived"

                # Check if already applied
                already_applied = page.locator(
                    "a:has-text('Вы откликнулись'), div:has-text('Вы откликнулись'), .applied-label"
                )
                if await already_applied.count() > 0:
                    log.info("habr_already_applied", url=url)
                    return "already"

                # Check if external response (on company website)
                external_btn = page.locator("a[href*='external_response'], a:has-text('Откликнуться у компании')")
                if await external_btn.count() > 0:
                    log.info("habr_external_response_only", url=url)
                    return "external"

                if resp and resp.status == 404:
                    log.info("habr_apply_vacancy_404", url=url)
                    return "archived"

                content = await page.content()
                if any(
                    marker in content
                    for marker in ("Ошибка 404", "закрыла свой профиль", "Вакансия в архиве", "вакансия закрыта")
                ):
                    log.info("habr_apply_vacancy_archived", url=url)
                    return "archived"

                # Check if already applied
                already_applied = page.locator(
                    "a:has-text('Вы откликнулись'), div:has-text('Вы откликнулись'), .applied-label"
                )
                if await already_applied.count() > 0:
                    log.info("habr_already_applied", url=url)
                    return "already"

                # Check if external response (on company website)
                external_btn = page.locator("a[href*='external_response'], a:has-text('Откликнуться у компании')")
                if await external_btn.count() > 0:
                    log.info("habr_external_response_only", url=url)
                    return "external"

                # Check if "Откликнуться" button exists
                # In Habr Career, the button is usually an anchor or button with specific text/class
                # Let's just try to find a link that goes to /applications/new
                apply_btn = page.locator("a[href*='/applications/new']").first
                if await apply_btn.count() == 0:
                    apply_btn = page.locator("button:has-text('Откликнуться')").first
                if await apply_btn.count() == 0:
                    apply_btn = page.locator("a:has-text('Откликнуться')").first

                if await apply_btn.count() > 0:
                    await apply_btn.click()
                    await random_delay(2, 4)

                    # Now we should be on the application form
                    # Cover letter text area
                    textarea = page.locator("textarea[name*='message'], textarea[id*='message']").first
                    if await textarea.count() > 0:
                        if callable(cover_letter):
                            try:
                                cover_letter = (
                                    await cover_letter()
                                    if asyncio.iscoroutinefunction(cover_letter)
                                    else cover_letter()
                                )
                            except Exception as e:
                                log.error("habr_deferred_cover_letter_error", error=str(e))
                                cover_letter = ""
                        await textarea.fill(cover_letter)
                        await random_delay(1, 3)

                    # Submit button
                    submit_btn = page.locator("input[type='submit'], button[type='submit']").first
                    if await submit_btn.count() > 0:
                        await submit_btn.click()
                        await page.wait_for_load_state("networkidle")
                        await random_delay(2, 4)
                        return True
                    else:
                        log.warning("habr_apply_submit_btn_not_found", url=url)
                else:
                    log.warning("habr_apply_btn_not_found_or_already_applied", url=url)

            except Exception as e:
                log.error("habr_playwright_apply_error", error=str(e), url=url)
            finally:
                await browser.close()

        return False

    async def check_messages(self) -> list[dict]:
        if not HABR_STATE_PATH.exists():
            return []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            try:
                context = await browser.new_context(storage_state=HABR_STATE_PATH)
                page = await context.new_page()

                await page.goto("https://career.habr.com/conversations")
                await random_delay(2, 4)

                try:
                    # Подождем загрузки списка чатов (может называться .conversation, .chat-item, или просто ссылки)
                    await page.wait_for_selector("a[href*='/conversations/']", timeout=10000)
                except PlaywrightTimeout:
                    log.info("habr_no_messages_found")
                    return []

                # Собираем все ссылки на чаты
                conv_links = await page.locator("a[href*='/conversations/']").all()
                results = []
                for link in conv_links:
                    text = await link.inner_text()
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    if not lines:
                        continue

                    # Эвристика: первая строка обычно компания/рекрутер, вторая - должность, остальное текст
                    company = lines[0] if len(lines) > 0 else "Unknown"
                    title = lines[1] if len(lines) > 1 else ""
                    msg_text = "\n".join(lines[2:]) if len(lines) > 2 else "Нет текста"

                    href = await link.get_attribute("href")
                    thread_id = href.split("/")[-1] if href else "unknown"

                    results.append(
                        {
                            "platform": "habr",
                            "sender": company,
                            "company": company,
                            "title": title,
                            "text": msg_text,
                            "status": "уведомление",  # дефолтный статус
                            "thread_id": thread_id,
                            "external_id": thread_id,
                        }
                    )

                return results
            except Exception as e:
                log.error("habr_check_messages_error", error=str(e))
                return []
            finally:
                await browser.close()


habr_playwright = HabrPlaywright()
