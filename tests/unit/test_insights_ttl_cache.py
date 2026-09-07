import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.config import settings
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe
from ignis.infrastructure.cache.insights_cache import InsightsTTLCache
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

THREADS_LIST = {
    "data": [
        {
            "id": "17900000000001",
            "text": "Chi phí self-hosted MCP server giảm 60% sau khi migrate",
            "permalink": "https://www.threads.net/@fioenix/post/C9xYzAbc",
            "timestamp": "2026-09-01T04:30:00+0000",
            "username": "fioenix",
            "media_type": "TEXT_POST",
        }
    ]
}

REELS_LIST = {
    "data": [
        {
            "id": "18000000000001",
            "caption": "Workflow tự động hóa kho vận cho shop thời trang",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "permalink": "https://www.instagram.com/reel/C9abcDEF/",
            "timestamp": "2026-09-02T02:15:00+0000",
            "like_count": 830,
            "comments_count": 61,
            "username": "logistics_vn",
        }
    ]
}

THREADS_INSIGHTS = {
    "data": [
        {"name": "views", "total_value": {"value": 48200}},
        {"name": "likes", "total_value": {"value": 1310}},
        {"name": "replies", "total_value": {"value": 284}},
    ]
}

REELS_INSIGHTS = {
    "data": [
        {"name": "plays", "total_value": {"value": 91500}},
        {"name": "reach", "total_value": {"value": 60400}},
    ]
}


def _resp(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.text = json.dumps(payload)
    return resp


def _auth_manager(token: str = "LONG_LIVED_TOKEN") -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_access_token.return_value = token
    return mgr


class _CountingGraph:
    """Mocked httpx GET that records how many insights calls actually went out."""

    def __init__(self, list_payload, insights_payload):
        self.list_payload = list_payload
        self.insights_payload = insights_payload
        self.insights_calls = 0

    @property
    def get(self):
        async def _get(url, params=None, **kwargs):
            if "/insights" in url:
                self.insights_calls += 1
                return _resp(self.insights_payload)
            return _resp(self.list_payload)

        return _get


# --- Cache primitive ---


def test_default_ttl_is_two_hours():
    assert settings.META_INSIGHTS_CACHE_TTL_SECONDS == 7200
    assert InsightsTTLCache().ttl_seconds == 7200


def test_partition_splits_cached_entries_from_the_ids_still_to_fetch():
    cache = InsightsTTLCache()
    cache.set("threads", "p1", "views,likes", {"views": 10.0})

    cached, missing = cache.partition("threads", ["p1", "p2"], "views,likes")

    assert cached == {"p1": {"views": 10.0}}
    assert missing == ["p2"]


def test_entries_are_scoped_by_platform_and_metric_set():
    cache = InsightsTTLCache()
    cache.set("threads", "p1", "views,likes", {"views": 10.0})

    # Same id on another platform, or under a different metric set, must miss.
    assert cache.get("reels", "p1", "views,likes") is None
    assert cache.get("threads", "p1", "plays,reach") is None


def test_expired_entries_are_dropped_once_the_ttl_elapses():
    cache = InsightsTTLCache(ttl_seconds=0)
    cache.set("threads", "p1", "views", {"views": 1.0})

    assert cache.get("threads", "p1", "views") is None


def test_cache_is_bounded_so_a_long_running_daemon_cannot_grow_without_limit():
    cache = InsightsTTLCache(maxsize=2)
    for i in range(5):
        cache.set("threads", f"p{i}", "views", {"views": float(i)})

    assert cache.stats()["entries"] <= 2


def test_mutating_a_returned_dict_does_not_corrupt_the_cached_entry():
    cache = InsightsTTLCache()
    cache.set("threads", "p1", "views", {"views": 10.0})

    cache.get("threads", "p1", "views")["views"] = 999.0

    assert cache.get("threads", "p1", "views") == {"views": 10.0}


# --- Plugin-level N+1 suppression ---


@pytest.mark.asyncio
async def test_threads_second_pass_within_the_ttl_issues_no_insights_request():
    plugin = ThreadsPlugin(auth_manager=_auth_manager())
    graph = _CountingGraph(THREADS_LIST, THREADS_INSIGHTS)

    with patch("httpx.AsyncClient.get", side_effect=graph.get):
        first = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=25, scope=IngressScope.OWN_PROFILE)
        assert graph.insights_calls == 1

        second = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=25, scope=IngressScope.OWN_PROFILE)

    # The 15-minute re-scan hits the cache: still exactly one insights request in total.
    assert graph.insights_calls == 1
    assert first[0].metric_value == 48200.0
    assert second[0].metric_value == first[0].metric_value
    assert second[0].metadata["reply_count"] == 284


@pytest.mark.asyncio
async def test_reels_second_pass_within_the_ttl_issues_no_insights_request():
    plugin = ReelsPlugin(auth_manager=_auth_manager(), ig_user_id="17841400000000000")
    graph = _CountingGraph(REELS_LIST, REELS_INSIGHTS)

    with patch("httpx.AsyncClient.get", side_effect=graph.get):
        first = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=25, scope=IngressScope.OWN_PROFILE)
        assert graph.insights_calls == 1

        second = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=25, scope=IngressScope.OWN_PROFILE)

    assert graph.insights_calls == 1
    assert first[0].metric_value == 91500.0
    assert second[0].metadata["reach"] == 60400


@pytest.mark.asyncio
async def test_an_expired_entry_forces_a_fresh_insights_request():
    plugin = ThreadsPlugin(auth_manager=_auth_manager(), insights_cache=InsightsTTLCache(ttl_seconds=0))
    graph = _CountingGraph(THREADS_LIST, THREADS_INSIGHTS)

    with patch("httpx.AsyncClient.get", side_effect=graph.get):
        await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)
        await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)

    assert graph.insights_calls == 2


@pytest.mark.asyncio
async def test_only_the_uncached_posts_are_fetched_on_the_next_pass():
    cache = InsightsTTLCache()
    plugin = ThreadsPlugin(auth_manager=_auth_manager(), insights_cache=cache)
    graph = _CountingGraph(THREADS_LIST, THREADS_INSIGHTS)

    # Warm one of the two posts, then ingest a window containing both.
    cache.set(PlatformType.THREADS.value, "17900000000001", plugin.INSIGHT_METRICS, {"views": 1.0})
    two_posts = {"data": THREADS_LIST["data"] + [dict(THREADS_LIST["data"][0], id="17900000000002")]}
    graph.list_payload = two_posts

    with patch("httpx.AsyncClient.get", side_effect=graph.get):
        signals = await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)

    assert graph.insights_calls == 1
    assert len(signals) == 2
    assert signals[0].metric_value == 1.0


@pytest.mark.asyncio
async def test_plugins_do_not_share_a_cache_across_instances():
    cache_a = InsightsTTLCache()
    plugin_a = ThreadsPlugin(auth_manager=_auth_manager(), insights_cache=cache_a)
    plugin_b = ThreadsPlugin(auth_manager=_auth_manager())
    graph = _CountingGraph(THREADS_LIST, THREADS_INSIGHTS)

    with patch("httpx.AsyncClient.get", side_effect=graph.get):
        await plugin_a.fetch_signals(scope=IngressScope.OWN_PROFILE)
        await plugin_b.fetch_signals(scope=IngressScope.OWN_PROFILE)

    assert graph.insights_calls == 2
