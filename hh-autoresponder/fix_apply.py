import re

with open("app/parsers/hh_playwright.py", "r") as f:
    content = f.read()

# We need to extract the success check and attachment logic OUTSIDE of if submit_btn:
# The logic inside if submit_btn is currently:
#             if submit_btn:
#                 ... click ... wait ... captcha ...
#                 ... foreign country modal ...
#                 success = False
#                 for _ in range(12):
#                     ... wait for success ...
#                 if success:
#                     ... attach deferred ... return True ...
#                 try: ... validation errors ...
#             await self._save_debug_screenshot(page, "apply_fail")
#
# We will change it to:
#             if submit_btn:
#                 ... click ...
#                 ... foreign country modal ...
#
#             # Wait for success REGARDLESS of whether submit_btn was clicked (1-click apply support)
#             success = False
#             for _ in range(12):
#                 ... wait for success ...
#
#             if success:
#                 ... attach deferred ... return True ...
#
#             if submit_btn:
#                 try: ... validation errors ...
#
#             await self._save_debug_screenshot(...)

# Let's use a simpler approach. I will just replace the entire block from `if submit_btn:` to `return False`.

old_code_start = '            if submit_btn:\\n                if screenshot_name:'
old_code_end = '            return False\\n\\n        except PlaywrightTimeout:'

match = re.search(re.escape(old_code_start) + r'(.*?)' + re.escape('            return False\n\n        except PlaywrightTimeout:'), content, re.DOTALL)
if not match:
    print("Could not find the block to replace")
    exit(1)

old_block = old_code_start + match.group(1) + '            return False'

new_block = """            if submit_btn:
                if screenshot_name:
                    try:
                        await page.screenshot(path=f"data/test_apply_{screenshot_name}_before.png")
                    except Exception:
                        pass
                await submit_btn.click()
                await page.wait_for_timeout(1500)
                await self._solve_captcha_if_present(page)

                # After submit also handle "foreign country" / confirm modals
                try:
                    clicked_anyway_2 = await page.evaluate(
                        '''() => {
                            const _CONFIRM_TEXTS = new Set([
                                'все равно откликнуться', 'всё равно откликнуться',
                                'все равно', 'всё равно',
                                'согласиться', 'согласен', 'соглашаюсь',
                                'продолжить', 'подтвердить', 'ok', 'ок',
                                'откликнуться всё равно', 'откликнуться все равно',
                            ]);
                            const buttons = document.querySelectorAll('button, a[role=button], [role=button]');
                            for (const b of buttons) {
                                const t = (b.innerText || '').trim().toLowerCase();
                                if (_CONFIRM_TEXTS.has(t)) {
                                    b.click();
                                    return true;
                                }
                            }
                            return false;
                        }'''
                    )
                    if clicked_anyway_2:
                        log.info("hh_clicked_foreign_anyway_post_submit")
                        await page.wait_for_timeout(2000)
                except Exception:
                    pass

            # Wait up to 12s for any of: URL change to negotiations,
            # success element, or visible 'отклик отправлен' text
            success = False
            for _ in range(12):
                await page.wait_for_timeout(1000)
                if "/applicant/negotiations" in page.url or "vacancy_response_success" in page.url:
                    success = True
                    break
                try:
                    if await page.query_selector('[data-qa="vacancy-response-link-view-topic"]'):
                        success = True
                        break
                    if await page.query_selector('[data-qa*="response-success"], [class*="response-success"]'):
                        success = True
                        break
                    # Check text on page for confirmation
                    body_text = await page.evaluate("() => document.body.innerText")
                    if "отклик отправлен" in body_text.lower() or "вы откликнулись" in body_text.lower() or "резюме доставлено" in body_text.lower():
                        success = True
                        break
                except Exception:
                    pass

            if success:
                # УРА! Отклик прошел успешно. Теперь мы не тратим токены на мертвые вакансии!
                # Смотрим, есть ли кнопка "Приложить сопроводительное письмо"
                if cover_letter and callable(cover_letter):
                    attach_btn = await page.query_selector('button:has-text("Приложить сопроводительное письмо"), span:has-text("Приложить сопроводительное письмо")')
                    if attach_btn:
                        log.info("hh_attaching_deferred_cover_letter_after_success")
                        await attach_btn.click()
                        await page.wait_for_timeout(1000)
                        # Генерируем письмо (тратим токены только сейчас!)
                        try:
                            import asyncio
                            cl_text = await cover_letter() if asyncio.iscoroutinefunction(cover_letter) else cover_letter()
                            if cl_text:
                                # Ищем появившееся текстовое поле
                                ta = await page.query_selector('textarea[placeholder*="опроводительн"], [data-qa="vacancy-response-popup-form-letter-input"]')
                                if ta and await ta.is_visible():
                                    await ta.fill(cl_text)
                                    await page.wait_for_timeout(500)
                                    # Кликаем отправить письмо
                                    send_btn = await page.query_selector('button:has-text("Сохранить"), button:has-text("Отправить")')
                                    if send_btn:
                                        await send_btn.click()
                                        await page.wait_for_timeout(1000)
                        except Exception as e:
                            log.error("hh_deferred_cover_letter_attach_error", error=str(e))
                
                if screenshot_name:
                    try:
                        await page.screenshot(path=f"data/test_apply_{screenshot_name}_after.png")
                    except Exception:
                        pass
                log.info("hh_apply_success", url=vacancy_url, final=page.url)
                await browser_manager.save_context("hh")
                return True

            if submit_btn:
                # Look for inline validation errors
                try:
                    err_text = await page.evaluate(
                        '''() => {
                            const errs = document.querySelectorAll('[class*="error"], [data-qa*="error"]');
                            return Array.from(errs).slice(0, 5).map(e => (e.innerText || '').trim()).filter(Boolean);
                        }'''
                    )
                    if err_text:
                        log.warning("hh_apply_validation_errors", errors=err_text[:3])
                        
                        # Если вакансия ЖЕСТКО требует сопроводительное
                        if any("опроводительное письмо" in e.lower() for e in err_text) and cover_letter and callable(cover_letter):
                            log.info("hh_cover_letter_strictly_required_generating_now")
                            try:
                                import asyncio
                                cl_text = await cover_letter() if asyncio.iscoroutinefunction(cover_letter) else cover_letter()
                                if cl_text:
                                    ta = await page.query_selector('textarea[placeholder*="опроводительн"], [data-qa="vacancy-response-popup-form-letter-input"]')
                                    if ta and await ta.is_visible():
                                        await ta.fill(cl_text)
                                        await submit_btn.click()
                                        await page.wait_for_timeout(2000)
                                        body_text = await page.evaluate("() => document.body.innerText")
                                        if "отклик отправлен" in body_text.lower() or "вы откликнулись" in body_text.lower() or "резюме доставлено" in body_text.lower():
                                            log.info("hh_apply_success_after_mandatory_cover_letter", url=vacancy_url)
                                            await browser_manager.save_context("hh")
                                            return True
                            except Exception as e:
                                log.error("hh_mandatory_cover_letter_error", error=str(e))

                        # Если капча введена неверно (ИИ ошибся), даем шанс на повторное решение
                        if "неверный текст" in err_text[0].lower():
                            log.info("hh_retrying_captcha_after_validation_error")
                            solved = await self._solve_captcha_if_present(page)
                            if solved:
                                # Проверяем, исчезла ли ошибка и появился ли текст успеха
                                await page.wait_for_timeout(2000)
                                body_text = await page.evaluate("() => document.body.innerText")
                                if "отклик отправлен" in body_text.lower() or "вы откликнулись" in body_text.lower() or "резюме доставлено" in body_text.lower():
                                    log.info("hh_apply_success", url=vacancy_url, final=page.url)
                                    await browser_manager.save_context("hh")
                                    return True

                        await self._save_debug_screenshot(page, "apply_validation_fail")
                        try:
                            from app.bot.captcha_notify import send_error_screenshot
                            await send_error_screenshot(
                                "data/debug_apply_validation_fail.png",
                                f"❌ <b>Ошибка валидации на hh.ru</b>\\n\\n<a href='{vacancy_url}'>Вакансия</a>\\n\\nПричина: {err_text[0]}\\nПосмотрите на скриншот."
                            )
                        except Exception as e:
                            log.warning("telegram_screenshot_failed", error=str(e))
                        return f"error: {err_text[0]}"
                except Exception:
                    pass

            await self._save_debug_screenshot(page, "apply_fail")
            if screenshot_name:
                try:
                    await page.screenshot(path=f"data/test_apply_{screenshot_name}_after.png")
                except Exception:
                    pass
            log.warning("hh_apply_uncertain", url=vacancy_url, current_url=page.url)

            # Отправляем скриншот ошибки пользователю в Telegram
            try:
                from app.bot.captcha_notify import send_error_screenshot
                await send_error_screenshot(
                    "data/debug_apply_fail.png",
                    f"❌ <b>Ошибка отклика на hh.ru</b>\\n\\n<a href='{vacancy_url}'>Вакансия</a>\\n\\nБот не смог откликнуться или пройти проверку. Посмотрите на скриншот, чтобы понять причину."
                )
            except Exception as e:
                log.warning("telegram_screenshot_failed", error=str(e))

            return False"""

content = content.replace(old_block, new_block)
with open("app/parsers/hh_playwright.py", "w") as f:
    f.write(content)
print("Done!")
