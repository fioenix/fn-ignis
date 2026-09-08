import logging
from typing import List
from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster, TrendSignal

logger = logging.getLogger(__name__)


class ClusterSignalsUseCase:
    """Use Case for clustering raw TrendSignals into TopicClusters and persisting them."""

    def __init__(self, clusterer: IClusteringEngine, repository: ITrendRepository):
        self._clusterer = clusterer
        self._repo = repository

    async def execute(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        if not signals:
            return []

        logger.info(f"Clustering {len(signals)} signals...")
        clusters = await self._clusterer.cluster_signals(signals)

        # Persist clusters
        await self._repo.save_clusters(clusters)
        # Update signals with assigned cluster IDs
        await self._repo.save_signals(signals)

        # Re-clustering can leave a stale cluster holding nothing, since its last signal has just
        # moved to the cluster it now belongs to. Those rows are invisible to every read path and
        # would otherwise accumulate on every pass, so the pipeline clears them as it goes.
        removed = await self._repo.prune_empty_clusters()
        if removed:
            logger.info(f"Pruned {removed} topic clusters left without any signal.")

        logger.info(f"Successfully generated and stored {len(clusters)} Topic Clusters.")
        return clusters

