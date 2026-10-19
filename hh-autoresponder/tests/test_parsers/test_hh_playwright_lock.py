import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.parsers.hh_playwright import HHPlaywright


@pytest.mark.asyncio
async def test_hh_playwright_lock_serializes_calls():
    """Тест: одновременные вызовы apply_to_vacancy и bump_resumes выполняются строго по очереди благодаря lock."""
    parser = HHPlaywright()

    execution_order = []

    async def fake_apply(*args, **kwargs):
        execution_order.append("apply_start")
        await asyncio.sleep(0.05)
        execution_order.append("apply_end")
        return True

    async def fake_bump(*args, **kwargs):
        execution_order.append("bump_start")
        await asyncio.sleep(0.01)
        execution_order.append("bump_end")
        return 1

    with (
        patch.object(parser, "_apply_to_vacancy_unlocked", side_effect=fake_apply),
        patch.object(parser, "_bump_resumes_unlocked", side_effect=fake_bump),
    ):
        # Запускаем две корутины конкурентно
        res_apply, res_bump = await asyncio.gather(
            parser.apply_to_vacancy("https://hh.ru/vacancy/1", "cover letter"),
            parser.bump_resumes(),
        )

    assert res_apply is True
    assert res_bump == 1

    # Проверяем строгую сериализацию: первый метод должен полностью завершиться до старта второго
    assert execution_order == [
        "apply_start",
        "apply_end",
        "bump_start",
        "bump_end",
    ]


@pytest.mark.asyncio
async def test_hh_playwright_lock_prevents_deadlock_on_login():
    """Тест: вызов _login_unlocked внутри locked метода не вызывает взаимную блокировку."""
    parser = HHPlaywright()

    with (
        patch.object(parser, "_login_unlocked", new_callable=AsyncMock, return_value=True),
        patch.object(parser, "_get_page", new_callable=AsyncMock) as mock_get_page,
    ):
        mock_page = AsyncMock()
        mock_page.is_closed.return_value = False
        mock_get_page.return_value = mock_page

        # bump_resumes вызывает _login_unlocked, держа self._lock
        # Не должно зависать
        res = await asyncio.wait_for(parser.bump_resumes(), timeout=1.0)
        assert isinstance(res, int)
