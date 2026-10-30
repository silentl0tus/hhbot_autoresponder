"""
Service to manage Cloudflare Tunnel for the Web Dashboard.
Provides a public HTTPS URL without requiring port forwarding,
external IP, or occupying the Android VPN slot.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import platform
import re
import shutil
from pathlib import Path

import httpx
import structlog

from app.config import settings

log = structlog.get_logger()

BIN_DIR = Path("data/bin")
CLOUDFLARED_PATH = BIN_DIR / "cloudflared"


class TunnelManager:
    def __init__(self):
        self._process: asyncio.subprocess.Process | None = None
        self._public_url: str | None = None
        self._lock = asyncio.Lock()
        self._drain_tasks: list[asyncio.Task] = []

    @property
    def public_url(self) -> str | None:
        return self._public_url

    @staticmethod
    def _ensure_resolv_conf() -> None:
        """Ensure /etc/resolv.conf contains Cloudflare DNS (1.1.1.1) and options use-vc to avoid SRV query SERVFAIL."""
        resolv = Path("/etc/resolv.conf")
        try:
            if resolv.exists() and os.access(resolv, os.W_OK):
                content = resolv.read_text(encoding="utf-8")
                # Remove 77.88.8.8 (Yandex DNS compresses SRV records causing Go bug #27546 'server misbehaving')
                lines = [line for line in content.splitlines() if "77.88.8.8" not in line]
                new_lines = [
                    "nameserver 1.1.1.1",
                    "nameserver 1.0.0.1",
                    "nameserver 8.8.8.8",
                    "options use-vc",
                ]
                for line in lines:
                    stripped = line.strip()
                    if stripped and not any(stripped.startswith(prefix) for prefix in new_lines):
                        new_lines.append(stripped)
                new_content = "\n".join(new_lines) + "\n"
                resolv.write_text(new_content, encoding="utf-8")
                log.info("resolv_conf_updated_with_cloudflare_dns")
        except Exception as e:  # noqa: BLE001
            log.debug("resolv_conf_update_skipped", error=str(e))

    def get_network_urls(self) -> list[tuple[str, str]]:
        """Return a list of (label, url) for all reachable interfaces."""
        port = getattr(settings, "dashboard_port", 8080)
        urls: list[tuple[str, str]] = []
        import socket

        # Wi-Fi / LAN IP
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                lan_ip = s.getsockname()[0]
                if lan_ip and not lan_ip.startswith("127."):
                    urls.append(("Wi-Fi / Локальная сеть", f"http://{lan_ip}:{port}"))
        except Exception:
            pass

        # Tailscale interface if available
        ts_ip = ""
        try:
            import subprocess

            res = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=2)
            candidate = res.stdout.strip()
            if candidate and candidate.startswith("100."):
                ts_ip = candidate
        except Exception:
            pass

        if not ts_ip:
            try:
                import subprocess

                ip_res = subprocess.run(
                    ["ip", "-4", "-o", "addr", "show", "tailscale0"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                m = re.search(r"inet\s+(100\.\d+\.\d+\.\d+)", ip_res.stdout)
                if m:
                    ts_ip = m.group(1)
            except Exception:
                pass

        if ts_ip and ts_ip.startswith("100."):
            urls.append(("Tailscale VPN", f"http://{ts_ip}:{port}"))

        urls.append(("Это устройство", f"http://localhost:{port}"))
        return urls

    def get_local_url(self) -> str:
        port = getattr(settings, "dashboard_port", 8080)
        host = getattr(settings, "dashboard_host", "127.0.0.1")
        if host in ("0.0.0.0", "127.0.0.1"):
            return f"http://localhost:{port}"
        return f"http://{host}:{port}"

    async def _find_or_download_binary(self) -> str | None:
        """Find cloudflared in PATH or local data/bin, or download it."""
        cmd = shutil.which("cloudflared")
        if cmd:
            return cmd

        if CLOUDFLARED_PATH.exists() and os.access(CLOUDFLARED_PATH, os.X_OK):
            return str(CLOUDFLARED_PATH)

        BIN_DIR.mkdir(parents=True, exist_ok=True)
        arch = platform.machine().lower()
        target = "arm64" if ("arm" in arch or "aarch" in arch) else "amd64"
        download_url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{target}"

        log.info("downloading_cloudflared", arch=arch, target=target, url=download_url)
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=60) as client:
                resp = await client.get(download_url)
                if resp.status_code == 200:
                    CLOUDFLARED_PATH.write_bytes(resp.content)
                    CLOUDFLARED_PATH.chmod(0o755)
                    log.info("cloudflared_downloaded_successfully", path=str(CLOUDFLARED_PATH))
                    return str(CLOUDFLARED_PATH)
                log.warning("cloudflared_download_failed", status=resp.status_code)
        except Exception as e:  # noqa: BLE001
            log.warning("cloudflared_download_exception", error=str(e))

        return None

    async def _start_ssh_tunnel(self, port: int) -> str | None:
        """Start an SSH reverse tunnel via localhost.run (port 22) or pinggy (port 443).

        Does not require external binaries or Cloudflare DNS SRV records,
        bypassing ISP/RKN blocks on argotunnel.com.
        """
        ssh_bin = shutil.which("ssh")
        if not ssh_bin:
            return None

        self._ensure_resolv_conf()

        providers = [
            (
                "localhost.run",
                [
                    ssh_bin,
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ServerAliveInterval=30",
                    "-o",
                    "ConnectTimeout=8",
                    "-R",
                    f"80:127.0.0.1:{port}",
                    "nokey@localhost.run",
                ],
                re.compile(r"https://[a-zA-Z0-9-]+\.(?:lhr\.life|lhrtunnel\.link|lhr\.rocks)"),
            ),
            (
                "pinggy",
                [
                    ssh_bin,
                    "-p",
                    "443",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ServerAliveInterval=30",
                    "-o",
                    "ConnectTimeout=8",
                    f"-R0:127.0.0.1:{port}",
                    "a.pinggy.io",
                ],
                re.compile(r"https://[a-zA-Z0-9-]+\.(?:free\.pinggy\.net|run\.pinggy-free\.link)"),
            ),
        ]

        for name, cmd, url_pattern in providers:
            log.info("starting_ssh_tunnel", provider=name, port=port)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                self._process = proc
                url_found = asyncio.Event()

                async def monitor_ssh(
                    stream,
                    proc=proc,
                    url_pattern=url_pattern,
                    url_found=url_found,
                    name=name,
                ):
                    try:
                        while proc.returncode is None:
                            line = await stream.readline()
                            if not line:
                                break
                            text = line.decode(errors="ignore")
                            match = url_pattern.search(text)
                            if match and not self._public_url:
                                self._public_url = match.group(0)
                                url_found.set()
                                log.info("ssh_tunnel_ready", provider=name, url=self._public_url)
                            elif text.strip():
                                log.debug("ssh_stream_log", provider=name, line=text.strip())
                    except Exception as e:  # noqa: BLE001
                        log.debug("ssh_stream_monitor_stopped", error=str(e))

                if proc.stdout:
                    self._drain_tasks.append(asyncio.create_task(monitor_ssh(proc.stdout)))

                try:
                    await asyncio.wait_for(url_found.wait(), timeout=10)
                    if self._public_url:
                        return self._public_url
                except TimeoutError:
                    log.warning("ssh_tunnel_timeout", provider=name)

                # If this provider timed out or didn't yield a URL, stop and try next
                self.stop()

            except Exception as e:  # noqa: BLE001
                log.warning("ssh_tunnel_start_error", provider=name, error=str(e))
                self.stop()

        return self._public_url

    async def _start_cloudflared_tunnel(self, port: int) -> str | None:
        """Start a cloudflared quick tunnel."""
        binary = await self._find_or_download_binary()
        if not binary:
            return None

        self._ensure_resolv_conf()

        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                "--edge-ip-version",
                "4",
                "tunnel",
                "--protocol",
                "http2",
                "--no-autoupdate",
                "--url",
                f"http://127.0.0.1:{port}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._process = proc

            url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            url_found = asyncio.Event()

            async def monitor_stream(stream):
                try:
                    while proc.returncode is None:
                        line = await stream.readline()
                        if not line:
                            break
                        text = line.decode(errors="ignore")
                        match = url_pattern.search(text)
                        if match and not self._public_url:
                            self._public_url = match.group(0)
                            url_found.set()
                            log.info("cloudflared_tunnel_ready", url=self._public_url)
                        elif "ERR" in text or "error" in text.lower():
                            log.warning("cloudflared_stream_log", line=text.strip())
                except Exception as e:  # noqa: BLE001
                    log.debug("stream_monitor_stopped", error=str(e))

            if proc.stderr:
                self._drain_tasks.append(asyncio.create_task(monitor_stream(proc.stderr)))
            if proc.stdout:
                self._drain_tasks.append(asyncio.create_task(monitor_stream(proc.stdout)))

            try:
                await asyncio.wait_for(url_found.wait(), timeout=15)
            except TimeoutError:
                log.warning("cloudflared_tunnel_timeout")

        except Exception as e:  # noqa: BLE001
            log.error("cloudflared_start_error", error=str(e))

        return self._public_url

    async def get_or_start_tunnel(self, force_restart: bool = False) -> str | None:
        """Return public URL (from config, existing active tunnel, or start new)."""
        # 1. Configured static URL has highest priority
        if getattr(settings, "dashboard_public_url", ""):
            return settings.dashboard_public_url.rstrip("/")

        async with self._lock:
            if not force_restart and self._public_url and self._process and self._process.returncode is None:
                return self._public_url

            if force_restart:
                self.stop()

            # Check if auto tunnel is disabled
            if not getattr(settings, "dashboard_auto_tunnel", True):
                return None

            port = getattr(settings, "dashboard_port", 8080)

            # Try SSH tunnel (pinggy) first - immune to Russian ISP blocks of argotunnel.com
            ssh_url = await self._start_ssh_tunnel(port)
            if ssh_url and self._process and self._process.returncode is None:
                return ssh_url

            # Fallback to cloudflared
            return await self._start_cloudflared_tunnel(port)

    def stop(self):
        """Stop running tunnel process and background reader tasks."""
        for t in self._drain_tasks:
            t.cancel()
        self._drain_tasks.clear()

        if self._process and self._process.returncode is None:
            with contextlib.suppress(Exception):
                self._process.terminate()
        self._process = None
        self._public_url = None


tunnel_manager = TunnelManager()
