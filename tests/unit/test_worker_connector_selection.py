"""The worker only registers connectors it can actually pull with.

Its image carries no browser runtime on purpose — Playwright plus Chromium would take it from
~90MB to ~500MB, and an unattended scraper on a 15-minute loop is what gets an IP blocked. A
connector that can only reach its data through a browser therefore belongs to Track 2, not to the
radar, and registering it here only produced a warning and zero signals on every cycle.
"""

from unittest.mock import AsyncMock

import pytest

from ignis.domain.value_objects import IngestRuntime
from ignis.interfaces.cli.scheduler import build_connector_registry


def _names(registry):
    return sorted(p.name for p in registry.list_plugins())


@pytest.fixture
def repository():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = None
    repo.list_platform_credentials.return_value = []
    repo.get_runtime_config.return_value = None
    return repo


@pytest.mark.asyncio
async def test_without_a_browser_only_official_api_connectors_are_registered(repository):
    registry, skipped = await build_connector_registry(repository, browser_available=False)

    registered = _names(registry)
    assert "Google Trends Intelligence" in registered
    assert not any("TikTok" in name for name in registered), registered

    skipped_names = {item["name"] for item in skipped}
    assert any("TikTok" in name for name in skipped_names), skipped
    assert all("browser" in item["reason"] for item in skipped)


@pytest.mark.asyncio
async def test_with_a_browser_every_connector_is_registered(repository):
    registry, skipped = await build_connector_registry(repository, browser_available=True)

    assert skipped == []
    assert any("TikTok" in name for name in _names(registry))


@pytest.mark.asyncio
async def test_a_dual_tier_connector_joins_when_its_official_api_is_configured(repository, monkeypatch):
    """Threads over the Graph API is plain HTTP, so a token lets it into a browserless worker."""
    from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

    async def http_api(self):
        return IngestRuntime.HTTP_API

    monkeypatch.setattr(ThreadsPlugin, "resolve_ingest_runtime", http_api)
    registry, skipped = await build_connector_registry(repository, browser_available=False)

    assert "Threads Trending Discussions" in _names(registry)
    assert "Threads Trending Discussions" not in {item["name"] for item in skipped}


@pytest.mark.asyncio
async def test_a_dual_tier_connector_is_left_out_when_only_a_session_exists(repository):
    """With no Graph token the plugin resolves to the browser tier, which this worker lacks."""
    registry, skipped = await build_connector_registry(repository, browser_available=False)

    assert "Threads Trending Discussions" not in _names(registry)
    assert "Instagram Reels Trending" not in _names(registry)


@pytest.mark.asyncio
async def test_a_connector_that_cannot_answer_is_kept_rather_than_dropped(repository, monkeypatch):
    """An error while resolving the runtime must not silently remove a channel from the radar."""
    from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin

    async def boom(self):
        raise RuntimeError("credential store unreachable")

    monkeypatch.setattr(GoogleTrendsRssPlugin, "resolve_ingest_runtime", boom)
    registry, _ = await build_connector_registry(repository, browser_available=False)

    assert "Google Trends Intelligence" in _names(registry)
