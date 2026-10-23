import pytest

from app.dashboard.api import (
    get_applications_list,
    get_dashboard_stats,
    get_messages_list,
    get_recent_logs,
    get_vacancies_list,
)
from app.dashboard.server import create_dashboard_app


def test_dashboard_routes_registered():
    app = create_dashboard_app()
    routes = [route.resource.canonical for route in app.router.routes() if route.resource]
    assert "/" in routes
    assert "/api/stats" in routes
    assert "/api/vacancies" in routes
    assert "/api/applications" in routes
    assert "/api/messages" in routes
    assert "/api/logs" in routes
    assert "/api/actions/reset_rejected" in routes


@pytest.mark.asyncio
async def test_get_dashboard_stats():
    data = await get_dashboard_stats()
    assert "summary" in data
    assert "funnel" in data
    assert "timeline" in data
    assert "reasons" in data
    assert "sessions" in data
    assert "total_vacancies" in data["summary"]
    assert "total_sent" in data["summary"]
    assert len(data["funnel"]) == 5


@pytest.mark.asyncio
async def test_get_vacancies_list():
    res = await get_vacancies_list(page=1, limit=5)
    assert "items" in res
    assert "total" in res
    assert isinstance(res["items"], list)
    if res["items"]:
        first = res["items"][0]
        assert "id" in first
        assert "title" in first
        assert "status" in first


@pytest.mark.asyncio
async def test_get_applications_list():
    apps = await get_applications_list(limit=5)
    assert isinstance(apps, list)


@pytest.mark.asyncio
async def test_get_messages_list():
    msgs = await get_messages_list(limit=5)
    assert isinstance(msgs, list)


def test_get_recent_logs():
    logs = get_recent_logs(lines_count=10)
    assert isinstance(logs, list)
