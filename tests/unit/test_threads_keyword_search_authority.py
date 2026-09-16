"""The Threads keyword-search verdict must be stored, and everything that routes must read it.

`check_keyword_search_access` already establishes the fact: without the `threads_keyword_search`
grant, the endpoint answers HTTP 200 while searching the authenticated account's own posts. That
verdict was computed and thrown away. Nothing persisted it, and neither the tier resolution, the
runtime resolution nor the search path consulted it -- so a public-market probe could call the
endpoint *after* the system had already established it only searches the operator's own account.

The danger is not an empty result. It is a full one: the account's own posts, shaped exactly like
market evidence, flowing into the Opportunity Index. No data is recoverable; false evidence is not.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from ignis.domain.exceptions import ConnectorAuthenticationException
from ignis.domain.value_objects import IngestRuntime
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


def _auth_manager(token="LONG_LIVED_TOKEN", verdict=None):
    manager = AsyncMock()
    manager.get_access_token.return_value = token
    manager.get_keyword_search_verdict.return_value = verdict
    return manager


def _browser_manager(storage_state=None):
    manager = AsyncMock()
    manager.get_storage_state.return_value = storage_state
    return manager


SESSION = {"cookies": [{"name": "sessionid", "value": "x", "domain": ".threads.com"}]}


# --- The verdict is written down ---


@pytest.mark.asyncio
async def test_the_probe_records_its_verdict():
    """A verdict recomputed on every call is a verdict nobody can route on."""
    manager = _auth_manager()
    plugin = ThreadsPlugin(auth_manager=manager)

    async def _get(url, params=None, **kwargs):
        response = MagicMock()
        response.status_code = 200
        if "keyword_search" in url:
            response.json.return_value = {"data": [{"id": "1", "username": "self_account"}]}
        else:
            response.json.return_value = {"id": "99", "username": "self_account"}
        return response

    plugin._graph_get = AsyncMock(
        side_effect=lambda url, params=None, **kw: (
            {"data": [{"id": "1", "username": "self_account"}]}
            if "keyword_search" in url
            else {"id": "99", "username": "self_account"}
        )
    )

    report = await plugin.check_keyword_search_access("cà phê")
    assert report["status"] == ThreadsPlugin.KEYWORD_SEARCH_SELF_ONLY
    manager.record_keyword_search_verdict.assert_awaited_once()
    assert (
        manager.record_keyword_search_verdict.await_args.args[0]
        == ThreadsPlugin.KEYWORD_SEARCH_SELF_ONLY
    )


@pytest.mark.asyncio
async def test_clearing_the_credential_clears_the_verdict():
    """A verdict outliving the token it describes is worse than no verdict at all."""
    from ignis.infrastructure.auth.meta_oauth import ThreadsAuthManager

    repository = AsyncMock()
    repository.delete_platform_credentials.return_value = True
    manager = ThreadsAuthManager(repository=repository, crypto_service=MagicMock())

    await manager.clear_auth()

    cleared = [
        call.args[0]
        for call in repository.set_runtime_config.await_args_list
        + repository.delete_runtime_config.await_args_list
        if call.args
    ]
    assert any("keyword_search" in str(key) for key in cleared), (
        "clear_auth() left the keyword-search verdict in place; the next token would inherit the "
        "previous token's permissions"
    )


# --- Everything that routes reads it ---


@pytest.mark.asyncio
async def test_a_self_only_token_does_not_outrank_a_browser_session():
    """The browser session can actually search Threads; a self-only token cannot."""
    plugin = ThreadsPlugin(
        auth_manager=_auth_manager(verdict=ThreadsPlugin.KEYWORD_SEARCH_SELF_ONLY),
        browser_auth_manager=_browser_manager(SESSION),
    )
    tier, _ = await plugin.resolve_auth_tier()
    assert tier == "session_cookies", (
        f"the OAuth token won with tier {tier!r}, although it is already known to search only the "
        "authenticated account's own posts"
    )


@pytest.mark.asyncio
async def test_ingest_runtime_follows_the_demoted_tier():
    plugin = ThreadsPlugin(
        auth_manager=_auth_manager(verdict=ThreadsPlugin.KEYWORD_SEARCH_NOT_PERMITTED),
        browser_auth_manager=_browser_manager(SESSION),
    )
    assert await plugin.resolve_ingest_runtime() == IngestRuntime.BROWSER


@pytest.mark.asyncio
async def test_a_public_verdict_leaves_the_graph_path_alone():
    """The correction must not fire on a token that genuinely holds the grant."""
    plugin = ThreadsPlugin(
        auth_manager=_auth_manager(verdict=ThreadsPlugin.KEYWORD_SEARCH_PUBLIC),
        browser_auth_manager=_browser_manager(SESSION),
    )
    tier, _ = await plugin.resolve_auth_tier()
    assert tier == "oauth2"
    assert await plugin.resolve_ingest_runtime() == IngestRuntime.HTTP_API


@pytest.mark.asyncio
async def test_an_unprobed_token_keeps_its_current_behaviour():
    """No verdict is not a negative verdict; an install that never probed is not punished."""
    plugin = ThreadsPlugin(
        auth_manager=_auth_manager(verdict=None),
        browser_auth_manager=_browser_manager(SESSION),
    )
    tier, _ = await plugin.resolve_auth_tier()
    assert tier == "oauth2"


# --- The search path refuses rather than inventing evidence ---


@pytest.mark.asyncio
async def test_search_refuses_when_the_only_path_left_searches_the_operators_own_posts():
    """With no browser session, the honest answer is a refusal, not the account's own timeline."""
    plugin = ThreadsPlugin(
        auth_manager=_auth_manager(verdict=ThreadsPlugin.KEYWORD_SEARCH_SELF_ONLY),
        browser_auth_manager=_browser_manager(None),
    )
    plugin._graph_get = AsyncMock(
        return_value={"data": [{"id": "1", "username": "self_account", "text": "own post"}]}
    )

    with pytest.raises(ConnectorAuthenticationException) as raised:
        await plugin.search_signals(keywords=["cà phê"])

    assert "browser_login" in str(raised.value), (
        "the refusal does not tell the operator the path that actually works"
    )
    plugin._graph_get.assert_not_awaited(), "the endpoint was called anyway"
