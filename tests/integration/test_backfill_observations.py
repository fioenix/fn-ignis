"""What the backfill must guarantee before it is allowed near a real corpus.

These run on both backends, because the two differ in exactly the places that matter here: what
a transaction rolls back, whether a foreign key is enforced, and what an upsert returns.
"""

import sqlite3
import uuid

import psycopg
import pytest

from scripts.backfill_observations import (
    BackfillRefused,
    backfill,
    observation_id_for,
    open_target,
)
from conftest import YT_ID, YT_URL

pytestmark = pytest.mark.asyncio

OTHER_ID = "9bZkp7q19f0"
OTHER_URL = f"https://www.youtube.com/watch?v={OTHER_ID}"


def _dsn(case) -> str:
    if case.name == "sqlite":
        return f"sqlite:///{case.repository._db_path}"
    return case.dsn


def _seed_legacy(case, mission_id=None, cluster_id=None):
    """Two legacy signals and three metric points, written the way the old schema held them.

    One point repeats its parent's payload -- the copy sql/008 made -- and two do not.
    """
    rows = [
        # id values both backends accept: BIGSERIAL on Postgres, TEXT on SQLite.
        (
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity,"
            " source_url, geo_code, cluster_id, mission_id, metadata, captured_at, published_at)"
            " VALUES (?, 'youtube', 'First video', 100.0, 1.0, ?, 'VN', ?, ?, ?,"
            " '2026-09-01T00:00:00+00:00', NULL)",
            ("1", YT_URL, cluster_id, mission_id, '{"video_id": "' + YT_ID + '"}'),
        ),
        (
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity,"
            " source_url, geo_code, cluster_id, mission_id, metadata, captured_at, published_at)"
            " VALUES (?, 'threads', 'A post', 50.0, 0.5, ?, 'VN', NULL, NULL, ?,"
            " '2026-09-02T00:00:00+00:00', NULL)",
            ("2", "https://www.threads.net/@a/post/P1", '{"post_id": "P1"}'),
        ),
    ]
    points = [
        ("1", "2026-09-01T00:00:00+00:00", 100.0, 1.0),  # the sql/008 copy
        ("1", "2026-09-03T00:00:00+00:00", 300.0, 2.0),
        ("2", "2026-09-04T00:00:00+00:00", 80.0, 0.9),
    ]
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            for statement, params in rows:
                conn.execute(statement, params)
            conn.executemany(
                "INSERT INTO signal_metrics (signal_id, captured_at, metric_value,"
                " growth_velocity) VALUES (?, ?, ?, ?)",
                points,
            )
        return
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        for statement, params in rows:
            conn.execute(statement.replace("?", "%s"), params)
        for point in points:
            conn.execute(
                "INSERT INTO signal_metrics (signal_id, captured_at, metric_value,"
                " growth_velocity) VALUES (%s, %s, %s, %s)",
                point,
            )


def _run(case, **kwargs) -> dict:
    target = open_target(_dsn(case))
    try:
        return backfill(target, **kwargs)
    finally:
        target.close()


def _observation_rows(case) -> list:
    query = (
        "SELECT id, source_id, cluster_id, observed_at, time_provenance, identity_source,"
        " metric_value FROM observations ORDER BY id"
    )
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            return [tuple(str(v) for v in row) for row in conn.execute(query)]
    with psycopg.connect(case.dsn) as conn:
        return [tuple(str(v) for v in row) for row in conn.execute(query)]


# --- the two mandatory contracts ---------------------------------------------------------------


async def test_running_the_backfill_twice_changes_nothing(repository_case):
    """Same ids, same counts, same rows. A second run is a no-op, not a second corpus."""
    _seed_legacy(repository_case)

    first = _run(repository_case, apply=True)
    rows_after_first = _observation_rows(repository_case)
    counts_after_first = repository_case.counts()

    second = _run(repository_case, apply=True)

    assert first["applied"] and second["applied"]
    assert second["pre_existing_observations"] == first["observations"]
    assert _observation_rows(repository_case) == rows_after_first
    assert repository_case.counts() == counts_after_first


async def test_a_failure_partway_leaves_all_three_tables_untouched(repository_case):
    """The sources are already written when it fails, and none of them may survive."""
    _seed_legacy(repository_case)
    before = repository_case.counts()

    def fail_after_sources():
        raise RuntimeError("writer died halfway")

    with pytest.raises(RuntimeError):
        _run(repository_case, apply=True, after_sources=fail_after_sources)

    assert repository_case.counts() == before
    assert before["sources"] == 0 and before["observations"] == 0


# --- the fixture that proves the source id is the database's, not the plan's --------------------


async def test_a_source_the_live_writer_already_created_is_reused(repository_case):
    """A random-id source with the same business identity must be joined, not duplicated.

    Deriving the source id instead of taking what the upsert returns would hit
    UNIQUE(platform, external_id) and abandon every observation already pointing at that row.
    """
    _seed_legacy(repository_case)
    existing_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    assert uuid.UUID(existing_id)  # written with a random id, the way the live writer does

    summary = _run(repository_case, apply=True)

    counts = repository_case.counts()
    assert counts["sources"] == summary["sources"], "no second row for the same external object"
    source_ids = {row[1] for row in _observation_rows(repository_case)}
    assert existing_id in source_ids, "the observations must hang off the row that already existed"


# --- what the writer refuses --------------------------------------------------------------------


async def test_an_observation_this_backfill_did_not_plan_stops_the_run(repository_case):
    """Live observations have random ids and no lineage, so there is nothing to reconcile to."""
    _seed_legacy(repository_case)
    source_id = repository_case.insert_source("youtube", f"video:{OTHER_ID}")
    repository_case.insert_legacy_observation(
        source_id=source_id,
        observed_at="2026-09-11T00:00:00+00:00",
        time_provenance="exact_ingestion",
        identity_source="metadata_external_id",
        metric_value=1.0,
        metadata="{}",
    )

    with pytest.raises(BackfillRefused, match="did not plan"):
        _run(repository_case, apply=True)

    assert repository_case.counts()["observations"] == 1, "the run stopped before writing"


async def test_a_signal_identifying_nothing_stops_the_run(repository_case):
    """Not skipped. A dropped row is invisible to the reconciliation that follows."""
    statement = (
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity,"
        " source_url, geo_code, metadata, captured_at)"
        " VALUES ('9', 'youtube', 'No identity', 1.0, 0.0, NULL, 'VN', '{}',"
        " '2026-09-01T00:00:00+00:00')"
    )
    if repository_case.name == "sqlite":
        with sqlite3.connect(repository_case.repository._db_path) as conn:
            conn.execute(statement)
    else:
        with psycopg.connect(repository_case.dsn, autocommit=True) as conn:
            conn.execute(statement)

    with pytest.raises(BackfillRefused, match="no external identity"):
        _run(repository_case, apply=True)

    assert repository_case.counts()["observations"] == 0


async def test_a_metric_point_without_a_lineage_id_stops_the_run():
    """An id derived from nothing is an id a second run cannot reproduce."""
    with pytest.raises(BackfillRefused, match="no lineage id"):
        observation_id_for("signal_metrics", "")


# --- what the plan puts where --------------------------------------------------------------------


async def test_only_the_parent_observation_carries_the_cluster_and_the_mission(repository_case):
    """A metric point says the source was seen again, not which cluster that sighting served.

    Measured on the corpus: 15,754 legacy rows carry a cluster and 2,637 surviving metric points
    hang off them, so copying the cluster down would make the membership multiset 18,391 against
    a baseline of 15,754. The mission ledger is the same shape -- one claim per legacy row.
    """
    cluster_id = str(uuid.uuid4())
    mission_id = str(uuid.uuid4())
    _insert_cluster_and_mission(repository_case, cluster_id, mission_id)
    _seed_legacy(repository_case, mission_id=mission_id, cluster_id=cluster_id)

    summary = _run(repository_case, apply=True)

    assert summary["observations"] == 4, "2 rows + 3 points - 1 sql/008 copy"
    assert summary["cluster_memberships"] == 1
    assert summary["mission_evidence"] == 1
    parent_id = observation_id_for("trend_signals", "1")
    clustered = {row[0] for row in _observation_rows(repository_case) if row[2] != "None"}
    assert clustered == {parent_id}


async def test_an_observation_id_comes_from_lineage_and_not_from_payload():
    """Two events identical on every field are two observations, so content cannot be the key."""
    assert observation_id_for("trend_signals", "1") != observation_id_for("signal_metrics", "1")
    assert observation_id_for("trend_signals", "1") == observation_id_for("trend_signals", "1")


def _insert_cluster_and_mission(case, cluster_id: str, mission_id: str) -> None:
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute(
                "INSERT INTO topic_clusters (id, canonical_name, last_updated_at)"
                " VALUES (?, 'a cluster', '2026-09-01')",
                (cluster_id,),
            )
            conn.execute(
                "INSERT INTO research_missions (id, title, keywords, created_at)"
                " VALUES (?, 'a mission', '[]', '2026-09-01')",
                (mission_id,),
            )
        return
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO topic_clusters (id, canonical_name) VALUES (%s, 'a cluster')",
            (cluster_id,),
        )
        conn.execute(
            "INSERT INTO research_missions (id, title, keywords, platforms, geo_code, timeframe,"
            " status) VALUES (%s, 'a mission', '{}', '{}', 'VN', '7d', 'COMPLETED')",
            (mission_id,),
        )
