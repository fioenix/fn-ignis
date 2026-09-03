"""
Regression coverage for the plugin registry keying.

Before this suite, `_plugins` was keyed by `PlatformType`, so registering both
TikTok plugins made the Creative Center silently evict the video-grid plugin and
its keyword search probe never ran.
"""

from typing import List
from unittest.mock import AsyncMock

import pytest

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


class _BasePlugin(IConnectorPlugin):
    """Minimal plugin recording which probe the registry actually invoked."""

    _platform = PlatformType.TIKTOK
    _plugin_id: str | None = None
    _name = "Base Plugin"

    def __init__(self):
        self.fetch_calls = 0
        self.search_calls: List[List[str]] = []
        self.suggestion_calls = 0

    @property
    def platform(self) -> PlatformType:
        return self._platform

    @property
    def name(self) -> str:
        return self._name

    @property
    def plugin_id(self) -> str:
        return self._plugin_id or super().plugin_id

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50) -> List[TrendSignal]:
        self.fetch_calls += 1
        return [TrendSignal(platform=self._platform, raw_title=f"{self.name} fetch", metric_value=1.0, geo_code=geo)]


class VideoGridPlugin(_BasePlugin):
    """Stands in for TikTokPlugin: overrides search_signals, so supports_search is True."""

    _plugin_id = "tiktok_video_grid"
    _name = "TikTok Video Grid"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20) -> List[TrendSignal]:
        self.search_calls.append(list(keywords))
        return [TrendSignal(platform=self._platform, raw_title=f"grid: {keywords[0]}", metric_value=2.0, geo_code=geo)]

    async def fetch_suggestions(self, keywords, geo=GeoCode.VN) -> List[dict]:
        self.suggestion_calls += 1
        return [{"term": f"{keywords[0]} review", "platform": "tiktok"}]


class CreativeCenterPlugin(_BasePlugin):
    """Stands in for TikTokCreativeCenterPlugin: no search override, so supports_search is False."""

    _plugin_id = "tiktok_creative_center"
    _name = "TikTok Creative Center"


class GooglePlugin(_BasePlugin):
    """Single plugin for its platform, so it keeps the default plugin_id."""

    _platform = PlatformType.GOOGLE_TRENDS
    _name = "Google Trends"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20) -> List[TrendSignal]:
        self.search_calls.append(list(keywords))
        return [TrendSignal(platform=self._platform, raw_title=f"google: {keywords[0]}", metric_value=3.0, geo_code=geo)]


class FailingGridPlugin(VideoGridPlugin):
    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50) -> List[TrendSignal]:
        raise ConnectorExecutionException("boom")


def _registry(*plugins, repository=None) -> ConnectorPluginRegistry:
    registry = ConnectorPluginRegistry(repository=repository)
    for p in plugins:
        registry.register(p)
    return registry


# --- Identity & coexistence ---


def test_default_plugin_id_is_the_platform_value():
    assert GooglePlugin().plugin_id == "google"


def test_two_plugins_on_the_same_platform_coexist():
    grid, creative = VideoGridPlugin(), CreativeCenterPlugin()
    registry = _registry(grid, creative)

    plugins = registry.list_plugins()
    assert len(plugins) == 2
    assert {p.name for p in plugins} == {"TikTok Video Grid", "TikTok Creative Center"}

    # Both get an independent circuit breaker.
    assert set(registry._breakers) == {"tiktok_video_grid", "tiktok_creative_center"}
    assert registry._breakers["tiktok_video_grid"] is not registry._breakers["tiktok_creative_center"]


def test_lookup_api_addresses_plugins_without_loss():
    grid, creative, google = VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin()
    registry = _registry(grid, creative, google)

    # get_plugins returns every probe on a platform.
    assert registry.get_plugins(PlatformType.TIKTOK) == [grid, creative]
    assert registry.get_plugins(PlatformType.GOOGLE_TRENDS) == [google]
    assert registry.get_plugins() == [grid, creative, google]

    # get_plugin_by_id addresses one exactly.
    assert registry.get_plugin_by_id("tiktok_creative_center") is creative
    assert registry.get_plugin_by_id("nope") is None

    # get_plugin stays backward compatible: first registration for the platform.
    assert registry.get_plugin(PlatformType.TIKTOK) is grid
    assert registry.get_plugin(PlatformType.GOOGLE_TRENDS) is google
    assert registry.get_plugin(PlatformType.YOUTUBE) is None


def test_duplicate_plugin_id_warns_before_replacing(caplog):
    first, second = VideoGridPlugin(), VideoGridPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(first)

    with caplog.at_level("WARNING"):
        registry.register(second)

    assert "already registered" in caplog.text
    assert len(registry.list_plugins()) == 1
    assert registry.get_plugin_by_id("tiktok_video_grid") is second


# --- Fan-out: every plugin is invoked ---


@pytest.mark.asyncio
async def test_fetch_from_all_invokes_every_registered_plugin():
    grid, creative, google = VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin()
    registry = _registry(grid, creative, google)

    signals = await registry.fetch_from_all(geo=GeoCode.VN, timeframe=Timeframe.LAST_24H)

    assert grid.fetch_calls == 1
    assert creative.fetch_calls == 1
    assert google.fetch_calls == 1
    assert len(signals) == 3


@pytest.mark.asyncio
async def test_search_across_all_reaches_the_tiktok_video_grid():
    """The exact regression: keyword search on TikTok must hit the video grid probe."""
    grid, creative, google = VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin()
    registry = _registry(grid, creative, google)

    signals = await registry.search_across_all(
        keywords=["ai agent"], geo=GeoCode.VN, timeframe=Timeframe.LAST_7D
    )

    assert grid.search_calls == [["ai agent"]]
    assert google.search_calls == [["ai agent"]]
    assert {s.raw_title for s in signals} == {"grid: ai agent", "google: ai agent"}


@pytest.mark.asyncio
async def test_search_skips_plugins_without_a_keyword_probe():
    """Creative Center inherits the default search_signals, which would just re-fetch macro trends."""
    grid, creative = VideoGridPlugin(), CreativeCenterPlugin()
    registry = _registry(grid, creative)

    signals = await registry.search_across_all(keywords=["ai agent"], geo=GeoCode.VN)

    assert creative.supports_search is False
    assert creative.fetch_calls == 0
    assert all("Creative Center" not in s.raw_title for s in signals)


@pytest.mark.asyncio
async def test_target_platforms_filter_selects_both_tiktok_probes():
    grid, creative, google = VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin()
    registry = _registry(grid, creative, google)

    await registry.search_across_all(
        keywords=["ai agent"], target_platforms=[PlatformType.TIKTOK]
    )

    # Filtering by platform must not be confused by the plugin_id keys.
    assert grid.search_calls == [["ai agent"]]
    assert google.search_calls == []


@pytest.mark.asyncio
async def test_fetch_suggestions_filters_by_platform_not_plugin_id():
    grid, creative, google = VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin()
    registry = _registry(grid, creative, google)

    suggestions = await registry.fetch_suggestions_across_all(
        keywords=["ai agent"], target_platforms=[PlatformType.TIKTOK]
    )

    assert grid.suggestion_calls == 1
    assert suggestions == [{"term": "ai agent review", "platform": "tiktok"}]


# --- Health reporting ---


def test_health_status_reports_every_plugin_independently():
    registry = _registry(VideoGridPlugin(), CreativeCenterPlugin(), GooglePlugin())
    status = registry.get_health_status()

    assert set(status) == {"tiktok_video_grid", "tiktok_creative_center", "google"}

    grid_status = status["tiktok_video_grid"]
    assert grid_status["platform"] == "tiktok"
    assert grid_status["plugin_id"] == "tiktok_video_grid"
    assert grid_status["supports_search"] is True
    assert status["tiktok_creative_center"]["platform"] == "tiktok"
    assert status["tiktok_creative_center"]["supports_search"] is False


@pytest.mark.asyncio
async def test_circuit_breaker_isolation_between_plugins_on_one_platform():
    repo = AsyncMock()
    failing, creative = FailingGridPlugin(), CreativeCenterPlugin()
    registry = _registry(failing, creative, repository=repo)

    for _ in range(3):
        await registry.fetch_from_all()

    status = registry.get_health_status()
    assert status["tiktok_video_grid"]["circuit_state"] == "OPEN"
    assert status["tiktok_video_grid"]["consecutive_failures"] == 3

    # The healthy sibling on the same platform must stay CLOSED and keep ingesting.
    assert status["tiktok_creative_center"]["circuit_state"] == "CLOSED"
    assert creative.fetch_calls == 3

    # A tripped breaker only silences its own plugin.
    signals = await registry.fetch_from_all()
    assert len(signals) == 1
    assert creative.fetch_calls == 4
