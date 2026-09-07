import pytest
from uuid import uuid4
from datetime import datetime, timezone
from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator


def test_bug08_matches_topic_strictly_handles_case_and_short_acronyms():
    reasoner = StrategicMarketReasoner()
    
    # "AI", "ai", "Ai" phải cho cùng kết quả
    assert reasoner._matches_topic_strictly("Video tạo bằng AI đỉnh cao", "AI")
    assert reasoner._matches_topic_strictly("Video tạo bằng AI đỉnh cao", "ai")
    assert reasoner._matches_topic_strictly("Video tạo bằng AI đỉnh cao", "Ai")
    
    # Keyword "ai agent" phải match với các video về AI hoặc AI Agent
    assert reasoner._matches_topic_strictly("Video tạo bằng AI đỉnh cao", "ai agent")
    assert reasoner._matches_topic_strictly("Hướng dẫn xây dựng AI Agent thực chiến", "ai agent")


def test_bug08_mission_analysis_catches_ai_cluster_for_ai_agent_keywords():
    reasoner = StrategicMarketReasoner()
    evaluator = QualityEvaluator()
    
    mission = ResearchMission(
        id=uuid4(),
        title="AI Market Research",
        keywords=["ai agent", "chatbot", "automation"],
        geo_code=GeoCode.VN,
    )
    
    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="AI",
            metric_value=85.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Video tạo bằng AI đỉnh cao hướng dẫn",
            metric_value=50000.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="Tự động hoá công việc với chatbot AI #congnghe",
            metric_value=20000.0,
            geo_code=GeoCode.VN,
        ),
    ]
    
    clusters = [
        TopicCluster(canonical_name="ai", cross_platform_score=78.6, signals=signals[:2]),
        TopicCluster(canonical_name="video tạo bằng AI", cross_platform_score=75.2, signals=[signals[1]]),
    ]
    
    scorecard = evaluator.evaluate_quality(signals, geo=GeoCode.VN)
    report = reasoner.analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
    )
    
    # Kiểm tra: phải có ít nhất 1 cơ hội thị trường được phát hiện, không bị NO_DATA_RECORDED toàn bộ
    active_opps = [opp for opp in report.market_opportunities if opp.opportunity_type != "NO_DATA_RECORDED"]
    assert len(active_opps) > 0, f"Phải bắt được cơ hội thị trường từ signals AI, thực tế: {[o.topic for o in report.market_opportunities]}"
    
    # overall_confidence không thể là 0.0
    assert scorecard.overall_confidence > 0.0
