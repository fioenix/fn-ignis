"""Retired private Threads Relay/Playwright collection cannot bypass the host ticket."""
from unittest.mock import patch

import pytest

from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
from ignis.infrastructure.connectors import meta_browser_ingress as ingress


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["https://www.threads.com", "https://www.threads.net"])
@pytest.mark.parametrize("route", ["/", "/search?q=synthetic"])
async def test_retired_threads_page_capture_refuses_before_browser_or_request(origin, route):
    with patch("playwright.async_api.async_playwright", side_effect=AssertionError("Retired browser launched")), \
            patch("httpx.AsyncClient", side_effect=AssertionError("Retired HTTP dispatched")):
        with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
            await ingress.collect_json_payloads(origin + route, {"cookies": []}, ["/api/graphql"],
                                                expected_query="synthetic", payload_validator=lambda body: body)
    assert not hasattr(ingress, "THREADS_SEARCH_RELAY_EXTRACTOR")
    assert not hasattr(ingress, "collect_threads_search_suggestions_via_browser")
