"""T020: MCP responses carry no author identity (Spec 015, contracts/mcp-surface.md).

Each response is checked against rows or connector payloads that still hold author fields and
handle links -- legacy rows, or a connector answering the way it did before Spec 015 -- because
the response boundary must hold on its own.
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.interfaces.mcp.server import handle_extract_customer_pain_points, handle_get_tiktok_video_comments

from tests.fixtures.author_identity_sentinels import (
    SENTINEL_TIKTOK_COMMENTER,
    SENTINEL_TIKTOK_HANDLE,
    SENTINEL_TIKTOK_NICKNAME,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
    tiktok_metadata,
    undeclared_sentinels,
    youtube_metadata,
)

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)
SHARE_LINK = f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}"


def _leaks(payload) -> list:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return [value for value in undeclared_sentinels() if value in text]


def _legacy_signals():
    return [
        TrendSignal(
            platform=PlatformType.TIKTOK, raw_title="Review áo khoác", metric_value=900.0,
            source_url=TIKTOK_HANDLE_URL, geo_code=GeoCode.VN, captured_at=NOW, metadata=tiktok_metadata(),
            observation_id=None,
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE, raw_title="Đánh giá áo khoác", metric_value=1200.0,
            source_url="https://www.youtube.com/watch?v=sentinelYT1", geo_code=GeoCode.VN, captured_at=NOW,
            metadata=youtube_metadata(),
        ),
    ]


@pytest.mark.asyncio
async def test_mission_analysis_reports_no_creators_and_identity_free_links():
    mission = ResearchMission(title="Áo khoác", keywords=["áo khoác"])
    repository = AsyncMock()
    repository.get_mission.return_value = mission
    repository.get_mission_signals.return_value = _legacy_signals()

    analysis = await GetMissionAnalysisUseCase(repository).execute(mission.id)

    assert "top_creators" not in analysis["stats"]
    assert all("channel" not in item["metadata"] for item in analysis["top_signals"])
    assert SHARE_LINK in [item["url"] for item in analysis["top_signals"]]
    assert _leaks(analysis) == []


def test_an_evidence_batch_row_has_an_identity_free_link_and_says_whether_it_can_be_verified():
    stored = _legacy_signals()[0]
    stored.identity_source = "url_external_id"
    unverifiable = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title="Áo khoác mặc mát", captured_at=NOW, metadata={},
        identity_source="unverifiable_content",
    )

    row = GetEvidenceQualificationBatchUseCase._evidence(stored)
    context = GetEvidenceQualificationBatchUseCase._evidence(unverifiable)

    assert (row["source_url"], row["source_verifiable"]) == (SHARE_LINK, True)
    assert (context["source_url"], context["source_verifiable"]) == (None, False)
    assert _leaks(row) == []


def _comment_components():
    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = [
        {"domain": "customer_inquiry", "term": term, "category": "question"} for term in ("?", "giá")
    ]
    # A mock keeps no request count, so it sets no daily ceiling.
    repository.reserve_connector_requests = AsyncMock(side_effect=NotImplementedError)
    components = {"registry": MagicMock(), "repository": repository, "tiktok_auth_manager": AsyncMock()}
    components["registry"]._plugins = {}
    return components


@pytest.mark.asyncio
async def test_pain_points_name_no_commenter_or_creator():
    legacy_payload = [
        {
            "video_url": TIKTOK_HANDLE_URL,
            "video_title": "Áo khoác chống nắng",
            "author": SENTINEL_TIKTOK_HANDLE,
            "views": 50000,
            "total_comments_fetched": 1,
            "comments": [
                {"comment_id": "1", "author": SENTINEL_TIKTOK_COMMENTER, "author_id": "id_1",
                 "text": "Giá bao nhiêu vậy shop?", "likes": 3},
            ],
        }
    ]
    with patch("ignis.interfaces.mcp.server.get_components", return_value=_comment_components()):
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as fetch:
            fetch.return_value = legacy_payload
            response = json.loads(await handle_extract_customer_pain_points(keywords=["áo khoác"], geo="VN", max_videos=1))

    assert response["status"] == "SUCCESS"
    assert [i["inquiry"] for i in response["top_inquiries_and_pain_points"]] == ["Giá bao nhiêu vậy shop?"]
    assert "author" not in response["top_inquiries_and_pain_points"][0]
    assert response["videos_breakdown"][0]["video_url"] == SHARE_LINK
    assert _leaks(response) == []


@pytest.mark.asyncio
async def test_video_comments_echo_an_identity_free_link_and_no_commenter():
    with patch("ignis.interfaces.mcp.server.get_components", return_value=_comment_components()):
        with patch.object(TikTokPlugin, "fetch_video_comments", new_callable=AsyncMock) as fetch:
            fetch.return_value = [{"comment_id": "1", "author": SENTINEL_TIKTOK_NICKNAME, "text": "Đẹp quá", "likes": 1}]
            response = json.loads(await handle_get_tiktok_video_comments(video_url=TIKTOK_HANDLE_URL, limit=5))

    assert response["video_url"] == SHARE_LINK
    assert "author" not in response["comments"][0]
    assert _leaks(response) == []


@pytest.mark.asyncio
async def test_top_comments_for_keywords_carry_no_creator():
    plugin = TikTokPlugin(auth_manager=None)
    signal = TrendSignal(
        platform=PlatformType.TIKTOK, raw_title="Áo khoác", metric_value=10.0, source_url=TIKTOK_HANDLE_URL,
        metadata={"channel": SENTINEL_TIKTOK_HANDLE, "item_id": TIKTOK_ITEM_ID},
    )
    with patch.object(TikTokPlugin, "search_signals", new=AsyncMock(return_value=[signal])), \
            patch.object(TikTokPlugin, "fetch_video_comments", new=AsyncMock(return_value=[])):
        videos = await plugin.fetch_top_comments_for_keywords(["áo khoác"], max_videos=1)

    assert videos[0]["video_url"] == SHARE_LINK
    assert "author" not in videos[0]


# --- per-response concentration with a key that is never stored (T026) -------------------------


def _assigned(marker):
    from ignis.domain.author_identity import AuthorAssignment, AuthorState

    if marker is None:
        return AuthorAssignment(AuthorState.UNKNOWN)
    return AuthorAssignment(AuthorState.KNOWN, marker=marker)


@pytest.mark.asyncio
async def test_video_comments_report_concentration_without_any_author():
    components = _comment_components()
    comments = [
        {"comment_id": str(i), "text": "Giá bao nhiêu?", "likes": 0, "author_assignment": _assigned(marker)}
        for i, marker in enumerate(["a" * 16, "a" * 16, "b" * 16, None])
    ]
    with patch("ignis.interfaces.mcp.server.get_components", return_value=components):
        with patch.object(TikTokPlugin, "fetch_video_comments", new_callable=AsyncMock) as fetch:
            fetch.return_value = comments
            response = json.loads(await handle_get_tiktok_video_comments(video_url=TIKTOK_HANDLE_URL, limit=5))

    key = fetch.await_args.kwargs["author_key"]
    assert isinstance(key, bytes) and len(key) == 32
    assert response["author_concentration"] == {"distinct_authors": 2, "unknown": 1, "unavailable": 0, "top_share": 2 / 3}
    assert all("author_assignment" not in comment for comment in response["comments"])
    assert key.hex() not in json.dumps(response)
    components["repository"].get_or_create_mission_author_key.assert_not_called()


@pytest.mark.asyncio
async def test_pain_points_report_concentration_across_videos():
    payload = [
        {"video_url": SHARE_LINK, "video_title": "Áo khoác", "views": 1, "total_comments_fetched": 2,
         "comments": [
             {"comment_id": "1", "text": "Giá bao nhiêu?", "likes": 1, "author_assignment": _assigned("c" * 16)},
             {"comment_id": "2", "text": "Đẹp", "likes": 1, "author_assignment": _assigned("c" * 16)},
         ]},
        {"video_url": SHARE_LINK, "video_title": "Áo khoác 2", "views": 1, "total_comments_fetched": 1,
         "comments": [{"comment_id": "3", "text": "Có size không?", "likes": 1, "author_assignment": _assigned("d" * 16)}]},
    ]
    with patch("ignis.interfaces.mcp.server.get_components", return_value=_comment_components()):
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as fetch:
            fetch.return_value = payload
            response = json.loads(await handle_extract_customer_pain_points(keywords=["áo khoác"], geo="VN", max_videos=2))

    assert isinstance(fetch.await_args.kwargs["author_key"], bytes)
    assert response["author_concentration"]["distinct_authors"] == 2
    assert "author_assignment" not in json.dumps(response)


@pytest.mark.asyncio
async def test_the_plugin_marks_commenters_only_under_the_key_it_is_given():
    plugin = TikTokPlugin(auth_manager=None)
    raw = {"comments": [
        {"cid": "1", "user": {"unique_id": "sentinel.one", "uid": "11"}, "text": "Giá?", "digg_count": 0},
        {"cid": "2", "user": {"unique_id": "sentinel.one", "uid": "11"}, "text": "Size?", "digg_count": 0},
        {"cid": "3", "user": {"unique_id": "sentinel.two", "uid": "22"}, "text": "Đẹp", "digg_count": 0},
    ]}
    with patch("playwright.async_api.async_playwright") as playwright:
        page = AsyncMock()
        page.evaluate.return_value = raw
        p = AsyncMock()
        playwright.return_value.__aenter__.return_value = p
        p.chromium.launch.return_value.new_context.return_value.new_page.return_value = page
        marked = await plugin.fetch_video_comments(video_url=SHARE_LINK, limit=10, author_key=bytes(32))
        unmarked = await plugin.fetch_video_comments(video_url=SHARE_LINK, limit=10)

    markers = [c["author_assignment"].marker for c in marked]
    assert markers[0] == markers[1] != markers[2]
    assert all("author_assignment" not in c for c in unmarked)
    assert "sentinel" not in str([{k: v for k, v in c.items() if k != "author_assignment"} for c in marked])


# --- T038 review findings 5, 7, 15 and 16 -----------------------------------------------------------

MENTIONED = "sentinel.mention.linh"


@pytest.mark.asyncio
async def test_comment_answers_carry_no_raw_mention():
    comments = [{"comment_id": "1", "text": f"@{MENTIONED} giá bao nhiêu?", "likes": 0}]
    pain_points = [{"video_url": SHARE_LINK, "video_title": f"Hỏi @{MENTIONED}", "views": 1,
                    "total_comments_fetched": 1, "comments": [dict(comments[0])]}]
    with patch("ignis.interfaces.mcp.server.get_components", return_value=_comment_components()):
        with patch.object(TikTokPlugin, "fetch_video_comments", new_callable=AsyncMock) as fetch:
            fetch.return_value = [dict(comments[0])]
            video = await handle_get_tiktok_video_comments(video_url=SHARE_LINK, limit=5)
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new_callable=AsyncMock) as fetch:
            fetch.return_value = pain_points
            pains = await handle_extract_customer_pain_points(keywords=["áo"], geo="VN", max_videos=1)

    assert MENTIONED not in video and MENTIONED not in pains
    assert "@[user] giá bao nhiêu?" in video


@pytest.mark.asyncio
async def test_the_plugin_stores_no_raw_mention_in_comment_text():
    plugin = TikTokPlugin(auth_manager=None)
    with patch("playwright.async_api.async_playwright") as playwright:
        page = AsyncMock()
        page.evaluate.return_value = {"comments": [{"cid": "1", "text": f"@{MENTIONED} đẹp", "user": {}}]}
        p = AsyncMock()
        playwright.return_value.__aenter__.return_value = p
        p.chromium.launch.return_value.new_context.return_value.new_page.return_value = page
        comments = await plugin.fetch_video_comments(video_url=SHARE_LINK, limit=5)

    assert comments[0]["text"] == "@[user] đẹp"


def test_a_host_receipt_masks_mentions_in_the_excerpt():
    from ignis.application.use_cases.host_browser_search import _outward

    receipt = _outward({"observations": [{"source_url": TIKTOK_HANDLE_URL, "excerpt": f"@{MENTIONED} mua ở đâu"}]})

    assert receipt["observations"][0]["excerpt"] == "@[user] mua ở đâu"


@pytest.mark.asyncio
async def test_exception_text_never_carries_a_handle(caplog):
    caplog.set_level("DEBUG")
    failing = RuntimeError(f"Page.goto: net::ERR_ABORTED at {TIKTOK_HANDLE_URL}")
    plugin = TikTokPlugin(auth_manager=None)

    with patch("playwright.async_api.async_playwright", side_effect=failing):
        with pytest.raises(Exception) as raised:
            await plugin.fetch_video_comments(video_url=SHARE_LINK, limit=5)
    with patch("ignis.interfaces.mcp.server.get_components", return_value=_comment_components()):
        with patch.object(TikTokPlugin, "fetch_video_comments", new=AsyncMock(side_effect=failing)):
            video = await handle_get_tiktok_video_comments(video_url=SHARE_LINK, limit=5)
        with patch.object(TikTokPlugin, "fetch_top_comments_for_keywords", new=AsyncMock(side_effect=failing)):
            pains = await handle_extract_customer_pain_points(keywords=["áo"], geo="VN", max_videos=1)
    signal = TrendSignal(platform=PlatformType.TIKTOK, raw_title="x", source_url=TIKTOK_HANDLE_URL, metadata={})
    with patch.object(TikTokPlugin, "search_signals", new=AsyncMock(return_value=[signal])), \
            patch.object(TikTokPlugin, "fetch_video_comments", new=AsyncMock(side_effect=failing)):
        await plugin.fetch_top_comments_for_keywords(["áo"], max_videos=1)

    for text in (str(raised.value), video, pains, caplog.text):
        assert SENTINEL_TIKTOK_HANDLE not in text


def test_a_serialized_citation_renders_declared_tokens():
    from ignis.domain.harness_models import CitationEvidence
    from ignis.interfaces.mcp.server import _citation_declared_names, _serialize_citation

    declared = "6f1c2c47-8a43-4c1e-9b1e-3d7a2b9c0001"
    citation = CitationEvidence(
        citation_id="CIT-01", platform=PlatformType.TIKTOK, title_or_query=f"Áo của @[declared:{declared}]",
        metric_highlight="1 views", excerpt=f"@[declared:{declared}] đẹp",
    )

    with _citation_declared_names({declared: "Brand X"}):
        named = _serialize_citation(citation)
    anonymous = _serialize_citation(citation)

    assert (named["title_or_query"], named["excerpt"]) == ("Áo của @Brand X", "@Brand X đẹp")
    assert declared not in json.dumps(anonymous)


@pytest.mark.asyncio
async def test_an_evidence_batch_reads_the_declarations_once(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
    from tests.unit.test_evidence_qualification import _market

    repository = SqliteTrendRepository(str(tmp_path / "batch.sqlite"))
    store = WorkspaceRepository(repository=repository)
    workspaces = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / "host"
    host.mkdir()
    workspace = await workspaces.confirm(await workspaces.propose(host, "Batch"), confirmation=True)
    mission, _, _ = await _market(repository, store, workspace, ("a", "b", "c"))
    calls = []
    original = repository.list_mission_declared_accounts

    async def counted(mission_id):
        calls.append(mission_id)
        return await original(mission_id)

    repository.list_mission_declared_accounts = counted
    batch = await GetEvidenceQualificationBatchUseCase(repository=repository, store=store).execute(str(mission.id))
    await repository.close()

    assert len(batch["evidence"]) == 3
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_threads_host_public_receipt_has_no_header_attribution_or_mention(monkeypatch):
    from ignis.interfaces.mcp import server
    from ignis.application.use_cases import host_browser_search as module
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from tests.fixtures.author_identity_sentinels import SENTINEL_THREADS_HANDLE, SENTINEL_THREADS_ATTRIBUTED_NAME
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    service = module.HostBrowserSearchService()
    monkeypatch.setattr(server, "_host_browser_search_service", service)
    try:
        request = await server.handle_prepare_host_browser_search("task", "session", ["synthetic"], 3, 60, True,
                                                                 source="threads")
        payload = host_answer(request)
        payload["answers"][0]["records"][0]["source_url"] = f"https://www.threads.com/@{SENTINEL_THREADS_HANDLE}/post/Synthetic020"
        service.stage(request["request_id"], payload)
        receipt = await server.handle_submit_host_browser_search(request["request_id"], "task", "session")
        assert _leaks(receipt) == []
        assert SENTINEL_THREADS_ATTRIBUTED_NAME not in json.dumps(receipt)
        assert receipt["observations"][0]["source_url"] == "https://www.threads.com/t/Synthetic020"
    finally:
        service.close()
