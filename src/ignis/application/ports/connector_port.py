from abc import ABC, abstractmethod
from typing import List, Optional
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe


class IConnectorPlugin(ABC):
    """Giao diện cổng (Port) chuẩn mực cho mọi Data Source Connector Plugin."""

    @property
    @abstractmethod
    def platform(self) -> PlatformType:
        """Định danh nền tảng của Plugin."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Tên hiển thị của Plugin."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Kiểm tra sức khỏe kết nối đến nguồn dữ liệu."""
        pass

    @abstractmethod
    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        """Lấy dữ liệu xu hướng chung và chuyển đổi về danh sách TrendSignal domain entities."""
        pass

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
    ) -> List[TrendSignal]:
        """Cào dữ liệu có định hướng theo danh sách từ khóa nghiên cứu cụ thể."""
        return await self.fetch_signals(geo=geo, timeframe=timeframe, limit=limit)
