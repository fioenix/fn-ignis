"""The benchmark has to build and measure the same thing on both backends.

A number from SQLite and a number from PostgreSQL are only comparable if the corpus behind them
is the same corpus and the record describing them has the same shape. SQLite restates its schema
in `_ensure_schema` while PostgreSQL reads `sql/`, so "the seeder works" is a claim that has to be
made twice.

A reduced shape, deliberately: this is the fast suite's parity check, not the benchmark. The
benchmark's own corpus floor is pinned in tests/unit/test_t021_read_path_benchmark.py, and the
measurement itself runs from scripts/t021_read_path_benchmark.py.
"""

import pytest

from ignis.domain.entities import TopicCluster
from scripts import t021_read_path_benchmark as benchmark

# Small enough to run in the suite, large enough that every relationship the seeder builds is
# exercised: several clusters, several sources each, several observations per source.
PARITY_SHAPE = benchmark.CorpusShape(
    clusters=4, sources_per_cluster=3, observations_per_source=3
)


@pytest.mark.asyncio
async def test_the_seeder_builds_the_same_corpus_on_both_backends(repository_case):
    corpus = await benchmark.build_corpus(repository_case.repository, PARITY_SHAPE)

    assert corpus == {"observations": 36, "sources": 12, "clusters": 4}
    counts = repository_case.counts()
    assert counts["observations"] == PARITY_SHAPE.observations, (
        f"{repository_case.name} stored {counts['observations']} of"
        f" {PARITY_SHAPE.observations} seeded observations"
    )
    assert counts["sources"] == PARITY_SHAPE.sources, (
        "the seeded signals did not resolve to one canonical source each, so the corpus the"
        " benchmark measures is not the corpus it reports"
    )
    assert counts["clustered_observations"] == PARITY_SHAPE.observations, (
        "an observation with no cluster is invisible to get_top_clusters"
    )


@pytest.mark.asyncio
async def test_the_measured_read_path_returns_the_same_shape_on_both_backends(repository_case):
    """Same corpus, same query, same result shape -- or the two numbers are not comparable."""
    await benchmark.build_corpus(repository_case.repository, PARITY_SHAPE)

    samples, result = await benchmark.measure(
        repository_case.repository, warmup=1, iterations=3
    )

    assert len(samples) == 3
    assert all(sample > 0 for sample in samples)
    # Every seeded cluster fits under the production limit of 10, and the reader keeps the latest
    # observation per source, so one signal per source comes back.
    assert result == {
        "clusters_returned": PARITY_SHAPE.clusters,
        "signals_in_result": PARITY_SHAPE.sources,
    }


@pytest.mark.asyncio
async def test_the_record_shape_is_identical_whichever_backend_produced_it(repository_case):
    """Only the backend name may differ. A field present on one side and missing on the other
    would let a release read a PostgreSQL claim off a SQLite record."""
    await benchmark.build_corpus(repository_case.repository, PARITY_SHAPE)
    samples, result = await benchmark.measure(
        repository_case.repository, warmup=1, iterations=3
    )

    record = benchmark.summarize(
        backend=repository_case.name,
        samples_ms=samples,
        corpus={"observations": 36, "sources": 12, "clusters": 4},
        result=result,
    )
    reference = benchmark.summarize(
        backend="reference",
        samples_ms=[1.0, 2.0, 3.0],
        corpus={"observations": 36, "sources": 12, "clusters": 4},
        result=result,
    )

    assert sorted(record) == sorted(reference)
    assert sorted(record["percentile"]) == sorted(reference["percentile"])
    assert record["query"] == reference["query"]
    assert record["threshold_p95_ms"] == benchmark.THRESHOLD_P95_MS
    assert record["backend"] == repository_case.name


@pytest.mark.asyncio
async def test_the_seeded_clusters_are_ranked_by_the_production_scorer(repository_case):
    """The benchmark must time a query that does real ranking work, not an empty scan."""
    await benchmark.build_corpus(repository_case.repository, PARITY_SHAPE)

    clusters = await repository_case.repository.get_top_clusters(
        geo=benchmark.QUERY_GEO,
        timeframe=benchmark.QUERY_TIMEFRAME,
        limit=benchmark.QUERY_LIMIT,
    )

    assert len(clusters) == PARITY_SHAPE.clusters
    assert all(isinstance(cluster, TopicCluster) for cluster in clusters)
    scores = [cluster.cross_platform_score for cluster in clusters]
    assert scores == sorted(scores, reverse=True), "the reader returned an unranked result"
    assert all(score > 0 for score in scores), (
        "every cluster scored zero, so the seeded metrics never reached the scorer"
    )
