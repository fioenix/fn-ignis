import pytest
from unittest.mock import AsyncMock
from typing import List

from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


class MockSuccessPlugin(IConnectorPlugin):
    @property
    def platform(self) -> PlatformType:
        return PlatformType.GOOGLE_TRENDS

    @property
    def name(self) -> str:
        return "Mock Success RSS"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50) -> List[TrendSignal]:
        return [
            TrendSignal(
                platform=PlatformType.GOOGLE_TRENDS,
                raw_title="Google Search Hot Trend",
                metric_value=50000.0,
                geo_code=geo
            )
        ]


class MockFailingPlugin(IConnectorPlugin):
    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    @property
    def name(self) -> str:
        return "Mock Failing YouTube"

    async def is_healthy(self) -> bool:
        return False

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50) -> List[TrendSignal]:
        raise ConnectorExecutionException("Network timeout or quota error")


@pytest.mark.asyncio
async def test_ingest_orchestration_with_error_isolation():
    registry = ConnectorPluginRegistry()
    registry.register(MockSuccessPlugin())
    registry.register(MockFailingPlugin())

    signals = await registry.fetch_from_all(geo=GeoCode.VN)

    assert len(signals) == 1
    assert signals[0].platform == PlatformType.GOOGLE_TRENDS


@pytest.mark.asyncio
async def test_circuit_breaker_tripping_on_repeated_failures():
    registry = ConnectorPluginRegistry()
    failing_plugin = MockFailingPlugin()
    registry.register(failing_plugin)

    # 3 failures -> Circuit Breaker trips to OPEN
    for _ in range(3):
        signals = await registry.fetch_from_all()
        assert len(signals) == 0

    breaker = registry._breakers[PlatformType.YOUTUBE]
    assert breaker.state == "OPEN"
    assert breaker.can_execute() is False


@pytest.mark.asyncio
async def test_retired_threads_does_not_dispatch_or_break_other_ingress():
    from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
    threads = ThreadsPlugin(auth_manager=AsyncMock(), browser_auth_manager=AsyncMock())
    threads.search_signals = AsyncMock(side_effect=AssertionError("Retired collection dispatched"))
    registry = ConnectorPluginRegistry()
    registry.register(MockSuccessPlugin())
    registry.register(threads)
    signals = await registry.fetch_from_all()
    assert len(signals) == 1
    assert registry.last_pass_report["unavailable_surfaces"] == {"threads": "HOST_BROWSER_REQUIRED"}
    assert signals[0].platform is PlatformType.GOOGLE_TRENDS
    threads.search_signals.assert_not_awaited()
    threads._auth_manager.get_access_token.assert_not_awaited()
    threads._browser_auth_manager.get_storage_state.assert_not_awaited()
