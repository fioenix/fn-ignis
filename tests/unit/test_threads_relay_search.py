"""Exercise the actual page-side Relay projection without any live account traffic."""
import copy
import json
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.infrastructure.connectors import meta_browser_ingress as ingress
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

PUBLIC_RESULT = {"data": {"searchResults": {"edges": []}}}


def relay_scripts():
    return [
        {"require": [["bootstrap", "init", [], [{"expectedPreloaders": [
            {"queryName": "BarcelonaSearchResultsQuery", "preloaderID": "search-1", "variables": {"query": "retail"}},
            {"queryName": "BarcelonaSearchResultsViewerDataQuery", "preloaderID": "viewer-1", "variables": {}},
        ]}]]]},
        {"require": [["RelayPrefetchedStreamCache", "next", [], ["search-1", {
            "__bbox": {"complete": True, "result": copy.deepcopy(PUBLIC_RESULT)},
        }]]]},
    ]


@pytest.mark.parametrize("mutation,accepted", [
    ("valid", True), ("wrong_query", False), ("wrong_preloader", False),
    ("viewer", False), ("incomplete", False), ("error", False), ("malformed", False),
])
def test_page_projection_requires_exact_complete_public_search_preloader(mutation, accepted):
    """Unbound Relay stream admission or removal of any proof check must fail this test."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute the actual page-side JavaScript")
    scripts = relay_scripts()
    expected = scripts[0]["require"][0][3][0]["expectedPreloaders"][0]
    args = scripts[1]["require"][0][3]
    if mutation == "wrong_query":
        expected["variables"]["query"] = "other"
    elif mutation == "wrong_preloader":
        args[0] = "foreign-result"
    elif mutation == "viewer":
        expected["queryName"] = "BarcelonaSearchResultsViewerDataQuery"
    elif mutation == "incomplete":
        args[1]["__bbox"]["complete"] = False
    elif mutation == "error":
        args[1]["__bbox"]["result"]["errors"] = [{"message": "failed"}]
    elif mutation == "malformed":
        args[1] = None
    # Unmatched background results must not leave the page, even when shaped like public posts.
    scripts.append({"require": [["RelayPrefetchedStreamCache", "next", [], ["viewer-1", {
        "__bbox": {"complete": True, "result": {"data": {"private": "not-returned"}}},
    }]]]})
    elements = [{"textContent": json.dumps(script)} for script in scripts]
    elements.append({"textContent": "not JSON"})
    source = getattr(ingress, "THREADS_SEARCH_RELAY_EXTRACTOR", "() => []")
    code = f"const project = ({source}); process.stdout.write(JSON.stringify(project({json.dumps(elements)}, 'retail')));"
    result = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout) == ([PUBLIC_RESULT] if accepted else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("status,request_url,accepted", [
    (200, "https://www.threads.com/search?q=retail", True),
    (500, "https://www.threads.com/search?q=retail", False),
    (200, "https://www.threads.com/search?q=other", False),
    (200, "https://example.com/search?q=retail", False),
])
async def test_scoped_capture_admits_relay_only_after_exact_successful_navigation(status, request_url, accepted):
    page = AsyncMock()
    page.on = MagicMock()
    page.goto.return_value = MagicMock(status=status, request=MagicMock(url=request_url))
    page.url = request_url
    page.locator = MagicMock(return_value=MagicMock(evaluate_all=AsyncMock(return_value=[PUBLIC_RESULT])))
    browser = AsyncMock()
    browser.new_context.return_value.new_page.return_value = page
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=playwright)
    manager.__aexit__ = AsyncMock(return_value=None)
    with patch("playwright.async_api.async_playwright", return_value=manager):
        results = await ingress.collect_json_payloads(
            "https://www.threads.com/search?q=retail", {}, ["/api/graphql"], scrolls=0,
            expected_query="retail", payload_validator=ThreadsPlugin._public_search_results,
        )
    assert results == ([PUBLIC_RESULT] if accepted else [])
