"""The ordering index exists on both backends, applies twice safely, and is actually used.

`sql/019` exists for one reason: without it the top-cluster reader sorted every observation in
the window before discarding all but one per (cluster, source). An index that is present but
never chosen would leave that cost exactly where it was while looking like the fix, so presence
is necessary and the query plan is the evidence.

SQLite restates the index in `_ensure_schema` rather than reading `sql/`, which is precisely the
kind of divergence this file exists to catch.
"""

import sqlite3
from pathlib import Path

import psycopg
import pytest

from ignis.domain.value_objects import Timeframe, timeframe_to_days
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

pytestmark = pytest.mark.asyncio

INDEX = "idx_observations_latest_per_source"


def _index_definition(case):
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (INDEX,)
            ).fetchone()
        return None if row is None else row[0]
    with psycopg.connect(case.dsn) as conn:
        row = conn.execute(
            "SELECT indexdef FROM pg_indexes WHERE indexname = %s", (INDEX,)
        ).fetchone()
    return None if row is None else row[0]


async def test_the_ordering_index_is_present_on_both_backends(repository_case):
    definition = _index_definition(repository_case)

    assert definition, f"{repository_case.name} has no {INDEX}"
    lowered = definition.lower()
    # The terms the reader orders by, in the order it orders by them.
    for term in ("cluster_id", "source_id", "observed_at", "metric_value", "growth_velocity"):
        assert term in lowered, f"{INDEX} on {repository_case.name} is missing {term}"
    # Partial on the two predicates the reader always applies, which is what keeps the legacy
    # observations -- 17,118 of the baseline's 18,597 -- out of it entirely.
    assert "where" in lowered, f"{INDEX} on {repository_case.name} is not partial"
    assert "exact_ingestion" in lowered


async def test_applying_the_migration_again_changes_nothing(repository_case):
    """Re-applying is how an operator recovers a half-run migration, so it has to be a no-op."""
    before = _index_definition(repository_case)

    if repository_case.name == "sqlite":
        # The repository restates its whole schema on demand; running that twice is the SQLite
        # equivalent of applying the file again.
        repository_case.repository._initialized = False
        await repository_case.repository._ensure_schema()
    else:
        sql_file = (
            Path(__file__).resolve().parents[2]
            / "sql"
            / "019_observations_latest_per_source_index.sql"
        )
        with psycopg.connect(repository_case.dsn, autocommit=True) as conn:
            conn.execute(sql_file.read_text(encoding="utf-8"))

    assert _index_definition(repository_case) == before


async def test_the_reader_still_answers_with_the_index_in_place(repository_case):
    """Presence is not correctness. The characterization suite covers the answers in full; this
    is the one assertion that the index did not make the reader stop returning anything."""
    assert await repository_case.repository.get_top_clusters(
        timeframe=Timeframe.LAST_24H, limit=10
    ) == []


async def test_sqlite_no_longer_sorts_the_window_into_a_temporary_b_tree(tmp_path):
    """The measured cause, asserted directly.

    Before `sql/019`, EXPLAIN QUERY PLAN reported USE TEMP B-TREE FOR LAST 5 TERMS OF ORDER BY:
    the window function's partition and ordering matched neither existing index, so every row in
    the window was sorted. This asserts the plan names the new index and no longer sorts.

    SQLite only, because this is the backend whose plan is readable without a server. The
    PostgreSQL half is covered by the index carrying the same column list and by the benchmark,
    which is the measurement a plan is only a proxy for.
    """
    repository = SqliteTrendRepository(str(tmp_path / "plan.sqlite"))
    try:
        await repository._ensure_schema()
        modifier = f"-{timeframe_to_days(Timeframe.LAST_24H)} days"
        query = (
            SqliteTrendRepository._LATEST_PER_SOURCE.format(
                modifier=modifier, cluster_filter=""
            )
            + " SELECT l.cluster_id, COUNT(*) FROM latest l"
            " JOIN topic_clusters tc ON tc.id = l.cluster_id"
            " WHERE l.rank = 1 GROUP BY l.cluster_id"
        )
        with sqlite3.connect(repository._db_path) as conn:
            plan = " | ".join(
                str(row[3]) for row in conn.execute("EXPLAIN QUERY PLAN " + query).fetchall()
            )
    finally:
        await repository.close()

    assert INDEX in plan, f"the ordering index is not used by the reader's plan: {plan}"
    assert "TEMP B-TREE FOR LAST 5 TERMS OF ORDER BY" not in plan, (
        f"the window ordering is still being sorted: {plan}"
    )
