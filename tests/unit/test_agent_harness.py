import pytest
from datetime import datetime, timezone
from uuid import uuid4

from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.domain.harness_models import ConfidenceLevel, TrendMaturityStage
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner


def test_quality_evaluator_empty():
    evaluator = QualityEvaluator()
    scorecard = evaluator.evaluate_quality([])
    assert scorecard.overall_confidence == 0.0
    assert scorecard.confidence_level == ConfidenceLevel.UNRELIABLE
    assert len(scorecard.flaws_detected) > 0


def test_quality_evaluator_healthy_signals():
    evaluator = QualityEvaluator()
    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Google Search Trends: AI Agent",
            metric_value=90.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Hướng dẫn làm AI Agent từ A đến Z",
            metric_value=50000.0,
            geo_code=GeoCode.VN,
            metadata={"channel_title": "Channel A", "likes": 1200, "comments": 45}
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="AI Agent là gì và ứng dụng tự động hóa",
            metric_value=12000.0,
            geo_code=GeoCode.VN,
            metadata={"channel_title": "Channel B", "likes": 300, "comments": 20}
        ),
    ]

    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    assert scorecard.coverage_score >= 40.0
    assert scorecard.language_precision == 100.0
    assert scorecard.overall_confidence >= 60.0
    assert scorecard.confidence_level in [ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH]


def test_strategic_reasoner_white_space_discovery():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()

    mission = ResearchMission(
        id=uuid4(),
        title="Thị trường AI Agent",
        keywords=["AI Agent Enterprise", "n8n automation"],
        geo_code=GeoCode.VN
    )

    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Google Search Trends: AI Agent Enterprise",
            metric_value=95.0, # Nhu cầu search rất cao
            geo_code=GeoCode.VN,
            metadata={"keyword": "AI Agent Enterprise", "related_queries": ["ai agent doanh nghiệp"]}
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Hướng dẫn n8n cơ bản cho người mới",
            metric_value=100000.0,
            geo_code=GeoCode.VN,
            metadata={"keyword": "n8n automation", "channel_title": "Vincent AI"}
        ),
    ]

    clusters = [
        TopicCluster(canonical_name="AI Agent", cross_platform_score=75.0, signals=signals)
    ]

    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(mission, signals, clusters, scorecard)

    assert len(report.market_opportunities) == 2
    
    # Check White Space for 'AI Agent Enterprise' (search cao, 0 video YouTube)
    opp = next(o for o in report.market_opportunities if o.topic == "AI Agent Enterprise")
    assert opp.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "ENTERPRISE_GAP"]
    assert opp.search_interest_score == 95.0
    assert opp.opportunity_index > 0
    assert len(report.strategic_insights) > 0
    assert len(report.actionable_takeaways) > 0
