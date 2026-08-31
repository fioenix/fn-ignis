import logging
from typing import Dict, Any
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)


class IngestTrendsUseCase:
    """
    Use Case điều phối việc cào dữ liệu từ tất cả Connector Plugins và lưu vào Repository.
    Tuân thủ Zero-Token Ingress và Error Isolation.
    """

    def __init__(self, registry: ConnectorPluginRegistry, repository: ITrendRepository):
        self._registry = registry
        self._repo = repository

    async def execute(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
    ) -> Dict[str, Any]:
        logger.info(f"Bắt đầu Ingest pipeline cho vùng {geo.value}, timeframe {timeframe.value}...")
        
        signals = await self._registry.fetch_from_all(geo=geo, timeframe=timeframe)
        saved_count = await self._repo.save_signals(signals)

        result = {
            "geo": geo.value,
            "timeframe": timeframe.value,
            "total_fetched": len(signals),
            "total_saved": saved_count,
        }
        logger.info(f"Hoàn thành Ingest pipeline: {result}")
        return result
