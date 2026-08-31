import logging
from typing import Dict, Any, List
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)


class ExecuteMissionUseCase:
    """
    Use Case kích hoạt cào sâu dữ liệu cho một Research Mission cụ thể,
    truyền timeframe chính xác, gắn mission_id, gom cụm và cập nhật trạng thái.
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
            raise ValueError(f"Research Mission {mission_id} không tồn tại.")

        logger.info(f"Bắt đầu thực thi Research Mission '{mission.title}' [ID: {mission_id}] với keywords: {mission.keywords} (Timeframe: {mission.timeframe})...")
        mission.status = "RUNNING"
        await self._repo.update_mission(mission)

        try:
            # 1. Cào sâu theo keywords với đúng timeframe được yêu cầu
            signals = await self._registry.search_across_all(
                keywords=mission.keywords,
                geo=mission.geo_code,
                target_platforms=mission.platforms,
            )

            # 2. Gắn mission_id vào toàn bộ signals
            for s in signals:
                s.mission_id = mission.id

            # 3. Gom cụm và chấm điểm
            clusters = await self._clusterer.cluster_signals(signals) if signals else []

            # 4. Lưu dữ liệu
            if clusters:
                await self._repo.save_clusters(clusters)
            if signals:
                await self._repo.save_signals(signals)

            mission.status = "COMPLETED"
            mission.summary = f"Thu thập thành công {len(signals)} signals trên {len(mission.platforms)} nền tảng, phát hiện {len(clusters)} cụm chủ đề phân tích."
            await self._repo.update_mission(mission)

            logger.info(f"Hoàn tất Research Mission {mission_id}: {mission.summary}")
            return {
                "mission_id": str(mission.id),
                "title": mission.title,
                "status": mission.status,
                "total_signals": len(signals),
                "total_clusters": len(clusters),
                "summary": mission.summary,
            }
        except Exception as e:
            logger.error(f"Lỗi khi thực thi Research Mission {mission_id}: {e}", exc_info=True)
            mission.status = "FAILED"
            mission.summary = f"Lỗi thực thi: {str(e)}"
            await self._repo.update_mission(mission)
            raise e
