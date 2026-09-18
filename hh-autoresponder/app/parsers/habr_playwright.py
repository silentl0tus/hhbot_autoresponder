import asyncio
from pathlib import Path
import structlog
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

from app.utils.anti_detect import random_delay

log = structlog.get_logger()
HABR_STATE_PATH = Path("data/browser_sessions/habr_state.json")

class HabrPlaywright:
    async def apply_to_vacancy(self, url: str, cover_letter: str) -> bool:
        if not HABR_STATE_PATH.exists():
            log.error("habr_apply_error", reason="No session state", path=str(HABR_STATE_PATH))
            return False

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(storage_state=HABR_STATE_PATH)
                page = await context.new_page()
                
                await page.goto(url)
                await random_delay(2, 4)
                
                # Check if "Откликнуться" button exists
                # In Habr Career, the button is usually an anchor or button with specific text/class
                # Let's just try to find a link that goes to /applications/new
                apply_btn = page.locator("a[href*='/applications/new']").first
                if await apply_btn.count() == 0:
                    apply_btn = page.locator("button:has-text('Откликнуться')").first
                    
                if await apply_btn.count() > 0:
                    await apply_btn.click()
                    await random_delay(2, 4)
                    
                    # Now we should be on the application form
                    # Cover letter text area
                    textarea = page.locator("textarea[name*='message'], textarea[id*='message']").first
                    if await textarea.count() > 0:
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

habr_playwright = HabrPlaywright()
