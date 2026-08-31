import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from ignis.interfaces.mcp.server import (
    handle_get_trending_topics,
    handle_get_topic_detail,
    handle_generate_trend_artifact,
    handle_trigger_ingress_refresh,
)


@pytest.mark.asyncio
async def test_mcp_get_trending_topics(sample_topic_cluster):
    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_use_case = AsyncMock()
        mock_use_case.execute = AsyncMock(return_value=[sample_topic_cluster])
        mock_get_comp.return_value = {"top_clusters_use_case": mock_use_case}

        res_str = await handle_get_trending_topics(geo="VN", limit=5)
        res = json.loads(res_str)

        assert len(res) == 1
        assert res[0]["topic_name"] == sample_topic_cluster.canonical_name
        assert res[0]["cross_platform_score"] == sample_topic_cluster.cross_platform_score


@pytest.mark.asyncio
async def test_mcp_generate_trend_artifact(sample_topic_cluster):
    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_use_case = AsyncMock()
        mock_use_case.execute = AsyncMock(return_value=[sample_topic_cluster])
        mock_builder = MagicMock()
        mock_builder.build_dashboard_artifact.return_value = "<html>Dashboard Mock</html>"

        mock_get_comp.return_value = {
            "top_clusters_use_case": mock_use_case,
            "artifact_builder": mock_builder,
        }

        res_str = await handle_generate_trend_artifact(geo="VN")
        res = json.loads(res_str)
        assert res["status"] == "SUCCESS"
        assert "artifact_file" in res


@pytest.mark.asyncio
async def test_mcp_generate_mission_artifact():
    from ignis.interfaces.mcp.server import handle_generate_mission_artifact
    from ignis.domain.entities import ResearchMission
    from ignis.domain.value_objects import GeoCode, PlatformType
    from ignis.domain.harness_models import HarnessResearchReport, QualityScorecard, TrendMaturityStage

    sample_mission = ResearchMission(
        id=uuid4(),
        title="Test AI Mission",
        keywords=["AI agent"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        shortcode="TEST1234",
    )

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_mission = AsyncMock(return_value=sample_mission)
        mock_repo.get_mission_signals = AsyncMock(return_value=[])

        mock_top_clusters = AsyncMock()
        mock_top_clusters.execute = AsyncMock(return_value=[])

        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_quality.return_value = QualityScorecard(
            coverage_score=40.0,
            language_precision=100.0,
            data_freshness_score=100.0,
            creator_diversity_score=100.0,
            overall_confidence=80.0,
        )

        mock_reasoner = MagicMock()
        mock_reasoner.analyze_mission.return_value = HarnessResearchReport(
            mission_id=str(sample_mission.id),
            title=sample_mission.title,
            scorecard=mock_evaluator.evaluate_quality.return_value,
            maturity_stage=TrendMaturityStage.EMERGING,
            verified_cross_platform_trends=[],
            market_opportunities=[],
            strategic_insights=["Insight 1"],
            actionable_takeaways=["Action 1"],
        )

        mock_builder = MagicMock()
        mock_builder.build_mission_report_artifact.return_value = "<html>Mission Report Mock</html>"

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "top_clusters_use_case": mock_top_clusters,
            "quality_evaluator": mock_evaluator,
            "strategic_reasoner": mock_reasoner,
            "artifact_builder": mock_builder,
        }

        res_str = await handle_generate_mission_artifact(str(sample_mission.id))
        res = json.loads(res_str)
        assert res["status"] == "SUCCESS"
        assert res["shortcode"] == "TEST1234"
        assert "artifact_file" in res
        assert "file://" in res["file_url"]


@pytest.mark.asyncio
async def test_mcp_authenticate_tiktok():
    from ignis.interfaces.mcp.server import handle_authenticate_tiktok

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_auth = AsyncMock()
        mock_auth.authenticate_interactive.return_value = {
            "success": True,
            "platform": "tiktok",
            "message": "Auth OK",
        }
        mock_get_comp.return_value = {"tiktok_auth_manager": mock_auth}

        res_str = await handle_authenticate_tiktok(headless=True, timeout_seconds=10)
        res = json.loads(res_str)
        assert res["success"] is True
        assert res["platform"] == "tiktok"


@pytest.mark.asyncio
async def test_mcp_platform_auth_status_and_clear():
    from ignis.interfaces.mcp.server import handle_get_platform_auth_status, handle_clear_platform_auth

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.list_platform_credentials.return_value = [
            {"platform": "tiktok", "is_active": True, "auth_type": "session_cookies"}
        ]
        mock_repo.delete_platform_credentials.return_value = True
        mock_get_comp.return_value = {"repository": mock_repo}

        # Test get status
        res_str = await handle_get_platform_auth_status()
        res = json.loads(res_str)
        assert res["status"] == "SUCCESS"
        assert len(res["platforms"]) == 1
        assert res["platforms"][0]["platform"] == "tiktok"

        # Test clear
        clear_str = await handle_clear_platform_auth("tiktok")
        clear_res = json.loads(clear_str)
        assert clear_res["cleared"] is True
        assert clear_res["platform"] == "tiktok"

