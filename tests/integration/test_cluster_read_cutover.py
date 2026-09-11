"""The cluster readers answer from observations, and from nothing else.

Two halves, and the second is the one that catches a half-finished cutover: data present only in
the new model has to be readable, and a change to the legacy table must not move the answer. A
reader that still consults trend_signals passes the first and fails the second.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.domain.cross_platform_score import cross_platform_score
from ignis.domain.value_objects import Timeframe
from conftest import YT_ID, YT_URL

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


def _exec(case, statement, params=()):
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute(statement, params)
        return
    with psycopg.connect(case.dsn, autocommit=True) as conn:
        conn.execute(statement.replace("?", "%s"), params)


def _cluster(case, name="a cluster") -> str:
    cluster_id = str(uuid.uuid4())
    if case.name == "sqlite":
        _exec(
            case,
            "INSERT INTO topic_clusters (id, canonical_name, last_updated_at)"
            " VALUES (?, ?, '2026-09-01T00:00:00+00:00')",
            (cluster_id, name),
        )
    else:
        _exec(case, "INSERT INTO topic_clusters (id, canonical_name) VALUES (?, ?)", (cluster_id, name))
    return cluster_id


def _observe(case, cluster_id, platform, external_id, *, hours_ago=1, metric=100.0,
             velocity=1.0, provenance="exact_ingestion", url=YT_URL):
    source_id = case.insert_source(platform, external_id)
    observed_at = None if provenance == "legacy_publish_only" else NOW - timedelta(hours=hours_ago)
    return case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=observed_at.isoformat() if observed_at and case.name == "sqlite" else observed_at,
        published_at=None,
        time_provenance=provenance,
        identity_source="metadata_external_id",
        observed_title=f"{platform} {external_id}",
        metric_value=metric,
        growth_velocity=velocity,
        geo_code="VN",
        source_url=url,
        metadata="{}",
    )


async def test_a_cluster_is_readable_from_the_new_model_alone(repository_case):
    """Nothing is written to trend_signals here at all."""
    cluster_id = _cluster(repository_case)
    _observe(repository_case, cluster_id, "youtube", f"video:{YT_ID}")
    _observe(repository_case, cluster_id, "tiktok", "video:7300000000000000001")

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert [str(c.id) for c in clusters] == [cluster_id]
    assert len(clusters[0].signals) == 2
    signals = await repository_case.repository.get_cluster_signals(
        uuid.UUID(cluster_id), timeframe=Timeframe.LAST_24H
    )
    assert len(signals) == 2


async def test_changing_the_legacy_table_does_not_move_the_answer(repository_case):
    """The half-finished cutover fails here and only here."""
    cluster_id = _cluster(repository_case)
    _observe(repository_case, cluster_id, "youtube", f"video:{YT_ID}")
    before = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    _exec(
        repository_case,
        "INSERT INTO trend_signals (platform, raw_title, metric_value, growth_velocity,"
        " source_url, geo_code, cluster_id, metadata, captured_at)"
        " VALUES ('threads', 'a legacy row nobody observed', 999999.0, 99.0,"
        " 'https://threads.net/@a/post/P9', 'VN', ?, '{}', ?)",
        (cluster_id, NOW.isoformat() if repository_case.name == "sqlite" else NOW),
    )

    after = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert len(after) == len(before) == 1
    assert after[0].cross_platform_score == before[0].cross_platform_score
    assert len(after[0].signals) == len(before[0].signals) == 1


async def test_the_default_window_ignores_observations_with_no_known_clock(repository_case):
    """published_at is not a substitute: 17,118 legacy observations have no collection time."""
    cluster_id = _cluster(repository_case)
    _observe(repository_case, cluster_id, "youtube", f"video:{YT_ID}")
    _observe(repository_case, cluster_id, "threads", "post:P1", provenance="legacy_publish_only")

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert len(clusters[0].signals) == 1, "only the observation whose clock is known"
    assert clusters[0].cross_platform_score == cross_platform_score(
        distinct_platforms=1, total_metric=100.0, average_velocity=1.0
    )


async def test_a_clock_the_migration_could_not_vouch_for_is_not_admitted(repository_case):
    """The window filters on provenance, not only on whether a clock is present.

    A legacy observation normally has observed_at NULL, so a test built on that alone passes
    with the provenance filter removed -- it is the NULL doing the work. This one carries a
    timestamp inside the window and a label saying the timestamp is not a known collection time,
    which is the only shape that tells the two conditions apart.
    """
    cluster_id = _cluster(repository_case)
    _observe(repository_case, cluster_id, "youtube", f"video:{YT_ID}")
    source_id = repository_case.insert_source("threads", "post:P1")
    repository_case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=(NOW - timedelta(hours=1)).isoformat()
        if repository_case.name == "sqlite"
        else NOW - timedelta(hours=1),
        time_provenance="unknown",
        identity_source="url_external_id",
        observed_title="a clock nobody can vouch for",
        metric_value=500000.0,
        growth_velocity=50.0,
        geo_code="VN",
        source_url="https://threads.net/@a/post/P1",
        metadata="{}",
    )

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert len(clusters[0].signals) == 1
    assert clusters[0].signals[0].platform.value == "youtube"


async def test_one_source_counts_once_however_often_it_was_polled(repository_case):
    """Polling frequency belongs to the harness, not to the topic."""
    cluster_id = _cluster(repository_case)
    source_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    for hours_ago, metric in ((3, 100.0), (2, 200.0), (1, 300.0)):
        repository_case.insert_legacy_observation(
            source_id=source_id,
            cluster_id=cluster_id,
            observed_at=(NOW - timedelta(hours=hours_ago)).isoformat()
            if repository_case.name == "sqlite"
            else NOW - timedelta(hours=hours_ago),
            time_provenance="exact_ingestion",
            identity_source="metadata_external_id",
            observed_title="Polled three times",
            metric_value=metric,
            growth_velocity=1.0,
            geo_code="VN",
            source_url=YT_URL,
            metadata="{}",
        )

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert len(clusters[0].signals) == 1, "one source, one contribution"
    assert clusters[0].signals[0].metric_value == 300.0, "and it is the most recent sighting"


async def test_the_platform_bands_are_the_recorded_ones(repository_case):
    """1 -> 0, 2 -> 20, 3+ -> 40. The SQL used to divide the count by five instead."""
    cluster_id = _cluster(repository_case)
    for index, (platform, external_id) in enumerate(
        (("youtube", f"video:{YT_ID}"), ("tiktok", "video:7300000000000000001"),
         ("threads", "post:P1"))
    ):
        _observe(repository_case, cluster_id, platform, external_id, metric=0.0, velocity=0.0,
                 hours_ago=index + 1)

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert clusters[0].cross_platform_score == 40.0, "three platforms take the whole band"


async def test_the_pruner_keeps_a_cluster_whose_only_observation_is_legacy(repository_case):
    """Membership, not recency. Pruning on the window would delete most of the backfilled topics."""
    kept = _cluster(repository_case, "legacy only")
    _observe(repository_case, kept, "youtube", f"video:{YT_ID}", provenance="legacy_publish_only")
    empty = _cluster(repository_case, "no observations at all")

    removed = await repository_case.repository.prune_empty_clusters()

    remaining = repository_case.query_one(
        "SELECT count(*) FROM topic_clusters WHERE id = ?",
        "SELECT count(*) FROM topic_clusters WHERE id = %s",
        (kept,),
    )
    gone = repository_case.query_one(
        "SELECT count(*) FROM topic_clusters WHERE id = ?",
        "SELECT count(*) FROM topic_clusters WHERE id = %s",
        (empty,),
    )
    assert removed >= 1
    assert remaining[0] == 1, "a cluster outside the analysis window is not an empty cluster"
    assert gone[0] == 0


async def test_the_pruner_ignores_the_legacy_table(repository_case):
    """A cluster with legacy rows but no observation is empty in the model that now counts."""
    cluster_id = _cluster(repository_case, "legacy rows only")
    _exec(
        repository_case,
        "INSERT INTO trend_signals (platform, raw_title, metric_value, source_url, geo_code,"
        " cluster_id, metadata, captured_at)"
        " VALUES ('youtube', 'a legacy row', 1.0, ?, 'VN', ?, '{}', ?)",
        (YT_URL, cluster_id, NOW.isoformat() if repository_case.name == "sqlite" else NOW),
    )

    await repository_case.repository.prune_empty_clusters()

    survived = repository_case.query_one(
        "SELECT count(*) FROM topic_clusters WHERE id = ?",
        "SELECT count(*) FROM topic_clusters WHERE id = %s",
        (cluster_id,),
    )
    assert survived[0] == 0
