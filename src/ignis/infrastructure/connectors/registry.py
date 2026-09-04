from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker protection: isolates failing plugins if consecutive errors exceed threshold."""
    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED (normal), OPEN (tripped), HALF_OPEN (probing)
        self.last_failure_time: Optional[datetime] = None
        # Kept so an empty channel can be explained as a quota ceiling rather
        # than a generic outage in the Data Ingress audit.
        self.last_error_type: Optional[str] = None
        self.last_error_message: Optional[str] = None

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_error_type = None
        self.last_error_message = None

    def record_failure(self, error: Optional[BaseException] = None):
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        if error is not None:
            self.last_error_type = type(error).__name__
            self.last_error_message = str(error)[:500]
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit Breaker TRIPPED to OPEN after {self.failure_count} consecutive failures.")

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
    """Manages connector plugin catalog and coordinates resilient multi-platform ingress with audit logging."""
    def __init__(self, repository: Optional[ITrendRepository] = None):
        # Keyed by plugin_id, not platform: a single platform can be served by
        # several plugins probing it differently (TikTok video grid vs Creative
        # Center). Keying by platform made the later registration silently
        # replace the earlier one.
        self._plugins: Dict[str, IConnectorPlugin] = {}
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._repository = repository

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    def register(self, plugin: IConnectorPlugin) -> None:
        plugin_id = plugin.plugin_id
        if plugin_id in self._plugins:
            logger.warning(
                f"Connector plugin id '{plugin_id}' is already registered by "
                f"[{self._plugins[plugin_id].name}]; replacing it with [{plugin.name}]. "
                "Override the `plugin_id` property if both plugins are meant to coexist."
            )
        self._plugins[plugin_id] = plugin
        self._breakers[plugin_id] = CircuitBreaker()
        logger.info(
            f"Registered Connector Plugin: [{plugin.name}] as '{plugin_id}' "
            f"for platform {plugin.platform.value}"
        )

    def get_plugin(self, platform: PlatformType) -> Optional[IConnectorPlugin]:
        """
        Return the first plugin registered for a platform.

        Kept for backward compatibility with existing call sites. Prefer
        `get_plugins()` when a platform may have several probes, or
        `get_plugin_by_id()` to address one exactly.
        """
        for plugin in self._plugins.values():
            if plugin.platform == platform:
                return plugin
        return None

    def get_plugin_by_id(self, plugin_id: str) -> Optional[IConnectorPlugin]:
        """Return exactly one plugin by its unique registry identifier."""
        return self._plugins.get(plugin_id)

    def get_plugins(self, platform: Optional[PlatformType] = None) -> List[IConnectorPlugin]:
        """Return every plugin registered for a platform, or all plugins when omitted."""
        if platform is None:
            return list(self._plugins.values())
        return [p for p in self._plugins.values() if p.platform == platform]

    def list_plugins(self) -> List[IConnectorPlugin]:
        return list(self._plugins.values())

    def get_health_status(self) -> Dict[str, dict]:
        """Report health and circuit breaker state independently for every registered plugin."""
        status = {}
        for plugin_id, plugin in self._plugins.items():
            breaker = self._breakers[plugin_id]
            status[plugin_id] = {
                "plugin_id": plugin_id,
                "platform": plugin.platform.value,
                "name": plugin.name,
                "supports_search": plugin.supports_search,
                "circuit_state": breaker.state,
                "consecutive_failures": breaker.failure_count,
                "last_failure": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
                "last_error_type": breaker.last_error_type,
                "last_error": breaker.last_error_message,
            }
        return status

    async def fetch_from_all(
        self, 
        geo: GeoCode = GeoCode.VN, 
        timeframe: Timeframe = Timeframe.LAST_24H
    ) -> List[TrendSignal]:
        tasks = []
        enabled_plugins = []

        for plugin_id, plugin in self._plugins.items():
            breaker = self._breakers[plugin_id]
            if not breaker.can_execute():
                logger.warning(f"Skipping plugin [{plugin.name}] because Circuit Breaker is OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Skipping plugin {plugin.name} due to OPEN Circuit Breaker ({breaker.failure_count} consecutive errors).",
                        level="WARNING"
                    )
                continue

            enabled_plugins.append(plugin)
            tasks.append(self._safe_fetch(plugin, breaker, geo, timeframe))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] encountered exception during ingress: {result}")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="INGRESS_FAILURE",
                        message=f"Error ingesting signals from {plugin.name}: {str(result)}",
                        level="ERROR",
                        details={"error": str(result), "platform": plugin.platform.value}
                    )
            elif isinstance(result, list):
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] collected {len(result)} signals.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="INGRESS_SUCCESS",
                        message=f"Successfully collected {len(result)} signals from {plugin.name}.",
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
        custom_timeframe: Optional[str] = None,
    ) -> List[TrendSignal]:
        tasks = []
        enabled_plugins = []

        for plugin_id, plugin in self._plugins.items():
            if target_platforms and plugin.platform not in target_platforms:
                continue

            if not plugin.supports_search:
                # Falling back to fetch_signals here would inject platform-wide
                # signals unrelated to the requested keywords.
                logger.debug(f"Skipping search on [{plugin.name}]: no keyword search probe.")
                continue

            breaker = self._breakers[plugin_id]
            if not breaker.can_execute():
                logger.warning(f"Skipping plugin [{plugin.name}] because Circuit Breaker is OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Skipping search on {plugin.name} due to OPEN Circuit Breaker.",
                        level="WARNING"
                    )
                continue

            enabled_plugins.append(plugin)
            tasks.append(self._safe_search(plugin, breaker, keywords, geo, timeframe, custom_timeframe))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] encountered exception during search: {result}")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_FAILURE",
                        message=f"Error searching {plugin.name} with keywords {keywords}: {str(result)}",
                        level="ERROR",
                        details={"keywords": keywords, "error": str(result)}
                    )
            elif isinstance(result, list):
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] retrieved {len(result)} signals for keywords {keywords}.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_SUCCESS",
                        message=f"Successfully retrieved {len(result)} signals from {plugin.name}.",
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
            breaker.record_failure(e)
            raise e

    async def _safe_search(
        self, 
        plugin: IConnectorPlugin, 
        breaker: CircuitBreaker, 
        keywords: List[str], 
        geo: GeoCode, 
        timeframe: Timeframe,
        custom_timeframe: Optional[str] = None,
    ) -> List[TrendSignal]:
        try:
            import inspect
            sig = inspect.signature(plugin.search_signals)
            if "custom_timeframe" in sig.parameters:
                signals = await plugin.search_signals(keywords=keywords, geo=geo, timeframe=timeframe, custom_timeframe=custom_timeframe)
            else:
                signals = await plugin.search_signals(keywords=keywords, geo=geo, timeframe=timeframe)
            breaker.record_success()
            return signals
        except Exception as e:
            breaker.record_failure(e)
            raise e

    async def fetch_suggestions_across_all(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        target_platforms: Optional[List[PlatformType]] = None,
    ) -> List[Dict[str, Any]]:
        """Collect search suggestions across all capable plugins."""
        all_suggestions: List[Dict[str, Any]] = []
        for plugin in self._plugins.values():
            if target_platforms and plugin.platform not in target_platforms:
                continue
            try:
                sugs = await plugin.fetch_suggestions(keywords=keywords, geo=geo)
                if sugs:
                    all_suggestions.extend(sugs)
            except Exception as e:
                logger.warning(f"Error fetching suggestions from {plugin.name}: {e}")
        return all_suggestions


