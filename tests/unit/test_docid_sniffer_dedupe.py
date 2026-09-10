"""The doc_id sniffer writes when Meta rotates a build, not once per intercepted request.

set() runs inside a Playwright request interceptor, so Threads calling GraphQL dozens of times
in one pass called it dozens of times. It queued a database write on every one: a measured pass
wrote the same three keys 97 times, 85 of them the same value for trending_topics.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
from ignis.infrastructure.connectors.meta_browser_ingress import GraphQLDocIdCache


@pytest.fixture(autouse=True)
def clean_caches(monkeypatch):
    """A class-level cache and a process-wide singleton both leak between tests."""
    GraphQLDocIdCache._cache = {
        "trending_topics": {"doc_id": None, "lsd": None},
        "search_posts": {"doc_id": None, "lsd": None},
        "search_suggestions": {"doc_id": None, "lsd": None},
    }
    GraphQLDocIdCache._pending_writes = set()

    manager = RuntimeConfigManager.get_instance()
    monkeypatch.setattr(manager, "_cache", {}, raising=False)
    writes = []

    async def _set(key, value, **kwargs):
        writes.append((key, value))

    monkeypatch.setattr(manager, "set", AsyncMock(side_effect=_set))
    monkeypatch.setattr(manager, "get_sync", lambda key, default=None: default or "")
    return writes


async def _drain():
    """Let the fire-and-forget persistence tasks finish."""
    await asyncio.gather(*list(GraphQLDocIdCache._pending_writes), return_exceptions=True)


@pytest.mark.asyncio
async def test_the_same_doc_id_seen_many_times_is_written_once(clean_caches):
    for _ in range(40):
        GraphQLDocIdCache.set("trending_topics", "doc-abc")
    await _drain()

    assert clean_caches == [("threads_doc_id_trending_topics", "doc-abc")]


@pytest.mark.asyncio
async def test_a_rotated_doc_id_is_written(clean_caches):
    """The whole point of persisting it: Meta ships a new build and the value really changes."""
    GraphQLDocIdCache.set("trending_topics", "doc-abc")
    for _ in range(10):
        GraphQLDocIdCache.set("trending_topics", "doc-abc")
    GraphQLDocIdCache.set("trending_topics", "doc-xyz")
    await _drain()

    assert clean_caches == [
        ("threads_doc_id_trending_topics", "doc-abc"),
        ("threads_doc_id_trending_topics", "doc-xyz"),
    ]


@pytest.mark.asyncio
async def test_a_value_already_in_the_database_is_not_rewritten(monkeypatch, clean_caches):
    """Otherwise every restart rewrites a doc_id that never changed."""
    manager = RuntimeConfigManager.get_instance()
    monkeypatch.setattr(
        manager, "get_sync",
        lambda key, default=None: "doc-persisted" if key.endswith("trending_topics") else "",
    )

    GraphQLDocIdCache.set("trending_topics", "doc-persisted")
    await _drain()

    assert clean_caches == []


@pytest.mark.asyncio
async def test_each_query_type_is_tracked_on_its_own(clean_caches):
    for _ in range(5):
        GraphQLDocIdCache.set("trending_topics", "doc-a")
        GraphQLDocIdCache.set("search_posts", "doc-b")
        GraphQLDocIdCache.set("search_suggestions", "doc-c")
    await _drain()

    assert sorted(clean_caches) == [
        ("threads_doc_id_search_posts", "doc-b"),
        ("threads_doc_id_search_suggestions", "doc-c"),
        ("threads_doc_id_trending_topics", "doc-a"),
    ]


@pytest.mark.asyncio
async def test_a_rotating_lsd_token_never_triggers_a_write(clean_caches):
    """The LSD rotates constantly and is not persisted, so it must not look like a change."""
    GraphQLDocIdCache.set("trending_topics", "doc-abc", lsd="lsd-1")
    for index in range(20):
        GraphQLDocIdCache.set("trending_topics", "doc-abc", lsd=f"lsd-{index}")
    await _drain()

    assert clean_caches == [("threads_doc_id_trending_topics", "doc-abc")]
    assert GraphQLDocIdCache._cache["trending_topics"]["lsd"] == "lsd-19"
