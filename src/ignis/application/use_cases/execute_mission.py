import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import TrendSignal
from ignis.domain.research_workspace import (
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    ResearchSurface,
    resolve_surface,
)
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)


class ExecuteMissionUseCase:
    """
    Use Case for executing deep data ingress for a specific Research Mission,
    passing exact timeframe filters, tagging mission_id, clustering signals, and updating state.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        registry: ConnectorPluginRegistry,
        clusterer: IClusteringEngine,
        workspace_store: Optional[IResearchWorkspaceStore] = None,
    ):
        self._repo = repository
        self._registry = registry
        self._clusterer = clusterer
        self._workspace_store = workspace_store

    async def _require_confirmed_brief(self, mission) -> None:
        """A Market mission does not probe until the requester has confirmed its Brief.

        The gate is fail-closed: a MARKET mission whose Brief cannot be read is blocked rather
        than run, because the alternative is collecting evidence against a hypothesis nobody
        agreed to and then presenting it as an answer to a decision.

        Missions on no surface -- everything created outside a research workspace -- are not
        gated. They were never framed as hypothesis-driven investigations, so demanding a Brief
        from them would be a rule applied backwards.
        """
        if resolve_surface(mission.surface) is not ResearchSurface.MARKET:
            return

        revision = None
        if self._workspace_store is not None:
            revision = await self._workspace_store.get_brief_revision_for_mission(mission.id)

        if revision is not None:
            return

        mission.status = "BLOCKED"
        mission.summary = (
            "Blocked: Market probes are not authorized until the requester confirms a complete "
            "Market Brief."
        )
        await self._repo.update_mission(mission)
        raise IncompleteMarketBriefError(REQUIRED_BRIEF_FIELDS)

    async def execute(self, mission_id: UUID) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

        await self._require_confirmed_brief(mission)

        logger.info(f"Executing Research Mission '{mission.title}' [ID: {mission_id}] with keywords: {mission.keywords} (Timeframe: {mission.timeframe})...")
        mission.status = "RUNNING"
        await self._repo.update_mission(mission)

        try:
            # 1. Targeted ingress across active connector plugins
            signals = await self._registry.search_across_all(
                keywords=mission.keywords,
                geo=mission.geo_code,
                target_platforms=mission.platforms,
                custom_timeframe=mission.timeframe,
            )

            # Fail-safe: a connector can exhaust its quota mid-pass, and the mission should not
            # lose the platform it already had. What it keeps is the evidence -- the observations
            # themselves stay exactly as they were recorded. They are deliberately not merged
            # into `signals`: everything in that list goes through the writer as a new collection
            # event, so preserving a platform that way would claim the harness polled something
            # it could not reach, and would add an observation on every failed pass.
            existing_signals = await self._repo.get_mission_signals(mission.id)
            preserved: List[TrendSignal] = []
            if existing_signals:
                existing_platforms = {s.platform for s in existing_signals}
                new_platforms = {s.platform for s in signals}
                for missing_plat in existing_platforms - new_platforms:
                    kept = [s for s in existing_signals if s.platform == missing_plat]
                    logger.warning(f"Preserving {len(kept)} signals for platform {missing_plat} due to ingress quota fallback.")
                    preserved.extend(kept)

            # 2. Tag signals with mission_id
            for s in signals:
                s.mission_id = mission.id

            # 3. Semantic clustering, over what the mission will hold in total
            clusters = (
                await self._clusterer.cluster_signals(signals + preserved)
                if (signals or preserved)
                else []
            )

            # 4. Failure-safe evidence replacement: write first, prune last.
            #
            # It withdrew first before, on its own committed statement, so anything that failed
            # afterwards left the mission with no evidence at all -- neither the new nor the old.
            # It was labelled an Atomic Replace and was neither.
            #
            # This is not atomic either, and does not claim to be. What it guarantees is
            # narrower than "at every point the pass can fail": any failure before or during the
            # prune leaves the mission holding at least the evidence it started with. Once the
            # prune succeeds the replacement is complete, and a later failure -- update_mission
            # marking the mission COMPLETED, for one -- is a failure after the fact, not a loss
            # of evidence. Stale claims surviving a failure are removed by the next pass;
            # evidence deleted by a failed pass is gone.
            if clusters:
                await self._repo.save_clusters(clusters)
            if signals:
                await self._repo.save_signals(signals)
            if preserved:
                await self._repo.attach_mission_evidence(mission.id, preserved)
                await self._repo.assign_observation_clusters(preserved)

            signals = signals + preserved

            # 5. Now, and only now, drop the claims this pass did not renew. The retained set is
            # the observations that actually survived the writes, read back off the signals
            # rather than assumed: a sighting the writer skipped carries no observation id and
            # must not be treated as evidence this mission holds.
            retained = [s.observation_id for s in signals if s.observation_id]
            await self._repo.prune_mission_evidence(mission.id, retained)
            active_platforms = list(set(s.platform.value if hasattr(s.platform, "value") else str(s.platform) for s in signals))
            active_plat_str = ", ".join(active_platforms) if active_platforms else "none"

            mission.status = "COMPLETED"
            mission.summary = f"Successfully collected {len(signals)} signals across {len(active_platforms)}/{len(mission.platforms)} responsive platforms ({active_plat_str}), discovered {len(clusters)} topic clusters."
            await self._repo.update_mission(mission)

            logger.info(f"Research Mission {mission_id} completed: {mission.summary}")
            return {
                "mission_id": str(mission.id),
                "title": mission.title,
                "status": mission.status,
                "total_signals": len(signals),
                "total_clusters": len(clusters),
                "summary": mission.summary,
            }
        except Exception as e:
            logger.error(f"Error executing Research Mission {mission_id}: {e}", exc_info=True)
            mission.status = "FAILED"
            mission.summary = f"Execution error: {str(e)}"
            await self._repo.update_mission(mission)
            raise e

