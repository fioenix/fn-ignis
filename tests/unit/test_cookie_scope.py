"""Browser cookies must retain their scope at every manual HTTP boundary."""

from unittest.mock import AsyncMock

import httpx
import pytest

from ignis.infrastructure.connectors import browser_support, meta_browser_ingress
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok import tiktok_plugin


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
@pytest.mark.parametrize("platform", ["tiktok", "threads", "instagram"])
async def test_health_http_sends_only_eligible_cookies(platform, requests, monkeypatch):
    domain = f".{platform}.com"
    state = {"cookies": [
        cookie("sessionid", "allowed", domain),
        cookie("SID", "foreign", ".google.com"),
        cookie("restricted", "wrong-path", domain, path="/restricted"),
        cookie("expired", "old", domain, expires=1),
        {"name": "unknown", "value": "unscoped"},
    ]}
    if platform == "tiktok":
        monkeypatch.setattr(tiktok_plugin, "browser_launch_available", AsyncMock(return_value=True))
        plugin = tiktok_plugin.TikTokPlugin(auth_manager=AsyncMock())
        plugin._auth_manager.get_storage_state.return_value = state
    else:
        plugin = ThreadsPlugin() if platform == "threads" else ReelsPlugin()
        plugin._browser_auth_manager = AsyncMock()
        plugin._browser_storage_state = AsyncMock(return_value=state)
    assert await plugin.is_healthy() is True
    assert requests[0].headers["cookie"] == "sessionid=allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("url,expected", [
    ("https://www.threads.com/api/graphql", "sessionid=allowed; csrftoken=local"),
    ("https://www.threads.net/api/graphql", ""),
    ("http://www.threads.com/api/graphql", ""),
    ("https://www.threads.com.evil.test/api/graphql", ""),
])
async def test_graphql_scopes_cookie_and_csrf_to_resolved_url(url, expected, requests):
    state = {"cookies": [
        cookie("csrftoken", "foreign", ".google.com"),
        cookie("sessionid", "allowed", ".threads.com"),
        cookie("csrftoken", "local", ".threads.com"),
    ]}
    result = await meta_browser_ingress.fetch_graphql_direct("123", {}, state, url=url)
    if expected:
        assert result == {"data": {"ok": True}}
        assert requests[0].headers["cookie"] == expected
        assert requests[0].headers["x-csrftoken"] == "local"
    else:
        assert result is None
        assert requests == []


@pytest.mark.asyncio
async def test_graphql_redirect_does_not_forward_csrf(monkeypatch):
    captured = []
    client_type = httpx.AsyncClient

    def respond(request):
        captured.append(request)
        return httpx.Response(302, headers={"location": "https://other.test/"})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(respond), **kw))
    result = await meta_browser_ingress.fetch_graphql_direct("123", {}, {"cookies": [
        cookie("sessionid", "allowed", ".threads.com"),
        cookie("csrftoken", "local", ".threads.com"),
    ]}, url="https://www.threads.com/api/graphql")
    assert result is None
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_graphql_cookie_scope_uses_normalized_http_request_path(requests):
    result = await meta_browser_ingress.fetch_graphql_direct("123", {}, {"cookies": [
        cookie("csrftoken", "restricted", ".threads.com", path="/api"),
    ]}, url="https://www.threads.com/api/../outside")
    assert result is None
    assert requests == []


@pytest.mark.asyncio
async def test_public_surface_still_follows_redirects(monkeypatch):
    captured = []
    client_type = httpx.AsyncClient

    def respond(request):
        captured.append(request)
        return (httpx.Response(302, headers={"location": "/final"})
                if request.url.path == "/start" else httpx.Response(200))

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client_type(
        transport=httpx.MockTransport(respond), **kw))
    assert await browser_support.surface_reachable("https://public.test/start") is True
    assert [r.url.path for r in captured] == ["/start", "/final"]
