import json

import httpx
import structlog

from app.config import settings
from app.ai.prompts import (
    SYSTEM_REPLY_GENERATOR,
    SYSTEM_SENTIMENT_ANALYZER,
    SYSTEM_COVER_LETTER_GENERATOR,
)
from app.ai.humanizer import get_humanizer_prompt
from app.ai.google_models import fetch_live_google_models

log = structlog.get_logger()

MODEL = settings.llm_model
# Модель для прохождения тестов вакансий (ответы на вопросы/тесты работодателя)
TEST_MODEL = settings.llm_model


def _ai_ready() -> bool:
    """AI используется только если включён и задан ключ."""
    return bool(settings.ai_enabled and settings.llm_api_key)


class ClaudeAI:
    """Опциональный LLM-помощник (OpenAI-совместимый эндпоинт, напр. polza.ai).

    Нужен ТОЛЬКО для прохождения тестов/анкет работодателя и ответов рекрутёрам.
    Если AI выключен (AI_ENABLED=false или нет ключа) — методы возвращают
    безопасные заглушки, бот продолжает откликаться без AI.
    """

    def __init__(self):
        client_kwargs = {
            "base_url": settings.llm_base_url.rstrip("/"),
            "headers": {"Authorization": f"Bearer {settings.llm_api_key}"},
            "timeout": httpx.Timeout(240.0, connect=30.0),
        }
        proxy = settings.llm_proxy or settings.proxy_url
        if proxy:
            client_kwargs["proxy"] = proxy
        self._client = httpx.AsyncClient(**client_kwargs)
        self._floor = settings.llm_max_tokens_floor
        self.last_error: str | None = None

    def reset_fallback(self):  # совместимость со старым интерфейсом
        pass

    def reinit_client(self):
        """Пересоздает HTTP клиент с обновленными settings."""
        client_kwargs = {
            "base_url": settings.llm_base_url.rstrip("/"),
            "headers": {"Authorization": f"Bearer {settings.llm_api_key}"},
            "timeout": httpx.Timeout(240.0, connect=30.0),
        }
        proxy = settings.llm_proxy or settings.proxy_url
        if proxy:
            client_kwargs["proxy"] = proxy
        self._client = httpx.AsyncClient(**client_kwargs)
        self.last_error = None
        log.info("llm_client_reinitialized", base_url=settings.llm_base_url, has_proxy=bool(proxy))

    def set_model(self, model_name: str):
        """Переключает активную модель LLM в памяти и обновляет .env."""
        settings.llm_model = model_name
        try:
            from app.config import save_env_variable
            save_env_variable("LLM_MODEL", model_name)
        except Exception as e:
            log.warning("update_env_model_failed", error=str(e))
        log.info("llm_model_changed", new_model=model_name)

    async def get_available_models(self) -> list[str]:
        """Динамически получает актуальные модели Google из API / документации."""
        return await fetch_live_google_models()

    async def _call(self, system: str, user_message: str, max_tokens: int = 1024, model: str | None = None) -> tuple[str, int, int]:
        self.last_error = None
        if not _ai_ready():
            if not settings.ai_enabled:
                self.last_error = "AI выключен в настройках (AI_ENABLED=false)"
            elif not settings.llm_api_key:
                self.last_error = "Не задан LLM_API_KEY в .env"
            return "", 0, 0

        # Reasoning-модели тратят часть бюджета max_tokens на «мысли» — держим
        # щедрый нижний порог, иначе видимый ответ приходит пустым.
        if max_tokens < self._floor:
            max_tokens = self._floor
        payload = {
            "model": model or settings.llm_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        }
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            self.last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            log.warning("llm_call_error", error=self.last_error)
            return "", 0, 0
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            log.warning("llm_call_error", error=self.last_error)
            return "", 0, 0

        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage") or {}
        return text, int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)

    async def generate_cover_letter(self, vacancy_title: str, vacancy_description: str, company_name: str = "", humanize: bool = False) -> tuple[str, int, int]:
        if not _ai_ready():
            reason = "AI выключен в настройках" if not settings.ai_enabled else "Отсутствует LLM_API_KEY"
            log.info("ai_disabled_fallback_used", reason=reason)
            return settings.cover_letter, 0, 0

        system = SYSTEM_COVER_LETTER_GENERATOR.format(
            resume=settings.resume_text,
            company_name=company_name or "Уважаемый работодатель",
            vacancy_title=vacancy_title,
            vacancy_description=vacancy_description[:2000]  # Limit to save tokens
        )
        user_msg = "Напиши сопроводительное письмо для этой вакансии."
        text, inp_tok, out_tok = await self._call(system, user_msg, max_tokens=1500)
        
        if not text:
            err_reason = self.last_error or "LLM API вернул пустой ответ"
            log.warning("ai_cover_letter_generation_failed", error=err_reason)
            try:
                from app.utils import notifier
                await notifier.send(
                    f"⚠️ <b>Внимание: Использована заглушка для отклика!</b>\n\n"
                    f"📌 <b>Вакансия:</b> {vacancy_title}\n"
                    f"❌ <b>Причина ошибки LLM API:</b>\n<code>{err_reason}</code>\n\n"
                    f"📝 <i>Отправлен дефолтный шаблон из .env</i>"
                )
            except Exception as e:
                log.warning("notifier_error", error=str(e))
            return settings.cover_letter, 0, 0

        if humanize:
            humanize_system = get_humanizer_prompt()
            humanize_msg = f"Очеловечь следующий текст сопроводительного письма, используя свои правила:\n\n{text}"
            humanized_text, h_inp, h_out = await self._call(humanize_system, humanize_msg, max_tokens=1500)
            if humanized_text:
                text = humanized_text
            else:
                err_reason = self.last_error or "Ошибка при очеловечивании письма"
                log.warning("humanizer_failed", error=err_reason)
            inp_tok += h_inp
            out_tok += h_out

        return text.strip(), inp_tok, out_tok

    async def generate_reply(self, recruiter_message: str, vacancy_context: str = "", platform: str = "") -> tuple[str, int, int]:
        if not _ai_ready():
            return "", 0, 0
        system = SYSTEM_REPLY_GENERATOR.format(
            resume=settings.resume_text,
            salary_min=settings.desired_salary_min,
            salary_max=settings.desired_salary_max,
            platform="hh.ru",
        )
        user_msg = f"Сообщение рекрутера:\n{recruiter_message}\n\nКонтекст вакансии:\n{vacancy_context}"
        text, inp_tok, out_tok = await self._call(system, user_msg, max_tokens=512)
        if not text:
            err_reason = self.last_error or "LLM API вернул пустой ответ"
            log.warning("ai_reply_generation_failed", error=err_reason)
            try:
                from app.utils import notifier
                await notifier.send(
                    f"⚠️ <b>Ошибка при генерации ответа рекрутёру через AI!</b>\n\n"
                    f"❌ <b>Причина ошибки LLM API:</b>\n<code>{err_reason}</code>"
                )
            except Exception as e:
                log.warning("notifier_error", error=str(e))
            return "", 0, 0
        return text.strip(), inp_tok, out_tok

    async def analyze_sentiment(self, message: str) -> dict:
        default = {"sentiment": "neutral", "intent": "info", "urgency": "low", "summary": message[:100]}
        if not _ai_ready():
            return default
        text, _, _ = await self._call(SYSTEM_SENTIMENT_ANALYZER, message, max_tokens=256)
        try:
            clean = text.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1].rsplit("```", 1)[0]
            return json.loads(clean)
        except (json.JSONDecodeError, IndexError):
            return default


    async def test_connection(self) -> tuple[bool, str]:
        """Проверяет подключение к LLM API и возвращает (успех, сообщение/ошибка)."""
        if not settings.llm_api_key:
            return False, "Не задан LLM_API_KEY в .env или настройках"

        payload = {
            "model": settings.llm_model,
            "max_tokens": 50,
            "messages": [
                {"role": "user", "content": "Ping! Reply with 'Pong'"},
            ],
        }
        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            choice = (data.get("choices") or [{}])[0]
            text = ((choice.get("message") or {}).get("content") or "").strip()
            return True, text or "OK"
        except httpx.HTTPStatusError as e:
            err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            self.last_error = err
            return False, err
        except Exception as e:
            err = f"{type(e).__name__}: {str(e)[:200]}"
            self.last_error = err
            return False, err


claude_ai = ClaudeAI()
