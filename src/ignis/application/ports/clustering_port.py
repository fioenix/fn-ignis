from abc import ABC, abstractmethod
from typing import List
from ignis.domain.entities import TrendSignal, TopicCluster


class IClusteringEngine(ABC):
    """Port interface for semantic clustering and cross-platform momentum calculation."""

    @abstractmethod
    async def cluster_signals(self, signals: List[TrendSignal]) -> List[TopicCluster]:
        """Cluster raw trend signals into canonical TopicClusters and compute cross-platform scores."""
        pass

