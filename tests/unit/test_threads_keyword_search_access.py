"""Threads public keyword search needs Meta App Review, and nothing in the API says so.

The endpoint answers HTTP 200 either way: approved, it searches public posts; unapproved, it
searches the authenticated account's own posts. An install that cannot tell the difference ends
up listening to itself and calling the result market data, so the difference is probed here and
reported — including the honest "cannot tell" case.
"""

from unittest.mock import AsyncMock

import pytest

from ignis.domain.exceptions import ConnectorAuthenticationException
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


def _plugin(graph_payloads):
    """A plugin whose Graph calls are stubbed, keyed by the endpoint suffix."""
    plugin = ThreadsPlugin()
    plugin._has_graph_token = AsyncMock(return_value=True)
    plugin._require_token = AsyncMock(return_value="token")

    async def graph_get(url, params):
        for suffix, payload in graph_payloads.items():
            if url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        return {}

    plugin._graph_get = AsyncMock(side_effect=graph_get)
    return plugin


ME = {"id": "1000000000001", "username": "own.account"}


@pytest.mark.asyncio
async def test_results_from_other_accounts_mean_public_search_is_live():
    plugin = _plugin({
        "/me": ME,
        "/keyword_search": {"data": [
            {"id": "1", "username": "stranger.one", "text": "market chatter"},
            {"id": "2", "username": "own.account", "text": "my own post"},
        ]},
    })

    report = await plugin.check_keyword_search_access("ai agent")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_PUBLIC
    assert "stranger" not in report["detail"], "The detail must not leak an author handle"


@pytest.mark.asyncio
async def test_results_only_from_the_authenticated_account_mean_the_scope_was_never_granted():
    plugin = _plugin({
        "/me": ME,
        "/keyword_search": {"data": [
            {"id": "1", "username": "own.account", "text": "my own post"},
            {"id": "2", "username": "@Own.Account", "text": "another of mine"},
        ]},
    })

    report = await plugin.check_keyword_search_access("ai agent")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_SELF_ONLY
    assert "App Review" in report["detail"]
    assert "browser_login=True" in report["detail"], "The message must point at the path that works"


@pytest.mark.asyncio
async def test_an_empty_result_is_reported_as_inconclusive_not_as_a_verdict():
    plugin = _plugin({"/me": ME, "/keyword_search": {"data": []}})

    report = await plugin.check_keyword_search_access("ai agent")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_INCONCLUSIVE
    assert "consistent with" in report["detail"]


@pytest.mark.asyncio
async def test_a_rejected_token_is_reported_as_not_permitted():
    plugin = _plugin({
        "/me": ME,
        "/keyword_search": ConnectorAuthenticationException("HTTP 403: scope missing"),
    })

    report = await plugin.check_keyword_search_access("ai agent")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_NOT_PERMITTED


@pytest.mark.asyncio
async def test_no_graph_token_is_not_treated_as_a_failure():
    """A browser-session install has no Graph token, which is the supported setup, not a fault."""
    plugin = ThreadsPlugin()
    plugin._has_graph_token = AsyncMock(return_value=False)

    report = await plugin.check_keyword_search_access("ai agent")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_NO_TOKEN
    assert "browser session" in report["detail"]


@pytest.mark.asyncio
async def test_no_probe_keyword_never_burns_a_request():
    plugin = _plugin({"/me": ME, "/keyword_search": {"data": []}})

    report = await plugin.check_keyword_search_access("")

    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_INCONCLUSIVE
    plugin._graph_get.assert_not_awaited()
