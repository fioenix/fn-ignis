import asyncio
import logging
import signal
import sys
from typing import Optional

from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.config import settings
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ignis.scheduler")


class IngressScheduler:
    """
    Background Cron Daemon tự động kích hoạt Ingress ETL và Semantic Clustering.
    Hoàn toàn Deterministic / 0 LLM Token.
    """

    def __init__(self, interval_seconds: int = 900, geo: GeoCode = GeoCode.VN):
        self.interval_seconds = interval_seconds
        self.geo = geo
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def run_once(self, registry: ConnectorPluginRegistry, cluster_use_case: ClusterSignalsUseCase):
        logger.info(f"Bắt đầu chu kỳ Ingress định kỳ cho khu vực {self.geo.value}...")
        try:
            signals = await registry.fetch_from_all(geo=self.geo)
            logger.info(f"Thu thập thành công {len(signals)} signals từ các plugins.")
            if signals:
                clusters = await cluster_use_case.execute(signals)
                logger.info(f"Gom cụm thành công {len(clusters)} Topic Clusters.")
        except Exception as e:
            logger.error(f"Lỗi trong chu kỳ Ingress Scheduler: {e}", exc_info=True)

    async def start(self):
        self._running = True
        logger.info(f"Khởi động Ingress Scheduler (Chu kỳ: {self.interval_seconds}s)...")

        # 1. Setup DI
        repository = PostgresTimescaleRepository(
            dsn=settings.DATABASE_URL,
            min_pool_size=settings.DB_MIN_POOL_SIZE,
            max_pool_size=settings.DB_MAX_POOL_SIZE,
        )
        registry = ConnectorPluginRegistry()
        registry.register(GoogleTrendsRssPlugin())
        registry.register(TikTokPlugin())
        registry.register(ThreadsPlugin())
        registry.register(ReelsPlugin())

        if settings.YOUTUBE_API_KEY:
            registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

        clusterer = SemanticClusterer()
        cluster_use_case = ClusterSignalsUseCase(clusterer=clusterer, repository=repository)

        try:
            while self._running and not self._shutdown_event.is_set():
                await self.run_once(registry, cluster_use_case)
                
                try:
                    await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            logger.info("Đang đóng kết nối Repository và dừng Scheduler...")
            await repository.close()
            logger.info("Ingress Scheduler đã dừng an toàn.")

    def stop(self):
        logger.info("Nhận tín hiệu dừng Scheduler...")
        self._running = False
        self._shutdown_event.set()


async def main_async():
    scheduler = IngressScheduler(interval_seconds=int(settings.__dict__.get("SCHEDULER_INTERVAL_SECONDS", 900)))

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
