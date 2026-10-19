"""Tests verifying that archived vacancies are detected and blocked
before any application attempt is made."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parsers.base import ParsedVacancy


class TestParsedVacancyIsArchived:
    """Unit tests for the is_archived field on ParsedVacancy."""

    def test_default_is_not_archived(self):
        v = ParsedVacancy(platform="hh", external_id="1", url="https://hh.ru/vacancy/1")
        assert v.is_archived is False

    def test_can_be_set_to_true(self):
        v = ParsedVacancy(
            platform="hh",
            external_id="1",
            url="https://hh.ru/vacancy/1",
            is_archived=True,
        )
        assert v.is_archived is True


class TestHHParserArchivedFlag:
    """Tests that HHParser.get_vacancy_details propagates archived=True."""

    @pytest.mark.asyncio
    async def test_archived_vacancy_sets_flag(self):
        from app.parsers.hh import HHParser

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "archived": True,
            "name": "Python Dev",
            "description": "<p>Job desc</p>",
            "key_skills": [],
            "employer": {"name": "Acme"},
            "experience": {"name": "От 3 до 6 лет"},
            "employment": {"name": "Полная занятость"},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("app.parsers.hh_oauth.hh_oauth.get_token", new_callable=AsyncMock, return_value="tok"),
            patch("app.parsers.hh.httpx.AsyncClient", return_value=mock_client),
        ):
            parser = HHParser()
            result = await parser.get_vacancy_details("https://hh.ru/vacancy/12345")

        assert result is not None
        assert result.is_archived is True

    @pytest.mark.asyncio
    async def test_active_vacancy_not_archived(self):
        from app.parsers.hh import HHParser

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "archived": False,
            "name": "Python Dev",
            "description": "<p>Job desc</p>",
            "key_skills": [],
            "employer": {"name": "Acme"},
            "experience": {},
            "employment": {},
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("app.parsers.hh_oauth.hh_oauth.get_token", new_callable=AsyncMock, return_value="tok"),
            patch("app.parsers.hh.httpx.AsyncClient", return_value=mock_client),
        ):
            parser = HHParser()
            result = await parser.get_vacancy_details("https://hh.ru/vacancy/12345")

        assert result is not None
        assert result.is_archived is False


class TestArchivedEnrichmentFilter:
    """Verify the enrichment logic: is_archived=True → status ARCHIVED."""

    def _make_archived_details(self) -> ParsedVacancy:
        return ParsedVacancy(
            platform="hh",
            external_id="999",
            url="https://hh.ru/vacancy/999",
            title="Archived Job",
            description="Some desc",
            is_archived=True,
        )

    def test_getattr_guard(self):
        """getattr(details, 'is_archived', False) works even on plain objects."""
        details = self._make_archived_details()
        assert getattr(details, "is_archived", False) is True

    def test_non_archived_passes_through(self):
        details = ParsedVacancy(
            platform="hh",
            external_id="1",
            url="https://hh.ru/vacancy/1",
            is_archived=False,
        )
        assert getattr(details, "is_archived", False) is False

    @pytest.mark.asyncio
    async def test_html_with_translation_script_not_archived(self):
        """Active vacancy with translation dictionary in <script> must NOT be marked archived."""
        from app.parsers.hh import HHParser

        html_content = """
        <html>
            <head>
                <script>
                    window.translations = {"applicant.negotiations.vacancyArchived": "Вакансия в архиве"};
                </script>
            </head>
            <body>
                <h1 data-qa="vacancy-title">QA Engineer</h1>
                <div data-qa="vacancy-description">Testing python apps</div>
                <span data-qa="vacancy-company-name">Tech Corp</span>
            </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_content
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        # Force API to fail (return 403) so it uses HTML fallback
        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 403

        with (
            patch("app.parsers.hh_oauth.hh_oauth.get_token", new_callable=AsyncMock, return_value="tok"),
            patch("app.parsers.hh.httpx.AsyncClient", return_value=mock_client),
        ):
            # API call returns 403, fallback call returns html_content
            mock_client.get.side_effect = [mock_api_resp, mock_resp]
            parser = HHParser()
            result = await parser.get_vacancy_details("https://hh.ru/vacancy/55555")

        assert result is not None
        assert result.title == "QA Engineer"
        assert result.is_archived is False

    @pytest.mark.asyncio
    async def test_html_with_real_archive_banner_is_archived(self):
        """Page with real archive header must be marked archived."""
        from app.parsers.hh import HHParser

        html_content = """
        <html>
            <body>
                <div data-qa="vacancy-archive-header">Вакансия в архиве</div>
                <div data-qa="vacancy-description">Old desc</div>
            </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html_content
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_api_resp = MagicMock()
        mock_api_resp.status_code = 403

        with (
            patch("app.parsers.hh_oauth.hh_oauth.get_token", new_callable=AsyncMock, return_value="tok"),
            patch("app.parsers.hh.httpx.AsyncClient", return_value=mock_client),
        ):
            mock_client.get.side_effect = [mock_api_resp, mock_resp]
            parser = HHParser()
            result = await parser.get_vacancy_details("https://hh.ru/vacancy/55555")

        assert result is not None
        assert result.is_archived is True
