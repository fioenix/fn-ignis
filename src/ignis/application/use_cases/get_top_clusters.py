from typing import List
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster
from ignis.domain.value_objects import GeoCode, Timeframe


class GetTopClustersUseCase:
    """Use Case for querying the top trending TopicClusters."""


    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        return await self._repo.get_top_clusters(geo=geo, timeframe=timeframe, limit=limit)
