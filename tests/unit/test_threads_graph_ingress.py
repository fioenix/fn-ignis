"""Every retired internal Threads feed scope refuses before Graph or legacy collection."""
from unittest.mock import AsyncMock, patch

import pytest

from ignis.domain.value_objects import IngressScope
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", list(IngressScope))
async def test_retired_graph_feed_refuses_all_scopes_without_api_or_legacy_fallback(scope):
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    plugin = ThreadsPlugin(auth_manager=AsyncMock())
    with patch("httpx.AsyncClient", side_effect=AssertionError("Retired Graph request")):
        with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
            await plugin.fetch_signals(scope=scope)
    plugin._auth_manager.get_access_token.assert_not_awaited()
