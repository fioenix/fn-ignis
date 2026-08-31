import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
from ignis.application.ports.connector_port import IConnectorPlugin
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
            logger.warning(f"Circuit Breaker đã CHUYỂN SANG OPEN (Ngắt tạm thời) do {self.failure_count} lần lỗi liên tiếp.")

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
        return True  # HALF_OPEN cho phép thử 1 request

class ConnectorPluginRegistry:
    """Quản lý toàn bộ danh mục Connector Plugins và điều phối Ingress."""
    def __init__(self):
        self._plugins: Dict[PlatformType, IConnectorPlugin] = {}
        self._breakers: Dict[PlatformType, CircuitBreaker] = {}

    def register(self, plugin: IConnectorPlugin) -> None:
        """Đăng ký một plugin mới vào hệ thống."""
        self._plugins[plugin.platform] = plugin
        self._breakers[plugin.platform] = CircuitBreaker()
        logger.info(f"Đã đăng ký Plugin Connector: [{plugin.name}] cho nền tảng {plugin.platform.value}")

    def get_plugin(self, platform: PlatformType) -> Optional[IConnectorPlugin]:
        return self._plugins.get(platform)

    def list_plugins(self) -> List[IConnectorPlugin]:
        return list(self._plugins.values())

    async def fetch_from_all(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H
    ) -> List[TrendSignal]:
        """
        Kích hoạt việc cào dữ liệu song song từ tất cả các plugin đang khả dụng.
        Nếu một plugin gặp lỗi, lỗi được cô lập hoàn toàn và ghi log; các plugin khác vẫn trả về dữ liệu.
        """
        tasks = []
        enabled_plugins = []

        for platform, plugin in self._plugins.items():
            breaker = self._breakers[platform]
            if not breaker.can_execute():
                logger.warning(f"Bỏ qua plugin [{plugin.name}] do Circuit Breaker đang ở trạng thái OPEN.")
                continue

            enabled_plugins.append(plugin)
            tasks.append(self._safe_fetch(plugin, breaker, geo, timeframe))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] gặp ngoại lệ khi cào dữ liệu: {result}")
            elif isinstance(result, list):
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] thu thập thành công {len(result)} signals.")

        return all_signals

    async def _safe_fetch(
        self, 
        plugin: IConnectorPlugin, 
        breaker: CircuitBreaker, 
        geo: GeoCode, 
        timeframe: Timeframe
    ) -> List[TrendSignal]:
        try:
            signals = await plugin.fetch_signals(geo=geo, timeframe=timeframe)
            breaker.record_success()
            return signals
        except Exception as e:
            breaker.record_failure()
            raise e
