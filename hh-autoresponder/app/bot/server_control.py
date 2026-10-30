import asyncio
import functools
from pathlib import Path

import aiohttp
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import settings

server_router = Router()


def admin_only(fn):
    @functools.wraps(fn)
    async def wrapper(event, **kwargs):
        chat_id = event.chat.id if isinstance(event, Message) else event.message.chat.id
        if str(chat_id) != str(settings.tg_admin_chat_id):
            return
        return await fn(event, **kwargs)

    return wrapper


async def run_root_command(cmd: str, timeout: float = 10.0) -> str:
    """Выполняет shell-команду асинхронно и безопасно без блокировки event loop."""
    proc = None
    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode(errors="replace").strip()
    except asyncio.TimeoutError:
        if proc:
            try:
                proc.kill()
            except Exception:
                pass
        return "⏳ Таймаут выполнения команды"
    except Exception as e:
        return f"❌ Ошибка: {e}"


async def fetch_public_ip() -> str:
    """Получает внешний IP через туннель Incy."""
    try:
        timeout = aiohttp.ClientTimeout(total=2.5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get("https://api.ipify.org") as resp:
                if resp.status == 200:
                    return (await resp.text()).strip()
    except Exception:
        pass
    return "Не определен"


def format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    parts = []
    if days > 0:
        parts.append(f"{days}д")
    if hours > 0 or days > 0:
        parts.append(f"{hours}ч")
    parts.append(f"{mins}м")
    return " ".join(parts)


async def get_system_report() -> str:
    # 1. Батарея
    bat_pct = "N/A"
    bat_status = "N/A"
    bat_temp = "N/A"
    try:
        cap_file = Path("/sys/class/power_supply/battery/capacity")
        if cap_file.exists():
            bat_pct = cap_file.read_text().strip() + "%"
        st_file = Path("/sys/class/power_supply/battery/status")
        if st_file.exists():
            st = st_file.read_text().strip()
            bat_status = "⚡ Зарядка" if "Charging" in st else ("🔋 Разряд" if "Discharging" in st else st)
        temp_file = Path("/sys/class/power_supply/battery/temp")
        if temp_file.exists():
            t = float(temp_file.read_text().strip()) / 10.0
            bat_temp = f"{t:.1f}°C"
    except Exception:
        pass

    # 2. Память RAM
    ram_str = "N/A"
    try:
        meminfo = Path("/proc/meminfo").read_text()
        total_kb = 0
        avail_kb = 0
        for line in meminfo.splitlines():
            if line.startswith("MemTotal:"):
                total_kb = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                avail_kb = int(line.split()[1])
        if total_kb > 0:
            used_mb = (total_kb - avail_kb) // 1024
            total_mb = total_kb // 1024
            pct = int((used_mb / total_mb) * 100)
            ram_str = f"{used_mb / 1024:.1f} / {total_mb / 1024:.1f} ГБ ({pct}%)"
    except Exception:
        pass

    # 3. Аптайм
    uptime_str = "N/A"
    try:
        up_sec = float(Path("/proc/uptime").read_text().split()[0])
        uptime_str = format_uptime(up_sec)
    except Exception:
        pass

    # 4. Сети и VPN
    tun0_ok = False
    try:
        devs = Path("/proc/net/dev").read_text()
        tun0_ok = "tun0:" in devs
    except Exception:
        pass
    tun0_icon = "🟢 В сети" if tun0_ok else "🔴 Отключен"

    ext_ip = await fetch_public_ip()

    # 5. Tailscale IP (динамически)
    ts_ip = "Не определен"
    try:
        ts_res = await run_root_command(
            "/data/data/com.termux/files/usr/bin/tailscale --socket=/data/data/com.termux/files/usr/var/run/tailscale/tailscaled.sock ip -4",
            timeout=2.0,
        )
        if ts_res and "." in ts_res and not ts_res.startswith("❌"):
            ts_ip = ts_res.strip().splitlines()[0]
    except Exception:
        pass

    # 6. Локальный Wi-Fi IP (динамически)
    wifi_ip = "Не подключен"
    try:
        wifi_res = await run_root_command(
            "ip -4 addr show wlan0 | grep -o 'inet [0-9.]*' | cut -d' ' -f2",
            timeout=2.0,
        )
        if wifi_res and "." in wifi_res and not wifi_res.startswith("❌"):
            wifi_ip = wifi_res.strip().splitlines()[0]
    except Exception:
        pass

    # Сборка красивого отчета
    msg = (
        "🖥️ <b>POCO F6 Pro — Серверный монитор</b>\n\n"
        f"🔋 <b>Батарея:</b> {bat_pct} ({bat_status}) | 🌡️ {bat_temp}\n"
        f"🧠 <b>RAM:</b> {ram_str}\n"
        f"⏱️ <b>Аптайм:</b> {uptime_str}\n\n"
        "🌐 <b>Сеть & VPN:</b>\n"
        f"• Incy VPN (tun0): {tun0_icon}\n"
        f"• Внешний VPN IP: <code>{ext_ip}</code>\n"
        f"• Локальный Wi-Fi: <code>{wifi_ip}</code>\n"
        f"• Tailscale IP: <code>{ts_ip}</code> 🟢\n"
        f"• ТВ Samsung (Таблица 100): 🟢 Маршрутизируется\n\n"
        "🔌 <b>Удаленный доступ (через Tailscale):</b>\n"
        f"• SSH Termux: <code>ssh -p 8022 u0_a152@{ts_ip}</code>\n"
        f"• Экран scrcpy: <code>adb connect {ts_ip}:5555</code>\n"
        f"• Дашборд: <code>http://{ts_ip}:8080</code>\n"
    )
    return msg


def server_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔄 Обновить статус", callback_data="srv_refresh"),
                InlineKeyboardButton(text="📶 Тест сети", callback_data="srv_test_net"),
            ],
            [
                InlineKeyboardButton(text="🦎 Перезапуск Tailscale", callback_data="srv_restart_ts"),
                InlineKeyboardButton(text="📡 Перезапуск Wi-Fi", callback_data="srv_restart_wifi"),
            ],
            [
                InlineKeyboardButton(text="⚠️ Перезагрузить смартфон", callback_data="srv_reboot_ask"),
            ],
        ]
    )


@server_router.message(Command("server"))
@admin_only
async def cmd_server(message: Message, **kw):
    text = await get_system_report()
    await message.answer(text, parse_mode="HTML", reply_markup=server_menu_keyboard())


@server_router.callback_query(F.data == "srv_refresh")
@admin_only
async def cb_srv_refresh(callback: CallbackQuery, **kw):
    await callback.answer("Обновление данных...")
    text = await get_system_report()
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=server_menu_keyboard())
    except Exception:
        pass


@server_router.callback_query(F.data == "srv_test_net")
@admin_only
async def cb_srv_test_net(callback: CallbackQuery, **kw):
    await callback.answer("⏳ Пинг 8.8.8.8 и ya.ru...")
    res = await run_root_command("ping -c 2 8.8.8.8 && ping -c 2 ya.ru", timeout=8.0)
    clean_res = res[-1500:] if len(res) > 1500 else res
    await callback.message.reply(
        f"📶 <b>Результат сетевого пинга:</b>\n<pre>{clean_res}</pre>",
        parse_mode="HTML",
    )


@server_router.callback_query(F.data == "srv_restart_ts")
@admin_only
async def cb_srv_restart_ts(callback: CallbackQuery, **kw):
    await callback.answer("⏳ Перезапуск Tailscale...")
    cmd = (
        "pkill -f tailscaled || true; sleep 1; "
        "nohup /data/data/com.termux/files/usr/bin/tailscaled "
        "--tun=tailscale0 "
        "--state=/data/data/com.termux/files/usr/var/lib/tailscale/tailscaled.state "
        "--socket=/data/data/com.termux/files/usr/var/run/tailscale/tailscaled.sock "
        "> /data/data/com.termux/files/usr/var/log/tailscaled.log 2>&1 & sleep 2; "
        "/data/data/com.termux/files/usr/bin/tailscale --socket=/data/data/com.termux/files/usr/var/run/tailscale/tailscaled.sock ip -4"
    )
    res = await run_root_command(cmd, timeout=10.0)
    await callback.message.reply(
        f"🦎 <b>Tailscale перезапущен:</b>\n<code>{res}</code>",
        parse_mode="HTML",
    )


@server_router.callback_query(F.data == "srv_restart_wifi")
@admin_only
async def cb_srv_restart_wifi(callback: CallbackQuery, **kw):
    await callback.answer("📡 Перезапуск Wi-Fi...")
    res = await run_root_command(
        "/system/bin/svc wifi disable; sleep 3; /system/bin/svc wifi enable; sleep 3; ip -4 addr show wlan0",
        timeout=12.0,
    )
    await callback.message.reply(
        f"📡 <b>Статус Wi-Fi после рестарта:</b>\n<pre>{res[-1000:]}</pre>",
        parse_mode="HTML",
    )


@server_router.callback_query(F.data == "srv_reboot_ask")
@admin_only
async def cb_srv_reboot_ask(callback: CallbackQuery, **kw):
    await callback.answer()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 ДА, ПЕРЕЗАГРУЗИТЬ", callback_data="srv_reboot_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="srv_reboot_cancel"),
            ]
        ]
    )
    await callback.message.reply(
        "⚠️ <b>Внимание! Вы запросили перезагрузку смартфона.</b>\n\n"
        "Смартфон выключится и запустится заново. Все демоны (Incy VPN, Table 100 для ТВ, Tailscale, Termux, Бот) поднимутся автоматически через KernelSU.\n\n"
        "Подтвердить?",
        parse_mode="HTML",
        reply_markup=kb,
    )


@server_router.callback_query(F.data == "srv_reboot_cancel")
@admin_only
async def cb_srv_reboot_cancel(callback: CallbackQuery, **kw):
    await callback.answer("Перезагрузка отменена")
    await callback.message.delete()


@server_router.callback_query(F.data == "srv_reboot_confirm")
@admin_only
async def cb_srv_reboot_confirm(callback: CallbackQuery, **kw):
    await callback.answer("🔄 Выполняется перезагрузка...")
    await callback.message.edit_text(
        "🔄 <b>Смартфон перезагружается...</b>\nСвязь восстановится через 30-45 секунд.",
        parse_mode="HTML",
    )
    await run_root_command("/system/bin/reboot || reboot", timeout=3.0)


@server_router.message(Command("reboot"))
@admin_only
async def cmd_reboot(message: Message, **kw):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 ДА, ПЕРЕЗАГРУЗИТЬ", callback_data="srv_reboot_confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="srv_reboot_cancel"),
            ]
        ]
    )
    await message.reply(
        "⚠️ <b>Перезагрузка смартфона:</b>\nПодтвердите действие:",
        parse_mode="HTML",
        reply_markup=kb,
    )


@server_router.message(Command("exec"))
@admin_only
async def cmd_exec(message: Message, **kw):
    raw_text = message.text or ""
    parts = raw_text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply(
            "Использование: <code>/exec &lt;shell_команда&gt;</code>\nПример: <code>/exec uptime</code>",
            parse_mode="HTML",
        )
        return

    cmd = parts[1].strip()
    await message.reply(f"⚡ <i>Выполняю:</i> <code>{cmd}</code>", parse_mode="HTML")
    res = await run_root_command(cmd, timeout=15.0)
    if not res:
        res = "[Команда завершилась без вывода]"

    if len(res) > 3800:
        res = res[:3800] + "\n... [вывод обрезан]"

    await message.reply(f"<pre>{res}</pre>", parse_mode="HTML")
