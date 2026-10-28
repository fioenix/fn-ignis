"""Retired Threads collection refuses every stored-credential variant before I/O."""
import pytest

from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "own_profile", "trending", "suggestions", "access_probe", "health"])
@pytest.mark.parametrize("credentials", ["cookies", "oauth", "both", "none"])
async def test_retired_threads_collection_never_uses_stored_credentials(operation, credentials, monkeypatch):
    from unittest.mock import AsyncMock
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    from ignis.domain.value_objects import IngressScope
    from ignis.application.ports.connector_port import SearchAttestation
    import httpx
    import playwright.async_api
    auth, browser = AsyncMock(), AsyncMock()
    auth.get_access_token.side_effect = AssertionError("Collection read OAuth credentials")
    browser.get_storage_state.side_effect = AssertionError("Collection read stored cookies")
    plugin = ThreadsPlugin(auth_manager=auth if credentials in {"oauth", "both"} else None,
                           browser_auth_manager=browser if credentials in {"cookies", "both"} else None)
    def forbidden(*args, **kwargs):
        pytest.fail("Retired Threads collection reached network/browser")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(playwright.async_api, "async_playwright", forbidden)
    if operation == "health":
        assert await plugin.is_healthy() is False
    elif operation == "access_probe":
        report = await plugin.check_keyword_search_access("synthetic")
        assert report["status"] == "UNAVAILABLE" and report["reason_code"] == "HOST_BROWSER_REQUIRED"
    else:
        attestation = SearchAttestation()
        with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
            if operation == "search":
                await plugin.search_signals(["synthetic"], attestation=attestation)
            elif operation == "own_profile":
                await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)
            elif operation == "trending":
                await plugin.fetch_trending_topics()
            else:
                await plugin.fetch_search_suggestions("synthetic")
        assert attestation.queried == []
    auth.get_access_token.assert_not_awaited()
    browser.get_storage_state.assert_not_awaited()
