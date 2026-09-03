import argparse
import asyncio
import logging

from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.config import settings
from ignis.domain.value_objects import resolve_geo, resolve_timeframe
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.persistence import create_repository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ignis.cli")


async def run_ingest(geo_code: str = "VN", timeframe_str: str = "24h", db_url: str | None = None):
    """CLI Runner executing standalone Ingress pipeline (Zero-Token Background ETL)."""
    geo = resolve_geo(geo_code)
    timeframe = resolve_timeframe(timeframe_str)
    logger.info(f"Starting fn-ignis Ingress CLI for region {geo.value}, timeframe {timeframe.value}...")

    # 1. Initialize Registry and register active Plugins
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())

    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))
    else:
        logger.warning("YOUTUBE_API_KEY not configured in environment. Skipping YouTube Plugin.")

    # 2. Initialize Repository (supports both SQLite and PostgreSQL)
    repository = create_repository(dsn=db_url)

    # 3. Trigger Ingest Use Case
    use_case = IngestTrendsUseCase(registry=registry, repository=repository)
    try:
        result = await use_case.execute(geo=geo, timeframe=timeframe)
        logger.info(f"Ingest completed: {result}")
        return result
    finally:
        await repository.close()


def main():
    parser = argparse.ArgumentParser(description="fn-ignis — Zero-Token Trend Ingress CLI Runner")
    parser.add_argument(
        "--geo",
        "-g",
        default=settings.DEFAULT_GEO,
        help="ISO 3166-1 country code (e.g., VN, US, JP, BR) [default: %(default)s]",
    )
    parser.add_argument(
        "--timeframe",
        "-t",
        default="24h",
        help="Ingress timeframe (e.g., 24h, 7d, 30d, 90d, 12m) [default: %(default)s]",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Database connection URL (Postgres or sqlite:///ignis.db)",
    )
    args = parser.parse_args()

    asyncio.run(run_ingest(geo_code=args.geo, timeframe_str=args.timeframe, db_url=args.db))


if __name__ == "__main__":
    main()

