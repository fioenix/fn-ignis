from datetime import datetime, timezone, timedelta
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator


def test_language_detector_multi_region():
    detector = HeuristicLanguageDetector()

    # 1. Vietnam (VN)
    assert detector.is_localized("Hướng dẫn xây dựng AI Agent cho doanh nghiệp", geo=GeoCode.VN)
    assert detector.is_localized("hoc lam ai agent tu dong hoa", geo=GeoCode.VN)
    assert not detector.is_localized("Como criar agentes autônomos grátis", geo=GeoCode.VN) # Portuguese
    assert not detector.is_localized("Formation complete intelligence artificielle", geo=GeoCode.VN) # French
    assert not detector.is_localized("챗GPT AI 에이전트 활용법", geo=GeoCode.VN) # Korean

    # 2. United States / English (US, GLOBAL)
    assert detector.is_localized("Building Autonomous AI Agents with LangChain", geo=GeoCode.US)
    assert detector.is_localized("Top 10 SaaS market trends in 2026", geo=GeoCode.GLOBAL)
    assert not detector.is_localized("챗GPT AI 에이전트 활용법", geo=GeoCode.US)
    assert not detector.is_localized("การสร้าง AI Agent สำหรับธุรกิจ", geo=GeoCode.US)

    # 3. Japan (JP)
    assert detector.is_localized("AIエージェントの業務自動化ガイド", geo=GeoCode.JP)
    assert not detector.is_localized("Building Autonomous AI Agents", geo=GeoCode.JP)

    # 4. Korea (KR)
    assert detector.is_localized("2026년 AI 에이전트 트렌드 분석", geo=GeoCode.KR)
    assert not detector.is_localized("Building Autonomous AI Agents", geo=GeoCode.KR)

    # 5. Thailand (TH)
    assert detector.is_localized("แนวโน้ม AI Agent ในปี 2026", geo=GeoCode.TH)
    assert not detector.is_localized("Building Autonomous AI Agents", geo=GeoCode.TH)

    # 6. Brazil (BR)
    assert detector.is_localized("Como criar agentes autônomos com inteligência artificial", geo=GeoCode.BR)
    assert detector.is_localized("Curso de automação para empresas", geo=GeoCode.BR)


def test_noise_blacklist_rejection_across_regions():
    detector = HeuristicLanguageDetector()
    noise = {"troll", "#funny", "hai kich"}

    assert not detector.is_localized("Video troll ban than cực mạnh", geo=GeoCode.VN, extra_noise=noise)
    assert not detector.is_localized("Funny prank troll compilation", geo=GeoCode.US, extra_noise=noise)
    assert detector.is_localized("Enterprise AI agent workflow", geo=GeoCode.US, extra_noise=noise)


def test_view_skew_outlier_not_firing_on_single_video():
    evaluator = QualityEvaluator()
    single_video = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Hướng dẫn làm AI Agent",
            metric_value=100000.0,
            geo_code=GeoCode.VN,
            metadata={"channel_title": "AI Master"}
        )
    ]
    scorecard = evaluator.evaluate_quality(single_video, geo=GeoCode.VN)
    # n=1 should not trigger "Severe view distribution skew"
    assert not any("Severe view distribution skew" in f for f in scorecard.flaws_detected)


def test_data_freshness_evaluation_with_published_at():
    evaluator = QualityEvaluator()
    now_utc = datetime.now(timezone.utc)
    old_date = (now_utc - timedelta(days=60)).isoformat()
    fresh_date = (now_utc - timedelta(days=5)).isoformat()

    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Video cũ hơn 30 ngày",
            metric_value=5000.0,
            geo_code=GeoCode.VN,
            metadata={"published_at": old_date}
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Video mới xuất bản 5 ngày",
            metric_value=8000.0,
            geo_code=GeoCode.VN,
            metadata={"published_at": fresh_date}
        ),
    ]

    # In a 30-day window, 1 of 2 is fresh -> 50%
    scorecard_30d = evaluator.evaluate_quality(signals, geo=GeoCode.VN, timeframe_days=30)
    assert scorecard_30d.data_freshness_score == 50.0

    # In a 90-day window, both are fresh -> 100%
    scorecard_90d = evaluator.evaluate_quality(signals, geo=GeoCode.VN, timeframe_days=90)
    assert scorecard_90d.data_freshness_score == 100.0
