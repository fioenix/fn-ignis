"""Persist a requester-confirmed Market Brief and open the mission it authorizes.

The adaptive Q&A lives in the host Agent, not here. This use case receives one complete payload
that the requester has already reviewed and confirmed, and it has no operation for anything less:
there is no draft to save, no partial answer to update, and no transcript to keep. A requester
who abandons the framing leaves nothing behind because nothing was ever sent.
"""

import logging
from typing import List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    IncompleteMarketBriefError,
    MarketBriefRevision,
    MissionLineage,
    ResearchSurface,
    WorkspaceScopeMismatchError,
    missing_brief_fields,
)
from ignis.domain.value_objects import GeoCode, PlatformType, resolve_geo, timeframe_to_days

logger = logging.getLogger(__name__)


class ConfirmMarketBriefUseCase:
    """Validate, persist and authorize: the only door a Market mission comes through."""

    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repo = repository
        self._store = store

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

        payload = {
            "decision": decision,
            "target_user": target_user,
            "problem": problem,
            "geo": geo,
            "timeframe": timeframe,
            "hypothesis": hypothesis,
            "falsifiers": list(falsifiers or []),
        }
        missing = missing_brief_fields(payload)
        if missing:
            # Refused before anything is written, so an incomplete framing leaves no mission,
            # no revision and no journal behind.
            raise IncompleteMarketBriefError(missing)

        timeframe_to_days(timeframe)
        lineage = lineage or MissionLineage()

        mission_id = uuid4()
        revision = MarketBriefRevision(
            brief_revision_id=uuid4(),
            workspace_id=workspace_id,
            mission_id=mission_id,
            revision_number=await self._store.next_brief_revision_number(workspace_id),
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=tuple(falsifiers),
            confirmed_by=confirmed_by,
        )

        mission = ResearchMission(
            id=mission_id,
            title=title or decision,
            keywords=list(keywords or []) or _keywords_from(hypothesis, target_user),
            agent=agent,
            session_id=session_id,
            platforms=platforms or [
                PlatformType.GOOGLE_TRENDS,
                PlatformType.YOUTUBE,
                PlatformType.TIKTOK,
                PlatformType.THREADS,
                PlatformType.REELS,
            ],
            geo_code=resolve_geo(geo) if not isinstance(geo, GeoCode) else geo,
            timeframe=timeframe,
            status="PENDING",
            workspace_id=workspace_id,
            surface=ResearchSurface.MARKET.value,
            parent_attention_mission_id=lineage.parent_attention_mission_id,
            parent_cluster_id=lineage.parent_cluster_id,
            brief_revision_id=revision.brief_revision_id,
        )

        # Both rows in one transaction, never two calls. The revision holds a foreign key to
        # the mission, so the mission has to be written first -- and writing it first on its own
        # is exactly what left an orphan MARKET mission behind when the revision write failed: a
        # mission the execution gate refuses to run, with no Brief anyone could confirm for it.
        await self._store.create_market_mission_with_brief(mission, revision)

        logger.info(
            "Confirmed Market Brief revision %s (#%s) authorizing mission %s in workspace %s.",
            revision.brief_revision_id,
            revision.revision_number,
            mission.id,
            workspace_id,
        )
        return mission, revision


def _keywords_from(hypothesis: str, target_user: str) -> List[str]:
    """A last-resort probe term when the host Agent supplied no keywords.

    Deliberately the hypothesis and the target user verbatim, not an extracted term list: picking
    terms out of free text is domain vocabulary work, and that lives in the database lexicons
    rather than in a fallback here.
    """
    return [term for term in (hypothesis.strip(), target_user.strip()) if term]
