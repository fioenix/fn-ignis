"""The writer touches the new model and leaves the legacy tables exactly as it found them.

The legacy tables stay in the schema on purpose: the audit reads them, the backfill reads them,
and they are the only record of what the corpus looked like before the migration. What stops is
writing to them. Until it does there are two sources of truth again the moment ingress resumes,
with the legacy side growing and the new model standing still.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from conftest import YT_ID, YT_URL

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _legacy_state(case) -> dict:
    """Row counts and full payloads, so an UPDATE shows up as well as an INSERT."""
    signals = "SELECT platform, raw_title, metric_value, growth_velocity, metadata, captured_at FROM trend_signals ORDER BY platform, raw_title"
    metrics = "SELECT signal_id, captured_at, metric_value, growth_velocity FROM signal_metrics ORDER BY signal_id, captured_at"
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            return {
                "signals": [tuple(str(v) for v in row) for row in conn.execute(signals)],
                "metrics": [tuple(str(v) for v in row) for row in conn.execute(metrics)],
            }
    with psycopg.connect(case.dsn) as conn:
        return {
            "signals": [tuple(str(v) for v in row) for row in conn.execute(signals)],
            "metrics": [tuple(str(v) for v in row) for row in conn.execute(metrics)],
        }


def _sighting(metric: float, hour: int = 1, **overrides) -> TrendSignal:
    fields = dict(
        platform=PlatformType.YOUTUBE,
        raw_title="One video",
        metric_value=metric,
        growth_velocity=1.0,
        source_url=YT_URL,
        geo_code=GeoCode.VN,
        captured_at=NOW + timedelta(hours=hour),
        metadata={"video_id": YT_ID},
    )
    fields.update(overrides)
    return TrendSignal(**fields)


async def test_two_sightings_of_one_source_write_one_source_and_two_observations(repository_case):
    repository = repository_case.repository

    assert await repository.save_signals([_sighting(100.0, hour=1)]) == 1
    assert await repository.save_signals([_sighting(200.0, hour=2)]) == 1

    counts = repository_case.counts()
    assert counts["sources"] == 1
    assert counts["observations"] == 2


async def test_the_legacy_tables_are_not_written_at_all(repository_case):
    repository = repository_case.repository
    before = _legacy_state(repository_case)

    await repository.save_signals([_sighting(100.0, hour=1)])
    await repository.save_signals([_sighting(200.0, hour=2)])

    assert _legacy_state(repository_case) == before == {"signals": [], "metrics": []}


async def test_a_legacy_row_for_the_same_source_is_left_untouched(repository_case):
    """The old writer would have found this row and updated it in place.

    Seeding it first is what separates "writes nothing new" from "writes nothing at all": an
    UPDATE leaves the row count unchanged, so only comparing payloads catches it.
    """
    statement = (
        "INSERT INTO trend_signals (platform, raw_title, metric_value, growth_velocity,"
        " source_url, geo_code, metadata, captured_at)"
        " VALUES ('youtube', 'One video', 1.0, 0.5, ?, 'VN', ?, ?)"
    )
    params = (YT_URL, '{"video_id": "' + YT_ID + '"}', NOW.isoformat())
    if repository_case.name == "sqlite":
        with sqlite3.connect(repository_case.repository._db_path) as conn:
            conn.execute(statement, params)
    else:
        with psycopg.connect(repository_case.dsn, autocommit=True) as conn:
            conn.execute(statement.replace("?", "%s"), (YT_URL, params[1], NOW))

    before = _legacy_state(repository_case)
    assert len(before["signals"]) == 1

    await repository_case.repository.save_signals([_sighting(999.0, hour=3)])

    after = _legacy_state(repository_case)
    assert after == before, "the legacy row must keep its own metric, title and clock"
    assert repository_case.counts()["observations"] == 1, "the sighting is recorded, once"


async def test_a_mission_still_gets_its_evidence(repository_case):
    repository = repository_case.repository
    mission = ResearchMission(
        title="Evidence after the cutover",
        keywords=["k"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)

    signal = _sighting(100.0)
    signal.mission_id = mission.id
    await repository.save_signals([signal])

    evidence = await repository.get_mission_signals(mission.id)
    assert len(evidence) == 1
    assert evidence[0].metric_value == 100.0
    assert repository_case.counts()["mission_evidence"] == 1
    assert _legacy_state(repository_case) == {"signals": [], "metrics": []}


async def test_a_cluster_assignment_still_reaches_the_observation(repository_case):
    repository = repository_case.repository
    signal = _sighting(100.0, captured_at=datetime.now(timezone.utc))
    cluster = TopicCluster(canonical_name="after the cutover", signals=[signal])

    await repository.save_clusters([cluster])
    await repository.save_signals([signal])

    assert repository_case.counts()["clustered_observations"] == 1
    clusters = await repository.get_top_clusters(timeframe=Timeframe.LAST_24H)
    assert [str(c.id) for c in clusters] == [str(cluster.id)]
    assert _legacy_state(repository_case) == {"signals": [], "metrics": []}


async def test_the_return_value_is_still_the_observations_recorded(repository_case):
    repository = repository_case.repository

    written = await repository.save_signals(
        [
            _sighting(100.0, hour=1),
            _sighting(200.0, hour=2),
            _sighting(
                300.0,
                hour=3,
                platform=PlatformType.THREADS,
                source_url="https://www.threads.net/@a/post/P1",
                metadata={"post_id": "P1"},
            ),
        ]
    )

    assert written == 3
    assert repository_case.counts() == {
        "sources": 2,
        "observations": 3,
        "mission_evidence": 0,
        "clustered_observations": 0,
    }


async def test_a_sighting_that_identifies_nothing_is_still_refused_quietly(repository_case):
    """Unchanged by this commit, asserted here because the legacy INSERT used to accept it."""
    written = await repository_case.repository.save_signals(
        [_sighting(100.0, source_url=None, metadata={})]
    )

    assert written == 0
    assert repository_case.counts()["observations"] == 0
    assert _legacy_state(repository_case) == {"signals": [], "metrics": []}


async def test_the_legacy_tables_are_still_there_to_be_read(repository_case):
    """Not dropped: the audit, the backfill and the migration record all read them."""
    for table in ("trend_signals", "signal_metrics"):
        row = repository_case.query_one(
            f"SELECT count(*) FROM {table}", f"SELECT count(*) FROM {table}"
        )
        assert row is not None and row[0] == 0
    assert uuid.UUID(repository_case.insert_source("youtube", f"video:{YT_ID}"))
