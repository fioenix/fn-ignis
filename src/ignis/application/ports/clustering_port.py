from abc import ABC, abstractmethod
from typing import List
from ignis.domain.entities import TrendSignal, TopicCluster


class IClusteringEngine(ABC):
    """Giao diện cổng cho bộ gom cụm xu hướng và tính điểm đà tăng trưởng đa kênh."""

    @abstractmethod
    async def cluster_signals(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        """Gom nhóm danh sách signals thành các TopicCluster và tính điểm cross_platform_score."""
        pass
