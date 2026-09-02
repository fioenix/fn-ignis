from abc import ABC, abstractmethod
from typing import Dict, List
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.value_objects import GeoCode


class IArtifactBuilder(ABC):
    """Port interface for deterministic HTML and report artifact generation."""

    @abstractmethod
    def build_dashboard_artifact(self, clusters: List[TopicCluster], geo: GeoCode = GeoCode.VN) -> str:
        """Generate a single-file interactive HTML dashboard of cross-platform trends."""
        pass

    @abstractmethod
    def build_topic_card_artifact(self, cluster: TopicCluster, signals: List[TrendSignal]) -> str:
        """Generate a single-file interactive HTML card for a specific trend cluster."""
        pass

    @abstractmethod
    def build_mission_report_artifact(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        platform_breakdown: Dict[str, int],
    ) -> str:
        """Generate a single-file interactive HTML dossier for a research mission."""
        pass

