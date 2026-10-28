from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType
from ignis.infrastructure.connectors.meta_browser_ingress import (
    caption_text,
    coerce_int,
    extract_records,
    walk_dicts,
)
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin

STORAGE_STATE = {"cookies": [
    {"name": "sessionid", "value": "SECRET", "domain": domain, "path": "/",
     "secure": True, "expires": -1, "httpOnly": True, "sameSite": "Lax"}
    for domain in (".threads.com", ".instagram.com")
]}

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


@pytest.mark.asyncio
@pytest.mark.parametrize("state,reason", [("healthy", None), ("login", "REELS_LOGIN_REQUIRED"),
    ("checkpoint", "REELS_CHECKPOINT"), ("challenge", "REELS_CHALLENGE"),
    ("captcha", "REELS_CHALLENGE"), ("answered_empty", None), ("unusable", "REELS_PAGE_UNUSABLE"),
    ("unrelated_json", "REELS_PAGE_UNUSABLE"), ("late_checkpoint", "REELS_CHECKPOINT"),
    ("response403", "REELS_LOGIN_REQUIRED"), ("response_fail", "REELS_PAGE_UNUSABLE"),
    ("html_response", "REELS_PAGE_UNUSABLE"), ("response_challenge", "REELS_CHALLENGE"),
    ("t058_wrong_tag", "REELS_PAGE_UNUSABLE"), ("t058_unbound", "REELS_PAGE_UNUSABLE"),
    ("t058_redirect", "REELS_PAGE_UNUSABLE"), ("t058_wrong_tag_empty", "REELS_PAGE_UNUSABLE"),
    ("t058_malformed_then_empty", "REELS_PAGE_UNUSABLE"), ("t058_empty_then_malformed", "REELS_PAGE_UNUSABLE")])
async def test_reels_flag_free_pages_require_cards_or_a_verified_empty_envelope(state, reason):
    from types import SimpleNamespace
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    from ignis.application.ports.connector_port import SearchAttestation
    handlers = {}
    page = AsyncMock()
    page.url = {"login": "https://www.instagram.com/accounts/login/", "checkpoint": "https://www.instagram.com/checkpoint/",
                "challenge": "https://www.instagram.com/challenge/"}.get(state, "https://www.instagram.com/explore/tags/synthetic/")
    page.on = MagicMock(side_effect=lambda name, callback: handlers.__setitem__(name, callback))
    page.remove_listener = MagicMock()
    page.locator = MagicMock(side_effect=lambda selector: SimpleNamespace(count=AsyncMock(
        return_value=int(state == "captcha" and "captcha" in selector))))
    if state == "t058_redirect":
        page.url = "https://www.instagram.com/explore/tags/other/"
    body = {"viewer": {"id": "not-a-reel"}} if state == "unrelated_json" else {"data": {"recent": {"sections": None}}} if state == "unusable" else {"data": {"recent": {"sections": []}}} if state in {"answered_empty", "t058_wrong_tag_empty"} else REELS_PAYLOAD
    if state in {"response403", "response_fail", "response_challenge"}:
        body = {**body, "status": "fail", "message": {"response403": "login_required", "response_challenge": "challenge_required"}.get(state, "unavailable")}
    response_url = "https://www.instagram.com/api/v1/tags/web_info/?tag_name=" + ("other" if state in {"t058_wrong_tag", "t058_wrong_tag_empty"} else "synthetic")
    if state == "t058_unbound":
        response_url = "https://www.instagram.com/api/v1/clips/"
    response = SimpleNamespace(url=response_url, request=SimpleNamespace(url=response_url, method="GET"), status=403 if state == "response403" else 200,
        headers={"content-type": "text/html" if state == "html_response" else "application/json"}, json=AsyncMock(return_value=body))
    if state == "late_checkpoint":
        async def wheel(*args):
            page.url = "https://www.instagram.com/checkpoint/"
        page.mouse.wheel.side_effect = wheel
    async def navigate(*args, **kwargs):
        if state in {"t058_malformed_then_empty", "t058_empty_then_malformed"}:
            bodies = [{"data": {"recent": {"sections": None}}}, {"data": {"recent": {"sections": []}}}]
            if state == "t058_empty_then_malformed":
                bodies.reverse()
            for body in bodies:
                response.json = AsyncMock(return_value=body)
                await handlers["response"](response)
        else:
            await handlers["response"](response)
        return SimpleNamespace(status=200)
    page.goto.side_effect = navigate
    browser = AsyncMock()
    browser.new_context.return_value.new_page.return_value = page
    engine = MagicMock()
    engine.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=engine), __aexit__=AsyncMock(return_value=None))
    attestation = SearchAttestation()
    plugin = ReelsPlugin()
    with patch("playwright.async_api.async_playwright", return_value=manager):
        if reason:
            with pytest.raises(ConnectorCapabilityUnavailableException, match=reason):
                await plugin._fetch_via_browser_session("https://www.instagram.com/explore/tags/synthetic/", {}, GeoCode.VN,
                                                       20, "synthetic", attestation)
            assert attestation.queried == []
        else:
            signals = await plugin._fetch_via_browser_session("https://www.instagram.com/explore/tags/synthetic/", {}, GeoCode.VN,
                                                             20, "synthetic", attestation)
            if state == "answered_empty":
                assert signals == []
            else:
                assert len(signals) == 1 and signals[0].metric_value == 96400
            assert attestation.queried == ["synthetic"]
    assert "AutomationControlled" not in str(engine.chromium.launch.await_args.kwargs)
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_capture", [False, True])
async def test_reels_unsettled_response_cannot_become_healthy_during_browser_close(cancel_capture):
    import asyncio
    from types import SimpleNamespace
    from ignis.application.ports.connector_port import SearchAttestation
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    handlers, late_tasks = {}, []
    started, release = asyncio.Event(), asyncio.Event()
    page = AsyncMock()
    page.url = "https://www.instagram.com/explore/tags/synthetic/"
    page.on = MagicMock(side_effect=lambda name, callback: handlers.__setitem__(name, callback))
    page.remove_listener = MagicMock()
    page.locator = MagicMock(return_value=SimpleNamespace(count=AsyncMock(return_value=0)))
    async def late_json():
        started.set()
        await release.wait()
        return {"status": "fail", "message": "challenge_required", **REELS_PAYLOAD}
    def response(reader):
        return SimpleNamespace(url="https://www.instagram.com/api/v1/tags/web_info/?tag_name=synthetic",
                               request=SimpleNamespace(url="https://www.instagram.com/api/v1/tags/web_info/?tag_name=synthetic", method="GET"), status=200,
                               headers={"content-type": "application/json"}, json=reader)
    async def navigate(*args, **kwargs):
        await handlers["response"](response(AsyncMock(return_value=REELS_PAYLOAD)))
        late_tasks.append(asyncio.ensure_future(handlers["response"](response(late_json))))
        await started.wait()
        if cancel_capture:
            await asyncio.Event().wait()
        return SimpleNamespace(status=200)
    page.goto.side_effect = navigate
    browser = AsyncMock()
    browser.new_context.return_value.new_page.return_value = page
    async def close():
        release.set()
        await asyncio.gather(*late_tasks, return_exceptions=True)
    browser.close.side_effect = close
    engine = MagicMock()
    engine.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock(__aenter__=AsyncMock(return_value=engine), __aexit__=AsyncMock(return_value=None))
    attestation = SearchAttestation()
    with patch("playwright.async_api.async_playwright", return_value=manager):
        if cancel_capture:
            capture = asyncio.create_task(ReelsPlugin()._fetch_via_browser_session(page.url, {}, GeoCode.VN, 20, "synthetic", attestation))
            await started.wait()
            capture.cancel()
            with pytest.raises(asyncio.CancelledError):
                await capture
        else:
            with pytest.raises(ConnectorCapabilityUnavailableException, match="REELS_(PAGE_UNUSABLE|CHALLENGE)"):
                await ReelsPlugin()._fetch_via_browser_session(page.url, {}, GeoCode.VN, 20, "synthetic", attestation)
    assert attestation.queried == []
    assert late_tasks and all(task.cancelled() for task in late_tasks)
    browser.close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("payloads,verified_empty", [
    ([{"data": {"recent": {"sections": []}}}], True),
    ([{"data": {"recent": {"sections": [{"layout_content": {"medias": []}}]}}}], True),
    ([], False), ([{"viewer": {"id": "synthetic"}}], False),
    ([{"data": {"recent": {"sections": None}}}], False),
    ([{"data": {"recent": {"sections": [{}]}}}], False),
    ([{"data": {"recent": {"sections": []}}}, {"status": "fail", "message": "login_required"}], False),
    ([{"data": {"recent": {"sections": []}}}, {"data": {"recent": {"sections": [{}]}}}], False),
])
async def test_reels_answered_empty_attests_only_a_well_formed_executed_search(payloads, verified_empty):
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    registry = ConnectorPluginRegistry()
    registry.register(ReelsPlugin(auth_manager=_oauth_manager(None), browser_auth_manager=_browser_manager()))
    with patch("ignis.infrastructure.connectors.reels.reels_plugin.collect_json_payloads", AsyncMock(return_value=payloads)):
        result = await registry.search_with_outcomes(keywords=["synthetic"])
    [outcome] = result.outcomes
    assert not result.signals
    if verified_empty:
        assert outcome.status.value == "EMPTY_NO_DATA"
        assert outcome.queried_keywords == ("synthetic",)
        assert outcome.queried_window is None
    else:
        assert outcome.status.value == "DEGRADED"
        assert outcome.queried_keywords == ()
        assert "REELS_PAGE_UNUSABLE" in outcome.note
