import logging
from typing import List
from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster, TrendSignal

logger = logging.getLogger(__name__)


class ClusterSignalsUseCase:
    """
    Use Case gom cụm các TrendSignal thành các TopicCluster và cập nhật thông tin vào kho lưu trữ.
    """

    def __init__(self, clusterer: IClusteringEngine, repository: ITrendRepository):
        self._clusterer = clusterer
        self._repo = repository

    async def execute(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        if not signals:
            return []

        logger.info(f"Bắt đầu gom cụm {len(signals)} signals...")
        clusters = await self._clusterer.cluster_signals(signals)

        # Lưu lại clusters vào database
        await self._repo.save_clusters(clusters)
        # Cập nhật signals với cluster_id mới
        await self._repo.save_signals(signals)

        logger.info(f"Đã tạo và lưu thành công {len(clusters)} Topic Clusters.")
        return clusters
