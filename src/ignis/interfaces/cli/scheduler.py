import asyncio
import importlib.util
import logging
import signal
from typing import Dict, List, Optional, Tuple

from ignis.application.use_cases.autonomous_discovery import AutonomousDiscoveryUseCase
from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.config import settings
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope
from ignis.infrastructure.auth.meta_browser_auth import (
    InstagramBrowserAuthManager,
    ThreadsBrowserAuthManager,
)
from ignis.infrastructure.auth.meta_oauth import InstagramAuthManager, ThreadsAuthManager
from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.application.ports.repository_port import ITrendRepository
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ignis.scheduler")



def browser_runtime_available() -> bool:
    """Whether this host can drive a headless browser at all."""
    return importlib.util.find_spec("playwright") is not None


async def build_connector_registry(
    repository: ITrendRepository,
    browser_available: Optional[bool] = None,
) -> Tuple[ConnectorPluginRegistry, List[Dict[str, str]]]:
    """Register the connectors this host can actually pull with, and report the ones it cannot.

    The worker image carries no browser: Playwright plus Chromium would take it from ~90MB to
    ~500MB, and an unattended scraper running every 15 minutes is what gets an IP blocked. So a
    connector joins the radar only when it can pull over an official HTTP API — which each
    connector answers for itself through `resolve_ingest_runtime()`, since a dual-tier connector
    like Threads is HTTP-only when a Graph token is configured and browser-bound otherwise.
    Browser-bound channels are not broken here; they belong to Track 2, where Playwright runs on
    the operator's own machine with their own session.
    """
    if browser_available is None:
        browser_available = browser_runtime_available()

    tiktok_auth_manager = TikTokAuthManager(repository=repository)
    candidates: List[IConnectorPlugin] = [
        GoogleTrendsRssPlugin(),
        TikTokPlugin(auth_manager=tiktok_auth_manager),
        TikTokCreativeCenterPlugin(auth_manager=tiktok_auth_manager),
        # The worker binds the same auth managers the MCP server does, otherwise the plugins
        # cannot reach the Tier-1 sessions stored in platform_credentials.
        ThreadsPlugin(
            auth_manager=ThreadsAuthManager(repository=repository),
            browser_auth_manager=ThreadsBrowserAuthManager(repository=repository),
        ),
        ReelsPlugin(
            auth_manager=InstagramAuthManager(repository=repository),
            browser_auth_manager=InstagramBrowserAuthManager(repository=repository),
        ),
    ]
    if settings.YOUTUBE_API_KEY:
        candidates.append(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

    registry = ConnectorPluginRegistry(repository=repository)
    skipped: List[Dict[str, str]] = []
    for plugin in candidates:
        try:
            runtime = await plugin.resolve_ingest_runtime()
        except Exception as e:
            logger.warning(f"Could not resolve the ingest runtime for {plugin.name}: {e}")
            runtime = IngestRuntime.HTTP_API

        if runtime == IngestRuntime.BROWSER and not browser_available:
            skipped.append({
                "name": plugin.name,
                "platform": plugin.platform.value,
                "reason": "needs a browser runtime this host does not provide",
            })
            continue
        registry.register(plugin)

    return registry, skipped


class IngressScheduler:
    """
    Background Cron Daemon executing periodic ETL ingestion, clustering,
    Autonomous Discovery Engine, and Synthetic Health Probes.
    """

    def __init__(
        self,
        interval_seconds: int = 900,
        discovery_interval_seconds: int = 43200,
        health_check_interval_seconds: int = 21600,
        geo: GeoCode = GeoCode.VN,
    ):
        self.interval_seconds = interval_seconds
        self.discovery_interval_seconds = discovery_interval_seconds
        self.health_check_interval_seconds = health_check_interval_seconds
        self.geo = geo
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._last_discovery_time: float = 0.0
        self._last_health_check_time: float = 0.0

    async def run_ingress_cycle(
        self,
        registry: ConnectorPluginRegistry,
        cluster_use_case: ClusterSignalsUseCase,
        ingest_use_case: Optional[IngestTrendsUseCase] = None,
    ):
        """Run one public-market ingress cycle.

        The radar listens to the market, never to the operator's own accounts: connectors whose
        only feed is the connected account are probed by keyword using the persisted lexicon, and
        the registry's scope guard drops any self-authored signal that still comes back.
        """
        logger.info(f"Starting standard periodic Ingress cycle for geo={self.geo.value}...")
        try:
            seeds = await ingest_use_case.load_seed_keywords() if ingest_use_case else []
            signals = await registry.fetch_from_all(
                geo=self.geo,
                scope=IngressScope.PUBLIC_MARKET,
                seed_keywords=seeds,
            )
            logger.info(f"Ingested {len(signals)} signals across active connector plugins.")
            if signals:
                clusters = await cluster_use_case.execute(signals)
                logger.info(f"Successfully clustered into {len(clusters)} Topic Clusters.")
        except Exception as e:
            logger.error(f"Error during periodic Ingress cycle: {e}", exc_info=True)

    # Backward compatibility alias
    run_once = run_ingress_cycle

    async def run_discovery_cycle(self, discovery_use_case: AutonomousDiscoveryUseCase):
        logger.info(f"Starting scheduled Autonomous Discovery cycle for geo={self.geo.value}...")
        try:
            result = await discovery_use_case.execute(geo=self.geo)
            logger.info(
                f"Autonomous Discovery completed: [{result.get('shortcode')}] "
                f"Total Signals: {result.get('total_signals')}, "
                f"Report: {result.get('artifact_file')}"
            )
        except Exception as e:
            logger.error(f"Error during Autonomous Discovery cycle: {e}", exc_info=True)

    async def run_health_probe_cycle(self, registry: ConnectorPluginRegistry, repository: ITrendRepository):
        logger.info("Running scheduled synthetic connector health probes...")
        for plugin_id, plugin in registry._plugins.items():
            try:
                is_ok = await plugin.is_healthy()
                status_str = "HEALTHY" if is_ok else "UNHEALTHY"
                level = "INFO" if is_ok else "WARNING"
                await repository.log_event(
                    component="scheduler.health_probe",
                    event_type="CONNECTOR_HEALTH_CHECK",
                    message=f"Connector {plugin.name} is {status_str}",
                    level=level,
                    details={"plugin_id": str(plugin_id), "platform": str(plugin.platform), "healthy": is_ok},
                )
            except Exception as e:
                logger.error(f"Health probe failed for connector {plugin.name}: {e}")
                await repository.log_event(
                    component="scheduler.health_probe",
                    event_type="CONNECTOR_HEALTH_ERROR",
                    message=f"Connector {plugin.name} health probe error: {e}",
                    level="ERROR",
                    details={"plugin_id": str(plugin_id), "platform": str(plugin.platform), "error": str(e)},
                )

    async def start(self):
        self._running = True
        logger.info(f"Starting fn-ignis Worker Scheduler (Ingress: {self.interval_seconds}s, Discovery: {self.discovery_interval_seconds}s, Health: {self.health_check_interval_seconds}s)...")

        # 1. Dependency Injection Setup
        repository = create_repository()
        registry, skipped = await build_connector_registry(repository)
        if skipped:
            logger.info(
                "Connectors left out of this worker: "
                + "; ".join(f"{item['name']} ({item['reason']})" for item in skipped)
            )

        clusterer = SemanticClusterer()
        try:
            clusterer.register_taxonomies(await repository.get_industry_taxonomies())
        except Exception as e:
            logger.warning(f"Could not load industry taxonomies for classification: {e}")
        try:
            identities = await SelfIdentityRegistry(repository).load()
            registry.register_self_identities(identities)
            logger.info(f"Self-content guard armed with {len(identities)} connected account identities.")
        except Exception as e:
            logger.warning(f"Could not load self-account identities: {e}")
        ingest_use_case = IngestTrendsUseCase(registry=registry, repository=repository)
        cluster_use_case = ClusterSignalsUseCase(clusterer=clusterer, repository=repository)
        quality_evaluator = QualityEvaluator()
        strategic_reasoner = StrategicMarketReasoner()
        artifact_builder = HtmlArtifactBuilder()

        discovery_use_case = AutonomousDiscoveryUseCase(
            repository=repository,
            registry=registry,
            clusterer=clusterer,
            quality_evaluator=quality_evaluator,
            strategic_reasoner=strategic_reasoner,
            artifact_builder=artifact_builder,
        )

        try:
            import time
            while self._running and not self._shutdown_event.is_set():
                # 1. Run standard ingress cycle
                await self.run_ingress_cycle(registry, cluster_use_case, ingest_use_case)

                # 2. Check and run discovery cycle if due
                current_time = time.time()
                if (current_time - self._last_discovery_time) >= self.discovery_interval_seconds:
                    await self.run_discovery_cycle(discovery_use_case)
                    self._last_discovery_time = current_time

                # 3. Check and run synthetic health probes if due
                if (current_time - self._last_health_check_time) >= self.health_check_interval_seconds:
                    await self.run_health_probe_cycle(registry, repository)
                    self._last_health_check_time = current_time

                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("Closing repository connections and shutting down scheduler...")
            if hasattr(repository, "close"):
                await repository.close()
            logger.info("Scheduler shutdown cleanly.")


    def stop(self):
        logger.info("Received shutdown signal for Scheduler...")
        self._running = False
        self._shutdown_event.set()


def resolve_ingress_interval(sync_minutes: int = 0, scheduler_seconds: int = 900) -> int:
    """Resolve active ingress interval in seconds, prioritizing non-zero SYNC_INTERVAL_MINUTES override."""
    if sync_minutes > 0:
        return int(sync_minutes * 60)
    return int(scheduler_seconds)


async def main_async():
    ingress_interval = resolve_ingress_interval(
        sync_minutes=getattr(settings, "SYNC_INTERVAL_MINUTES", 0),
        scheduler_seconds=getattr(settings, "SCHEDULER_INTERVAL_SECONDS", 900),
    )
    discovery_interval = int(settings.DISCOVERY_INTERVAL_HOURS * 3600)
    scheduler = IngressScheduler(
        interval_seconds=ingress_interval,
        discovery_interval_seconds=discovery_interval,
    )


    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, scheduler.stop)
        except NotImplementedError:
            pass  # Windows fallback

    await scheduler.start()


def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler terminated by user.")


if __name__ == "__main__":
    main()

