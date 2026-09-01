import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.interfaces.mcp.server import handle_get_tiktok_search_suggestions


@pytest.mark.asyncio
async def test_tiktok_plugin_fetch_suggestions_mocked():
    mock_auth = AsyncMock()
    mock_auth.get_storage_state.return_value = {"cookies": []}

    plugin = TikTokPlugin(auth_manager=mock_auth)

    with patch("playwright.async_api.async_playwright") as mock_playwright:
        mock_p = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_playwright.return_value.__aenter__.return_value = mock_p
        mock_p.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_card = AsyncMock()
        mock_card.query_selector.return_value = None
        mock_card.inner_text.return_value = "#xiaozhi #chatbotai #aiagents"
        mock_page.query_selector_all.return_value = [mock_card]

        suggestions = await plugin.fetch_suggestions(keywords=["ai agent"], geo=GeoCode.VN)
        assert len(suggestions) == 1
        assert suggestions[0]["keyword"] == "ai agent"
        assert suggestions[0]["platform"] == "tiktok"
        assert len(suggestions[0]["suggestions"]) >= 1


@pytest.mark.asyncio
async def test_handle_get_tiktok_search_suggestions():
    mock_comp = {
        "registry": AsyncMock(),
    }
    mock_comp["registry"].fetch_suggestions_across_all.return_value = [
        {
            "keyword": "ai agent",
            "platform": "tiktok",
            "suggestions_count": 2,
            "suggestions": [
                {"query": "Trend Character Ai", "type": "search_guide"},
                {"query": "#xiaozhi", "type": "trending_hashtag"},
            ]
        }
    ]

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        resp_json = await handle_get_tiktok_search_suggestions(keywords=["ai agent"], geo="VN")
        resp = json.loads(resp_json)
        assert resp["status"] == "SUCCESS"
        assert resp["total_keywords"] == 1
        assert len(resp["data"]) == 1
        assert resp["data"][0]["suggestions"][0]["query"] == "Trend Character Ai"
