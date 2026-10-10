from typing import Optional
from ignis.application.ports.repository_port import ITrendRepository
from ignis.config import reveal_secret, settings
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def create_repository(dsn: Optional[str] = None, *, min_pool_size=None, max_pool_size=None) -> ITrendRepository:
    """
    Factory function to initialize the appropriate storage adapter based on connection string:
    - sqlite://... -> SqliteTrendRepository (Zero-Docker mode)
    - postgresql://... -> PostgresTimescaleRepository (Production / Cloud mode)
    """
    target_dsn = dsn or reveal_secret(settings.DATABASE_URL)
    if target_dsn.startswith("sqlite"):
        return SqliteTrendRepository(db_path=target_dsn)
    else:
        return PostgresTimescaleRepository(
            dsn=target_dsn,
            min_pool_size=settings.DB_MIN_POOL_SIZE if min_pool_size is None else min_pool_size,
            max_pool_size=settings.DB_MAX_POOL_SIZE if max_pool_size is None else max_pool_size,
        )


__all__ = [
    "ITrendRepository",
    "PostgresTimescaleRepository",
    "SqliteTrendRepository",
    "create_repository",
]
