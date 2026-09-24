#!/usr/bin/env python
"""Measure the production `get_top_clusters` read path against SC-001, on either backend.

SC-001 asks for P95 under 50 ms over a corpus of 10,000+ signals, and until now nothing had ever
measured it. A success criterion with no measurement behind it is a claim, so this seeds a corpus
through the repository's own writer, times the port method production calls, and publishes what it
found -- including when what it found is a failure.

What makes the number trustworthy is what it refuses to do:

- The corpus is written through `save_clusters` and `save_signals`, not with raw INSERTs. A
  hand-seeded table can miss a constraint, an index or a column default, and the query would then
  be measured against a schema no deployment has.
- The timed call is `ITrendRepository.get_top_clusters`, the same method the MCP tools and the
  discovery use case call. Timing an equivalent query written here would measure a different
  system that happens to return similar rows.
- The corpus shape is fixed in this module and checked before anything is timed. Shrinking the
  corpus is the cheapest way to pass, so no run can choose its own size.
- `--enforce` turns the threshold into an exit code. Without it the run still reports
  `passed: false` on a violation; there is no mode in which an over-threshold result reads as a
  pass.

The PostgreSQL run needs IGNIS_TEST_POSTGRES_DSN, and uses it only to create, migrate and drop its
own `ignis_benchmark_<uuid>` database. No configured database is ever read or written, and no DSN
is printed. The SQLite run builds its database inside a temporary directory and removes it.

Corpus shape, and why this one. The 2026-09-10 migration baseline measured the real corpus at
18,597 observations over 1,924 canonical sources -- about 9.7 sightings per source. The default
shape here holds that ratio at 10 and lands exactly on the floor SC-001 names: 200 clusters x 5
sources x 10 observations = 10,000 observations, all inside the 24-hour window and all
`exact_ingestion`, because an observation outside the window or with a legacy clock is filtered
out before the query does any work and would make the corpus smaller than it looks.

Usage:
    .venv/bin/python scripts/t021_read_path_benchmark.py --backend sqlite --enforce
    .venv/bin/python scripts/t021_read_path_benchmark.py --backend postgres --enforce
    .venv/bin/python scripts/t021_read_path_benchmark.py --backend sqlite \
        --json-out .handoff/t021-sqlite.json

Exit codes: 0 measured (and within threshold, or --enforce was not given), 1 the threshold was
exceeded under --enforce, 2 the benchmark could not run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from ignis.domain.entities import TopicCluster, TrendSignal  # noqa: E402
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe  # noqa: E402

SQL_DIR = REPO / "sql"

# ---------------------------------------------------------------------------
# The contract, stated once. tests/unit/test_t021_read_path_benchmark.py pins every one of these
# against SC-001, so none of them can be relaxed to make a run pass.
# ---------------------------------------------------------------------------

# SC-001: "get_top_clusters over 10,000+ sample signals reaches P95 latency < 50ms".
THRESHOLD_P95_MS = 50.0
REQUIRED_OBSERVATIONS = 10_000

# The query as production calls it. The defaults of the port method, written out rather than
# omitted, so the record says which query the number describes.
QUERY_GEO = GeoCode.VN
QUERY_TIMEFRAME = Timeframe.LAST_24H
QUERY_LIMIT = 10

# Measurement protocol.
#
# Warm-up exists because the first call pays for things a steady-state reader does not: SQLite
# opening the file and parsing the schema, psycopg opening a pooled connection and Postgres
# planning the statement for the first time. Those costs are real but they are paid once per
# process, and a percentile over 50 samples that includes them describes neither state honestly.
# They are run and discarded.
WARMUP_CALLS = 5
MEASURED_ITERATIONS = 50

# Nearest rank, 1-indexed: P95 over 50 samples is the 48th smallest, ceil(0.95 * 50). Chosen over
# the interpolating definition because every value it can report is a duration that was actually
# measured -- an interpolated 47.55th sample is a number no call ever took.
PERCENTILE = 0.95

SCRATCH_PREFIX = "ignis_benchmark_"
SCRATCH_PATTERN = re.compile(rf"^{re.escape(SCRATCH_PREFIX)}[0-9a-f]{{32}}$")

# Every migration the repository's schema contract applies, in order. Mirrored from
# tests/integration/conftest.py, which tests/unit/test_t037_schema_rehearsal.py keeps in step.
SCHEMA_MIGRATIONS = (
    "001_initial_schema.sql",
    "002_platform_credentials.sql",
    "008_deduplicate_signal_metrics.sql",
    "015_split_published_at.sql",
    "016_source_observation_model.sql",
    "017_research_workspace.sql",
    "018_source_identity_aliases.sql",
    "019_observations_latest_per_source_index.sql",
)

# The platforms a sighting can come from, cycled so that a cluster spans several of them. The
# cross-platform score is computed from the distinct count, so a single-platform corpus would
# exercise a code path no deployment sees.
SEED_PLATFORMS = (
    PlatformType.GOOGLE_TRENDS,
    PlatformType.YOUTUBE,
    PlatformType.TIKTOK,
    PlatformType.THREADS,
    PlatformType.REELS,
)


class Unrunnable(RuntimeError):
    """The benchmark cannot run, which is missing evidence rather than a failing result."""


@dataclass(frozen=True)
class CorpusShape:
    """How many of each entity the seeded corpus holds."""

    clusters: int
    sources_per_cluster: int
    observations_per_source: int

    @property
    def sources(self) -> int:
        return self.clusters * self.sources_per_cluster

    @property
    def observations(self) -> int:
        return self.sources * self.observations_per_source


# Fixed, not a CLI argument. See the module docstring for where the ratio comes from.
DEFAULT_SHAPE = CorpusShape(clusters=200, sources_per_cluster=5, observations_per_source=10)


def check_shape(shape: CorpusShape) -> None:
    """Refuse a corpus smaller than the one the criterion is stated over."""
    if shape.observations < REQUIRED_OBSERVATIONS:
        raise Unrunnable(
            f"SC-001 is stated over {REQUIRED_OBSERVATIONS:,} observations and this shape holds"
            f" {shape.observations:,}. A benchmark on a smaller corpus measures something else."
        )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(samples: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile: the ceil(fraction * n)-th smallest sample, 1-indexed."""
    if not samples:
        raise Unrunnable("no samples were measured")
    ordered = sorted(samples)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def describe_result(clusters: Sequence[TopicCluster]) -> Dict[str, int]:
    """What the timed query actually returned.

    Without this the record cannot distinguish a fast reader from an empty one. A corpus that
    fell outside the window, or landed on the legacy clock, is filtered out before the query does
    any work -- and the benchmark would then publish the latency of scanning nothing while the
    corpus line still read 10,000 observations.
    """
    return {
        "clusters_returned": len(clusters),
        "signals_in_result": sum(len(cluster.signals) for cluster in clusters),
    }


def summarize(
    backend: str,
    samples_ms: Sequence[float],
    corpus: Dict[str, int],
    result: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """One record, carrying everything needed to judge or reproduce the number."""
    p95 = percentile(samples_ms, PERCENTILE)
    return {
        "backend": backend,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "median_ms": round(percentile(samples_ms, 0.50), 3),
        "p95_ms": round(p95, 3),
        "max_ms": round(max(samples_ms), 3),
        "min_ms": round(min(samples_ms), 3),
        "samples": len(samples_ms),
        "warmup_calls": WARMUP_CALLS,
        "measured_iterations": MEASURED_ITERATIONS,
        "percentile": {"fraction": PERCENTILE, "method": "nearest_rank", "rank": max(
            1, math.ceil(PERCENTILE * len(samples_ms))
        )},
        "threshold_p95_ms": THRESHOLD_P95_MS,
        "corpus": dict(corpus),
        "result": dict(result or {}),
        "query": {
            "geo": QUERY_GEO.value,
            "timeframe": QUERY_TIMEFRAME.value,
            "limit": QUERY_LIMIT,
        },
        "passed": p95 < THRESHOLD_P95_MS,
    }


def exit_code(record: Dict[str, Any], enforce: bool) -> int:
    """The threshold becomes an exit code only under --enforce; `passed` never softens."""
    if enforce and not record["passed"]:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Seeding, through the repository's own writer
# ---------------------------------------------------------------------------


def _seed_clusters(shape: CorpusShape, now: datetime) -> List[TopicCluster]:
    return [
        TopicCluster(
            canonical_name=f"benchmark cluster {index:05d}",
            category="benchmark",
            first_seen_at=now - timedelta(hours=23),
            last_updated_at=now,
        )
        for index in range(shape.clusters)
    ]


def _seed_signals(shape: CorpusShape, clusters: Sequence[TopicCluster], now: datetime):
    """Every observation inside the 24-hour window, on the exact-ingestion clock.

    Both conditions are filters in the query, so an observation that fails either is dropped
    before the reader does any work -- and a corpus seeded without them would be smaller than its
    row count says while still reporting 10,000 rows.
    """
    for cluster_index, cluster in enumerate(clusters):
        for source_index in range(shape.sources_per_cluster):
            ordinal = cluster_index * shape.sources_per_cluster + source_index
            platform = SEED_PLATFORMS[ordinal % len(SEED_PLATFORMS)]
            for observation_index in range(shape.observations_per_source):
                # Spread across the window deterministically, newest last, so that the
                # latest-per-source ranking has something to choose between.
                minutes_back = 23 * 60 - (observation_index * 97 + ordinal) % (23 * 60)
                yield TrendSignal(
                    platform=platform,
                    raw_title=f"benchmark observation {ordinal:06d}-{observation_index:02d}",
                    metric_value=float(1_000 + ordinal * 7 + observation_index),
                    growth_velocity=float((ordinal % 13) + observation_index * 0.5),
                    source_url=f"https://benchmark.invalid/{platform.value}/{ordinal:06d}",
                    geo_code=QUERY_GEO,
                    cluster_id=cluster.id,
                    captured_at=now - timedelta(minutes=minutes_back),
                    metadata={
                        # A real object identifier, so identity resolves by the metadata route
                        # rather than by the normalized-URL fallback. The route decides which
                        # namespace the source lands in, and a corpus resolved the other way
                        # would hold different rows.
                        "video_id": f"bench{ordinal:06d}"
                        if platform is PlatformType.YOUTUBE
                        else None,
                        "item_id": f"{9_000_000 + ordinal}"
                        if platform is PlatformType.TIKTOK
                        else None,
                        "post_id": f"{8_000_000 + ordinal}"
                        if platform is PlatformType.THREADS
                        else None,
                        "reel_id": f"{7_000_000 + ordinal}"
                        if platform is PlatformType.REELS
                        else None,
                        "keyword": f"benchmark keyword {ordinal:06d}"
                        if platform is PlatformType.GOOGLE_TRENDS
                        else None,
                        "ordinal": ordinal,
                    },
                )


SEED_BATCH = 500


async def build_corpus(repository, shape: CorpusShape = DEFAULT_SHAPE) -> Dict[str, int]:
    """Write the corpus through the repository, and report what it actually contains.

    The counts come back from the shape rather than from a query, because the caller needs them
    before anything is timed; the read-path assertion that the corpus is visible at all is in the
    contract test, which drives this same function.
    """
    now = datetime.now(timezone.utc)
    clusters = _seed_clusters(shape, now)
    await repository.save_clusters(clusters)

    batch: List[TrendSignal] = []
    for signal in _seed_signals(shape, clusters, now):
        # None-valued metadata keys would be written verbatim and the resolver skips them, but
        # they are noise in every stored payload. Dropped here rather than branched above.
        signal.metadata = {k: v for k, v in signal.metadata.items() if v is not None}
        batch.append(signal)
        if len(batch) >= SEED_BATCH:
            await repository.save_signals(batch)
            batch = []
    if batch:
        await repository.save_signals(batch)

    return {
        "observations": shape.observations,
        "sources": shape.sources,
        "clusters": shape.clusters,
    }


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------


async def measure(
    repository, warmup: int = WARMUP_CALLS, iterations: int = MEASURED_ITERATIONS
) -> List[float]:
    """Time `get_top_clusters` in milliseconds, and describe what the last call returned.

    perf_counter_ns is monotonic and the highest resolution the interpreter offers, so a clock
    adjustment during the run cannot produce a negative or impossibly small sample. The warm-up
    calls are run and discarded; only the measured ones become samples.
    """
    last: List[TopicCluster] = []
    for _ in range(warmup):
        await repository.get_top_clusters(
            geo=QUERY_GEO, timeframe=QUERY_TIMEFRAME, limit=QUERY_LIMIT
        )

    samples: List[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        clusters = await repository.get_top_clusters(
            geo=QUERY_GEO, timeframe=QUERY_TIMEFRAME, limit=QUERY_LIMIT
        )
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
        last = clusters
    return samples, describe_result(last)


# ---------------------------------------------------------------------------
# Backends. Each builds a database nothing else owns, and removes it.
# ---------------------------------------------------------------------------


def scratch_database_name() -> str:
    return SCRATCH_PREFIX + uuid.uuid4().hex


def is_scratch_name(database: str) -> bool:
    return SCRATCH_PATTERN.fullmatch(database or "") is not None


def guard_scratch_name(database: str) -> str:
    """The single place a database name is allowed through to CREATE or DROP."""
    if not is_scratch_name(database):
        raise Unrunnable(f"{database!r} is not a scratch database name; refusing to touch it.")
    return database


async def run_sqlite(shape: CorpusShape) -> Dict[str, Any]:
    """A SQLite database inside a temporary directory, removed whatever happens."""
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX))
    try:
        repository = SqliteTrendRepository(str(scratch / "benchmark.sqlite"))
        try:
            corpus = await build_corpus(repository, shape)
            samples, result = await measure(repository)
        finally:
            await repository.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return summarize("sqlite", samples, corpus, result)


def _postgres_admin_dsn() -> str:
    dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        raise Unrunnable(
            "IGNIS_TEST_POSTGRES_DSN is not set, so the PostgreSQL benchmark cannot run. That is"
            " missing evidence, not a passing result, and there is no fallback: a configured"
            " database would be seeded with 10,000 synthetic observations."
        )
    return dsn


def _scratch_dsn(admin_dsn: str, database: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    parts = conninfo_to_dict(admin_dsn)
    parts["dbname"] = guard_scratch_name(database)
    return make_conninfo(**parts)


async def run_postgres(shape: CorpusShape) -> Dict[str, Any]:
    """A database this process created, migrated, measured and dropped."""
    import psycopg
    from psycopg import sql

    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

    admin_dsn = _postgres_admin_dsn()
    database = scratch_database_name()
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(guard_scratch_name(database))))
    try:
        dsn = _scratch_dsn(admin_dsn, database)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
            for migration in SCHEMA_MIGRATIONS:
                conn.execute((SQL_DIR / migration).read_text(encoding="utf-8"))

        repository = PostgresTimescaleRepository(dsn=dsn, min_pool_size=1, max_pool_size=4)
        try:
            corpus = await build_corpus(repository, shape)
            samples, result = await measure(repository)
        finally:
            await repository.close()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(guard_scratch_name(database))
                )
            )
    return summarize("postgres", samples, corpus, result)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def render(record: Dict[str, Any]) -> str:
    corpus = record["corpus"]
    verdict = "PASS" if record["passed"] else "FAIL"
    return "\n".join(
        (
            f"backend               {record['backend']}",
            f"corpus                {corpus['observations']:,} observations,"
            f" {corpus['sources']:,} sources, {corpus['clusters']:,} clusters",
            f"query                 get_top_clusters(geo={record['query']['geo']},"
            f" timeframe={record['query']['timeframe']}, limit={record['query']['limit']})",
            f"returned              {record['result'].get('clusters_returned', 0)} clusters,"
            f" {record['result'].get('signals_in_result', 0)} signals",
            f"protocol              {record['warmup_calls']} warm-up calls discarded,"
            f" {record['samples']} measured",
            f"percentile            nearest rank, fraction {record['percentile']['fraction']},"
            f" rank {record['percentile']['rank']} of {record['samples']}",
            f"median                {record['median_ms']:.3f} ms",
            f"p95                   {record['p95_ms']:.3f} ms",
            f"max                   {record['max_ms']:.3f} ms",
            f"min                   {record['min_ms']:.3f} ms",
            f"threshold             p95 < {record['threshold_p95_ms']:.1f} ms",
            f"verdict               {verdict}",
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--backend", choices=("sqlite", "postgres"), default="sqlite")
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="exit 1 when the measured P95 is not below the threshold",
    )
    parser.add_argument("--json-out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        check_shape(DEFAULT_SHAPE)
        runner = run_sqlite if args.backend == "sqlite" else run_postgres
        record = asyncio.run(runner(DEFAULT_SHAPE))
    except Unrunnable as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 2

    print(render(record))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"\nrecord written to {args.json_out}")
    return exit_code(record, args.enforce)


if __name__ == "__main__":
    raise SystemExit(main())
