"""A benchmark is evidence, so the thing producing it has to be unable to flatter the result.

The number this publishes only means something if three things are true, and none of them is
visible in the number itself: it has to time the repository method production calls rather than a
hand-written query standing in for it, it has to run against a corpus at least as large as the one
SC-001 names, and it has to fail when the threshold is exceeded. Each is asserted here, in the
fast suite, because the benchmark itself is far too slow to be one of these tests.
"""

import asyncio
from pathlib import Path

import pytest

from ignis.domain.entities import TopicCluster
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from scripts import t021_read_path_benchmark as benchmark


# --- the contract the number is measured against ----------------------------------------------


def test_the_threshold_and_corpus_floor_are_the_ones_the_success_criterion_names():
    """SC-001: get_top_clusters over 10,000+ signals at P95 under 50 ms."""
    assert benchmark.THRESHOLD_P95_MS == 50.0
    assert benchmark.REQUIRED_OBSERVATIONS == 10_000


def test_the_default_corpus_shape_meets_the_floor_it_is_measured_against():
    """The shape is fixed in the module, not passed in, so no run can quietly shrink it."""
    shape = benchmark.DEFAULT_SHAPE
    assert shape.observations == shape.clusters * shape.sources_per_cluster * (
        shape.observations_per_source
    )
    assert shape.observations >= benchmark.REQUIRED_OBSERVATIONS


def test_a_shape_below_the_floor_is_refused_rather_than_measured():
    """Reducing the corpus is the cheapest way to pass, so it is the one that has to be blocked."""
    small = benchmark.CorpusShape(clusters=2, sources_per_cluster=2, observations_per_source=2)
    with pytest.raises(benchmark.Unrunnable):
        benchmark.check_shape(small)


# --- the measurement protocol -----------------------------------------------------------------


def test_the_percentile_is_the_documented_nearest_rank_one():
    """Nearest rank, 1-indexed: P95 of 50 samples is the 48th smallest, ceil(0.95 * 50).

    Written against a sample set whose members are distinguishable, because the interpolating
    definition numpy uses would return 47.55 here and quietly report a value nobody measured.
    """
    samples = [float(n) for n in range(1, 51)]
    assert benchmark.percentile(samples, 0.95) == 48.0
    assert benchmark.percentile(samples, 0.50) == 25.0
    assert benchmark.percentile([7.0], 0.95) == 7.0


def test_the_summary_reports_every_field_the_contract_asks_for():
    record = benchmark.summarize(
        backend="sqlite",
        samples_ms=[float(n) for n in range(1, 51)],
        corpus={"observations": 10_000, "sources": 1_000, "clusters": 200},
    )
    for field in (
        "backend",
        "median_ms",
        "p95_ms",
        "max_ms",
        "min_ms",
        "samples",
        "warmup_calls",
        "measured_iterations",
        "percentile",
        "threshold_p95_ms",
        "corpus",
        "result",
        "query",
        "passed",
    ):
        assert field in record, f"the benchmark record says nothing about {field}"
    assert record["samples"] == 50
    assert record["measured_iterations"] == benchmark.MEASURED_ITERATIONS
    assert record["warmup_calls"] == benchmark.WARMUP_CALLS
    assert record["query"] == {
        "geo": benchmark.QUERY_GEO.value,
        "timeframe": benchmark.QUERY_TIMEFRAME.value,
        "limit": benchmark.QUERY_LIMIT,
    }


# --- the gate ---------------------------------------------------------------------------------


def test_a_p95_over_the_threshold_does_not_pass():
    """The whole point. A run that reports a number and exits 0 regardless measures nothing."""
    over = benchmark.summarize(
        backend="sqlite",
        samples_ms=[80.0] * 50,
        corpus={"observations": 10_000, "sources": 1_000, "clusters": 200},
    )
    assert over["p95_ms"] == 80.0
    assert over["passed"] is False
    assert benchmark.exit_code(over, enforce=True) == 1


def test_a_p95_under_the_threshold_passes():
    under = benchmark.summarize(
        backend="sqlite",
        samples_ms=[4.0] * 50,
        corpus={"observations": 10_000, "sources": 1_000, "clusters": 200},
    )
    assert under["passed"] is True
    assert benchmark.exit_code(under, enforce=True) == 0


def test_without_enforce_a_violation_still_reports_itself_as_failed():
    """Not enforcing is allowed to keep the exit code at 0; it is not allowed to claim a pass."""
    over = benchmark.summarize(
        backend="sqlite",
        samples_ms=[80.0] * 50,
        corpus={"observations": 10_000, "sources": 1_000, "clusters": 200},
    )
    assert benchmark.exit_code(over, enforce=False) == 0
    assert over["passed"] is False


# --- what is actually being timed ---------------------------------------------------------------


def test_the_timed_call_is_the_repository_method_production_uses(tmp_path):
    """Timing a hand-written query instead of the port method would measure a different system.

    Driven through a real SqliteTrendRepository, subclassed only to count: the call has to reach
    the production implementation and come back with the production return type.
    """
    calls = []

    class CountingRepository(SqliteTrendRepository):
        async def get_top_clusters(self, geo=None, timeframe=None, limit=10):
            calls.append((geo, timeframe, limit))
            return await super().get_top_clusters(geo=geo, timeframe=timeframe, limit=limit)

    async def drive():
        repository = CountingRepository(str(tmp_path / "wiring.sqlite"))
        try:
            shape = benchmark.CorpusShape(
                clusters=2, sources_per_cluster=2, observations_per_source=2
            )
            corpus = await benchmark.build_corpus(repository, shape)
            samples, result = await benchmark.measure(repository, warmup=1, iterations=3)
            clusters = await repository.get_top_clusters(
                geo=benchmark.QUERY_GEO,
                timeframe=benchmark.QUERY_TIMEFRAME,
                limit=benchmark.QUERY_LIMIT,
            )
            return corpus, samples, result, clusters
        finally:
            await repository.close()

    corpus, samples, result, clusters = asyncio.run(drive())

    assert len(calls) == 1 + 3 + 1, "the benchmark did not call get_top_clusters once per iteration"
    assert {call[1] for call in calls} == {benchmark.QUERY_TIMEFRAME}
    assert {call[2] for call in calls} == {benchmark.QUERY_LIMIT}
    assert len(samples) == 3, "warm-up calls leaked into the measured samples"
    assert all(sample > 0 for sample in samples)
    assert corpus == {"observations": 8, "sources": 4, "clusters": 2}
    assert clusters and all(isinstance(c, TopicCluster) for c in clusters), (
        "the seeded corpus is invisible to the read path, so the benchmark would time an empty scan"
    )
    assert result["clusters_returned"] == len(clusters)
    assert result["signals_in_result"] == sum(len(c.signals) for c in clusters)


def test_the_corpus_is_seeded_through_the_repository_write_path(tmp_path):
    """Writing rows with raw SQL would bypass the schema and indexes the query actually meets."""
    saved = []

    class RecordingRepository(SqliteTrendRepository):
        async def save_signals(self, signals):
            saved.extend(signals)
            return await super().save_signals(signals)

    async def drive():
        repository = RecordingRepository(str(tmp_path / "seed.sqlite"))
        try:
            shape = benchmark.CorpusShape(
                clusters=2, sources_per_cluster=2, observations_per_source=2
            )
            return await benchmark.build_corpus(repository, shape)
        finally:
            await repository.close()

    corpus = asyncio.run(drive())

    assert len(saved) == corpus["observations"]
    assert all(signal.cluster_id is not None for signal in saved), (
        "an observation with no cluster is invisible to get_top_clusters"
    )


def test_two_builds_of_one_shape_produce_the_same_corpus(tmp_path):
    """Deterministic, or two runs are measuring two different databases."""

    async def drive(name):
        repository = SqliteTrendRepository(str(tmp_path / name))
        try:
            shape = benchmark.CorpusShape(
                clusters=3, sources_per_cluster=2, observations_per_source=2
            )
            await benchmark.build_corpus(repository, shape)
            clusters = await repository.get_top_clusters(
                geo=benchmark.QUERY_GEO,
                timeframe=benchmark.QUERY_TIMEFRAME,
                limit=benchmark.QUERY_LIMIT,
            )
            return [(c.canonical_name, round(c.cross_platform_score, 9)) for c in clusters]
        finally:
            await repository.close()

    assert asyncio.run(drive("a.sqlite")) == asyncio.run(drive("b.sqlite"))


# --- what the benchmark may never reach ---------------------------------------------------------


def test_the_postgres_run_never_falls_back_to_a_configured_database():
    """IGNIS_TEST_POSTGRES_DSN or nothing. A fallback would point the seeder at a real corpus."""
    source = Path(benchmark.__file__).read_text(encoding="utf-8")
    assert "IGNIS_TEST_POSTGRES_DSN" in source
    assert "DATABASE_URL" not in source


def test_the_postgres_run_only_ever_names_a_scratch_database():
    name = benchmark.scratch_database_name()
    assert name.startswith(benchmark.SCRATCH_PREFIX)
    assert benchmark.is_scratch_name(name)
    assert not benchmark.is_scratch_name("ignis")
    assert not benchmark.is_scratch_name("postgres")
    with pytest.raises(benchmark.Unrunnable):
        benchmark.guard_scratch_name("ignis_production")


def test_the_record_says_what_the_timed_query_returned(tmp_path):
    """A fast reader and an empty one produce the same latency. Only this tells them apart."""
    assert benchmark.describe_result([]) == {"clusters_returned": 0, "signals_in_result": 0}

    async def drive():
        repository = SqliteTrendRepository(str(tmp_path / "result.sqlite"))
        try:
            shape = benchmark.CorpusShape(
                clusters=4, sources_per_cluster=3, observations_per_source=2
            )
            await benchmark.build_corpus(repository, shape)
            _, result = await benchmark.measure(repository, warmup=0, iterations=1)
            return result
        finally:
            await repository.close()

    result = asyncio.run(drive())
    # Four clusters seeded, ten asked for, so every one comes back -- with one signal per source,
    # because the reader keeps the latest observation of each.
    assert result == {"clusters_returned": 4, "signals_in_result": 12}
