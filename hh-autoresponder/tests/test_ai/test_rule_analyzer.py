import pytest
from app.ai.rule_analyzer import _match_any_re, LEVEL_SENIOR, LEVEL_MIDDLE, LEVEL_SENIOR_TITLE_EXTRA
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
    assert "Senior уровень" in res["reason"]

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
    assert "Senior уровень" not in res["reason"]


def test_senior_in_title_disqualified_even_if_description_mentions_middle():
    """Тест: Если в заголовке Senior (и нет вилки middle), вакансия должна отсекаться,
    даже если в описании упоминаются middle разработчики или стек AI."""
    title = "Senior Fullstack-разработчик (Python/FastAPI + AI)"
    desc = "Ищем Senior в команду. В подчинении будут middle-разработчики. Стек: Python, FastAPI, Docker."
    res = analyze_vacancy(title, desc, skills="")
    assert res["score"] == 0
    assert res["is_relevant"] is False
    assert "Senior уровень" in res["reason"]
    assert "senior_level" in res["red_flags"]


def test_veduschy_title_disqualified(mocker):
    """Тест: 'ведущий' в заголовке = Senior уровень, должен отсекаться."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["маркетолог", "маркетинг", "performance"],
                 excluded_keywords=[], excluded_companies=[])
    title = "Ведущий маркетолог перформанс"
    res = analyze_vacancy(title, "", skills="")
    assert res["score"] == 0
    assert "senior_level" in res["red_flags"]


def test_expert_title_disqualified(mocker):
    """Тест: 'expert' в заголовке = Senior уровень, должен отсекаться."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["маркетолог", "маркетинг", "performance"],
                 excluded_keywords=[], excluded_companies=[])
    title = "Маркетолог-эксперт / Performance Expert"
    res = analyze_vacancy(title, "", skills="")
    assert res["score"] == 0
    assert "senior_level" in res["red_flags"]


def test_team_lead_title_disqualified(mocker):
    """Тест: 'team lead' в заголовке = Senior уровень, должен отсекаться."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["маркетолог", "маркетинг", "performance"],
                 excluded_keywords=[], excluded_companies=[])
    title = "Маркетолог (Team Lead)"
    res = analyze_vacancy(title, "", skills="")
    assert res["score"] == 0
    assert "senior_level" in res["red_flags"]


def test_reason_includes_matched_pattern(mocker):
    """Тест: Причина отсева содержит название паттерна для диагностики."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["маркетолог", "performance"],
                 excluded_keywords=[], excluded_companies=[])
    title = "Senior маркетолог"
    res = analyze_vacancy(title, "", skills="")
    assert res["score"] == 0
    assert "паттерн" in res["reason"]


def test_base_score_is_15_without_stack(mocker):
    """Тест: Если заголовок совпадает, но нет совпадений по стеку, базовый балл равен 15."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["python"],
                 negative_keywords=[],
                 stack_keywords=["fastapi", "docker"])
    title = "Python разработчик"
    desc = "Пишем на неизвестном фреймворке."
    res = analyze_vacancy(title, desc, skills="")
    
    assert res["score"] == 15
    assert res["stack_match"] == 0


def test_soft_negative_penalty(mocker):
    """Тест: Если есть и стоп-слово, и целевое слово, дается штраф -10, но не дисквалификация (score > 0)."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["python"],
                 negative_keywords=["стажер"],
                 stack_keywords=["fastapi"])
    # Включаем и целевое слово и негативное в заголовок
    title = "Стажер Python"
    desc = "Опыт не важен. Стек: fastapi."
    res = analyze_vacancy(title, desc, skills="")
    
    # Base = 15, Penalty = -10, Stack = +5. Total = 10.
    assert res["score"] == 10
    assert "negative_keyword_soft" in res["red_flags"]
    assert res["is_relevant"] is False


def test_stack_keywords_score(mocker):
    """Тест: Каждое найденное слово из стека прибавляет баллы."""
    mocker.patch("app.ai.rule_analyzer.settings",
                 target_keywords=["python"],
                 negative_keywords=[],
                 stack_keywords=["fastapi", "docker", "postgresql", "redis"])
    title = "Python developer"
    desc = "Требуется опыт с FastAPI, Docker. Знание postgresql будет плюсом."
    res = analyze_vacancy(title, desc, skills="")
    
    # 3 stack matches: fastapi, docker, postgresql (each gives 5, total 15)
    # Base: 15. Total: 30.
    assert res["score"] == 30
    assert res["stack_match"] > 0

