"""Regressions for unmeasured silence and evidence lost during social collection."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from ignis.application.ports.connector_port import SearchAttestation
from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


@pytest.mark.asyncio
@pytest.mark.parametrize("response_query,landed_page", [
    ("retail", "https://www.tiktok.com/search?q=retail"),
    ("unrelated", "https://www.tiktok.com/search?q=retail"),
    ("retail", "https://www.tiktok.com/explore"),
    ("retail", "https://www.tiktok.com/search?q=unrelated"),
])
@pytest.mark.parametrize("body,expected", [
    ({"status_code": 999, "itemList": []}, False),
    ({"status_code": 0, "sug_list": [], "user_input_query": "retail"}, False),
    ({"status_code": 0, "batchStoryItemLists": []}, False),
    ({"status_code": 0, "data": [{"id": "user123", "unique_id": "reviewer"}]}, False),
    ({"status_code": 0, "itemList": []}, True),
    ({"status_code": 0, "data": [{"item": {
        "id": "123", "desc": "Retail product review", "author": {"uniqueId": "reviewer"},
        "stats": {"playCount": 1234},
    }}]}, True),
])
async def test_only_a_video_search_envelope_attests_execution(body, expected, response_query, landed_page):
    expected = expected and response_query == "retail" and landed_page.endswith("/search?q=retail")
    response = SimpleNamespace(
        url=f"https://www.tiktok.com/api/search/general/?keyword={response_query}", status=200,
        headers={"content-type": "application/json"}, json=AsyncMock(return_value=body),
    )
    class Page:
        url = landed_page
        def on(self, event, callback):
            self.callback = callback
        async def goto(self, *args, **kwargs):
            await self.callback(response)
        wait_for_timeout = AsyncMock()
        query_selector_all = AsyncMock(return_value=[])
    browser = SimpleNamespace(
        new_context=AsyncMock(return_value=SimpleNamespace(new_page=AsyncMock(return_value=Page()))),
        close=AsyncMock(),
    )
    class Playwright:
        async def __aenter__(self):
            return SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
        async def __aexit__(self, *args):
            pass
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["notification"])
    attestation = SearchAttestation()
    with patch("playwright.async_api.async_playwright", return_value=Playwright()):
        signals = await plugin._fetch_via_playwright(
            url="https://www.tiktok.com/search?q=retail", storage_state=None,
            geo=GeoCode.VN, keyword="retail", attestation=attestation,
        )
    assert attestation.queried == (["retail"] if expected else [])
    assert bool(attestation.failures) is not expected
    if expected and body.get("data"):
        assert len(signals) == 1
        assert signals[0].metric_value == 1234
    if not expected:
        assert signals == []
    if not landed_page.endswith("/search?q=retail"):
        Page.query_selector_all.assert_not_awaited()


def test_threads_qualification_preserves_full_text_and_publication_date():
    text = ("Office retail review. " * 30).strip()
    signal = ThreadsPlugin()._map_browser_post(
        {"pk": "123", "code": "post123", "caption": {"text": text},
         "taken_at": 1759276800, "user": {"username": "reviewer"}},
        geo=GeoCode.VN, keyword="office retail",
    )
    assert signal.published_at == datetime(2025, 10, 1, tzinfo=timezone.utc)
    evidence = GetEvidenceQualificationBatchUseCase._evidence(signal)
    assert evidence["excerpt"] == text
    assert evidence["published_at"] == "2025-10-01T00:00:00+00:00"
    assert evidence["source_url"] == "https://www.threads.net/@reviewer/post/post123"


@pytest.mark.asyncio
async def test_graph_threads_preserves_full_text_and_publication_date():
    plugin = ThreadsPlugin()
    text = "Office retail review. " * 30 + "Contact person@example.com"
    with patch.object(plugin, "_fetch_insights_batch", AsyncMock(return_value={})):
        [signal] = await plugin._map_items([
            {"id": "123", "text": text, "timestamp": "2025-10-01T00:00:00Z"},
        ], "synthetic-token", GeoCode.VN)
    assert signal.published_at == datetime(2025, 10, 1, tzinfo=timezone.utc)
    assert len(signal.metadata["excerpt"]) > 200
    assert "person@example.com" not in signal.metadata["excerpt"]


def test_tiktok_keeps_the_platform_publication_clock_and_full_sanitized_caption():
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["notification"])
    text = "Office retail review. " * 30 + "Contact person@example.com"
    signal = plugin._parse_json_item({
        "id": "123", "desc": text, "author": {"uniqueId": "reviewer"},
        "stats": {"playCount": 1234}, "createTime": 1759276800,
    }, GeoCode.VN, "retail")
    assert signal.published_at == datetime(2025, 10, 1, tzinfo=timezone.utc)
    assert len(signal.metadata["excerpt"]) > 250
    assert "person@example.com" not in signal.metadata["excerpt"]


@pytest.mark.asyncio
async def test_dom_fallback_keeps_the_full_sanitized_caption_for_qualification():
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["notification"])
    caption = "Office retail review. " * 30 + "Contact person@example.com"
    card = SimpleNamespace(
        query_selector=AsyncMock(side_effect=[None, SimpleNamespace(
            get_attribute=AsyncMock(return_value="https://www.tiktok.com/@reviewer/video/1234567890"),
        )]), inner_text=AsyncMock(return_value=caption + "\nreviewer"),
    )
    signal = await plugin._parse_dom_card(card, GeoCode.VN, "retail")
    evidence = GetEvidenceQualificationBatchUseCase._evidence(signal)
    assert len(evidence["excerpt"]) > 250
    assert evidence["excerpt"].endswith("Contact [REDACTED_EMAIL]")
    assert evidence["published_at"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["tiktok", "threads"])
async def test_all_requested_queries_are_executed_without_a_silent_ten_query_cap(platform):
    queries = [f"retail-query-{index}" for index in range(12)]
    attestation = SearchAttestation()
    async def fetch(**kwargs):
        kwargs["attestation"].executed(kwargs["keyword"])
        return []
    if platform == "tiktok":
        plugin = TikTokPlugin()
        with patch.object(plugin, "_fetch_via_playwright", side_effect=fetch):
            await plugin.search_signals(queries, attestation=attestation)
    else:
        plugin = ThreadsPlugin()
        with patch("ignis.infrastructure.connectors.threads.threads_plugin.GraphQLDocIdCache.get", return_value=(None, None)), patch.object(plugin, "_fetch_via_browser_session", side_effect=fetch):
            await plugin._search_via_browser_session(queries, {}, GeoCode.VN, 20, attestation)
    assert attestation.queried == queries
