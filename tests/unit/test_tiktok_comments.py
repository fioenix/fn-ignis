import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.interfaces.mcp.server import (
    handle_extract_customer_pain_points,
)


@pytest.mark.asyncio
async def test_tiktok_plugin_fetch_video_comments_mocked():
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

        mock_page.evaluate.return_value = {
            "comments": [
                {
                    "cid": "7111222333",
                    "user": {"nickname": "Nguyen Van A", "unique_id": "nguyenvana"},
                    "text": "Giá bao nhiêu vậy shop? Có dùng được cho Mac không?",
                    "digg_count": 5,
                    "reply_comment_total": 2,
                    "create_time": 1725000000,
                }
            ]
        }

        comments = await plugin.fetch_video_comments(
            video_url="https://www.tiktok.com/@author/video/7666063173253991687",
            limit=10,
        )
        assert len(comments) == 1
        assert comments[0]["author"].startswith("Ng***_")
        assert "Giá bao nhiêu" in comments[0]["text"]
        assert comments[0]["likes"] == 5



@pytest.mark.asyncio
async def test_handle_extract_customer_pain_points():
    mock_comp = {
        "registry": MagicMock(),
        "tiktok_auth_manager": AsyncMock(),
    }
    mock_comp["registry"]._plugins = {}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [
                {
                    "video_url": "https://www.tiktok.com/@author/video/7666063173253991687",
                    "video_title": "Hướng dẫn xây dựng AI Agent",
                    "author": "TechReview",
                    "views": 50000,
                    "total_comments_fetched": 2,
                    "comments": [
                        {
                            "comment_id": "1",
                            "author": "UserB",
                            "text": "Cài n8n trên server như thế nào vậy anh?",
                            "likes": 3,
                        },
                        {
                            "comment_id": "2",
                            "author": "UserC",
                            "text": "Video rất hay, cảm ơn bạn",
                            "likes": 1,
                        },
                    ],
                }
            ]

            resp_json = await handle_extract_customer_pain_points(keywords=["ai agent"], geo="VN", max_videos=1)
            resp = json.loads(resp_json)
            assert resp["status"] == "SUCCESS"
            assert resp["total_videos_analyzed"] == 1
            assert resp["total_comments_extracted"] == 2
            assert len(resp["top_inquiries_and_pain_points"]) == 1
            assert "như thế nào" in resp["top_inquiries_and_pain_points"][0]["inquiry"]
