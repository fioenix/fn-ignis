import logging
from typing import Any, Dict, List
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal
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
    ):
        self._repo = repository
        self._registry = registry
        self._clusterer = clusterer

    async def execute(self, mission_id: UUID) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

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

            # 4. Atomic Replace: withdraw this mission's claims. The observations and sources
            # survive -- other missions may be standing on them.
            await self._repo.delete_mission_signals(mission.id)

            # 5. Persist the new sightings, and re-attach the preserved ones by reference
            if clusters:
                await self._repo.save_clusters(clusters)
            if signals:
                await self._repo.save_signals(signals)
            if preserved:
                await self._repo.attach_mission_evidence(mission.id, preserved)
                await self._repo.assign_observation_clusters(preserved)

            signals = signals + preserved
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

