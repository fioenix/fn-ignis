"""Retired internal Threads grant probing cannot use credentials or provider requests."""
from unittest.mock import AsyncMock, patch

import pytest

from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "synthetic public query"])
async def test_retired_access_probe_never_spends_a_provider_request(query):
    manager = AsyncMock()
    plugin = ThreadsPlugin(auth_manager=manager)
    with patch("httpx.AsyncClient", side_effect=AssertionError("Deferred API grant probe")):
        report = await plugin.check_keyword_search_access(query)
    assert report["status"] == "UNAVAILABLE" and report["reason_code"] == "HOST_BROWSER_REQUIRED"
    assert report["recommended_path"] == 'prepare_host_browser_search(source="threads")'
    manager.get_access_token.assert_not_awaited()
    manager.record_keyword_search_verdict.assert_not_awaited()
