import re

with open("app/parsers/hh_playwright.py", "r") as f:
    content = f.read()

old_func_start = '    async def _request_manual_captcha(self, page) -> bool:'
old_func_end = '    def resolve_captcha(self, text: str):'

match = re.search(re.escape(old_func_start) + r'(.*?)' + re.escape('    def resolve_captcha(self, text: str):'), content, re.DOTALL)
if not match:
    print("Could not find the function")
    exit(1)

old_block = old_func_start + match.group(1)

new_block = """    async def _request_manual_captcha(self, page) -> bool:
        \"\"\"Send CAPTCHA screenshot to Telegram and wait for user input.

        Uses asyncio.Event so the Telegram handler can wake us up.
        Returns True if CAPTCHA was solved, False on timeout/skip.
        \"\"\"
        from app.utils import notifier
        import asyncio

        CAPTCHA_TIMEOUT = 300  # seconds

        for attempt in range(1, 4):
            # Take a fresh screenshot of the captcha area (or full page)
            IMG_SELECTOR = 'img[src*="/captcha/"], img[data-qa*="captcha"], [data-qa="captcha-picture"], .bloko-modal img, [role="dialog"] img'
            captcha_img = await page.query_selector(IMG_SELECTOR)
            if captcha_img:
                self._captcha_screenshot = await captcha_img.screenshot()
            else:
                self._captcha_screenshot = await page.screenshot()

            # Save screenshot to disk so Telegram handler can send it
            screenshot_path = "data/debug_captcha_manual.png"
            try:
                from pathlib import Path
                Path(screenshot_path).parent.mkdir(parents=True, exist_ok=True)
                Path(screenshot_path).write_bytes(self._captcha_screenshot)
            except Exception as e:
                log.warning("captcha_screenshot_save_error", error=str(e))

            # Prepare the event for user input
            self._captcha_event = asyncio.Event()
            self._captcha_text = ""

            # Notify user via Telegram
            log.info("hh_captcha_requesting_manual_input", attempt=attempt)
            msg = "🔒 <b>Ввод CAPTCHA!</b>\\n\\nСкриншот отправлен ниже. Пожалуйста, введите текст с картинки.\\n\\n⏱ Таймаут: 5 минут\\n\\nИспользуйте кнопки или просто отправьте текст."
            if attempt > 1:
                msg = f"❌ <b>Текст не подошел (Попытка {attempt}/3).</b>\\n\\n" + msg
            
            await notifier.send(msg)

            # Send the screenshot image via special callback
            try:
                from app.bot.captcha_notify import send_captcha_to_user
                await send_captcha_to_user(screenshot_path)
            except Exception as e:
                log.warning("captcha_tg_send_error", error=str(e))

            # Wait for user input with 5-minute timeout
            try:
                await asyncio.wait_for(self._captcha_event.wait(), timeout=CAPTCHA_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("hh_captcha_manual_timeout")
                self._captcha_event = None
                self._captcha_screenshot = None
                await notifier.send("⏱ <b>Таймаут CAPTCHA</b> — отклик пропущен.")
                return False

            user_text = self._captcha_text.strip()
            self._captcha_event = None
            self._captcha_screenshot = None

            if not user_text:
                log.info("hh_captcha_manual_skipped")
                return False

            # Fill and submit the user's answer
            log.info("hh_captcha_manual_input", text=user_text)
            
            # Allow 2 inner retries for stale element references
            success_filling = False
            for retry in (1, 2):
                captcha_input = await page.query_selector(
                    'input[placeholder*="Текст с картинки"], input[placeholder*="Код с картинки"], input[data-qa="captcha-input"], input[name="captchaText"]'
                )
                if not captcha_input:
                    # Captcha disappeared?
                    success_filling = True
                    break
                try:
                    await captcha_input.fill(user_text)
                    await page.wait_for_timeout(500)

                    submit_btn = await page.query_selector(
                        'button:has-text("Отправить"), button:has-text("Подтвердить")'
                    )
                    if submit_btn:
                        await submit_btn.click()
                        await page.wait_for_timeout(3000)
                    
                    success_filling = True
                    break
                except Exception as e:
                    log.warning("hh_captcha_manual_fill_error", error=str(e)[:120])
                    if retry == 1:
                        await page.wait_for_timeout(500)
                        continue
            
            # Check if captcha is still there
            captcha_input = await page.query_selector(
                'input[placeholder*="Текст с картинки"], input[placeholder*="Код с картинки"], input[data-qa="captcha-input"], input[name="captchaText"]'
            )
            if not captcha_input or not await captcha_input.is_visible():
                log.info("hh_captcha_manual_success")
                await notifier.send("✅ <b>CAPTCHA пройдена!</b> Отклик продолжается.")
                return True
            else:
                log.warning("hh_captcha_manual_wrong", attempt=attempt)
                # It will loop to attempt+1 and ask the user again with a fresh screenshot

        await notifier.send("❌ <b>CAPTCHA не пройдена</b> — исчерпаны попытки.")
        return False

"""

content = content.replace(old_block, new_block)
with open("app/parsers/hh_playwright.py", "w") as f:
    f.write(content)
print("Done!")
