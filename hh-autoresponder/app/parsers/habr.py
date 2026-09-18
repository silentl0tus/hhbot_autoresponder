import re
import math
from typing import Optional

import httpx
import structlog
from bs4 import BeautifulSoup

from app.parsers.base import ParsedVacancy, BaseParser

log = structlog.get_logger()

HABR_BASE = "https://career.habr.com"
HABR_SEARCH = "https://career.habr.com/vacancies"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8",
}

class HabrParser(BaseParser):
    platform = "habr"

    async def login(self) -> bool:
        return True

    async def search_vacancies(self, query: str, **filters) -> list[ParsedVacancy]:
        params = {
            "q": query,
            "type": "all",
        }
        
        vacancies = []
        pages = int(filters.get("pages", 3))
        
        for page in range(1, pages + 1):
            params["page"] = page
            try:
                async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30) as client:
                    resp = await client.get(HABR_SEARCH, params=params)
                    resp.raise_for_status()
                    
                soup = BeautifulSoup(resp.text, "lxml")
                cards = soup.find_all("div", class_="vacancy-card")
                if not cards:
                    break
                    
                for card in cards:
                    try:
                        title_el = card.find("a", class_="vacancy-card__title-link")
                        company_el = card.find("a", class_="link-comp")
                        salary_el = card.find("div", class_="vacancy-card__salary")
                        skills_els = card.find_all("a", class_="link-comp link-comp--appearance-dark")
                        
                        if not title_el:
                            continue
                            
                        title = title_el.text.strip()
                        href = title_el.get("href", "")
                        ext_id = href.split("/")[-1] if href else ""
                        url = HABR_BASE + href if href else ""
                        company = company_el.text.strip() if company_el else ""
                        
                        # habr salary parsing is messy ("от 100 000 ₽", "до 200 000 ₽", etc.)
                        salary_text = salary_el.text.strip() if salary_el else ""
                        salary_from, salary_to, currency = None, None, "RUR"
                        if "₽" in salary_text:
                            currency = "RUR"
                        elif "$" in salary_text:
                            currency = "USD"
                        elif "€" in salary_text:
                            currency = "EUR"
                            
                        nums = [int(n.replace(" ", "")) for n in re.findall(r"\d{1,3}(?: \d{3})+", salary_text)]
                        if "от" in salary_text.lower() and len(nums) == 1:
                            salary_from = nums[0]
                        elif "до" in salary_text.lower() and len(nums) == 1:
                            salary_to = nums[0]
                        elif len(nums) >= 2:
                            salary_from = nums[0]
                            salary_to = nums[1]
                            
                        skills = [s.text.strip() for s in skills_els]
                        
                        vac = ParsedVacancy(
                            platform=HabrParser.platform,
                            external_id=ext_id,
                            url=url,
                            title=title,
                            company_name=company,
                            salary_from=salary_from,
                            salary_to=salary_to,
                            salary_currency=currency,
                            skills=skills,
                        )
                        vacancies.append(vac)
                    except Exception as e:
                        log.debug("habr_card_parse_error", error=str(e))
                        
            except Exception as e:
                log.error("habr_search_error", error=str(e), page=page)
                break
                
        return vacancies

    async def get_vacancy_details(self, url: str) -> Optional[ParsedVacancy]:
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
            
            soup = BeautifulSoup(resp.text, "lxml")
            desc_el = soup.find("div", class_="vacancy-description__text")
            desc_text = desc_el.text.strip() if desc_el else ""
            
            # Update title, company if needed but usually we just need description
            vac = ParsedVacancy(
                platform=HabrParser.platform,
                url=url,
                description=desc_text,
            )
            return vac
        except Exception as e:
            log.error("habr_details_error", error=str(e), url=url)
            return None

    async def check_messages(self) -> list[dict]:
        return []

    async def apply_to_vacancy(self, url: str, cover_letter: str, screenshot_name: str | None = None) -> bool:
        """Apply via Playwright if available, otherwise skip."""
        try:
            from app.parsers.habr_playwright import habr_playwright
            return await habr_playwright.apply_to_vacancy(url, cover_letter)
        except ImportError:
            log.warning("habr_apply_not_supported", url=url, reason="playwright not available")
            return False
