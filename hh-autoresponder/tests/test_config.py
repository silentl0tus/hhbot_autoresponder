import pytest

from app.config import Settings


def test_candidate_profile_defaults():
    cfg = Settings()
    assert cfg.english_level in ("A2", "B1", "B2", "C1")
    assert isinstance(cfg.relocation_ready, bool)
    assert isinstance(cfg.business_trips_ready, bool)
    assert isinstance(cfg.notice_period, str)


@pytest.mark.parametrize(
    "input_val,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("да", True),
        ("ДА", True),
        ("готов", True),
        ("согласен", True),
        (True, True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("нет", False),
        ("НЕ ГОТОВ", False),
        ("не согласен", False),
        (False, False),
    ],
)
def test_candidate_bool_flags_parsing(input_val, expected):
    cfg = Settings(relocation_ready=input_val, business_trips_ready=input_val)
    assert cfg.relocation_ready is expected
    assert cfg.business_trips_ready is expected


def test_candidate_resume_text(tmp_path):
    resume_file = tmp_path / "resume.txt"
    resume_file.write_text("Тестовое резюме кандидата в кодировке UTF-8: привет мир!", encoding="utf-8")
    cfg = Settings(resume_text_path=str(resume_file))
    assert cfg.resume_text == "Тестовое резюме кандидата в кодировке UTF-8: привет мир!"
