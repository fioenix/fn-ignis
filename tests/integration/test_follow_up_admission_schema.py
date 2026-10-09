"""T072 additive030 physical integrity and privilege prerequisites, not PostgreSQL admission."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4
import json

import psycopg
from psycopg import sql
import pytest

from ignis.domain.follow_up_admission import OperationalGap, ParentBudget, AssignmentBudget, WorkAuthority, SourceGrant
from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope
from ignis.domain.research_work import ResearchInputBindings
from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
from ignis.application.ports.research_work_port import ResearchWorkCommitReceipt
from ignis.infrastructure.persistence.sqlite_follow_up_admission import encode
from ignis.infrastructure.persistence.sqlite_follow_up_admission_schema import install_admission_schema
from tests.integration.test_mission_follow_up_schema import seed, admit, work_values, schema as base_schema
from tests.integration.conftest import RUNTIME_ROLE

schema = base_schema
ROOT = Path(__file__).resolve().parents[2]
TABLES = (
    "mission_follow_up_gaps",
    "mission_follow_up_parent_budgets",
    "mission_follow_up_assignment_budgets",
    "mission_follow_up_authorities",
    "mission_follow_up_commands",
    "mission_follow_up_reservation_resources",
)


def install(db):
    if db.postgres:
        with psycopg.connect(db.admin_dsn) as conn:
            conn.execute((ROOT / "sql/030_mission_follow_up_admission.sql").read_text())
            for table in TABLES:
                conn.execute(
                    sql.SQL("ALTER TABLE public.{} OWNER TO {}").format(
                        sql.Identifier(table), sql.Identifier(RUNTIME_ROLE)
                    )
                )
            for fn in ("preserve_follow_up_admission_history()", "validate_follow_up_admission_payload()"):
                conn.execute(
                    sql.SQL("ALTER FUNCTION public." + fn + " OWNER TO {}").format(sql.Identifier(RUNTIME_ROLE))
                )
    else:
        install_admission_schema(db.conn)


def support_records(x):
    parent = UUID(x["parent"])
    root_id = uuid4()
    binding_id = uuid4()
    inputs = ResearchInputBindings(
        mission_id=parent,
        manifest_digest="a" * 64,
        brief_digest="b" * 64,
        frame_digest=None,
        observation_ids=(),
        finding_revisions=(),
    )
    gap = OperationalGap(
        gap_id=UUID(x["gap"]), parent_work_id=UUID(x["parent_work"]), inputs=inputs, question="bounded"
    )
    root = ParentBudget(
        budget_id=root_id,
        mission_id=parent,
        manifest_digest="a" * 64,
        brief_digest="b" * 64,
        quota_unit="queries",
        cost_unit="offline_unit",
        quota_ceiling=10,
        cost_ceiling=10,
        resources=(("queries", 10),),
        confirmation_ref="offline-owner",
    )
    binding = AssignmentBudget(
        binding_id=binding_id,
        budget_id=root_id,
        assignment_id=UUID(x["assignment"]),
        epoch=1,
        assignment_version=1,
        assignment_quota=10,
        quota_unit="queries",
        cost_ceiling=10,
        confirmation_ref="offline-owner",
    )
    scope = FollowUpScope(queries=("bounded",), sources=frozenset({"youtube"}))
    work = FollowUpWork(
        work_id=UUID(x["work"]),
        parent_work_id=UUID(x["parent_work"]),
        assignment_id=UUID(x["assignment"]),
        gap_id=gap.gap_id,
        inputs=inputs,
        research_epoch=1,
        assignment_version=1,
        work_version=1,
        brief_revision_id=UUID(x["brief"]),
        approved_scope=scope,
        requested_scope=scope,
        authority_deadline=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    authority = WorkAuthority(
        work=work,
        budget_id=root_id,
        binding_id=binding_id,
        quota_unit="queries",
        cost_unit="offline_unit",
        quota=4,
        cost=6,
        quota_ceiling=10,
        cost_ceiling=10,
        resources=(("queries", 4),),
        sources=(
            SourceGrant(
                source="youtube",
                platform="youtube",
                tier="public_http",
                paid=False,
                plan_digest="c" * 64,
                connector_revision="offline",
                capability_id="offline-public",
                capability_epoch=1,
            ),
        ),
        confirmation_ref="offline-owner",
    )
    command = FollowUpFactCommand(
        mission_id=parent, record=root, expected_revision=0, idempotency_key="offline", host_authorized=True
    )
    receipt = ResearchWorkCommitReceipt(
        disposition="APPLIED",
        reason_code=None,
        revision=1,
        work_version=None,
        assignment_version=None,
        receipt_id=uuid4(),
        event_ids=(),
        recorded_at=datetime.now(timezone.utc),
    )
    return {
        TABLES[0]: dict(
            gap_id=x["gap"], parent_mission_id=x["parent"], parent_work_id=x["parent_work"], payload=encode(gap)
        ),
        TABLES[1]: dict(budget_id=str(root_id), parent_mission_id=x["parent"], payload=encode(root)),
        TABLES[2]: dict(
            binding_id=str(binding_id),
            parent_mission_id=x["parent"],
            budget_id=str(root_id),
            assignment_id=x["assignment"],
            epoch=1,
            payload=encode(binding),
        ),
        TABLES[3]: dict(
            work_id=x["work"],
            parent_mission_id=x["parent"],
            gap_id=x["gap"],
            budget_id=str(root_id),
            binding_id=str(binding_id),
            payload=encode(authority),
        ),
        TABLES[4]: dict(
            parent_mission_id=x["parent"],
            operation="FACT",
            command_key="offline",
            fingerprint=command.fingerprint,
            work_id=str(root_id),
            command_payload=encode(command),
            receipt_payload=encode(receipt),
        ),
        TABLES[5]: dict(reservation_id=x["reservation"], resource="queries", allocated=4),
    }


def setup(db):
    x = seed(db)
    db.conn.commit()
    db.install()
    install(db)
    db.insert("mission_follow_up_work", work_values(x))
    db.conn.commit()
    admit(db, x)
    return x, support_records(x)


def test_populated030_reapply_preserves_canonical_and029_rows(schema):
    x, records = setup(schema)
    for table, row in records.items():
        schema.insert(table, row)
    schema.conn.commit()
    before = schema.baseline()
    original = {table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in TABLES}
    history = {
        table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("mission_follow_up_work", "mission_follow_ups", "mission_follow_up_reservations")
    }
    for _ in range(2):
        install(schema)
        assert schema.baseline() == before
        assert {table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in TABLES} == original
        assert {table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in history} == history


@pytest.mark.parametrize("table", TABLES)
def test030_history_cannot_be_updated_or_deleted(schema, table):
    _, records = setup(schema)
    for target, row in records.items():
        schema.insert(target, row)
    schema.conn.commit()
    column = next(iter(records[table]))
    for statement in (f"UPDATE {table} SET {column}={column}", f"DELETE FROM {table}"):
        with schema.rejected("check"):
            schema.execute(statement)


@pytest.mark.parametrize("control", ["scalar", "foreign", "negative", "huge"])
def test030_direct_payload_identity_and_finite_negative_controls(schema, control):
    _, records = setup(schema)
    target = TABLES[1]
    row = records[target].copy()
    if control == "scalar":
        row["payload"] = "[]"
    elif control == "foreign":
        row["budget_id"] = str(uuid4())
    else:
        payload = json.loads(row["payload"])
        payload["fields"]["quota_ceiling"] = -1 if control == "negative" else 2**80
        row["payload"] = json.dumps(payload)
    with schema.rejected("check"):
        schema.insert(target, row)
    assert schema.execute(f"SELECT count(*) FROM {target}").fetchone()[0] == 0


IDENTITY_COMPONENTS = (
    (TABLES[0], "gap_id", ("gap_id", "uuid")),
    (TABLES[1], "budget_id", ("budget_id", "uuid")),
    (TABLES[2], "binding_id", ("binding_id", "uuid")),
    (TABLES[3], "work_id", ("work", "fields", "work_id", "uuid")),
    (TABLES[4], "parent_mission_id", ("mission_id", "uuid")),
    (TABLES[4], "operation", None),
    (TABLES[4], "command_key", None),
    (TABLES[5], "reservation_id", None),
    (TABLES[5], "resource", None),
)


def nullable030_setup(db):
    """Install the actual earlier030 table declarations without transforming rows."""
    from ignis.infrastructure.persistence.sqlite_follow_up_admission_schema import SCHEMA, install_payload_guards

    x = seed(db)
    db.conn.commit()
    db.install()
    db.conn.executescript(SCHEMA.replace("TEXT NOT NULL PRIMARY KEY", "TEXT PRIMARY KEY"))
    install_payload_guards(db.conn)
    db.insert("mission_follow_up_work", work_values(x))
    db.conn.commit()
    admit(db, x)
    return x, support_records(x)


@pytest.mark.parametrize("table,column,path", IDENTITY_COMPONENTS)
@pytest.mark.parametrize("existing", [False, True], ids=["fresh", "installed030"])
def test_sqlite030_refuses_every_null_primary_identity(schema, table, column, path, existing):
    if schema.postgres:
        pytest.skip("SQLite nullable TEXT primary-key compatibility control.")
    _, records = nullable030_setup(schema) if existing else setup(schema)
    if existing:
        install(schema)
    declaration = next(row for row in schema.execute(f"PRAGMA table_info({table})").fetchall() if row[1] == column)
    # Reapply protects nullable old tables via guards; it does not rebuild the declaration.
    assert declaration[3] == (0 if existing and table in TABLES[:4] else 1)
    for dependency in TABLES[: TABLES.index(table)]:
        schema.insert(dependency, records[dependency])
    schema.conn.commit()
    # The otherwise-identical row passes first, so refusal is not masked by another constraint.
    schema.execute("SAVEPOINT positive_control")
    schema.insert(table, records[table])
    assert schema.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    schema.execute("ROLLBACK TO positive_control")
    schema.execute("RELEASE positive_control")
    row = records[table].copy()
    row[column] = None
    if path is not None:
        payload_column = "command_payload" if table == TABLES[4] else "payload"
        payload = json.loads(row[payload_column])
        current = payload["fields"]
        for key in path[:-1]:
            current = current[key]
        current[path[-1]] = None
        row[payload_column] = json.dumps(payload)
    with schema.rejected("notnull"):
        schema.insert(table, row)
    assert schema.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    assert schema.execute(f"SELECT count(*) FROM {table} WHERE {column} IS NULL").fetchone()[0] == 0


def test_sqlite030_reapply_preserves_preexisting_nullable_identity_history(schema):
    if schema.postgres:
        pytest.skip("SQLite old nullable identity preservation control.")
    _, records = nullable030_setup(schema)
    legacy = records[TABLES[0]].copy()
    legacy["gap_id"] = None
    payload = json.loads(legacy["payload"])
    payload["fields"]["gap_id"]["uuid"] = None
    legacy["payload"] = json.dumps(payload)
    schema.insert(TABLES[0], legacy)
    from ignis.infrastructure.persistence.sqlite_follow_up_admission import decode

    with pytest.raises((ValueError, TypeError)):
        decode(legacy["payload"])
    for table, row in records.items():
        schema.insert(table, row)
    schema.conn.commit()
    canonical = schema.baseline()
    tables = (*TABLES, "mission_follow_up_work", "mission_follow_ups", "mission_follow_up_reservations")
    original = {table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables}
    for _ in range(2):
        install(schema)
        assert schema.baseline() == canonical
        assert {table: schema.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall() for table in tables} == original
        with schema.rejected("notnull"):
            schema.insert(TABLES[0], legacy)
        assert schema.execute(f"SELECT count(*) FROM {TABLES[0]} WHERE gap_id IS NULL").fetchone()[0] == 1
