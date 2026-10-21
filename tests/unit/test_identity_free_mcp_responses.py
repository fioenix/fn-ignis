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
