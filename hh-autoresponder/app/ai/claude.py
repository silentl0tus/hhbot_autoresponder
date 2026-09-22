import json
import re
import httpx
import structlog

from app.config import settings
from app.ai.prompts import (
    SYSTEM_REPLY_GENERATOR,
    SYSTEM_SENTIMENT_ANALYZER,
    SYSTEM_COVER_LETTER_GENERATOR,
    SYSTEM_SCREENER_ANSWER_GENERATOR,
    SYSTEM_HH_SCREENER_GENERATOR,
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


def clean_screener_answer(text: str) -> str:
    """Очищает сгенерированный ответ скринеру от мета-текста, преамбул и альтернативных вариантов."""
    if not text:
        return ""

    # Если модель вернула разделитель '---' или '***' с альтернативами, отсекаем всё после него
    if "---" in text:
        text = text.split("---", 1)[0]
    if "***" in text:
        text = text.split("***", 1)[0]

    lines = [line.strip() for line in text.split("\n")]
    filtered_lines = []

    # Регулярки для отлова мусорных строк ассистента
    meta_patterns = [
        r"^(вот\s+вариант|вариант\s+\d|ещ[её]\s+вариант|как\s+бы\s+ответил|как\s+мог\s+бы|предлагаемый\s+вариант|ответ:|пример\s+ответа|конечно|держи\s+вариант|вот\s+как)",
        r"^\*?\*?(вариант|ещ[её]\s+вариант|короткий\s+вариант).*",
        r"^(первый\s+вариант|второй\s+вариант).*",
    ]

    for line in lines:
        if not line:
            if filtered_lines and filtered_lines[-1] != "":
                filtered_lines.append("")
            continue

        lower = line.lower()
        if any(re.match(pat, lower) for pat in meta_patterns):
            continue

        filtered_lines.append(line)

    result = "\n".join(filtered_lines).strip()
    # Убираем обрамляющие кавычки
    if (result.startswith('"') and result.endswith('"')) or (result.startswith('«') and result.endswith('»')):
        result = result[1:-1].strip()

    return result


def clean_cover_letter(text: str) -> str:
    """Очищает текст сопроводительного письма от вводных фраз ('Откликаюсь на вакансию...'),
    мета-преамбул и лишних кавычек."""
    if not text:
        return ""

    # Убираем преамбулы вроде "Text:", "Письмо:", "Сопроводительное письмо:"
    text = re.sub(r"^(Text|Сопроводительное письмо|Письмо|Текст письма):\s*", "", text, flags=re.IGNORECASE).strip()

    # Шаблоны фраз отклика, которые избыточны в интерфейсе чата HH
    vacancy_intro_pattern = re.compile(
        r"^(откликаюсь\s+на\s+вакансию|пишу\s+(вам\s+)?(по\s+поводу|относительно|по)\s+ваканси|меня\s+заинтересовала\s+(ваша\s+)?вакансия|подаю\s+отклик|хочу\s+откликнуться|направляю\s+(свой\s+)?отклик|рассматриваю\s+вакансию)",
        re.IGNORECASE,
    )

    lines = [line.strip() for line in text.split("\n")]
    filtered_lines = []

    for line in lines:
        if not line:
            if filtered_lines and filtered_lines[-1] != "":
                filtered_lines.append("")
            continue

        cleaned_line = line
        # Если строка начинается с приветствия, например "Здравствуйте! Откликаюсь на вакансию..."
        greeting_match = re.match(r"^(здравствуйте|добрый\s+день)[!.,]?\s+(.*)", cleaned_line, re.IGNORECASE)
        if greeting_match:
            remainder = greeting_match.group(2).strip()
            if vacancy_intro_pattern.match(remainder):
                continue

        if vacancy_intro_pattern.match(cleaned_line):
            continue

        filtered_lines.append(line)

    result = "\n".join(filtered_lines).strip()
    if (result.startswith('"') and result.endswith('"')) or (result.startswith('«') and result.endswith('»')):
        result = result[1:-1].strip()

    return result


OPENROUTER_FREE_FALLBACK_MODELS = [
    "nex-agi/nex-n2.5-pro:free",
    "nex-agi/nex-n2.5-mini:free",
    "liquid/lfm-2.5-2.6b:free",
    "inclusionai/ling-3.0-flash-vl:free",
    "qwen/qwen3.8-27b:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3.5-lightning:free",
    "z-ai/glm-5.2:free",
    "deepseek/deepseek-v4-flash-0731:free",
]

# Паттерны «отказа ассистента» — модель не следует промпту и пишет сервисное сообщение.
# Такой текст нельзя отправлять в отклик вместо сопроводительного письма.
ASSISTANT_REFUSAL_PATTERNS = [
    "не могу обработать",
    "не могу выполнить",
    "не могу создать",
    "не могу помочь",
    "не в состоянии",
    "как языковая модель",
    "как искусственный интеллект",
    "как иИ",
    "as an ai",
    "as a language model",
    "i cannot",
    "i'm unable",
    "i am unable",
    "i'm not able",
    "i cannot process",
    "cannot fulfill",
    "я всего лишь языковая модель",
    "я являюсь языковой моделью",
    "прошу прощения",
    "не имею возможности",
    "к сожалению, я не могу",
    "отсутствуют сведения",
    "невозможно сопоставить",
    "пришлите фактический профиль",
    "в предоставленном профиле",
    "без вымышленных утверждений невозможно",
]




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
        try:
            self._client = httpx.AsyncClient(**client_kwargs)
        except ValueError as e:
            import structlog
            structlog.get_logger().error("invalid_proxy_scheme", error=str(e), proxy=proxy)
            client_kwargs.pop("proxy", None)
            client_kwargs["trust_env"] = False
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
        try:
            self._client = httpx.AsyncClient(**client_kwargs)
        except ValueError as e:
            import structlog
            structlog.get_logger().error("invalid_proxy_scheme", error=str(e), proxy=proxy)
            client_kwargs.pop("proxy", None)
            client_kwargs["trust_env"] = False
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

        primary_model = model or settings.llm_model
        fallback_chain: list[str] = [primary_model]

        is_openrouter = "openrouter" in settings.llm_base_url
        if is_openrouter:
            for fb in OPENROUTER_FREE_FALLBACK_MODELS:
                if fb not in fallback_chain:
                    fallback_chain.append(fb)
        elif "generativelanguage" in settings.llm_base_url:
            google_preset = [
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.5-flash"
            ]
            for fb in google_preset:
                if fb not in fallback_chain:
                    fallback_chain.append(fb)

            live_models = await fetch_live_google_models()
            for fb in live_models:
                if fb not in fallback_chain:
                    fallback_chain.append(fb)

        last_error_text = ""

        for attempt_idx, candidate_model in enumerate(fallback_chain):
            payload = {
                "model": candidate_model,
                "max_tokens": max_tokens,
                "temperature": 0.15,  # Жесткий контроль галлюцинаций
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            }
            try:
                resp = await self._client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()

                choice = (data.get("choices") or [{}])[0]
                msg = choice.get("message") or {}
                text = msg.get("content") or ""

                # Никогда не используем msg.get("reasoning") как текст ответа:
                # это внутренний черновик/ход мыслей нейросети.
                if text:
                    # Очищаем блоки рассуждений <think>...</think> или <thought>...</thought>
                    text = re.sub(r"<(think|thought)>.*?</\1>", "", text, flags=re.DOTALL).strip()
                    # Если генерация оборвалась внутри незакрытого тега рассуждений
                    if "<think>" in text or "<thought>" in text:
                        text = re.sub(r"<(think|thought)>.*", "", text, flags=re.DOTALL).strip()

                if text:
                    # Если ответ получен через fallback-модель, автоматически переключаем активную модель
                    if candidate_model != primary_model:
                        log.info(
                            "llm_fallback_switched",
                            prev_model=primary_model,
                            new_model=candidate_model,
                            attempt=attempt_idx + 1,
                        )
                        self.set_model(candidate_model)

                    usage = data.get("usage") or {}
                    return (
                        text,
                        int(usage.get("prompt_tokens", 0) or 0),
                        int(usage.get("completion_tokens", 0) or 0),
                    )
                else:
                    last_error_text = f"Модель {candidate_model} вернула пустой контент (или только мысли reasoning)"
                    log.warning("llm_empty_response", model=candidate_model)
            except httpx.HTTPStatusError as e:
                last_error_text = f"HTTP {e.response.status_code} ({candidate_model}): {e.response.text[:150]}"
                log.warning(
                    "llm_call_error_trying_fallback",
                    model=candidate_model,
                    status_code=e.response.status_code,
                    attempt=attempt_idx + 1,
                    total_candidates=len(fallback_chain),
                    error=last_error_text,
                )
            except Exception as e:
                last_error_text = f"{type(e).__name__} ({candidate_model}): {str(e)[:150]}"
                log.warning(
                    "llm_call_error_trying_fallback",
                    model=candidate_model,
                    error=last_error_text,
                    attempt=attempt_idx + 1,
                )

        self.last_error = last_error_text or "Все модели в цепочке fallback завершились ошибкой"
        return "", 0, 0

    async def generate_cover_letter(self, vacancy_title: str, vacancy_description: str, company_name: str = "", humanize: bool = False, feedback: str = "") -> tuple[str, int, int]:
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
        user_msg = (
            "Напиши сопроводительное письмо для этой вакансии. "
            "Начинай сразу с ключевых фактов и стека, без вводной фразы 'Откликаюсь на вакансию'."
        )
        if feedback:
            user_msg += f"\n\nСгенерируй письмо заново, ОБЯЗАТЕЛЬНО учтя следующее исправление/ошибку от пользователя:\n{feedback}"
        # Лимит 2500 токенов достаточен и для текста письма, и для запаса на reasoning-модели
        text, inp_tok, out_tok = await self._call(system, user_msg, max_tokens=2500)
        
        # Очищаем от вводных фраз отклика ("Откликаюсь на вакансию..."), которые уже есть в интерфейсе HH
        if text:
            text = clean_cover_letter(text)

        # Валидация: письмо соискателя на русском языке не должно быть сырым дампом рассуждений на английском
        if text:
            has_cyrillic = bool(re.search(r"[а-яёА-ЯЁ]", text))
            has_reasoning_leak = any(marker in text.lower() for marker in (
                "we need answer", "candidate has", "strict facts", "forbidden exact phrase", "need map requirements"
            ))
            if not has_cyrillic or has_reasoning_leak:
                log.warning(
                    "ai_cover_letter_invalid_output_rejected",
                    has_cyrillic=has_cyrillic,
                    has_reasoning_leak=has_reasoning_leak,
                    preview=text[:150],
                )
                text = ""

        # Фильтр паттернов «отказа ассистента»:
        # модель не следует промпту и пишет сервисное сообщение вместо письма.
        if text:
            text_lower = text.lower()
            refusal_hit = next(
                (p for p in ASSISTANT_REFUSAL_PATTERNS if p in text_lower), None
            )
            if refusal_hit:
                log.warning(
                    "ai_cover_letter_refusal_pattern_rejected",
                    pattern=refusal_hit,
                    preview=text[:200],
                )
                text = ""

        if not text:
            err_reason = self.last_error or "LLM API вернул пустой или некорректный ответ"
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
            humanized_text, h_inp, h_out = await self._call(humanize_system, humanize_msg, max_tokens=2500)
            if humanized_text and re.search(r"[а-яёА-ЯЁ]", humanized_text):
                text = clean_cover_letter(humanized_text)
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

    async def generate_screener_answer(
        self,
        question: str,
        vacancy_context: str = "",
        history: str = "",
        humanize: bool = True,
    ) -> tuple[str, int, int]:
        """Генерирует емкий и точный ответ соискателя на вопрос-скринер рекрутера."""
        if not _ai_ready():
            return "Здравствуйте! Подтверждаю интерес к вакансии, готов обсудить детали.", 0, 0

        system = SYSTEM_SCREENER_ANSWER_GENERATOR.format(
            resume=settings.resume_text,
            salary_min=settings.desired_salary_min,
            salary_max=settings.desired_salary_max,
        )
        user_msg = f"Вопрос скринера:\n{question}"
        if vacancy_context:
            user_msg += f"\n\nКонтекст вакансии:\n{vacancy_context}"
        if history:
            user_msg += f"\n\nПредыдущий диалог:\n{history}"

        text, inp_tok, out_tok = await self._call(system, user_msg, max_tokens=600)
        if not text:
            err_reason = self.last_error or "LLM API вернул пустой ответ"
            log.warning("ai_screener_generation_failed", error=err_reason)
            return "", 0, 0

        if humanize:
            humanize_system = (
                "Ты — соискатель, редактирующий собственное короткое сообщение рекрутеру.\n"
                "Твоя цель: убрать признаки ИИ-генерации (канцеляризмы 'данный/является/осуществляет', "
                "клише, стерильность) и сделать текст живым, разговорно-деловым и естественным, сохранив все технические факты.\n"
                "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать преамбулы ('Вот вариант', 'Как мог бы написать живой человек') "
                "и предлагать несколько вариантов ответа. Выведи СТРОГО ЕДИНСТВЕННЫЙ готовый текст сообщения соискателя."
            )
            humanize_msg = f"Отредактируй это сообщение для чата:\n{text}"
            humanized_text, h_inp, h_out = await self._call(humanize_system, humanize_msg, max_tokens=600)
            if humanized_text:
                text = humanized_text
            inp_tok += h_inp
            out_tok += h_out

        clean_text = clean_screener_answer(text)
        return clean_text or text.strip(), inp_tok, out_tok

    async def generate_hh_answer(
        self,
        question: str,
        options: list[str] | None = None,
        vacancy_title: str = "",
        company_name: str = "",
        history: str = "",
        humanize: bool = True,
    ) -> tuple[str, str | None, int, int]:
        """
        Генерирует ответ на вопрос работодателя/робота в чате HeadHunter.
        Если переданы options (варианты выбора), AI сопоставляет резюме с вариантами
        и возвращает (текстовый_ответ, рекомендуемый_вариант, inp_tok, out_tok).
        """
        if not _ai_ready():
            first_opt = options[0] if options else None
            return "Здравствуйте! Подтверждаю интерес к вакансии, готов обсудить стек и детали.", first_opt, 0, 0

        system = SYSTEM_HH_SCREENER_GENERATOR.format(
            resume=settings.resume_text,
            salary_min=settings.desired_salary_min,
            salary_max=settings.desired_salary_max,
        )

        user_msg = f"Вопрос от работодателя/рекрутера:\n{question}"
        if options:
            opts_str = "\n".join(f"- {opt}" for opt in options)
            user_msg += f"\n\nПредложенные варианты выбора:\n{opts_str}"
        if vacancy_title or company_name:
            user_msg += f"\n\nКонтекст: Вакансия '{vacancy_title}' в компании '{company_name}'"
        if history:
            user_msg += f"\n\nПредыдущие сообщения:\n{history}"

        text, inp_tok, out_tok = await self._call(system, user_msg, max_tokens=600)
        if not text:
            err_reason = self.last_error or "LLM API вернул пустой ответ"
            log.warning("ai_hh_answer_generation_failed", error=err_reason)
            first_opt = options[0] if options else None
            return "", first_opt, 0, 0

        # Парсим RECOMMENDED_OPTION, если были варианты
        recommended_opt = None
        clean_lines = []
        for line in text.split("\n"):
            line_s = line.strip()
            if line_s.startswith("RECOMMENDED_OPTION:"):
                raw_opt = line_s.replace("RECOMMENDED_OPTION:", "").strip().strip('"').strip("'")
                if options:
                    for opt in options:
                        if opt.lower() in raw_opt.lower() or raw_opt.lower() in opt.lower():
                            recommended_opt = opt
                            break
                    if not recommended_opt:
                        recommended_opt = raw_opt
            else:
                clean_lines.append(line)

        text_body = "\n".join(clean_lines).strip()

        if humanize and text_body:
            humanize_system = (
                "Ты — соискатель, редактирующий собственное короткое сообщение рекрутеру.\n"
                "Твоя цель: убрать признаки ИИ-генерации (канцеляризмы 'данный/является/осуществляет', "
                "клише, стерильность) и сделать текст живым, разговорно-деловым и естественным, сохранив все технические факты.\n"
                "КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО писать преамбулы ('Вот вариант', 'Как мог бы написать живой человек') "
                "и предлагать несколько вариантов ответа. Выведи СТРОГО ЕДИНСТВЕННЫЙ готовый текст сообщения соискателя."
            )
            humanize_msg = f"Отредактируй это сообщение для чата:\n{text_body}"
            humanized_text, h_inp, h_out = await self._call(humanize_system, humanize_msg, max_tokens=600)
            if humanized_text:
                text_body = humanized_text
            inp_tok += h_inp
            out_tok += h_out

        clean_text = clean_screener_answer(text_body)
        return clean_text or text_body, recommended_opt, inp_tok, out_tok

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


    async def generate_custom_idea_answer(
        self,
        question: str,
        user_idea: str,
    ) -> str:
        """Генерирует финальный ответ рекрутеру на основе черновой мысли пользователя."""
        if not settings.ai_enabled:
            return user_idea
            
        from app.ai.prompts import SYSTEM_CUSTOM_IDEA_GENERATOR
        
        sys_prompt = SYSTEM_CUSTOM_IDEA_GENERATOR.format(
            question=question,
            user_idea=user_idea,
        )
        user_prompt = "Пожалуйста, сформируй ответ на основе моей идеи."
        
        ans, inp, outp = await self._call(sys_prompt, user_prompt, max_tokens=300)
        return clean_screener_answer(ans) if ans else user_idea


claude_ai = ClaudeAI()
