from abc import ABC, abstractmethod
from typing import List
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe


class IConnectorPlugin(ABC):
    """Port interface for data source connector plugins."""

    @property
    @abstractmethod
    def platform(self) -> PlatformType:
        """Platform identifier for this connector."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name of this connector plugin."""
        pass

    @property
    def plugin_id(self) -> str:
        """
        Unique registry identifier for this plugin.

        Defaults to the platform value, which is correct while a platform is served
        by exactly one plugin. Override it when several plugins serve the same
        platform through different probes (e.g. TikTok video grid vs Creative Center),
        otherwise the later registration silently replaces the earlier one.
        """
        return self.platform.value

    @property
    def supports_search(self) -> bool:
        """
        Whether this plugin implements a real keyword search probe.

        Derived from whether the subclass overrides `search_signals`, so it cannot
        drift out of sync with the implementation. Plugins relying on the inherited
        default only re-run `fetch_signals`, which would inject platform-wide
        signals unrelated to the requested keywords.
        """
        return type(self).search_signals is not IConnectorPlugin.search_signals

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Check the operational health and reachability of the data source."""
        pass

    @abstractmethod
    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        """Fetch general trend signals and map them to TrendSignal domain entities."""
        pass

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
    ) -> List[TrendSignal]:
        """Perform targeted search against specific research keywords."""
        return await self.fetch_signals(geo=geo, timeframe=timeframe, limit=limit)

    async def fetch_suggestions(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
    ) -> List[dict]:
        """Fetch real-world search suggestions and query autocomplete terms."""
        return []


