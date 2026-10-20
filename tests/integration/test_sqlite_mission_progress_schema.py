"""Explicit additive progress setup, exercised against actual SQLite constraints and reads."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

import pytest
import pytest_asyncio

from ignis.domain.exceptions import RepositoryException
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


STAMP = "2026-10-04T00:00:00+00:00"
WORKSPACE = "00000000-0000-4000-8000-000000000001"
MISSION = "00000000-0000-4000-8000-000000000002"
OTHER_MISSION = "00000000-0000-4000-8000-000000000003"
SOURCE = "00000000-0000-4000-8000-000000000005"
OBSERVATION = "00000000-0000-4000-8000-000000000006"
RUN = "00000000-0000-4000-8000-000000000007"
CLAIM = "00000000-0000-4000-8000-000000000009"
EVENT = "00000000-0000-4000-8000-000000000020"
OTHER_EVENT = "00000000-0000-4000-8000-000000000021"
KEY = f"probe-outcomes:{MISSION}:{RUN}:{'a' * 64}"
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
REFERENCE = {
    "mission_id": MISSION,
    "observation_id": OBSERVATION,
    "source_id": SOURCE,
    "evidence_role": "MARKET_EVIDENCE",
    "direction": None,
    "qualification_relation": None,
    "qualification_frame_fingerprint": None,
}


@contextmanager
def _connection(repository):
    conn = repository._get_connection()
    try:
        yield conn
    finally:
        if repository._mem_conn is None:
            conn.close()


def _insert(conn, table, fields):
    # Identifiers come only from literal test fixtures, never callers or provider data.
    conn.execute(
        f"INSERT INTO {table} ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
        tuple(fields.values()),
    )


def _seed(repository):
    rows = (
        ("research_workspaces", dict(id=WORKSPACE, slug="schema", root_path="/schema", created_at=STAMP)),
        (
            "research_missions",
            dict(id=MISSION, title="Schema mission", keywords="[]", created_at=STAMP, workspace_id=WORKSPACE),
        ),
        (
            "research_missions",
            dict(id=OTHER_MISSION, title="Other mission", keywords="[]", created_at=STAMP, workspace_id=WORKSPACE),
        ),
        (
            "market_brief_revisions",
            dict(
                id="00000000-0000-4000-8000-000000000011",
                workspace_id=WORKSPACE,
                mission_id=MISSION,
                revision_number=1,
                decision="decide",
                target_user="operator",
                problem="setup",
                geo="VN",
                timeframe="7d",
                hypothesis="testable",
                falsifiers='["refused"]',
                confirmed_by="owner",
                confirmed_at=STAMP,
            ),
        ),
        (
            "mission_run_journals",
            dict(
                id=RUN,
                workspace_id=WORKSPACE,
                mission_id=MISSION,
                journal_path="/schema/run",
                sequence=1,
                status="COMPLETED",
                started_at=STAMP,
                completed_at=STAMP,
            ),
        ),
        ("mission_writer_claims", dict(mission_id=MISSION, run_id=RUN, claimed_at=STAMP)),
        ("sources", dict(id=SOURCE, platform="youtube", external_id="video:schema")),
        (
            "observations",
            dict(
                id=OBSERVATION,
                source_id=SOURCE,
                observed_at=None,
                time_provenance="unknown",
                identity_source="metadata_external_id",
                observed_title="Unknown ingestion time",
                metric_value=None,
            ),
        ),
        (
            "mission_evidence",
            dict(
                id="00000000-0000-4000-8000-000000000012",
                mission_id=MISSION,
                observation_id=OBSERVATION,
                recorded_at=STAMP,
            ),
        ),
        (
            "mission_manifests",
            dict(
                mission_id=MISSION,
                outcome="observe",
                required_channels='["youtube"]',
                authority_boundary='{"public_http":true,"official_api":false,"browser_session":false,"paid_quota":false}',
                output_type="COLLECTION_FRAME",
                stop_conditions='["complete"]',
                analysis_policy="evidence-v1",
                retention_policy="mission-only",
                created_by="owner",
                confirmed_at=STAMP,
                manifest_digest="manifest",
            ),
        ),
        (
            "mission_probe_outcomes",
            dict(
                id="00000000-0000-4000-8000-000000000013",
                run_id=RUN,
                platform="youtube",
                connector_surface="youtube.search",
                status="EMPTY_NO_DATA",
                signals_collected=0,
                queried_keywords='["schema"]',
                query_fingerprint="fingerprint",
                completed_at=STAMP,
            ),
        ),
        (
            "mission_evidence_qualifications",
            dict(
                id="00000000-0000-4000-8000-000000000014",
                mission_id=MISSION,
                observation_id=OBSERVATION,
                frame_fingerprint="frame",
                relation="QUALIFIED_SUPPORT",
                purpose="VOC",
                confidence=0.9,
                reason_code="DIRECT_TO_FRAME",
                judged_by="owner",
                hypothesis_target="core",
                evidence_role="SUPPORT",
                evidence_contract_version=2,
                created_at=STAMP,
            ),
        ),
        (
            "mission_claims",
            dict(
                id=CLAIM,
                mission_id=MISSION,
                frame_digest="frame",
                client_claim_key="claim",
                claim_type="OBSERVATION",
                wording="observed",
                status="PERMITTED",
                created_by="owner",
                created_at=STAMP,
            ),
        ),
        (
            "mission_claim_evidence",
            dict(
                id="00000000-0000-4000-8000-000000000015",
                claim_id=CLAIM,
                observation_id=OBSERVATION,
                role="SUPPORT",
                hypothesis_target="core",
            ),
        ),
        (
            "source_identity_aliases",
            dict(
                id="00000000-0000-4000-8000-000000000016",
                platform="youtube",
                alias_external_id="url:schema",
                canonical_external_id="video:schema",
                witnessed_by="owner",
                recorded_at=STAMP,
            ),
        ),
        (
            "trend_signals",
            dict(
                id="00000000-0000-4000-8000-000000000017",
                platform="youtube",
                raw_title="Legacy title",
                metric_value=0,
                captured_at=STAMP,
            ),
        ),
        ("signal_metrics", dict(id=1, signal_id="00000000-0000-4000-8000-000000000017", captured_at=STAMP)),
    )
    with _connection(repository) as conn:
        for table, fields in rows:
            _insert(conn, table, fields)
        conn.commit()


def _snapshot(repository):
    result = {}
    with _connection(repository) as conn:
        for table in CANONICAL:
            rows = sorted(
                json.dumps(dict(row), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                for row in conn.execute(f"SELECT * FROM {table}")
            )
            encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
            result[table] = {"count": len(rows), "sha256": hashlib.sha256(encoded).hexdigest()}
    return result


def _tables(repository):
    with _connection(repository) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


async def _install(repository):
    initializer = getattr(repository, "_ensure_progress_schema", None)
    assert callable(initializer), "Explicit mission progress schema initializer is missing"
    await initializer()
    assert set(TABLES) <= _tables(repository), "Additive mission progress schema is missing"


def _event(conn, **changes):
    fields = dict(
        id=EVENT,
        mission_id=MISSION,
        revision=1,
        ordinal=1,
        run_id=RUN,
        kind="PROBE_OUTCOMES_RECORDED",
        provenance="HARNESS_OBSERVED",
        causation_key=KEY,
        evidence_references=json.dumps([REFERENCE]),
    )
    fields.update(changes)
    _insert(conn, "mission_progress_events", fields)


def _command(conn, **changes):
    fields = dict(
        mission_id=MISSION,
        command_key=KEY,
        payload_fingerprint="b" * 64,
        outcome_count=1,
        run_id=RUN,
        event_id=EVENT,
        revision=1,
        ordinal=1,
    )
    fields.update(changes)
    _insert(conn, "mission_progress_commands", fields)


@pytest_asyncio.fixture(params=("file", "memory"))
async def canonical_repository(request, tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "schema.sqlite") if request.param == "file" else ":memory:")
    await repository._ensure_schema()
    try:
        yield repository
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_explicit_setup_and_reapplication_invent_no_progress(canonical_repository):
    repository = canonical_repository
    assert not set(TABLES) & _tables(repository)
    await _install(repository)
    await _install(repository)
    with _connection(repository) as conn:
        assert [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES] == [0, 0, 0]


@pytest.mark.asyncio
async def test_populated_setup_and_reapplication_preserve_all_canonical_rows(canonical_repository):
    repository = canonical_repository
    _seed(repository)
    before = _snapshot(repository)
    assert [before[table]["count"] for table in CANONICAL] == [1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    await _install(repository)
    assert _snapshot(repository) == before
    with _connection(repository) as conn:
        _event(conn)
        _command(conn)
        conn.execute("INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (?, 1)", (MISSION,))
        conn.commit()
    await _install(repository)
    assert _snapshot(repository) == before
    with _connection(repository) as conn:
        assert tuple(conn.execute("SELECT revision, ordinal, run_id FROM mission_progress_events").fetchone()) == (
            1,
            1,
            RUN,
        )
        assert conn.execute("SELECT revision FROM mission_progress_revisions").fetchone()[0] == 1
        assert conn.execute("SELECT outcome_count FROM mission_progress_commands").fetchone()[0] == 1
        assert conn.execute("SELECT observed_at, metric_value FROM observations").fetchone()[:] == (None, None)
    print("T009_CANONICAL_BEFORE_AFTER=" + json.dumps(before, sort_keys=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ("fresh", "old", "populated", "memory"))
async def test_legacy_reads_never_initialize_progress(layout, tmp_path, monkeypatch):
    repository = SqliteTrendRepository(":memory:" if layout == "memory" else str(tmp_path / "read.sqlite"))
    if layout != "fresh":
        await repository._ensure_schema()
        if layout == "populated":
            _seed(repository)
        if layout == "old":
            with _connection(repository) as conn:
                conn.execute("ALTER TABLE research_missions DROP COLUMN platforms")
                conn.commit()
        if layout != "memory":
            repository = SqliteTrendRepository(repository._db_path)
    trace, invoked = [], []
    original = repository._get_connection
    original_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        # Include the snapshot's separate in-memory backup connection in the SQL spy.
        conn = original_connect(*args, **kwargs)
        conn.set_trace_callback(trace.append)
        return conn

    def connect():
        conn = original()
        conn.set_trace_callback(trace.append)
        return conn

    async def forbidden_initializer():
        invoked.append(True)
        raise AssertionError("A legacy read attempted progress setup")

    monkeypatch.setattr(repository, "_get_connection", connect)
    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    monkeypatch.setattr(repository, "_ensure_progress_schema", forbidden_initializer, raising=False)
    try:
        mission = await repository.get_mission(UUID(MISSION))
        missions = await repository.list_missions()
        snapshot = await repository.load_mission_evidence_snapshot(UUID(MISSION))
        assert (mission is not None) == (layout == "populated")
        assert len(missions) == (2 if layout == "populated" else 0)
        assert (snapshot.mission is not None) == (layout == "populated")
        assert not invoked
        assert not any("mission_progress_" in statement.lower() for statement in trace)
        assert not set(TABLES) & _tables(repository)
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ("missing", "old"))
async def test_explicit_progress_setup_refuses_missing_canonical_targets(layout, tmp_path, monkeypatch):
    repository = SqliteTrendRepository(str(tmp_path / "missing.sqlite"))
    if layout == "old":
        with _connection(repository) as conn:
            conn.execute("CREATE TABLE research_missions (id TEXT PRIMARY KEY)")
            conn.commit()
    before = _tables(repository)
    initializer = getattr(repository, "_ensure_progress_schema", None)
    assert callable(initializer), "Explicit mission progress schema initializer is missing"

    async def forbidden_canonical_setup():
        raise AssertionError("Progress setup attempted canonical bootstrap")

    monkeypatch.setattr(repository, "_ensure_schema", forbidden_canonical_setup)
    with pytest.raises(RepositoryException):
        await initializer()
    assert _tables(repository) == before
    assert not repository._initialized


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    (
        {"revision": 0},
        {"revision": -1},
        {"revision": 1.5},
        {"revision": "wrong"},
        {"ordinal": 0},
        {"ordinal": 1.5},
        {"kind": "UNRECORDED"},
        {"provenance": "ASSUMED"},
        {"causation_key": "  "},
        {"id": None},
        {"id": "wrong"},
        {"mission_id": None},
        {"run_id": None},
        {"run_id": OTHER_EVENT},
        {"claim_id": OTHER_EVENT},
        {"mission_id": OTHER_MISSION, "evidence_references": "[]"},
        {"work_id": "wrong"},
        {"handoff_id": "wrong"},
        {"finding_id": "wrong"},
        {"recorded_at": None},
        {"evidence_references": None},
    ),
)
async def test_event_constraints_refuse_invalid_identity_and_position(canonical_repository, changes):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn, pytest.raises(sqlite3.IntegrityError):
        _event(conn, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reference",
    (
        {**REFERENCE, "title": "extra content"},
        {key: value for key, value in REFERENCE.items() if key != "direction"},
        {**REFERENCE, "mission_id": OTHER_MISSION},
        {**REFERENCE, "observation_id": "wrong"},
        {**REFERENCE, "source_id": "wrong"},
        {**REFERENCE, "evidence_role": "SUPPORT"},
        {**REFERENCE, "direction": "INVENTED"},
        {**REFERENCE, "direction": 1},
        {**REFERENCE, "qualification_relation": "QUALIFIED_SUPPORT"},
        {**REFERENCE, "qualification_frame_fingerprint": "a" * 64},
        {**REFERENCE, "qualification_relation": "INVENTED", "qualification_frame_fingerprint": "a" * 64},
        {**REFERENCE, "qualification_relation": "QUALIFIED_SUPPORT", "qualification_frame_fingerprint": "A" * 64},
        {**REFERENCE, "qualification_relation": "QUALIFIED_SUPPORT", "qualification_frame_fingerprint": "a" * 63},
        {**REFERENCE, "source_id": {"id": SOURCE}},
        None,
        "string",
        1,
    ),
)
async def test_event_references_refuse_untyped_unknown_or_cross_scope_fields(canonical_repository, reference):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn, pytest.raises(sqlite3.IntegrityError):
        _event(conn, evidence_references=json.dumps([reference]))


@pytest.mark.asyncio
@pytest.mark.parametrize("references", ("{", "{}", "null", "1", '"string"'))
async def test_event_references_require_a_valid_json_array(canonical_repository, references):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn, pytest.raises(sqlite3.IntegrityError):
        _event(conn, evidence_references=references)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    (
        {"outcome_count": 0},
        {"outcome_count": 1.5},
        {"payload_fingerprint": "A" * 64},
        {"payload_fingerprint": "a" * 63},
        {"command_key": "wrong"},
        {"command_key": KEY + "x"},
        {"event_id": OTHER_EVENT},
        {"revision": 2},
        {"ordinal": 2},
        {"run_id": OTHER_EVENT},
        {"mission_id": OTHER_MISSION},
        {"event_kind": "OBSERVATIONS_COMMITTED"},
        {"event_provenance": "HOST_REPORTED"},
        {"event_id": None},
    ),
)
async def test_command_constraints_bind_exact_original_receipt(canonical_repository, changes):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        _event(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _command(conn, **changes)


@pytest.mark.asyncio
async def test_defaults_nulls_unique_receipts_and_per_connection_foreign_keys(canonical_repository):
    repository = canonical_repository
    _seed(repository)
    await _install(repository)
    for _ in range(2):
        with _connection(repository) as conn:
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (?)", (OTHER_EVENT,))
            conn.rollback()
    with _connection(repository) as conn:
        conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (?)", (MISSION,))
        assert conn.execute("SELECT revision FROM mission_progress_revisions").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE mission_progress_revisions SET revision = -1")
        _event(conn)
        _command(conn)
        with pytest.raises(sqlite3.IntegrityError):
            _event(conn, id=OTHER_EVENT)
        with pytest.raises(sqlite3.IntegrityError):
            _command(conn)
        _insert(
            conn,
            "mission_progress_events",
            dict(
                mission_id=MISSION,
                revision=2,
                ordinal=1,
                kind="WORK_WAITING",
                provenance="HOST_REPORTED",
                causation_key="wait",
            ),
        )
        row = conn.execute("SELECT * FROM mission_progress_events WHERE revision = 2").fetchone()
        assert UUID(row["id"]).version == 4
        assert row["recorded_at"] is not None
        assert [
            row[field]
            for field in ("occurred_at", "run_id", "work_id", "handoff_id", "finding_id", "claim_id", "reason")
        ] == [None] * 7
        assert json.loads(row["evidence_references"]) == []
        conn.commit()


@pytest.mark.asyncio
async def test_typed_reference_roles_and_qualifications_preserve_nulls(canonical_repository):
    _seed(canonical_repository)
    await _install(canonical_repository)
    references = [REFERENCE, {**REFERENCE, "evidence_role": "ATTENTION_CONTEXT", "direction": "CONTEXT"}]
    for relation in (
        "QUALIFIED_SUPPORT",
        "QUALIFIED_CONTRADICTION",
        "CONTEXT_ONLY",
        "EXCLUDED_IRRELEVANT",
        "UNASSESSED",
    ):
        references.append(
            {
                **REFERENCE,
                "direction": "CONTRADICTION",
                "qualification_relation": relation,
                "qualification_frame_fingerprint": "a" * 64,
            }
        )
    with _connection(canonical_repository) as conn:
        _event(conn, evidence_references=json.dumps(references), occurred_at=STAMP, claim_id=CLAIM)
        row = conn.execute("SELECT evidence_references, occurred_at FROM mission_progress_events").fetchone()
        assert json.loads(row[0]) == references
        assert row[1] == STAMP


@pytest.mark.asyncio
async def test_updates_validate_scope_and_individual_delete_refuses_then_mission_cascades(canonical_repository):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        _event(conn, claim_id=CLAIM)
        _command(conn)
        conn.commit()
        for changes in ("mission_id = ?", "evidence_references = ?"):
            value = OTHER_MISSION if changes.startswith("mission_id") else json.dumps([{**REFERENCE, "title": "extra"}])
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE mission_progress_events SET {changes}", (value,))
        for table, identity in (("mission_run_journals", RUN), ("mission_claims", CLAIM)):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (identity,))
        conn.execute("DELETE FROM research_missions WHERE id = ?", (MISSION,))
        assert [conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES] == [0, 0, 0]
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.asyncio
async def test_cross_mission_claim_and_non_probe_receipt_are_refused(canonical_repository):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        conn.execute("UPDATE mission_claims SET mission_id = ? WHERE id = ?", (OTHER_MISSION, CLAIM))
        with pytest.raises(sqlite3.IntegrityError):
            _event(conn, claim_id=CLAIM)
        _event(conn, kind="OBSERVATIONS_COMMITTED")
        with pytest.raises(sqlite3.IntegrityError):
            _command(conn)


@pytest.mark.asyncio
async def test_setup_on_reopened_canonical_store_never_calls_canonical_initializer(tmp_path, monkeypatch):
    original = SqliteTrendRepository(str(tmp_path / "reopened.sqlite"))
    await original._ensure_schema()
    _seed(original)
    before = _snapshot(original)
    repository = SqliteTrendRepository(original._db_path)

    async def forbidden_canonical_setup():
        raise AssertionError("Progress setup attempted canonical bootstrap")

    monkeypatch.setattr(repository, "_ensure_schema", forbidden_canonical_setup)
    await _install(repository)
    assert not repository._initialized
    assert _snapshot(repository) == before


@pytest.mark.asyncio
async def test_runtime_json_uuid_defaults_and_integer_bounds_are_observed(canonical_repository):
    repository = canonical_repository
    _seed(repository)
    await _install(repository)
    with _connection(repository) as conn:
        observed = tuple(conn.execute("SELECT sqlite_version(), json_valid('[]'), json_type('[]')").fetchone())
        assert observed[1:] == (1, "array")
        print(
            "T009_SQLITE_RUNTIME="
            + json.dumps({"version": observed[0], "json_valid": observed[1], "json_type": observed[2]})
        )
        _event(conn, revision=9223372036854775807, ordinal=2147483647)
        _command(conn, revision=9223372036854775807, ordinal=2147483647, outcome_count=2147483647)
        for field in ("ordinal", "outcome_count"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(f"UPDATE mission_progress_commands SET {field} = 2147483648")
        with pytest.raises(sqlite3.IntegrityError):
            _event(conn, id=OTHER_EVENT, ordinal=2147483648)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE mission_progress_events SET ordinal = 2147483648")
        for revision in (2, 3):
            _insert(
                conn,
                "mission_progress_events",
                dict(
                    mission_id=MISSION,
                    revision=revision,
                    ordinal=1,
                    kind="WORK_STARTED",
                    provenance="HOST_REPORTED",
                    causation_key="start",
                ),
            )
        rows = conn.execute("SELECT id, recorded_at FROM mission_progress_events WHERE revision < 4").fetchall()
        assert len({row[0] for row in rows}) == 2
        assert all(UUID(row[0]).version == 4 and str(UUID(row[0])) == row[0] for row in rows)
        assert all(datetime.fromisoformat(row[1]).utcoffset() is not None for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", ({"provenance": "HOST_REPORTED"}, {"causation_key": KEY[:-1] + "c"}))
async def test_original_receipt_cannot_bind_different_provenance_or_causation(canonical_repository, changes):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        _event(conn, **changes)
        with pytest.raises(sqlite3.IntegrityError):
            _command(conn)


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ("view", "nonprimary", "composite_primary", "missing_mission_column"))
async def test_progress_setup_requires_actual_canonical_fk_targets(layout, tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "invalid-target.sqlite"))
    with _connection(repository) as conn:
        conn.execute("CREATE TABLE research_missions (id TEXT PRIMARY KEY)")
        conn.execute("CREATE TABLE mission_claims (id TEXT PRIMARY KEY, mission_id TEXT)")
        statements = {
            "view": "CREATE VIEW mission_run_journals AS SELECT id, id AS mission_id FROM research_missions",
            "nonprimary": "CREATE TABLE mission_run_journals (id TEXT, mission_id TEXT)",
            "composite_primary": "CREATE TABLE mission_run_journals (id TEXT, mission_id TEXT, PRIMARY KEY(id, mission_id))",
            "missing_mission_column": "CREATE TABLE mission_run_journals (id TEXT PRIMARY KEY)",
        }
        conn.execute(statements[layout])
        conn.commit()
    before = _tables(repository)
    with pytest.raises(RepositoryException):
        await repository._ensure_progress_schema()
    assert _tables(repository) == before
    assert not set(TABLES) & _tables(repository)


@pytest.mark.asyncio
async def test_progress_references_refuse_blob_storage(canonical_repository):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn, pytest.raises(sqlite3.IntegrityError):
        _event(conn, evidence_references=b"[]")


def _nul_parent(conn, table, identity):
    """Keep real FKs satisfiable so syntax refusal cannot be confused with a missing parent."""
    fields = dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (identity,)).fetchone())
    fields["id"] = identity + "\x00hidden"
    if table == "mission_run_journals":
        fields["journal_path"] = "/schema/nul-run"
    if table == "mission_claims":
        fields["client_claim_key"] = "nul-claim"
    _insert(conn, table, fields)
    return fields["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("INSERT", "UPDATE"))
@pytest.mark.parametrize(
    "table,column,identity,parent",
    (
        ("mission_progress_events", "id", EVENT, None),
        ("mission_progress_events", "mission_id", MISSION, "research_missions"),
        ("mission_progress_events", "run_id", RUN, "mission_run_journals"),
        ("mission_progress_events", "claim_id", CLAIM, "mission_claims"),
        ("mission_progress_events", "work_id", OTHER_EVENT, None),
        ("mission_progress_events", "handoff_id", OTHER_EVENT, None),
        ("mission_progress_events", "finding_id", OTHER_EVENT, None),
        ("mission_progress_revisions", "mission_id", MISSION, "research_missions"),
    ),
)
async def test_nul_suffix_direct_uuid_is_refused_on_insert_and_update(
    canonical_repository, operation, table, column, identity, parent
):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        corrupt = _nul_parent(conn, parent, identity) if parent else identity + "\x00hidden"
        if table == "mission_progress_events":
            baseline = {"kind": "WORK_WAITING", "run_id": None, "evidence_references": "[]"}
            if operation == "UPDATE":
                _event(conn, **baseline)
            with pytest.raises(sqlite3.IntegrityError):
                if operation == "INSERT":
                    _event(conn, **{**baseline, column: corrupt})
                else:
                    conn.execute(f"UPDATE mission_progress_events SET {column} = ? WHERE id = ?", (corrupt, EVENT))
        else:
            if operation == "UPDATE":
                conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (?)", (MISSION,))
            with pytest.raises(sqlite3.IntegrityError):
                if operation == "INSERT":
                    conn.execute("INSERT INTO mission_progress_revisions (mission_id) VALUES (?)", (corrupt,))
                else:
                    conn.execute("UPDATE mission_progress_revisions SET mission_id = ?", (corrupt,))
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == (operation == "UPDATE")
        if operation == "UPDATE":
            assert conn.execute(f"SELECT {column} FROM {table}").fetchone()[0] != corrupt


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("INSERT", "UPDATE"))
@pytest.mark.parametrize("field", ("mission_id", "observation_id", "source_id", "qualification_frame_fingerprint"))
async def test_nul_suffix_json_reference_is_refused_on_insert_and_update(canonical_repository, operation, field):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        reference = {**REFERENCE}
        changes = {"kind": "WORK_WAITING", "run_id": None}
        if field == "qualification_frame_fingerprint":
            reference.update(qualification_relation="QUALIFIED_SUPPORT", qualification_frame_fingerprint="a" * 64)
        if field == "mission_id":
            changes["mission_id"] = _nul_parent(conn, "research_missions", MISSION)
            reference["mission_id"] = changes["mission_id"]
        else:
            reference[field] += "\x00hidden"
        corrupt = json.dumps([reference])
        assert "\\u0000hidden" in corrupt
        if operation == "UPDATE":
            _event(conn)
        with pytest.raises(sqlite3.IntegrityError):
            if operation == "INSERT":
                _event(conn, **changes, evidence_references=corrupt)
            else:
                conn.execute(
                    "UPDATE mission_progress_events SET evidence_references = ?, mission_id = ?,"
                    " kind = 'WORK_WAITING', run_id = NULL WHERE id = ?",
                    (corrupt, changes.get("mission_id", MISSION), EVENT),
                )
        assert conn.execute("SELECT count(*) FROM mission_progress_events").fetchone()[0] == (operation == "UPDATE")
        if operation == "UPDATE":
            assert json.loads(
                conn.execute("SELECT evidence_references FROM mission_progress_events").fetchone()[0]
            ) == [REFERENCE]


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("INSERT", "UPDATE"))
async def test_nul_suffix_receipt_fingerprint_is_refused_on_insert_and_update(canonical_repository, operation):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        _event(conn)
        if operation == "UPDATE":
            _command(conn)
        corrupt = "b" * 64 + "\x00hidden"
        with pytest.raises(sqlite3.IntegrityError):
            if operation == "INSERT":
                _command(conn, payload_fingerprint=corrupt)
            else:
                conn.execute("UPDATE mission_progress_commands SET payload_fingerprint = ?", (corrupt,))
        assert conn.execute("SELECT count(*) FROM mission_progress_commands").fetchone()[0] == (operation == "UPDATE")
        if operation == "UPDATE":
            assert conn.execute("SELECT payload_fingerprint FROM mission_progress_commands").fetchone()[0] == "b" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ("INSERT", "UPDATE"))
async def test_nul_suffix_command_key_is_refused_with_matching_receipt(canonical_repository, operation):
    _seed(canonical_repository)
    await _install(canonical_repository)
    with _connection(canonical_repository) as conn:
        corrupt = KEY + "\x00hidden"
        if operation == "INSERT":
            _event(conn, causation_key=corrupt)
        else:
            _event(conn)
            _command(conn)
            _event(conn, id=OTHER_EVENT, ordinal=2, causation_key=corrupt)
        with pytest.raises(sqlite3.IntegrityError):
            if operation == "INSERT":
                _command(conn, command_key=corrupt)
            else:
                conn.execute(
                    "UPDATE mission_progress_commands SET command_key = ?, event_id = ?, ordinal = 2",
                    (corrupt, OTHER_EVENT),
                )
        assert conn.execute("SELECT count(*) FROM mission_progress_commands").fetchone()[0] == (operation == "UPDATE")
        if operation == "UPDATE":
            assert tuple(
                conn.execute("SELECT command_key, event_id, ordinal FROM mission_progress_commands").fetchone()
            ) == (KEY, EVENT, 1)
