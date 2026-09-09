from abc import ABC, abstractmethod
from typing import List
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope, PlatformType, Timeframe


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

    async def resolve_ingest_runtime(self) -> IngestRuntime:
        """Which runtime this connector needs to pull with the credentials it currently has.

        Override it with `IngestRuntime.BROWSER` when the only way in is a headless browser, or
        return it conditionally when an official API tier may or may not be configured. A host
        without a browser runtime uses this to skip the connector rather than register one that
        warns on every cycle and returns nothing.
        """
        return IngestRuntime.HTTP_API

    @property
    def default_feed_scope(self) -> IngressScope:
        """Whose content `fetch_signals` returns when no scope is requested.

        Most connectors read a public surface. A connector whose cheapest or only feed is the
        authenticated account's own timeline (Threads `/me/threads`, Instagram `/{ig-user}/media`,
        a personalised home feed) MUST declare `IngressScope.OWN_PROFILE` here. The registry then
        keeps that feed out of market-listening passes and reaches for the connector's keyword
        probe instead, so the operator's own posts never land in demand analysis by accident.
        """
        return IngressScope.PUBLIC_MARKET

    @abstractmethod
    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        """Fetch general trend signals and map them to TrendSignal domain entities.

        A connector serving both surfaces honours `scope`; one serving only a public surface may
        ignore it. Returning account-owned content under `IngressScope.PUBLIC_MARKET` is a bug.
        """
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


