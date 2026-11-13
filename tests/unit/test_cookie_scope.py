"""Browser cookies must retain their scope at every manual HTTP boundary."""

from unittest.mock import AsyncMock

import httpx
import pytest

from ignis.infrastructure.connectors import meta_browser_ingress
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


def cookie(name, value, domain, **overrides):
    return {
        "name": name, "value": value, "domain": domain, "path": "/",
        "secure": True, "expires": -1, "httpOnly": True, "sameSite": "Lax",
        **overrides,
    }


@pytest.fixture
def requests(monkeypatch):
    captured = []
    client_type = httpx.AsyncClient

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    def client(**kwargs):
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    return captured


@pytest.mark.parametrize("domain,path,url,expected", [
    ("threads.com", "/", "https://threads.com/", "token=value"),
    ("threads.com", "/", "https://www.threads.com/", ""),
    (".threads.com", "/", "https://www.threads.com/", "token=value"),
    (".threads.com", "/", "https://notthreads.com/", ""),
    (".threads.com", "/", "https://threads.com.evil.test/", ""),
    (".threads.com", "/api", "https://www.threads.com/api/graphql", "token=value"),
    (".threads.com", "/api", "https://www.threads.com/apiculture", ""),
    (".threads.com", "/api", "https://www.threads.com/api", "token=value"),
    (".threads.com", "/api/", "https://www.threads.com/api", ""),
    (".threads.net", "/", "https://www.threads.net/api/graphql", "token=value"),
    (".threads.com", "/api", "https://www.threads.com/api/../outside", ""),
    (".threads.com", "/api", "https://www.threads.com/outside/../api/graphql", "token=value"),
])
def test_cookie_host_and_path_boundaries(domain, path, url, expected):
    state = {"cookies": [cookie("token", "value", domain, path=path)]}
    assert meta_browser_ingress.build_cookie_header(state, url) == expected


@pytest.mark.parametrize("overrides,expected", [
    ({"secure": False}, "token=value"),
    ({"secure": True}, ""),
    ({"secure": False, "expires": 1}, ""),
    ({"secure": False, "expires": 4102444800}, "token=value"),
    ({"secure": False, "value": ""}, "token="),
    ({"secure": False, "value": "value; other=secret"}, ""),
    ({"secure": False, "value": "value\r\nInjected: secret"}, ""),
    ({"secure": False, "name": "token; injected"}, ""),
    ({"secure": False, "path": "api"}, ""),
    ({"secure": False, "expires": None}, ""),
    ({"secure": False, "expires": float("nan")}, ""),
    ({"secure": False, "partitionKey": "https://other.test"}, ""),
])
def test_cookie_transport_expiry_and_malformed_state(overrides, expected):
    state = {"cookies": [{**cookie("token", "value", ".threads.com"), **overrides}]}
    assert meta_browser_ingress.build_cookie_header(state, "http://www.threads.com/api") == expected


def test_csrf_uses_longest_eligible_path_and_ignores_foreign_tokens():
    state = {"cookies": [
        cookie("csrftoken", "foreign", ".google.com"),
        cookie("csrftoken", "root", ".threads.com"),
        cookie("csrftoken", "scoped", ".threads.com", path="/api"),
    ]}
    assert meta_browser_ingress.extract_token_from_storage(
        state, "csrftoken", "https://www.threads.com/api/graphql") == "scoped"


@pytest.mark.asyncio
async def test_threads_health_refuses_without_sending_cookies(requests, monkeypatch):
    domain = ".threads.com"
    state = {"cookies": [
        cookie("sessionid", "allowed", domain),
        cookie("SID", "foreign", ".google.com"),
        cookie("restricted", "wrong-path", domain, path="/restricted"),
        cookie("expired", "old", domain, expires=1),
        {"name": "unknown", "value": "unscoped"},
    ]}
    plugin = ThreadsPlugin()
    plugin._browser_auth_manager = AsyncMock()
    plugin._browser_storage_state = AsyncMock(return_value=state)
    assert await plugin.is_healthy() is False
    assert requests == []


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://www.threads.com/api/graphql", "https://www.threads.net/api/graphql",
    "http://www.threads.com/api/graphql", "https://www.threads.com.evil.test/api/graphql",
    "https://www.threads.com/api/../outside"])
async def test_retired_cookie_graphql_cannot_send_cookies_or_follow_redirects(url, requests):
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
        await meta_browser_ingress.fetch_graphql_direct("123", {}, {"cookies": [
            cookie("sessionid", "allowed", ".threads.com"), cookie("csrftoken", "local", ".threads.com")]}, url=url)
    assert requests == []
