from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.exceptions import ConnectorAuthenticationException
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType
from ignis.infrastructure.connectors.meta_browser_ingress import (
    caption_text,
    coerce_int,
    extract_records,
    walk_dicts,
)
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin

STORAGE_STATE = {"cookies": [{"name": "sessionid", "value": "SECRET"}]}

# Shaped like Meta's private GraphQL envelope: the post sits several wrappers deep.
THREADS_PAYLOAD = {
    "data": {
        "searchResults": {
            "edges": [
                {
                    "node": {
                        "thread": {
                            "thread_items": [
                                {
                                    "post": {
                                        "pk": "17900000000009",
                                        "code": "C9xYzAbc",
                                        "caption": {"text": "Shop mình đang tìm phần mềm quản lý kho cho 3 kênh bán"},
                                        "like_count": 412,
                                        "taken_at": 1788400000,
                                        "user": {"username": "fashion_ops_vn"},
                                        "text_post_app_info": {
                                            "direct_reply_count": 57,
                                            "repost_count": 9,
                                            "quote_count": 3,
                                        },
                                    }
                                }
                            ]
                        }
                    }
                }
            ]
        }
    }
}

REELS_PAYLOAD = {
    "data": {
        "recent": {
            "sections": [
                {
                    "layout_content": {
                        "medias": [
                            {
                                "media": {
                                    "pk": "18000000000009",
                                    "code": "C9abcDEF",
                                    "media_type": 2,
                                    "caption": {"text": "Review máy in tem đơn hàng cho shop online"},
                                    "like_count": 1820,
                                    "comment_count": 140,
                                    "play_count": 96400,
                                    "taken_at": 1788410000,
                                    "user": {"username": "ecom_tools"},
                                    "clips_metadata": {
                                        "music_info": {"music_asset_info": {"title": "Trending Audio 01"}}
                                    },
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }
}


def _browser_manager(state=STORAGE_STATE) -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_storage_state.return_value = state
    return mgr


def _oauth_manager(token) -> AsyncMock:
    mgr = AsyncMock()
    mgr.get_access_token.return_value = token
    return mgr


# --- Shared extraction helpers ---


def test_walk_dicts_reaches_nodes_nested_inside_lists():
    found = [d for d in walk_dicts({"a": [{"b": {"c": 1}}]}) if "c" in d]
    assert found == [{"c": 1}]


def test_walk_dicts_is_depth_limited_so_a_hostile_payload_cannot_blow_the_stack():
    node = {"leaf": True}
    for _ in range(40):
        node = {"wrap": node}

    assert not any(d.get("leaf") for d in walk_dicts(node, max_depth=5))


def test_extract_records_deduplicates_and_respects_the_limit():
    payloads = [{"items": [{"pk": "1"}, {"pk": "1"}, {"pk": "2"}, {"pk": "3"}]}]

    records = extract_records(
        payloads,
        is_record=lambda n: "pk" in n,
        identity=lambda n: n.get("pk"),
        limit=2,
    )

    assert [r["pk"] for r in records] == ["1", "2"]


@pytest.mark.parametrize(
    "raw,expected",
    [("42", 42), (7.9, 7), (None, 0), ("", 0), ("abc", 0)],
)
def test_coerce_int_never_raises_on_meta_payload_noise(raw, expected):
    assert coerce_int(raw) == expected


def test_caption_text_handles_both_dict_and_plain_string_shapes():
    assert caption_text({"caption": {"text": " hi "}}) == "hi"
    assert caption_text({"caption": "hello"}) == "hello"
    assert caption_text({"text": "fallback"}) == "fallback"
    assert caption_text({}) == ""


# --- Threads Tier 1 ingress ---


@pytest.mark.asyncio
async def test_threads_search_uses_the_browser_session_when_no_oauth_token_exists():
    plugin = ThreadsPlugin(
        auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager()
    )

    with patch(
        "ignis.infrastructure.connectors.threads.threads_plugin.collect_json_payloads",
        AsyncMock(return_value=[THREADS_PAYLOAD]),
    ) as collect:
        signals = await plugin.search_signals(keywords=["quản lý kho"], geo=GeoCode.VN, limit=10)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.platform == PlatformType.THREADS
    assert "quản lý kho" in signal.raw_title
    assert signal.metric_value == 412.0
    assert signal.source_url == "https://www.threads.net/@fashion_ops_vn/post/C9xYzAbc"
    assert signal.metadata["reply_count"] == 57
    assert signal.metadata["reposts"] == 9
    assert signal.metadata["quotes"] == 3
    assert signal.metadata["source"] == "threads_browser_session"
    assert signal.metadata["tier"] == "TIER_1_BROWSER_SESSION"
    assert signal.metadata["matched_keyword"] == "quản lý kho"
    assert signal.metadata["published_at"].startswith("2026-")

    kwargs = collect.await_args.kwargs
    assert kwargs["storage_state"] == STORAGE_STATE
    assert "q=qu" in kwargs["url"]  # keyword is URL-encoded into the public search page


@pytest.mark.asyncio
async def test_threads_prefers_the_graph_api_when_a_token_is_available():
    plugin = ThreadsPlugin(
        auth_manager=_oauth_manager("LONG_LIVED_TOKEN"), browser_auth_manager=_browser_manager()
    )

    with patch(
        "ignis.infrastructure.connectors.threads.threads_plugin.collect_json_payloads",
        AsyncMock(return_value=[THREADS_PAYLOAD]),
    ) as collect, patch.object(
        ThreadsPlugin, "_graph_get", AsyncMock(return_value={"data": []})
    ) as graph_get:
        await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)

    collect.assert_not_awaited()
    graph_get.assert_awaited()


@pytest.mark.asyncio
async def test_threads_still_raises_when_oauth_is_configured_but_unusable_and_no_session_exists():
    plugin = ThreadsPlugin(
        auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager(state=None)
    )

    with pytest.raises(ConnectorAuthenticationException):
        await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)


@pytest.mark.asyncio
async def test_threads_is_healthy_on_a_browser_session_alone():
    plugin = ThreadsPlugin(auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager())
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert await plugin.is_healthy() is True

    offline = ThreadsPlugin(
        auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager(state=None)
    )
    assert await offline.is_healthy() is False


# --- Reels Tier 1 ingress ---


@pytest.mark.asyncio
async def test_reels_search_uses_the_browser_session_when_no_oauth_token_exists():
    plugin = ReelsPlugin(
        auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager()
    )

    with patch(
        "ignis.infrastructure.connectors.reels.reels_plugin.collect_json_payloads",
        AsyncMock(return_value=[REELS_PAYLOAD]),
    ) as collect:
        signals = await plugin.search_signals(keywords=["in tem đơn hàng"], geo=GeoCode.VN, limit=10)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.platform == PlatformType.REELS
    assert signal.metric_value == 96400.0
    assert signal.source_url == "https://www.instagram.com/reel/C9abcDEF/"
    assert signal.metadata["like_count"] == 1820
    assert signal.metadata["comment_count"] == 140
    assert signal.metadata["music_title"] == "Trending Audio 01"
    assert signal.metadata["source"] == "instagram_browser_session"
    assert signal.metadata["tier"] == "TIER_1_BROWSER_SESSION"

    # Keyword is normalized to a bare hashtag slug for the public tag page.
    assert collect.await_args.kwargs["url"] == "https://www.instagram.com/explore/tags/intemđơnhàng/"


@pytest.mark.asyncio
async def test_reels_browser_ingress_does_not_require_an_instagram_business_account_id():
    plugin = ReelsPlugin(
        auth_manager=_oauth_manager(None), ig_user_id="", browser_auth_manager=_browser_manager()
    )

    with patch(
        "ignis.infrastructure.connectors.reels.reels_plugin.collect_json_payloads",
        AsyncMock(return_value=[REELS_PAYLOAD]),
    ):
        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=5, scope=IngressScope.OWN_PROFILE)

    assert len(signals) == 1


@pytest.mark.asyncio
async def test_reels_prefers_the_graph_api_when_a_token_is_available():
    plugin = ReelsPlugin(
        auth_manager=_oauth_manager("LONG_LIVED_TOKEN"),
        ig_user_id="17841400000000000",
        browser_auth_manager=_browser_manager(),
    )

    with patch(
        "ignis.infrastructure.connectors.reels.reels_plugin.collect_json_payloads",
        AsyncMock(return_value=[REELS_PAYLOAD]),
    ) as collect, patch.object(ReelsPlugin, "_graph_get", AsyncMock(return_value={"data": []})):
        await plugin.fetch_signals(scope=IngressScope.OWN_PROFILE)

    collect.assert_not_awaited()


@pytest.mark.asyncio
async def test_reels_is_healthy_synthetic_probe():
    plugin = ReelsPlugin(auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager())
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert await plugin.is_healthy() is True

        # When session expires and redirects to login (e.g. 302/401)
        mock_resp.status_code = 302
        assert await plugin.is_healthy() is False

    offline = ReelsPlugin(
        auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager(state=None)
    )
    assert await offline.is_healthy() is False
