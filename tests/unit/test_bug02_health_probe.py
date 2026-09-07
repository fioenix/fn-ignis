import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ignis.domain.value_objects import PlatformType
from ignis.interfaces.mcp.server import handle_verify_connectors_health


@pytest.mark.asyncio
async def test_bug02_health_probe_empty_returns_degraded():
    """AC-1 & AC-2: Khi connector có synthetic_probe trả về rỗng, gán status PARSE_EMPTY và overall DEGRADED."""
    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_domain_lexicons.return_value = [{"term": "test"}]

        mock_plugin = AsyncMock()
        mock_plugin.name = "Mock Probed Plugin"
        mock_plugin.platform = PlatformType.TIKTOK
        mock_plugin.is_healthy.return_value = True
        mock_plugin.synthetic_probe.return_value = []  # Trả về rỗng

        mock_registry = MagicMock()
        mock_registry._plugins = {"tiktok": mock_plugin}
        mock_registry._breakers = {}

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "registry": mock_registry,
        }

        res_str = await handle_verify_connectors_health()
        res = json.loads(res_str)

        assert res["overall_status"] == "DEGRADED"
        assert res["connectors"]["Mock Probed Plugin"]["status"] == "PARSE_EMPTY"
        assert any(a["type"] == "PROBE_RETURNED_EMPTY" for a in res["alerts"])


@pytest.mark.asyncio
async def test_bug02_database_write_failure_alert():
    """AC-3: Khi repo.save_clusters gặp lỗi, phát hiện DATABASE_WRITE_FAILURE và overall DEGRADED."""
    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_domain_lexicons.return_value = [{"term": "test"}]
        mock_repo.save_clusters.side_effect = RuntimeError("Disk full / read only error")

        mock_registry = MagicMock()
        mock_registry._plugins = {}
        mock_registry._breakers = {}

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "registry": mock_registry,
        }

        res_str = await handle_verify_connectors_health()
        res = json.loads(res_str)

        assert res["overall_status"] == "DEGRADED"
        assert res["database"]["write_probe"] == "FAILED"
        assert any(a["type"] == "DATABASE_WRITE_FAILURE" for a in res["alerts"])
