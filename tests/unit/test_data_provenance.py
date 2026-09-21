"""Epic 2 — Data Provenance, Ingress Health Audit & Citation Attribution Engine."""
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.harness_models import (
    ChannelHealthStatus,
    CitationEvidence,
    QualityScorecard,
    StrategicInsight,
    TrendMaturityStage,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


ALL_PLATFORMS = [
    PlatformType.GOOGLE_TRENDS,
    PlatformType.YOUTUBE,
    PlatformType.TIKTOK,
    PlatformType.THREADS,
    PlatformType.REELS,
]


def _mission(**kwargs) -> ResearchMission:
    defaults = dict(
        id=uuid4(),
        title="Thị trường AI Agent",
        keywords=["AI Agent Enterprise", "n8n automation"],
        platforms=list(ALL_PLATFORMS),
        geo_code=GeoCode.VN,
        timeframe="30d",
    )
    defaults.update(kwargs)
    return ResearchMission(**defaults)


def _signals():
    return [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Google Search Trends: AI Agent Enterprise",
            metric_value=95.0,
            growth_velocity=180.0,
            geo_code=GeoCode.VN,
            metadata={"keyword": "AI Agent Enterprise"},
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Hướng dẫn n8n cơ bản cho người mới bắt đầu",
            metric_value=120000.0,
            geo_code=GeoCode.VN,
            source_url="https://youtu.be/demo",
            metadata={"channel_title": "Vincent AI", "comments": 45},
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Xây dựng AI Agent cho doanh nghiệp Việt Nam",
            metric_value=8000.0,
            geo_code=GeoCode.VN,
            metadata={"channel_title": "AI Lab"},
        ),
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="Cách làm AI Agent bán hàng tự động cho shop",
            metric_value=52000.0,
            geo_code=GeoCode.VN,
            metadata={"author": "@shopai", "comments": 35, "top_comment": "Giá bao nhiêu vậy shop?"},
        ),
    ]


# --- test_channel_summary_generation -------------------------------------

def test_channel_summary_generation_covers_all_five_platforms():
    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(mission=_mission(), signals=_signals())

    assert len(summaries) == 5
    by_platform = {reasoner._platform_value(c.platform): c for c in summaries}
    assert set(by_platform) == {"google", "youtube", "tiktok", "threads", "reels"}

    # Channels holding signals are HEALTHY and carry a verifiable top citation.
    assert by_platform["youtube"].status == ChannelHealthStatus.HEALTHY
    assert by_platform["youtube"].signals_count == 2
    assert by_platform["youtube"].top_citation is not None
    # The top citation is the highest-engagement signal, not an arbitrary one.
    assert by_platform["youtube"].top_citation.title_or_query == "Hướng dẫn n8n cơ bản cho người mới bắt đầu"
    assert "120.0K views" in by_platform["youtube"].top_citation.metric_highlight
    assert by_platform["youtube"].top_citation.author_or_channel == "Vincent AI"
    assert by_platform["youtube"].timeframe_used == "30d (VN)"

    assert by_platform["google"].top_citation.metric_highlight.startswith("search index 95/100")

    # Zero-signal channels are reported with an explicit cause, never omitted.
    for empty in ("threads", "reels"):
        assert by_platform[empty].signals_count == 0
        assert by_platform[empty].status == ChannelHealthStatus.EMPTY_NO_DATA
        assert by_platform[empty].top_citation is None
        assert "No signals matched keywords" in by_platform[empty].notes


def test_channel_summary_flags_missing_auth_and_open_circuit_breaker():
    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(
        mission=_mission(),
        signals=_signals(),
        auth_status={"tiktok": True, "threads": True, "reels": False},
        connector_health={
            "threads_graph": {"platform": "threads", "circuit_state": "OPEN", "consecutive_failures": 3},
            "reels_graph": {"platform": "reels", "circuit_state": "CLOSED", "consecutive_failures": 0},
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "youtube_api": {"platform": "youtube", "circuit_state": "CLOSED"},
            "tiktok_grid": {"platform": "tiktok", "circuit_state": "CLOSED"},
        },
    )
    by_platform = {reasoner._platform_value(c.platform): c for c in summaries}

    assert by_platform["reels"].status == ChannelHealthStatus.AUTH_REQUIRED
    assert "token" in by_platform["reels"].notes.lower()

    assert by_platform["threads"].status == ChannelHealthStatus.DEGRADED
    assert "Circuit Breaker" in by_platform["threads"].notes


def test_channel_summary_detects_rate_limit_from_health_hint():
    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(
        mission=_mission(platforms=[PlatformType.YOUTUBE]),
        signals=[],
        connector_health={
            "youtube_api": {
                "platform": "youtube",
                "circuit_state": "OPEN",
                "consecutive_failures": 3,
                "last_error": "HTTP 429 quota exceeded",
            }
        },
    )
    assert summaries[0].status == ChannelHealthStatus.RATE_LIMITED


def test_channel_summary_ids_are_unique_and_sequential():
    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(mission=_mission(), signals=_signals())
    ids = [c.top_citation.citation_id for c in summaries if c.top_citation]
    assert ids == ["CIT-01", "CIT-02", "CIT-03"]


# --- test_citation_attribution_binding -----------------------------------

def test_citation_attribution_binding():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    mission = _mission()
    signals = _signals()
    clusters = [TopicCluster(canonical_name="AI Agent", cross_platform_score=75.0, signals=signals)]
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)

    report = reasoner.analyze_mission(mission, signals, clusters, scorecard)

    assert report.strategic_insights
    assert all(isinstance(i, StrategicInsight) for i in report.strategic_insights)

    cited = [i for i in report.strategic_insights if i.citations]
    assert cited, "At least one insight must be bound to concrete evidence."

    every_citation = [
        c for c in (
            [cit for i in report.strategic_insights for cit in i.citations]
            + [c.top_citation for c in report.channel_summaries if c.top_citation]
        )
    ]
    for insight in report.strategic_insights:
        assert insight.statement.strip()
    for cit in every_citation:
        assert isinstance(cit, CitationEvidence)
        assert cit.citation_id.startswith("CIT-")
        assert cit.title_or_query
        assert cit.metric_highlight

    # A citation id identifies one source across the whole dossier: the same
    # video cited by two insights must not read as two independent proofs.
    by_id = {}
    for cit in every_citation:
        by_id.setdefault(cit.citation_id, set()).add((str(cit.platform), cit.title_or_query))
    assert all(len(sources) == 1 for sources in by_id.values())


def test_attribute_citations_reuses_one_id_per_source():
    reasoner = StrategicMarketReasoner()
    signals = _signals()
    insights = reasoner.attribute_citations([
        ("First claim about the same video", [signals[1]]),
        ("Second claim about the same video", [signals[1]]),
    ])
    assert insights[0].citations[0].citation_id == insights[1].citations[0].citation_id


def test_attribute_citations_marks_unsupported_statements_as_uncited():
    reasoner = StrategicMarketReasoner()
    insights = reasoner.attribute_citations([
        ("Claim backed by data", _signals()[:1]),
        ("Claim with no evidence", []),
        ("   ", _signals()[:1]),  # blank statements are dropped
    ])
    assert len(insights) == 2
    assert insights[0].citations and insights[0].citations[0].citation_id == "CIT-01"
    assert insights[1].citations == []


def test_voice_of_customer_insight_cites_the_discussed_assets():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    signals = _signals()
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(_mission(), signals, [], scorecard)

    voc = [i for i in report.strategic_insights if "Voice of Customer" in i.statement]
    assert voc, "Comment-bearing signals must produce a Voice of Customer insight."
    assert "80 comments captured" in voc[0].statement
    assert voc[0].citations


def test_partial_ingress_coverage_is_reported_as_an_insight():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    signals = _signals()
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(
        _mission(),
        signals,
        [],
        scorecard,
        auth_status={"tiktok": True, "threads": False, "reels": False},
    )
    coverage = [i for i in report.strategic_insights if "Incomplete ingress coverage" in i.statement]
    assert coverage
    assert "THREADS (AUTH_REQUIRED)" in coverage[0].statement
    assert any("Restore empty ingress channels" in a.statement for a in report.actionable_takeaways)


# --- test_report_serialization_backward_compat ---------------------------

def test_report_serialization_backward_compat_with_legacy_string_insights():
    """Missions produced before Epic 2 stored plain strings; they must still render."""
    from ignis.infrastructure.templates.html_builder import _normalize_insights
    from ignis.interfaces.mcp.server import _serialize_insights, _serialize_channel_summaries

    legacy = ["Insight 1", "Insight 2"]

    normalized = _normalize_insights(legacy)
    assert normalized == [
        {"statement": "Insight 1", "citations": []},
        {"statement": "Insight 2", "citations": []},
    ]

    serialized = _serialize_insights(legacy)
    assert serialized == [
        {"statement": "Insight 1", "citations": []},
        {"statement": "Insight 2", "citations": []},
    ]
    assert json.dumps(serialized)

    # A legacy report simply has no channel audit; that must not raise.
    assert _serialize_channel_summaries(None) == []
    assert _serialize_channel_summaries([]) == []


def test_serialize_channel_summaries_produces_json_safe_payload():
    from ignis.interfaces.mcp.server import _serialize_channel_summaries

    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(mission=_mission(), signals=_signals())
    payload = _serialize_channel_summaries(summaries)

    assert len(payload) == 5
    assert payload[0]["platform"] == "google"
    assert payload[0]["status"] == "HEALTHY"
    assert payload[0]["top_citation"]["citation_id"] == "CIT-01"
    assert json.dumps(payload, ensure_ascii=False)


def test_html_builder_renders_legacy_string_insights_without_crashing(sample_trend_signal):
    from ignis.domain.harness_models import HarnessResearchReport

    legacy_report = HarnessResearchReport(
        mission_id=str(uuid4()),
        title="Legacy Mission",
        scorecard=QualityScorecard(overall_confidence=70.0),
        maturity_stage=TrendMaturityStage.EMERGING,
        strategic_insights=["Legacy plain string insight"],
        actionable_takeaways=["Legacy action"],
    )
    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=_mission(),
        signals=[sample_trend_signal],
        platform_breakdown={"google": 1},
        report=legacy_report,
    )
    assert "Legacy plain string insight" in html
    assert "NO DIRECT CITATION" in html
    # No channel audit on a legacy report -> the section is skipped, not broken.
    assert "Data Ingress &amp; Provenance Audit" not in html


# --- HTML generation test -------------------------------------------------

def test_html_renders_ingress_audit_table_and_citation_pills():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    mission = _mission()
    signals = _signals()
    clusters = [TopicCluster(canonical_name="AI Agent", cross_platform_score=75.0, signals=signals)]
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(
        mission,
        signals,
        clusters,
        scorecard,
        auth_status={"tiktok": True, "threads": True, "reels": False},
        connector_health={
            "threads_graph": {"platform": "threads", "circuit_state": "OPEN", "consecutive_failures": 3},
            "reels_graph": {"platform": "reels", "circuit_state": "CLOSED"},
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "youtube_api": {"platform": "youtube", "circuit_state": "CLOSED"},
            "tiktok_grid": {"platform": "tiktok", "circuit_state": "CLOSED"},
        },
    )

    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission,
        signals=signals,
        platform_breakdown={"google": 1, "youtube": 2, "tiktok": 1},
        report=report,
    )

    assert "<!DOCTYPE html>" in html
    assert "Data Ingress &amp; Provenance Audit" in html
    assert "3/5 channels healthy" in html
    # Every targeted channel gets a row, including the broken ones.
    for label in ("GOOGLE", "YOUTUBE", "TIKTOK", "THREADS", "REELS"):
        assert label in html
    assert "AUTH_REQUIRED" in html
    assert "DEGRADED" in html
    assert "Vincent AI" in html
    # Citation pill badges under the insights.
    assert "◆ [CIT-" in html
    assert "bg-blue-100 text-blue-800" in html


# --- MCP tool contract ----------------------------------------------------

@pytest.mark.asyncio
async def test_get_mission_analysis_exposes_channel_summaries_and_citations():
    from ignis.interfaces.mcp.server import handle_get_mission_analysis

    mission = _mission(shortcode="TEST-PROV")
    signals = _signals()
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_mission = AsyncMock(return_value=mission)
        mock_repo.get_mission_signals = AsyncMock(return_value=signals)
        mock_repo.get_domain_lexicons = AsyncMock(return_value=[])
        mock_repo.list_platform_credentials = AsyncMock(return_value=[
            {"platform": "tiktok", "is_active": True},
        ])

        mock_top_clusters = AsyncMock()
        mock_top_clusters.execute = AsyncMock(return_value=[])

        mock_registry = MagicMock()
        mock_registry.get_health_status.return_value = {
            "google_rss": {"platform": "google", "circuit_state": "CLOSED"},
            "youtube_api": {"platform": "youtube", "circuit_state": "CLOSED"},
            "tiktok_grid": {"platform": "tiktok", "circuit_state": "CLOSED"},
            "threads_graph": {"platform": "threads", "circuit_state": "CLOSED"},
            "reels_graph": {"platform": "reels", "circuit_state": "CLOSED"},
        }

        analysis_use_case = AsyncMock()
        analysis_use_case.execute = AsyncMock(return_value={
            "mission": {"id": str(mission.id), "title": mission.title},
            "stats": {},
            "top_signals": [],
        })

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "registry": mock_registry,
            "top_clusters_use_case": mock_top_clusters,
            "quality_evaluator": evaluator,
            "strategic_reasoner": reasoner,
            "get_mission_analysis_use_case": analysis_use_case,
        }

        payload = json.loads(await handle_get_mission_analysis(str(mission.id)))

    assert "channel_summaries" in payload
    assert len(payload["channel_summaries"]) == 5

    by_platform = {c["platform"]: c for c in payload["channel_summaries"]}
    assert by_platform["youtube"]["status"] == "HEALTHY"
    assert by_platform["youtube"]["top_citation"]["citation_id"].startswith("CIT-")
    # Threads/Reels have no stored credentials in this fixture.
    assert by_platform["threads"]["status"] == "AUTH_REQUIRED"
    assert by_platform["reels"]["status"] == "AUTH_REQUIRED"
    assert by_platform["tiktok"]["status"] == "HEALTHY"

    assert payload["strategic_insights"]
    assert all("statement" in i and "citations" in i for i in payload["strategic_insights"])


# --- RATE_LIMITED wiring through the real CircuitBreaker -------------------

def test_circuit_breaker_records_last_error_type():
    from ignis.infrastructure.connectors.registry import CircuitBreaker

    breaker = CircuitBreaker(failure_threshold=2)
    assert breaker.last_error_type is None

    breaker.record_failure(RuntimeError("HTTP 429 quota exceeded for youtube.data.v3"))
    assert breaker.last_error_type == "RuntimeError"
    assert "429" in breaker.last_error_message

    # A success clears the diagnosis so a stale cause is never reported.
    breaker.record_success()
    assert breaker.last_error_type is None
    assert breaker.last_error_message is None


def test_rate_limited_status_flows_from_registry_health_to_channel_audit():
    from ignis.application.ports.connector_port import IConnectorPlugin
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    class _QuotaExceededPlugin(IConnectorPlugin):
        platform = PlatformType.YOUTUBE
        name = "YouTube Quota Test"
        plugin_id = "youtube_quota_test"
        supports_search = True

        async def fetch_signals(self, geo=GeoCode.VN, timeframe=None):
            raise RuntimeError("HTTP 429: quota exceeded")

        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=None):
            raise RuntimeError("HTTP 429: quota exceeded")

        async def is_healthy(self) -> bool:
            return False

    registry = ConnectorPluginRegistry()
    registry.register(_QuotaExceededPlugin())

    breaker = registry._breakers["youtube_quota_test"]
    for _ in range(breaker.failure_threshold):
        breaker.record_failure(RuntimeError("HTTP 429: quota exceeded"))

    health = registry.get_health_status()
    assert health["youtube_quota_test"]["circuit_state"] == "OPEN"
    assert health["youtube_quota_test"]["last_error_type"] == "RuntimeError"

    summaries = StrategicMarketReasoner().summarize_channel_ingress(
        mission=_mission(platforms=[PlatformType.YOUTUBE]),
        signals=[],
        connector_health=health,
    )
    assert summaries[0].status == ChannelHealthStatus.RATE_LIMITED
    assert "429" in summaries[0].notes


def test_rate_limit_detection_reads_the_exception_type_alone():
    """A typed rate-limit error is enough; the message may carry no digits."""
    reasoner = StrategicMarketReasoner()
    summaries = reasoner.summarize_channel_ingress(
        mission=_mission(platforms=[PlatformType.TIKTOK]),
        signals=[],
        connector_health={
            "tiktok_grid": {
                "platform": "tiktok",
                "circuit_state": "OPEN",
                "consecutive_failures": 3,
                "last_error_type": "RateLimitException",
                "last_error": "blocked",
            }
        },
    )
    assert summaries[0].status == ChannelHealthStatus.RATE_LIMITED


# --- Language protocol ----------------------------------------------------

def test_dynamic_report_copy_is_rendered_in_english():
    """
    All machine-readable dynamic strings and insights generated by the Strategic
    Market Reasoner must be rendered in standard English.
    """
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    signals = _signals()
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(
        _mission(),
        signals,
        [TopicCluster(canonical_name="AI Agent", cross_platform_score=75.0, signals=signals)],
        scorecard,
        auth_status={"tiktok": True, "threads": False, "reels": False},
    )

    assert report.strategic_insights[0].statement.startswith("Market maturity stage")
    assert any(
        "Schedule periodic ingress surveillance" in a.statement
        for a in report.actionable_takeaways
    )
    assert all(
        any(marker in o.strategic_recommendation for marker in ("Opportunity Index", "equilibrium"))
        for o in report.market_opportunities
    )
    for ch in report.channel_summaries:
        if ch.notes:
            assert any(w in ch.notes for w in ("No signals", "Missing", "Circuit Breaker", "Rate limit"))
        if ch.top_citation:
            assert any(
                unit in ch.top_citation.metric_highlight
                for unit in ("views", "search index", "engagements")
            )


def test_jinja_template_carries_no_hardcoded_vietnamese():
    from pathlib import Path

    template = Path("src/ignis/infrastructure/templates/html/mission_report.html").read_text(encoding="utf-8")
    # Diacritics only ever arrive through injected data, never from the template.
    for marker in ("Không có tín hiệu", "Chưa cấu hình", "lượt xem", "Kênh chạm trần"):
        assert marker not in template
