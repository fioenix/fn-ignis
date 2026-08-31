import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin

SAMPLE_TIKTOK_API_RESPONSE = {
    "data": {
        "list": [
            {
                "item_id": "718293849102",
                "title": "#congnghe2026 AI Agent sieu hot",
                "stats": {
                    "play_count": 450000,
                    "digg_count": 35000,
                    "comment_count": 1200,
                    "share_count": 500
                },
                "author": {
                    "unique_id": "tech_reviewer_vn",
                    "nickname": "Review Cong Nghe"
                },
                "hashtags": ["congnghe2026", "ai", "trend"]
            }
        ]
    }
}

@pytest.mark.asyncio
async def test_tiktok_plugin_fetch():
    plugin = TikTokPlugin()
    assert plugin.platform == PlatformType.TIKTOK
    assert plugin.name == "TikTok Trending Ingress"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_TIKTOK_API_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)
        assert len(signals) == 1
        s = signals[0]
        assert s.platform == PlatformType.TIKTOK
        assert "#congnghe2026" in s.raw_title
        assert s.metric_value == 450000.0
        assert s.metadata["author"] == "tech_reviewer_vn"
        assert "ai" in s.metadata["hashtags"]
