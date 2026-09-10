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



def test_resolve_ingress_interval_requires_both_intervals():
    """Neither argument may default; a default here is a second copy of a Settings value.

    The scheduler_seconds default used to be 900 -- a 15-minute tick that spends the whole
    daily YouTube search quota in about an hour -- so a caller that omitted it silently got
    the unsafe cadence instead of the configured one.
    """
    import inspect

    from ignis.interfaces.cli.scheduler import resolve_ingress_interval

    parameters = inspect.signature(resolve_ingress_interval).parameters
    for name in ("sync_minutes", "scheduler_seconds"):
        assert parameters[name].default is inspect.Parameter.empty, (
            f"{name} must stay required so it cannot drift from Settings"
        )


def test_ingress_scheduler_requires_an_explicit_interval():
    import inspect

    from ignis.interfaces.cli.scheduler import IngressScheduler

    parameter = inspect.signature(IngressScheduler.__init__).parameters["interval_seconds"]
    assert parameter.default is inspect.Parameter.empty


def test_zero_sync_minutes_leaves_the_configured_cadence_in_charge():
    """0 is the shipped SYNC_INTERVAL_MINUTES, so the seconds field must win at that value."""
    from ignis.config import Settings
    from ignis.interfaces.cli.scheduler import resolve_ingress_interval

    configured = Settings.model_fields["SCHEDULER_INTERVAL_SECONDS"].default
    assert resolve_ingress_interval(sync_minutes=0, scheduler_seconds=configured) == configured
