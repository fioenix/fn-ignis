import asyncio
import logging
import signal

from ignis.application.use_cases.autonomous_discovery import AutonomousDiscoveryUseCase
from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.config import settings
from ignis.domain.value_objects import GeoCode
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
from ignis.application.ports.repository_port import ITrendRepository
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ignis.scheduler")


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

    async def run_ingress_cycle(self, registry: ConnectorPluginRegistry, cluster_use_case: ClusterSignalsUseCase):
        logger.info(f"Starting standard periodic Ingress cycle for geo={self.geo.value}...")
        try:
            signals = await registry.fetch_from_all(geo=self.geo)
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
        for plat_name, plugin in registry._plugins.items():
            try:
                is_ok = await plugin.is_healthy()
                status_str = "HEALTHY" if is_ok else "UNHEALTHY"
                level = "INFO" if is_ok else "WARNING"
                await repository.log_event(
                    component="scheduler.health_probe",
                    event_type="CONNECTOR_HEALTH_CHECK",
                    message=f"Connector {plugin.name} is {status_str}",
                    level=level,
                    details={"platform": str(plat_name), "healthy": is_ok},
                )
            except Exception as e:
                logger.error(f"Health probe failed for connector {plugin.name}: {e}")
                await repository.log_event(
                    component="scheduler.health_probe",
                    event_type="CONNECTOR_HEALTH_ERROR",
                    message=f"Connector {plugin.name} health probe error: {e}",
                    level="ERROR",
                    details={"platform": str(plat_name), "error": str(e)},
                )

    async def start(self):
        self._running = True
        logger.info(f"Starting fn-ignis Worker Scheduler (Ingress: {self.interval_seconds}s, Discovery: {self.discovery_interval_seconds}s, Health: {self.health_check_interval_seconds}s)...")

        # 1. Dependency Injection Setup
        repository = create_repository()
        tiktok_auth_manager = TikTokAuthManager(repository=repository)
        tiktok_plugin = TikTokPlugin(auth_manager=tiktok_auth_manager)
        creative_center_plugin = TikTokCreativeCenterPlugin(auth_manager=tiktok_auth_manager)

        registry = ConnectorPluginRegistry(repository=repository)
        registry.register(GoogleTrendsRssPlugin())
        registry.register(tiktok_plugin)
        registry.register(creative_center_plugin)
        registry.register(ThreadsPlugin())
        registry.register(ReelsPlugin())

        if settings.YOUTUBE_API_KEY:
            registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

        clusterer = SemanticClusterer()
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
                await self.run_ingress_cycle(registry, cluster_use_case)

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


async def main_async():
    ingress_interval = int(settings.__dict__.get("SCHEDULER_INTERVAL_SECONDS", 900))
    discovery_interval = int(settings.__dict__.get("DISCOVERY_INTERVAL_SECONDS", 43200))
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

