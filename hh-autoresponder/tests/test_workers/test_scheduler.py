import pytest
from datetime import datetime, timezone
from freezegun import freeze_time
from app.workers.scheduler import WorkerScheduler
from app.config import settings

@pytest.fixture
def mock_scheduler(mocker):
    mocker.patch("app.workers.scheduler.WorkerScheduler._load_state")
    mocker.patch("app.workers.scheduler.WorkerScheduler._save_state")
    return WorkerScheduler()

@freeze_time("2026-09-19 02:00:00", tz_offset=3)
def test_quiet_hours_at_night(mock_scheduler, mocker):
    """Тест: Ночью (2:00) возвращается True (тихие часы)."""
    mocker.patch.object(settings, "notify_hour_start", 9)
    mocker.patch.object(settings, "notify_hour_end", 22)
    assert mock_scheduler._is_quiet_hours() is True

@freeze_time("2026-09-19 12:00:00", tz_offset=3)
def test_quiet_hours_at_day(mock_scheduler, mocker):
    """Тест: Днём (12:00) возвращается False (рабочие часы)."""
    mocker.patch.object(settings, "notify_hour_start", 9)
    mocker.patch.object(settings, "notify_hour_end", 22)
    assert mock_scheduler._is_quiet_hours() is False

@pytest.mark.asyncio
async def test_job_apply_skipped_during_quiet_hours(mock_scheduler, mocker):
    """Тест: _job_apply пропускается в тихие часы."""
    mock_scheduler.auto_apply = True
    mock_scheduler.is_paused = False
    
    # Мокаем тихие часы = True
    mocker.patch.object(mock_scheduler, "_is_quiet_hours", return_value=True)
    
    mock_run_auto_apply = mocker.patch("app.workers.scheduler.run_auto_apply")
    
    await mock_scheduler._job_apply()
    
    # Не должно быть вызовов
    mock_run_auto_apply.assert_not_called()
