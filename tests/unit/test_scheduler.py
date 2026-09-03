import pytest
from unittest.mock import AsyncMock, MagicMock
from ignis.interfaces.cli.scheduler import IngressScheduler
from ignis.domain.value_objects import GeoCode


@pytest.mark.asyncio
async def test_scheduler_run_once():
    scheduler = IngressScheduler(interval_seconds=1, geo=GeoCode.VN)

    mock_registry = AsyncMock()
    mock_registry.fetch_from_all = AsyncMock(return_value=[MagicMock()])
    mock_cluster_use_case = AsyncMock()
    mock_cluster_use_case.execute = AsyncMock(return_value=[MagicMock()])

    await scheduler.run_once(mock_registry, mock_cluster_use_case)

    assert mock_registry.fetch_from_all.called
    assert mock_cluster_use_case.execute.called


@pytest.mark.asyncio
async def test_scheduler_stop():
    scheduler = IngressScheduler(interval_seconds=1)
    scheduler.stop()
    assert scheduler._running is False
    assert scheduler._shutdown_event.is_set()


@pytest.mark.asyncio
async def test_scheduler_health_probe_cycle():
    scheduler = IngressScheduler(interval_seconds=1)
    mock_plugin = AsyncMock()
    mock_plugin.name = "Google Trends Intelligence"
    mock_plugin.is_healthy.return_value = True

    mock_registry = MagicMock()
    mock_registry._plugins = {"google": mock_plugin}

    mock_repo = AsyncMock()

    await scheduler.run_health_probe_cycle(mock_registry, mock_repo)
    assert mock_plugin.is_healthy.called
    assert mock_repo.log_event.called
    call_args = mock_repo.log_event.call_args[1]
    assert call_args["event_type"] == "CONNECTOR_HEALTH_CHECK"
    assert call_args["level"] == "INFO"


@pytest.mark.parametrize(
    "sync_min,sched_sec,expected",
    [
        (0, 900, 900),
        (0, 300, 300),
        (15, 900, 900),
        (60, 900, 3600),
        (30, 300, 1800),
    ],
)
def test_ingress_interval_resolution(sync_min, sched_sec, expected):
    from ignis.interfaces.cli.scheduler import resolve_ingress_interval

    result = resolve_ingress_interval(sync_minutes=sync_min, scheduler_seconds=sched_sec)
    assert result == expected

