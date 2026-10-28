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


# --- The search path refuses rather than inventing evidence ---


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict", ["PUBLIC_SEARCH_ENABLED", "SELF_ONLY", "NOT_PERMITTED", None])
async def test_stored_keyword_verdict_cannot_reactivate_internal_collection(verdict):
    manager = _auth_manager()
    manager.get_keyword_search_verdict.return_value = verdict
    plugin = ThreadsPlugin(auth_manager=manager, browser_auth_manager=AsyncMock())
    assert await plugin.resolve_auth_tier() == ("host_required", None)
    assert await plugin.is_healthy() is False
    assert (await plugin.check_keyword_search_access("synthetic"))["status"] == "UNAVAILABLE"
    manager.get_access_token.assert_not_awaited()
    manager.get_keyword_search_verdict.assert_not_awaited()
    manager.record_keyword_search_verdict.assert_not_awaited()
