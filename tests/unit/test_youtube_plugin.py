import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import httpx

from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.domain.exceptions import (
    ConnectorExecutionException,
    ConnectorQuotaExceededException,
)
from ignis.infrastructure.connectors.youtube import youtube_plugin as youtube_plugin_module
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



# --- the keyword search path and the failure contract -------------------------------------------
#
# SC-004 promises coverage for this plugin. What was tested was the trending-feed happy path and
# one quota case; what a research mission actually calls is `search_signals`, whose two-call
# search.list -> videos.list shape, timeframe cutoff and error handling were untested. A
# `search.list` costs 100 quota units against a 10,000-unit day, so the behaviour that decides how
# often it is called is not an implementation detail.


def _json_response(payload, status_code=200, content_type="application/json"):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.json = MagicMock(return_value=payload)
    response.raise_for_status = MagicMock()
    return response


def _search_list(video_ids):
    return {"items": [{"id": {"videoId": v}} for v in video_ids]}


def _videos_list(entries):
    """entries: (video_id, title, views, published_at_iso)."""
    return {
        "items": [
            {
                "id": video_id,
                "snippet": {
                    "title": title,
                    "channelId": f"chan_{video_id}",
                    "channelTitle": "A Channel",
                    "publishedAt": published_at,
                },
                "statistics": {"viewCount": str(views), "likeCount": "1", "commentCount": "2"},
            }
            for video_id, title, views, published_at in entries
        ]
    }


def _recent(hours_ago=2):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture(autouse=True)
def _clear_youtube_query_cache():
    """The query cache is module state with a TTL, so one test's result would answer the next."""
    youtube_plugin_module._YOUTUBE_QUERY_CACHE.clear()
    yield
    youtube_plugin_module._YOUTUBE_QUERY_CACHE.clear()


@pytest.mark.asyncio
async def test_search_signals_reads_metrics_from_the_videos_call_not_the_search_call():
    """search.list returns no statistics, so a signal built from it alone would carry no metrics."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    published = _recent(hours_ago=10)

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [
            _json_response(_search_list(["vid_1", "vid_2"])),
            _json_response(
                _videos_list(
                    [
                        ("vid_1", "Review máy lọc nước", 120_000, published),
                        ("vid_2", "Unboxing máy lọc nước", 60_000, published),
                    ]
                )
            ),
        ]

        signals = await plugin.search_signals(["máy lọc nước"], geo=GeoCode.VN, limit=5)

    assert [s.metadata["video_id"] for s in signals] == ["vid_1", "vid_2"]
    assert signals[0].metric_value == 120_000.0
    assert signals[0].metadata["views"] == 120_000
    assert signals[0].metadata["likes"] == 1
    assert signals[0].metadata["comments"] == 2
    assert signals[0].metadata["keyword"] == "máy lọc nước"
    assert signals[0].source_url == "https://www.youtube.com/watch?v=vid_1"
    assert signals[0].growth_velocity > 0, "velocity is views per hour since publication"
    assert mock_get.call_count == 2, "one search.list and one batched videos.list, not one per id"


@pytest.mark.asyncio
async def test_a_video_older_than_the_requested_window_is_dropped():
    """publishedAfter is sent to the API, and enforced again here because the API honours it loosely.

    Without the second check a 24-hour mission can return a video from last year and report it as
    current demand.
    """
    plugin = YouTubeDataPlugin(api_key="test_key")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [
            _json_response(_search_list(["fresh", "stale"])),
            _json_response(
                _videos_list(
                    [
                        ("fresh", "Fresh upload", 10_000, _recent(hours_ago=3)),
                        ("stale", "Two years old", 9_000_000, "2024-01-01T00:00:00Z"),
                    ]
                )
            ),
        ]

        signals = await plugin.search_signals(
            ["đánh giá"], geo=GeoCode.VN, timeframe=Timeframe.LAST_24H
        )

    assert [s.metadata["video_id"] for s in signals] == ["fresh"]


@pytest.mark.asyncio
async def test_a_title_too_short_to_be_a_topic_is_dropped():
    plugin = YouTubeDataPlugin(api_key="test_key")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [
            _json_response(_search_list(["ok", "junk"])),
            _json_response(
                _videos_list(
                    [
                        ("ok", "A usable title", 500, _recent()),
                        ("junk", " x ", 900_000, _recent()),
                    ]
                )
            ),
        ]

        signals = await plugin.search_signals(["x"], geo=GeoCode.VN)

    assert [s.metadata["video_id"] for s in signals] == ["ok"]
    assert plugin._is_garbage("") is True
    assert plugin._is_garbage("  a ") is True
    assert plugin._is_garbage("a real title") is False


@pytest.mark.asyncio
async def test_the_same_video_returned_for_two_keywords_is_emitted_once():
    """Two keywords in one mission overlap often; the corpus must not double-count the overlap."""
    plugin = YouTubeDataPlugin(api_key="test_key")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [
            _json_response(_search_list(["shared"])),
            _json_response(_videos_list([("shared", "Shared video", 1_000, _recent())])),
            _json_response(_search_list(["shared"])),
        ]

        signals = await plugin.search_signals(["first", "second"], geo=GeoCode.VN)

    assert [s.metadata["video_id"] for s in signals] == ["shared"]


@pytest.mark.asyncio
async def test_a_search_quota_refusal_propagates_so_the_breaker_can_trip():
    """Swallowing this would keep spending a 100-unit call against an exhausted daily quota."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    refusal = _json_response(
        {"error": {"errors": [{"reason": "quotaExceeded"}]}}, status_code=403
    )

    with patch("httpx.AsyncClient.get", return_value=refusal):
        with pytest.raises(ConnectorQuotaExceededException):
            await plugin.search_signals(["anything"], geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_a_rate_limit_status_is_treated_as_quota_whatever_the_body_says():
    """429 carries no reason code, and retrying it immediately is the behaviour to avoid."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    throttled = _json_response({}, status_code=429, content_type="text/html")

    with patch("httpx.AsyncClient.get", return_value=throttled):
        with pytest.raises(ConnectorQuotaExceededException):
            await plugin.search_signals(["anything"], geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_a_transport_failure_on_one_keyword_does_not_lose_the_others():
    """FR: one failing source must not stop the pass. Only a quota refusal is allowed to."""
    plugin = YouTubeDataPlugin(api_key="test_key")

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.side_effect = [
            httpx.ConnectError("Network down"),
            _json_response(_search_list(["vid_ok"])),
            _json_response(_videos_list([("vid_ok", "Survived", 42, _recent())])),
        ]

        signals = await plugin.search_signals(["broken", "working"], geo=GeoCode.VN)

    assert [s.metadata["video_id"] for s in signals] == ["vid_ok"]


@pytest.mark.asyncio
async def test_search_without_an_api_key_returns_nothing_rather_than_calling_the_api():
    """The trending feed raises on a missing key; search returns empty, and both are deliberate."""
    plugin = YouTubeDataPlugin(api_key="")

    with patch("httpx.AsyncClient.get") as mock_get:
        assert await plugin.search_signals(["anything"]) == []

    assert mock_get.call_count == 0


@pytest.mark.asyncio
async def test_the_trending_feed_without_an_api_key_is_a_connector_failure():
    plugin = YouTubeDataPlugin(api_key="")
    with pytest.raises(ConnectorExecutionException):
        await plugin.fetch_signals(geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_a_403_that_is_not_about_quota_is_reported_as_an_ordinary_failure():
    """A disabled key and an exhausted quota need different responses, so they are different types."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    forbidden = _json_response(
        {"error": {"message": "API key not valid", "errors": [{"reason": "forbidden"}]}},
        status_code=403,
    )

    with patch("httpx.AsyncClient.get", return_value=forbidden):
        with pytest.raises(ConnectorExecutionException) as caught:
            await plugin.fetch_signals(geo=GeoCode.VN)

    assert not isinstance(caught.value, ConnectorQuotaExceededException)
    assert "API key not valid" in str(caught.value)


@pytest.mark.asyncio
async def test_a_transport_failure_on_the_trending_feed_is_a_connector_failure():
    plugin = YouTubeDataPlugin(api_key="test_key")
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network down")):
        with pytest.raises(ConnectorExecutionException):
            await plugin.fetch_signals(geo=GeoCode.VN)


@pytest.mark.asyncio
async def test_a_failing_health_check_reports_unhealthy_rather_than_raising():
    plugin = YouTubeDataPlugin(api_key="test_key")
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network down")):
        assert await plugin.is_healthy() is False


# --- geo and timeframe translation --------------------------------------------------------------


def test_a_global_request_falls_back_to_a_region_the_api_accepts():
    """`chart=mostPopular` requires a regionCode; GLOBAL is not one."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    assert plugin._geo_to_region_code(GeoCode.GLOBAL) == "US"
    assert plugin._geo_to_region_code(GeoCode.VN) == "VN"


def test_relevance_language_is_set_only_where_the_mapping_knows_one():
    """Sending a wrong language narrows the result set, so an unknown geo sends none at all."""
    plugin = YouTubeDataPlugin(api_key="test_key")
    assert plugin._geo_to_relevance_language(GeoCode.VN) == "vi"
    assert plugin._geo_to_relevance_language(GeoCode.JP) == "ja"
    assert plugin._geo_to_relevance_language(GeoCode.BR) is None


@pytest.mark.parametrize(
    "requested,expected_days",
    [
        ("24h", 1),
        ("1d", 1),
        ("last_24h", 1),
        ("7d", 7),
        ("last_7d", 7),
        ("30d", 30),
        ("1m", 30),
        ("last_30d", 30),
        ("90d", 90),
        ("3m", 90),
        ("12m", 365),
        ("1y", 365),
        # Unrecognized input must still produce a cutoff rather than raise: anything naming 90
        # lands on the quarter, everything else on the week.
        ("last 90 days", 90),
        ("whenever", 7),
    ],
)
def test_every_timeframe_alias_produces_the_documented_cutoff(requested, expected_days):
    plugin = YouTubeDataPlugin(api_key="test_key")
    formatted, cutoff = plugin._timeframe_to_published_after(requested)

    elapsed_days = (datetime.now(timezone.utc) - cutoff).total_seconds() / 86400.0
    assert abs(elapsed_days - expected_days) < 0.01
    # RFC 3339 in UTC, which is the only form the API accepts.
    assert formatted.endswith("Z")
    assert datetime.strptime(formatted, "%Y-%m-%dT%H:%M:%SZ")
