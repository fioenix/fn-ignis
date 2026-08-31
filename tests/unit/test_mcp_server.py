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

        html = await handle_generate_trend_artifact(geo="VN")
        assert "<html>Dashboard Mock</html>" in html
