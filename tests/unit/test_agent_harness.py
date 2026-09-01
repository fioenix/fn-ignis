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


def test_quality_evaluator_small_and_large_sample_size():
    evaluator = QualityEvaluator()
    small_signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Google Search Trends: Trợ lý AI",
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

    # Small sample (N=2 localized content signals) is penalized
    scorecard_small = evaluator.evaluate_quality(small_signals, geo=GeoCode.VN)
    assert scorecard_small.coverage_score >= 40.0
    assert scorecard_small.language_precision == 100.0
    assert scorecard_small.overall_confidence < 60.0
    assert any("Low localized dataset size" in f for f in scorecard_small.flaws_detected)

    # Large sample (N=16 localized signals) receives full confidence
    large_signals = list(small_signals)
    for i in range(14):
        large_signals.append(
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title=f"Video hướng dẫn AI Agent thực chiến phần {i+1}",
                metric_value=20000.0,
                geo_code=GeoCode.VN,
                metadata={"channel_title": f"Creator {i+1}"}
            )
        )
    scorecard_large = evaluator.evaluate_quality(large_signals, geo=GeoCode.VN)
    assert scorecard_large.overall_confidence >= 70.0

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
    assert opp.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "ENTERPRISE_GAP", "UNVERIFIED_DEMAND_GAP"]
    assert opp.search_interest_score == 95.0
    assert opp.opportunity_index > 0
    assert len(report.strategic_insights) > 0
    assert len(report.actionable_takeaways) > 0



def test_language_filter_portuguese_rejection():
    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    portuguese_title = "n8n Agents Chegou: Veja Como Funcionam os Novos Agentes Autônomos"
    french_title = "Formation Complète n8n Débutant avec Cas Pratique"
    vietnamese_title = "Hướng dẫn tự động hóa với n8n và AI agent cho doanh nghiệp"

    assert evaluator.is_vietnamese(portuguese_title) is False
    assert reasoner._is_vietnamese(portuguese_title) is False

    assert evaluator.is_vietnamese(french_title) is False
    assert reasoner._is_vietnamese(french_title) is False

    assert evaluator.is_vietnamese(vietnamese_title) is True
    assert reasoner._is_vietnamese(vietnamese_title) is True


def test_opportunity_index_sample_size_damping_and_label_alignment():
    reasoner = StrategicMarketReasoner()

    # Case 1: Single video with demand 90 -> raw OI is ~86, but damped
    signals_single = [
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="Google Search Trends: n8n", metric_value=90.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n cơ bản", metric_value=500.0),
    ]
    opps = reasoner._discover_market_opportunities(signals_single, ["n8n"])
    assert len(opps) == 1
    # Damping factor for N=1: 0.35 + 0.65*(1/5) = 0.48 -> damped OI is ~40.3
    assert opps[0].opportunity_index < 50.0

    # Case 2: Negative Opportunity Index (-30) must be SATURATED_SEGMENT, NOT GROWING_OPPORTUNITY
    signals_saturated = [
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="Google Search Trends: n8n", metric_value=30.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n 1", metric_value=50000.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n 2", metric_value=50000.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n 3", metric_value=50000.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n 4", metric_value=50000.0),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Hướng dẫn n8n 5", metric_value=50000.0),
    ]
    opps_sat = reasoner._discover_market_opportunities(signals_saturated, ["n8n"])
    assert opps_sat[0].opportunity_index < 0
    assert opps_sat[0].opportunity_type == "SATURATED_SEGMENT"
    assert "saturated" in opps_sat[0].strategic_recommendation.lower()


def test_language_filter_english_tech_rejection():
    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    english_chatbot_1 = "How to build an AI Chatbot with Flowise and LangChain"
    english_chatbot_2 = "Ultimate AI Agent Tutorial for Beginners (No Code)"
    english_chatbot_3 = "Building Custom GPTs vs AI Agents in 2026"
    vietnamese_chatbot = "Hướng dẫn tạo AI Chatbot chăm sóc khách hàng tự động cho shop"

    assert evaluator.is_vietnamese(english_chatbot_1) is False
    assert reasoner._is_vietnamese(english_chatbot_1) is False

    assert evaluator.is_vietnamese(english_chatbot_2) is False
    assert reasoner._is_vietnamese(english_chatbot_2) is False

    assert evaluator.is_vietnamese(english_chatbot_3) is False
    assert reasoner._is_vietnamese(english_chatbot_3) is False

    assert evaluator.is_vietnamese(vietnamese_chatbot) is True
    assert reasoner._is_vietnamese(vietnamese_chatbot) is True


def test_comedy_and_outlier_rejection():
    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    # Foreign script rejection (Korean / CJK)
    korean_video = "뚝배기 코팅 공정 및 자동화 (Tráng men nồi đất tự động)"
    assert evaluator.is_vietnamese(korean_video) is False
    assert reasoner._is_vietnamese(korean_video) is False

    # English technical title rejection
    cnc_video = "CNC Machining and Milling Automation Tutorial"
    assert evaluator.is_vietnamese(cnc_video) is False

    # Topic keyword isolation: video without topic keyword does not match
    unrelated_video = "Hệ thống nhà thông minh toàn diện"
    assert reasoner._matches_topic_strictly(unrelated_video, "tự động hóa ai") is False

    # Dynamic mission noise registration by Agent
    evaluator.register_noise_blacklist(["#namthầnkinh", "#funny"])
    reasoner.register_noise_blacklist(["#namthầnkinh", "#funny"])

    comedy_video = "Hệ thống tự động hóa toàn diện #namthầnkinh #funny"
    assert evaluator.is_vietnamese(comedy_video) is False
    assert reasoner._is_garbage(comedy_video) is True




