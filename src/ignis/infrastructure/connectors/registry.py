import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Bảo vệ hệ thống: Tự động ngắt plugin nếu tỷ lệ lỗi liên tiếp vượt ngưỡng."""
    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED (bình thường), OPEN (ngắt), HALF_OPEN (thử lại)
        self.last_failure_time: Optional[datetime] = None

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit Breaker đã CHUYỂN SANG OPEN do {self.failure_count} lần lỗi liên tiếp.")

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.last_failure_time:
                elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_time_seconds:
                    self.state = "HALF_OPEN"
                    return True
            return False
        return True


class ConnectorPluginRegistry:
    """Quản lý toàn bộ danh mục Connector Plugins và điều phối Ingress kèm Audit Logging."""
    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._plugins: Dict[PlatformType, IConnectorPlugin] = {}
        self._breakers: Dict[PlatformType, CircuitBreaker] = {}
        self._repository = repository

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    def register(self, plugin: IConnectorPlugin) -> None:
        self._plugins[plugin.platform] = plugin
        self._breakers[plugin.platform] = CircuitBreaker()
        logger.info(f"Đã đăng ký Plugin Connector: [{plugin.name}] cho nền tảng {plugin.platform.value}")

    def get_plugin(self, platform: PlatformType) -> Optional[IConnectorPlugin]:
        return self._plugins.get(platform)

    def list_plugins(self) -> List[IConnectorPlugin]:
        return list(self._plugins.values())

    def get_health_status(self) -> Dict[str, dict]:
        """Báo cáo trạng thái sức khỏe và Circuit Breaker của tất cả các kênh."""
        status = {}
        for platform, plugin in self._plugins.items():
            breaker = self._breakers[platform]
            status[platform.value] = {
                "name": plugin.name,
                "circuit_state": breaker.state,
                "consecutive_failures": breaker.failure_count,
                "last_failure": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
            }
        return status

    async def fetch_from_all(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H
    ) -> List[TrendSignal]:
        tasks = []
        enabled_plugins = []

        for platform, plugin in self._plugins.items():
            breaker = self._breakers[platform]
            if not breaker.can_execute():
                logger.warning(f"Bỏ qua plugin [{plugin.name}] do Circuit Breaker OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Bỏ qua plugin {plugin.name} do Circuit Breaker đang OPEN ({breaker.failure_count} lỗi liên tiếp).",
                        level="WARNING"
                    )
                continue

            enabled_plugins.append(plugin)
            tasks.append(self._safe_fetch(plugin, breaker, geo, timeframe))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] gặp ngoại lệ khi cào: {result}")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="INGRESS_FAILURE",
                        message=f"Lỗi khi cào dữ liệu từ {plugin.name}: {str(result)}",
                        level="ERROR",
                        details={"error": str(result), "platform": plugin.platform.value}
                    )
            elif isinstance(result, list):
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] thu thập {len(result)} signals.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="INGRESS_SUCCESS",
                        message=f"Thu thập thành công {len(result)} signals từ {plugin.name}.",
                        level="INFO",
                        details={"count": len(result), "platform": plugin.platform.value}
                    )

        return all_signals

    async def search_across_all(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        target_platforms: Optional[List[PlatformType]] = None,
    ) -> List[TrendSignal]:
        tasks = []
        enabled_plugins = []

        for platform, plugin in self._plugins.items():
            if target_platforms and platform not in target_platforms:
                continue

            breaker = self._breakers[platform]
            if not breaker.can_execute():
                logger.warning(f"Bỏ qua plugin [{plugin.name}] do Circuit Breaker OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Bỏ qua search trên {plugin.name} do Circuit Breaker OPEN.",
                        level="WARNING"
                    )
                continue

            enabled_plugins.append(plugin)
            tasks.append(self._safe_search(plugin, breaker, keywords, geo, timeframe))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] gặp ngoại lệ khi search: {result}")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_FAILURE",
                        message=f"Lỗi khi search trên {plugin.name} với keywords {keywords}: {str(result)}",
                        level="ERROR",
                        details={"keywords": keywords, "error": str(result)}
                    )
            elif isinstance(result, list):
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] tìm kiếm được {len(result)} signals theo keywords {keywords}.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_SUCCESS",
                        message=f"Tìm kiếm thành công {len(result)} signals từ {plugin.name}.",
                        level="INFO",
                        details={"keywords": keywords, "count": len(result)}
                    )

        return all_signals

    async def _safe_fetch(self, plugin: IConnectorPlugin, breaker: CircuitBreaker, geo: GeoCode, timeframe: Timeframe) -> List[TrendSignal]:
        try:
            signals = await plugin.fetch_signals(geo=geo, timeframe=timeframe)
            breaker.record_success()
            return signals
        except Exception as e:
            breaker.record_failure()
            raise e

    async def _safe_search(self, plugin: IConnectorPlugin, breaker: CircuitBreaker, keywords: List[str], geo: GeoCode, timeframe: Timeframe) -> List[TrendSignal]:
        try:
            signals = await plugin.search_signals(keywords=keywords, geo=geo, timeframe=timeframe)
            breaker.record_success()
            return signals
        except Exception as e:
            breaker.record_failure()
            raise e
