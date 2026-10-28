import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.services.tunnel import TunnelManager


def test_tunnel_manager_get_local_url():
    mgr = TunnelManager()
    with patch.object(settings, "dashboard_port", 8080), patch.object(settings, "dashboard_host", "127.0.0.1"):
        assert mgr.get_local_url() == "http://localhost:8080"


@pytest.mark.asyncio
async def test_tunnel_manager_static_public_url():
    mgr = TunnelManager()
    with patch.object(settings, "dashboard_public_url", "https://my-dashboard.example.com"):
        url = await mgr.get_or_start_tunnel()
        assert url == "https://my-dashboard.example.com"


@pytest.mark.asyncio
async def test_tunnel_manager_starts_cloudflared(monkeypatch):
    mgr = TunnelManager()
    monkeypatch.setattr(mgr, "_find_or_download_binary", AsyncMock(return_value="/bin/cloudflared"))
    monkeypatch.setattr(settings, "dashboard_public_url", "")
    monkeypatch.setattr(settings, "dashboard_auto_tunnel", True)

    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.terminate = MagicMock()

    async def mock_readline_stderr():
        await asyncio.sleep(0.01)
        return b"INF https://random-test-subdomain.trycloudflare.com is ready\n"

    async def mock_readline_stdout():
        await asyncio.sleep(0.05)
        return b""

    mock_stderr = AsyncMock()
    mock_stderr.readline = mock_readline_stderr
    mock_proc.stderr = mock_stderr

    mock_stdout = AsyncMock()
    mock_stdout.readline = mock_readline_stdout
    mock_proc.stdout = mock_stdout

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        url = await mgr.get_or_start_tunnel()
        assert url == "https://random-test-subdomain.trycloudflare.com"
        assert mgr.public_url == "https://random-test-subdomain.trycloudflare.com"

        mgr.stop()
        mock_proc.terminate.assert_called_once()
        assert mgr.public_url is None
