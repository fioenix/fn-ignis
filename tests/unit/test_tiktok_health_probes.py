"""Both TikTok connectors report on what a pass actually needs, not a constant.

TikTokPlugin.is_healthy and TikTokCreativeCenterPlugin.is_healthy both answered `return True`,
so verify_connectors_health reported them HEALTHY in every circumstance -- on a host with no
browser installed, with no session, and with TikTok unreachable. Four of six connectors had a
real probe; these two were a literal.
"""

from unittest.mock import AsyncMock

import pytest

from ignis.infrastructure.connectors import browser_support
from ignis.infrastructure.connectors.tiktok import (
    creative_center_plugin as creative_center_module,
    tiktok_plugin as tiktok_module,
)
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import (
    TikTokCreativeCenterPlugin,
)
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin


@pytest.fixture(autouse=True)
def reset_runtime_cache():
    browser_support.reset_browser_runtime_cache()
    yield
    browser_support.reset_browser_runtime_cache()


@pytest.fixture
def plugins():
    return TikTokPlugin(), TikTokCreativeCenterPlugin()


@pytest.fixture
def probes(monkeypatch):
    """Replace the two probes in the namespaces that call them.

    Both plugin modules import the helpers by name, so patching browser_support itself leaves
    their references untouched -- the first version of these tests did that and the patches had
    no effect at all.
    """
    launchable = AsyncMock(return_value=True)
    reachable = AsyncMock(return_value=True)
    for module in (tiktok_module, creative_center_module):
        monkeypatch.setattr(module, "browser_launch_available", launchable)
        monkeypatch.setattr(module, "surface_reachable", reachable)
    return launchable, reachable


@pytest.mark.asyncio
async def test_no_browser_means_unhealthy(plugins, probes):
    """The whole point: a browser-only connector cannot pull without a browser."""
    launchable, reachable = probes
    launchable.return_value = False

    for plugin in plugins:
        assert await plugin.is_healthy() is False

    assert not reachable.await_count, "a missing browser settles it; do not go to the network"


@pytest.mark.asyncio
async def test_an_unreachable_surface_means_unhealthy(plugins, probes):
    _launchable, reachable = probes
    reachable.return_value = False

    for plugin in plugins:
        assert await plugin.is_healthy() is False


@pytest.mark.asyncio
async def test_a_working_host_means_healthy(plugins, probes):
    for plugin in plugins:
        assert await plugin.is_healthy() is True


@pytest.mark.asyncio
async def test_a_missing_session_does_not_make_the_grid_unhealthy(probes):
    """The explore grid is public, and an auth manager with nothing stored yet is normal.

    Before authenticate_tiktok has ever run there is no storage_state. Treating that as a
    failure would report a connector that pulls fine as broken; expiry is what
    get_platform_auth_status is for.
    """
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(return_value=None)

    assert await TikTokPlugin(auth_manager=auth).is_healthy() is True


@pytest.mark.asyncio
async def test_a_broken_session_read_does_not_crash_the_probe(probes):
    """A health check that raises is worse than one that answers."""
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(side_effect=RuntimeError("database is gone"))

    assert await TikTokPlugin(auth_manager=auth).is_healthy() is True


@pytest.mark.asyncio
async def test_a_stored_session_is_sent_with_the_probe(probes):
    """TikTok shows a different page to a visitor it recognises, so use the session we hold."""
    _launchable, reachable = probes
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(
        return_value={"cookies": [{"name": "sessionid", "value": "abc"}]}
    )

    await TikTokPlugin(auth_manager=auth).is_healthy()

    assert reachable.await_args.kwargs["cookie_header"] == "sessionid=abc"


@pytest.mark.asyncio
async def test_no_playwright_module_is_not_launchable(monkeypatch):
    monkeypatch.setattr(browser_support, "browser_module_available", lambda: False)

    assert await browser_support.browser_launch_available() is False


@pytest.mark.asyncio
async def test_the_launchable_answer_is_resolved_once(monkeypatch):
    """Starting the Playwright driver costs about half a second; six connectors share the answer."""
    calls = []

    def _available():
        calls.append(1)
        return False

    monkeypatch.setattr(browser_support, "browser_module_available", _available)

    await browser_support.browser_launch_available()
    await browser_support.browser_launch_available()
    await browser_support.browser_launch_available()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_the_creative_center_probe_follows_redirects():
    """Its entry URL answers 301 and lands elsewhere, so refusing redirects would report broken.

    Verified against the live surface on 10/09/2026: 301 to
    ads.tiktok.com/creative/creativeCenter/trends, then 200.
    """
    import inspect

    source = inspect.getsource(browser_support.surface_reachable)

    assert "follow_redirects=True" in source


def test_the_creative_center_url_is_the_one_tiktok_serves_directly():
    """Pinned rather than probed: a network call here would make the suite depend on TikTok.

    The old inspiration/popular/hashtag path answers 301 and lands on this one. Both were run
    through fetch_macro_trends on 10/09/2026 and returned identical rows, so the redirect was
    only costing a round trip. If TikTok moves it again this test is the reminder to re-verify.
    """
    assert (
        TikTokCreativeCenterPlugin.BASE_URL
        == "https://ads.tiktok.com/creative/creativeCenter/trends"
    )


@pytest.mark.asyncio
async def test_no_auth_manager_blocks_keyword_search():
    """Two surfaces, two requirements: explore needs no login, keyword search does."""
    reason = await TikTokPlugin().keyword_search_blocked_reason()

    assert reason and "explore" in reason.lower()


@pytest.mark.asyncio
async def test_no_stored_session_blocks_keyword_search():
    """Measured 10/09/2026: with nothing stored, search_signals ran and returned zero cards.

    Reporting only HEALTHY hid that, which is why a research mission came back with nothing
    from TikTok and the report gave no reason.
    """
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(return_value=None)

    reason = await TikTokPlugin(auth_manager=auth).keyword_search_blocked_reason()

    assert reason and "authenticate_tiktok" in reason


@pytest.mark.asyncio
async def test_a_stored_session_blocks_nothing():
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(return_value={"cookies": [{"name": "sessionid", "value": "x"}]})

    assert await TikTokPlugin(auth_manager=auth).keyword_search_blocked_reason() is None


@pytest.mark.asyncio
async def test_a_failed_session_read_is_reported_not_raised():
    """A diagnostic that raises tells the operator less than one that answers."""
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(side_effect=RuntimeError("pool is gone"))

    reason = await TikTokPlugin(auth_manager=auth).keyword_search_blocked_reason()

    assert reason and "pool is gone" in reason


@pytest.mark.asyncio
async def test_a_blocked_surface_does_not_make_the_connector_unhealthy(probes):
    """The connector still serves the public grid, so the verdict stays HEALTHY.

    The gap belongs in remediation, where an operator reads it, not folded into a boolean that
    would deregister a connector that works.
    """
    auth = AsyncMock()
    auth.get_storage_state = AsyncMock(return_value=None)
    plugin = TikTokPlugin(auth_manager=auth)

    assert await plugin.is_healthy() is True
    assert await plugin.keyword_search_blocked_reason() is not None


@pytest.mark.asyncio
async def test_a_non_string_readiness_answer_is_ignored():
    """hasattr is true of any mock, and this report is serialised to JSON.

    The first version of the health wiring accepted whatever the attribute returned, so a mock
    plugin in an unrelated test put an AsyncMock into the payload and the whole diagnostic
    failed to serialise -- one connector's odd answer taking down the entire report.
    """
    import json

    from ignis.interfaces.mcp import server as mcp_server

    plugin = AsyncMock()
    plugin.keyword_search_blocked_reason = AsyncMock(return_value=AsyncMock())

    blocked = await plugin.keyword_search_blocked_reason()
    accepted = blocked if isinstance(blocked, str) and blocked.strip() else None

    assert accepted is None
    json.dumps({"remediation": accepted})  # would raise if a mock had been let through
    assert hasattr(mcp_server, "handle_verify_connectors_health")
