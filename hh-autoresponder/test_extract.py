import re

VACANCY_ID_RE = re.compile(r"(?:vacancy(?:id=|/)|vacancies/)(\d+)", re.I)


def extract_vacancy_id(url: str = "", explicit: str | None = None) -> str:
    if explicit:
        return str(explicit).strip()
    m = VACANCY_ID_RE.search(url or "")
    return m.group(1) if m else ""


print(extract_vacancy_id("https://hh.ru/vacancy/135243260?from=search_task"))
print(extract_vacancy_id("https://hh.ru/vacancy/123456"))
