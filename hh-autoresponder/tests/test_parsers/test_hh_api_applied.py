from unittest.mock import AsyncMock, patch

import pytest

from app.parsers.hh_api import extract_negotiation_vacancy_ids, hh_api_client

SAMPLE_NEGOTIATIONS_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div data-qa="negotiations-list">
        <!-- Real negotiation 1 -->
        <div data-qa="negotiations-item">
            <a href="/vacancy/100000001?hhtmFrom=negotiation_list">
                <span data-qa="negotiations-item-vacancy">Python Developer</span>
            </a>
            <div data-qa="negotiations-item-company">Company A</div>
        </div>

        <!-- Real negotiation 2 -->
        <div data-qa="negotiations-item">
            <a href="https://hh.ru/vacancy/100000002?hhtmFrom=negotiation_list">
                <span data-qa="negotiations-item-vacancy">QA Automation</span>
            </a>
            <div data-qa="negotiations-item-company">Company B</div>
        </div>
    </div>

    <!-- Recommendations widget (SHOULD BE IGNORED) -->
    <div data-qa="vacancy-serp__vacancy">
        <a href="https://hh.ru/vacancy/999999999?hhtmFromLabel=suitable_vacancies&amp;hhtmFrom=negotiation_list">
            <span>Recommended Senior QA</span>
        </a>
    </div>

    <!-- Another recommendation card (SHOULD BE IGNORED) -->
    <div class="recommendations">
        <a href="/vacancy/888888888?hhtmFromLabel=suitable_vacancies">
            <span>Recommended ML Engineer</span>
        </a>
    </div>
</body>
</html>
"""


def test_extract_negotiation_vacancy_ids_filters_recommendations():
    ids = extract_negotiation_vacancy_ids(SAMPLE_NEGOTIATIONS_HTML)
    # Only real negotiations must be collected
    assert ids == {"100000001", "100000002"}
    assert "999999999" not in ids
    assert "888888888" not in ids


def test_extract_negotiation_vacancy_ids_regex_fallback():
    # Test regex fallback without BeautifulSoup-style data-qa wrappers
    raw_html = """
    <div>
        <a href="/vacancy/200000001?hhtmFrom=negotiation_list">Negotiation 1</a>
        <a href="https://hh.ru/vacancy/200000002?hhtmFrom=negotiation_list">Negotiation 2</a>
        <a href="https://hh.ru/vacancy/300000001?hhtmFromLabel=suitable_vacancies&hhtmFrom=negotiation_list">Rec</a>
        <a href="/vacancy/300000002?hhtmFrom=recommendations">Rec 2</a>
    </div>
    """
    with patch("app.parsers.hh_api.BeautifulSoup", side_effect=Exception("BS4 simulated failure")):
        ids = extract_negotiation_vacancy_ids(raw_html)
        assert ids == {"200000001", "200000002"}
        assert "300000001" not in ids
        assert "300000002" not in ids


@pytest.mark.asyncio
async def test_fetch_applied_vacancy_ids_pagination(monkeypatch):
    monkeypatch.setattr(hh_api_client, "reload_cookies", lambda: True)
    hh_api_client._cookies = {"_xsrf": "test_xsrf"}
    hh_api_client._xsrf = "test_xsrf"

    page_0_html = (
        """
    <div>
    """
        + "".join(
            [
                f'<div data-qa="negotiations-item"><a href="/vacancy/10000{i:03d}?hhtmFrom=negotiation_list"></a></div>'
                for i in range(20)
            ]
        )
        + """
    </div>
    """
    )

    page_1_html = (
        """
    <div>
    """
        + "".join(
            [
                f'<div data-qa="negotiations-item"><a href="/vacancy/20000{i:03d}?hhtmFrom=negotiation_list"></a></div>'
                for i in range(5)
            ]
        )
        + """
    </div>
    """
    )

    async def mock_get(url, params=None, follow_redirects=True):
        page = params.get("page", 0) if params else 0
        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        if page == 0:
            mock_resp.text = page_0_html
        elif page == 1:
            mock_resp.text = page_1_html
        else:
            mock_resp.text = ""
        return mock_resp

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        result_ids = await hh_api_client.fetch_applied_vacancy_ids()
        # 20 from page 0 + 5 from page 1 = 25 total
        assert len(result_ids) == 25
        assert "10000000" in result_ids
        assert "20000004" in result_ids
