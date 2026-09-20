"""
Модуль для динамического получения актуального списка моделей Google Gemini
из официальной документации Google AI (ai.google.dev) и API-эндпоинта /models.
"""
from __future__ import annotations

import re
import httpx
import structlog
from app.config import settings

log = structlog.get_logger()

DOCS_MODELS_URL = "https://ai.google.dev/gemini-api/docs/models?hl=en"

# Исключения для веб-ресурсов и CSS-классов с сайта ai.google.dev
NON_MODEL_KEYWORDS = {
    "logo", "dark-theme", "svg", "png", "card", "cta", "elevation", "hovercard",
    "header", "switcher", "font", "table", "grid", "button", "desc", "details",
    "row", "centered", "small", "overview", "links", "title", "width", "item",
    "footer", "supported", "not-supported", "recommended", "new", "experimental"
}


def _is_valid_model_name(name: str) -> bool:
    """Фильтрует истинные модели (gemini-3.8-flash и т.д.) от HTML/CSS-классов."""
    if not name.startswith("gemini-"):
        return False
    if any(ext in name for ext in (".png", ".svg", ".jpg", ".css", ".js")):
        return False
    parts = name.split("-")
    if len(parts) < 2:
        return False
    # Проверяем, не является ли имя версткой (например, gemini-api-card)
    for kw in NON_MODEL_KEYWORDS:
        if kw in parts:
            return False
            
    # Google no longer supports models below version 3
    version_match = re.search(r"gemini-(\d+)\.", name)
    if version_match:
        major_version = int(version_match.group(1))
        if major_version < 3:
            return False
            
    return True


async def fetch_live_google_models() -> list[str]:
    """
    Динамически запрашивает актуальные модели Google Gemini:
    1. Пробует вызывать GET /models через настроенный llm_base_url (если есть доступ).
    2. В случае неудачи или геоблокировки спарсит официальный веб-документ ai.google.dev.
    """
    models: list[str] = []

    # 1. Попытка через API (если задан LLM_API_KEY и работает прокси/эндпоинт)
    if settings.llm_api_key and settings.llm_base_url:
        try:
            async with httpx.AsyncClient(
                base_url=settings.llm_base_url.rstrip("/"),
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                timeout=httpx.Timeout(10.0),
            ) as client:
                resp = await client.get("/models")
                if resp.status_code == 200:
                    data = resp.json()
                    raw_models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
                    # For API, model names might be formatted as 'models/gemini-...', so strip prefix if needed
                    models = []
                    for m in raw_models:
                        clean_m = m.replace("models/", "")
                        if _is_valid_model_name(clean_m):
                            models.append(clean_m)
                    if models:
                        log.info("google_models_fetched_from_api", count=len(models))
                        return sorted(set(models))
        except Exception as e:
            log.debug("fetch_models_api_failed", error=str(e)[:100])

    # 2. Фолбэк — чтение в реальном времени официальной документации ai.google.dev
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(DOCS_MODELS_URL)
            if resp.status_code == 200:
                raw_matches = re.findall(r"gemini-[a-zA-Z0-9\.\-]+", resp.text)
                clean_models = set()
                for m in raw_matches:
                    cleaned = m.rstrip("\"'/,>").lower()
                    if _is_valid_model_name(cleaned):
                        clean_models.add(cleaned)
                models = sorted(clean_models)
                log.info("google_models_fetched_from_docs", count=len(models))
                return models
    except Exception as e:
        log.warning("fetch_models_docs_failed", error=str(e)[:100])

    return models
