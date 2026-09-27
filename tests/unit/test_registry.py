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
        self.search_limits: List[int] = []
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
        self.search_limits.append(limit)
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


@pytest.mark.asyncio
async def test_search_across_all_accepts_and_forwards_a_result_limit():
    """AutonomousDiscoveryUseCase has always passed limit=30.

    search_across_all never declared it, so every daily discovery raised TypeError inside a
    try/except and produced a dossier with zero signals.
    """
    grid = VideoGridPlugin()
    registry = ConnectorPluginRegistry()
    registry.register(grid)

    signals = await registry.search_across_all(keywords=["ai agent"], limit=30)

    assert len(signals) == 1
    assert grid.search_calls == [["ai agent"]]
    assert grid.search_limits == [30], "The cap must reach the connector, not be dropped"


# --- Per-surface outcomes for a mission search ---
#
# A mission run records what every eligible surface did, so a reopened report can tell a measured
# zero from a probe that never measured. The outcome travels with the call's own result: reading a
# registry-wide "last pass" would let two concurrent missions overwrite each other's facts.

from ignis.domain.exceptions import (  # noqa: E402
    ConnectorAuthenticationException,
    ConnectorQuotaExceededException,
)
from ignis.domain.harness_models import ChannelHealthStatus  # noqa: E402


class EmptyYouTubePlugin(_BasePlugin):
    """Ran every query and found nothing, and says so."""

    _platform = PlatformType.YOUTUBE
    _name = "YouTube Empty"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20,
                             attestation=None):
        for keyword in keywords:
            attestation.executed(keyword)
        return []


class SilentYouTubePlugin(_BasePlugin):
    """Returns nothing and attests nothing: its silence measured nothing."""

    _platform = PlatformType.YOUTUBE
    _name = "YouTube Silent"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        return []


class QuotaGridPlugin(VideoGridPlugin):
    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        raise ConnectorQuotaExceededException("quota exhausted")


class HttpRateLimitedPlugin(VideoGridPlugin):
    _plugin_id = "reels"
    _platform = PlatformType.REELS
    _name = "Reels 429"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        raise ConnectorExecutionException("HTTP 429 Too Many Requests")


class AuthRejectedPlugin(VideoGridPlugin):
    _plugin_id = "threads"
    _platform = PlatformType.THREADS
    _name = "Threads without session"

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        raise ConnectorAuthenticationException("no token and no browser session")


class SessionlessGridPlugin(VideoGridPlugin):
    """TikTok keyword search returns nothing, without error, when no session is stored."""

    async def keyword_search_blocked_reason(self):
        return "No TikTok session is stored, so keyword search returns nothing."

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        return []


class BrokenGridPlugin(VideoGridPlugin):
    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        raise ConnectorExecutionException("selector changed")


def _by_surface(result):
    return {o.connector_surface: (o.status, o.signals_collected) for o in result.outcomes}


@pytest.mark.asyncio
async def test_every_eligible_surface_reports_exactly_what_it_did():
    registry = _registry(GooglePlugin(), EmptyYouTubePlugin(), CreativeCenterPlugin())

    result = await registry.search_with_outcomes(keywords=["ai agent"], geo=GeoCode.VN)

    assert [s.raw_title for s in result.signals] == ["google: ai agent"]
    # The Creative Center has no keyword probe, so it is not an eligible surface of this search.
    assert _by_surface(result) == {
        "google": (ChannelHealthStatus.HEALTHY, 1),
        "youtube": (ChannelHealthStatus.EMPTY_NO_DATA, 0),
    }
    assert {o.platform for o in result.outcomes} == {"google", "youtube"}


@pytest.mark.asyncio
async def test_a_failed_probe_is_never_reported_as_an_empty_one():
    registry = _registry(
        QuotaGridPlugin(), HttpRateLimitedPlugin(), AuthRejectedPlugin(), EmptyYouTubePlugin()
    )
    broken = _registry(BrokenGridPlugin())

    result = await registry.search_with_outcomes(keywords=["ai agent"])
    failed = await broken.search_with_outcomes(keywords=["ai agent"])

    assert _by_surface(result) == {
        "tiktok_video_grid": (ChannelHealthStatus.RATE_LIMITED, 0),
        "reels": (ChannelHealthStatus.RATE_LIMITED, 0),
        "threads": (ChannelHealthStatus.AUTH_REQUIRED, 0),
        "youtube": (ChannelHealthStatus.EMPTY_NO_DATA, 0),
    }
    assert _by_surface(failed) == {"tiktok_video_grid": (ChannelHealthStatus.DEGRADED, 0)}


@pytest.mark.asyncio
async def test_an_empty_answer_from_a_surface_that_needs_a_missing_session_is_not_a_measured_zero():
    result = await _registry(SessionlessGridPlugin()).search_with_outcomes(keywords=["ai agent"])

    assert _by_surface(result) == {"tiktok_video_grid": (ChannelHealthStatus.AUTH_REQUIRED, 0)}


@pytest.mark.asyncio
async def test_a_surface_skipped_by_an_open_circuit_is_recorded_not_dropped():
    registry = _registry(BrokenGridPlugin(), EmptyYouTubePlugin())
    for _ in range(3):
        await registry.search_with_outcomes(keywords=["ai agent"])
    assert registry._breakers["tiktok_video_grid"].state == "OPEN"

    result = await registry.search_with_outcomes(keywords=["ai agent"])

    assert _by_surface(result)["tiktok_video_grid"] == (ChannelHealthStatus.DEGRADED, 0)

    quota = _registry(QuotaGridPlugin())
    for _ in range(3):
        await quota.search_with_outcomes(keywords=["ai agent"])
    skipped = await quota.search_with_outcomes(keywords=["ai agent"])
    assert _by_surface(skipped) == {"tiktok_video_grid": (ChannelHealthStatus.RATE_LIMITED, 0)}


@pytest.mark.asyncio
async def test_platform_filtering_decides_which_surfaces_are_eligible():
    registry = _registry(GooglePlugin(), EmptyYouTubePlugin(), VideoGridPlugin())

    result = await registry.search_with_outcomes(
        keywords=["ai agent"], target_platforms=[PlatformType.YOUTUBE]
    )

    assert _by_surface(result) == {"youtube": (ChannelHealthStatus.EMPTY_NO_DATA, 0)}


@pytest.mark.asyncio
async def test_two_concurrent_searches_each_keep_their_own_outcomes():
    import asyncio

    class SlowGoogle(GooglePlugin):
        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20,
                                 attestation=None):
            await asyncio.sleep(0.01)
            attestation.executed(keywords[0])
            return [] if keywords == ["nothing"] else await super().search_signals(keywords, geo)

    registry = _registry(SlowGoogle())

    found, empty = await asyncio.gather(
        registry.search_with_outcomes(keywords=["ai agent"]),
        registry.search_with_outcomes(keywords=["nothing"]),
    )

    assert _by_surface(found) == {"google": (ChannelHealthStatus.HEALTHY, 1)}
    assert _by_surface(empty) == {"google": (ChannelHealthStatus.EMPTY_NO_DATA, 0)}
    assert [o.queried_keywords for o in empty.outcomes] == [("nothing",)]
    assert [o.queried_keywords for o in found.outcomes] == [("ai agent",)]


@pytest.mark.asyncio
async def test_the_list_only_search_keeps_its_contract():
    registry = _registry(GooglePlugin(), EmptyYouTubePlugin())

    signals = await registry.search_across_all(keywords=["ai agent"])

    assert isinstance(signals, list)
    assert [s.raw_title for s in signals] == ["google: ai agent"]


# --- Review 0d70e9b: an empty answer is a measured zero only when the surface attests it ran ------

from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin  # noqa: E402
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin  # noqa: E402

BROWSER_STATE = {"cookies": [{"name": "sessionid", "value": "unit-test"}]}
# A search page that answered with its API envelope but no matching item: the query ran.
EMPTY_SEARCH_PAYLOAD = {"data": {"recent": {"sections": []}, "searchResults": {"edges": []}}}


def _session_plugin(plugin_class):
    oauth, browser = AsyncMock(), AsyncMock()
    oauth.get_access_token.return_value = None
    browser.get_storage_state.return_value = BROWSER_STATE
    return plugin_class(auth_manager=oauth, browser_auth_manager=browser)


@pytest.mark.parametrize(
    "plugin_class, module",
    [
        (ReelsPlugin, "ignis.infrastructure.connectors.reels.reels_plugin"),
        (ThreadsPlugin, "ignis.infrastructure.connectors.threads.threads_plugin"),
    ],
)
@pytest.mark.asyncio
async def test_a_browser_surface_that_captured_nothing_is_not_a_measured_empty(plugin_class, module):
    """No Playwright, an unusable session and a failed capture all return [] from collect."""
    from unittest.mock import patch

    registry = _registry(_session_plugin(plugin_class))
    with patch(f"{module}.collect_json_payloads", AsyncMock(return_value=[])), \
            patch(f"{module}.fetch_graphql_direct", AsyncMock(return_value=None), create=True):
        result = await registry.search_with_outcomes(keywords=["ai cho cửa hàng"])

    [outcome] = result.outcomes
    assert outcome.status is not ChannelHealthStatus.EMPTY_NO_DATA
    assert outcome.status in (ChannelHealthStatus.DEGRADED, ChannelHealthStatus.AUTH_REQUIRED)



@pytest.mark.asyncio
async def test_an_empty_answer_without_an_attestation_is_degraded_not_measured():
    result = await _registry(SilentYouTubePlugin()).search_with_outcomes(keywords=["ai agent"])

    [outcome] = result.outcomes
    assert outcome.status is ChannelHealthStatus.DEGRADED and outcome.queried_keywords == ()


@pytest.mark.parametrize(
    "plugin_class, module",
    [
        (ReelsPlugin, "ignis.infrastructure.connectors.reels.reels_plugin"),
        (ThreadsPlugin, "ignis.infrastructure.connectors.threads.threads_plugin"),
    ],
)
@pytest.mark.asyncio
async def test_a_browser_surface_attests_only_the_ten_keywords_it_actually_queried(plugin_class, module):
    """The page answered with an empty envelope for each query it ran; the eleventh never ran."""
    from unittest.mock import patch

    keywords = [f"topic{index}" for index in range(1, 12)]
    registry = _registry(_session_plugin(plugin_class))
    with patch(f"{module}.collect_json_payloads", AsyncMock(return_value=[EMPTY_SEARCH_PAYLOAD])), \
            patch(f"{module}.fetch_graphql_direct", AsyncMock(return_value=None), create=True):
        result = await registry.search_with_outcomes(keywords=keywords)

    [outcome] = result.outcomes
    assert outcome.status is ChannelHealthStatus.EMPTY_NO_DATA
    assert outcome.queried_keywords == tuple(keywords[:10])
