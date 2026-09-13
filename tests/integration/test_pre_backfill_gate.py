"""A runtime that meets a migrated-but-not-backfilled database refuses to run.

sql/016 creates sources, observations and mission_evidence empty. Between that statement and a
finished backfill the corpus has two truths and the new one is blank: every read answers "there
is nothing", every write starts building a second history beside the first, and the pruner --
before this branch guarded it -- deleted the topics the backfill was about to carry over.

There is no safe behaviour in that state, so the repository declines to open in it and names the
script that ends it. The check is at startup because that is where the window opens: the deploy
that ships the new runtime either happens after the backfill or it does not.
"""

import sqlite3

import psycopg
import pytest

from ignis.domain.exceptions import RepositoryException
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from conftest import YT_URL

pytestmark = pytest.mark.asyncio

LEGACY_ROW = (
    "INSERT INTO trend_signals (platform, raw_title, metric_value, source_url, geo_code,"
    " metadata, captured_at) VALUES ('youtube', 'a legacy row', 1.0, '{url}', 'VN', '{{}}',"
    " '2026-08-01T00:00:00+00:00')"
).format(url=YT_URL)


def _seed_legacy(case):
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute(LEGACY_ROW)
        return
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        conn.execute(LEGACY_ROW)


def _reopen(case):
    if case.name == "sqlite":
        return SqliteTrendRepository(case.repository._db_path)
    return PostgresTimescaleRepository(dsn=case.dsn, min_pool_size=1, max_pool_size=2)


async def _readiness(repository):
    """Whatever each backend does before serving its first query."""
    if isinstance(repository, SqliteTrendRepository):
        await repository._ensure_schema()
    else:
        await repository._get_pool()


async def test_a_corpus_that_was_never_backfilled_is_refused(repository_case):
    _seed_legacy(repository_case)
    fresh = _reopen(repository_case)

    try:
        with pytest.raises(RepositoryException) as refusal:
            await _readiness(fresh)
    finally:
        await fresh.close()

    message = str(refusal.value)
    assert "backfill_observations" in message, "the refusal has to name the way out of it"


async def test_a_backfilled_corpus_opens_normally(repository_case):
    """One observation is enough: the gate asks whether the backfill ran, not how far it got."""
    _seed_legacy(repository_case)
    source_id = repository_case.insert_source("youtube", "video:dQw4w9WgXcQ")
    repository_case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=None,
        observed_at=None,
        published_at=None,
        time_provenance="legacy_publish_only",
        identity_source="metadata_external_id",
        observed_title="carried over",
        metric_value=1.0,
        growth_velocity=0.0,
        geo_code="VN",
        source_url=YT_URL,
        metadata="{}",
    )
    fresh = _reopen(repository_case)

    try:
        await _readiness(fresh)
    finally:
        await fresh.close()


async def test_an_empty_database_opens_normally(repository_case):
    """A database with no legacy corpus was never waiting on a backfill."""
    fresh = _reopen(repository_case)
    try:
        await _readiness(fresh)
    finally:
        await fresh.close()
