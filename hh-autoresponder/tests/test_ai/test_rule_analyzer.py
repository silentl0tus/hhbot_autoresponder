import pytest
from app.ai.rule_analyzer import _match_any_re, LEVEL_SENIOR, LEVEL_MIDDLE
from app.ai.rule_analyzer import analyze_vacancy

def test_senior_level_disqualification():
    """Тест: Чистые Senior вакансии должны получать 0 баллов."""
    title = "Senior Python Developer"
    desc = "Ищем Senior разработчика с опытом от 5 лет. Подчинение CTO."
    
    # Мокаем config/settings внутри если нужно, но _match_any_re работает статично
    is_senior = _match_any_re(title + desc, LEVEL_SENIOR)
    is_middle = _match_any_re(title + desc, LEVEL_MIDDLE)
    
    assert is_senior is True
    assert is_middle is False
    
    res = analyze_vacancy(title, desc, skills="")
    assert res["score"] == 0
    assert res["is_relevant"] is False
    assert res["reason"] == "Отказ (Senior уровень)"

def test_middle_senior_level_allowance():
    """Тест: Вакансии Middle/Senior должны получать баллы и не блокироваться."""
    title = "Middle/Senior Python Developer"
    desc = "Ищем разработчика уровня middle или senior."
    
    is_senior = _match_any_re(title + desc, LEVEL_SENIOR)
    is_middle = _match_any_re(title + desc, LEVEL_MIDDLE)
    
    assert is_senior is True
    assert is_middle is True  # Упомянут middle
    
    res = analyze_vacancy(title, desc, skills="")
    # Так как упоминается middle, отсева по senior не должно быть.
    # Score зависит от других факторов, но точно не 0 по причине "Senior уровень".
    assert res["reason"] != "Отказ (Senior уровень)"


def test_senior_in_title_disqualified_even_if_description_mentions_middle():
    """Тест: Если в заголовке Senior (и нет вилки middle), вакансия должна отсекаться,
    даже если в описании упоминаются middle разработчики или стек AI."""
    title = "Senior Fullstack-разработчик (Python/FastAPI + AI)"
    desc = "Ищем Senior в команду. В подчинении будут middle-разработчики. Стек: Python, FastAPI, Docker."
    res = analyze_vacancy(title, desc, skills="")
    assert res["score"] == 0
    assert res["is_relevant"] is False
    assert res["reason"] == "Отказ (Senior уровень)"
    assert "senior_level" in res["red_flags"]

