from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.parsers.hh_oauth import HHOAuth


@pytest.mark.asyncio
async def test_get_token_lock_serializes_concurrent_refreshes():
    oauth = HHOAuth()

    # Cached token is expired
    expired_token = {
        "access_token": "expired_access",
        "refresh_token": "valid_refresh",
        "expires_at": time.time() - 100,
    }
    new_token = {
        "access_token": "new_access_token",
        "refresh_token": "new_refresh_token",
        "expires_at": time.time() + 3600,
    }

    refresh_call_count = 0

    async def mock_refresh(ref_tok):
        nonlocal refresh_call_count
        refresh_call_count += 1
        await asyncio.sleep(0.05)
        return new_token

    saved_tokens = []

    def mock_save(tok):
        saved_tokens.append(tok)
        # Update what load_token will return after saving
        expired_token.clear()
        expired_token.update(tok)

    with (
        patch("app.parsers.hh_oauth._load_token", side_effect=lambda: dict(expired_token)),
        patch("app.parsers.hh_oauth._save_token", side_effect=mock_save),
        patch.object(oauth, "_refresh", side_effect=mock_refresh) as p_refresh,
    ):
        results = await asyncio.gather(
            oauth.get_token(),
            oauth.get_token(),
            oauth.get_token(),
        )

        assert results == ["new_access_token", "new_access_token", "new_access_token"]
        assert refresh_call_count == 1
        assert p_refresh.call_count == 1


@pytest.mark.asyncio
async def test_get_token_returns_cached_token_when_valid():
    oauth = HHOAuth()
    valid_token = {
        "access_token": "fresh_access",
        "refresh_token": "valid_refresh",
        "expires_at": time.time() + 1000,
    }

    with (
        patch("app.parsers.hh_oauth._load_token", return_value=valid_token),
        patch.object(oauth, "_refresh", new=AsyncMock()) as p_refresh,
        patch.object(oauth, "_authorize", new=AsyncMock()) as p_auth,
    ):
        res = await oauth.get_token()
        assert res == "fresh_access"
        p_refresh.assert_not_called()
        p_auth.assert_not_called()


@pytest.mark.asyncio
async def test_get_token_force_refresh_reuses_already_updated_token():
    oauth = HHOAuth()
    updated_token = {
        "access_token": "already_refreshed_access",
        "refresh_token": "valid_refresh",
        "expires_at": time.time() + 1000,
    }

    with (
        patch("app.parsers.hh_oauth._load_token", return_value=updated_token),
        patch.object(oauth, "_refresh", new=AsyncMock()) as p_refresh,
        patch.object(oauth, "_authorize", new=AsyncMock()) as p_auth,
    ):
        # Caller reports 'stale_token' failed, but cache already holds 'already_refreshed_access'
        res = await oauth.get_token(force_refresh=True, failed_token="stale_token")
        assert res == "already_refreshed_access"
        p_refresh.assert_not_called()
        p_auth.assert_not_called()


@pytest.mark.asyncio
async def test_authorize_via_playwright_page_closed_in_finally():
    oauth = HHOAuth()
    mock_page = AsyncMock()
    mock_page.on = MagicMock()
    mock_page.goto.side_effect = RuntimeError("Navigation exploded")

    mock_bm = AsyncMock()
    mock_bm.new_page = AsyncMock(return_value=mock_page)

    with patch.dict("sys.modules", {"app.utils.browser": MagicMock(browser_manager=mock_bm)}):
        res = await oauth._authorize_via_playwright()
        assert res is None
        mock_page.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_invalidate_token_unlinks_file():
    oauth = HHOAuth()
    with patch("app.parsers.hh_oauth.TOKEN_FILE") as mock_file:
        await oauth.invalidate_token()
        mock_file.unlink.assert_called_once_with(missing_ok=True)
