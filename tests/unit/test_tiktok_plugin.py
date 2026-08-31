import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin

SAMPLE_TIKTOK_ITEM = {
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
    }
}

@pytest.mark.asyncio
async def test_tiktok_plugin_properties():
    plugin = TikTokPlugin()
    assert plugin.platform == PlatformType.TIKTOK
    assert "TikTok" in plugin.name
    assert await plugin.is_healthy() is True

@pytest.mark.asyncio
async def test_tiktok_plugin_parse_json_item():
    plugin = TikTokPlugin()
    signal = plugin._parse_json_item(SAMPLE_TIKTOK_ITEM, geo=GeoCode.VN, keyword="ai agent")
    assert signal is not None
    assert signal.platform == PlatformType.TIKTOK
    assert signal.raw_title == "#congnghe2026 AI Agent sieu hot"
    assert signal.metric_value == 450000.0
    assert signal.metadata["author"] == "tech_reviewer_vn"
    assert signal.metadata["likes"] == 35000
    assert signal.metadata["keyword"] == "ai agent"
    assert signal.source_url == "https://www.tiktok.com/@tech_reviewer_vn/video/718293849102"

@pytest.mark.asyncio
async def test_tiktok_plugin_parse_dom_card():
    plugin = TikTokPlugin()
    mock_card = AsyncMock()
    mock_link = AsyncMock()
    mock_link.get_attribute.return_value = "https://www.tiktok.com/@creator/video/12345"
    mock_card.query_selector.return_value = mock_link
    mock_card.inner_text.return_value = "1.5M\nAI Agent tu dong hoa quy trinh\n@creator"

    signal = await plugin._parse_dom_card(mock_card, geo=GeoCode.VN, keyword="ai")
    assert signal is not None
    assert signal.platform == PlatformType.TIKTOK
    assert signal.metric_value == 1500000.0
    assert "AI Agent tu dong hoa" in signal.raw_title
    assert signal.source_url == "https://www.tiktok.com/@creator/video/12345"

@pytest.mark.asyncio
async def test_tiktok_plugin_fetch_and_search_mocked():
    mock_auth = AsyncMock()
    mock_auth.get_storage_state.return_value = {"cookies": []}

    plugin = TikTokPlugin(auth_manager=mock_auth)
    
    with patch.object(plugin, "_fetch_via_playwright", new_callable=AsyncMock) as mock_fetch:
        mock_sig = MagicMock()
        mock_sig.platform = PlatformType.TIKTOK
        mock_fetch.return_value = [mock_sig]

        # Test fetch_signals
        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)
        assert len(signals) == 1
        assert signals[0].platform == PlatformType.TIKTOK

        # Test search_signals
        search_signals = await plugin.search_signals(keywords=["ai", "agent"], geo=GeoCode.VN)
        assert len(search_signals) == 2
