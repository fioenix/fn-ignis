from abc import ABC, abstractmethod
from typing import List, Optional
from uuid import UUID
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe

class ITrendRepository(ABC):
    """Giao diện cổng lưu trữ và truy vấn dữ liệu Trends (Time-series & Clusters)."""

    @abstractmethod
    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Lưu danh sách signals vào Timescale hypertable. Trả về số lượng đã lưu."""
        pass

    @abstractmethod
    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        """Lưu hoặc cập nhật thông tin các Topic Clusters."""
        pass

    @abstractmethod
    async def get_top_clusters(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H, 
        limit: int = 10
    ) -> List[TopicCluster]:
        """Truy vấn các chủ đề có điểm momentum cao nhất."""
        pass

    @abstractmethod
    async def get_cluster_signals(
        self, 
        cluster_id: UUID, 
        timeframe: Timeframe = Timeframe.LAST_7D
    ) -> List[TrendSignal]:
        """Lấy toàn bộ lịch sử tín hiệu chuỗi thời gian của một cụm chủ đề."""
        pass
