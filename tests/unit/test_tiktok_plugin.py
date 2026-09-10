import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.domain.value_objects import PlatformType, GeoCode
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


# The grid parser rejects everything until the notification vocabulary is registered, which is
# how it guarantees it never stores the operator's own inbox. Production registers it from
# market_lexicons at bootstrap; these tests do the same by hand.
UI_NOISE = ["follow bạn", "tin nhắn", "thông báo", "live "]


def _armed_plugin() -> TikTokPlugin:
    plugin = TikTokPlugin()
    plugin.register_ui_noise(UI_NOISE)
    return plugin

@pytest.mark.asyncio
async def test_tiktok_plugin_properties():
    plugin = TikTokPlugin()
    assert plugin.platform == PlatformType.TIKTOK
    assert "TikTok" in plugin.name
    # is_healthy is no longer a constant: it asks whether a Chromium can be launched and
    # whether the surface answers, so its result depends on the host and the network. A
    # properties test must not assert it -- CI installs the playwright module but never
    # runs `playwright install`, so the honest answer there is False.
    # test_tiktok_health_probes.py covers the probe with the capability stubbed.

@pytest.mark.asyncio
async def test_tiktok_plugin_parse_json_item():
    plugin = _armed_plugin()
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
    plugin = _armed_plugin()
    mock_card = AsyncMock()
    mock_link = AsyncMock()
    mock_link.get_attribute.return_value = "https://www.tiktok.com/@creator/video/12345"

    async def mock_query(selector):
        if "xpath=.." in selector:
            return None
        if "/video/" in selector:
            return mock_link
        return None

    mock_card.query_selector.side_effect = mock_query
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
    
    mock_call_count = 0
    async def mock_fetch_impl(*args, **kwargs):
        nonlocal mock_call_count
        mock_call_count += 1
        mock_sig = MagicMock()
        mock_sig.platform = PlatformType.TIKTOK
        mock_sig.source_url = f"https://www.tiktok.com/@user/video/{mock_call_count}"
        return [mock_sig]

    with patch.object(plugin, "_fetch_via_playwright", side_effect=mock_fetch_impl):
        # Test fetch_signals
        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)
        assert len(signals) == 1
        assert signals[0].platform == PlatformType.TIKTOK

        # Test search_signals
        search_signals = await plugin.search_signals(keywords=["ai", "agent"], geo=GeoCode.VN)
        assert len(search_signals) == 2


@pytest.mark.asyncio
async def test_the_grid_parser_rejects_everything_without_its_vocabulary():
    """Fail closed: no vocabulary means no card can be shown to be public, so none is kept."""
    plugin = TikTokPlugin()

    assert plugin._parse_json_item(SAMPLE_TIKTOK_ITEM, geo=GeoCode.VN, keyword="ai agent") is None


@pytest.mark.asyncio
async def test_a_notification_card_is_never_ingested():
    """The class promises it never touches the inbox; that promise is this vocabulary."""
    plugin = _armed_plugin()

    assert plugin._is_private_or_notification("UserA đã bắt đầu follow bạn") is True
    assert plugin._is_private_or_notification("tin nhắn mới") is True
    assert plugin._is_private_or_notification("#congnghe2026 AI Agent sieu hot") is False


def test_an_intent_probe_never_borrows_another_market_phrasing():
    """A geo with no registered phrasing is skipped rather than probed in someone else's."""
    plugin = TikTokPlugin()
    assert plugin._intent_probe_templates("VN") == []

    plugin.register_suggest_templates({
        "VN": ["cách làm {}"],
        "DEFAULT": ["how to make {}"],
    })

    assert plugin._intent_probe_templates("VN") == ["cách làm {}"]
    assert plugin._intent_probe_templates("US") == ["how to make {}"]


def test_a_ui_noise_term_matches_on_word_boundaries():
    """A term must match the word, not the middle of a longer one.

    Raw substring matching dropped "olive oil review" as a notification, because the stored
    term is "live " and "olive " contains it. The trailing space in that term was there to stop
    the same thing happening inside "livestream", and a boundary does both jobs, so the space
    is no longer load-bearing and registration strips it.
    """
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["live "])

    assert plugin._is_private_or_notification("live ngay bay gio") is True
    assert plugin._is_private_or_notification("livestream review") is False
    assert plugin._is_private_or_notification("olive oil review") is False


def test_a_multi_word_term_tolerates_odd_whitespace():
    """A scraped caption may carry a line break where the badge text has a single space."""
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["bắt đầu follow"])

    assert plugin._is_private_or_notification("UserA đã bắt đầu follow bạn") is True
    assert plugin._is_private_or_notification("UserA đã bắt  đầu\nfollow bạn") is True
    assert plugin._is_private_or_notification("bắt đầu theo dõi") is False
