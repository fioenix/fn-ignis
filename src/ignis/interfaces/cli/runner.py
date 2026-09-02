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
    """CLI Runner executing standalone Ingress pipeline (Zero-Token Background ETL)."""
    geo = GeoCode(geo_code.upper())
    logger.info(f"Starting fn-ignis Ingress CLI for region {geo.value}...")

    # 1. Initialize Registry and register active Plugins
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())

    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))
    else:
        logger.warning("YOUTUBE_API_KEY not configured in environment. Skipping YouTube Plugin.")

    # 2. Initialize Repository
    repository = PostgresTimescaleRepository(
        dsn=settings.DATABASE_URL,
        min_pool_size=settings.DB_MIN_POOL_SIZE,
        max_pool_size=settings.DB_MAX_POOL_SIZE,
    )

    # 3. Trigger Ingest Use Case
    use_case = IngestTrendsUseCase(registry=registry, repository=repository)
    try:
        result = await use_case.execute(geo=geo, timeframe=Timeframe.LAST_24H)
        logger.info(f"Ingest completed: {result}")
    finally:
        await repository.close()



def main():
    geo_arg = sys.argv[1] if len(sys.argv) > 1 else settings.DEFAULT_GEO
    asyncio.run(run_ingest(geo_code=geo_arg))


if __name__ == "__main__":
    main()
