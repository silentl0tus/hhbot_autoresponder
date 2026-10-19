from app.ai.claude import clean_cover_letter


def test_clean_cover_letter_removes_ai_score():
    text = "Я опытный разработчик.\nИИ-балл: 2/10"
    assert clean_cover_letter(text) == "Я опытный разработчик."

    text2 = "Текст отклика.\n\nии-балл: 1"
    assert clean_cover_letter(text2) == "Текст отклика."


def test_clean_cover_letter_removes_markdown_bolding_and_headers():
    raw = (
        "7 лет в интеграции комплексов.\n\n"
        "**Что умею конкретно:**\n"
        "- **СЗИ и Linux:** Прошивал ARM-устройства.\n"
        "- **Автоматизация:** Пишу на Python.\n\n"
        "Готов обсудить на интервью."
    )
    cleaned = clean_cover_letter(raw)
    assert "**" not in cleaned
    assert "Что умею конкретно:" not in cleaned
    assert "- СЗИ и Linux: Прошивал ARM-устройства." in cleaned
    assert "- Автоматизация: Пишу на Python." in cleaned
