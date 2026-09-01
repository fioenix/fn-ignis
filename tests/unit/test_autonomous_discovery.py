import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.domain.harness_models import HarnessResearchReport, MarketOpportunity, TrendMaturityStage, QualityScorecard
from ignis.application.use_cases.autonomous_discovery import AutonomousDiscoveryUseCase
from ignis.interfaces.mcp.server import handle_trigger_autonomous_discovery


@pytest.mark.asyncio
async def test_autonomous_discovery_use_case_execution(tmp_path):
    mock_repo = AsyncMock()
    mock_repo.list_missions.return_value = []
    mock_repo.get_mission_signals.return_value = []
    
    mock_registry = AsyncMock()
    mock_registry._plugins = {}
    mock_registry.fetch_suggestions_across_all.return_value = [
        {
            "keyword": "ai agent",
            "suggestions": [
                {"query": "ai agent shop", "type": "search_guide"},
                {"query": "#xiaozhi", "type": "trending_hashtag"},
            ]
        }
    ]
    mock_registry.search_across_all.return_value = [
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="AI Agent Tutorial",
            metric_value=15000,
            growth_velocity=0.5,
            geo_code=GeoCode.VN,
            source_url="https://tiktok.com/@user/video/1",
        )
    ]

    mock_clusterer = AsyncMock()
    mock_clusterer.cluster_signals.return_value = []

    mock_quality = MagicMock()
    mock_quality.evaluate_quality.return_value = QualityScorecard(
        coverage_score=80.0,
        language_precision=90.0,
        data_freshness_score=95.0,
        creator_diversity_score=85.0,
        overall_confidence=87.5,
    )

    mock_reasoner = MagicMock()
    mock_reasoner.analyze_mission.return_value = HarnessResearchReport(
        mission_id="00000000-0000-0000-0000-000000000001",
        title="Autonomous Discovery Test",
        maturity_stage=TrendMaturityStage.EMERGING,
        market_opportunities=[
            MarketOpportunity(
                topic="AI Agent Shop",
                opportunity_type="HIGH_DEMAND_LOW_SUPPLY",
                search_interest_score=85.0,
                content_supply_score=10.0,
                opportunity_index=75.0,
                strategic_recommendation="Prime white space opportunity in e-commerce automation.",
            )
        ],
        strategic_insights=["Accelerating search interest across local retail channels."],
        actionable_takeaways=["Build localized MVP with pre-built e-commerce templates."],
        scorecard=mock_quality.evaluate_quality.return_value,
    )

    mock_builder = MagicMock()
    mock_builder.build_mission_report_artifact.return_value = "<html><body><h1>Discovery</h1></body></html>"

    use_case = AutonomousDiscoveryUseCase(
        repository=mock_repo,
        registry=mock_registry,
        clusterer=mock_clusterer,
        quality_evaluator=mock_quality,
        strategic_reasoner=mock_reasoner,
        artifact_builder=mock_builder,
        reports_dir=tmp_path,
    )

    result = await use_case.execute(geo=GeoCode.VN, max_macro_topics=2)

    assert result["status"] == "SUCCESS"
    assert result["geo_code"] == "VN"
    assert len(result["top_opportunities"]) == 1
    assert result["top_opportunities"][0]["topic"] == "AI Agent Shop"
    assert "daily_discovery_vn_" in result["artifact_file"]
    assert mock_repo.save_mission.called
    assert mock_repo.log_event.called


@pytest.mark.asyncio
async def test_handle_trigger_autonomous_discovery():
    mock_comp = {
        "autonomous_discovery_use_case": AsyncMock(),
    }
    mock_comp["autonomous_discovery_use_case"].execute.return_value = {
        "status": "SUCCESS",
        "shortcode": "DISCOVERY-VN-20260901",
        "total_signals": 25,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        resp_json = await handle_trigger_autonomous_discovery(geo="VN")
        resp = json.loads(resp_json)
        assert resp["status"] == "SUCCESS"
        assert resp["shortcode"] == "DISCOVERY-VN-20260901"
