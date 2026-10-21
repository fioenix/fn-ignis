"""T031: count the author identity a store already holds, read-only, showing no value (SC-006).

The seeded store holds rows as they were written before Spec 015: author fields at any depth,
handle links, a handle-derived source key and @mentions in titles. The inventory must count them
per table and field, print no identity value, and leave the file byte-for-byte unchanged.
"""

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

from tests.fixtures.author_identity_sentinels import (
    MENTION_TEXT,
    SENTINEL_TIKTOK_COMMENTER,
    THREADS_HANDLE_URL,
    TIKTOK_HANDLE_URL,
    mention_sentinels,
    threads_metadata,
    tiktok_metadata,
    undeclared_sentinels,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "inventory_author_identity.py"
NOW = "2026-10-01T00:00:00+00:00"


def _seed(path: Path) -> None:
    repository = SqliteTrendRepository(str(path))
    asyncio.run(repository._ensure_schema())
    asyncio.run(repository.close())
    conn = sqlite3.connect(path)
    sources = [str(uuid.uuid4()) for _ in range(3)]
    conn.executemany(
        "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
        [
            (sources[0], "tiktok", "video:7694797676306615583"),
            (sources[1], "threads", "url:https://threads.net/@sentinel.threads.author"),
            (sources[2], "youtube", "video:abc123"),
        ],
    )
    rows = [
        (sources[0], "Review áo khoác", TIKTOK_HANDLE_URL, tiktok_metadata()),
        (sources[1], MENTION_TEXT, THREADS_HANDLE_URL, threads_metadata()),
        (sources[2], "Đánh giá áo khoác", "https://www.youtube.com/watch?v=abc123", {"video_id": "abc123", "views": 3}),
    ]
    conn.executemany(
        "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
        " observed_title, metric_value, growth_velocity, geo_code, source_url, metadata)"
        " VALUES (?, ?, ?, 'exact_ingestion', 'metadata_external_id', ?, 0, 0, 'VN', ?, ?)",
        [(str(uuid.uuid4()), source, NOW, title, url, json.dumps(meta, ensure_ascii=False)) for source, title, url, meta in rows],
    )
    conn.execute(
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity, source_url,"
        " geo_code, metadata, captured_at) VALUES (?, 'tiktok', ?, 0, 0, ?, 'VN', ?, ?)",
        (str(uuid.uuid4()), MENTION_TEXT, TIKTOK_HANDLE_URL,
         json.dumps({"comments": [{"author": SENTINEL_TIKTOK_COMMENTER, "text": "x"}]}), NOW),
    )
    conn.commit()
    conn.close()


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


@pytest.fixture
def seeded(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    _seed(path)
    return path


def test_the_inventory_counts_identity_per_table_and_field(seeded):
    result = _run("--sqlite", str(seeded))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    observations = report["tables"]["observations"]
    assert report["store"] == "sqlite" and report["read_only"] is True
    assert observations["rows"] == 3
    assert observations["fields"]["metadata"]["rows_with_author_identity"] == 2
    assert observations["fields"]["metadata"]["by_key"]["username"] == 1
    assert observations["fields"]["metadata"]["by_key"]["author"] == 1
    assert observations["fields"]["source_url"]["handle_links"] == 2
    assert observations["fields"]["observed_title"]["mentions"] == 1
    assert report["tables"]["sources"]["fields"]["external_id"]["handle_keys"] == 1
    legacy = report["tables"]["trend_signals"]["fields"]
    assert (legacy["metadata"]["rows_with_author_identity"], legacy["source_url"]["handle_links"], legacy["raw_title"]["mentions"]) == (1, 1, 1)


def test_the_inventory_shows_no_identity_value(seeded):
    result = _run("--sqlite", str(seeded))

    output = result.stdout + result.stderr
    assert [value for value in undeclared_sentinels() + mention_sentinels() if value in output] == []


def test_the_store_is_unchanged_after_the_run(seeded):
    before = hashlib.sha256(seeded.read_bytes()).hexdigest()
    siblings = sorted(p.name for p in seeded.parent.iterdir())

    assert _run("--sqlite", str(seeded)).returncode == 0

    assert hashlib.sha256(seeded.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in seeded.parent.iterdir()) == siblings


def test_a_missing_store_is_refused_without_creating_one(tmp_path):
    missing = tmp_path / "absent.sqlite3"

    result = _run("--sqlite", str(missing))

    assert result.returncode != 0 and not missing.exists()


def test_a_dsn_is_named_by_its_variable_and_never_printed(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "IGNIS_INVENTORY_TEST_DSN"],
        capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin",
             "IGNIS_INVENTORY_TEST_DSN": "postgresql://inventory:not-a-real-secret@127.0.0.1:1/none"},
    )

    assert result.returncode != 0
    assert "not-a-real-secret" not in result.stdout + result.stderr
    assert "IGNIS_INVENTORY_TEST_DSN" in result.stderr
