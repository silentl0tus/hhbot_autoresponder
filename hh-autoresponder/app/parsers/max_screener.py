"""
Модуль взаимодействия с веб-мессенджером MAX (web.max.ru) для прохождения скринеров вакансий.

Управляет headless-браузером Playwright, читает сообщения в диалоге с ботом-рекрутером
(например, @giga_recruiter_bot от Сбера) и отправляет согласованные соискателем ответы.
"""
import asyncio
from pathlib import Path
import structlog
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

log = structlog.get_logger()

DEFAULT_BOT_URL = "https://web.max.ru/giga_recruiter_bot"
STORAGE_PATH = Path("data/browser_sessions/max_state.json")


class MaxScreenerParser:
    def __init__(self, bot_url: str = DEFAULT_BOT_URL, storage_path: Path = STORAGE_PATH):
        self.bot_url = bot_url
        self.storage_path = storage_path
        self._pw = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self.last_seen_message_text: str | None = None
        self.last_sent_text: str | None = None

    def is_session_available(self) -> bool:
        """Проверяет, сохранен ли файл авторизации в MAX."""
        return self.storage_path.exists() and self.storage_path.stat().st_size > 0

    async def start(self, headless: bool = True) -> bool:
        """Запускает Playwright и открывает диалог со скринером."""
        if not self.is_session_available():
            log.warning("max_session_missing", path=str(self.storage_path))
            return False

        try:
            self._pw = await async_playwright().start()
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
            self._browser = await self._pw.chromium.launch(
                headless=headless,
                args=launch_args
            )

            ctx_opts = {
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1280, "height": 720},
                "locale": "ru-RU",
                "timezone_id": "Europe/Moscow",
                "storage_state": str(self.storage_path),
            }

            self._context = await self._browser.new_context(**ctx_opts)
            await self._context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = {runtime: {}};
                """
            )

            self._page = await self._context.new_page()
            log.info("max_screener_navigating", url=self.bot_url)
            await self._page.goto(self.bot_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(4)
            return True
        except Exception as e:
            log.error("max_screener_start_error", error=str(e))
            await self.close()
            return False

    async def get_latest_screener_question(self) -> str | None:
        """Извлекает текст последнего входящего вопроса от бота-скринера."""
        if not self._page:
            return None

        try:
            # Селекторы сообщений в интерфейсе веб-мессенджера MAX (исключаем свои сообщения)
            selectors = [
                '[class*="incoming"] [class*="text"]',
                '[class*="bubble"]:not([class*="out"]):not([class*="outgoing"]):not([class*="mine"]):not([class*="self"])',
                '[data-qa*="message-incoming"]',
                '[class*="message"]:not([class*="outgoing"]):not([class*="mine"]):not([class*="self"]):not([class*="out"]):not([class*="sent"])',
                '[class*="message-text"]',
                '[class*="message"]',
            ]

            latest_text = ""
            for selector in selectors:
                elements = await self._page.query_selector_all(selector)
                if elements:
                    # Идем с конца в поисках последнего непустого сообщения
                    for el in reversed(elements):
                        t = (await el.inner_text()).strip()
                        if t and len(t) > 3:
                            # Проверяем, что это не наш собственный только что отправленный ответ
                            if self.last_sent_text and (t == self.last_sent_text or t in self.last_sent_text or self.last_sent_text in t):
                                continue
                            latest_text = t
                            break
                    if latest_text:
                        break

            if not latest_text:
                # Фоллбэк: ищем текстовые блоки внутри основного контейнера чата
                chat_container = await self._page.query_selector('[class*="chat-history"], [class*="messages-list"], [id="app"]')
                if chat_container:
                    all_text = await chat_container.inner_text()
                    lines = [line.strip() for line in all_text.split("\n") if line.strip()]
                    if lines:
                        candidate = lines[-1]
                        if not (self.last_sent_text and candidate in self.last_sent_text):
                            latest_text = candidate

            if latest_text and latest_text != self.last_seen_message_text:
                self.last_seen_message_text = latest_text
                log.info("screener_question_captured", text_preview=latest_text[:80])
                return latest_text

            return None
        except Exception as e:
            log.warning("get_latest_screener_question_error", error=str(e))
            return None

    async def send_answer(self, text: str) -> bool:
        """Вводит ответ в поле ввода чата MAX и отправляет его."""
        if not self._page:
            return False

        try:
            # Ищем поле ввода сообщения
            input_selectors = [
                'textarea[placeholder*="сообщение" i]',
                'textarea[placeholder*="message" i]',
                'textarea',
                'div[contenteditable="true"]',
                '[role="textbox"]',
                'input[type="text"][placeholder*="сообщение" i]',
            ]

            input_field = None
            for sel in input_selectors:
                el = await self._page.query_selector(sel)
                if el and await el.is_visible():
                    input_field = el
                    break

            if not input_field:
                log.error("max_input_field_not_found")
                return False

            await input_field.click()
            await asyncio.sleep(0.3)

            # Очищаем поле ввода если там что-то было
            await self._page.keyboard.press("Control+A")
            await self._page.keyboard.press("Backspace")

            # Вводим текст с имитацией печати человека (задержка 20-35мс между символами)
            await input_field.type(text, delay=25)
            await asyncio.sleep(0.5)

            # Пробуем нажать кнопку отправки или Enter
            send_btn = await self._page.query_selector(
                'button[aria-label*="отправить" i], button[title*="отправить" i], button[class*="send"], [data-testid*="send"]'
            )
            if send_btn and await send_btn.is_visible():
                await send_btn.click()
            else:
                await self._page.keyboard.press("Enter")

            await asyncio.sleep(1)
            self.last_sent_text = text.strip()
            self.last_seen_message_text = text.strip()
            log.info("max_screener_answer_sent", text_preview=text[:60])
            return True
        except Exception as e:
            log.error("max_screener_send_error", error=str(e))
            return False

    async def close(self):
        """Закрывает страницу и браузер."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception:
            pass
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None


max_screener = MaxScreenerParser()
