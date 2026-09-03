import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

THREADS_LIST_RESPONSE = {
    "data": [
        {
            "id": "17900000000001",
            "text": "Đội engineering của mình vừa migrate sang self-hosted MCP server, chi phí giảm 60%",
            "permalink": "https://www.threads.net/@fioenix/post/C9xYzAbc",
            "timestamp": "2026-09-01T04:30:00+0000",
            "username": "fioenix",
            "media_type": "TEXT_POST",
        },
        {
            "id": "17900000000002",
            "text": "Ai đang dùng AI coding assistant cho team 20+ dev? Review thật giúp mình với",
            "permalink": "https://www.threads.net/@tech_lead_hanoi/post/C9xYzDef",
            "timestamp": "2026-09-02T11:00:00+0000",
            "username": "tech_lead_hanoi",
            "media_type": "TEXT_POST",
        },
    ]
}

INSIGHTS_BY_ID = {
    "17900000000001": {
        "data": [
            {"name": "views", "total_value": {"value": 48200}},
            {"name": "likes", "total_value": {"value": 1310}},
            {"name": "replies", "total_value": {"value": 284}},
            {"name": "reposts", "total_value": {"value": 57}},
            {"name": "quotes", "total_value": {"value": 12}},
        ]
    },
    "17900000000002": {
        "data": [
            {"name": "views", "values": [{"value": 9100}]},
            {"name": "likes", "values": [{"value": 402}]},
            {"name": "replies", "values": [{"value": 96}]},
        ]
    },
}


def _resp(status_code: int, payload=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if payload is None:
        resp.json.side_effect = ValueError("no json")
        resp.text = "upstream error"
    else:
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    return resp


def _auth_manager(token: str | None = "LONG_LIVED_TOKEN") -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_access_token.return_value = token
    return mgr


def _route_graph(list_payload=None, search_payload=None):
    """Dispatch mocked httpx GETs by URL so list/search/insights each get the right body."""

    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            media_id = url.rsplit("/", 2)[-2]
            return _resp(200, INSIGHTS_BY_ID.get(media_id, {"data": []}))
        if "keyword_search" in url:
            return _resp(200, search_payload if search_payload is not None else {"data": []})
        return _resp(200, list_payload if list_payload is not None else {"data": []})

    return _get


# --- Ingress parsing ---


@pytest.mark.asyncio
async def test_fetch_signals_maps_graph_api_payload_to_trend_signals():
    plugin = ThreadsPlugin(auth_manager=_auth_manager())

    with patch("httpx.AsyncClient.get", side_effect=_route_graph(list_payload=THREADS_LIST_RESPONSE)):
        signals = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=25)

    assert len(signals) == 2
    first = signals[0]
    assert first.platform == PlatformType.THREADS
    assert "self-hosted MCP server" in first.raw_title
    # views/impressions is the primary demand metric
    assert first.metric_value == 48200.0
    assert first.source_url == "https://www.threads.net/@fioenix/post/C9xYzAbc"
    assert first.metadata["like_count"] == 1310
    assert first.metadata["reply_count"] == 284
    assert first.metadata["reposts"] == 57
    assert first.metadata["username"] == "fioenix"
    assert first.metadata["source"] == "threads_graph_api"

    # Timestamps are normalized to UTC ISO-8601 regardless of Meta's +0000 form.
    published = datetime.fromisoformat(first.metadata["published_at"])
    assert published.tzinfo is not None
    assert published.astimezone(timezone.utc).isoformat() == first.metadata["published_at"]

    # The legacy "values" insight shape must parse identically to "total_value".
    assert signals[1].metric_value == 9100.0
    assert signals[1].metadata["reply_count"] == 96


@pytest.mark.asyncio
async def test_fetch_signals_sends_timeframe_window_and_token():
    plugin = ThreadsPlugin(auth_manager=_auth_manager())
    captured = {}

    async def _get(url, params=None, **kwargs):
        if "/me/threads" in url:
            captured.update(params)
        return _resp(200, {"data": []})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        await plugin.fetch_signals(timeframe=Timeframe.LAST_30D, limit=40)

    assert captured["access_token"] == "LONG_LIVED_TOKEN"
    assert captured["limit"] == 40
    window_days = (int(captured["until"]) - int(captured["since"])) / 86400
    assert 29.9 < window_days < 30.1


@pytest.mark.asyncio
async def test_search_signals_probes_keyword_search_endpoint_per_keyword():
    plugin = ThreadsPlugin(auth_manager=_auth_manager())
    queries = []

    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            media_id = url.rsplit("/", 2)[-2]
            return _resp(200, INSIGHTS_BY_ID.get(media_id, {"data": []}))
        if "keyword_search" in url:
            queries.append(params["q"])
            return _resp(200, {"data": [THREADS_LIST_RESPONSE["data"][0]]})
        return _resp(200, {"data": []})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        signals = await plugin.search_signals(
            keywords=["MCP server", "  ", "AI coding assistant"],
            geo=GeoCode.VN,
            timeframe=Timeframe.LAST_7D,
        )

    assert queries == ["MCP server", "AI coding assistant"]
    # The same post returned for both keywords is de-duplicated by post id.
    assert len(signals) == 1
    assert signals[0].metadata["matched_keyword"] == "MCP server"


@pytest.mark.asyncio
async def test_metric_falls_back_to_likes_when_insights_scope_is_missing():
    plugin = ThreadsPlugin(auth_manager=_auth_manager())

    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            # Token lacks threads_manage_insights: Meta answers 400, not 401.
            return _resp(400, {"error": {"message": "insights permission required"}})
        return _resp(200, {"data": [THREADS_LIST_RESPONSE["data"][0]]})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        signals = await plugin.fetch_signals()

    assert len(signals) == 1
    assert signals[0].metric_value == 0.0
    assert signals[0].metadata["views"] == 0


# --- Soft-block handling: 401 / 403 / 429 ---


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_invalid_or_expired_token_raises_auth_exception_and_audits(status):
    auth_mgr = _auth_manager()
    plugin = ThreadsPlugin(auth_manager=auth_mgr)

    with patch("httpx.AsyncClient.get", return_value=_resp(status, {"error": {"message": "Invalid OAuth access token"}})):
        with pytest.raises(ConnectorAuthenticationException, match=f"HTTP {status}"):
            await plugin.fetch_signals()

    auth_mgr.record_api_failure.assert_awaited_once()
    assert auth_mgr.record_api_failure.await_args.args[0] == status


@pytest.mark.asyncio
async def test_rate_limit_raises_quota_exception_and_audits():
    auth_mgr = _auth_manager()
    plugin = ThreadsPlugin(auth_manager=auth_mgr)

    with patch("httpx.AsyncClient.get", return_value=_resp(429, {"error": {"message": "Application request limit reached"}})):
        with pytest.raises(ConnectorQuotaExceededException, match="429"):
            await plugin.fetch_signals()

    assert auth_mgr.record_api_failure.await_args.args[0] == 429


@pytest.mark.asyncio
async def test_missing_token_raises_instead_of_returning_empty():
    plugin = ThreadsPlugin(auth_manager=_auth_manager(token=None))

    with patch("httpx.AsyncClient.get") as mock_get:
        with pytest.raises(ConnectorAuthenticationException, match="authenticate_threads"):
            await plugin.fetch_signals()

    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_unauthenticated_oauth_connector_is_not_reported_healthy():
    assert await ThreadsPlugin(auth_manager=_auth_manager(token=None)).is_healthy() is False
    assert await ThreadsPlugin(auth_manager=_auth_manager()).is_healthy() is True


# --- Circuit breaker integration ---


@pytest.mark.asyncio
async def test_circuit_breaker_trips_after_repeated_meta_soft_blocks():
    repo = AsyncMock()
    registry = ConnectorPluginRegistry(repository=repo)
    plugin = ThreadsPlugin(auth_manager=_auth_manager())
    registry.register(plugin)

    with patch("httpx.AsyncClient.get", return_value=_resp(429, {"error": {"message": "rate limited"}})):
        for _ in range(3):
            signals = await registry.fetch_from_all(geo=GeoCode.VN, timeframe=Timeframe.LAST_24H)
            assert signals == []

    status = registry.get_health_status()[PlatformType.THREADS.value]
    assert status["circuit_state"] == "OPEN"
    assert status["consecutive_failures"] == 3

    # Once OPEN the registry stops calling the plugin at all.
    with patch("httpx.AsyncClient.get") as mock_get:
        await registry.fetch_from_all()
        mock_get.assert_not_called()

    events = [c.kwargs["event_type"] for c in repo.log_event.await_args_list]
    assert "INGRESS_FAILURE" in events
    assert "CIRCUIT_OPEN" in events


@pytest.mark.asyncio
async def test_expired_token_failure_is_never_reported_as_healthy_success():
    """A 401 must not be laundered into an empty-but-successful ingress."""
    repo = AsyncMock()
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(ThreadsPlugin(auth_manager=_auth_manager()))

    with patch("httpx.AsyncClient.get", return_value=_resp(401, {"error": {"message": "expired"}})):
        await registry.fetch_from_all()

    events = [c.kwargs["event_type"] for c in repo.log_event.await_args_list]
    assert "INGRESS_SUCCESS" not in events
    assert "INGRESS_FAILURE" in events


# --- Legacy unauthenticated fallback stays intact ---


@pytest.mark.asyncio
async def test_plugin_without_auth_manager_uses_public_fallback():
    plugin = ThreadsPlugin()
    legacy_payload = {
        "data": {
            "mediaData": [
                {
                    "id": "3344556677",
                    "caption": {"text": "Trải nghiệm dùng AI Coding Assistant hiệu quả cho CTO"},
                    "like_count": 3400,
                    "reply_count": 280,
                    "user": {"username": "tech_lead_hanoi"},
                    "code": "C9xYzAbc",
                }
            ]
        }
    }

    with patch("httpx.AsyncClient.get", return_value=_resp(200, legacy_payload)):
        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)

    assert len(signals) == 1
    assert signals[0].metric_value == 3400.0
    assert signals[0].metadata["source"] == "threads_public_trending"
    assert await plugin.is_healthy() is True
