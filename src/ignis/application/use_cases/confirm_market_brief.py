"""Persist a requester-confirmed Market Brief and open the mission it authorizes.

The adaptive Q&A lives in the host Agent, not here. This use case receives one complete payload
that the requester has already reviewed and confirmed, and it has no operation for anything less:
there is no draft to save, no partial answer to update, and no transcript to keep. A requester
who abandons the framing leaves nothing behind because nothing was ever sent.
"""

import logging
from dataclasses import replace
from typing import List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    IncompleteMarketBriefError,
    InvalidMissionManifestError,
    MarketBriefRevision,
    MissionManifest,
    MissionOutputType,
    MissionLineage,
    ResearchSurface,
    WorkspaceScopeMismatchError,
    missing_brief_fields,
)
from ignis.domain.value_objects import GeoCode, PlatformType, resolve_geo, timeframe_to_days
from ignis.application.use_cases.create_attention_mission import _platforms_from_resources

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
        manifest: MissionManifest,
        title: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        lineage: Optional[MissionLineage] = None,
        agent: str = "claude",
        session_id: Optional[str] = None,
        platforms: Optional[List[PlatformType]] = None,
        alternative_hypotheses: Optional[Sequence[str]] = None,
        null_hypothesis: Optional[str] = None,
        kill_criteria: Optional[Sequence[str]] = None,
        revision_rule: Optional[str] = None,
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
        alternatives = [value for value in (alternative_hypotheses or ()) if str(value).strip()]
        kills = [value for value in (kill_criteria or ()) if str(value).strip()]
        if len(alternatives) < 2:
            missing.append("alternative_hypotheses")
        if not str(null_hypothesis or "").strip():
            missing.append("null_hypothesis")
        if not kills:
            missing.append("kill_criteria")
        if not str(revision_rule or "").strip():
            missing.append("revision_rule")
        if missing:
            # Refused before anything is written, so an incomplete framing leaves no mission,
            # no revision and no journal behind.
            raise IncompleteMarketBriefError(list(dict.fromkeys(missing)))

        timeframe_to_days(timeframe)
        lineage = lineage or MissionLineage()

        if manifest.mission_id is not None:
            raise InvalidMissionManifestError(
                "A new Market assignment must not pre-assign its mission_id."
            )
        if manifest.output_type not in (
            MissionOutputType.MARKET_ANALYSIS,
            MissionOutputType.STRATEGIC_ARTIFACT,
        ):
            raise InvalidMissionManifestError(
                "A Market mission can produce only MARKET_ANALYSIS or STRATEGIC_ARTIFACT."
            )

        selected_platforms = platforms or _platforms_from_resources(manifest.allowed_resources)
        if set(selected_platforms) != set(_platforms_from_resources(manifest.allowed_resources)):
            raise InvalidMissionManifestError(
                "The selected platforms must match the connector surfaces allowed by the manifest."
            )

        mission_id = uuid4()
        revision = MarketBriefRevision(
            brief_revision_id=uuid4(),
            workspace_id=workspace_id,
            mission_id=mission_id,
            # Provisional. The store allocates the authoritative number inside the transaction
            # that writes the row, because a number read here and used there is a number two
            # concurrent confirmations can both see.
            revision_number=1,
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=tuple(falsifiers),
            alternative_hypotheses=(
                tuple(alternative_hypotheses) if alternative_hypotheses is not None else None
            ),
            null_hypothesis=null_hypothesis,
            kill_criteria=tuple(kill_criteria) if kill_criteria is not None else None,
            revision_rule=revision_rule,
            confirmed_by=confirmed_by,
        )

        mission = ResearchMission(
            id=mission_id,
            title=title or decision,
            keywords=list(keywords or []) or _keywords_from(hypothesis, target_user),
            agent=agent,
            session_id=session_id,
            platforms=selected_platforms,
            geo_code=resolve_geo(geo) if not isinstance(geo, GeoCode) else geo,
            timeframe=timeframe,
            status="PENDING",
            workspace_id=workspace_id,
            surface=ResearchSurface.MARKET.value,
            parent_attention_mission_id=lineage.parent_attention_mission_id,
            parent_cluster_id=lineage.parent_cluster_id,
            revises_mission_id=lineage.revises_mission_id,
            brief_revision_id=revision.brief_revision_id,
        )

        # Both rows in one transaction, never two calls. The revision holds a foreign key to
        # the mission, so the mission has to be written first -- and writing it first on its own
        # is exactly what left an orphan MARKET mission behind when the revision write failed: a
        # mission the execution gate refuses to run, with no Brief anyone could confirm for it.
        manifest = replace(manifest, mission_id=mission.id)
        mission, revision, _ = await self._store.create_market_mission_with_brief_and_manifest(
            mission, revision, manifest
        )

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
