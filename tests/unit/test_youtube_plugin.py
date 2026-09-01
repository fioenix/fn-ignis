import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock
import httpx


from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.domain.exceptions import ConnectorQuotaExceededException, ConnectorExecutionException
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin


SAMPLE_YOUTUBE_API_RESPONSE = {
    "items": [
        {
            "id": "vid_abc123",
            "snippet": {
                "publishedAt": "2026-08-30T10:00:00Z",
                "channelId": "chan_xyz",
                "title": "MV Ca Nhạc Mới Nhất 2026",
                "description": "Video ca nhạc chính thức",
                "channelTitle": "Artist Official",
                "tags": ["nhac tre", "vpop", "trending"],
                "categoryId": "10"
            },
            "statistics": {
                "viewCount": "2500000",
                "likeCount": "180000",
                "commentCount": "12000"
            }
        }
    ]
}


@pytest.mark.asyncio
async def test_youtube_plugin_parse_signals():
    plugin = YouTubeDataPlugin(api_key="mock_key_123")
    assert plugin.platform == PlatformType.YOUTUBE
    assert plugin.name == "YouTube Data API v3"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_YOUTUBE_API_RESPONSE
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)

        assert len(signals) == 1
        s = signals[0]
        assert s.platform == PlatformType.YOUTUBE
        assert s.raw_title == "MV Ca Nhạc Mới Nhất 2026"
        assert s.metric_value == 2500000.0
        assert s.source_url == "https://www.youtube.com/watch?v=vid_abc123"
        assert s.metadata["channel_title"] == "Artist Official"
        assert s.metadata["likes"] == 180000
        assert s.metadata["comments"] == 12000
        assert "vpop" in s.metadata["tags"]


@pytest.mark.asyncio
async def test_youtube_plugin_quota_exceeded():
    plugin = YouTubeDataPlugin(api_key="mock_key_123")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.json.return_value = {
            "error": {
                "errors": [{"reason": "quotaExceeded"}],
                "message": "The request cannot be completed because you have exceeded your quota."
            }
        }
        mock_get.return_value = mock_response

        with pytest.raises(ConnectorQuotaExceededException):
            await plugin.fetch_signals(geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_youtube_plugin_is_healthy():
    plugin_no_key = YouTubeDataPlugin(api_key="")
    assert await plugin_no_key.is_healthy() is False

    plugin_with_key = YouTubeDataPlugin(api_key="valid_key")
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert await plugin_with_key.is_healthy() is True


@pytest.mark.asyncio
async def test_youtube_search_ttl_caching():
    plugin = YouTubeDataPlugin(api_key="mock_key_123")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    search_response = {
        "items": [
            {
                "id": {"videoId": "cached_vid_1"},
                "snippet": {
                    "publishedAt": now_iso,
                    "channelId": "chan_cached",
                    "title": "Tutorial AI Agent n8n Automation",
                    "channelTitle": "AI Tutor",
                }
            }
        ]
    }
    video_details_response = {
        "items": [
            {
                "id": "cached_vid_1",
                "snippet": {
                    "publishedAt": now_iso,
                    "title": "Tutorial AI Agent n8n Automation",
                    "channelTitle": "AI Tutor",
                    "channelId": "chan_cached",
                },
                "statistics": {
                    "viewCount": "15000",
                    "likeCount": "800",
                    "commentCount": "50",
                }
            }
        ]
    }


    with patch("httpx.AsyncClient.get") as mock_get:
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.json.return_value = search_response

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.json.return_value = video_details_response

        mock_get.side_effect = [resp1, resp2]

        # Call 1: Fetches from API (2 HTTP requests: search.list + videos.list)
        signals_1 = await plugin.search_signals(keywords=["n8n test cache"], geo=GeoCode.VN)
        assert len(signals_1) == 1
        assert signals_1[0].raw_title == "Tutorial AI Agent n8n Automation"
        assert mock_get.call_count == 2

        # Call 2: Must be retrieved from TTLCache without any HTTP request
        signals_2 = await plugin.search_signals(keywords=["n8n test cache"], geo=GeoCode.VN)
        assert len(signals_2) == 1
        assert signals_2[0].raw_title == "Tutorial AI Agent n8n Automation"
        # call_count remains 2 (0 new network calls, quota preserved!)
        assert mock_get.call_count == 2

