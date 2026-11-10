import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from ignis.domain.exceptions import ConnectorAuthenticationException
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin

SAMPLE_REELS_RESPONSE = {
    "items": [
        {
            "id": "reel_998877",
            "code": "C71abcDEF",
            "caption": {"text": "Top xu hướng thời trang mùa thu 2026 #fashion #style"},
            "play_count": 890000,
            "like_count": 67000,
            "comment_count": 2100,
            "user": {"username": "fashion_trend_vn"},
            "music_metadata": {"music_title": "Trending Beat Vol 4"}
        }
    ]
}


@pytest.mark.asyncio
async def test_missing_token_does_not_offer_a_removed_authentication_tool(monkeypatch):
    plugin = ReelsPlugin()
    monkeypatch.setattr(plugin, "resolve_auth_tier", AsyncMock(return_value=(None, None)))

    with pytest.raises(ConnectorAuthenticationException) as error:
        await plugin._require_token()

    assert "No valid Instagram credentials" in str(error.value)
    assert "authenticate_instagram" not in str(error.value)

@pytest.mark.asyncio
async def test_reels_plugin_fetch():
    plugin = ReelsPlugin()
    assert plugin.platform == PlatformType.REELS
    assert plugin.name == "Instagram Reels Trending"

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SAMPLE_REELS_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10, scope=IngressScope.OWN_PROFILE)
        assert len(signals) == 1
        s = signals[0]
        assert s.platform == PlatformType.REELS
        assert "Top xu hướng thời trang" in s.raw_title
        assert s.metric_value == 890000.0
        assert s.metadata["music_title"] == "Trending Beat Vol 4"
        assert s.source_url == "https://www.instagram.com/reel/C71abcDEF/"
