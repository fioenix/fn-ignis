from unittest.mock import AsyncMock, patch

import pytest

from ignis.config import settings
from ignis.domain.value_objects import IngressScope
from ignis.infrastructure.cache.insights_cache import InsightsTTLCache
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

THREADS_INSIGHTS = {
    "data": [
        {"name": "views", "total_value": {"value": 48200}},
        {"name": "likes", "total_value": {"value": 1310}},
        {"name": "replies", "total_value": {"value": 284}},
    ]
}

def _auth_manager(token: str = "LONG_LIVED_TOKEN") -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_access_token.return_value = token
    return mgr


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
async def test_retired_threads_does_not_consume_or_refresh_insight_cache():
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    cache = InsightsTTLCache()
    plugin = ThreadsPlugin(auth_manager=_auth_manager(), insights_cache=cache)
    with patch.object(cache, "get", side_effect=AssertionError("Retired cache read")), \
            patch("httpx.AsyncClient", side_effect=AssertionError("Retired insights request")):
        with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
            await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)
