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


def test_evidence_grounded_gap_artifact_omits_every_forbidden_verdict_section():
    mission = _market_mission()
    contract = {
        "analysis_status": "INSUFFICIENT_EVIDENCE",
        "evidence_frame": {"frame_digest": "f" * 64},
        "gap_report": {
            "withheld_outputs": [
                "opportunity_index", "demand_gap", "whitespace", "saturation",
                "commercial_recommendations",
            ],
            "failed_gates": ["MISSING_CONTRADICTION_COVERAGE"],
            "missing_evidence": ["qualified counterevidence for a named hypothesis"],
            "attempted_probes": [],
            "safe_partial_conclusions": ["youtube returned 12 observations."],
            "next_best_probe": "Run one bounded falsification probe.",
            "required_authority": None,
            "estimated_cost": None,
        },
        "withheld_claim_count": 1,
        "withheld_reasons": ["MISSING_CONTRADICTION_COVERAGE"],
    }
    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission,
        signals=[],
        platform_breakdown={},
        analysis_contract=contract,
    )
    body = _body(html)

    assert 'data-analysis-status="INSUFFICIENT_EVIDENCE"' in body
    assert "Evidence contract is not sufficient" in body
    assert "MISSING_CONTRADICTION_COVERAGE" in body
    assert "Run one bounded falsification probe." in body
    assert "Market White Space Matrix" not in body
    assert "Strategic Insights" not in body
    assert "Action Blueprint" not in body
    assert "Strategic Takeaway" not in body
    assert "Opportunity Index" not in body


def test_evidence_grounded_ready_artifact_renders_claims_and_counterevidence():
    mission = _market_mission()
    contract = {
        "analysis_status": "READY",
        "evidence_frame": {"frame_digest": "f" * 64},
        "claim_ledger": {
            "INFERENCE": [{
                "wording": "Stockout pain is repeated across the qualified sample.",
                "client_claim_key": "claim-1",
                "evidence_bindings": [{
                    "observation_id": "obs-1",
                    "probe_outcome_id": None,
                    "role": "SUPPORT",
                    "hypothesis_target": "core",
                }],
                "limitations": ["The sample covers one seven-day window."],
                "change_conditions": ["A broader sample finds no repeated pain."],
            }]
        },
        "channel_outcomes": [{
            "connector_surface": "youtube",
            "status": "HEALTHY",
            "signals_collected": 4,
            "queried_window": "7d",
        }],
        "contradictory_evidence": [{
            "observation_id": "obs-counter",
            "hypothesis_target": "alternative:1",
            "purpose": "VOC",
        }],
        "retention_policy": "mission-only",
        "redaction_policy": "credentials-and-personal-data-redacted",
        "platform_policy": "authorized-surface-terms-apply",
        "reuse_limit": "Requalify against the receiving mission frame.",
    }
    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=mission,
        signals=[],
        platform_breakdown={},
        analysis_contract=contract,
    )

    assert 'data-claim-ledger' in html
    assert "Stockout pain is repeated across the qualified sample." in html
    assert "obs-1 → SUPPORT / core" in html
    assert "youtube → HEALTHY · 4 signal(s) · 7d" in html
    assert "The sample covers one seven-day window." in html
    assert "obs-counter" in html and "alternative:1" in html
    assert "mission-report/evidence-grounded-v1" in html
    assert "mission-only" in html
    assert "credentials-and-personal-data-redacted" in html
    assert "authorized-surface-terms-apply" in html
    assert "Requalify against the receiving mission frame." in html


def test_claim_artifact_redacts_private_values_from_a_raw_ledger_projection():
    contract = {
        "analysis_status": "READY",
        "evidence_frame": {"frame_digest": "f" * 64},
        "claim_ledger": {"OBSERVATION": [{
            "wording": "Participant synthetic@example.test reports a problem.",
            "client_claim_key": "claim-1", "evidence_bindings": [],
            "limitations": ["Call 0931405002"],
            "change_conditions": ["access_token=synthetic-not-a-live-credential"],
        }]},
        "channel_outcomes": [], "contradictory_evidence": [],
    }
    html = HtmlArtifactBuilder().build_mission_report_artifact(
        mission=_market_mission(), signals=[], platform_breakdown={}, analysis_contract=contract,
    )
    for private in ("synthetic@example.test", "0931405002", "synthetic-not-a-live-credential"):
        assert private not in html
    assert "[REDACTED_EMAIL]" in html
    assert "[REDACTED_PHONE]" in html
    assert "[REDACTED_SECRET]" in html
    assert contract["claim_ledger"]["OBSERVATION"][0]["wording"].startswith("Participant synthetic@")


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
