"""
Модуль гуманизации (очеловечивания) текста откликов на основе правил
из скилла digitaltraffic-detectai/SKILL.md.
"""
from __future__ import annotations

from pathlib import Path
import structlog

log = structlog.get_logger()

# Путь к файлу скилла внутри конфигурации проекта
SKILL_PATH = Path("configs/humanizer_skill.md")

_PROMPT_CACHE: str | None = None


def _clean_skill_prompt(raw_text: str) -> str:
    """Убирает YAML-шапку (frontmatter), если она есть."""
    text = raw_text.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2].strip()
    return text


def get_humanizer_prompt() -> str:
    """Возвращает системный промпт для гуманизации текста."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE:
        return _PROMPT_CACHE

    try:
        if SKILL_PATH.exists():
            raw = SKILL_PATH.read_text(encoding="utf-8")
            cleaned = _clean_skill_prompt(raw)
            if cleaned:
                log.info("humanizer_prompt_loaded_from_file", path=str(SKILL_PATH), length=len(cleaned))
                _PROMPT_CACHE = cleaned
                return _PROMPT_CACHE
    except Exception as e:
        log.warning("humanizer_file_read_error", path=str(SKILL_PATH), error=str(e))

    fallback = (
        "Ты редактор, который убирает признаки ИИ-генерации из русскоязычных текстов "
        "и возвращает живой голос.\n\n"
        "Правила:\n"
        "1. Убирай канцеляризмы ('данный' -> 'этот', 'является' -> тире/убрать, 'осуществляет' -> глагол).\n"
        "2. Убирай восторженные эпитеты и штампы ('инновационный', 'уникальный', 'важно отметить').\n"
        "3. Избегай одинаковой длины предложений и стерильного тона.\n"
        "4. Сохраняй сухой инженерный стиль и технические факты."
    )
    _PROMPT_CACHE = fallback
    return _PROMPT_CACHE
