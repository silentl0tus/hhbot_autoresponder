import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.ai.google_models import fetch_live_google_models
from app.ai.claude import claude_ai


@pytest.mark.asyncio
async def test_fetch_live_google_models_fallback():
    mock_html = """
    <html>
      <body>
        <a href="/gemini-api/docs/models/gemini-3.8-flash">Gemini 3.8 Flash</a>
        <a href="/gemini-api/docs/models/gemini-3.6-flash">Gemini 3.6 Flash</a>
        <a href="/gemini-api/docs/models/gemini-2.5-flash">Gemini 2.5 Flash</a>
      </body>
    </html>
    """
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = mock_html

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        
        models = await fetch_live_google_models()
        assert "gemini-3.8-flash" in models
        assert "gemini-3.6-flash" in models
        assert "gemini-2.5-flash" in models


@pytest.mark.asyncio
async def test_claude_ai_get_available_models():
    with patch("app.ai.claude.fetch_live_google_models", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = ["gemini-3.8-flash", "gemini-3.6-flash"]
        models = await claude_ai.get_available_models()
        assert models == ["gemini-3.8-flash", "gemini-3.6-flash"]
