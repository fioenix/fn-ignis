import asyncio
import logging
import sys

from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.config import settings
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ignis.cli")


async def run_ingest(geo_code: str = "VN"):
    """CLI Runner chạy Ingress pipeline độc lập (Zero-Token Background ETL)."""
    geo = GeoCode(geo_code.upper())
    logger.info(f"Khởi động fn-ignis Ingress CLI cho khu vực {geo.value}...")

    # 1. Khởi tạo Registry và đăng ký Plugins
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())

    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))
    else:
        logger.warning("Không tìm thấy YOUTUBE_API_KEY trong cấu hình. Bỏ qua YouTube Plugin.")

    # 2. Khởi tạo Repository
    repository = PostgresTimescaleRepository(
        dsn=settings.DATABASE_URL,
        min_pool_size=settings.DB_MIN_POOL_SIZE,
        max_pool_size=settings.DB_MAX_POOL_SIZE,
    )

    # 3. Kích hoạt Ingest Use Case
    use_case = IngestTrendsUseCase(registry=registry, repository=repository)
    try:
        result = await use_case.execute(geo=geo, timeframe=Timeframe.LAST_24H)
        logger.info(f"Ingest hoàn tất: {result}")
    finally:
        await repository.close()


def main():
    geo_arg = sys.argv[1] if len(sys.argv) > 1 else settings.DEFAULT_GEO
    asyncio.run(run_ingest(geo_code=geo_arg))


if __name__ == "__main__":
    main()
