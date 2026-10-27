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
from ignis.infrastructure.connectors.host_browser.validator import collection_path


def snapshot_digest(snapshot):
    def encode(value):
        if dataclasses.is_dataclass(value):
            return {field.name: getattr(value, field.name) for field in dataclasses.fields(value)}
        if isinstance(value, Mapping):
            return dict(value)
        return str(value)
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                     default=encode, ensure_ascii=False).encode()).hexdigest()


async def prepare_scope(executor, mission_id, source="tiktok"):
    store = executor._workspace_store
    if store is None:
        raise ValueError("Confirmed mission workspace is required")
    snapshot = await store.load_mission_evidence_snapshot(mission_id)
    mission, manifest = snapshot.mission, snapshot.manifest
    if mission is None or manifest is None or not mission.workspace_id:
        raise ValueError("Confirmed mission scope is required")
    if mission.status.upper() in TERMINAL_MISSION_STATES or mission.status.upper() == "RUNNING":
        raise ValueError("Mission is not pending collection")
    surface = "tiktok_video" if source == "tiktok" else "threads" if source == "threads" else None
    if surface not in manifest.allowed_resources or not manifest.authority_boundary.browser_session:
        raise ValueError("Host source is outside confirmed authority")
    host_sources = tuple(name for name, resource in (("tiktok", "tiktok_video"), ("threads", "threads"))
                         if resource in manifest.allowed_resources)
    host_surfaces = tuple("tiktok_video" if name == "tiktok" else name for name in host_sources)
    if resolve_surface(mission.surface) is ResearchSurface.MARKET and snapshot.brief is None:
        raise ValueError("Confirmed Market Brief is required")
    preliminary = await executor._build_collection_plan(mission, manifest, {})
    queries = executor._collection_queries(preliminary)
    remaining = tuple(surface for surface in manifest.allowed_resources if surface not in host_surfaces)
    requirements = await executor._registry.resolve_execution_requirements(
        target_platforms=mission.platforms, allowed_surfaces=remaining,
        required_surfaces=tuple(surface for surface in manifest.required_channels if surface in remaining),
        optional_surfaces=tuple(surface for surface in manifest.optional_channels if surface in remaining),
        keywords=queries,
    ) if remaining else dict(resources=(), authority=(), quota_costs={}, surface_requirements={})
    requirements = dict(requirements)
    if requirements.get("unavailable_resources"):
        raise ValueError("A required non-host surface is unavailable")
    requirements["resources"] = tuple(requirements.get("resources", ())) + host_surfaces
    requirements["surface_requirements"] = {**requirements.get("surface_requirements", {}), **{
        ("tiktok_video" if name == "tiktok" else name): dict(
            authority_tier="browser_session", quota_costs={},
            connector_path="host_browser:" + ("tiktok-public-grid-v1" if name == "tiktok" else "threads-search-top-v1"),
            connector_revision="tiktok-public-grid-v1" if name == "tiktok" else "threads-search-top-v1",
            sampling=dict(limit=20, ordering="visible_grid" if name == "tiktok" else "top_visible_sample"),
        ) for name in host_sources}}
    requirements = executor._scope_optional_execution(manifest, requirements)
    if "queries" in manifest.quota_budget:
        requirements["quota_costs"] = {**requirements.get("quota_costs", {}), "queries": len(queries)}
    manifest.require_execution_authority(resources=requirements["resources"],
                                         authority=requirements["authority"],
                                         quota_costs=requirements["quota_costs"])
    if surface not in requirements["resources"]:
        raise ValueError("Host surface was not admitted by the mission budget")
    plan = await executor._build_collection_plan(mission, manifest, requirements)
    current = await store.load_mission_evidence_snapshot(mission_id)
    if snapshot_digest(current) != snapshot_digest(snapshot):
        raise ValueError("STALE_SCOPE")
    return dict(mission=mission, manifest=manifest, requirements=requirements, plan=plan,
                queries=executor._collection_queries(plan), digest=snapshot_digest(snapshot), source=source,
                host_sources=tuple(name for name in host_sources
                                   if ("tiktok_video" if name == "tiktok" else name) in requirements["resources"]),
                required_host_sources=tuple(name for name in host_sources
                    if ("tiktok_video" if name == "tiktok" else name) in manifest.required_channels))


async def ingest_scope(executor, binding, receipt, *, author_records=None):
    # A legacy single-host receipt and a composed source receipt use the same writer seam.
    receipts = receipt.get("sources") or {binding.get("source", "tiktok"): receipt}
    host_surfaces = {"tiktok_video" if name == "tiktok" else name for name in binding["host_sources"]}
    def require_lifetime():
        if datetime.now(timezone.utc) >= binding["expires_at"]:
            raise ValueError("Host mission request expired")
        guard = binding.get("lifecycle_guard")
        if guard is not None:
            guard()

    async def guard(journal):
        binding["run"] = dict(run_id=str(journal.run_id), journal_path=str(journal.journal_path))
        require_lifetime()
        current = await prepare_scope(executor, binding["mission"].id, binding.get("source", "tiktok"))
        require_lifetime()
        if current["digest"] != binding["digest"] or current["plan"] != binding["plan"]:
            raise ValueError("STALE_SCOPE")

    async def search(**kwargs):
        require_lifetime()
        if kwargs["keywords"] != binding["queries"]:
            raise ValueError("Collection query union changed")
        remaining = tuple(surface for surface in kwargs["target_surfaces"] if surface not in host_surfaces)
        other = await executor._registry.search_with_outcomes(**{**kwargs, "target_surfaces": remaining}) if remaining else SearchPassResult()
        require_lifetime()
        signals, outcomes = list(other.signals), list(other.outcomes)
        for source in binding["host_sources"]:
            if source not in receipts:
                outcomes.append(SurfaceProbeResult(platform=source,
                    connector_surface="tiktok_video" if source == "tiktok" else source,
                    status=ChannelHealthStatus.NOT_REQUESTED, signals_collected=0,
                    note="Optional host source was not staged; no fallback was requested"))
        for source, staged in receipts.items():
            surface = "tiktok_video" if source == "tiktok" else source
            version = "tiktok-public-grid-v1" if source == "tiktok" else "threads-search-top-v1"
            path = collection_path(source, version, 20)
            host_signals = [TrendSignal(
                platform=PlatformType(source), raw_title=record["excerpt"], metric_value=0.0,
                source_url=record["source_url"], geo_code=binding["mission"].geo_code,
                captured_at=datetime.fromisoformat(record["captured_at"]),
                published_at=datetime.fromisoformat(record["published_at"]) if record["published_at"] else None,
                metadata={**record, **path, "connector_surface": surface, "keyword": record["query"],
                          "metric_known": False, "metric_kind": None},
            ) for record in (author_records[source] if author_records is not None else staged["observations"])]
            if author_records is not None:
                # Transfer only to the canonical transient signals; erase the staging sidecar.
                for record in author_records[source]:
                    record.clear()
                author_records[source].clear()
            statuses = {item["status"] for item in staged["outcomes"]}
            status = "DEGRADED" if "DEGRADED" in statuses else "HEALTHY" if host_signals else "EMPTY_NO_DATA"
            # Canonical executor assigns markers/declared tokens before any clustering or write.
            outcomes.append(SurfaceProbeResult(
                platform=source, connector_surface=surface, status=ChannelHealthStatus(status),
                signals_collected=len(host_signals), queried_keywords=tuple(binding["queries"]), queried_window=None,
                scope_attestation={"query_outcomes": staged["outcomes"], "metric_known": False, **path},
                authority_tier="browser_session", connector_path=path["collection_path"],
                connector_revision=version, note="Host visible sample; window and counters retain missingness",
            ))
            signals.extend(host_signals)
        return SearchPassResult(signals=signals, outcomes=outcomes)

    return await executor._execute_authorized(
        binding["mission"], binding["manifest"], binding["requirements"], scope_guard=guard,
        search_provider=search, expiry_guard=require_lifetime,
    )
