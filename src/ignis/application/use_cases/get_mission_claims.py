"""Read the current Claim Ledger without promoting stale claims to renderable output."""

from dataclasses import replace
from typing import Any, Dict

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.research_workspace import (
    ClaimStatus,
    InvalidMissionClaimError,
    ResearchSurface,
    resolve_surface,
)
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_data


class GetMissionClaimsUseCase:
    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repository = repository
        self._store = store

    async def execute(
        self, mission_id: str, *, include_superseded: bool = False
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
            return {
                **base,
                "status": "NOT_APPLICABLE",
                "reason_code": "MARKET_MISSION_REQUIRED",
                "render_status": "WITHHELD",
                "claims": [],
            }
        try:
            snapshot = await self._store.load_mission_evidence_snapshot(mission.id)
            frame = frame_from_snapshot(snapshot)
        except InvalidMissionClaimError as exc:
            history = await self._store.list_mission_claims(
                mission.id, include_superseded=True
            )
            return {
                **base,
                "status": "BLOCKED",
                "reason_code": "INCOMPLETE_EVIDENCE_FRAME",
                "error": str(exc),
                "render_status": "WITHHELD",
                "claims": sanitize_pii_data([claim.to_payload() for claim in history]),
            }

        # Supersession is a current-render projection, not a destructive write from a reader
        # whose snapshot may already be older than a concurrent request's completed frame.
        claims = [
            replace(claim, status=ClaimStatus.SUPERSEDED)
            if claim.frame_digest != frame.frame_digest else claim
            for claim in snapshot.claims
        ]
        if not include_superseded:
            claims = [claim for claim in claims if claim.status is not ClaimStatus.SUPERSEDED]
        permitted = [
            claim
            for claim in claims
            if claim.frame_digest == frame.frame_digest
            and claim.status is ClaimStatus.PERMITTED
        ]
        withheld = [
            claim
            for claim in claims
            if claim.frame_digest == frame.frame_digest
            and claim.status is ClaimStatus.WITHHELD
        ]
        superseded = [claim for claim in claims if claim.status is ClaimStatus.SUPERSEDED]
        return {
            **base,
            "status": "READY",
            "frame_digest": frame.frame_digest,
            "render_status": "PERMITTED" if permitted else "WITHHELD",
            "counts": {
                "permitted": len(permitted),
                "withheld": len(withheld),
                "superseded": len(superseded),
            },
            "claims": sanitize_pii_data([claim.to_payload() for claim in claims]),
        }
