import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.interfaces.mcp.server import (
    handle_extract_customer_pain_points,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/@author/video/7666063173253991687", "/video/7666063173253991687", "/share/video/7666063173253991687/?tracking=1#ignored"])
async def test_tiktok_plugin_fetch_video_comments_mocked(path):
    mock_auth = AsyncMock()
    mock_auth.get_storage_state.return_value = {"cookies": []}
    plugin = TikTokPlugin(auth_manager=mock_auth)

    with patch("playwright.async_api.async_playwright") as mock_playwright:
        mock_p = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()
        mock_page.url = "https://www.tiktok.com/share/video/7666063173253991687"

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
            video_url="https://www.tiktok.com" + path,
            limit=10,
        )
        mock_page.goto.assert_awaited_once_with("https://www.tiktok.com/share/video/7666063173253991687", wait_until="domcontentloaded", timeout=25000)
        guard = mock_context.route.await_args.args[1]
        for url, allowed in [("https://evil.invalid/video/7666063173253991687", False),
                             ("https://www.tiktok.com/video/999", False),
                             ("https://www.tiktok.com/@other/video/7666063173253991687", True)]:
            route = AsyncMock()
            route.request = MagicMock(url=url)
            route.request.is_navigation_request.return_value = True
            await guard(route)
            assert route.abort.await_count == int(not allowed)
            assert route.continue_.await_count == int(allowed)
        assert len(comments) == 1
        # No author field, not even a pseudonym: a fixed-salt hash links one commenter across
        # every mission and leaks a prefix of the name (Spec 015, research R3).
        assert "author" not in comments[0] and "author_id" not in comments[0]
        assert "nguyenvana" not in json.dumps(comments) and "Ng" not in json.dumps(comments)
        assert "Giá bao nhiêu" in comments[0]["text"]
        assert comments[0]["likes"] == 5


@pytest.mark.asyncio
async def test_comment_scraping_logs_carry_no_handle(caplog):
    caplog.set_level("DEBUG")
    plugin = TikTokPlugin(auth_manager=None)

    with patch("playwright.async_api.async_playwright", side_effect=RuntimeError("browser unavailable")):
        with pytest.raises(Exception):
            await plugin.fetch_video_comments(
                video_url="https://www.tiktok.com/@sentinel.tiktok.author/video/7666063173253991687", limit=10
            )
    with pytest.raises(ValueError, match="Invalid TikTok video URL"):
        await plugin.fetch_video_comments(video_url="https://www.tiktok.com/@sentinel.tiktok.profile")

    assert "sentinel.tiktok" not in caplog.text



@pytest.mark.asyncio
async def test_handle_extract_customer_pain_points():
    # The baseline inquiry triggers come from the customer_inquiry lexicon domain. Whether the
    # seed actually carries them is covered by test_vocabulary_loader; here the point is that
    # the tool reads them from the repository instead of a list compiled into the module.
    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = [
        {"domain": "customer_inquiry", "term": term, "category": "question"}
        for term in ("?", "how", "price", "như thế nào", "giá")
    ]
    # A mock keeps no request count, so it sets no daily ceiling.
    repository.reserve_connector_requests = AsyncMock(side_effect=NotImplementedError)
    mock_comp = {
        "registry": MagicMock(),
        "repository": repository,
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
            repository.get_domain_lexicons.assert_awaited_with(domain="customer_inquiry")


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://attacker.invalid/@brand/video/123", "http://www.tiktok.com/video/123",
    "https://www.tiktok.com:443/video/123", "https://user@www.tiktok.com/video/123",
    "https://tiktok.com/video/123", "https://www.tiktok.com/video/１２３",
    "https://www.tiktok.com/video/123/extra", "file:///video/123",
])
async def test_t058_comments_reject_untrusted_url_before_browser_or_auth(url):
    auth = AsyncMock()
    plugin = TikTokPlugin(auth_manager=auth)
    with patch("playwright.async_api.async_playwright") as browser:
        with pytest.raises(ValueError, match="Invalid TikTok video URL"):
            await plugin.fetch_video_comments(url)
        browser.assert_not_called()
        auth.get_storage_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_t058_comments_tool_rejected_url_has_existing_error_shape():
    from ignis.interfaces.mcp.server import handle_get_tiktok_video_comments
    comp = {"registry": MagicMock(), "tiktok_auth_manager": None}
    comp["registry"]._plugins = {}
    with patch("ignis.interfaces.mcp.server.get_components", return_value=comp), patch("playwright.async_api.async_playwright"):
        result = json.loads(await handle_get_tiktok_video_comments("https://evil.invalid/video/123"))
    assert result == {"status": "ERROR", "message": "Invalid TikTok video URL"}


@pytest.mark.asyncio
async def test_t058_comments_refuse_redirect_before_api_evaluation():
    plugin = TikTokPlugin()
    with patch("playwright.async_api.async_playwright") as manager:
        engine = manager.return_value.__aenter__.return_value
        page = engine.chromium.launch.return_value.new_context.return_value.new_page.return_value
        page.url = "https://evil.invalid/video/123"
        with pytest.raises(Exception, match="Invalid TikTok video URL"):
            await plugin.fetch_video_comments("https://www.tiktok.com/video/123")
        page.evaluate.assert_not_awaited()
        engine.chromium.launch.return_value.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_t058_comments_response_provenance_uses_validated_id():
    from ignis.interfaces.mcp.server import handle_get_tiktok_video_comments
    plugin = TikTokPlugin()
    comp = {"registry": MagicMock()}
    comp["registry"]._plugins = {"tiktok": plugin}
    with patch("ignis.interfaces.mcp.server.get_components", return_value=comp), patch.object(plugin, "fetch_video_comments", AsyncMock(return_value=[])):
        result = json.loads(await handle_get_tiktok_video_comments("https://www.tiktok.com/video/123?track=1#fragment"))
    assert result["status"] == "SUCCESS"
    assert result["video_url"] == "https://www.tiktok.com/share/video/123"


@pytest.mark.asyncio
@pytest.mark.parametrize("api_data", [{"error": "Invalid comment origin"},
                                      {"error": "redirect rejected"},
                                      {"error": "Invalid JSON"}, {"error": ""}, None, []])
async def test_t058_comments_api_failure_returns_error(api_data):
    from ignis.interfaces.mcp.server import handle_get_tiktok_video_comments

    plugin = TikTokPlugin()
    comp = {"registry": MagicMock()}
    comp["registry"]._plugins = {"tiktok": plugin}
    with patch("ignis.interfaces.mcp.server.get_components", return_value=comp), patch("playwright.async_api.async_playwright") as manager:
        engine = manager.return_value.__aenter__.return_value
        browser = engine.chromium.launch.return_value
        page = browser.new_context.return_value.new_page.return_value
        page.url = "https://www.tiktok.com/share/video/123"
        page.evaluate.return_value = api_data
        result = json.loads(await handle_get_tiktok_video_comments(page.url))
        page.evaluate.assert_awaited_once()
        browser.close.assert_awaited_once()
    assert result == {"status": "ERROR", "message": "Failed to fetch TikTok comments: TikTok comment API request failed"}


@pytest.mark.parametrize("handle", ["", "guest-author"])
def test_t058_comments_guest_and_hyphenated_handles_canonicalize(handle):
    assert TikTokPlugin.canonical_comment_video_url(
        f"https://www.tiktok.com/@{handle}/video/123"
    ) == "https://www.tiktok.com/share/video/123"
    with pytest.raises(ValueError, match="Invalid TikTok video URL"):
        TikTokPlugin.canonical_comment_video_url(f"https://evil.invalid/@{handle}/video/123")
