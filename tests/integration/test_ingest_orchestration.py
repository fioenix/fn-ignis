import pytest
from unittest.mock import AsyncMock
from typing import List

from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
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

    mock_repo = AsyncMock()
    mock_repo.save_signals = AsyncMock(return_value=1)

    use_case = IngestTrendsUseCase(registry=registry, repository=mock_repo)
    result = await use_case.execute(geo=GeoCode.VN)

    assert result["total_fetched"] == 1
    assert result["total_saved"] == 1
    assert mock_repo.save_signals.called
    saved_signals = mock_repo.save_signals.call_args[0][0]
    assert len(saved_signals) == 1
    assert saved_signals[0].platform == PlatformType.GOOGLE_TRENDS


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
