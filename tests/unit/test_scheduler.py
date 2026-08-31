import pytest
from unittest.mock import AsyncMock, patch, MagicMock
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
