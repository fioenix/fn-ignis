"""Start an exploratory Attention mission inside a confirmed research workspace.

Attention is the entry point for a requester who does not yet know which topic is worth
investigating commercially, so it asks for no hypothesis and no Market Brief. It reuses the
existing mission record and the existing ingress path; the only thing it adds is the workspace
scope and the surface that keeps its results from being read as a market verdict.
"""

import logging
from typing import List, Optional
from uuid import UUID

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import ResearchSurface, WorkspaceScopeMismatchError
from ignis.domain.value_objects import GeoCode, PlatformType, timeframe_to_days

logger = logging.getLogger(__name__)


class CreateAttentionMissionUseCase:
    """Create an `ATTENTION` mission bound to a research workspace."""

    def __init__(self, repository: ITrendRepository, store: IResearchWorkspaceStore):
        self._repo = repository
        self._store = store

    async def execute(
        self,
        workspace_id: UUID,
        title: str,
        keywords: Optional[List[str]] = None,
        seed: Optional[str] = None,
        agent: str = "claude",
        session_id: Optional[str] = None,
        platforms: Optional[List[PlatformType]] = None,
        geo: GeoCode = GeoCode.VN,
        timeframe: str = "7d",
    ) -> ResearchMission:
        workspace = await self._store.get_research_workspace(workspace_id)
        if workspace is None:
            # An error rather than an implicit create: a workspace is a durable thing the
            # requester confirmed, and inventing one here would write research state into a
            # folder nobody agreed to.
            raise WorkspaceScopeMismatchError(
                f"No confirmed research workspace {workspace_id} exists in the configured Ignis "
                "database. Propose and confirm the workspace before starting a mission."
            )

        # The canonical refusal, called for its exception rather than its value: an unvalidated
        # timeframe used to reach the database intact and fail only when analysis asked it for a
        # span, leaving a stored mission nobody could window.
        timeframe_to_days(timeframe)

        probe_terms = list(keywords or [])
        if seed and seed.strip() and seed.strip() not in probe_terms:
            probe_terms.insert(0, seed.strip())
        if not probe_terms:
            probe_terms = [title]

        mission = ResearchMission(
            title=title,
            keywords=probe_terms,
            agent=agent,
            session_id=session_id,
            platforms=platforms or [
                PlatformType.GOOGLE_TRENDS,
                PlatformType.YOUTUBE,
                PlatformType.TIKTOK,
                PlatformType.THREADS,
                PlatformType.REELS,
            ],
            geo_code=geo,
            timeframe=timeframe,
            status="PENDING",
            workspace_id=workspace_id,
            surface=ResearchSurface.ATTENTION.value,
        )
        await self._repo.create_mission(mission)
        logger.info(
            "Created ATTENTION mission %s (%s) in research workspace %s.",
            mission.id,
            mission.shortcode,
            workspace_id,
        )
        return mission
