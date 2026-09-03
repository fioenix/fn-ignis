import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin

IG_MEDIA_RESPONSE = {
    "data": [
        {
            "id": "1789000001",
            "caption": "Top xu hướng thời trang mùa thu 2026 #fashion #style",
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "permalink": "https://www.instagram.com/reel/C71abcDEF/",
            "timestamp": "2026-09-01T09:15:00+0000",
            "like_count": 67000,
            "comments_count": 2100,
            "username": "fashion_trend_vn",
        },
        {
            "id": "1789000002",
            "caption": "Ảnh feed thường, không phải Reel",
            "media_type": "IMAGE",
            "media_product_type": "FEED",
            "permalink": "https://www.instagram.com/p/C71abcXYZ/",
            "timestamp": "2026-09-02T02:00:00+0000",
            "like_count": 120,
            "comments_count": 4,
            "username": "fashion_trend_vn",
        },
    ]
}

IG_INSIGHTS = {
    "1789000001": {
        "data": [
            {"name": "plays", "values": [{"value": 890000}]},
            {"name": "reach", "values": [{"value": 512000}]},
            {"name": "total_interactions", "values": [{"value": 69300}]},
        ]
    }
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


def _auth_manager(token: str | None = "IG_LONG_LIVED_TOKEN") -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_access_token.return_value = token
    return mgr


def _plugin(token: str | None = "IG_LONG_LIVED_TOKEN", ig_user_id: str = "17841400000000000") -> ReelsPlugin:
    return ReelsPlugin(auth_manager=_auth_manager(token), ig_user_id=ig_user_id)


def _route(media_payload=None, top_media_payload=None, hashtag_id: str = "1789099999"):
    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            media_id = url.rsplit("/", 2)[-2]
            return _resp(200, IG_INSIGHTS.get(media_id, {"data": []}))
        if "ig_hashtag_search" in url:
            return _resp(200, {"data": [{"id": hashtag_id}]})
        if "/top_media" in url:
            return _resp(200, top_media_payload if top_media_payload is not None else {"data": []})
        return _resp(200, media_payload if media_payload is not None else {"data": []})

    return _get


# --- Graph API ingress ---


@pytest.mark.asyncio
async def test_fetch_signals_extracts_reel_engagement_metrics():
    plugin = _plugin()

    with patch("httpx.AsyncClient.get", side_effect=_route(media_payload=IG_MEDIA_RESPONSE)):
        signals = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=30)

    # The non-Reel FEED image must be filtered out.
    assert len(signals) == 1
    s = signals[0]
    assert s.platform == PlatformType.REELS
    assert "Top xu hướng thời trang" in s.raw_title
    assert s.metric_value == 890000.0
    assert s.source_url == "https://www.instagram.com/reel/C71abcDEF/"
    assert s.metadata["play_count"] == 890000
    assert s.metadata["like_count"] == 67000
    assert s.metadata["comment_count"] == 2100
    assert s.metadata["reach"] == 512000
    assert s.metadata["caption"].startswith("Top xu hướng")
    assert s.metadata["published_at"] == "2026-09-01T09:15:00+00:00"
    assert s.metadata["source"] == "instagram_graph_api"


@pytest.mark.asyncio
async def test_fetch_signals_sends_window_and_account_scoped_url():
    plugin = _plugin()
    captured = {"url": None, "params": None}

    async def _get(url, params=None, **kwargs):
        if "/media" in url:
            captured["url"] = url
            captured["params"] = params
        return _resp(200, {"data": []})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        await plugin.fetch_signals(timeframe=Timeframe.LAST_24H)

    assert "17841400000000000/media" in captured["url"]
    assert captured["params"]["access_token"] == "IG_LONG_LIVED_TOKEN"
    window_days = (int(captured["params"]["until"]) - int(captured["params"]["since"])) / 86400
    assert 0.9 < window_days < 1.1


@pytest.mark.asyncio
async def test_search_signals_resolves_hashtag_then_reads_top_media():
    plugin = _plugin()
    hashtag_queries = []

    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            media_id = url.rsplit("/", 2)[-2]
            return _resp(200, IG_INSIGHTS.get(media_id, {"data": []}))
        if "ig_hashtag_search" in url:
            hashtag_queries.append(params["q"])
            return _resp(200, {"data": [{"id": "1789099999"}]})
        if "/top_media" in url:
            return _resp(200, {"data": [IG_MEDIA_RESPONSE["data"][0]]})
        return _resp(200, {"data": []})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        signals = await plugin.search_signals(keywords=["thời trang thu"], geo=GeoCode.VN)

    # Instagram hashtag search takes a single alphanumeric token.
    assert hashtag_queries == ["thờitrangthu"]
    assert len(signals) == 1
    assert signals[0].metadata["matched_keyword"] == "thời trang thu"


@pytest.mark.asyncio
async def test_search_skips_keyword_when_hashtag_is_unknown():
    plugin = _plugin()

    async def _get(url, params=None, **kwargs):
        if "ig_hashtag_search" in url:
            return _resp(200, {"data": []})
        return _resp(200, {"data": []})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        assert await plugin.search_signals(keywords=["từkhóalạ"]) == []


@pytest.mark.asyncio
async def test_metric_falls_back_to_likes_without_insights_scope():
    plugin = _plugin()

    async def _get(url, params=None, **kwargs):
        if "/insights" in url:
            return _resp(400, {"error": {"message": "insights permission required"}})
        return _resp(200, {"data": [IG_MEDIA_RESPONSE["data"][0]]})

    with patch("httpx.AsyncClient.get", side_effect=_get):
        signals = await plugin.fetch_signals()

    assert signals[0].metric_value == 67000.0
    assert signals[0].metadata["play_count"] == 0


# --- Credential and soft-block handling ---


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_invalid_token_raises_and_audits(status):
    auth_mgr = _auth_manager()
    plugin = ReelsPlugin(auth_manager=auth_mgr, ig_user_id="17841400000000000")

    with patch("httpx.AsyncClient.get", return_value=_resp(status, {"error": {"message": "Invalid OAuth access token"}})):
        with pytest.raises(ConnectorAuthenticationException, match=f"HTTP {status}"):
            await plugin.fetch_signals()

    assert auth_mgr.record_api_failure.await_args.args[0] == status


@pytest.mark.asyncio
async def test_rate_limit_raises_quota_exception():
    plugin = _plugin()

    with patch("httpx.AsyncClient.get", return_value=_resp(429, {"error": {"message": "limit reached"}})):
        with pytest.raises(ConnectorQuotaExceededException, match="429"):
            await plugin.fetch_signals()


@pytest.mark.asyncio
async def test_missing_ig_user_id_raises_before_any_request():
    plugin = ReelsPlugin(auth_manager=_auth_manager(), ig_user_id="")

    with patch("httpx.AsyncClient.get") as mock_get:
        with pytest.raises(ConnectorAuthenticationException, match="INSTAGRAM_USER_ID"):
            await plugin.fetch_signals()

    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_unauthenticated_oauth_connector_is_not_reported_healthy():
    assert await _plugin(token=None).is_healthy() is False
    assert await _plugin().is_healthy() is True


# --- Legacy unauthenticated fallback stays intact ---


@pytest.mark.asyncio
async def test_plugin_without_auth_manager_uses_public_clips_fallback():
    plugin = ReelsPlugin()
    legacy_payload = {
        "items": [
            {
                "id": "reel_998877",
                "code": "C71abcDEF",
                "caption": {"text": "Top xu hướng thời trang mùa thu 2026 #fashion #style"},
                "play_count": 890000,
                "like_count": 67000,
                "comment_count": 2100,
                "user": {"username": "fashion_trend_vn"},
                "music_metadata": {"music_title": "Trending Beat Vol 4"},
            }
        ]
    }

    with patch("httpx.AsyncClient.get", return_value=_resp(200, legacy_payload)):
        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)

    assert len(signals) == 1
    assert signals[0].metric_value == 890000.0
    assert signals[0].metadata["play_count"] == 890000
    assert signals[0].metadata["comment_count"] == 2100
    assert signals[0].metadata["music_title"] == "Trending Beat Vol 4"
    assert signals[0].metadata["source"] == "instagram_public_clips"
