"""Unknown host counters must not become zero-reach or maturity conclusions."""

import pytest
from datetime import datetime, timezone
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock

from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.harness_models import QualityScorecard, TrendMaturityStage
from ignis.domain.research_workspace import MissionProbeOutcome, QualificationContext, ResearchSurface
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin


@pytest.mark.parametrize("stats,known,expected", [
    ({}, False, 0),
    ({"diggCount": 400}, False, 0),
    ({"playCount": 0, "diggCount": 400}, True, 0),
    ({"play_count": "1200"}, True, 1200),
    ({"playCount": "unknown"}, False, 0),
])
def test_native_json_view_measurements_do_not_fall_back_to_likes(stats, known, expected):
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["notification"])
    signal = plugin._parse_json_item({"id": "123", "desc": "Túi đi làm",
        "author": {"uniqueId": "fixture"}, "stats": stats}, GeoCode.VN, "túi đi làm")
    assert signal is not None
    assert signal.metadata["metric_known"] is known
    assert signal.metric_value == expected
    assert QualityEvaluator().evaluate_quality([signal], GeoCode.VN, 30).data_freshness_score == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("counter", [None, "0", "1.2K"])
async def test_native_grid_preserves_missing_measurement_through_analysis(counter):
    plugin = TikTokPlugin()
    plugin.register_ui_noise(["notification"])
    card = SimpleNamespace(query_selector=AsyncMock(side_effect=[None, SimpleNamespace(
        get_attribute=AsyncMock(return_value="https://www.tiktok.com/@fixture/video/1234567890"),
    )]), inner_text=AsyncMock(return_value=(counter + "\n" if counter is not None else "") + "Túi đi làm\nfixture"))
    signal = await plugin._parse_dom_card(card, GeoCode.VN, "túi đi làm")
    assert signal.metadata["metric_known"] is False
    score = QualityEvaluator().evaluate_quality([signal], geo=GeoCode.VN, timeframe_days=30)
    assert score.data_freshness_score == 0
    assert any("Publication freshness unmeasured" in text for text in score.flaws_detected)
    report = StrategicMarketReasoner().analyze_mission(
        ResearchMission(title="Office bags", keywords=["túi đi làm"], surface=ResearchSurface.ATTENTION),
        [signal], [TopicCluster(canonical_name="Túi đi làm", signals=[signal])], score,
    )
    assert report.verified_cross_platform_trends[0]["total_estimated_reach"] is None
    assert report.maturity_stage is None


@pytest.mark.parametrize("measured", [False, True])
def test_attention_report_preserves_missing_reach_and_uses_only_measured_maturity(measured):
    signals = [TrendSignal(platform=PlatformType.TIKTOK, raw_title="Túi đi làm",
                           metric_value=0, geo_code=GeoCode.VN, metadata={"metric_known": False})]
    if measured:
        signals.append(TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Túi đi làm",
                                   metric_value=12000, geo_code=GeoCode.VN))
    mission = ResearchMission(title="Office bags", keywords=["túi đi làm"], surface=ResearchSurface.ATTENTION)
    report = StrategicMarketReasoner().analyze_mission(
        mission, signals, [TopicCluster(canonical_name="Túi đi làm", signals=signals)], QualityScorecard(),
    )
    assert report.maturity_stage == (TrendMaturityStage.EMERGING if measured else None)
    trend = report.verified_cross_platform_trends[0]
    assert trend["total_estimated_reach"] is None
    assert trend["measured_reach"] == (12000 if measured else None)
    assert trend["unmeasured_signals"] == 1
    assert all("steady viewer baseline" not in item.statement for item in report.strategic_insights)


def test_measured_zero_remains_a_real_measurement():
    signal = TrendSignal(platform=PlatformType.TIKTOK, raw_title="Túi đi làm", metric_value=0)
    report = StrategicMarketReasoner().analyze_mission(
        ResearchMission(title="Office bags", keywords=["túi đi làm"], surface=ResearchSurface.ATTENTION),
        [signal], [TopicCluster(canonical_name="Túi đi làm", signals=[signal])], QualityScorecard(),
    )
    assert report.verified_cross_platform_trends[0]["total_estimated_reach"] == 0


@pytest.mark.parametrize("window, expected", [(None, "Window unmeasured (VN)"), ("7d", "7d (VN)")])
def test_report_channel_window_comes_from_measurement_not_requested_timeframe(window, expected):
    mission = ResearchMission(title="Office bags", keywords=["túi đi làm"],
                              surface=ResearchSurface.ATTENTION, timeframe="30d", geo_code=GeoCode.VN)
    signal = TrendSignal(platform=PlatformType.TIKTOK, raw_title="Túi đi làm", observation_id=uuid4(),
                         metadata={"connector_surface": "tiktok_video", "metric_known": False})
    outcome = MissionProbeOutcome(run_id=uuid4(), platform="tiktok", connector_surface="tiktok_video",
        status="HEALTHY", signals_collected=1, query_fingerprint="a" * 64,
        completed_at=datetime.now(timezone.utc), queried_window=window)
    report = StrategicMarketReasoner().analyze_mission(mission, [signal], [], QualityScorecard(),
        qualification=QualificationContext.build([signal.observation_id], [], [outcome]))
    assert report.channel_summaries[0].timeframe_used == expected


def test_attention_report_suggests_explicit_assignment_not_periodic_collection():
    report = StrategicMarketReasoner().analyze_mission(
        ResearchMission(title="Office bags", keywords=["túi đi làm"], surface=ResearchSurface.ATTENTION),
        [], [], QualityScorecard())
    assert report.actionable_takeaways[-1].statement == (
        "Request a separately authorized bounded follow-up probe only when another research question is needed."
    )


@pytest.mark.parametrize("publication_known", [False, True])
def test_host_capture_time_cannot_prove_publication_freshness(publication_known):
    signal = TrendSignal(platform=PlatformType.TIKTOK, raw_title="Túi đi làm",
        published_at=datetime.now(timezone.utc) if publication_known else None,
        metadata={"collection_path": "host_browser:tiktok-public-grid-v1", "metric_known": False})
    score = QualityEvaluator().evaluate_quality([signal], geo=GeoCode.VN, timeframe_days=30)
    assert score.data_freshness_score == (100.0 if publication_known else 0.0)
    if not publication_known:
        assert not any("High data freshness" in item for item in score.strengths_detected)
        assert any("Publication freshness unmeasured" in item for item in score.flaws_detected)
        assert not any("contains outdated signals" in item for item in score.flaws_detected)
