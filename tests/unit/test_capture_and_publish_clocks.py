"""captured_at and published_at are two clocks and must never be collapsed back into one.

Before this split, three connector sites stamped the content's publish time into captured_at,
so a 30-day window meant "videos published in the last 30 days" for YouTube and "posts we
scraped in the last 30 days" for Threads. Timeframe queries run on captured_at, so that column
has to mean the same thing for every platform.
"""

import ast
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

CONNECTORS = Path(__file__).resolve().parents[2] / "src" / "ignis" / "infrastructure" / "connectors"

PULLED_AT = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
POSTED_AT = datetime(2026, 7, 1, 8, 30, tzinfo=timezone.utc)


def _signal(**kw) -> TrendSignal:
    base = dict(
        platform=PlatformType.YOUTUBE,
        raw_title="Khoa hoc AI cho nguoi moi bat dau",
        metric_value=120000.0,
        geo_code=GeoCode.VN,
        source_url="https://www.youtube.com/watch?v=abc123",
        captured_at=PULLED_AT,
        published_at=POSTED_AT,
    )
    base.update(kw)
    return TrendSignal(**base)


@pytest.mark.asyncio
async def test_sqlite_round_trip_keeps_both_times(tmp_path):
    """Both columns must survive a write and a read, independently."""
    repo = SqliteTrendRepository(db_path=str(tmp_path / "clocks.db"))
    cluster = TopicCluster(canonical_name="khoa hoc ai", signals=[_signal()])
    # The order the pipeline uses: the cluster is persisted first so the signals it labels can
    # reference it, then the signals are written. save_clusters used to write them itself, which
    # made it a second write path and stored one source twice.
    await repo.save_clusters([cluster])
    await repo.save_signals(cluster.signals)

    stored = await repo.get_cluster_signals(cluster.id)

    assert len(stored) == 1
    assert stored[0].captured_at == PULLED_AT
    assert stored[0].published_at == POSTED_AT


@pytest.mark.asyncio
async def test_a_platform_that_reports_no_publish_time_stores_null(tmp_path):
    """Google's keyword probes have no publish concept; the column stays empty, not guessed."""
    repo = SqliteTrendRepository(db_path=str(tmp_path / "nopub.db"))
    cluster = TopicCluster(
        canonical_name="google search trends",
        signals=[_signal(platform=PlatformType.GOOGLE_TRENDS, published_at=None)],
    )
    await repo.save_clusters([cluster])
    await repo.save_signals(cluster.signals)

    stored = await repo.get_cluster_signals(cluster.id)

    assert stored[0].captured_at == PULLED_AT
    assert stored[0].published_at is None


@pytest.mark.asyncio
async def test_a_database_written_before_the_split_gains_the_column(tmp_path):
    """A file created by an earlier version must be upgraded in place, not rejected."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE trend_signals (
                   id TEXT PRIMARY KEY, platform TEXT NOT NULL, raw_title TEXT NOT NULL,
                   metric_value REAL NOT NULL, growth_velocity REAL DEFAULT 0.0,
                   source_url TEXT, geo_code TEXT DEFAULT 'VN', cluster_id TEXT,
                   mission_id TEXT, metadata TEXT, captured_at TEXT NOT NULL)"""
        )
        conn.commit()
    finally:
        conn.close()

    repo = SqliteTrendRepository(db_path=db_path)
    await repo.get_domain_lexicons()  # any call forces the schema check

    conn = sqlite3.connect(db_path)
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(trend_signals)")}
    finally:
        conn.close()

    assert "published_at" in columns


def test_no_connector_stamps_a_publish_time_into_captured_at():
    """The regression guard: captured_at is the ingestion clock, everywhere, by construction.

    Three sites used to assign a parsed publish timestamp to captured_at. Reading the source is
    the only way to catch that returning, because both fields are datetimes and any test using a
    fixture would pass either way.
    """
    offenders = []
    for path in sorted(CONNECTORS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "captured_at":
                    continue
                value = kw.value
                if isinstance(value, ast.Call):
                    continue  # datetime.now(timezone.utc)
                if isinstance(value, ast.Name) and (
                    value.id.startswith("cap") or value.id.endswith("captured_at")
                ):
                    continue
                if isinstance(value, ast.Attribute) and value.attr == "captured_at":
                    continue
                offenders.append(
                    f"{path.relative_to(CONNECTORS).as_posix()}:{value.lineno}: "
                    f"captured_at={ast.unparse(value)}"
                )

    assert not offenders, (
        "captured_at must be the ingestion time. Pass a source timestamp as published_at "
        "instead:\n" + "\n".join(offenders)
    )
