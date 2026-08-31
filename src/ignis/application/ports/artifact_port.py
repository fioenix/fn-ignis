from abc import ABC, abstractmethod
from typing import List, Dict, Any
from ignis.domain.entities import TopicCluster, TrendSignal

class IArtifactBuilder(ABC):
    """Giao diện cổng dựng mã HTML/React Artifacts cho Agent Client."""

    @abstractmethod
    def build_dashboard_html(
        self, 
        clusters: List[TopicCluster], 
        metadata: Dict[str, Any]
    ) -> str:
        """Dựng giao diện HTML Dashboard tổng quan (Tailwind + Recharts)."""
        pass

    @abstractmethod
    def build_topic_deepdive_html(
        self, 
        cluster: TopicCluster, 
        signals: List[TrendSignal]
    ) -> str:
        """Dựng giao diện HTML phân tích sâu 1 chủ đề."""
        pass
