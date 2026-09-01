from abc import ABC, abstractmethod
from typing import Dict, List
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.value_objects import GeoCode


class IArtifactBuilder(ABC):
    """Giao diện cổng sinh Artifacts hiển thị chuẩn xác (Deterministic Artifact Builder)."""

    @abstractmethod
    def build_dashboard_artifact(self, clusters: List[TopicCluster], geo: GeoCode = GeoCode.VN) -> str:
        """Sinh Single-file HTML Dashboard tổng quan xu hướng đa kênh."""
        pass

    @abstractmethod
    def build_topic_card_artifact(self, cluster: TopicCluster, signals: List[TrendSignal]) -> str:
        """Sinh Single-file HTML Card chi tiết một chủ đề xu hướng."""
        pass

    @abstractmethod
    def build_mission_report_artifact(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        platform_breakdown: Dict[str, int],
    ) -> str:
        """Sinh Single-file HTML Báo cáo chuyên sâu cho một Research Mission."""
        pass
