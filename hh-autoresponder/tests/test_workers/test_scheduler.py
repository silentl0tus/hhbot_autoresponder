import pytest
from datetime import datetime, timezone
from freezegun import freeze_time
from app.workers.scheduler import WorkerScheduler
from app.config import settings

@pytest.fixture
def mock_scheduler(mocker):
    mocker.patch("app.workers.scheduler.WorkerScheduler._load_state", return_value={})
    mocker.patch("app.workers.scheduler.WorkerScheduler._save_state")
    return WorkerScheduler()

@freeze_time("2026-09-19 02:00:00", tz_offset=3)
def test_quiet_hours_at_night(mock_scheduler, mocker):
    """Тест: Ночью (2:00) возвращается True (тихие часы)."""
    mocker.patch.object(settings, "notify_hour_start", 9)
    mock_scheduler._work_end_hour = 22
    mock_scheduler._work_end_minute = 0
    assert mock_scheduler._is_quiet_hours() is True

@freeze_time("2026-09-19 12:00:00", tz_offset=3)
def test_quiet_hours_at_day(mock_scheduler, mocker):
    """Тест: Днём (12:00) возвращается False (рабочие часы)."""
    mocker.patch.object(settings, "notify_hour_start", 9)
    mock_scheduler._work_end_hour = 22
    mock_scheduler._work_end_minute = 0
    assert mock_scheduler._is_quiet_hours() is False

@freeze_time("2026-09-19 19:30:00")  # 19:30 UTC = 22:30 МСК
def test_quiet_hours_at_22_30_with_end_23(mock_scheduler, mocker):
    """Тест: В 22:30 МСК при конце дня 23:15 — рабочие часы."""
    mock_scheduler._work_end_hour = 23
    mock_scheduler._work_end_minute = 15
    assert mock_scheduler._is_quiet_hours() is False

@freeze_time("2026-09-19 20:20:00")  # 20:20 UTC = 23:20 МСК
def test_quiet_hours_after_random_end(mock_scheduler, mocker):
    """Тест: В 23:20 МСК при конце дня 23:15 — тихие часы."""
    mock_scheduler._work_end_hour = 23
    mock_scheduler._work_end_minute = 15
    assert mock_scheduler._is_quiet_hours() is True

@freeze_time("2026-09-19 20:40:00")  # 20:40 UTC = 23:40 МСК
def test_quiet_hours_at_max_boundary(mock_scheduler, mocker):
    """Тест: В 23:40 МСК (максимальная граница) — тихие часы."""
    mock_scheduler._work_end_hour = 23
    mock_scheduler._work_end_minute = 40
    assert mock_scheduler._is_quiet_hours() is True

@pytest.mark.asyncio
async def test_job_apply_skipped_during_quiet_hours(mock_scheduler, mocker):
    """Тест: _job_apply пропускается в тихие часы."""
    mock_scheduler.auto_apply = True
    mock_scheduler.is_paused = False

    mocker.patch.object(mock_scheduler, "_is_quiet_hours", return_value=True)
    mock_run_auto_apply = mocker.patch("app.workers.scheduler.run_auto_apply")

    await mock_scheduler._job_apply()

    mock_run_auto_apply.assert_not_called()

@pytest.mark.asyncio
async def test_job_search_skipped_during_quiet_hours(mock_scheduler, mocker):
    """Тест: _job_search пропускается в тихие часы (поиск остановлен ночью)."""
    mock_scheduler.is_paused = False

    mocker.patch.object(mock_scheduler, "_is_quiet_hours", return_value=True)
    mock_run_search = mocker.patch("app.workers.scheduler.run_vacancy_search")

    await mock_scheduler._job_search()

    mock_run_search.assert_not_called()

@pytest.mark.asyncio
async def test_job_analyze_skipped_during_quiet_hours(mock_scheduler, mocker):
    """Тест: _job_analyze пропускается в тихие часы."""
    mock_scheduler.is_paused = False

    mocker.patch.object(mock_scheduler, "_is_quiet_hours", return_value=True)
    mock_run_analyze = mocker.patch("app.workers.scheduler.run_vacancy_analysis")

    await mock_scheduler._job_analyze()

    mock_run_analyze.assert_not_called()

@pytest.mark.asyncio
async def test_job_search_runs_during_working_hours(mock_scheduler, mocker):
    """Тест: _job_search выполняется в рабочее время."""
    mock_scheduler.is_paused = False

    mocker.patch.object(mock_scheduler, "_is_quiet_hours", return_value=False)
    mock_run_search = mocker.patch("app.workers.scheduler.run_vacancy_search")

    await mock_scheduler._job_search()

    mock_run_search.assert_called_once()
