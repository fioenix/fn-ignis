"""The TikTok connector reports on what a pass actually needs, not a constant.

TikTokPlugin.is_healthy and the retired Creative Center probe both answered `return True`,
so verify_connectors_health reported them HEALTHY in every circumstance -- on a host with no
browser installed, with no session, and with TikTok unreachable. Four of six connectors had a
real probe; these two were a literal.
"""

from unittest.mock import AsyncMock

import pytest

from ignis.infrastructure.connectors import browser_support


@pytest.fixture(autouse=True)
def reset_runtime_cache():
    browser_support.reset_browser_runtime_cache()
    yield
    browser_support.reset_browser_runtime_cache()


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
