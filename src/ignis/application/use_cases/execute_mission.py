import logging
from typing import Dict, Any
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
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

            # Fail-safe: If a source encountered transient quota exhaustion, preserve historical signals
            existing_signals = await self._repo.get_mission_signals(mission.id)
            if existing_signals:
                existing_platforms = {s.platform for s in existing_signals}
                new_platforms = {s.platform for s in signals}
                missing_platforms = existing_platforms - new_platforms
                for missing_plat in missing_platforms:
                    preserved = [s for s in existing_signals if s.platform == missing_plat]
                    logger.warning(f"Preserving {len(preserved)} signals for platform {missing_plat} due to ingress quota fallback.")
                    signals.extend(preserved)

            # 2. Tag signals with mission_id
            for s in signals:
                s.mission_id = mission.id

            # 3. Semantic clustering
            clusters = await self._clusterer.cluster_signals(signals) if signals else []

            # 4. Atomic Replace: clear previous signals for this mission
            await self._repo.delete_mission_signals(mission.id)

            # 5. Persist fresh signals and clusters
            if clusters:
                await self._repo.save_clusters(clusters)
            if signals:
                await self._repo.save_signals(signals)

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

