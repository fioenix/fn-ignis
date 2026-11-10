import pytest
from unittest.mock import AsyncMock, patch
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin


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
        mock_page.on = lambda event, cb: None


        mock_card = AsyncMock()
        mock_card.query_selector.return_value = None
        mock_card.inner_text.return_value = "#xiaozhi #chatbotai #aiagents"
        mock_page.query_selector_all.return_value = [mock_card]

        suggestions = await plugin.fetch_suggestions(keywords=["ai agent"], geo=GeoCode.VN)
        assert len(suggestions) == 1
        assert suggestions[0]["keyword"] == "ai agent"
        assert suggestions[0]["platform"] == "tiktok"
        assert len(suggestions[0]["suggestions"]) >= 1
