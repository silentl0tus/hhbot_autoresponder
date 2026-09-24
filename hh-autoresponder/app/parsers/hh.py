import re

import httpx
import structlog
from bs4 import BeautifulSoup

from app.parsers.base import ParsedVacancy
from app.utils.rate_limiter import hh_limiter

log = structlog.get_logger()

HH_BASE = "https://hh.ru"
HH_SEARCH = "https://hh.ru/search/vacancy"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

EXPERIENCE_MAP = {
    "no": "noExperience",
    "1-3": "between1And3",
    "3-6": "between3And6",
    "6+": "moreThan6",
}


class HHParser:
    platform = "hh"

    async def login(self) -> bool:
        return True

    async def search_vacancies(self, query: str, **filters) -> list[ParsedVacancy]:
        params = {
            "text": query,
            "search_field": "name",
            "enable_snippets": "true",
            "no_magic": "true",
        }

        if filters.get("remote", True):
            params["schedule"] = "remote"

        exp = filters.get("experience")
        if exp and exp in EXPERIENCE_MAP:
            params["experience"] = EXPERIENCE_MAP[exp]

        pages = int(filters.get("pages", 3))  # берём несколько страниц для большего пула
        vacancies = []
        for page in range(pages):
            params["page"] = page
            try:
                async with hh_limiter:
                    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                        resp = await client.get(HH_SEARCH, params=params)
                        resp.raise_for_status()

                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.select('[data-qa="vacancy-serp__vacancy"]')
                log.info("hh_search_results", query=query, page=page, count=len(cards))
                if not cards:
                    break  # страницы кончились

                for card in cards[:50]:
                    vacancy = self._parse_card(card)
                    if vacancy:
                        vacancies.append(vacancy)
            except Exception as e:
                log.error("hh_search_error", query=query, page=page, error=str(e))
                break

        return vacancies

    def _parse_card(self, card) -> ParsedVacancy | None:
        title_el = card.select_one('[data-qa="serp-item__title"]')
        if not title_el:
            return None

        title = title_el.get_text(strip=True)
        url = title_el.get("href", "")

        ext_id_match = re.search(r"/vacancy/(\d+)", url)
        ext_id = ext_id_match.group(1) if ext_id_match else ""

        company_el = card.select_one('[data-qa="vacancy-serp__vacancy-employer"]')
        company_name = company_el.get_text(strip=True) if company_el else ""
        company_url = ""
        if company_el:
            link = company_el.select_one("a")
            if link:
                company_url = link.get("href", "")

        salary_from, salary_to, currency = None, None, ""
        salary_el = card.select_one('[data-qa="vacancy-serp__vacancy-compensation"]')
        if salary_el:
            salary_from, salary_to, currency = self._parse_salary(salary_el.get_text())

        loc_el = card.select_one('[data-qa="vacancy-serp__vacancy-address"]')
        location = loc_el.get_text(strip=True) if loc_el else ""
        is_remote = "удалённ" in location.lower() or "remote" in location.lower()

        clean_url = url.split("?")[0] if url else ""

        return ParsedVacancy(
            platform="hh",
            external_id=ext_id,
            url=clean_url,
            title=title,
            company_name=company_name,
            company_url=company_url,
            salary_from=salary_from,
            salary_to=salary_to,
            salary_currency=currency,
            location=location,
            is_remote=is_remote,
        )

    def _parse_salary(self, text: str) -> tuple[int | None, int | None, str]:
        text = text.replace("\xa0", "").replace(" ", "")
        currency = ""
        if "₽" in text or "руб" in text:
            currency = "RUB"
        elif "$" in text or "USD" in text:
            currency = "USD"
        elif "€" in text or "EUR" in text:
            currency = "EUR"

        numbers = [int(x) for x in re.findall(r"\d+", text)]
        if "от" in text and "до" in text and len(numbers) >= 2:
            return numbers[0], numbers[1], currency
        elif "от" in text and numbers:
            return numbers[0], None, currency
        elif "до" in text and numbers:
            return None, numbers[0], currency
        elif numbers:
            return numbers[0], numbers[-1] if len(numbers) > 1 else None, currency
        return None, None, currency

    async def get_vacancy_details(self, url: str) -> ParsedVacancy | None:
        import re
        import html
        m = re.search(r"/vacancy/(\d+)", url)
        vacancy_id = m.group(1) if m else url.rstrip("/").split("/")[-1].split("?")[0]
        
        # 1. Сначала пробуем быстрый и надежный официальный API hh.ru
        if vacancy_id.isdigit():
            try:
                from app.parsers.hh_oauth import hh_oauth, UA
                token = await hh_oauth.get_token()
                headers = {"User-Agent": UA}
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                async with httpx.AsyncClient(headers=headers, timeout=20) as client:
                    resp = await client.get(f"https://api.hh.ru/vacancies/{vacancy_id}")
                    if resp.status_code == 200:
                        data = resp.json()

                        # Архивная вакансия — сразу сообщаем об этом, не тратим токены на отклик.
                        is_archived = bool(data.get("archived", False))
                        if is_archived:
                            log.info("hh_vacancy_archived", vacancy_id=vacancy_id, url=url)

                        raw_desc = data.get("description", "")
                        clean_desc = html.unescape(re.sub(r"<[^>]+>", " ", raw_desc)).strip()
                        skills = [s.get("name", "") for s in data.get("key_skills", []) if s.get("name")]
                        emp = data.get("employer", {}) or {}
                        company_name = emp.get("name", "")
                        
                        return ParsedVacancy(
                            platform="hh",
                            external_id=vacancy_id,
                            url=url,
                            title=data.get("name", ""),
                            description=clean_desc,
                            company_name=company_name,
                            is_archived=is_archived,
                            experience=(data.get("experience", {}) or {}).get("name", ""),
                            employment_type=(data.get("employment", {}) or {}).get("name", ""),
                            skills=skills,
                        )
            except Exception as e:
                log.warning("hh_api_vacancy_details_failed", error=str(e))

        # 2. Фолбэк на прямой парсинг веб-страницы
        try:
            async with hh_limiter:
                async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")

            title_el = soup.select_one('[data-qa="vacancy-title"]')
            title = title_el.get_text(strip=True) if title_el else ""

            desc_el = soup.select_one('[data-qa="vacancy-description"]')
            description = desc_el.get_text(separator="\n", strip=True) if desc_el else ""

            skills = []
            for tag in soup.select('[data-qa="bloko-tag__text"], [data-qa="skills-element"]'):
                skills.append(tag.get_text(strip=True))

            exp_el = soup.select_one('[data-qa="vacancy-experience"]')
            experience = exp_el.get_text(strip=True) if exp_el else ""

            emp_el = soup.select_one('[data-qa="vacancy-view-employment-mode"]')
            employment = emp_el.get_text(strip=True) if emp_el else ""

            company_el = soup.select_one('[data-qa="vacancy-company-name"]')
            company = company_el.get_text(strip=True) if company_el else ""

            return ParsedVacancy(
                platform="hh",
                external_id=vacancy_id,
                url=url,
                title=title,
                description=description,
                company_name=company,
                experience=experience,
                employment_type=employment,
                skills=skills,
            )

        except Exception as e:
            log.error("hh_details_error", url=url, error=str(e))
            return None

    async def apply_to_vacancy(self, url: str, cover_letter: str, screenshot_name: str | None = None) -> bool | str:
        """Apply via Playwright if available, otherwise skip."""
        pw = self._get_playwright()
        if pw:
            return await pw.apply_to_vacancy(url, cover_letter, screenshot_name=screenshot_name)
        log.warning("hh_apply_not_supported", url=url, reason="playwright not available")
        return False

    async def check_messages(self) -> list[dict]:
        """Check messages via Playwright if available."""
        pw = self._get_playwright()
        if pw:
            return await pw.check_messages()
        log.info("hh_messages_skip", reason="playwright not available")
        return []

    async def check_negotiations(self) -> list[dict]:
        """Check negotiations status via Playwright."""
        pw = self._get_playwright()
        if pw:
            return await pw.check_negotiations_status()
        return []

    async def login(self) -> bool:
        """Always returns True — search works via HTML scraping without login.
        Playwright login is only needed for apply/messages and is called there."""
        return True

    def _get_playwright(self):
        """Get HHPlaywright instance if available."""
        try:
            from app.parsers.hh_playwright import hh_playwright
            return hh_playwright
        except ImportError:
            return None
