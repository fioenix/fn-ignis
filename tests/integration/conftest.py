"""Shared fixtures for the dual-backend contracts.

Every contract about the source/observation/evidence model has to hold on both backends, so the
repository under test is a fixture parameter rather than something each module chooses. SQLite
restates its schema in _ensure_schema and Postgres reads sql/, which is exactly the kind of
divergence these tests exist to catch.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

# A real YouTube id is 11 characters and the URL pattern needs at least 6, so a short stand-in
# would resolve by the normalized-URL fallback and a route assertion would be measuring the
# wrong thing.
YT_ID = "dQw4w9WgXcQ"
YT_URL = f"https://www.youtube.com/watch?v={YT_ID}"

SCHEMA_MIGRATIONS = (
    "001_initial_schema.sql",
    "008_deduplicate_signal_metrics.sql",
    "015_split_published_at.sql",
    "016_source_observation_model.sql",
)


@dataclass
class RepositoryCase:
    name: str
    repository: object = field(repr=False)
    dsn: str | None = field(default=None, repr=False)

    def query_one(self, sqlite_text: str, postgres_text: str, params: tuple = ()):
        if self.name == "sqlite":
            with sqlite3.connect(self.repository._db_path) as conn:
                return conn.execute(sqlite_text, params).fetchone()
        with psycopg.connect(self.dsn) as conn:
            return conn.execute(postgres_text, params).fetchone()

    def count_identity_rows(self, platform: str, source_url: str, raw_title: str) -> int:
        """How many canonical rows one external object occupies.

        It used to count trend_signals rows matching platform, URL and title. The writer no
        longer writes there, and the question the test is asking -- is one external source
        stored once -- is now answered by the sources table. The URL and title arguments stay
        so the caller still says which object it means.
        """
        del source_url, raw_title
        row = self.query_one(
            "SELECT COUNT(*) FROM sources WHERE platform = ?",
            "SELECT COUNT(*) FROM sources WHERE platform = %s",
            (platform,),
        )
        return int(row[0])

    def observation_routes(self) -> list:
        """identity_source of every observation, oldest first."""
        query = (
            "SELECT identity_source FROM observations o"
            " JOIN sources s ON s.id = o.source_id ORDER BY o.observed_at"
        )
        if self.name == "sqlite":
            with sqlite3.connect(self.repository._db_path) as conn:
                rows = conn.execute(query).fetchall()
        else:
            with psycopg.connect(self.dsn) as conn:
                rows = conn.execute(query).fetchall()
        return [row[0] for row in rows]

    def counts(self) -> dict:
        queries = {
            "sources": "SELECT count(*) FROM sources",
            "observations": "SELECT count(*) FROM observations",
            "mission_evidence": "SELECT count(*) FROM mission_evidence",
            "clustered_observations": (
                "SELECT count(*) FROM observations WHERE cluster_id IS NOT NULL"
            ),
        }
        if self.name == "sqlite":
            with sqlite3.connect(self.repository._db_path) as conn:
                return {name: conn.execute(q).fetchone()[0] for name, q in queries.items()}
        with psycopg.connect(self.dsn) as conn:
            return {name: conn.execute(q).fetchone()[0] for name, q in queries.items()}

    def insert_legacy_observation(self, **fields) -> str:
        """Write one observation directly, the way the backfill will.

        The read contract has to be testable against data no writer produces today: a legacy
        observation has no ingestion time at all, and only the backfill creates those.
        """
        columns = (
            "source_id",
            "cluster_id",
            "observed_at",
            "published_at",
            "time_provenance",
            "identity_source",
            "observed_title",
            "metric_value",
            "growth_velocity",
            "geo_code",
            "source_url",
            "metadata",
        )
        # SQLite binds no UUID objects, and the schema stores ids as text on that backend.
        values = [
            str(value) if isinstance(value := fields.get(column), UUID) else value
            for column in columns
        ]
        if self.name == "sqlite":
            observation_id = str(uuid4())
            with sqlite3.connect(self.repository._db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    f"INSERT INTO observations (id, {', '.join(columns)})"
                    f" VALUES ({', '.join(['?'] * (len(columns) + 1))})",
                    [observation_id, *values],
                )
            return observation_id
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            row = conn.execute(
                f"INSERT INTO observations ({', '.join(columns)})"
                f" VALUES ({', '.join(['%s'] * len(columns))}) RETURNING id",
                values,
            ).fetchone()
        return str(row[0])

    def insert_source(self, platform: str, external_id: str) -> str:
        if self.name == "sqlite":
            source_id = str(uuid4())
            with sqlite3.connect(self.repository._db_path) as conn:
                conn.execute(
                    "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
                    (source_id, platform, external_id),
                )
            return source_id
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            row = conn.execute(
                "INSERT INTO sources (platform, external_id) VALUES (%s, %s) RETURNING id",
                (platform, external_id),
            ).fetchone()
        return str(row[0])

    def attach_evidence(self, mission_id, observation_id: str) -> None:
        if self.name == "sqlite":
            with sqlite3.connect(self.repository._db_path) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                    " VALUES (?, ?, ?, ?)",
                    (str(uuid4()), str(mission_id), observation_id, "2026-09-11T00:00:00+00:00"),
                )
            return
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)",
                (str(mission_id), observation_id),
            )


class TwoObservationRegistry:
    """Replace only the external connectors; persistence and mission execution stay real."""

    def __init__(self, source_url: str, raw_title: str):
        self._source_url = source_url
        self._raw_title = raw_title
        self._observations = iter(
            (
                (100.0, datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)),
                (200.0, datetime(2026, 9, 10, 2, 0, tzinfo=timezone.utc)),
            )
        )

    async def search_across_all(self, **_kwargs):
        metric, captured_at = next(self._observations)
        return [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title=self._raw_title,
                metric_value=metric,
                source_url=self._source_url,
                geo_code=GeoCode.VN,
                captured_at=captured_at,
                metadata={"channel_title": "Canonical Source Test"},
            )
        ]


class OneSightingRegistry:
    """One sighting, with the connector's metadata under the test's control.

    TwoObservationRegistry reports channel_title and no video_id, so it exercises the URL route.
    The route a signal takes is decided by exactly this: whether the connector wrote the
    platform's own identifier.
    """

    def __init__(self, source_url: str, raw_title: str, metadata: dict, platform=None):
        self._source_url = source_url
        self._raw_title = raw_title
        self._metadata = metadata
        self._platform = platform or PlatformType.YOUTUBE

    async def search_across_all(self, **_kwargs):
        return [
            TrendSignal(
                platform=self._platform,
                raw_title=self._raw_title,
                metric_value=100.0,
                source_url=self._source_url,
                geo_code=GeoCode.VN,
                captured_at=datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc),
                metadata=dict(self._metadata),
            )
        ]


class SilentRegistry:
    """A connector that returns nothing this pass -- the quota exhaustion case."""

    async def search_across_all(self, **_kwargs):
        return []


def _postgres_dsns() -> tuple[str, str, str]:
    base_dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if not base_dsn:
        pytest.skip("IGNIS_TEST_POSTGRES_DSN is required for the real Postgres repository contract")

    parts = conninfo_to_dict(base_dsn)
    database_name = f"ignis_contract_{uuid4().hex}"
    admin_dsn = make_conninfo(**parts)
    test_dsn = make_conninfo(**{**parts, "dbname": database_name})
    return admin_dsn, test_dsn, database_name


def _apply_postgres_schema(dsn: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    with psycopg.connect(dsn) as conn:
        for migration in SCHEMA_MIGRATIONS:
            conn.execute((repo_root / "sql" / migration).read_text(encoding="utf-8"))


@pytest_asyncio.fixture(params=("sqlite", "postgres"))
async def repository_case(request, tmp_path):
    if request.param == "sqlite":
        repository = SqliteTrendRepository(str(tmp_path / "mission_identity.sqlite"))
        await repository._ensure_schema()
        case = RepositoryCase(name="sqlite", repository=repository)
        try:
            yield case
        finally:
            await repository.close()
        return

    admin_dsn, test_dsn, database_name = _postgres_dsns()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        _apply_postgres_schema(test_dsn)
        repository = PostgresTimescaleRepository(dsn=test_dsn, min_pool_size=1, max_pool_size=2)
        try:
            yield RepositoryCase(name="postgres", repository=repository, dsn=test_dsn)
        finally:
            await repository.close()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))
