"""Request-scoped host collection through the existing mission writer and ingestion."""

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone

from ignis.application.use_cases.execute_mission import TERMINAL_MISSION_STATES
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import ResearchSurface, resolve_surface
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.registry import SearchPassResult, SurfaceProbeResult


def snapshot_digest(snapshot):
    def encode(value):
        if dataclasses.is_dataclass(value):
            return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        if isinstance(value, Mapping):
            return dict(value)
        return str(value)
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                     default=encode, ensure_ascii=False).encode()).hexdigest()


async def prepare_scope(executor, mission_id):
    store = executor._workspace_store
    if store is None:
        raise ValueError("Confirmed mission workspace is required")
    snapshot = await store.load_mission_evidence_snapshot(mission_id)
    mission, manifest = snapshot.mission, snapshot.manifest
    if mission is None or manifest is None or not mission.workspace_id:
        raise ValueError("Confirmed mission scope is required")
    if mission.status.upper() in TERMINAL_MISSION_STATES or mission.status.upper() == "RUNNING":
        raise ValueError("Mission is not pending collection")
    if "tiktok_video" not in manifest.allowed_resources or not manifest.authority_boundary.browser_session:
        raise ValueError("Host TikTok search is outside confirmed authority")
    if resolve_surface(mission.surface) is ResearchSurface.MARKET and snapshot.brief is None:
        raise ValueError("Confirmed Market Brief is required")
    preliminary = await executor._build_collection_plan(mission, manifest, {})
    queries = executor._collection_queries(preliminary)
    remaining = tuple(surface for surface in manifest.allowed_resources if surface != "tiktok_video")
    requirements = await executor._registry.resolve_execution_requirements(
        target_platforms=mission.platforms, allowed_surfaces=remaining,
        required_surfaces=tuple(surface for surface in manifest.required_channels if surface in remaining),
        optional_surfaces=tuple(surface for surface in manifest.optional_channels if surface in remaining),
        keywords=queries,
    ) if remaining else dict(resources=(), authority=(), quota_costs={}, surface_requirements={})
    requirements = dict(requirements)
    if requirements.get("unavailable_resources"):
        raise ValueError("A required non-host surface is unavailable")
    requirements["resources"] = tuple(requirements.get("resources", ())) + ("tiktok_video",)
    requirements["surface_requirements"] = {
        **requirements.get("surface_requirements", {}), "tiktok_video": dict(
            authority_tier="browser_session", connector_path="host_browser:tiktok-public-grid-v1",
            quota_costs={},
            connector_revision="tiktok-public-grid-v1", sampling=dict(limit=20, ordering="visible_grid"),
        ),
    }
    requirements = executor._scope_optional_execution(manifest, requirements)
    if "queries" in manifest.quota_budget:
        requirements["quota_costs"] = {**requirements.get("quota_costs", {}), "queries": len(queries)}
    manifest.require_execution_authority(resources=requirements["resources"],
                                         authority=requirements["authority"],
                                         quota_costs=requirements["quota_costs"])
    if "tiktok_video" not in requirements["resources"]:
        raise ValueError("Host surface was not admitted by the mission budget")
    plan = await executor._build_collection_plan(mission, manifest, requirements)
    current = await store.load_mission_evidence_snapshot(mission_id)
    if snapshot_digest(current) != snapshot_digest(snapshot):
        raise ValueError("STALE_SCOPE")
    return dict(mission=mission, manifest=manifest, requirements=requirements, plan=plan,
                queries=executor._collection_queries(plan), digest=snapshot_digest(snapshot))


async def ingest_scope(executor, binding, receipt):
    def require_lifetime():
        if datetime.now(timezone.utc) >= binding["expires_at"]:
            raise ValueError("Host mission request expired")

    async def guard(journal):
        binding["run"] = dict(run_id=str(journal.run_id), journal_path=str(journal.journal_path))
        require_lifetime()
        current = await prepare_scope(executor, binding["mission"].id)
        require_lifetime()
        if current["digest"] != binding["digest"] or current["plan"] != binding["plan"]:
            raise ValueError("STALE_SCOPE")

    async def search(**kwargs):
        require_lifetime()
        if kwargs["keywords"] != binding["queries"]:
            raise ValueError("Collection query union changed")
        remaining = tuple(surface for surface in kwargs["target_surfaces"] if surface != "tiktok_video")
        other = await executor._registry.search_with_outcomes(**{**kwargs, "target_surfaces": remaining}) if remaining else SearchPassResult()
        require_lifetime()
        signals = [TrendSignal(
            platform=PlatformType.TIKTOK, raw_title=record["excerpt"], metric_value=0.0,
            source_url=record["source_url"], geo_code=binding["mission"].geo_code,
            captured_at=datetime.fromisoformat(record["captured_at"]),
            published_at=datetime.fromisoformat(record["published_at"]) if record["published_at"] else None,
            metadata={**record, "connector_surface": "tiktok_video", "keyword": record["query"],
                      "metric_known": False, "metric_kind": None},
        ) for record in receipt["observations"]]
        statuses = {item["status"] for item in receipt["outcomes"]}
        status = ("DEGRADED" if "DEGRADED" in statuses else
                  "HEALTHY" if signals else "EMPTY_NO_DATA")
        host = SurfaceProbeResult(
            platform="tiktok", connector_surface="tiktok_video", status=ChannelHealthStatus(status),
            signals_collected=len(signals), queried_keywords=tuple(binding["queries"]), queried_window=None,
            scope_attestation={"query_outcomes": receipt["outcomes"], "metric_known": False},
            authority_tier="browser_session", connector_path="host_browser:tiktok-public-grid-v1",
            connector_revision="tiktok-public-grid-v1", note="Host public grid; window and counters unmeasured",
        )
        return SearchPassResult(signals=list(other.signals) + signals, outcomes=list(other.outcomes) + [host])

    return await executor._execute_authorized(
        binding["mission"], binding["manifest"], binding["requirements"], scope_guard=guard,
        search_provider=search, expiry_guard=require_lifetime,
    )
