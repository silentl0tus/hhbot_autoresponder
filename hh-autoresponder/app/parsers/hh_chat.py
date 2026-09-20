"""
Модуль взаимодействия с чатами HeadHunter (https://hh.ru/chat) через Playwright.
Позволяет:
- Отслеживать чаты с новыми сообщениями/вопросами от работодателей и роботов-рекрутеров.
- Считывать текст вопроса и варианты быстрых ответов (если рекрутер задал опрос с выбором).
- Отправлять ответ кликом по кнопке выбора или вводом текста в чат.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from app.config import settings

log = structlog.get_logger()

HH_CHAT_URL = "https://hh.ru/chat"
DEFAULT_STORAGE_PATH = Path("data/browser_sessions/hh_state.json")

HH_REJECT_PATTERNS = (
    "отказ",
    "не подош",
    "отклонил",
    "отклонен",
    "решил остановить",
    "к сожалению, в настоящий момент",
    "к сожалению, мы не готовы",
    "к сожалению, мы вынуждены",
    "не готовы пригласить",
    "вынуждены отказать",
    "выбрали другого",
    "в пользу другого",
    "вернуться к вашей кандидатуре",
    "сохраним ваше резюме",
    "желаем вам успехов",
    "желаем успехов в поиске",
    "позиция закрыта",
    "вакансия закрыта",
    "архив",
)


def is_rejection_text(text: str) -> bool:
    """Проверяет, содержит ли текст явные признаки отказа или закрытия вакансии."""
    if not text:
        return False
    t_lc = text.lower()
    return any(p in t_lc for p in HH_REJECT_PATTERNS)


class HHChatParser:
    def __init__(self, storage_path: Path | str = DEFAULT_STORAGE_PATH):
        self.storage_path = Path(storage_path)
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._lock = asyncio.Lock()

    def is_session_available(self) -> bool:
        """Проверяет, существует ли файл сессии hh_state.json."""
        return self.storage_path.exists() and self.storage_path.stat().st_size > 50

    async def start(self, headless: bool = True) -> bool:
        """Запускает браузер с авторизованной сессией hh.ru и открывает раздел чатов."""
        if not self.is_session_available():
            log.warning("hh_chat_no_session", path=str(self.storage_path))
            return False

        async with self._lock:
            if self._page and not self._page.is_closed():
                return True

            try:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=headless,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                self._context = await self._browser.new_context(
                    storage_state=str(self.storage_path),
                    viewport={"width": 1280, "height": 900},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                )
                self._page = await self._context.new_page()

                log.info("hh_chat_navigating", url=HH_CHAT_URL)
                await self._page.goto(HH_CHAT_URL, wait_until="domcontentloaded", timeout=45000)
                await self._page.wait_for_timeout(3000)

                # Проверяем, что успешно загрузился интерфейс чатов
                url = self._page.url
                if "/account/login" in url or "/auth/" in url:
                    log.warning("hh_chat_session_expired", url=url)
                    await self.close()
                    return False

                # Закрываем cookie banner, если висит
                try:
                    cookie_btn = await self._page.query_selector('button[data-qa="cookies-policy-informer-accept"]')
                    if cookie_btn:
                        await cookie_btn.click()
                        await self._page.wait_for_timeout(500)
                except Exception:
                    pass

                log.info("hh_chat_started_successfully", url=self._page.url)
                return True

            except Exception as e:
                log.error("hh_chat_start_error", error=str(e))
                await self.close()
                return False

    async def close(self):
        """Закрывает браузер и освобождает ресурсы."""
        async with self._lock:
            try:
                if self._page and not self._page.is_closed():
                    await self._page.close()
            except Exception:
                pass
            self._page = None

            try:
                if self._context:
                    await self._context.close()
            except Exception:
                pass
            self._context = None

            try:
                if self._browser:
                    await self._browser.close()
            except Exception:
                pass
            self._browser = None

            try:
                if self._playwright:
                    await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    async def get_unread_or_active_chats(self) -> list[dict[str, Any]]:
        """Сканирует список диалогов на https://hh.ru/chat и возвращает список активных/непрочитанных чатов."""
        if not self._page or self._page.is_closed():
            ok = await self.start(headless=True)
            if not ok:
                log.warning("hh_chat_start_failed_in_get_chats")
                return []

        async with self._lock:
            try:
                curr_url = self._page.url.rstrip("/")
                target_root = HH_CHAT_URL.rstrip("/")
                # Если открыт конкретный чат (hh.ru/chat/12345), возвращаемся в корень чатов
                if curr_url != target_root:
                    log.info("hh_chat_navigating_to_root_list", from_url=curr_url, to_url=target_root)
                    await self._page.goto(HH_CHAT_URL, wait_until="domcontentloaded", timeout=20000)
                    await self._page.wait_for_timeout(2000)
                else:
                    log.debug("hh_chat_reloading_list")
                    await self._page.reload(wait_until="domcontentloaded", timeout=20000)
                    await self._page.wait_for_timeout(1500)

                # JS для извлечения карточек чатов
                _CHATS_JS = r"""() => {
                    const res = [];
                    const items = document.querySelectorAll('a[data-qa*="chatik-open-chat-"]');
                    for (const el of items) {
                        const href = el.getAttribute('href') || '';
                        const qa = el.getAttribute('data-qa') || '';
                        let chatId = '';
                        const m = qa.match(/chatik-open-chat-(\d+)/) || href.match(/\/chat\/(\d+)/);
                        if (m) chatId = m[1];

                        const titleEl = el.querySelector('[data-qa="chat-cell-title"]');
                        const metaEl = el.querySelector('[data-qa="chat-cell-meta"]');
                        const subtitleEl = el.querySelector('[data-qa="chat-cell-subtitle"]');
                        const badgeEl = el.querySelector('[data-qa="chatik-info-badges"]');

                        const badgeText = badgeEl ? (badgeEl.innerText || '').trim() : '';
                        const unreadCount = parseInt(badgeText, 10) || 0;
                        const hasUnread = unreadCount > 0 || !!badgeEl;

                        const lastMsg = subtitleEl ? (subtitleEl.innerText || '').trim() : '';
                        const company = metaEl ? (metaEl.innerText || '').trim() : '';
                        const rejectRegex = /отказ|не подош|отклон|останов|не готовы пригласить|к сожалению|вынуждены отказать|другого кандидата|вакансия закрыта|позиция закрыта|архив/i;
                        const isRejection = rejectRegex.test(lastMsg) || rejectRegex.test(company);

                        res.push({
                            chat_id: chatId,
                            title: titleEl ? (titleEl.innerText || '').trim() : '',
                            company: company,
                            last_message: lastMsg,
                            unread_count: unreadCount,
                            has_unread: hasUnread,
                            is_rejection: isRejection,
                        });
                    }
                    return res;
                }"""
                chats = await self._page.evaluate(_CHATS_JS)
                for c in chats:
                    if is_rejection_text(c.get("last_message", "")) or is_rejection_text(c.get("company", "")):
                        c["is_rejection"] = True

                unread_cnt = sum(1 for c in chats if c.get("has_unread") and not c.get("is_rejection"))
                reject_cnt = sum(1 for c in chats if c.get("is_rejection"))
                log.info(
                    "hh_chat_list_scanned",
                    total=len(chats),
                    unread=unread_cnt,
                    rejections=reject_cnt,
                )
                return chats
            except Exception as e:
                log.warning("hh_chat_get_list_error", error=str(e))
                return []

    async def inspect_chat(self, chat_id: str) -> dict[str, Any] | None:
        """Открывает диалог с chat_id и извлекает последнее входящее сообщение, вопрос и варианты ответов."""
        if not self._page or self._page.is_closed():
            ok = await self.start(headless=True)
            if not ok:
                log.warning("hh_chat_start_failed_in_inspect", chat_id=chat_id)
                return None

        async with self._lock:
            try:
                target_url = f"https://hh.ru/chat/{chat_id}"
                log.info("hh_chat_inspecting_dialog", chat_id=chat_id, target_url=target_url)
                if target_url not in self._page.url:
                    await self._page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    await self._page.wait_for_timeout(2500)

                # JS для парсинга сообщений и быстрых кнопок
                _INSPECT_JS = r"""() => {
                    const res = {
                        vacancy: '',
                        company: '',
                        last_incoming_text: '',
                        last_incoming_author: '',
                        is_last_from_me: false,
                        options: [],
                        history: [],
                        is_closed: false,
                        is_rejection: false
                    };

                    // Header title / company
                    const headerTitle = document.querySelector('[class*="header-title"], [class*="header__title"]');
                    if (headerTitle) res.vacancy = headerTitle.innerText.trim();
                    const headerSub = document.querySelector('[class*="header-subtitle"], [class*="header__subtitle"]');
                    if (headerSub) res.company = headerSub.innerText.trim();

                    // Bubble messages
                    const bubbles = document.querySelectorAll('[class*="chat-bubble--"], [class*="chat-bubble-container"]');
                    const parsedMsgs = [];
                    for (const b of bubbles) {
                        const isOutgoing = b.className.includes('outgoing');
                        const authorEl = b.querySelector('[class*="author-name"]');
                        const author = authorEl ? authorEl.innerText.trim() : (isOutgoing ? 'Кандидат' : 'Рекрутер');
                        
                        const textEl = b.querySelector('[class*="chat-bubble-text--"]') || b.querySelector('[class*="chat-bubble-content"]');
                        const text = textEl ? textEl.innerText.trim() : '';
                        if (!text) continue;

                        parsedMsgs.push({
                            is_outgoing: isOutgoing,
                            author: author,
                            text: text
                        });
                    }

                    res.history = parsedMsgs.slice(-8);

                    if (parsedMsgs.length > 0) {
                        const lastMsg = parsedMsgs[parsedMsgs.length - 1];
                        res.is_last_from_me = lastMsg.is_outgoing;
                        
                        // Find last incoming
                        for (let i = parsedMsgs.length - 1; i >= 0; i--) {
                            if (!parsedMsgs[i].is_outgoing) {
                                res.last_incoming_text = parsedMsgs[i].text;
                                res.last_incoming_author = parsedMsgs[i].author;
                                break;
                            }
                        }
                    }

                    // Quick option buttons (magritte buttons with short choices like 'Да...', 'Нет...')
                    const quickBtns = [];
                    const btns = document.querySelectorAll('button[class*="magritte-button"]');
                    for (const btn of btns) {
                        const t = (btn.innerText || '').trim();
                        // Filter out navbar / chat controls
                        if (!t || t.length > 80) continue;
                        if (['Ещё', 'Помощь', 'Поиск', 'Москва', 'Понятно', 'Отменить', 'Отправить'].includes(t)) continue;
                        if (btn.closest('[data-qa="chatik-message-input"]')) continue;
                        
                        // Make sure it looks like an answer option
                        quickBtns.push(t);
                    }
                    res.options = quickBtns;

                    // Проверка закрытости чата и возможности отправки сообщений
                    const textarea = document.querySelector('textarea[data-qa="text-input"]');
                    const isInputDisabled = !textarea || textarea.disabled || textarea.readOnly || textarea.getAttribute('disabled') !== null;
                    const pageText = (document.body.innerText || '');
                    const isClosedNotice = pageText.includes('Чат закрыт') || 
                                           pageText.includes('Диалог закрыт') || 
                                           pageText.includes('нельзя отправить сообщение') ||
                                           pageText.includes('отправка сообщений отключена') ||
                                           pageText.includes('Переписка завершена') ||
                                           !!document.querySelector('[data-qa*="chat-closed"], [class*="chat-closed"], [class*="closed-banner"]');

                    res.is_closed = isClosedNotice || (isInputDisabled && quickBtns.length === 0);

                    const rejectRegex = /отказ|не подош|отклон|останов|не готовы пригласить|к сожалению|вынуждены отказать|другого кандидата|вернуться к вашей кандидатуре|желаем успехов|вакансия закрыта|позиция закрыта/i;
                    res.is_rejection = rejectRegex.test(res.last_incoming_text || '') || (isClosedNotice && quickBtns.length === 0);

                    return res;
                }"""
                data = await self._page.evaluate(_INSPECT_JS)
                if not data:
                    log.warning("hh_chat_inspect_eval_empty", chat_id=chat_id)
                    return None

                data["chat_id"] = chat_id
                if is_rejection_text(data.get("last_incoming_text", "")):
                    data["is_rejection"] = True

                log.info(
                    "hh_chat_inspect_done",
                    chat_id=chat_id,
                    company=data.get("company", ""),
                    vacancy=data.get("vacancy", ""),
                    last_incoming=(data.get("last_incoming_text", "") or "")[:60],
                    is_outgoing=data.get("is_last_from_me"),
                    is_rejection=data.get("is_rejection"),
                    is_closed=data.get("is_closed"),
                    options=data.get("options", []),
                )
                return data

            except Exception as e:
                log.error("hh_chat_inspect_error", chat_id=chat_id, error=str(e))
                return None

    async def send_option(self, chat_id: str, option_text: str) -> bool:
        """Кликает по кнопке выбора с указанным текстом в чате."""
        if not self._page or self._page.is_closed():
            ok = await self.start(headless=True)
            if not ok:
                log.warning("hh_chat_start_failed_in_send_option")
                return False

        async with self._lock:
            try:
                target_url = f"https://hh.ru/chat/{chat_id}"
                log.info("hh_chat_send_option_start", chat_id=chat_id, option=option_text)
                if target_url not in self._page.url:
                    await self._page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    await self._page.wait_for_timeout(2000)

                clicked = await self._page.evaluate(r"""(optText) => {
                    const btns = document.querySelectorAll('button[class*="magritte-button"]');
                    for (const btn of btns) {
                        const t = (btn.innerText || '').trim();
                        if (t === optText || t.toLowerCase() === optText.toLowerCase()) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }""", option_text)

                if clicked:
                    log.info("hh_chat_option_clicked_successfully", chat_id=chat_id, option=option_text)
                    await self._page.wait_for_timeout(2000)
                    # Сохраняем обновленные куки
                    await self._context.storage_state(path=str(self.storage_path))
                    return True
                else:
                    log.warning("hh_chat_option_not_found_on_page", chat_id=chat_id, option=option_text)
                    return False

            except Exception as e:
                log.error("hh_chat_send_option_error", chat_id=chat_id, error=str(e))
                return False

    async def send_text_message(self, chat_id: str, text: str) -> bool:
        """Вводит текст в поле ввода чата и отправляет его."""
        if not self._page or self._page.is_closed():
            ok = await self.start(headless=True)
            if not ok:
                log.warning("hh_chat_start_failed_in_send_message")
                return False

        async with self._lock:
            try:
                target_url = f"https://hh.ru/chat/{chat_id}"
                log.info("hh_chat_send_message_start", chat_id=chat_id, text_len=len(text), preview=text[:60])
                if target_url not in self._page.url:
                    await self._page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                    await self._page.wait_for_timeout(2000)

                ta = await self._page.query_selector('textarea[data-qa="text-input"], textarea')
                if not ta:
                    log.warning("hh_chat_input_not_found", chat_id=chat_id)
                    return False

                await ta.click()
                await ta.fill(text)
                await self._page.wait_for_timeout(500)

                # Кликаем кнопку отправки
                send_btn = await self._page.query_selector('button[data-qa="chatik-do-send-message"]')
                if send_btn:
                    await send_btn.click()
                else:
                    await ta.press("Enter")

                log.info("hh_chat_message_sent_successfully", chat_id=chat_id, length=len(text))
                await self._page.wait_for_timeout(2500)
                await self._context.storage_state(path=str(self.storage_path))
                return True

            except Exception as e:
                log.error("hh_chat_send_message_error", chat_id=chat_id, error=str(e))
                return False


# Глобальный экземпляр
hh_chat_parser = HHChatParser()
