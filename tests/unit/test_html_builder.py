from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


def test_build_dashboard_artifact(sample_topic_cluster):
    builder = HtmlArtifactBuilder()
    html = builder.build_dashboard_artifact([sample_topic_cluster], geo=GeoCode.VN)

    assert "<!DOCTYPE html>" in html
    assert "FN-IGNIS" in html
    assert "Generative AI" in html
    assert str(sample_topic_cluster.cross_platform_score) in html
    assert "VN" in html


def test_build_topic_card_artifact(sample_topic_cluster, sample_trend_signal):
    builder = HtmlArtifactBuilder()
    html = builder.build_topic_card_artifact(sample_topic_cluster, [sample_trend_signal])

    assert "<!DOCTYPE html>" in html
    assert "Generative AI" in html
    assert sample_trend_signal.raw_title in html


def test_build_mission_report_artifact_with_qualitative_sections(sample_trend_signal):
    from ignis.domain.entities import ResearchMission
    from datetime import datetime, timezone
    builder = HtmlArtifactBuilder()

    mission = ResearchMission(
        title="AI Agent Market Opportunity in Vietnam",
        keywords=["ai agent", "chatbot"],
        shortcode="IGN-TEST",
        geo_code=GeoCode.VN,
        created_at=datetime.now(timezone.utc),
    )

    customer_inquiries = [
        {
            "author": "Nguyen Van A",
            "inquiry": "Giá bao nhiêu vậy shop? Có dùng được cho Mac không?",
            "likes": 5,
            "video_title": "AI Agent Overview",
        }
    ]

    search_suggestions = [
        {
            "keyword": "ai agent",
            "suggestions": [
                {"query": "ai agent tiktok shop", "type": "search_guide"},
                {"query": "#xiaozhi", "type": "trending_hashtag"},
            ]
        }
    ]

    macro_trends = [
        {
            "rank": 1,
            "hashtag": "#golivegrowfast",
            "category": "News & Entertainment",
            "views": "1.9B",
            "posts": "346K",
        }
    ]

    html = builder.build_mission_report_artifact(
        mission=mission,
        signals=[sample_trend_signal],
        platform_breakdown={"google_trends": 1, "tiktok": 1},
        customer_inquiries=customer_inquiries,
        search_suggestions=search_suggestions,
        macro_trends=macro_trends,
    )

    assert "<!DOCTYPE html>" in html
    assert "Voice of Customer" in html
    assert "Giá bao nhiêu vậy shop?" in html
    assert "Derivative Search Demand" in html
    assert "ai agent tiktok shop" in html
    assert "Macro Radar" in html
    assert "#golivegrowfast" in html


def test_html_builder_multi_currency_and_number_filters():
    builder = HtmlArtifactBuilder()
    currency_fn = builder._env.filters["format_currency"]
    number_fn = builder._env.filters["format_number"]

    assert currency_fn(150000, GeoCode.VN) == "150.000 ₫"
    assert currency_fn(150, GeoCode.US) == "$150"
    assert currency_fn(150.5, GeoCode.GLOBAL) == "$150.50"
    assert currency_fn(200, "SG") == "S$200"
    assert currency_fn(99, "EU") == "€99.00"

    assert number_fn(1500000) == "1.5M"
    assert number_fn(25400) == "25.4K"
    assert number_fn(850) == "850"




# --- Decision-grade evidence: the artifact renders the persisted qualification ------------------


def _qualified_html(report, mission, signals):
    return HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission, signals=signals, platform_breakdown={"youtube": len(signals)}, report=report,
    )


def _body(html):
    """The rendered page body, without the head scripts or the closing chart script."""
    return html.split("<body", 1)[1].rsplit("<script", 1)[0]


def _market_mission():
    from uuid import uuid4

    from ignis.domain.entities import ResearchMission

    return ResearchMission(
        title="Retail copilot", keywords=["ai retail"], shortcode="IGN-Q", surface="MARKET",
        workspace_id=uuid4(),
    )


def _report(surface, qualification, opportunities=(), handoff_status=None):
    from ignis.domain.harness_models import HarnessResearchReport, QualityScorecard

    return HarnessResearchReport(
        mission_id="m", title="Retail copilot", scorecard=QualityScorecard(question_relevance_score=3.3),
        maturity_stage=None, market_opportunities=list(opportunities), surface=surface,
        qualification=qualification, handoff_status=handoff_status,
    )


def _summary(status, reason=None, reason_code=None):
    from ignis.domain.harness_models import QualificationSummary

    return QualificationSummary(
        status=status, total_evidence=60, qualified_support=2, context_only=12,
        excluded_irrelevant=40, unassessed=6, question_relevance_score=3.7,
        reason=reason, reason_code=reason_code,
    )


def test_a_withheld_market_verdict_renders_the_reason_and_no_opportunity_index():
    mission = _market_mission()
    summary = _summary(
        "INSUFFICIENT_RELEVANT_EVIDENCE",
        "No topic has both qualified demand and qualified supply measurement.",
        "NO_SUFFICIENT_TOPIC",
    )
    html = _qualified_html(_report("MARKET", summary), mission, [])

    assert 'data-qualification-status="INSUFFICIENT_RELEVANT_EVIDENCE"' in html
    assert 'data-reason-code="NO_SUFFICIENT_TOPIC"' in html
    assert "No topic has both qualified demand and qualified supply measurement." in html
    for label, value in (("qualified_support", 2), ("context_only", 12),
                         ("excluded_irrelevant", 40), ("unassessed", 6)):
        assert f'data-count="{label}">{value}<' in html
    assert 'data-dimension="question_relevance">3.7' in html
    assert 'id="demandSupplyBarChart"' not in html, "the index chart was rendered"
    after_panel = _body(html).split("withheld-verdict", 1)[1]
    assert "Index:" not in after_panel and "Opportunity Index" not in after_panel
    assert "Withheld" in html


def test_a_ready_market_report_renders_its_opportunities():
    from ignis.domain.harness_models import MarketOpportunity

    mission = _market_mission()
    opportunity = MarketOpportunity(
        topic="ai retail", opportunity_type="GROWING_OPPORTUNITY", search_interest_score=60.0,
        content_supply_score=30.0, opportunity_index=16.5, strategic_recommendation="Runway.",
        evidence_sufficiency="SUFFICIENT_POSITIVE_SUPPLY",
    )
    html = _qualified_html(_report("MARKET", _summary("READY"), [opportunity]), mission, [])

    assert 'data-qualification-status="READY"' in html
    assert 'id="demandSupplyBarChart"' in html and "withheld-verdict" not in html


def test_an_attention_report_without_a_candidate_says_so_without_presenting_a_market_failure():
    mission = _market_mission()
    mission.surface = "ATTENTION"
    summary = _summary(
        "INSUFFICIENT_RELEVANT_EVIDENCE",
        "No cluster is directly relevant and backed by two independent sources.",
        "NO_QUALIFIED_CLUSTER",
    )
    html = _qualified_html(_report("ATTENTION", summary, handoff_status="NO_QUALIFIED_CANDIDATE"), mission, [])

    assert 'data-handoff-status="NO_QUALIFIED_CANDIDATE"' in html
    assert "No qualified handoff candidate" in html
    assert 'id="demandSupplyBarChart"' not in html, "the index chart was rendered"
    assert "Index:" not in _body(html)


def test_a_legacy_report_renders_no_qualification_section(sample_trend_signal):
    from ignis.domain.entities import ResearchMission

    mission = ResearchMission(title="Legacy", keywords=["ai"], shortcode="IGN-L")
    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission, signals=[sample_trend_signal], platform_breakdown={"youtube": 1},
    )

    assert "data-qualification-status" not in html
