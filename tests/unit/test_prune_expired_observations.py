"""T014: the explicit 13-month retention action (Spec 016 US4, FR-014).

An observation collected before the cutoff is removed unless a stored claim cites it; its mission
evidence goes with it. A dry run lists and writes nothing; --apply removes and reads back.
"""

import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "prune_expired_observations.py"
sys.path.insert(0, str(ROOT / "scripts"))
import prune_expired_observations  # noqa: E402
from prune_expired_observations import cutoff  # noqa: E402

NOW = datetime.now(timezone.utc)
OLD = (NOW - timedelta(days=430)).isoformat()
RECENT = (NOW - timedelta(days=300)).isoformat()


def _seed(path: Path) -> dict:
    repository = SqliteTrendRepository(str(path))
    asyncio.run(repository._ensure_schema())
    asyncio.run(repository.close())
    conn = sqlite3.connect(path)
    source = str(uuid.uuid4())
    conn.execute("INSERT INTO sources (id, platform, external_id) VALUES (?, 'youtube', 'video:a1')", (source,))
    ids = {name: str(uuid.uuid4()) for name in ("old_free", "old_evidence", "old_claimed", "recent")}
    observed = {"old_free": OLD, "old_evidence": OLD, "old_claimed": OLD, "recent": RECENT}
    conn.executemany(
        "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
        " observed_title, metric_value, growth_velocity, geo_code, source_url, metadata)"
        " VALUES (?, ?, ?, 'exact_ingestion', 'metadata_external_id', 'áo khoác', 0, 0, 'VN', NULL, '{}')",
        [(ids[name], source, observed[name]) for name in ids],
    )
    mission = str(uuid.uuid4())
    conn.executemany(
        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at) VALUES (?, ?, ?, ?)",
        [(str(uuid.uuid4()), mission, ids[name], OLD) for name in ("old_evidence", "old_claimed", "recent")],
    )
    # Only the claim -> observation link is under test, not the qualification chain behind it.
    for (name,) in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'mission_claim_evidence'"
    ).fetchall():
        conn.execute(f'DROP TRIGGER "{name}"')
    conn.execute(
        "INSERT INTO mission_claim_evidence (id, claim_id, observation_id, role) VALUES (?, ?, ?, 'CONTEXT')",
        (str(uuid.uuid4()), str(uuid.uuid4()), ids["old_claimed"]),
    )
    conn.commit()
    conn.close()
    return {**ids, "mission": mission}


def _run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True, cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
    )


def _ids(path, table, column="id"):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute(f"SELECT {column} FROM {table}")}
    finally:
        conn.close()


@pytest.fixture
def seeded(tmp_path):
    path = tmp_path / "retention.sqlite3"
    return path, _seed(path)


def test_a_dry_run_lists_only_unreferenced_expired_observations(seeded):
    path, ids = seeded
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    result = _run("--sqlite", str(path))

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["mode"] == "dry-run" and report["older_than_months"] == 13
    assert report["expired"] == 3 and report["kept"] == {"claim": 1, "research_work": 0, "readiness": 0}
    assert sorted(report["ids"]) == sorted([ids["old_free"], ids["old_evidence"]])
    assert report["mission_evidence_by_mission"] == {ids["mission"]: 1}
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before, "A dry run must not write"


def test_apply_removes_them_with_their_evidence_and_keeps_the_rest(seeded):
    path, ids = seeded

    result = _run("--sqlite", str(path), "--apply")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["readback"] == {"removed": 2, "remaining_to_remove": 0}
    assert _ids(path, "observations") == {ids["old_claimed"], ids["recent"]}
    assert _ids(path, "mission_evidence", "observation_id") == {ids["old_claimed"], ids["recent"]}
    assert len(_ids(path, "sources")) == 1, "Sources are kept"
    again = json.loads(_run("--sqlite", str(path), "--apply").stdout)
    assert again["readback"] == {"removed": 0, "remaining_to_remove": 0}


def test_a_shorter_retention_reaches_recent_observations(seeded):
    path, ids = seeded
    report = json.loads(_run("--sqlite", str(path), "--older-than-months", "6").stdout)
    assert ids["recent"] in report["ids"] and ids["old_claimed"] not in report["ids"]


def test_the_cutoff_is_midnight_in_vietnam_months_earlier():
    now = datetime(2026, 3, 31, 2, 0, tzinfo=timezone.utc)  # 31/03/2026 09:00 in Asia/Ho_Chi_Minh
    assert cutoff(now, 13) == datetime(2025, 2, 27, 17, 0, tzinfo=timezone.utc)  # 28/02/2025 00:00 ICT
    assert cutoff(datetime(2026, 10, 22, 18, 0, tzinfo=timezone.utc), 1) == datetime(
        2026, 9, 22, 17, 0, tzinfo=timezone.utc
    )  # 23/10 01:00 ICT -> 23/09 00:00 ICT


def test_refuses_a_missing_store_and_a_zero_retention(tmp_path):
    missing = tmp_path / "absent.sqlite3"
    assert _run("--sqlite", str(missing), "--apply").returncode != 0 and not missing.exists()
    assert _run("--sqlite", str(missing), "--older-than-months", "0").returncode != 0


def test_a_store_with_legacy_signals_keeps_one_observation_and_still_opens(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    ids = _seed(path)
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM mission_claim_evidence")
    conn.execute("DELETE FROM observations WHERE id = ?", (ids["recent"],))
    conn.execute(
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, captured_at)"
        " VALUES (?, 'youtube', 'áo khoác', 0, ?)",
        (str(uuid.uuid4()), OLD),
    )
    conn.commit()
    conn.close()

    report = json.loads(_run("--sqlite", str(path), "--apply").stdout)

    assert report["kept"]["readiness"] == 1 and report["readback"]["removed"] == 2
    assert len(_ids(path, "observations")) == 1
    repository = SqliteTrendRepository(str(path))
    asyncio.run(repository._ensure_schema())  # The readiness check refuses a store with no observation.
    asyncio.run(repository.close())


def test_apply_holds_the_write_lock_while_it_decides(seeded, monkeypatch):
    path, ids = seeded
    original = prune_expired_observations._plan
    attempts = []

    def plan_with_a_concurrent_claim(read, tables, limit):
        other = sqlite3.connect(path, timeout=0)
        try:
            other.execute(
                "INSERT INTO mission_claim_evidence (id, claim_id, observation_id, role) VALUES (?, ?, ?, 'CONTEXT')",
                (str(uuid.uuid4()), str(uuid.uuid4()), ids["old_free"]),
            )
            other.commit()
            attempts.append("written")
        except sqlite3.OperationalError as error:
            attempts.append(str(error))
        finally:
            other.close()
        return original(read, tables, limit)

    monkeypatch.setattr(prune_expired_observations, "_plan", plan_with_a_concurrent_claim)
    prune_expired_observations._sqlite(path, 13, NOW, apply=True)

    assert attempts and all("locked" in attempt for attempt in attempts), attempts
