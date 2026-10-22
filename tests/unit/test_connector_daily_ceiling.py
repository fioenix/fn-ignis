"""T013: each channel stops at its daily request ceiling (Spec 016 US4, FR-013).

One request is one keyword searched on one channel, counted per calendar day in Asia/Ho_Chi_Minh
in the store, so separate sessions share the count. A pass that does not fit stops that channel
with RATE_LIMITED and a `daily_ceiling` note before any request is sent; the other channels run.
"""

import asyncio
import sqlite3
from datetime import datetime, timezone
from typing import List

import pytest

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.listening_period import LISTENING_TZ
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


class _SearchPlugin(IConnectorPlugin):
    def __init__(self, platform: PlatformType):
        self._platform = platform
        self.search_calls: List[List[str]] = []

    @property
    def platform(self) -> PlatformType:
        return self._platform

    @property
    def name(self) -> str:
        return f"{self._platform.value} search"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50) -> List[TrendSignal]:
        return []

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20) -> List[TrendSignal]:
        self.search_calls.append(list(keywords))
        return [TrendSignal(platform=self._platform, raw_title=f"{keywords[0]} video", metric_value=1.0, geo_code=geo)]


@pytest.fixture
def store(tmp_path):
    return tmp_path / "ceiling.sqlite3"


def _registry(path):
    repository = SqliteTrendRepository(str(path))
    registry = ConnectorPluginRegistry(repository=repository)
    tiktok, google = _SearchPlugin(PlatformType.TIKTOK), _SearchPlugin(PlatformType.GOOGLE_TRENDS)
    registry.register(tiktok)
    registry.register(google)
    return registry, repository, tiktok, google


def _outcome(result, platform):
    return next(outcome for outcome in result.outcomes if outcome.platform == platform)


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT platform, used FROM connector_request_days").fetchall())
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_a_channel_at_its_ceiling_stops_and_the_others_run(store):
    registry, repository, tiktok, google = _registry(store)
    await repository.set_runtime_config("connector.tiktok.daily_request_ceiling", "1")

    first = await registry.search_with_outcomes(keywords=["áo khoác"])
    # A second session on the same store sees the same count.
    registry, _, tiktok_again, google_again = _registry(store)
    second = await registry.search_with_outcomes(keywords=["áo len"])

    assert _outcome(first, "tiktok").status != ChannelHealthStatus.RATE_LIMITED
    stopped = _outcome(second, "tiktok")
    assert stopped.status == ChannelHealthStatus.RATE_LIMITED and stopped.signals_collected == 0
    assert stopped.note.startswith("daily_ceiling")
    assert tiktok_again.search_calls == [], "No request may be sent past the ceiling"
    assert google_again.search_calls == [["áo len"]]
    assert _outcome(second, "google").status != ChannelHealthStatus.RATE_LIMITED
    assert _counts(store) == {"tiktok": 1, "google": 2}


@pytest.mark.asyncio
async def test_a_pass_that_does_not_fit_is_refused_whole(store):
    registry, repository, tiktok, _ = _registry(store)
    await repository.set_runtime_config("connector.tiktok.daily_request_ceiling", "1")

    result = await registry.search_with_outcomes(keywords=["áo khoác", "áo len"])

    assert _outcome(result, "tiktok").status == ChannelHealthStatus.RATE_LIMITED
    assert tiktok.search_calls == []
    assert _counts(store).get("tiktok", 0) == 0


@pytest.mark.asyncio
async def test_default_ceilings_apply_when_none_is_configured(store):
    registry, _, tiktok, _ = _registry(store)
    keywords = [f"từ khoá {index}" for index in range(51)]

    over = await registry.search_with_outcomes(keywords=keywords)
    within = await registry.search_with_outcomes(keywords=keywords[:50])

    assert _outcome(over, "tiktok").status == ChannelHealthStatus.RATE_LIMITED
    assert _outcome(within, "tiktok").status != ChannelHealthStatus.RATE_LIMITED
    assert tiktok.search_calls == [keywords[:50]]
    assert _counts(store)["google"] == 50, "Google keeps the default of 50 as well"


@pytest.mark.asyncio
async def test_the_count_is_kept_for_the_vietnam_calendar_day(store):
    registry, _, _, _ = _registry(store)

    await registry.search_with_outcomes(keywords=["áo khoác"])

    conn = sqlite3.connect(store)
    try:
        days = {row[0] for row in conn.execute("SELECT request_day FROM connector_request_days")}
    finally:
        conn.close()
    assert days == {datetime.now(timezone.utc).astimezone(LISTENING_TZ).date().isoformat()}


@pytest.mark.asyncio
async def test_an_invalid_configured_ceiling_falls_back_to_the_default(store):
    registry, repository, tiktok, _ = _registry(store)
    await repository.set_runtime_config("connector.tiktok.daily_request_ceiling", "many")

    result = await registry.search_with_outcomes(keywords=["áo khoác"])

    assert _outcome(result, "tiktok").status != ChannelHealthStatus.RATE_LIMITED
    assert tiktok.search_calls == [["áo khoác"]]


@pytest.mark.asyncio
async def test_a_store_without_a_ledger_sets_no_ceiling():
    registry = ConnectorPluginRegistry(repository=None)
    tiktok = _SearchPlugin(PlatformType.TIKTOK)
    registry.register(tiktok)

    result = await registry.search_with_outcomes(keywords=["áo khoác"])

    assert _outcome(result, "tiktok").status != ChannelHealthStatus.RATE_LIMITED
    assert tiktok.search_calls == [["áo khoác"]]


class _ProbeOnlyPlugin(_SearchPlugin):
    """A popularity-chart feed: an ingress pass routes it to the keyword probe (stage 2)."""

    feed_yields_candidate_topics = False


@pytest.mark.asyncio
async def test_the_ingress_keyword_probe_respects_the_ceiling(store):
    repository = SqliteTrendRepository(str(store))
    registry = ConnectorPluginRegistry(repository=repository)
    youtube = _ProbeOnlyPlugin(PlatformType.YOUTUBE)
    registry.register(youtube)
    await repository.set_runtime_config("connector.youtube.daily_request_ceiling", "0")

    signals = await registry.fetch_from_all(seed_keywords=["áo khoác"])

    assert youtube.search_calls == [] and signals == []
    assert _counts(store).get("youtube", 0) == 0


@pytest.mark.asyncio
async def test_in_memory_reservations_are_serialised():
    # The shared in-memory connection lost or failed some of 60 concurrent reservations in about
    # one run in ten before reservations went through the write lock; twenty runs catch that.
    day = datetime(2026, 10, 22, tzinfo=timezone.utc)
    for _ in range(20):
        repository = SqliteTrendRepository(":memory:")
        results = await asyncio.gather(
            *(repository.reserve_connector_requests(day.date(), "tiktok", 1, 25, day) for _ in range(60))
        )
        assert sum(admitted for admitted, _ in results) == 25
        assert await repository.reserve_connector_requests(day.date(), "tiktok", 0, 25, day) == (True, 25)


@pytest.mark.asyncio
async def test_pain_point_extraction_reserves_its_tiktok_searches(store):
    """extract_customer_pain_points searches TikTok outside the registry, so it reserves itself."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
    from ignis.interfaces.mcp import server

    repository = SqliteTrendRepository(str(store))
    await repository.set_runtime_config("connector.tiktok.daily_request_ceiling", "1")
    components = {"registry": MagicMock(), "repository": repository, "tiktok_auth_manager": AsyncMock()}
    components["registry"]._plugins = {}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=components):
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as fetch:
            fetch.return_value = []
            refused = json.loads(await server.handle_extract_customer_pain_points(keywords=["áo khoác", "áo len"]))
            admitted = json.loads(await server.handle_extract_customer_pain_points(keywords=["áo khoác"]))

    assert refused["status"] == "RATE_LIMITED" and refused["reason"] == "daily_ceiling"
    assert admitted["status"] == "SUCCESS"
    assert fetch.await_count == 1
    assert _counts(store) == {"tiktok": 1}


class _CappedPlugin(_SearchPlugin):
    """Reads at most ten keywords per search, as TikTok and Reels do."""

    max_search_keywords = 10


@pytest.mark.asyncio
async def test_the_count_is_what_a_capped_connector_sends(store):
    repository = SqliteTrendRepository(str(store))
    registry = ConnectorPluginRegistry(repository=repository)
    reels = _CappedPlugin(PlatformType.REELS)
    registry.register(reels)
    await repository.set_runtime_config("connector.reels.daily_request_ceiling", "10")

    result = await registry.search_with_outcomes(keywords=[f"từ khoá {index}" for index in range(15)])

    assert _outcome(result, "reels").status != ChannelHealthStatus.RATE_LIMITED
    assert _counts(store) == {"reels": 10}


@pytest.mark.asyncio
async def test_pain_points_count_every_tiktok_keyword_searched(store):
    """TikTok search reads every keyword it is given, so fifteen keywords need fifteen requests."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import json

    from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
    from ignis.interfaces.mcp import server

    repository = SqliteTrendRepository(str(store))
    await repository.set_runtime_config("connector.tiktok.daily_request_ceiling", "10")
    components = {"registry": MagicMock(), "repository": repository, "tiktok_auth_manager": AsyncMock()}
    components["registry"]._plugins = {}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=components):
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as fetch:
            refused = json.loads(await server.handle_extract_customer_pain_points(
                keywords=[f"từ khoá {index}" for index in range(15)]))

    assert refused["status"] == "RATE_LIMITED" and fetch.await_count == 0
