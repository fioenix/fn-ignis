"""T039: anonymise author identity stored before Spec 015 (OG-3, FR-015).

The seeded store holds rows as they were written before the policy: author fields at any depth,
handle links, a handle-derived source key and @mentions. A dry run must list the targets without
writing; --apply must rewrite them through the collection policy in one transaction and read back
zero remaining targets. Rows that already comply, declared tokens included, must not change.
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

from ignis.application.author_policy import strip_stored_identity
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

from tests.fixtures.author_identity_sentinels import (
    MENTION_TEXT,
    SENTINEL_TIKTOK_COMMENTER,
    THREADS_HANDLE_URL,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
    threads_metadata,
    tiktok_metadata,
    undeclared_sentinels,
    youtube_metadata,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "anonymise_author_identity.py"
INVENTORY = ROOT / "scripts" / "inventory_author_identity.py"
NOW = "2026-10-01T00:00:00+00:00"
DECLARED_TITLE = "Áo của @[declared:0b5f6a1e-1111-4222-8333-944455556666] mặc mát không?"
CLEAN_METADATA = {"video_id": "abc123", "views": 3, "note": "giá @[user] hỏi"}


def _seed(path: Path) -> dict:
    repository = SqliteTrendRepository(str(path))
    asyncio.run(repository._ensure_schema())
    asyncio.run(repository.close())
    conn = sqlite3.connect(path)
    sources = [str(uuid.uuid4()) for _ in range(5)]
    conn.executemany(
        "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
        [
            (sources[0], "tiktok", f"video:{TIKTOK_ITEM_ID}"),
            (sources[1], "threads", "url:https://threads.net/@sentinel.threads.author"),
            (sources[2], "youtube", "video:sentinelYT1"),
            (sources[3], "youtube", "video:abc123"),
            (sources[4], "youtube", "video:list1"),
        ],
    )
    observations = [str(uuid.uuid4()) for _ in range(5)]
    rows = [
        (observations[0], sources[0], "Review áo khoác", TIKTOK_HANDLE_URL, json.dumps(tiktok_metadata(), ensure_ascii=False)),
        (observations[1], sources[1], MENTION_TEXT, THREADS_HANDLE_URL, json.dumps(threads_metadata(), ensure_ascii=False)),
        (observations[2], sources[2], "Đánh giá áo khoác", "https://www.youtube.com/watch?v=sentinelYT1",
         json.dumps(youtube_metadata(), ensure_ascii=False)),
        (observations[3], sources[3], DECLARED_TITLE, "https://www.youtube.com/watch?v=abc123",
         json.dumps(CLEAN_METADATA, ensure_ascii=False)),
        (observations[4], sources[4], "Danh sách", None, json.dumps(["not", "a", "mapping"])),
    ]
    conn.executemany(
        "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
        " observed_title, metric_value, growth_velocity, geo_code, source_url, metadata)"
        " VALUES (?, ?, ?, 'exact_ingestion', 'metadata_external_id', ?, 0, 0, 'VN', ?, ?)",
        [(oid, source, NOW, title, url, meta) for oid, source, title, url, meta in rows],
    )
    mission = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), mission, observations[2], NOW),
    )
    # Only the claim -> observation link is under test, not the qualification chain behind it.
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'mission_claim_evidence'"
    ).fetchall()
    for (name,) in triggers:
        conn.execute(f'DROP TRIGGER "{name}"')
    claim = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO mission_claim_evidence (id, claim_id, observation_id, role) VALUES (?, ?, ?, 'CONTEXT')",
        (str(uuid.uuid4()), claim, observations[2]),
    )
    conn.execute(
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity, source_url,"
        " geo_code, metadata, captured_at) VALUES (?, 'tiktok', ?, 0, 0, ?, 'VN', ?, ?)",
        (str(uuid.uuid4()), MENTION_TEXT, TIKTOK_HANDLE_URL,
         json.dumps({"comments": [{"author": SENTINEL_TIKTOK_COMMENTER, "text": "x"}]}), NOW),
    )
    conn.execute(
        "INSERT INTO topic_clusters (id, canonical_name, topic_label, summary_text, last_updated_at)"
        " VALUES (?, 'áo khoác', 'áo khoác', ?, ?)",
        (str(uuid.uuid4()), f"Nhiều người hỏi {MENTION_TEXT}", NOW),
    )
    conn.commit()
    conn.close()
    return {"observations": observations, "mission": mission, "claim": claim}


def _run(script: Path, *args):
    return subprocess.run(
        [sys.executable, str(script), *args], capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path, sql: str):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


@pytest.fixture
def seeded(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    return path, _seed(path)


def test_a_dry_run_lists_the_targets_and_writes_nothing(seeded):
    path, ids = seeded
    before = _digest(path)

    result = _run(SCRIPT, "--sqlite", str(path))

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["mode"] == "dry-run" and manifest["store"] == "sqlite"
    targets = manifest["targets"]
    assert sorted(targets["observations"]["ids"]) == sorted(ids["observations"][:3])
    assert targets["observations"]["fields"] == {"metadata": 3, "observed_title": 1, "source_url": 2}
    assert targets["trend_signals"]["fields"] == {"metadata": 1, "raw_title": 1, "source_url": 1}
    assert targets["topic_clusters"]["fields"] == {"summary_text": 1}
    assert manifest["missions"] == [ids["mission"]]
    assert manifest["bound_claims"] == 1
    assert manifest["source_keys_not_rewritten"] == 1
    assert [value for value in undeclared_sentinels() if value in result.stdout + result.stderr] == []
    assert _digest(path) == before, "A dry run must not write"


def test_apply_rewrites_the_targets_and_reads_back_none(seeded):
    path, ids = seeded

    result = _run(SCRIPT, "--sqlite", str(path), "--apply")

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "apply"
    assert report["readback"] == {"remaining_targets": 0, "rows_changed": 5}
    inventory = json.loads(_run(INVENTORY, "--sqlite", str(path)).stdout)["tables"]
    for table in ("observations", "trend_signals", "topic_clusters"):
        for field, counts in inventory[table]["fields"].items():
            assert not any(counts.get(name) for name in ("rows_with_author_identity", "handle_links", "mentions")), (
                f"{table}.{field} still holds identity: {counts}"
            )
    dump = "\n".join(str(row) for row in _rows(path, "SELECT observed_title, source_url, metadata FROM observations"))
    assert [value for value in undeclared_sentinels() if value in dump] == []
    urls = dict(_rows(path, "SELECT id, source_url FROM observations"))
    assert urls[ids["observations"][0]] == f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}"
    meta = json.loads(dict(_rows(path, "SELECT id, metadata FROM observations"))[ids["observations"][2]])
    assert meta["video_id"] == "sentinelYT1" and meta["views"] == 12000 and "channel_id" not in meta


def test_compliant_rows_and_the_source_key_are_left_alone(seeded):
    path, ids = seeded
    untouched = ids["observations"][3:]
    query = f"SELECT id, observed_title, source_url, metadata FROM observations WHERE id IN {tuple(untouched)}"
    before = sorted(_rows(path, query))

    assert _run(SCRIPT, "--sqlite", str(path), "--apply").returncode == 0

    assert sorted(_rows(path, query)) == before
    assert _rows(path, "SELECT count(*) FROM sources WHERE external_id LIKE 'url:%@%'") == [(1,)]
    again = _run(SCRIPT, "--sqlite", str(path), "--apply")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["readback"] == {"remaining_targets": 0, "rows_changed": 0}


def test_the_stored_row_policy_returns_a_compliant_row_unchanged():
    url = "https://www.youtube.com/watch?v=abc123"
    assert strip_stored_identity("youtube", url, DECLARED_TITLE, CLEAN_METADATA) == (url, DECLARED_TITLE, CLEAN_METADATA)
    _, title, metadata = strip_stored_identity("youtube", url, MENTION_TEXT, youtube_metadata())
    assert title.startswith("@[user]") and "channel_title" not in metadata


def test_a_missing_store_is_not_created(tmp_path):
    missing = tmp_path / "absent.sqlite3"
    result = _run(SCRIPT, "--sqlite", str(missing), "--apply")
    assert result.returncode != 0 and not missing.exists()
