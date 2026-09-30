"""Start an exploratory Attention mission inside a confirmed research workspace.

Attention is the entry point for a requester who does not yet know which topic is worth
investigating commercially, so it asks for no hypothesis and no Market Brief. It reuses the
existing mission record and the existing ingress path; the only thing it adds is the workspace
scope and the surface that keeps its results from being read as a market verdict.
"""

import logging
from dataclasses import replace
from typing import List, Optional
from uuid import UUID

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import ResearchSurface, WorkspaceScopeMismatchError
from ignis.domain.research_workspace import (
    InvalidMissionManifestError,
    MissionManifest,
    MissionOutputType,
)
from ignis.domain.value_objects import GeoCode, PlatformType, resolve_platform, timeframe_to_days

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
        manifest: MissionManifest,
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

        if manifest.mission_id is not None:
            raise InvalidMissionManifestError(
                "A new Attention assignment must not pre-assign its mission_id."
            )
        if manifest.output_type not in (
            MissionOutputType.COLLECTION_FRAME,
            MissionOutputType.ATTENTION_REPORT,
        ):
            raise InvalidMissionManifestError(
                "An Attention mission can produce only COLLECTION_FRAME or ATTENTION_REPORT."
            )

        selected_platforms = platforms or _platforms_from_resources(manifest.allowed_resources)
        resource_platforms = set(_platforms_from_resources(manifest.allowed_resources))
        if set(selected_platforms) != resource_platforms:
            raise InvalidMissionManifestError(
                "The selected platforms must match the connector surfaces allowed by the manifest."
            )

        mission = ResearchMission(
            title=title,
            keywords=probe_terms,
            agent=agent,
            session_id=session_id,
            platforms=selected_platforms,
            geo_code=geo,
            timeframe=timeframe,
            status="PENDING",
            workspace_id=workspace_id,
            surface=ResearchSurface.ATTENTION.value,
        )
        manifest = replace(manifest, mission_id=mission.id)
        await self._store.create_attention_mission_with_manifest(mission, manifest)
        logger.info(
            "Created ATTENTION mission %s (%s) in research workspace %s.",
            mission.id,
            mission.shortcode,
            workspace_id,
        )
        return mission


def _platforms_from_resources(resources) -> List[PlatformType]:
    """Map built-in exact connector surfaces to their public platform identities."""
    platforms: List[PlatformType] = []
    for resource in resources:
        platform_name = "tiktok" if resource.startswith("tiktok_") else resource
        platform = resolve_platform(platform_name)
        if platform not in platforms:
            platforms.append(platform)
    return platforms
