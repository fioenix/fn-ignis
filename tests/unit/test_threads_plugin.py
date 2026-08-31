import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

SAMPLE_THREADS_RESPONSE = {
    "data": {
        "mediaData": [
            {
                "id": "3344556677",
                "caption": {"text": "Trải nghiệm dùng AI Coding Assistant hiệu quả cho CTO"},
                "like_count": 3400,
                "reply_count": 280,
                "user": {"username": "tech_lead_hanoi"},
                "code": "C9xYzAbc"
            }
        ]
    }
}

@pytest.mark.asyncio
async def test_threads_plugin_fetch():
    plugin = ThreadsPlugin()
    assert plugin.platform == PlatformType.THREADS
    assert plugin.name == "Threads Trending Discussions"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_THREADS_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)
        assert len(signals) == 1
        s = signals[0]
        assert s.platform == PlatformType.THREADS
        assert "Trải nghiệm dùng AI Coding Assistant" in s.raw_title
        assert s.metric_value == 3400.0
        assert s.metadata["reply_count"] == 280
        assert s.source_url == "https://www.threads.net/@tech_lead_hanoi/post/C9xYzAbc"
