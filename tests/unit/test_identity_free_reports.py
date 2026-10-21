"""T019: reports and citations show content, never who posted it (Spec 015, FR-016).

Rows written before the policy still hold author fields and handle links, so the rendering layer
must not rely on ingress alone: it shows a declared name or nothing, and a link that names no
account or "link unavailable".
"""

from datetime import datetime, timezone

from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

from tests.fixtures.author_identity_sentinels import (
    SENTINEL_PROFILE_URL,
    SENTINEL_TIKTOK_COMMENTER,
    SENTINEL_YOUTUBE_CHANNEL_TITLE,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
    tiktok_metadata,
    undeclared_sentinels,
    youtube_metadata,
)

NOW = datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc)


def _legacy_signals():
    """Two rows as a pre-031 store holds them: author fields and handle links intact."""
    return [
        TrendSignal(
            platform=PlatformType.TIKTOK, raw_title="Review áo khoác", metric_value=900.0,
            source_url=TIKTOK_HANDLE_URL, geo_code=GeoCode.VN, captured_at=NOW, metadata=tiktok_metadata(),
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE, raw_title="Đánh giá áo khoác", metric_value=1200.0,
            source_url=SENTINEL_PROFILE_URL, geo_code=GeoCode.VN, captured_at=NOW,
            metadata={**youtube_metadata(), "video_id": None},
        ),
    ]


def test_a_citation_names_no_undeclared_author_and_links_without_a_handle():
    citation = StrategicMarketReasoner()._build_citation(_legacy_signals()[0], 1)

    assert citation.author_or_channel is None
    assert citation.url == f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}"


def test_a_report_over_legacy_rows_renders_no_author_identity():
    mission = ResearchMission(title="Áo khoác", keywords=["áo khoác"], shortcode="IGN-015", geo_code=GeoCode.VN)
    inquiries = [{"author": SENTINEL_TIKTOK_COMMENTER, "inquiry": "Giá bao nhiêu vậy shop?", "likes": 2}]

    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission,
        signals=_legacy_signals(),
        platform_breakdown={"tiktok": 1, "youtube": 1},
        customer_inquiries=inquiries,
    )

    assert [value for value in undeclared_sentinels() if value in html] == []
    assert SENTINEL_YOUTUBE_CHANNEL_TITLE not in html
    assert "Giá bao nhiêu vậy shop?" in html
    assert f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}" in html
    # The YouTube row has only a channel link, so it has no link a reader could open.
    assert "link unavailable" in html
