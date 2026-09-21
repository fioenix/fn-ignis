"""Open a Market investigation from an Attention result, and revise one without rewriting it.

Two things happen here, and they are the same operation seen from two sides:

- a requester selects a topic an Attention mission surfaced, and the Market mission that follows
  records where the question came from; and
- a requester changes a field of a Brief that has already been confirmed, and gets a new
  immutable revision under a new mission rather than an edit to the old one.

Both refuse to touch what already exists. The Attention mission is never re-labelled, the earlier
Brief is never updated, and the earlier evidence is never re-pointed at the new hypothesis -- a
Market mission answers its own Brief with evidence it collected itself, and lineage is the record
of where the question started, not a shortcut past collecting the answer.

The host Agent still owns the Q&A. This use case receives one complete confirmed payload and has
no operation for anything less.
"""

import logging
from typing import List, Optional, Sequence, Tuple
from uuid import UUID

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    InvalidMissionLineageError,
    MarketBriefRevision,
    MissionLineage,
    ResearchSurface,
    SurfaceViolationError,
    WorkspaceScopeMismatchError,
    resolve_surface,
)
from ignis.domain.value_objects import PlatformType

logger = logging.getLogger(__name__)


class CreateMarketRevisionUseCase:
    """The lineage-aware door to a Market mission: validate the origin, then confirm the Brief."""

    def __init__(
        self,
        repository: ITrendRepository,
        store: IResearchWorkspaceStore,
        confirm_use_case: Optional[ConfirmMarketBriefUseCase] = None,
    ):
        self._repo = repository
        self._store = store
        self._confirm = confirm_use_case or ConfirmMarketBriefUseCase(repository, store)

    async def execute(
        self,
        workspace_id: UUID,
        decision: str,
        target_user: str,
        problem: str,
        geo: str,
        timeframe: str,
        hypothesis: str,
        falsifiers: Sequence[str],
        confirmed_by: str,
        title: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        lineage: Optional[MissionLineage] = None,
        previous_mission_id: Optional[UUID] = None,
        agent: str = "claude",
        session_id: Optional[str] = None,
        platforms: Optional[List[PlatformType]] = None,
    ) -> Tuple[ResearchMission, MarketBriefRevision]:
        workspace = await self._store.get_research_workspace(workspace_id)
        if workspace is None:
            raise WorkspaceScopeMismatchError(
                f"No confirmed research workspace {workspace_id} exists in the configured Ignis "
                "database. Propose and confirm the workspace before confirming a Brief."
            )

        if previous_mission_id is not None:
            previous = await self._scoped_mission(workspace_id, previous_mission_id, "revised")
            if resolve_surface(previous.surface) is not ResearchSurface.MARKET:
                raise SurfaceViolationError(
                    f"Mission {previous.id} is on the "
                    f"{previous.surface or 'unrecorded'} surface, so it has no Brief to revise. "
                    "A Market investigation opened from an Attention result is a handoff, not a "
                    "revision: pass it as lineage instead."
                )
            # The origin of the question does not change when the question is sharpened, so a
            # revision that says nothing about lineage keeps the lineage it is revising.
            if lineage is None:
                lineage = MissionLineage.of_mission(previous)

        lineage = lineage or MissionLineage()
        await self._validate_lineage(workspace_id, lineage)

        mission, revision = await self._confirm.execute(
            workspace_id=workspace_id,
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=falsifiers,
            confirmed_by=confirmed_by,
            title=title,
            keywords=keywords,
            lineage=lineage,
            agent=agent,
            session_id=session_id,
            platforms=platforms,
        )
        logger.info(
            "Opened MARKET mission %s at Brief revision #%s in workspace %s "
            "(attention parent=%s, cluster=%s, revises=%s).",
            mission.id,
            revision.revision_number,
            workspace_id,
            lineage.parent_attention_mission_id,
            lineage.parent_cluster_id,
            previous_mission_id,
        )
        return mission, revision

    # ------------------------------------------------------------------
    # Lineage
    # ------------------------------------------------------------------

    async def _validate_lineage(self, workspace_id: UUID, lineage: MissionLineage) -> None:
        """Refuse an origin nobody could follow back.

        Validated before anything is written, so a handoff that names a mission from another
        research -- or a cluster that Attention run never saw -- leaves no mission, no revision
        and no journal behind.
        """
        if lineage.is_empty:
            return

        if lineage.parent_attention_mission_id is None:
            raise InvalidMissionLineageError(
                "A selected cluster does not say which Attention run selected it. Pass the "
                "parent Attention mission together with the cluster."
            )

        parent = await self._scoped_mission(
            workspace_id, lineage.parent_attention_mission_id, "handed off"
        )
        if resolve_surface(parent.surface) is not ResearchSurface.ATTENTION:
            raise SurfaceViolationError(
                f"Mission {parent.id} is on the {parent.surface or 'unrecorded'} surface, so it "
                "is not an Attention result a Market investigation can be handed off from."
            )

        if lineage.parent_cluster_id is not None:
            observed = {
                signal.cluster_id
                for signal in await self._repo.get_mission_signals(parent.id)
                if signal.cluster_id is not None
            }
            if lineage.parent_cluster_id not in observed:
                raise InvalidMissionLineageError(
                    f"Cluster {lineage.parent_cluster_id} is not one that Attention mission "
                    f"{parent.id} observed, so the selected topic cannot be traced back to it."
                )

    async def _scoped_mission(
        self, workspace_id: UUID, mission_id: UUID, role: str
    ) -> ResearchMission:
        """Read a mission that this research is supposed to own.

        A missing mission and a mission belonging to another research are different failures and
        are reported as such: the first is a stale identifier, the second is a requester about to
        attach one research's history to another's.
        """
        mission = await self._repo.get_mission(mission_id)
        if mission is None:
            raise InvalidMissionLineageError(
                f"No mission {mission_id} exists, so it cannot be {role}."
            )
        if mission.workspace_id != workspace_id:
            raise WorkspaceScopeMismatchError(
                f"Mission {mission.id} belongs to workspace {mission.workspace_id}, "
                f"not to {workspace_id}, so it cannot be {role} here."
            )
        return mission
