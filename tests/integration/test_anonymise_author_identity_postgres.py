"""T039 on PostgreSQL: a dry run writes nothing, --apply rewrites legacy identity and reads back none."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

from tests.fixtures.author_identity_sentinels import (
    MENTION_TEXT,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
    tiktok_metadata,
    undeclared_sentinels,
)

ROOT = Path(__file__).resolve().parents[2]


def _run(dsn, *args):
    return subprocess.run(
        [sys.executable, "scripts/anonymise_author_identity.py", "--database-url-env", "IGNIS_ANONYMISE_DSN", *args],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "IGNIS_ANONYMISE_DSN": str(dsn)},
    )


def test_anonymise_rewrites_postgres_rows_only_on_apply(schema_postgres_dsn):
    source = str(uuid.uuid4())
    with psycopg.connect(schema_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES (%s, 'tiktok', %s)",
            (source, f"video:{TIKTOK_ITEM_ID}"),
        )
        observation = conn.execute(
            "INSERT INTO observations (source_id, observed_at, time_provenance, identity_source,"
            " observed_title, metric_value, growth_velocity, geo_code, source_url, metadata)"
            " VALUES (%s, now(), 'exact_ingestion', 'metadata_external_id', %s, 0, 0, 'VN', %s, %s) RETURNING id",
            (source, MENTION_TEXT, TIKTOK_HANDLE_URL, json.dumps(tiktok_metadata())),
        ).fetchone()[0]
        before = conn.execute("SELECT observed_title, source_url, metadata FROM observations WHERE id = %s", (observation,)).fetchone()

    dry = _run(schema_postgres_dsn)

    assert dry.returncode == 0, dry.stderr
    manifest = json.loads(dry.stdout)
    assert manifest["store"] == "postgres" and manifest["mode"] == "dry-run"
    assert manifest["targets"]["observations"]["ids"] == [str(observation)]
    with psycopg.connect(schema_postgres_dsn) as conn:
        assert conn.execute(
            "SELECT observed_title, source_url, metadata FROM observations WHERE id = %s", (observation,)
        ).fetchone() == before

    applied = _run(schema_postgres_dsn, "--apply")

    assert applied.returncode == 0, applied.stderr
    assert json.loads(applied.stdout)["readback"] == {"remaining_targets": 0, "rows_changed": 1}
    with psycopg.connect(schema_postgres_dsn) as conn:
        title, url, metadata = conn.execute(
            "SELECT observed_title, source_url, metadata FROM observations WHERE id = %s", (observation,)
        ).fetchone()
    assert url == f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}" and title.startswith("@[user]")
    stored = json.dumps(metadata, ensure_ascii=False) + title + url
    assert [value for value in undeclared_sentinels() if value in stored + dry.stdout + applied.stdout + applied.stderr] == []
