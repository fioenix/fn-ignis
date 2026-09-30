"""Mission-bound execution stays idle until one confirmed task is explicitly run."""

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    MissionManifest,
    MissionOutputType,
    MissionTerminalStateError,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.infrastructure.connectors.registry import SearchPassResult, SurfaceProbeResult


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


class CountingClusterer:
    def __init__(self):
        self.calls = 0

    async def cluster_signals(self, _signals):
        self.calls += 1
        return []


class CountingRegistry:
    def __init__(self):
        self.authority_checks = 0
        self.connector_calls = 0

    async def resolve_execution_requirements(self, **_kwargs):
        self.authority_checks += 1
        return {
            "resources": ("youtube",),
            "authority": ("public_http",),
            "quota_costs": {"youtube_search_calls": 1},
        }

    async def search_with_outcomes(self, **_kwargs):
        self.connector_calls += 1
        return SearchPassResult(
            outcomes=[
                SurfaceProbeResult(
                    platform="youtube",
                    connector_surface="youtube",
                    status=ChannelHealthStatus.EMPTY_NO_DATA,
                    signals_collected=0,
                    queried_keywords=("retail setup friction",),
                    queried_window="7d",
                )
            ]
        )


class BoundaryRegistry:
    def __init__(self, requirements):
        self.requirements = requirements
        self.authority_checks = 0
        self.connector_calls = 0

    async def resolve_execution_requirements(self, **_kwargs):
        self.authority_checks += 1
        return self.requirements

    async def search_with_outcomes(self, **_kwargs):
        self.connector_calls += 1
        raise AssertionError("authority refusal must happen before a connector session opens")


class OptionalBrowserRegistry:
    def __init__(self):
        self.target_surfaces = None

    async def resolve_execution_requirements(self, **_kwargs):
        return {
            "resources": ("youtube", "threads"),
            "authority": ("official_api", "browser_session"),
            "quota_costs": {},
            "surface_requirements": {
                "youtube": {
                    "authority_tier": "official_api",
                    "requires_paid_quota": False,
                    "quota_costs": {},
                    "connector_path": "youtube.search",
                    "connector_revision": "v3",
                    "sampling": {"limit": 20, "ordering": "platform_default"},
                },
                "threads": {
                    "authority_tier": "browser_session",
                    "requires_paid_quota": False,
                    "quota_costs": {},
                    "connector_path": "threads.search",
                    "connector_revision": "browser-v1",
                    "sampling": {"limit": 20, "ordering": "platform_default"},
                },
            },
        }

    async def search_with_outcomes(self, **kwargs):
        self.target_surfaces = kwargs["target_surfaces"]
        return SearchPassResult(
            outcomes=[
                SurfaceProbeResult(
                    platform="youtube",
                    connector_surface="youtube",
                    status=ChannelHealthStatus.EMPTY_NO_DATA,
                    signals_collected=0,
                    queried_keywords=tuple(kwargs["keywords"]),
                    queried_window=kwargs["custom_timeframe"],
                )
            ]
        )


class CredentialLeakingRegistry(CountingRegistry):
    async def search_with_outcomes(self, **_kwargs):
        self.connector_calls += 1
        raise RuntimeError(
            "GET https://api.example.test/search?key=live-google-key-123&access_token=live-meta-token-456"
        )


class MixedStateRegistry:
    required = (
        "youtube",
        "google",
        "tiktok_video_grid",
        "tiktok_creative_center",
        "threads",
        "reels",
    )
    optional = ("tiktok_optional",)

    async def resolve_execution_requirements(self, **_kwargs):
        return {
            "resources": self.required,
            "authority": ("public_http",),
            "quota_costs": {},
            "unavailable_resources": (),
            "not_requested_resources": self.optional,
        }

    async def search_with_outcomes(self, **kwargs):
        keywords = tuple(kwargs["keywords"])
        window = kwargs["custom_timeframe"]
        statuses = (
            ("youtube", "youtube", ChannelHealthStatus.HEALTHY, 1),
            ("google", "google", ChannelHealthStatus.EMPTY_NO_DATA, 0),
            ("tiktok", "tiktok_video_grid", ChannelHealthStatus.AUTH_REQUIRED, 0),
            ("tiktok", "tiktok_creative_center", ChannelHealthStatus.RATE_LIMITED, 0),
            ("threads", "threads", ChannelHealthStatus.DEGRADED, 0),
            ("reels", "reels", ChannelHealthStatus.FAILED, 0),
        )
        outcomes = [
            SurfaceProbeResult(
                platform=platform,
                connector_surface=surface,
                status=status,
                signals_collected=count,
                note=(None if status is ChannelHealthStatus.HEALTHY else f"{status.value} test"),
                queried_keywords=keywords if status in {
                    ChannelHealthStatus.HEALTHY,
                    ChannelHealthStatus.EMPTY_NO_DATA,
                } else (),
                queried_window=window if status in {
                    ChannelHealthStatus.HEALTHY,
                    ChannelHealthStatus.EMPTY_NO_DATA,
                } else None,
            )
            for platform, surface, status, count in statuses
        ]
        signal = TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="One bounded observation",
            metric_value=1,
            source_url="https://youtube.example/watch?v=mixed-state",
            geo_code=GeoCode.VN,
            captured_at=NOW,
            metadata={"connector_surface": "youtube"},
        )
        return SearchPassResult(signals=[signal], outcomes=outcomes)


def _manifest():
    return MissionManifest(
        outcome="Collect one bounded evidence frame",
        decision_context=None,
        required_channels=("youtube",),
        optional_channels=(),
        authority_boundary=AuthorityBoundary(
            public_http=True,
            official_api=False,
            browser_session=False,
            paid_quota=False,
        ),
        quota_budget={"youtube_search_calls": 1},
        output_type=MissionOutputType.COLLECTION_FRAME,
        stop_conditions=("one run completed", "new authority required"),
        analysis_policy="evidence-gated-v1",
        retention_policy="mission-only",
        created_by="contract-test",
        confirmed_at=NOW,
    )


def _mixed_manifest():
    return replace(
        _manifest(),
        required_channels=MixedStateRegistry.required,
        optional_channels=MixedStateRegistry.optional,
        quota_budget={},
    )


def _optional_browser_manifest():
    return replace(
        _manifest(),
        required_channels=("youtube",),
        optional_channels=("threads",),
        authority_boundary=AuthorityBoundary(
            public_http=False,
            official_api=True,
            browser_session=False,
            paid_quota=False,
        ),
        quota_budget={},
    )


@pytest.mark.asyncio
async def test_idle_install_does_no_research_work_until_an_explicit_manifested_task(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(db_path=str(tmp_path / "idle.db"))
    store = WorkspaceRepository(repository=repository)
    registry = CountingRegistry()
    clusterer = CountingClusterer()
    executor = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        workspace_store=store,
    )

    # Constructing the runtime is not a task assignment.
    assert registry.authority_checks == 0
    assert registry.connector_calls == 0
    assert clusterer.calls == 0
    assert await repository.get_recent_logs(limit=20) == []
    assert not list(tmp_path.rglob("run-*.json"))
    assert not list(tmp_path.rglob("*.html"))
    repo_root = Path(__file__).resolve().parents[2]
    assert not (repo_root / "src/ignis/interfaces/cli/scheduler.py").exists()
    assert "ignis-worker" not in (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "fn-ignis-worker" not in (repo_root / "docker-compose.yml").read_text(encoding="utf-8")

    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / "host"
    host.mkdir()
    proposal = await workspace_case.propose(host, "Mission bound idle")
    workspace = await workspace_case.confirm(proposal, confirmation=True)
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="One explicit YouTube probe",
        keywords=["retail setup friction"],
        platforms=[PlatformType.YOUTUBE],
        manifest=_manifest(),
    )

    # Creating the confirmed assignment persists authority but still performs no collection.
    assert registry.authority_checks == 0
    assert registry.connector_calls == 0
    stored_manifest = await store.get_mission_manifest(mission.id)
    assert stored_manifest == replace(_manifest(), mission_id=mission.id)

    result = await executor.execute(mission.id)
    assert result["status"] == "COMPLETED"
    assert registry.authority_checks == 1
    assert registry.connector_calls == 1
    assert len(await store.list_run_journals(mission.id)) == 1
    journal_payload = json.loads(Path(result["run"]["journal_path"]).read_text(encoding="utf-8"))
    assert journal_payload["collection_plan"] == result["collection_plan"]
    assert journal_payload["collection_plan_digest"] == result["collection_plan_digest"]
    assert result["evidence_frame"]["collection_plan_digest"] == result["collection_plan_digest"]
    assert result["evidence_frame"]["manifest_digest"] == stored_manifest.manifest_digest
    assert len(result["channel_outcomes"]) == 1
    response_outcome = result["channel_outcomes"][0]
    assert response_outcome["connector_surface"] == "youtube"
    assert response_outcome["status"] == "EMPTY_NO_DATA"
    assert response_outcome["signals_collected"] == 0
    assert response_outcome["queried_keywords"] == ["retail setup friction"]
    assert response_outcome["queried_window"] == "7d"
    assert response_outcome["scope_attestation"] == {
        "geo": "VN",
        "timeframe": "7d",
        "keywords": ["retail setup friction"],
    }
    assert response_outcome["note"] == (
        "The attested scope returned no qualifying observations."
    )
    assert response_outcome["collection_plan_digest"] == result["collection_plan_digest"]
    assert len(response_outcome["query_fingerprint"]) == 64
    persisted_outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    assert persisted_outcomes[0].scope_attestation == {
        "geo": "VN",
        "timeframe": "7d",
        "keywords": ["retail setup friction"],
    }
    assert persisted_outcomes[0].note == (
        "The attested scope returned no qualifying observations."
    )
    assert result["channel_outcomes"] == [
        executor._probe_outcome_payload(persisted_outcomes[0])
    ]
    assert result["retention_policy"] == "mission-only"
    assert "Another mission" in result["reuse_limit"]

    with pytest.raises(MissionTerminalStateError):
        await executor.execute(mission.id)

    assert registry.authority_checks == 1
    assert registry.connector_calls == 1
    assert len(await store.list_run_journals(mission.id)) == 1
    await repository.close()


@pytest.mark.asyncio
async def test_mixed_channel_states_are_complete_and_match_persisted_outcomes(
    tmp_path, monkeypatch
):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.interfaces.mcp import server as mcp_server

    repository = SqliteTrendRepository(db_path=str(tmp_path / "mixed-states.db"))
    store = WorkspaceRepository(repository=repository)
    executor = ExecuteMissionUseCase(
        repository=repository,
        registry=MixedStateRegistry(),
        clusterer=CountingClusterer(),
        workspace_store=store,
    )
    host = tmp_path / "mixed-state-host"
    host.mkdir()
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, "Mixed channel states"), confirmation=True
    )
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Mixed channel states",
        keywords=["retail setup friction"],
        manifest=_mixed_manifest(),
    )

    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "repository": repository,
            "workspace_store": store,
            "execute_mission_use_case": executor,
        },
    )
    result = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))
    persisted = await store.get_latest_completed_probe_outcomes(mission.id)

    assert [item["connector_surface"] for item in result["channel_outcomes"]] == list(
        _mixed_manifest().allowed_resources
    )
    assert {item["status"] for item in result["channel_outcomes"]} == {
        status.value for status in ChannelHealthStatus
    }
    persisted_by_surface = {item.connector_surface: item for item in persisted}
    assert result["channel_outcomes"] == [
        executor._probe_outcome_payload(persisted_by_surface[surface])
        for surface in _mixed_manifest().allowed_resources
    ]
    by_surface = {item.connector_surface: item for item in persisted}
    assert by_surface["google"].measures_zero is True
    assert by_surface["tiktok_optional"].status is ChannelHealthStatus.NOT_REQUESTED
    optional_plan = result["collection_plan"]["probes"][-1]
    assert optional_plan["connector_surface"] == "tiktok_optional"
    assert optional_plan["authority_tier"] == "not-requested"
    assert optional_plan["connector_path"] == "unavailable"
    assert optional_plan["sampling"] == {"limit": 0, "ordering": "not_requested"}
    assert all(item.collection_plan_digest == result["collection_plan_digest"] for item in persisted)
    stored_manifest = await store.get_mission_manifest(mission.id)
    assert result["manifest_digest"] == stored_manifest.manifest_digest
    assert len(result["evidence_frame"]["frame_digest"]) == 64
    assert result["retention_policy"] == "mission-only"
    assert result["redaction_policy"] == "credentials-and-personal-data-redacted"
    assert result["platform_policy"] == "authorized-surface-terms-apply"
    assert "explicitly associate" in result["reuse_limit"]
    await repository.close()


@pytest.mark.asyncio
async def test_unauthorized_optional_surface_does_not_block_required_collection(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(db_path=str(tmp_path / "optional-browser.db"))
    store = WorkspaceRepository(repository=repository)
    registry = OptionalBrowserRegistry()
    executor = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=CountingClusterer(),
        workspace_store=store,
    )
    host = tmp_path / "optional-browser-host"
    host.mkdir()
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, "Optional browser"), confirmation=True
    )
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Required API with optional browser",
        keywords=["retail setup friction"],
        manifest=_optional_browser_manifest(),
    )

    result = await executor.execute(mission.id)

    assert result["status"] == "COMPLETED"
    assert registry.target_surfaces == ("youtube",)
    assert [item["status"] for item in result["channel_outcomes"]] == [
        "EMPTY_NO_DATA",
        "NOT_REQUESTED",
    ]
    await repository.close()


@pytest.mark.parametrize(
    "terminal_state",
    ["COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT_EVIDENCE"],
)
@pytest.mark.asyncio
async def test_every_terminal_state_refuses_continuation_before_any_side_effect(
    tmp_path, terminal_state
):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(db_path=str(tmp_path / f"{terminal_state}.db"))
    store = WorkspaceRepository(repository=repository)
    host = tmp_path / f"host-{terminal_state.lower()}"
    host.mkdir()
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, terminal_state), confirmation=True
    )
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Terminal state contract",
        keywords=["retail setup friction"],
        platforms=[PlatformType.YOUTUBE],
        manifest=_manifest(),
    )
    mission.status = terminal_state
    await repository.update_mission(mission)
    registry = CountingRegistry()
    clusterer = CountingClusterer()
    executor = ExecuteMissionUseCase(repository, registry, clusterer, workspace_store=store)

    with pytest.raises(MissionTerminalStateError) as exc_info:
        await executor.execute(mission.id)

    assert exc_info.value.status == terminal_state
    assert registry.authority_checks == 0
    assert registry.connector_calls == 0
    assert clusterer.calls == 0
    assert await store.list_run_journals(mission.id) == []
    assert not list(host.rglob("run-*.json"))
    assert not list(host.rglob("*.html"))
    await repository.close()


@pytest.mark.asyncio
async def test_attention_create_handler_returns_the_persisted_manifest_digest(tmp_path, monkeypatch):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.interfaces.mcp import server as mcp_server

    repository = SqliteTrendRepository(db_path=str(tmp_path / "handler-digest.db"))
    store = WorkspaceRepository(repository=repository)
    host = tmp_path / "handler-digest"
    host.mkdir()
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, "Handler digest"), confirmation=True
    )
    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "workspace_store": store,
            "create_attention_mission_use_case": CreateAttentionMissionUseCase(repository, store),
        },
    )
    manifest = _manifest()

    payload = json.loads(
        await mcp_server.handle_create_attention_mission(
            workspace_id=str(workspace.workspace_id),
            title="One explicit YouTube probe",
            keywords=["retail setup friction"],
            platforms=["youtube"],
            requested_outcome=manifest.outcome,
            allowed_resources=list(manifest.allowed_resources),
            authority_boundary=manifest.authority_boundary.to_payload(),
            output_type=manifest.output_type.value,
            stop_conditions=list(manifest.stop_conditions),
            retention_policy=manifest.retention_policy,
            quota_budget=dict(manifest.quota_budget),
            analysis_policy=manifest.analysis_policy,
        )
    )

    stored = await store.get_mission_manifest(payload["mission_id"])
    assert stored is not None
    assert payload["manifest_digest"] == stored.manifest_digest
    await repository.close()


@pytest.mark.asyncio
async def test_execution_failure_redacts_credentials_from_exception_log_and_mission(
    tmp_path, caplog
):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(db_path=str(tmp_path / "redacted-failure.db"))
    store = WorkspaceRepository(repository=repository)
    host = tmp_path / "redacted-failure"
    host.mkdir()
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, "Redacted failure"), confirmation=True
    )
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Credential-safe failure",
        keywords=["retail setup friction"],
        platforms=[PlatformType.YOUTUBE],
        manifest=_manifest(),
    )
    registry = CredentialLeakingRegistry()
    executor = ExecuteMissionUseCase(
        repository, registry, CountingClusterer(), workspace_store=store
    )

    with caplog.at_level("ERROR"), pytest.raises(RuntimeError) as exc_info:
        await executor.execute(mission.id)

    stored = await repository.get_mission(mission.id)
    rendered = " ".join((str(exc_info.value), caplog.text, stored.summary or ""))
    assert "live-google-key-123" not in rendered
    assert "live-meta-token-456" not in rendered
    assert "[REDACTED_SECRET]" in rendered
    await repository.close()


@pytest.mark.parametrize(
    ("requirements", "reason_code", "detail_field", "detail"),
    [
        (
            {
                "resources": ("youtube",),
                "authority": ("browser_session",),
                "quota_costs": {},
            },
            "MISSING_AUTHORITY",
            "missing_authority",
            "browser_session",
        ),
        (
            {
                "resources": ("reels",),
                "authority": ("public_http",),
                "quota_costs": {},
            },
            "OUT_OF_SCOPE_RESOURCE",
            "out_of_scope_resources",
            "reels",
        ),
    ],
)
@pytest.mark.asyncio
async def test_mcp_authority_refusal_opens_no_session_or_journal(
    tmp_path,
    monkeypatch,
    requirements,
    reason_code,
    detail_field,
    detail,
):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.interfaces.mcp import server as mcp_server

    repository = SqliteTrendRepository(db_path=str(tmp_path / f"{reason_code}.db"))
    store = WorkspaceRepository(repository=repository)
    workspace_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / reason_code.lower()
    host.mkdir()
    workspace = await workspace_case.confirm(
        await workspace_case.propose(host, reason_code), confirmation=True
    )
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="One explicit boundary probe",
        keywords=["retail setup friction"],
        platforms=[PlatformType.YOUTUBE],
        manifest=_manifest(),
    )
    registry = BoundaryRegistry(requirements)
    executor = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
        workspace_store=store,
    )
    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "repository": repository,
            "workspace_store": store,
            "execute_mission_use_case": executor,
        },
    )

    payload = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))

    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == reason_code
    assert detail in payload[detail_field]
    assert payload["note"] == "No connector session was opened and no run journal was created."
    assert registry.authority_checks == 1
    assert registry.connector_calls == 0
    assert await store.list_run_journals(mission.id) == []
    assert not list(host.rglob("run-*.json"))

    retry = json.loads(await mcp_server.handle_execute_mission_ingress(str(mission.id)))
    assert retry["status"] == "TERMINAL"
    assert retry["terminal_state"] == "BLOCKED"
    assert registry.authority_checks == 1
    assert registry.connector_calls == 0
    assert await store.list_run_journals(mission.id) == []
    await repository.close()
