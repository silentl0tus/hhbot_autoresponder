"""
Оценка вакансии по правилам, без трат AI-токенов.

Балл складывается из явных сигналов: совпадение по заголовку, стек, зарплата,
удалёнка, уровень. Все ключевые слова задаются в .env:
  TARGET_KEYWORDS_RAW   — хотя бы одно в заголовке → вакансия подходит
  NEGATIVE_KEYWORDS_RAW — есть в заголовке → дисквалификация
  STACK_KEYWORDS_RAW    — каждое совпадение в тексте даёт бонус к баллу
  SALARY_FLOOR          — вакансии с указанной ЗП ниже отсеиваются
"""
from __future__ import annotations

import re

from app.config import settings

# Сигналы уровня (для небольшого бонуса)
LEVEL_MIDDLE = [r"\bmiddle\b", r"\bmid\b", r"\bсредн"]
LEVEL_SENIOR = [
    r"\bsenior\b", r"\bстарш", r"\bлид\b", r"\blead\b", r"\bhead\b",
    r"\bprincipal\b", r"\bархитектор\b", r"\barchitect\b",
    r"руководител", r"директор", r"начальник", r"глава",
]
# Дополнительные слова, которые указывают на Senior-уровень в заголовке
# (не затрагивают описание, только title-фильтр)
LEVEL_SENIOR_TITLE_EXTRA = [
    r"\bexpert\b", r"\bэксперт\b",
    r"\bteam\s*lead\b", r"\btech\s*lead\b",
    r"ведущий", r"главный",
]


def _match_any_re(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def _contains_any(text: str, words: list[str]) -> bool:
    return any(w.lower() in text for w in words)


def analyze_vacancy(
    title: str,
    description: str = "",
    skills: str = "",
    salary_from: int | None = None,
    salary_to: int | None = None,
    is_remote: bool = False,
    salary_currency: str = "",
    desired_salary_min: int = 150000,
    desired_salary_max: int = 400000,
) -> dict:
    t = (title or "").lower()
    d = (description or "").lower()
    s_skills = (skills or "").lower()
    full = f"{t}\n{d}\n{s_skills}"

    red_flags: list[str] = []

    # 1. Заголовок должен содержать хотя бы одно целевое слово
    has_target = _contains_any(t, settings.target_keywords)
    if not has_target:
        return {
            "score": 0, "reason": "Заголовок не соответствует целевым словам",
            "is_relevant": False, "seniority": "unknown",
            "red_flags": ["title_mismatch"], "stack_match": 0,
        }

    # 2. Железная дисквалификация Senior/Lead в заголовке.
    # Если в заголовке есть Senior/Lead/Head/Архитектор и нет явного указания Middle/Junior (вилки) -> отказ
    has_senior_title = _match_any_re(t, LEVEL_SENIOR) or _match_any_re(t, LEVEL_SENIOR_TITLE_EXTRA)
    has_middle_or_jun_title = _match_any_re(t, LEVEL_MIDDLE) or bool(
        re.search(r"\bjunior\b|\bjun\b|\bджуниор\b|\bмладш", t, re.IGNORECASE)
    )
    if has_senior_title and not has_middle_or_jun_title:
        matched = next(
            (p for p in LEVEL_SENIOR + LEVEL_SENIOR_TITLE_EXTRA if re.search(p, t, re.IGNORECASE)),
            "неизвестно",
        )
        return {
            "score": 0, "reason": f"Отказ (Senior уровень, паттерн: '{matched}')",
            "is_relevant": False, "seniority": "senior",
            "red_flags": ["senior_level"], "stack_match": 0,
        }

    # 3. Стоп-слова в заголовке — контекстная дисквалификация.
    #    Если заголовок содержит стоп-слово И целевое слово одновременно
    #    (напр. "AI Engineer") — НЕ дисквалифицируем, а штрафуем -10.
    #    Если целевого слова нет (напр. "Java Developer") —
    #    дисквалификация (score=0).
    has_negative = _contains_any(t, settings.negative_keywords)
    negative_penalty = 0
    if has_negative:
        if not has_target:
            return {
                "score": 0, "reason": "Дисквалифицировано стоп-словом",
                "is_relevant": False, "seniority": "unknown",
                "red_flags": ["negative_keyword"], "stack_match": 0,
            }
        # Есть и стоп-слово, и целевое → штраф, не дисквалификация
        negative_penalty = -10
        red_flags.append("negative_keyword_soft")

    # 3. Зарплата ниже порога (если указана и в рублях) — отсеиваем
    cur = (salary_currency or "").upper()
    if (salary_from or salary_to) and cur in ("", "RUR", "RUB", "РУБ"):
        best = max(salary_from or 0, salary_to or 0)
        if 0 < best < settings.salary_floor:
            return {
                "score": 0, "reason": f"Зарплата {best} ниже порога {settings.salary_floor}",
                "is_relevant": False, "seniority": "unknown",
                "red_flags": ["salary_below_floor"], "stack_match": 0,
            }

    # 4. Считаем балл
    score = 15  # совпал заголовок (снижено с 30 для обязательного наличия стека/бонусов)
    score += negative_penalty  # штраф за стоп-слово (если был)

    stack_hits = sum(1 for kw in settings.stack_keywords if kw.lower() in full)
    stack_score = min(stack_hits * 5, 40)
    score += stack_score

    # Зарплата
    if salary_from or salary_to:
        if salary_from and salary_to:
            sal_mid = (salary_from + salary_to) // 2
        else:
            sal_mid = salary_from or salary_to or 0
        if sal_mid >= desired_salary_min:
            score += 15
        elif sal_mid >= desired_salary_min * 0.7:
            score += 5
        else:
            red_flags.append("low_salary")

    # Удалёнка
    if is_remote or "удалён" in d or "удален" in d or "remote" in d:
        score += 5

    # Уровень
    seniority = "middle"
    is_senior = _match_any_re(full, LEVEL_SENIOR)
    is_middle = _match_any_re(full, LEVEL_MIDDLE)
    # Бонус: junior + middle одновременно в заголовке (напр. "Junior / Middle AI Engineer")
    # — это наша целевая зона, +15.
    has_junior_title = bool(re.search(r"\bjunior\b|\bjun\b|\bджуниор\b|\bмладш", t, re.IGNORECASE))
    if has_junior_title and is_middle:
        seniority = "junior_middle"
        score += 15
    elif is_senior and not is_middle:
        # Проходим сюда только если Senior есть в описании, но не в заголовке.
        # (заголовок уже проверен выше)
        seniority = "senior"
        matched_desc = next(
            (p for p in LEVEL_SENIOR if re.search(p, full, re.IGNORECASE)),
            "неизвестно",
        )
        return {
            "score": 0, "reason": f"Отказ (Senior уровень в описании, паттерн: '{matched_desc}')",
            "is_relevant": False, "seniority": "senior",
            "red_flags": ["senior_level"], "stack_match": 0,
        }
    elif is_middle:
        score += 10

    score = max(0, min(score, 100))

    return {
        "score": score,
        "reason": f"title=ok, stack={stack_hits}({stack_score}p), level={seniority}{', neg_soft' if negative_penalty else ''}",
        "is_relevant": score >= 60,
        "seniority": seniority,
        "red_flags": red_flags,
        "stack_match": stack_score * 100 // 40 if stack_score else 0,
    }
