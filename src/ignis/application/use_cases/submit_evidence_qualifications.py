"""Record one batch of the host Agent's typed evidence judgments, whole or not at all.

Ignis cannot prove that a semantic judgment is right. It can prove that the judgment is well formed,
that it names evidence the mission holds, and that it was made against the frame the mission is
framed by -- and it refuses the whole batch when any of that fails, so a half-recorded batch never
changes what a report concludes.
"""

from typing import Any, Dict, Optional, Sequence

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.research_workspace import (
    EvidenceQualification,
    EvidenceQualificationConflictError,
    InvalidEvidenceQualificationError,
    QualificationProgress,
    ResearchSurface,
    compute_frame_fingerprint,
    resolve_surface,
)

MAX_ASSESSMENTS_PER_BATCH = 50
NEXT_STEP = "Call get_mission_evidence_qualification_batch with this mission."


class SubmitEvidenceQualificationsUseCase:
    """Validate a batch of judgments against the mission frame and evidence, then persist it."""

    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repo = repository
        self._store = store

    async def execute(
        self,
        mission_id: str,
        frame_fingerprint: str,
        assessments: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if mission is None:
            return {
                "status": "NOT_FOUND",
                "mission_id": str(mission_id),
                "error": f"No research mission found with ID or shortcode '{mission_id}'.",
            }
        base = {"mission_id": str(mission.id), "shortcode": mission.shortcode}
        surface = resolve_surface(mission.surface)
        if surface is None:
            return {
                **base,
                "status": "NOT_APPLICABLE",
                "note": "This mission declared no research surface, so there is nothing to qualify.",
            }
        if mission.workspace_id is None or (
            await self._store.get_research_workspace(mission.workspace_id)
        ) is None:
            return self._refused(
                base, "BLOCKED", "WORKSPACE_SCOPE",
                "The mission names a research workspace the configured database does not hold.",
            )
        brief = None
        if surface is ResearchSurface.MARKET:
            brief = await self._store.get_brief_revision_for_mission(mission.id)
            if brief is None:
                return self._refused(
                    base, "BLOCKED", "BRIEF_NOT_CONFIRMED",
                    "Market evidence is judged against the confirmed Market Brief, and this "
                    "mission has no readable confirmed Brief.",
                )

        expected_frame = compute_frame_fingerprint(mission, brief)
        if frame_fingerprint != expected_frame:
            return self._refused(
                base, "CONFLICT", "STALE_FRAME",
                "The frame fingerprint does not match this mission's current frame. Read a new "
                "batch and judge it against the frame that batch carries.",
            )
        batch = list(assessments or [])
        if not 1 <= len(batch) <= MAX_ASSESSMENTS_PER_BATCH:
            return self._refused(
                base, "INVALID", "INVALID_BATCH_SIZE",
                f"A batch carries from 1 to {MAX_ASSESSMENTS_PER_BATCH} assessments; this one "
                f"carries {len(batch)}.",
            )

        try:
            judgments = [
                self._judgment(mission.id, expected_frame, brief, item) for item in batch
            ]
        except (InvalidEvidenceQualificationError, TypeError, AttributeError) as exc:
            return self._refused(base, "INVALID", "INVALID_JUDGMENT", str(exc))

        observation_ids = [str(j.observation_id) for j in judgments]
        if len(set(observation_ids)) != len(observation_ids):
            return self._refused(
                base, "INVALID", "DUPLICATE_OBSERVATION",
                "An observation appears more than once in the batch.",
            )
        signals = await self._repo.get_mission_signals(mission.id)
        held = {str(s.observation_id) for s in signals if s.observation_id}
        foreign = [oid for oid in observation_ids if oid not in held]
        if foreign:
            return self._refused(
                base, "INVALID", "FOREIGN_OBSERVATION",
                f"{len(foreign)} observation(s) are not part of this mission's current evidence: "
                f"{', '.join(foreign[:5])}.",
            )

        try:
            recorded = await self._store.save_evidence_qualifications(mission.id, judgments)
        except EvidenceQualificationConflictError as exc:
            return self._refused(base, "CONFLICT", "CONFLICTING_REWRITE", str(exc))
        except InvalidEvidenceQualificationError as exc:
            # The evidence changed between the ownership check and the write; the database's
            # own key refused it, and nothing of the batch was kept.
            return self._refused(base, "INVALID", "FOREIGN_OBSERVATION", str(exc))

        progress = QualificationProgress.from_evidence(
            list(held), await self._store.list_evidence_qualifications(mission.id)
        )
        return {
            **base,
            "status": "RECORDED",
            "recorded": recorded,
            "progress": progress.to_payload(),
            "next_step": NEXT_STEP,
        }

    @staticmethod
    def _judgment(mission_id, frame: str, brief: Optional[Any], item: Dict[str, Any]):
        if not isinstance(item, dict):
            raise InvalidEvidenceQualificationError("Every assessment must be an object.")
        missing = [
            name for name in (
                "observation_id", "relation", "purpose", "confidence", "reason_code", "judged_by"
            )
            if name not in item
        ]
        if missing:
            raise InvalidEvidenceQualificationError(
                f"An assessment is missing: {', '.join(missing)}."
            )
        return EvidenceQualification(
            mission_id=mission_id,
            observation_id=item["observation_id"],
            frame_fingerprint=frame,
            brief_revision_id=brief.brief_revision_id if brief is not None else None,
            relation=item["relation"],
            purpose=item["purpose"],
            confidence=item["confidence"],
            reason_code=item["reason_code"],
            judged_by=item["judged_by"],
            model=item.get("model"),
        )

    @staticmethod
    def _refused(base: Dict[str, Any], status: str, reason_code: str, error: str) -> Dict[str, Any]:
        return {
            **base,
            "status": status,
            "reason_code": reason_code,
            "error": error,
            "note": "The whole batch was refused and nothing was recorded.",
        }


