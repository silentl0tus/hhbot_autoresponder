import pytest
from app.ai.claude import clean_cover_letter

def test_clean_cover_letter_removes_ai_score():
    text = "Я опытный разработчик.\nИИ-балл: 2/10"
    assert clean_cover_letter(text) == "Я опытный разработчик."
    
    text2 = "Текст отклика.\n\nии-балл: 1"
    assert clean_cover_letter(text2) == "Текст отклика."

def test_clean_cover_letter_removes_placeholders():
    text = "Я опытный разработчик.\nС уважением, [Вставьте Ваше имя]"
    assert clean_cover_letter(text) == "Я опытный разработчик."
    
    text2 = "Текст отклика.\nС уважением, Имя"
    assert clean_cover_letter(text2) == "Текст отклика."
