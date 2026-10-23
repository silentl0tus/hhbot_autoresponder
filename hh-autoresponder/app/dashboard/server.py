from pathlib import Path

import structlog
from aiohttp import web

from app.config import settings
from app.dashboard.api import (
    get_applications_list,
    get_dashboard_stats,
    get_messages_list,
    get_recent_logs,
    get_vacancies_list,
    trigger_reset_rejected,
)

log = structlog.get_logger()
STATIC_DIR = Path(__file__).parent / "static"


async def handle_index(request: web.Request) -> web.FileResponse:
    index_file = STATIC_DIR / "index.html"
    return web.FileResponse(index_file)


async def handle_api_stats(request: web.Request) -> web.Response:
    try:
        data = await get_dashboard_stats()
        return web.json_response(data)
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_api_stats_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_vacancies(request: web.Request) -> web.Response:
    try:
        status = request.query.get("status")
        search = request.query.get("search")
        page = int(request.query.get("page", 1))
        limit = min(int(request.query.get("limit", 25)), 100)
        sort = request.query.get("sort", "date")

        data = await get_vacancies_list(status=status, search=search, page=page, limit=limit, sort=sort)
        return web.json_response(data)
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_api_vacancies_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_applications(request: web.Request) -> web.Response:
    try:
        limit = min(int(request.query.get("limit", 50)), 100)
        data = await get_applications_list(limit=limit)
        return web.json_response({"items": data})
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_api_applications_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_messages(request: web.Request) -> web.Response:
    try:
        limit = min(int(request.query.get("limit", 40)), 100)
        data = await get_messages_list(limit=limit)
        return web.json_response({"items": data})
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_api_messages_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_logs(request: web.Request) -> web.Response:
    try:
        lines = min(int(request.query.get("lines", 100)), 300)
        level = request.query.get("level")
        data = get_recent_logs(lines_count=lines, level_filter=level)
        return web.json_response({"items": data})
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_api_logs_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def handle_api_reset_rejected(request: web.Request) -> web.Response:
    try:
        count = await trigger_reset_rejected()
        return web.json_response({"success": True, "count": count})
    except Exception as e:  # noqa: BLE001
        log.error("dashboard_action_reset_error", error=str(e))
        return web.json_response({"success": False, "error": str(e)}, status=500)


def create_dashboard_app() -> web.Application:
    app = web.Application()

    app.router.add_get("/", handle_index)
    app.router.add_get("/api/stats", handle_api_stats)
    app.router.add_get("/api/vacancies", handle_api_vacancies)
    app.router.add_get("/api/applications", handle_api_applications)
    app.router.add_get("/api/messages", handle_api_messages)
    app.router.add_get("/api/logs", handle_api_logs)
    app.router.add_post("/api/actions/reset_rejected", handle_api_reset_rejected)

    # Static files
    if STATIC_DIR.exists():
        app.router.add_static("/static/", STATIC_DIR)

    return app


async def start_dashboard(host: str = "127.0.0.1", port: int = 8080) -> web.AppRunner:
    app = create_dashboard_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("dashboard_started", url=f"http://{host}:{port}")
    return runner


def main():
    host = settings.dashboard_host if hasattr(settings, "dashboard_host") else "127.0.0.1"
    port = settings.dashboard_port if hasattr(settings, "dashboard_port") else 8080
    app = create_dashboard_app()
    print(f"🚀 Запуск Job Hunter Dashboard: http://{host}:{port}")
    web.run_app(app, host=host, port=port)


if __name__ == "__main__":
    main()
