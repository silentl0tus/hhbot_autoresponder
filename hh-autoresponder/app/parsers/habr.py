import re
import typing
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

                        location = ""
                        is_remote = False
                        experience = ""
                        meta_el = card.find("div", class_="vacancy-card__meta")
                        if meta_el:
                            chips = meta_el.find_all("div", class_="basic-chip")
                            for chip in chips:
                                text_el = chip.find("div", class_="chip-with-icon__text")
                                chip_text = text_el.get_text(strip=True) if text_el else ""
                                icon = chip.find("use")
                                icon_href = (icon.get("xlink:href", "") or icon.get("href", "")) if icon else ""
                                if "placemark" in icon_href:
                                    location = chip_text
                                elif "format" in icon_href:
                                    if any(r in chip_text.lower() for r in ("удалён", "удален", "remote")):
                                        is_remote = True
                                    location = f"{location}, {chip_text}".strip(", ") if location else chip_text
                                elif "grade" in icon_href:
                                    experience = chip_text

                        card_text = card.get_text().lower()
                        if any(
                            r in card_text
                            for r in ("можно удалённо", "можно удаленно", "удаленная работа", "удалённая работа")
                        ):
                            is_remote = True

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
                            location=location,
                            is_remote=is_remote,
                            experience=experience,
                        )
                        vacancies.append(vac)
                    except Exception as e:
                        log.debug("habr_card_parse_error", error=str(e))

            except Exception as e:
                log.error("habr_search_error", error=str(e), page=page)
                break

        return vacancies

    async def get_vacancy_details(self, url: str) -> Optional[ParsedVacancy]:
        ext_id = url.rstrip("/").split("/")[-1].split("?")[0]
        try:
            async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code == 404:
                    log.info("habr_vacancy_404_archived", url=url, external_id=ext_id)
                    return ParsedVacancy(
                        platform=HabrParser.platform,
                        external_id=ext_id,
                        url=url,
                        is_archived=True,
                    )
                if resp.status_code != 200:
                    return None

            soup = BeautifulSoup(resp.text, "lxml")

            is_archived = False
            raw_text = soup.get_text()
            if any(
                marker in raw_text
                for marker in ("Ошибка 404", "закрыла свой профиль", "Вакансия в архиве", "вакансия закрыта")
            ):
                is_archived = True
            elif soup.select_one(".vacancy-archive, .archive-banner, [data-qa='vacancy-archive-header']"):
                is_archived = True

            is_archived = False
            raw_text = soup.get_text()
            if any(
                marker in raw_text
                for marker in ("Ошибка 404", "закрыла свой профиль", "Вакансия в архиве", "вакансия закрыта")
            ):
                is_archived = True
            elif soup.select_one(".vacancy-archive, .archive-banner, [data-qa='vacancy-archive-header']"):
                is_archived = True

            desc_el = soup.find("div", class_="vacancy-description__text")
            desc_text = desc_el.text.strip() if desc_el else ""

            loc = ""
            remote = False
            meta_div = soup.find("div", class_="vacancy-meta") or soup.find("div", class_="vacancy-header")
            if meta_div:
                chips = meta_div.find_all("div", class_="basic-chip")
                for chip in chips:
                    text_el = chip.find("div", class_="chip-with-icon__text")
                    chip_text = text_el.get_text(strip=True) if text_el else ""
                    icon = chip.find("use")
                    icon_href = (icon.get("xlink:href", "") or icon.get("href", "")) if icon else ""
                    if "placemark" in icon_href:
                        loc = chip_text
                    elif "format" in icon_href:
                        if any(r in chip_text.lower() for r in ("удалён", "удален", "remote")):
                            remote = True
                        loc = f"{loc}, {chip_text}".strip(", ") if loc else chip_text

            vac = ParsedVacancy(
                platform=HabrParser.platform,
                external_id=ext_id,
                url=url,
                description=desc_text,
                location=loc,
                is_remote=remote,
                is_archived=is_archived,
            )
            return vac
        except Exception as e:
            log.error("habr_details_error", error=str(e), url=url)
            return None

    async def check_messages(self) -> list[dict]:
        try:
            from app.parsers.habr_playwright import habr_playwright

            return await habr_playwright.check_messages()
        except ImportError:
            log.warning("habr_check_msgs_not_supported", reason="playwright not available")
            return []

    async def apply_to_vacancy(
        self, url: str, cover_letter: str | typing.Callable, screenshot_name: str | None = None
    ) -> bool | str:
        """Apply via Playwright if available, otherwise skip."""
        try:
            from app.parsers.habr_playwright import habr_playwright

            return await habr_playwright.apply_to_vacancy(url, cover_letter)
        except ImportError:
            log.warning("habr_apply_not_supported", url=url, reason="playwright not available")
            return False
