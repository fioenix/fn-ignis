"""Everything `get_top_clusters` answers today, pinned before the reader is made faster.

T021 measured the read path over 10,000 observations and found the P95 crossing its 50 ms gate.
Making it faster means rewriting the query and adding an index, and the only thing standing
between that and a silent change of meaning is a test that already knew every answer.

So this file is deliberately not about speed. It fixes the selection rule, the tie-break, the
window, the aggregates, the ranking, the truncation, and every provenance field that reaches the
caller -- on both backends, because SQLite restates its schema while PostgreSQL reads `sql/`, and
a reader optimised on one of them is a reader that now disagrees with the other.

Two behaviours recorded here are gaps rather than guarantees, and are marked as such: `geo` is
accepted and never filters, and clusters tied on both ranking keys come back in whatever order
the database produced them.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from ignis.domain.cross_platform_score import cross_platform_score
from ignis.domain.value_objects import GeoCode, Timeframe

pytestmark = pytest.mark.asyncio

NOW = datetime.now(timezone.utc)


def _stamp(case, moment):
    """SQLite stores timestamps as text; psycopg binds datetimes."""
    return moment.isoformat() if case.name == "sqlite" else moment


def _cluster(case, name, category="general", topic_label=None, summary=None):
    cluster_id = str(uuid.uuid4())
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute(
                "INSERT INTO topic_clusters (id, canonical_name, topic_label, summary_text,"
                " category, first_seen_at, last_updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    cluster_id,
                    name,
                    topic_label,
                    summary,
                    category,
                    "2026-09-01T00:00:00+00:00",
                    "2026-09-02T00:00:00+00:00",
                ),
            )
    else:
        with psycopg.connect(case.dsn, autocommit=True) as conn:
            conn.execute(
                "INSERT INTO topic_clusters (id, canonical_name, topic_label, summary_text,"
                " category, first_seen_at, last_updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    cluster_id,
                    name,
                    topic_label,
                    summary,
                    category,
                    datetime(2026, 9, 1, tzinfo=timezone.utc),
                    datetime(2026, 9, 2, tzinfo=timezone.utc),
                ),
            )
    return cluster_id


def _observe(
    case,
    cluster_id,
    source_id,
    *,
    hours_ago=1.0,
    metric=100.0,
    velocity=1.0,
    title="observed",
    provenance="exact_ingestion",
    identity_source="metadata_external_id",
    geo="VN",
    url="https://example.invalid/one",
    metadata="{}",
    published_hours_ago=None,
    observed_at="use_hours_ago",
):
    moment = NOW - timedelta(hours=hours_ago)
    published = None if published_hours_ago is None else _stamp(
        case, NOW - timedelta(hours=published_hours_ago)
    )
    return case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=_stamp(case, moment) if observed_at == "use_hours_ago" else observed_at,
        published_at=published,
        time_provenance=provenance,
        identity_source=identity_source,
        observed_title=title,
        metric_value=metric,
        growth_velocity=velocity,
        geo_code=geo,
        source_url=url,
        metadata=metadata,
    )


async def _top(case, **kwargs):
    params = {"geo": GeoCode.VN, "timeframe": Timeframe.LAST_24H, "limit": 10}
    params.update(kwargs)
    return await case.repository.get_top_clusters(**params)


# --- which observation represents a source -----------------------------------------------------


async def test_one_signal_per_source_and_it_is_the_latest_in_the_window(repository_case):
    """A source polled hourly must not outweigh one polled daily."""
    cluster = _cluster(repository_case, "latest per source")
    source = repository_case.insert_source("youtube", "video:one")
    _observe(repository_case, cluster, source, hours_ago=6, metric=10.0, title="oldest")
    _observe(repository_case, cluster, source, hours_ago=3, metric=20.0, title="middle")
    _observe(repository_case, cluster, source, hours_ago=1, metric=30.0, title="newest")

    clusters = await _top(repository_case)

    assert len(clusters) == 1
    assert [s.raw_title for s in clusters[0].signals] == ["newest"]
    assert [s.metric_value for s in clusters[0].signals] == [30.0]


async def test_a_source_in_two_clusters_keeps_a_signal_in_each(repository_case):
    """Partitioned on (cluster_id, source_id), not source_id: 175 corpus identities span two."""
    first = _cluster(repository_case, "cluster one")
    second = _cluster(repository_case, "cluster two")
    source = repository_case.insert_source("youtube", "video:shared")
    _observe(repository_case, first, source, hours_ago=5, metric=50.0, title="in one")
    _observe(repository_case, second, source, hours_ago=1, metric=60.0, title="in two")

    clusters = await _top(repository_case)

    by_name = {c.canonical_name: c for c in clusters}
    assert sorted(by_name) == ["cluster one", "cluster two"]
    assert [s.raw_title for s in by_name["cluster one"].signals] == ["in one"]
    assert [s.raw_title for s in by_name["cluster two"].signals] == ["in two"]


@pytest.mark.parametrize(
    ("metrics", "velocities", "expected_title"),
    (
        # Same instant: the larger metric wins.
        ((5.0, 9.0), (1.0, 1.0), "metric 9.0"),
        # Same instant and metric: the larger velocity wins.
        ((7.0, 7.0), (2.0, 8.0), "velocity 8.0"),
    ),
)
async def test_observations_at_one_instant_break_the_tie_by_metric_then_velocity(
    repository_case, metrics, velocities, expected_title
):
    """Latest clock, then larger metric, then larger velocity, then the row id."""
    cluster = _cluster(repository_case, "tie break")
    source = repository_case.insert_source("youtube", "video:tie")
    for metric, velocity in zip(metrics, velocities):
        title = f"metric {metric}" if metrics[0] != metrics[1] else f"velocity {velocity}"
        _observe(
            repository_case,
            cluster,
            source,
            hours_ago=2,
            metric=metric,
            velocity=velocity,
            title=title,
        )

    clusters = await _top(repository_case)

    assert [s.raw_title for s in clusters[0].signals] == [expected_title]


async def test_two_observations_identical_on_every_ranking_key_resolve_repeatably(
    repository_case,
):
    """Once clock, metric and velocity tie, the row id decides -- and it decides every time."""
    cluster = _cluster(repository_case, "fully tied")
    source = repository_case.insert_source("youtube", "video:fully-tied")
    for _ in range(2):
        _observe(repository_case, cluster, source, hours_ago=2, metric=4.0, velocity=4.0)

    first = await _top(repository_case)
    again = await _top(repository_case)

    assert len(first[0].signals) == 1
    assert first[0].signals[0].observation_id == again[0].signals[0].observation_id


# --- what the window admits --------------------------------------------------------------------


async def test_an_observation_older_than_the_timeframe_is_excluded(repository_case):
    cluster = _cluster(repository_case, "window")
    source = repository_case.insert_source("youtube", "video:window")
    _observe(repository_case, cluster, source, hours_ago=48, metric=90.0, title="two days old")

    assert await _top(repository_case, timeframe=Timeframe.LAST_24H) == []

    wider = await _top(repository_case, timeframe=Timeframe.LAST_7D)
    assert [s.raw_title for s in wider[0].signals] == ["two days old"]


@pytest.mark.parametrize("provenance", ("legacy_publish_only", "unknown"))
async def test_only_exact_ingestion_observations_are_read(repository_case, provenance):
    """17,118 corpus observations have no known collection time; the window cannot use them."""
    cluster = _cluster(repository_case, "provenance")
    source = repository_case.insert_source("youtube", "video:provenance")
    _observe(repository_case, cluster, source, hours_ago=1, provenance=provenance)

    assert await _top(repository_case) == []


async def test_an_observation_with_no_collection_time_is_excluded(repository_case):
    cluster = _cluster(repository_case, "no clock")
    source = repository_case.insert_source("youtube", "video:no-clock")
    _observe(
        repository_case,
        cluster,
        source,
        provenance="unknown",
        observed_at=None,
    )

    assert await _top(repository_case) == []


async def test_an_observation_in_no_cluster_is_excluded(repository_case):
    source = repository_case.insert_source("youtube", "video:unclustered")
    _observe(repository_case, None, source, hours_ago=1)

    assert await _top(repository_case) == []


async def test_geo_is_accepted_and_does_not_filter(repository_case):
    """Recorded as the gap it is. Neither reader has ever filtered on geo, and T021 is not the
    change that starts: adding a filter here would silently empty existing callers' results."""
    cluster = _cluster(repository_case, "geo ignored")
    source = repository_case.insert_source("youtube", "video:geo")
    _observe(repository_case, cluster, source, hours_ago=1, geo="VN")

    for geo in (GeoCode.VN, GeoCode.GLOBAL):
        clusters = await _top(repository_case, geo=geo)
        assert len(clusters) == 1, f"geo={geo} changed which clusters came back"
        assert clusters[0].signals[0].geo_code == GeoCode.VN


# --- the aggregates and the score --------------------------------------------------------------


async def test_the_score_is_the_shared_function_over_one_observation_per_source(repository_case):
    """Computed in Python from SQL aggregates, by the same function the clusterer uses.

    Asserted against `cross_platform_score` itself rather than against a literal, because the
    thing being pinned is that the reader has not grown its own copy of the arithmetic.
    """
    cluster = _cluster(repository_case, "scored")
    for index, (platform, metric, velocity) in enumerate(
        (("youtube", 1_000.0, 2.0), ("tiktok", 3_000.0, 6.0), ("threads", 5_000.0, 10.0))
    ):
        source = repository_case.insert_source(platform, f"video:scored-{index}")
        # An older sighting of each source, to prove the aggregate uses only the latest one.
        _observe(repository_case, cluster, source, hours_ago=8, metric=999_999.0, velocity=999.0)
        _observe(
            repository_case, cluster, source, hours_ago=1, metric=metric, velocity=velocity
        )

    clusters = await _top(repository_case)

    expected = cross_platform_score(
        distinct_platforms=3,
        total_metric=1_000.0 + 3_000.0 + 5_000.0,
        average_velocity=(2.0 + 6.0 + 10.0) / 3,
    )
    assert clusters[0].cross_platform_score == expected
    assert len(clusters[0].signals) == 3


async def test_clusters_are_ranked_by_score_then_by_signal_count(repository_case):
    """Two keys, in this order. A cluster with more sources only wins a tie on score."""
    # Three platforms and a large metric: the top band on every term.
    strong = _cluster(repository_case, "strong")
    for index, platform in enumerate(("youtube", "tiktok", "threads")):
        source = repository_case.insert_source(platform, f"video:strong-{index}")
        _observe(repository_case, strong, source, hours_ago=1, metric=10_000_000.0, velocity=50.0)

    # One platform and a tiny metric: near the bottom.
    weak = _cluster(repository_case, "weak")
    source = repository_case.insert_source("youtube", "video:weak")
    _observe(repository_case, weak, source, hours_ago=1, metric=1.0, velocity=0.0)

    clusters = await _top(repository_case)

    assert [c.canonical_name for c in clusters] == ["strong", "weak"]
    assert clusters[0].cross_platform_score > clusters[1].cross_platform_score


async def test_clusters_tied_on_score_are_ranked_by_the_number_of_signals(repository_case):
    """Same score, different source count: more sources comes first."""
    # Identical metric and velocity per source, so the score is identical; only the count differs
    # -- and the metric sum is the same because each source carries zero.
    few = _cluster(repository_case, "few sources")
    many = _cluster(repository_case, "many sources")
    for index in range(2):
        source = repository_case.insert_source("youtube", f"video:few-{index}")
        _observe(repository_case, few, source, hours_ago=1, metric=0.0, velocity=0.0)
    for index in range(4):
        source = repository_case.insert_source("youtube", f"video:many-{index}")
        _observe(repository_case, many, source, hours_ago=1, metric=0.0, velocity=0.0)

    clusters = await _top(repository_case)

    assert [c.cross_platform_score for c in clusters] == [0.0, 0.0]
    assert [c.canonical_name for c in clusters] == ["many sources", "few sources"]


# --- truncation --------------------------------------------------------------------------------


async def test_limit_truncates_after_ranking_and_keeps_the_strongest(repository_case):
    """The limit is applied to the ranked list, so it takes the top N rather than any N."""
    for index in range(5):
        cluster = _cluster(repository_case, f"cluster {index}")
        source = repository_case.insert_source("youtube", f"video:rank-{index}")
        _observe(
            repository_case,
            cluster,
            source,
            hours_ago=1,
            metric=float(10 ** (index + 1)),
            velocity=float(index),
        )

    every = await _top(repository_case, limit=10)
    top_two = await _top(repository_case, limit=2)

    assert len(every) == 5
    assert [c.canonical_name for c in top_two] == [c.canonical_name for c in every[:2]]
    assert [c.canonical_name for c in top_two] == ["cluster 4", "cluster 3"]


async def test_a_limit_beyond_the_corpus_returns_everything(repository_case):
    cluster = _cluster(repository_case, "only one")
    source = repository_case.insert_source("youtube", "video:only")
    _observe(repository_case, cluster, source, hours_ago=1)

    assert len(await _top(repository_case, limit=50)) == 1


async def test_an_empty_corpus_returns_an_empty_list(repository_case):
    assert await _top(repository_case) == []


# --- what reaches the caller -------------------------------------------------------------------


async def test_every_provenance_field_survives_the_read(repository_case):
    """The reader is the only place these come back, so an optimisation must not drop one."""
    cluster = _cluster(
        repository_case, "full payload", category="fashion", topic_label="a label"
    )
    source = repository_case.insert_source("tiktok", "video:payload")
    observation_id = _observe(
        repository_case,
        cluster,
        source,
        hours_ago=2,
        metric=123.5,
        velocity=4.5,
        title="the observed title",
        identity_source="url_external_id",
        url="https://tiktok.invalid/@a/video/1",
        metadata='{"item_id": "1", "note": "kept"}',
        published_hours_ago=30,
    )

    clusters = await _top(repository_case)
    signal = clusters[0].signals[0]

    assert clusters[0].category == "fashion"
    assert clusters[0].topic_label == "a label"
    assert clusters[0].first_seen_at is not None
    assert clusters[0].last_updated_at is not None
    assert str(signal.observation_id) == str(observation_id)
    assert signal.identity_source == "url_external_id"
    assert signal.time_provenance == "exact_ingestion"
    assert signal.platform.value == "tiktok"
    assert signal.raw_title == "the observed title"
    assert signal.metric_value == 123.5
    assert signal.growth_velocity == 4.5
    assert signal.source_url == "https://tiktok.invalid/@a/video/1"
    assert signal.geo_code == GeoCode.VN
    assert signal.metadata == {"item_id": "1", "note": "kept"}
    assert signal.captured_at is not None
    assert signal.published_at is not None
    assert str(clusters[0].id) == str(cluster)
    assert signal.cluster_id is not None and str(signal.cluster_id) == str(cluster)


async def test_a_cluster_with_no_stored_summary_gets_the_counted_fallback(repository_case):
    cluster = _cluster(repository_case, "no summary", summary=None)
    for index, platform in enumerate(("youtube", "tiktok")):
        source = repository_case.insert_source(platform, f"video:summary-{index}")
        _observe(repository_case, cluster, source, hours_ago=1)

    clusters = await _top(repository_case)

    assert clusters[0].summary_text == "2 sources across 2 platforms."


async def test_a_stored_summary_is_returned_unchanged(repository_case):
    cluster = _cluster(repository_case, "has summary", summary="the stored summary")
    source = repository_case.insert_source("youtube", "video:stored-summary")
    _observe(repository_case, cluster, source, hours_ago=1)

    clusters = await _top(repository_case)

    assert clusters[0].summary_text == "the stored summary"


# --- what the two-phase reader added, and what it must not have changed -----------------------


async def test_clusters_tied_on_both_ranking_keys_come_back_in_a_defined_order(repository_case):
    """The one behaviour T021's optimisation deliberately changed, pinned so it stays changed.

    Before the reader ranked clusters in order to read only the top ones, two clusters tied on
    score and on source count came back in whatever order the database produced. That order could
    differ between the two backends and between two runs of one of them, and once `limit`
    truncates the list it decides which cluster the caller never sees. `cluster_rank_key` makes
    the order total by falling back to the cluster id, so a tie resolves the same way everywhere.
    """
    ids = []
    for index in range(4):
        cluster = _cluster(repository_case, f"tied cluster {index}")
        ids.append(cluster)
        source = repository_case.insert_source("youtube", f"video:tied-{index}")
        _observe(repository_case, cluster, source, hours_ago=1, metric=0.0, velocity=0.0)

    clusters = await _top(repository_case)

    assert [c.cross_platform_score for c in clusters] == [0.0] * 4
    assert [len(c.signals) for c in clusters] == [1] * 4
    expected = sorted(ids, reverse=True)
    assert [str(c.id) for c in clusters] == expected, "a tie on both keys is not ordered by id"

    again = await _top(repository_case)
    assert [str(c.id) for c in again] == expected, "one corpus answered the same question twice"


async def test_a_truncated_tie_takes_the_same_clusters_every_time(repository_case):
    """The reason the tie-break matters: `limit` lands in the middle of the tied group."""
    for index in range(5):
        cluster = _cluster(repository_case, f"truncated {index}")
        source = repository_case.insert_source("youtube", f"video:truncated-{index}")
        _observe(repository_case, cluster, source, hours_ago=1, metric=0.0, velocity=0.0)

    first = await _top(repository_case, limit=2)
    again = await _top(repository_case, limit=2)
    everything = await _top(repository_case, limit=10)

    assert [str(c.id) for c in first] == [str(c.id) for c in again]
    assert [str(c.id) for c in first] == [str(c.id) for c in everything[:2]], (
        "the truncated read chose different clusters than the full ranking would have"
    )


async def test_the_ranked_clusters_carry_the_score_ranking_used(repository_case):
    """Ranking and payload are two statements now, so the score the caller sees has to be the
    one the ranking sorted on rather than a second computation over re-read rows."""
    cluster = _cluster(repository_case, "consistent score")
    for index, platform in enumerate(("youtube", "tiktok")):
        source = repository_case.insert_source(platform, f"video:consistent-{index}")
        _observe(
            repository_case, cluster, source, hours_ago=1, metric=5_000.0, velocity=3.0
        )

    clusters = await _top(repository_case)

    assert clusters[0].cross_platform_score == cross_platform_score(
        distinct_platforms=2, total_metric=10_000.0, average_velocity=3.0
    )
    assert len(clusters[0].signals) == 2


async def test_a_cluster_outside_the_limit_is_read_no_further_than_ranking(repository_case):
    """Only the ranked clusters may appear, and each must arrive with its full payload.

    A cluster dropped by `limit` must leave no trace, and one kept must not arrive half-read --
    the failure mode of splitting a query in two is a cluster whose ranking row survived while
    its payload row did not.
    """
    for index in range(6):
        cluster = _cluster(repository_case, f"partial {index}")
        for source_index in range(3):
            source = repository_case.insert_source(
                "youtube", f"video:partial-{index}-{source_index}"
            )
            _observe(
                repository_case,
                cluster,
                source,
                hours_ago=1,
                metric=float(10 ** (index + 1)),
                velocity=1.0,
            )

    clusters = await _top(repository_case, limit=3)

    assert [c.canonical_name for c in clusters] == ["partial 5", "partial 4", "partial 3"]
    assert all(len(c.signals) == 3 for c in clusters), "a ranked cluster arrived without payload"
    assert all(c.canonical_name and c.last_updated_at for c in clusters)
