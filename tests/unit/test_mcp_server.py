import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from ignis.domain.value_objects import PlatformType


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


@pytest.mark.asyncio
async def test_mcp_verify_connectors_health():
    from ignis.interfaces.mcp.server import handle_verify_connectors_health

    with patch("ignis.interfaces.mcp.server.get_components") as mock_get_comp:
        mock_repo = AsyncMock()
        mock_repo.get_domain_lexicons.return_value = [{"term": "ai agent", "domain": "tech"}]

        mock_plugin = AsyncMock()
        mock_plugin.name = "YouTube Data API v3"
        mock_plugin.platform = PlatformType.YOUTUBE
        mock_plugin.is_healthy.return_value = True

        mock_registry = MagicMock()
        # The registry keys plugins by plugin_id; platform is read off the plugin.
        mock_registry._plugins = {"youtube": mock_plugin}

        mock_get_comp.return_value = {
            "repository": mock_repo,
            "registry": mock_registry,
        }

        res_str = await handle_verify_connectors_health()
        res = json.loads(res_str)
        assert res["overall_status"] == "HEALTHY"
        assert res["database"]["status"] == "HEALTHY"
        assert res["database"]["active_lexicons_count"] == 1
        assert "YouTube Data API v3" in res["connectors"]
        assert res["connectors"]["YouTube Data API v3"]["status"] == "HEALTHY"




# --- User Story 1: mission ingress needs no earlier analysis call to be configured ---------------


def test_the_server_wires_one_synchronizer_into_mission_ingress(monkeypatch):
    """The synchronizer the mission path calls is bound to the very plugins the registry probes."""
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.interfaces.mcp import server as mcp_server

    monkeypatch.setattr(
        mcp_server, "create_repository", lambda: SqliteTrendRepository("sqlite:///:memory:")
    )
    comp = mcp_server._init_components()

    synchronizer = comp["vocabulary_synchronizer"]
    assert comp["execute_mission_use_case"]._vocabulary_sync is synchronizer
    assert synchronizer._tiktok_plugin is comp["tiktok_plugin"]
    assert synchronizer._google_trends_plugin is comp["google_trends_plugin"]
    assert synchronizer._registry is comp["registry"]
    assert synchronizer._clusterer is comp["clusterer"]
    assert comp["registry"].get_plugin_by_id("tiktok_video_grid") is comp["tiktok_plugin"]


def test_the_server_wires_youtube_to_the_shared_repository_quota_manager(monkeypatch):
    from pydantic import SecretStr

    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.interfaces.mcp import server as mcp_server

    repository = SqliteTrendRepository("sqlite:///:memory:")
    monkeypatch.setattr(mcp_server, "create_repository", lambda: repository)
    monkeypatch.setattr(mcp_server.settings, "YOUTUBE_API_KEY", SecretStr("test-key"))

    comp = mcp_server._init_components()
    plugin = comp["registry"].get_plugin_by_id("youtube")

    assert plugin._quota_manager._repository is repository


@pytest.mark.asyncio
async def test_connector_health_exposes_secret_free_youtube_quota_state():
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    from ignis.domain.value_objects import PlatformType
    from ignis.interfaces.mcp.server import handle_verify_connectors_health

    class YouTubePlugin:
        name = "YouTube Data API v3"
        platform = PlatformType.YOUTUBE
        _api_key = "must-not-appear"

        async def is_healthy(self):
            return True

        async def quota_status(self):
            return {
                "quota_day": "2026-09-29",
                "next_reset_at": "2026-09-30T07:00:00+00:00",
                "buckets": {
                    "search_list": {
                        "used": 70,
                        "scheduled_used": 70,
                        "limit": 100,
                        "scheduled_limit": 70,
                        "exhausted": False,
                    },
                    "default_units": {
                        "used": 4,
                        "scheduled_used": 0,
                        "limit": 10_000,
                        "scheduled_limit": None,
                        "exhausted": False,
                    },
                },
            }

    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = []
    repository.list_platform_credentials.return_value = []
    registry = MagicMock()
    registry._plugins = {"youtube": YouTubePlugin()}
    registry._breakers = {}

    with patch(
        "ignis.interfaces.mcp.server.get_components",
        return_value={"repository": repository, "registry": registry},
    ):
        raw = await handle_verify_connectors_health()

    payload = json.loads(raw)
    youtube = payload["connectors"]["YouTube Data API v3"]
    assert youtube["quota"]["buckets"]["search_list"] == {
        "used": 70,
        "scheduled_used": 70,
        "limit": 100,
        "scheduled_limit": 70,
        "exhausted": False,
    }
    assert "must-not-appear" not in raw


@pytest.mark.asyncio
async def test_connector_health_reads_quota_after_its_provider_probe():
    from ignis.interfaces.mcp.server import handle_verify_connectors_health

    class YouTubePlugin:
        name = "YouTube Data API v3"
        platform = PlatformType.YOUTUBE

        def __init__(self):
            self.used = 0

        async def is_healthy(self):
            self.used += 1
            return True

        async def quota_status(self):
            return {
                "quota_day": "2026-09-29",
                "next_reset_at": "2026-09-30T07:00:00+00:00",
                "buckets": {"default_units": {"used": self.used, "limit": 10_000}},
            }

    repository = AsyncMock()
    repository.get_domain_lexicons.return_value = []
    repository.list_platform_credentials.return_value = []
    registry = MagicMock()
    registry._plugins = {"youtube": YouTubePlugin()}
    registry._breakers = {}

    with patch(
        "ignis.interfaces.mcp.server.get_components",
        return_value={"repository": repository, "registry": registry},
    ):
        raw = await handle_verify_connectors_health()

    youtube = json.loads(raw)["connectors"]["YouTube Data API v3"]
    assert youtube["quota"]["buckets"]["default_units"]["used"] == 1


@pytest.mark.asyncio
async def test_execute_mission_ingress_synchronizes_before_any_connector_call_as_the_first_operation():
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.domain.entities import ResearchMission
    from ignis.infrastructure.connectors.registry import SearchPassResult
    from ignis.interfaces.mcp.server import handle_execute_mission_ingress

    order = []

    class Synchronizer:
        async def synchronize(self):
            order.append("synchronize")

    class Registry:
        async def search_with_outcomes(self, **_kwargs):
            order.append("connector")
            return SearchPassResult()

    mission = ResearchMission(title="Cold start", keywords=["ai retail"])
    repository = MagicMock()
    repository.get_mission = AsyncMock(return_value=mission)
    repository.get_mission_signals = AsyncMock(return_value=[])
    repository.update_mission = AsyncMock()
    repository.prune_mission_evidence = AsyncMock(return_value=0)
    use_case = ExecuteMissionUseCase(
        repository=repository, registry=Registry(), clusterer=MagicMock(),
        vocabulary_sync=Synchronizer(),
    )

    with patch("ignis.interfaces.mcp.server.get_components") as get_components:
        get_components.return_value = {"repository": repository, "execute_mission_use_case": use_case}
        payload = json.loads(await handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "COMPLETED"
    assert order == ["synchronize", "connector"]


@pytest.mark.asyncio
async def test_a_vocabulary_failure_is_a_structured_refusal_not_a_transport_error():
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.domain.entities import ResearchMission
    from ignis.domain.exceptions import VocabularySynchronizationError
    from ignis.interfaces.mcp.server import handle_execute_mission_ingress

    class Unreadable:
        async def synchronize(self):
            raise VocabularySynchronizationError("market_lexicons is unreadable")

    registry = MagicMock()
    registry.search_with_outcomes = AsyncMock()
    mission = ResearchMission(title="Cold start", keywords=["ai retail"])
    repository = MagicMock()
    repository.get_mission = AsyncMock(return_value=mission)
    repository.update_mission = AsyncMock()
    use_case = ExecuteMissionUseCase(
        repository=repository, registry=registry, clusterer=MagicMock(),
        vocabulary_sync=Unreadable(),
    )

    with patch("ignis.interfaces.mcp.server.get_components") as get_components:
        get_components.return_value = {"repository": repository, "execute_mission_use_case": use_case}
        payload = json.loads(await handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "FAILED"
    assert payload["operation"] == "execute_mission_ingress"
    assert "market_lexicons is unreadable" in payload["error"]
    assert "No connector was called" in payload["note"]
    registry.search_with_outcomes.assert_not_called()
