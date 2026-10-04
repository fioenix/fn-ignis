"""An existing evidence graph survives the partial-outcome SQLite upgrade."""

import re
import sqlite3

import pytest

from scripts import rehearse_evidence_grounded_schema as rehearsal
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.mark.parametrize("deny_swap", [False, True])
def test_existing_constraint_upgrade_preserves_every_row_and_dependent_binding(tmp_path, deny_swap):
    path = tmp_path / "existing.sqlite"
    rehearsal._initialize(path)
    with sqlite3.connect(path) as conn:
        rehearsal._seed_synthetic_projection(conn)
        rehearsal._seed_control_plane(conn)
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'mission_probe_outcomes'"
        ).fetchone()[0]
        # Recreate the pre-026 CHECK, independently of the runtime's upgrade detector.
        legacy_schema = re.sub(
            r"(?:CONSTRAINT mission_probe_outcomes_partial_count_check )?"
            r"CHECK \(signals_collected >= 0.*?\),\s*CHECK \(status <> 'EMPTY_NO_DATA'",
            "CHECK (signals_collected >= 0 AND (status = 'HEALTHY') = "
            "(signals_collected > 0)), CHECK (status <> 'EMPTY_NO_DATA'",
            schema, flags=re.DOTALL,
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("CREATE TEMP TABLE preserved_outcomes AS SELECT * FROM mission_probe_outcomes")
        conn.execute("DROP TABLE mission_probe_outcomes")
        conn.execute(legacy_schema)
        conn.execute("INSERT INTO mission_probe_outcomes SELECT * FROM preserved_outcomes")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
        before = {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                  for table in tables}
        assert before["mission_claim_evidence"] and before["mission_evidence_qualifications"]
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE mission_probe_outcomes SET status='DEGRADED', signals_collected=47")
        conn.rollback()

        if deny_swap:
            schema_before = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
            conn.set_authorizer(lambda action, *args: sqlite3.SQLITE_DENY
                                if action == sqlite3.SQLITE_ALTER_TABLE else sqlite3.SQLITE_OK)
            with pytest.raises(sqlite3.DatabaseError):
                SqliteTrendRepository._upgrade_evidence_grounded_schema(conn)
            conn.set_authorizer(None)
            assert conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall() == schema_before
            assert {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                    for table in tables} == before
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
            return
        SqliteTrendRepository._upgrade_evidence_grounded_schema(conn)
        SqliteTrendRepository._ensure_evidence_grounded_triggers(conn)
        after = {table: conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
                 for table in tables}
        assert after == before
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute("UPDATE mission_probe_outcomes SET status='DEGRADED', signals_collected=47,"
                     " note='One query failed; other queries retained observations'")
        conn.commit()
        for status in ("EMPTY_NO_DATA", "FAILED", "AUTH_REQUIRED", "RATE_LIMITED", "NOT_REQUESTED"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE mission_probe_outcomes SET status=?", (status,))
            conn.rollback()
        settled = conn.execute("SELECT * FROM mission_probe_outcomes").fetchall()
        SqliteTrendRepository._upgrade_evidence_grounded_schema(conn)
        assert conn.execute("SELECT * FROM mission_probe_outcomes").fetchall() == settled
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
