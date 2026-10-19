from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.parsers.hh_playwright import HHPlaywright


@pytest.fixture
def parser():
    return HHPlaywright()


@pytest.mark.asyncio
async def test_capture_captcha_screenshot_ignores_avatar(parser):
    page = MagicMock()

    # Image that looks like an avatar
    avatar_img = MagicMock()
    avatar_img.is_visible = AsyncMock(return_value=True)
    avatar_img.get_attribute = AsyncMock(return_value="https://hhcdn.ru/user_photo/avatar_123.jpg")
    avatar_img.bounding_box = AsyncMock(return_value={"width": 40, "height": 40})
    avatar_img.screenshot = AsyncMock(return_value=b"avatar_bytes")

    # Real captcha image
    captcha_img = MagicMock()
    captcha_img.is_visible = AsyncMock(return_value=True)
    captcha_img.get_attribute = AsyncMock(return_value="https://hh.ru/captcha?id=999")
    captcha_img.bounding_box = AsyncMock(return_value={"width": 180, "height": 60})
    captcha_img.screenshot = AsyncMock(return_value=b"captcha_bytes")

    async def mock_query_selector_all(sel):
        if "captcha" in sel:
            return [avatar_img, captcha_img]
        return []

    page.query_selector_all = mock_query_selector_all
    page.query_selector = AsyncMock(return_value=None)
    page.screenshot = AsyncMock(return_value=b"page_bytes")

    result = await parser._capture_captcha_screenshot(page)
    assert result == b"captcha_bytes"
    captcha_img.screenshot.assert_awaited_once()
    avatar_img.screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_captcha_screenshot_fallback_to_modal(parser):
    page = MagicMock()
    page.query_selector_all = AsyncMock(return_value=[])

    modal = MagicMock()
    modal.is_visible = AsyncMock(return_value=True)
    modal.screenshot = AsyncMock(return_value=b"modal_bytes")

    async def mock_query_selector(sel):
        if ".bloko-modal" in sel or "role" in sel:
            return modal
        return None

    page.query_selector = mock_query_selector
    page.screenshot = AsyncMock(return_value=b"page_bytes")

    result = await parser._capture_captcha_screenshot(page)
    assert result == b"modal_bytes"
    modal.screenshot.assert_awaited_once()
    page.screenshot.assert_not_awaited()


@pytest.mark.asyncio
async def test_capture_captcha_screenshot_fallback_to_page(parser):
    page = MagicMock()
    page.query_selector_all = AsyncMock(return_value=[])
    page.query_selector = AsyncMock(return_value=None)
    page.screenshot = AsyncMock(return_value=b"full_page_bytes")

    result = await parser._capture_captcha_screenshot(page)
    assert result == b"full_page_bytes"
    page.screenshot.assert_awaited_once()
