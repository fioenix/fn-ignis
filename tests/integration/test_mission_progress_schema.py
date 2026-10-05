"""Additive progress DDL contracts, exercised on disposable real PostgreSQL databases."""

import hashlib
import json
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import errors, sql
from psycopg.types.json import Jsonb

from conftest import REPO_SQL, all_postgres_migrations, runtime_owner
from test_postgres_rls_coverage import MISSION, OBSERVATION, RUN, SOURCE, SPARE_MISSION, _attempt, _seed

MIGRATION = "027_mission_progress.sql"
TABLES = ("mission_progress_revisions", "mission_progress_events", "mission_progress_commands")
CANONICAL = (
    "sources",
    "observations",
    "mission_evidence",
    "research_missions",
    "research_workspaces",
    "market_brief_revisions",
    "mission_run_journals",
    "mission_writer_claims",
    "mission_manifests",
    "mission_probe_outcomes",
    "mission_evidence_qualifications",
    "mission_claims",
    "mission_claim_evidence",
    "source_identity_aliases",
    "trend_signals",
    "signal_metrics",
)
EVENT = "00000000-0000-4000-8000-000000000020"
KEY = f"probe-outcomes:{MISSION}:{RUN}:{'a' * 64}"
REFERENCE = {
    "mission_id": MISSION,
    "observation_id": OBSERVATION,
    "source_id": SOURCE,
    "evidence_role": "MARKET_EVIDENCE",
    "direction": None,
    "qualification_relation": None,
    "qualification_frame_fingerprint": None,
}


def _apply(dsn, names):
    with psycopg.connect(dsn) as conn:
        for name in names:
            conn.execute((REPO_SQL / name).read_text(encoding="utf-8"))


def _install(dsn):
    # During RED, exercise the missing schema rather than failing in fixture setup.
    if (REPO_SQL / MIGRATION).exists():
        _apply(dsn, (MIGRATION,))


def _require_schema(dsn):
    with psycopg.connect(dsn) as conn:
        present = [conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] for table in TABLES]
    assert all(present), "Additive mission progress schema is missing"


@pytest.fixture
def populated_progress_dsn(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, tuple(name for name in all_postgres_migrations() if name != MIGRATION))
    _seed(dsn)
    # A real legacy observation whose absent ingestion clock must survive installation.
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source)"
            " VALUES (%s, %s, NULL, 'unknown', 'metadata_external_id')",
            (uuid4(), SOURCE),
        )
    return dsn


def _snapshot(dsn):
    result = {}
    with psycopg.connect(dsn) as conn:
        for table in CANONICAL:
            rows = conn.execute(
                sql.SQL("SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))
            ).fetchall()
            encoded = json.dumps([row[0] for row in rows], ensure_ascii=False, separators=(",", ":"))
            result[table] = {"count": len(rows), "sha256": hashlib.sha256(encoded.encode()).hexdigest()}
    return result


def _event(conn, **changes):
    fields = {
        "id": EVENT,
        "mission_id": MISSION,
        "revision": 1,
        "ordinal": 1,
        "run_id": RUN,
        "kind": "PROBE_OUTCOMES_RECORDED",
        "provenance": "HARNESS_OBSERVED",
        "causation_key": KEY,
        "evidence_references": Jsonb([REFERENCE]),
    }
    fields.update(changes)
    conn.execute(
        sql.SQL("INSERT INTO mission_progress_events ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, fields)),
            sql.SQL(", ").join(sql.Placeholder() for _ in fields),
        ),
        tuple(fields.values()),
    )


def _command(conn, **changes):
    fields = {
        "mission_id": MISSION,
        "command_key": KEY,
        "payload_fingerprint": "b" * 64,
        "outcome_count": 1,
        "run_id": RUN,
        "event_id": EVENT,
        "revision": 1,
        "ordinal": 1,
    }
    fields.update(changes)
    conn.execute(
        sql.SQL("INSERT INTO mission_progress_commands ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, fields)),
            sql.SQL(", ").join(sql.Placeholder() for _ in fields),
        ),
        tuple(fields.values()),
    )


def test_fresh_install_and_reapply_make_no_synthetic_progress(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, tuple(name for name in all_postgres_migrations() if name != MIGRATION))
    _install(dsn)
    _require_schema(dsn)
    _install(dsn)
    with psycopg.connect(dsn) as conn:
        assert [
            conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))).fetchone()[0] for t in TABLES
        ] == [0, 0, 0]


def test_populated_install_and_reapply_preserve_all_canonical_rows(populated_progress_dsn):
    dsn = populated_progress_dsn
    before = _snapshot(dsn)
    _install(dsn)
    _require_schema(dsn)
    assert _snapshot(dsn) == before
    with psycopg.connect(dsn) as conn:
        _event(conn)
        _command(conn)
        conn.execute("INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (%s, 1)", (MISSION,))
    _install(dsn)
    assert _snapshot(dsn) == before
    with psycopg.connect(dsn) as conn:
        assert conn.execute("SELECT revision FROM mission_progress_revisions").fetchall() == [(1,)]
        assert conn.execute("SELECT revision, ordinal, run_id FROM mission_progress_events").fetchall() == [
            (1, 1, UUID(RUN))
        ]
        assert conn.execute("SELECT outcome_count FROM mission_progress_commands").fetchall() == [(1,)]
    print("T008_CANONICAL_BEFORE_AFTER=" + json.dumps(before, sort_keys=True))


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"revision": 0}, errors.CheckViolation),
        ({"revision": -1}, errors.CheckViolation),
        ({"ordinal": 0}, errors.CheckViolation),
        ({"kind": "UNRECORDED"}, errors.CheckViolation),
        ({"provenance": "ASSUMED"}, errors.CheckViolation),
        ({"causation_key": "  "}, errors.CheckViolation),
        ({"run_id": None}, errors.CheckViolation),
        ({"run_id": str(uuid4())}, errors.ForeignKeyViolation),
        ({"mission_id": SPARE_MISSION, "evidence_references": Jsonb([])}, errors.CheckViolation),
        ({"claim_id": str(uuid4())}, errors.ForeignKeyViolation),
    ],
)
def test_event_constraints_refuse_invalid_positions_and_identity(populated_progress_dsn, changes, error):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn, pytest.raises(error):
        _event(conn, **changes)


@pytest.mark.parametrize(
    "reference",
    [
        {**REFERENCE, "raw_content": "unreviewed"},
        {k: v for k, v in REFERENCE.items() if k != "direction"},
        {**REFERENCE, "mission_id": SPARE_MISSION},
        {**REFERENCE, "source_id": "not-a-uuid"},
        {**REFERENCE, "source_id": None},
        {**REFERENCE, "evidence_role": "PERMITTED"},
        {**REFERENCE, "direction": "ELIGIBLE"},
        {**REFERENCE, "qualification_relation": "QUALIFIED_SUPPORT"},
        {**REFERENCE, "qualification_frame_fingerprint": "c" * 64},
        {**REFERENCE, "qualification_relation": "UNASSESSED", "qualification_frame_fingerprint": "not-sha256"},
        {**REFERENCE, "direction": {"raw": "transcript"}},
        "untyped",
    ],
)
def test_event_references_accept_only_exact_typed_payloads(populated_progress_dsn, reference):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn, pytest.raises(errors.CheckViolation):
        _event(conn, evidence_references=Jsonb([reference]))


def test_event_reference_container_and_cross_mission_claim_are_refused(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    from test_postgres_rls_coverage import T025_CLAIM

    with psycopg.connect(dsn) as conn, pytest.raises(errors.CheckViolation):
        _event(conn, evidence_references=Jsonb({"raw": "payload"}))
    with psycopg.connect(dsn) as conn, pytest.raises(errors.CheckViolation):
        _event(
            conn,
            mission_id=SPARE_MISSION,
            run_id=None,
            kind="CLAIM_GATE_CHANGED",
            claim_id=T025_CLAIM,
            evidence_references=Jsonb([]),
        )


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"outcome_count": 0}, errors.CheckViolation),
        ({"payload_fingerprint": "bad"}, errors.CheckViolation),
        ({"command_key": "bad"}, errors.CheckViolation),
        ({"revision": 2}, errors.ForeignKeyViolation),
        ({"ordinal": 2}, errors.ForeignKeyViolation),
        ({"event_id": str(uuid4())}, errors.ForeignKeyViolation),
        (
            {"mission_id": SPARE_MISSION, "command_key": f"probe-outcomes:{SPARE_MISSION}:{RUN}:{'a' * 64}"},
            errors.ForeignKeyViolation,
        ),
        (
            {"run_id": str(uuid4()), "command_key": f"probe-outcomes:{MISSION}:{uuid4()}:{'a' * 64}"},
            errors.CheckViolation,
        ),
    ],
)
def test_command_constraints_bind_the_original_receipt(populated_progress_dsn, changes, error):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn:
        _event(conn)
    with psycopg.connect(dsn) as conn, pytest.raises(error):
        _command(conn, **changes)


def test_duplicate_slots_and_commands_are_refused(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn:
        _event(conn)
        _command(conn)
    with psycopg.connect(dsn) as conn, pytest.raises(errors.UniqueViolation):
        _event(conn, id=uuid4())
    with psycopg.connect(dsn) as conn, pytest.raises(errors.UniqueViolation):
        _command(conn)


def test_non_superuser_table_owner_can_commit_and_roll_back_progress(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with runtime_owner(dsn) as owner_dsn:
        with psycopg.connect(owner_dsn) as conn:
            assert conn.execute(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            ).fetchone() == (False, False)
            conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (%s)", (MISSION,))
            assert conn.execute(
                "UPDATE mission_progress_revisions SET revision=revision+1 WHERE mission_id=%s RETURNING revision",
                (MISSION,),
            ).fetchone() == (1,)
            _event(conn)
            _command(conn)
        with psycopg.connect(owner_dsn) as conn:
            conn.execute("UPDATE mission_progress_revisions SET revision=revision+1 WHERE mission_id=%s", (MISSION,))
            conn.rollback()
        with psycopg.connect(owner_dsn) as conn:
            assert conn.execute("SELECT revision FROM mission_progress_revisions").fetchall() == [(1,)]
            conn.execute("UPDATE mission_progress_events SET reason='recorded receipt'")
            conn.execute("DELETE FROM mission_progress_commands")
            conn.execute("DELETE FROM mission_progress_events")
            conn.execute("DELETE FROM mission_progress_revisions")


def test_revision_control_refuses_negative_and_unknown_mission(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn, pytest.raises(errors.CheckViolation):
        conn.execute("INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (%s, -1)", (MISSION,))
    with psycopg.connect(dsn) as conn, pytest.raises(errors.ForeignKeyViolation):
        conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (%s)", (uuid4(),))


@pytest.mark.parametrize("changes", [{"kind": "OBSERVATIONS_COMMITTED"}, {"provenance": "HOST_REPORTED"}])
def test_probe_receipt_cannot_bind_a_different_event_fact(populated_progress_dsn, changes):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn:
        _event(conn, **changes)
    with psycopg.connect(dsn) as conn, pytest.raises(errors.ForeignKeyViolation):
        _command(conn)


def test_update_cannot_move_a_referenced_run_to_another_mission(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn:
        _event(conn)
    with psycopg.connect(dsn) as conn, pytest.raises(errors.CheckViolation):
        conn.execute("UPDATE mission_progress_events SET mission_id=%s, evidence_references='[]'", (SPARE_MISSION,))


def test_individual_referenced_deletion_refused_and_whole_mission_cascades(populated_progress_dsn):
    from test_postgres_rls_coverage import T025_CLAIM

    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with psycopg.connect(dsn) as conn:
        _event(conn, claim_id=T025_CLAIM)
        _command(conn)
        conn.execute("INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (%s, 1)", (MISSION,))
    for table, identity in (("mission_run_journals", RUN), ("mission_claims", T025_CLAIM)):
        with psycopg.connect(dsn) as conn, pytest.raises(errors.ForeignKeyViolation):
            conn.execute(sql.SQL("DELETE FROM {} WHERE id=%s").format(sql.Identifier(table)), (identity,))
    with psycopg.connect(dsn) as conn:
        conn.execute("DELETE FROM research_missions WHERE id=%s", (MISSION,))
        assert [
            conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(t))).fetchone()[0] for t in TABLES
        ] == [0, 0, 0]


def test_public_grant_negative_control_and_reapply_close_effective_access(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    role = "ignis_progress_" + uuid4().hex
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS").format(sql.Identifier(role)))
            conn.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
            for table in TABLES:
                conn.execute(sql.SQL("GRANT ALL ON {} TO PUBLIC").format(sql.Identifier(table)))
        # Reproduce the bypass: RLS filters SELECT, but cannot stop inherited TRUNCATE.
        for table in TABLES:
            assert _attempt(dsn, role, table, "SELECT") == "read 0"
            assert _attempt(dsn, role, table, "TRUNCATE") == "truncated"
        _install(dsn)
        for table in TABLES:
            for operation in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert _attempt(dsn, role, table, operation) == "denied"
            with psycopg.connect(dsn) as conn:
                for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                    assert conn.execute(
                        "SELECT has_table_privilege(%s, %s, %s)", (role, table, privilege)
                    ).fetchone() == (False,)
    finally:
        with psycopg.connect(dsn) as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_client_fixture_rows_are_valid_when_executed_by_the_owner(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, all_postgres_migrations())
    _require_schema(dsn)
    _seed(dsn)
    with runtime_owner(dsn) as owner_dsn:
        from conftest import RUNTIME_ROLE

        for table in TABLES:
            assert _attempt(owner_dsn, RUNTIME_ROLE, table, "INSERT") == "insert 1"


def test_owner_event_id_defaults_work_without_uuid_ossp_execute(populated_progress_dsn):
    dsn = populated_progress_dsn
    _install(dsn)
    _require_schema(dsn)
    with runtime_owner(dsn) as owner_dsn, psycopg.connect(owner_dsn) as conn:
        assert conn.execute("SELECT has_function_privilege('public.uuid_generate_v4()', 'EXECUTE')").fetchone() == (
            False,
        )
        event_id = conn.execute(
            "INSERT INTO mission_progress_events (mission_id, revision, ordinal, kind, provenance, causation_key)"
            " VALUES (%s, 1, 1, 'COLLECTION_STARTED', 'HARNESS_OBSERVED', 'start') RETURNING id",
            (MISSION,),
        ).fetchone()[0]
        assert type(event_id) is UUID
        assert conn.execute("SELECT id FROM mission_progress_events WHERE mission_id=%s", (MISSION,)).fetchall() == [
            (event_id,)
        ]
