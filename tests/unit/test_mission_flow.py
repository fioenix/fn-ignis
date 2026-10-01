import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.interfaces.mcp.server import handle_generate_mission_artifact


@pytest.mark.asyncio
async def test_mission_artifact_generation():
    mission_id = uuid4()
    sample_mission = ResearchMission(
        id=mission_id,
        title="Xu hướng AI Agent 2026",
        keywords=["AI Agent", "FastMCP"],
        geo_code=GeoCode.VN,
        status="COMPLETED"
    )
    sample_signal = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="AI Agent Trends 2026",
        metric_value=90.0,
        mission_id=mission_id,
        geo_code=GeoCode.VN
    )

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_mission = AsyncMock(return_value=sample_mission)
        mock_repo.get_mission_signals = AsyncMock(return_value=[sample_signal])

        mock_top_clusters = AsyncMock()
        mock_top_clusters.execute = AsyncMock(return_value=[])

        mock_builder = MagicMock()
        mock_builder.build_mission_report_artifact.return_value = "<html>Mission Report Mock</html>"

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "top_clusters_use_case": mock_top_clusters,
            "quality_evaluator": QualityEvaluator(),
            "strategic_reasoner": StrategicMarketReasoner(),
            "artifact_builder": mock_builder,
        }

        res_str = await handle_generate_mission_artifact(str(mission_id))
        res = json.loads(res_str)
        assert res["status"] == "SUCCESS"
        assert "artifact_file" in res
        assert "file://" in res["file_url"]
