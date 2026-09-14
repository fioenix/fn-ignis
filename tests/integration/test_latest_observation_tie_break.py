"""Two observations of one source at the same instant resolve the same way every time.

The schema allows a source to be observed twice with an identical clock -- nothing forbids it,
and a pass that writes two sightings of one object in the same second produces exactly that.
Ordering only by observed_at leaves the choice to whatever order the rows come back in, so the
same corpus answered a question two ways depending on insertion order, and the cluster's score
moved with it.

The rule is: latest clock, then the larger metric, then the larger velocity, then the row id.
The first three are what the reader returns and the score is computed from, so once they tie the
remaining choice cannot change any answer.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.domain.value_objects import Timeframe
from conftest import YT_ID, YT_URL

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)
SAME_INSTANT = NOW - timedelta(hours=1)


def _cluster(case) -> str:
    cluster_id = str(uuid.uuid4())
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute(
                "INSERT INTO topic_clusters (id, canonical_name, last_updated_at)"
                " VALUES (?, ?, '2026-09-01T00:00:00+00:00')",
                (cluster_id, "tie break"),
            )
    else:
        with psycopg.connect(case.dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO topic_clusters (id, canonical_name) VALUES (%s, %s)",
                (cluster_id, "tie break"),
            )
    return cluster_id


def _observe_at_same_instant(case, cluster_id, source_id, *, metric, velocity):
    observed_at = SAME_INSTANT.isoformat() if case.name == "sqlite" else SAME_INSTANT
    return case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=observed_at,
        published_at=None,
        time_provenance="exact_ingestion",
        identity_source="metadata_external_id",
        observed_title=f"metric {metric}",
        metric_value=metric,
        growth_velocity=velocity,
        geo_code="VN",
        source_url=YT_URL,
        metadata="{}",
    )


@pytest.mark.parametrize("insertion_order", ("larger first", "smaller first"))
async def test_the_reader_picks_the_same_observation_whatever_the_insertion_order(
    repository_case, insertion_order
):
    cluster_id = _cluster(repository_case)
    source_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    pair = [(200.0, 2.0), (100.0, 1.0)]
    if insertion_order == "smaller first":
        pair.reverse()
    for metric, velocity in pair:
        _observe_at_same_instant(
            repository_case, cluster_id, source_id, metric=metric, velocity=velocity
        )

    signals = await repository_case.repository.get_cluster_signals(
        uuid.UUID(cluster_id), timeframe=Timeframe.LAST_24H
    )

    assert len(signals) == 1, "one source is still one signal"
    assert (signals[0].metric_value, signals[0].growth_velocity) == (200.0, 2.0)


@pytest.mark.parametrize("insertion_order", ("larger first", "smaller first"))
async def test_the_cluster_score_does_not_depend_on_insertion_order(
    repository_case, insertion_order
):
    """get_top_clusters reads through its own query, so it has to break the tie the same way."""
    cluster_id = _cluster(repository_case)
    source_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    pair = [(200.0, 2.0), (100.0, 1.0)]
    if insertion_order == "smaller first":
        pair.reverse()
    for metric, velocity in pair:
        _observe_at_same_instant(
            repository_case, cluster_id, source_id, metric=metric, velocity=velocity
        )

    clusters = await repository_case.repository.get_top_clusters(timeframe=Timeframe.LAST_24H)

    assert len(clusters) == 1
    assert [(s.metric_value, s.growth_velocity) for s in clusters[0].signals] == [(200.0, 2.0)]


async def test_a_later_clock_still_wins_over_a_larger_metric(repository_case):
    """The tie-break only applies to a tie: recency is not traded away for a bigger number."""
    cluster_id = _cluster(repository_case)
    source_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    _observe_at_same_instant(repository_case, cluster_id, source_id, metric=900.0, velocity=9.0)
    later = NOW - timedelta(minutes=1)
    repository_case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=later.isoformat() if repository_case.name == "sqlite" else later,
        published_at=None,
        time_provenance="exact_ingestion",
        identity_source="metadata_external_id",
        observed_title="the newest sighting",
        metric_value=1.0,
        growth_velocity=0.5,
        geo_code="VN",
        source_url=YT_URL,
        metadata="{}",
    )

    signals = await repository_case.repository.get_cluster_signals(
        uuid.UUID(cluster_id), timeframe=Timeframe.LAST_24H
    )

    assert [s.metric_value for s in signals] == [1.0]
