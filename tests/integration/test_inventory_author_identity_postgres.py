"""T031 on PostgreSQL: the inventory counts legacy identity in a READ ONLY transaction."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg

from tests.fixtures.author_identity_sentinels import TIKTOK_HANDLE_URL, tiktok_metadata, undeclared_sentinels

ROOT = Path(__file__).resolve().parents[2]


def test_the_inventory_reads_postgres_without_writing(schema_postgres_dsn):
    source = str(uuid.uuid4())
    with psycopg.connect(schema_postgres_dsn, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES (%s, 'tiktok', 'video:7694797676306615583')",
            (source,),
        )
        conn.execute(
            "INSERT INTO observations (source_id, observed_at, time_provenance, identity_source,"
            " observed_title, metric_value, growth_velocity, geo_code, source_url, metadata)"
            " VALUES (%s, now(), 'exact_ingestion', 'metadata_external_id', 'Áo khoác', 0, 0, 'VN', %s, %s)",
            (source, TIKTOK_HANDLE_URL, json.dumps(tiktok_metadata())),
        )
        before = conn.execute("SELECT count(*) FROM observations").fetchone()[0]

    result = subprocess.run(
        [sys.executable, "scripts/inventory_author_identity.py", "--database-url-env", "IGNIS_INVENTORY_DSN"],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src"), "IGNIS_INVENTORY_DSN": str(schema_postgres_dsn)},
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    fields = report["tables"]["observations"]["fields"]
    assert report["store"] == "postgres" and report["read_only"] is True
    assert fields["metadata"]["rows_with_author_identity"] == 1
    assert fields["source_url"]["handle_links"] == 1
    assert [value for value in undeclared_sentinels() if value in result.stdout + result.stderr] == []
    with psycopg.connect(schema_postgres_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == before
