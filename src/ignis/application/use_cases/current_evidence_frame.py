"""Derive the current evidence-frame identity from persisted mission facts."""

from typing import Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.research_workspace import (
    EvidenceFrame,
    InvalidMissionClaimError,
    MissionManifest,
    build_evidence_frame,
)


async def load_current_evidence_frame(
    repository: ITrendRepository,
    store: IResearchWorkspaceStore,
    mission,
    manifest: Optional[MissionManifest] = None,
) -> EvidenceFrame:
    """Build the one canonical current frame; never accept a caller-supplied digest as current."""

    manifest = manifest or await store.get_mission_manifest(mission.id)
    if manifest is None:
        raise InvalidMissionClaimError(
            "A surfaced mission needs its persisted Mission Manifest before a frame can be derived."
        )
    brief = await store.get_brief_revision_for_mission(mission.id)
    signals = await repository.get_mission_signals(mission.id)
    qualifications = await store.list_evidence_qualifications(mission.id)
    outcomes = await store.get_latest_completed_probe_outcomes(mission.id)
    plan_digests = {
        outcome.collection_plan_digest
        for outcome in outcomes
        if outcome.collection_plan_digest is not None
    }
    if len(plan_digests) != 1 or any(
        outcome.collection_plan_digest is None for outcome in outcomes
    ):
        raise InvalidMissionClaimError(
            "The latest completed run does not identify one complete collection plan."
        )
    collection_plan_digest = next(iter(plan_digests))

    observations = [
        {
            "observation_id": str(signal.observation_id),
            "source_id": str(signal.source_id) if signal.source_id else None,
            "platform": (
                signal.platform.value
                if hasattr(signal.platform, "value")
                else str(signal.platform)
            ),
            "raw_title": signal.raw_title,
            "metric_value": signal.metric_value,
            "growth_velocity": signal.growth_velocity,
            "source_url": signal.source_url,
            "geo_code": (
                signal.geo_code.value
                if hasattr(signal.geo_code, "value")
                else str(signal.geo_code)
            ),
            "cluster_id": str(signal.cluster_id) if signal.cluster_id else None,
            "identity_source": signal.identity_source,
            "time_provenance": signal.time_provenance,
            "metadata": dict(signal.metadata or {}),
            "captured_at": signal.captured_at,
            "published_at": signal.published_at,
        }
        for signal in signals
    ]
    qualification_records = [
        {
            "mission_id": str(item.mission_id),
            "observation_id": str(item.observation_id),
            "frame_fingerprint": item.frame_fingerprint,
            "brief_revision_id": (
                str(item.brief_revision_id) if item.brief_revision_id else None
            ),
            "relation": item.relation.value,
            "purpose": item.purpose.value,
            "confidence": item.confidence,
            "reason_code": item.reason_code.value,
            "judged_by": item.judged_by,
            "model": item.model,
            "created_at": item.created_at,
            "hypothesis_target": item.hypothesis_target,
            "evidence_role": item.evidence_role.value if item.evidence_role else None,
            "evidence_contract_version": item.evidence_contract_version,
        }
        for item in qualifications
    ]
    outcome_records = [
        {
            "outcome_id": str(item.outcome_id),
            "run_id": str(item.run_id),
            "platform": item.platform,
            "connector_surface": item.connector_surface,
            "status": item.status.value,
            "signals_collected": item.signals_collected,
            "queried_keywords": list(item.queried_keywords),
            "queried_window": item.queried_window,
            "query_fingerprint": item.query_fingerprint,
            "completed_at": item.completed_at,
            "scope_attestation": item.scope_attestation,
            "note": item.note,
            "collection_plan_digest": item.collection_plan_digest,
        }
        for item in outcomes
    ]
    return build_evidence_frame(
        mission_id=mission.id,
        brief_revision_id=brief.brief_revision_id if brief else None,
        manifest_digest=manifest.manifest_digest,
        collection_plan_digest=collection_plan_digest,
        observations=observations,
        qualifications=qualification_records,
        channel_outcomes=outcome_records,
        analysis_policy=manifest.analysis_policy,
    )
