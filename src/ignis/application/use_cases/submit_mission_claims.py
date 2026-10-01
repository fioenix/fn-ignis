"""Validate and persist candidate claims against the current evidence frame."""

from typing import Any, Dict, Mapping, Sequence
from uuid import uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.research_workspace import (
    ClaimStatus,
    ClaimType,
    InvalidMissionClaimError,
    MissionClaim,
    MissionClaimEvidence,
    QualificationContext,
    ResearchSurface,
    assess_strategic_sufficiency,
    compute_candidate_claim_key,
    resolve_surface,
)
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_data

MAX_CLAIMS_PER_BATCH = 50
BOUND_CLAIM_TYPES = frozenset(
    {
        ClaimType.OBSERVATION,
        ClaimType.MEASUREMENT,
        ClaimType.INFERENCE,
        ClaimType.ASSUMPTION,
        ClaimType.RECOMMENDATION,
    }
)


class SubmitMissionClaimsUseCase:
    """The only path from host-authored candidate prose to the persisted Claim Ledger."""

    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repository = repository
        self._store = store

    async def execute(
        self,
        mission_id: str,
        frame_digest: str,
        candidates: Sequence[Mapping[str, Any]],
        *,
        created_by: str,
    ) -> Dict[str, Any]:
        mission = await self._repository.get_mission(mission_id)
        if mission is None:
            return {
                "status": "NOT_FOUND",
                "mission_id": str(mission_id),
                "error": f"No research mission found with ID or shortcode '{mission_id}'.",
            }
        base = {"mission_id": str(mission.id), "shortcode": mission.shortcode}
        if resolve_surface(mission.surface) is not ResearchSurface.MARKET:
            return self._refused(
                base,
                "NOT_APPLICABLE",
                "MARKET_MISSION_REQUIRED",
                "Strategic claims require a confirmed Market mission.",
            )
        batch = list(candidates or ())
        if not 1 <= len(batch) <= MAX_CLAIMS_PER_BATCH:
            return self._refused(
                base,
                "INVALID",
                "INVALID_BATCH_SIZE",
                f"A claim batch carries from 1 to {MAX_CLAIMS_PER_BATCH} candidates.",
            )

        snapshot = await self._store.load_mission_evidence_snapshot(mission.id)
        manifest, brief = snapshot.manifest, snapshot.brief
        if manifest is None or brief is None:
            return self._refused(
                base,
                "BLOCKED",
                "INCOMPLETE_MISSION_FRAME",
                "The persisted Mission Manifest and confirmed Market Brief are both required.",
            )
        signals, qualifications, outcomes = snapshot.signals, snapshot.qualifications, snapshot.outcomes
        context = QualificationContext.build(
            [signal.observation_id for signal in signals if signal.observation_id],
            qualifications,
            outcomes,
            geo=mission.geo_code,
            timeframe=mission.timeframe,
        )
        try:
            frame = frame_from_snapshot(snapshot)
        except InvalidMissionClaimError as exc:
            return self._refused(base, "BLOCKED", "INCOMPLETE_EVIDENCE_FRAME", str(exc))
        if frame_digest != frame.frame_digest:
            return self._refused(
                base,
                "CONFLICT",
                "STALE_FRAME",
                "The submitted frame digest is not the mission's current evidence frame.",
            )

        sufficiency = assess_strategic_sufficiency(
            manifest=manifest,
            brief=brief,
            qualifications=qualifications,
            probe_outcomes=outcomes,
            assessment_state=context.assessment_state,
            current_frame_digest=frame.frame_digest,
            submitted_frame_digest=frame_digest,
            observations=signals,
            query_topics=mission.keywords,
        )
        try:
            claims = [
                self._candidate_claim(
                    mission.id,
                    brief.brief_revision_id,
                    frame.frame_digest,
                    candidate,
                    created_by,
                    sufficiency,
                )
                for candidate in batch
            ]
            stored = await self._store.save_mission_claims(
                mission.id, frame.frame_digest, claims
            )
        except (InvalidMissionClaimError, TypeError, ValueError) as exc:
            return self._refused(base, "INVALID", "INVALID_CLAIM_BATCH", str(exc))

        # A concurrent evidence writer may commit after validation but before this save.
        # Retain the exact candidate for audit, but never return permission for a stale frame.
        try:
            current = frame_from_snapshot(
                await self._store.load_mission_evidence_snapshot(mission.id)
            )
            unchanged = current.frame_digest == frame.frame_digest
        except InvalidMissionClaimError:
            unchanged = False
        if not unchanged:
            return {
                **base,
                "status": "CONFLICT",
                "reason_code": "STALE_FRAME",
                "analysis_status": "INSUFFICIENT_EVIDENCE",
                "render_status": "WITHHELD",
                "frame_digest": frame.frame_digest,
                "recorded": len(stored),
                "permitted": 0,
                "withheld": len(stored),
                "claims": [],
                "note": "The frame changed during submission. Recorded candidates remain audit "
                        "history only; read the current frame before submitting again.",
            }
        permitted_count = sum(claim.status is ClaimStatus.PERMITTED for claim in stored)
        withheld_count = sum(claim.status is ClaimStatus.WITHHELD for claim in stored)
        return {
            **base,
            "status": "RECORDED",
            "analysis_status": (
                "READY"
                if sufficiency.ready and permitted_count > 0
                else "INSUFFICIENT_EVIDENCE"
            ),
            "frame_digest": frame.frame_digest,
            "recorded": len(stored),
            "permitted": permitted_count,
            "withheld": withheld_count,
            "sufficiency": sufficiency.to_payload(),
            "claims": sanitize_pii_data([claim.to_payload() for claim in stored]),
        }

    @staticmethod
    def _candidate_claim(
        mission_id,
        brief_revision_id,
        frame_digest: str,
        candidate: Mapping[str, Any],
        created_by: str,
        sufficiency,
    ) -> MissionClaim:
        if not isinstance(candidate, Mapping):
            raise InvalidMissionClaimError("Every candidate claim must be an object.")
        claim_type = ClaimType(str(candidate.get("claim_type", "UNKNOWN")).strip().upper())
        claim_id = uuid4()
        bindings = tuple(
            MissionClaimEvidence(
                claim_id=claim_id,
                observation_id=item.get("observation_id"),
                probe_outcome_id=item.get("probe_outcome_id"),
                role=item.get("role"),
                hypothesis_target=item.get("hypothesis_target"),
            )
            for item in candidate.get("evidence_bindings", ())
        )
        if claim_type in BOUND_CLAIM_TYPES and not bindings:
            raise InvalidMissionClaimError(
                f"{claim_type.value} requires at least one current evidence binding."
            )
        client_key = candidate.get("client_claim_key") or compute_candidate_claim_key(candidate)
        reasons = list(
            sufficiency.gap_report.failed_gates
            if not sufficiency.ready and sufficiency.gap_report is not None
            else ()
        )
        if claim_type is ClaimType.UNKNOWN:
            reasons.append("UNKNOWN_CLAIM_TYPE")
        metric_denominator = candidate.get("metric_denominator")
        metric_timeframe = candidate.get("metric_timeframe")
        if claim_type is ClaimType.MEASUREMENT:
            if not str(metric_denominator or "").strip():
                reasons.append(f"MISSING_METRIC_DENOMINATOR:{client_key}")
            if not str(metric_timeframe or "").strip():
                reasons.append(f"MISSING_METRIC_TIMEFRAME:{client_key}")
        status = ClaimStatus.PERMITTED if not reasons else ClaimStatus.WITHHELD
        return MissionClaim(
            claim_id=claim_id,
            mission_id=mission_id,
            brief_revision_id=brief_revision_id,
            frame_digest=frame_digest,
            client_claim_key=str(client_key),
            claim_type=claim_type,
            wording=candidate.get("wording", ""),
            inference_method=candidate.get("inference_method"),
            metric_denominator=metric_denominator,
            metric_timeframe=metric_timeframe,
            confidence=candidate.get("confidence"),
            limitations=tuple(candidate.get("limitations") or ()),
            change_conditions=tuple(candidate.get("change_conditions") or ()),
            status=status,
            withheld_reasons=tuple(dict.fromkeys(reasons)),
            created_by=created_by,
            evidence_bindings=bindings,
        )

    @staticmethod
    def _refused(base, status: str, reason_code: str, error: str) -> Dict[str, Any]:
        return {
            **base,
            "status": status,
            "reason_code": reason_code,
            "error": error,
            "note": "The whole claim batch was refused and nothing was recorded.",
        }
