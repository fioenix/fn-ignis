"""Behavioral contract for source identity and mission evidence across both repositories."""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@dataclass
class RepositoryCase:
    name: str
    repository: object = field(repr=False)
    dsn: str | None = field(default=None, repr=False)

    def count_identity_rows(self, platform: str, source_url: str, raw_title: str) -> int:
        if self.name == "sqlite":
            with sqlite3.connect(self.repository._db_path) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM trend_signals
                    WHERE platform = ? AND source_url = ? AND raw_title = ?
                    """,
                    (platform, source_url, raw_title),
                ).fetchone()
        else:
            with psycopg.connect(self.dsn) as conn:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM trend_signals
                    WHERE platform = %s AND source_url = %s AND raw_title = %s
                    """,
                    (platform, source_url, raw_title),
                ).fetchone()
        return int(row[0])

    def observation_routes(self) -> list:
        """identity_source of every observation, in the order they were written."""
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
        for migration in (
            "001_initial_schema.sql",
            "008_deduplicate_signal_metrics.sql",
            "015_split_published_at.sql",
            "016_source_observation_model.sql",
        ):
            conn.execute((repo_root / "sql" / migration).read_text(encoding="utf-8"))


@pytest_asyncio.fixture(params=("sqlite", "postgres"))
async def repository_case(request, tmp_path):
    if request.param == "sqlite":
        repository = SqliteTrendRepository(str(tmp_path / "mission_identity.sqlite"))
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


@pytest.mark.asyncio
async def test_one_source_keeps_distinct_evidence_for_two_missions(repository_case):
    """One external source is canonical once while each mission keeps its metric snapshot."""
    repository = repository_case.repository
    source_url = "https://www.youtube.com/watch?v=one-source"
    raw_title = "One source observed by two missions"
    registry = TwoObservationRegistry(source_url=source_url, raw_title=raw_title)
    use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
    )
    mission_a = ResearchMission(
        title="Mission A",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    mission_b = ResearchMission(
        title="Mission B",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission_a)
    await repository.save_mission(mission_b)

    result_a = await use_case.execute(mission_a.id)
    result_b = await use_case.execute(mission_b.id)

    evidence_a = await repository.get_mission_signals(mission_a.id)
    evidence_b = await repository.get_mission_signals(mission_b.id)
    assert result_a["total_signals"] == result_b["total_signals"] == 1
    identity_rows = repository_case.count_identity_rows("youtube", source_url, raw_title)
    assert identity_rows == 1, f"{repository_case.name} stored one external source as {identity_rows} rows"
    assert len(evidence_a) == 1, "mission A lost the source it observed"
    assert len(evidence_b) == 1, "mission B lost the source it observed"
    assert [signal.metric_value for signal in evidence_a] == [100.0]
    assert [signal.metric_value for signal in evidence_b] == [200.0]


class UrlOnlyRegistry:
    """One sighting whose identifier is only recoverable from its URL."""

    def __init__(self, source_url: str, raw_title: str):
        self._source_url = source_url
        self._raw_title = raw_title

    async def search_across_all(self, **_kwargs):
        return [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title=self._raw_title,
                metric_value=100.0,
                source_url=self._source_url,
                geo_code=GeoCode.VN,
                captured_at=datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc),
                metadata={},
            )
        ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata_carries_the_id", "expected_route"),
    ((True, "metadata_external_id"), (False, "url_external_id")),
)
async def test_an_observation_records_the_route_that_resolved_it(
    repository_case, metadata_carries_the_id, expected_route
):
    """The live writer has to store the route the resolver returned, not a default.

    A real YouTube id is 11 characters and the URL pattern needs at least 6, so a short stand-in
    would resolve by the normalized-URL fallback and this test would assert the wrong route.
    """
    repository = repository_case.repository
    source_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    raw_title = "One source, one route"
    registry = (
        TwoObservationRegistry(source_url=source_url, raw_title=raw_title)
        if metadata_carries_the_id
        else UrlOnlyRegistry(source_url=source_url, raw_title=raw_title)
    )
    use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
    )
    mission = ResearchMission(
        title="Route",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    await use_case.execute(mission.id)

    assert repository_case.observation_routes() == [expected_route]
