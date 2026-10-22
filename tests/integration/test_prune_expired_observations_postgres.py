"""T014 on PostgreSQL: the retention action keeps claimed observations and cascades evidence."""

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.now(timezone.utc)


def _run(dsn, *args):
    return subprocess.run(
        [sys.executable, "scripts/prune_expired_observations.py", "--database-url-env", "IGNIS_PRUNE_DSN", *args],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "IGNIS_PRUNE_DSN": str(dsn)},
    )


def test_prune_on_postgres_keeps_claimed_and_recent_observations(schema_postgres_dsn):
    source, mission = str(uuid.uuid4()), str(uuid.uuid4())
    ids = {name: str(uuid.uuid4()) for name in ("old_free", "old_evidence", "old_claimed", "recent")}
    observed = {name: NOW - timedelta(days=430) for name in ids} | {"recent": NOW - timedelta(days=300)}
    with psycopg.connect(schema_postgres_dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id) VALUES (%s, 'youtube', 'video:a1')", (source,))
        for name, observation in ids.items():
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
                " observed_title, metric_value, growth_velocity, geo_code, metadata)"
                " VALUES (%s, %s, %s, 'exact_ingestion', 'metadata_external_id', 'áo khoác', 0, 0, 'VN', '{}')",
                (observation, source, observed[name]),
            )
        # Seed bindings without their missions and qualifications: only the links are under test.
        conn.execute("SET session_replication_role = replica")
        for name in ("old_evidence", "old_claimed", "recent"):
            conn.execute(
                "INSERT INTO mission_evidence (mission_id, observation_id, recorded_at) VALUES (%s, %s, now())",
                (mission, ids[name]),
            )
        conn.execute(
            "INSERT INTO mission_claim_evidence (claim_id, observation_id, role) VALUES (%s, %s, 'CONTEXT')",
            (str(uuid.uuid4()), ids["old_claimed"]),
        )

    dry = _run(schema_postgres_dsn)

    assert dry.returncode == 0, dry.stderr
    report = json.loads(dry.stdout)
    assert report["store"] == "postgres" and report["kept"]["claim"] == 1
    assert sorted(report["ids"]) == sorted([ids["old_free"], ids["old_evidence"]])

    applied = _run(schema_postgres_dsn, "--apply")

    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["readback"] == {"removed": 2, "remaining_to_remove": 0}
    with psycopg.connect(schema_postgres_dsn) as conn:
        left = {str(row[0]) for row in conn.execute("SELECT id FROM observations")}
        evidence = {str(row[0]) for row in conn.execute("SELECT observation_id FROM mission_evidence")}
    assert left == evidence == {ids["old_claimed"], ids["recent"]}


def test_apply_locks_out_new_claim_bindings_while_it_decides(schema_postgres_dsn, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import prune_expired_observations

    source, observation = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(schema_postgres_dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO sources (id, platform, external_id) VALUES (%s, 'youtube', 'video:b2')", (source,))
        conn.execute(
            "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
            " observed_title, metric_value, growth_velocity, geo_code, metadata)"
            " VALUES (%s, %s, %s, 'exact_ingestion', 'metadata_external_id', 'áo len', 0, 0, 'VN', '{}')",
            (observation, source, NOW - timedelta(days=430)),
        )
    original = prune_expired_observations._plan
    attempts = []

    def plan_with_a_concurrent_claim(read, tables, limit):
        with psycopg.connect(schema_postgres_dsn, autocommit=True) as other:
            other.execute("SET session_replication_role = replica")
            other.execute("SET lock_timeout = '300ms'")
            try:
                other.execute(
                    "INSERT INTO mission_claim_evidence (claim_id, observation_id, role) VALUES (%s, %s, 'CONTEXT')",
                    (str(uuid.uuid4()), observation),
                )
                attempts.append("written")
            except psycopg.errors.LockNotAvailable:
                attempts.append("locked")
        return original(read, tables, limit)

    monkeypatch.setenv("IGNIS_PRUNE_DSN", str(schema_postgres_dsn))
    monkeypatch.setattr(prune_expired_observations, "_plan", plan_with_a_concurrent_claim)
    prune_expired_observations._postgres("IGNIS_PRUNE_DSN", 13, NOW, apply=True)

    assert attempts and set(attempts) == {"locked"}, attempts
