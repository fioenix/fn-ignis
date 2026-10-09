"""Explicit additive private admission storage; no canonical rows are transformed."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS mission_follow_up_gaps (
 gap_id TEXT NOT NULL PRIMARY KEY, parent_mission_id TEXT NOT NULL REFERENCES research_missions(id),
 parent_work_id TEXT NOT NULL, payload TEXT NOT NULL CHECK(json_valid(payload)),
 FOREIGN KEY(parent_mission_id,parent_work_id) REFERENCES research_work_items(mission_id,work_id),
 UNIQUE(parent_mission_id,gap_id)
);
CREATE TABLE IF NOT EXISTS mission_follow_up_parent_budgets (
 budget_id TEXT NOT NULL PRIMARY KEY,parent_mission_id TEXT NOT NULL UNIQUE REFERENCES research_missions(id),
 payload TEXT NOT NULL CHECK(json_valid(payload)),UNIQUE(parent_mission_id,budget_id)
);
CREATE TABLE IF NOT EXISTS mission_follow_up_assignment_budgets (
 binding_id TEXT NOT NULL PRIMARY KEY,parent_mission_id TEXT NOT NULL,budget_id TEXT NOT NULL,
 assignment_id TEXT NOT NULL,epoch INTEGER NOT NULL CHECK(epoch>0),payload TEXT NOT NULL CHECK(json_valid(payload)),
 FOREIGN KEY(parent_mission_id,budget_id) REFERENCES mission_follow_up_parent_budgets(parent_mission_id,budget_id),
 FOREIGN KEY(parent_mission_id,assignment_id,epoch) REFERENCES research_assignments(mission_id,assignment_id,epoch),
 UNIQUE(parent_mission_id,binding_id),UNIQUE(assignment_id,epoch)
);
CREATE TABLE IF NOT EXISTS mission_follow_up_authorities (
 work_id TEXT NOT NULL PRIMARY KEY,parent_mission_id TEXT NOT NULL,gap_id TEXT NOT NULL,budget_id TEXT NOT NULL,
 binding_id TEXT NOT NULL,payload TEXT NOT NULL CHECK(json_valid(payload)),
 FOREIGN KEY(parent_mission_id,work_id) REFERENCES research_work_items(mission_id,work_id),
 FOREIGN KEY(parent_mission_id,gap_id) REFERENCES mission_follow_up_gaps(parent_mission_id,gap_id),
 FOREIGN KEY(parent_mission_id,budget_id) REFERENCES mission_follow_up_parent_budgets(parent_mission_id,budget_id),
 FOREIGN KEY(parent_mission_id,binding_id) REFERENCES mission_follow_up_assignment_budgets(parent_mission_id,binding_id),
 UNIQUE(parent_mission_id,work_id)
);
CREATE TABLE IF NOT EXISTS mission_follow_up_commands (
 parent_mission_id TEXT NOT NULL REFERENCES research_missions(id),operation TEXT NOT NULL CHECK(operation IN ('FACT','RECORD','ADMIT')),
 command_key TEXT NOT NULL,fingerprint TEXT NOT NULL,work_id TEXT NOT NULL,
 command_payload TEXT NOT NULL CHECK(json_valid(command_payload)),
 receipt_payload TEXT NOT NULL CHECK(json_valid(receipt_payload)),
 PRIMARY KEY(parent_mission_id,operation,command_key)
);
CREATE TABLE IF NOT EXISTS mission_follow_up_reservation_resources (
 reservation_id TEXT NOT NULL REFERENCES mission_follow_up_reservations(reservation_id),
 resource TEXT NOT NULL,allocated INTEGER NOT NULL CHECK(typeof(allocated)='integer' AND allocated>=0),
 PRIMARY KEY(reservation_id,resource)
);
"""


def install_admission_schema(conn):
    if conn.in_transaction:
        raise ValueError("Schema installation requires a separate writer boundary.")
    conn.executescript(SCHEMA)
    # Earlier SQLite030 TEXT primary keys permit NULL. Guard existing tables without
    # rebuilding them or changing unresolved historical rows; fresh DDL is NOT NULL.
    identities = {
        "gaps": ("gap_id",),
        "parent_budgets": ("budget_id",),
        "assignment_budgets": ("binding_id",),
        "authorities": ("work_id",),
        "commands": ("parent_mission_id", "operation", "command_key"),
        "reservation_resources": ("reservation_id", "resource"),
    }
    for name, columns in identities.items():
        table = f"mission_follow_up_{name}"
        condition = " OR ".join(f"NEW.{column} IS NULL" for column in columns)
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_identity_not_null BEFORE INSERT ON {table} "
            f"WHEN {condition} BEGIN SELECT RAISE(ABORT,'Admission identity must not be null'); END"
        )
    for name in ("gaps", "parent_budgets", "assignment_budgets", "authorities", "commands", "reservation_resources"):
        table = f"mission_follow_up_{name}"
        for operation in ("UPDATE", "DELETE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_immutable BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Admission history is immutable'); END"
            )
    install_payload_guards(conn)
    conn.commit()


def install_payload_guards(conn):
    """Index/payload identity and finite values hold even for direct owner inserts."""
    specs = {
        "gaps": (
            "OperationalGap",
            {
                "gap_id": "gap_id.uuid",
                "parent_work_id": "parent_work_id.uuid",
                "parent_mission_id": "inputs.fields.mission_id.uuid",
            },
            (),
        ),
        "parent_budgets": (
            "ParentBudget",
            {"budget_id": "budget_id.uuid", "parent_mission_id": "mission_id.uuid"},
            ("quota_ceiling", "cost_ceiling"),
        ),
        "assignment_budgets": (
            "AssignmentBudget",
            {
                "binding_id": "binding_id.uuid",
                "budget_id": "budget_id.uuid",
                "assignment_id": "assignment_id.uuid",
                "epoch": "epoch",
            },
            ("epoch", "assignment_version", "assignment_quota", "cost_ceiling"),
        ),
        "authorities": (
            "WorkAuthority",
            {
                "work_id": "work.fields.work_id.uuid",
                "gap_id": "work.fields.gap_id.uuid",
                "parent_mission_id": "work.fields.inputs.fields.mission_id.uuid",
                "budget_id": "budget_id.uuid",
                "binding_id": "binding_id.uuid",
            },
            ("quota", "cost", "quota_ceiling", "cost_ceiling"),
        ),
    }
    for name, (kind, bindings, numbers) in specs.items():
        table = f"mission_follow_up_{name}"
        checks = [
            "json_type(NEW.payload) IS NOT 'object'",
            f"json_extract(NEW.payload,'$.type') IS NOT '{kind}'",
            "length(NEW.payload)>1048576",
        ]
        for column, path in bindings.items():
            checks.append(f"json_extract(NEW.payload,'$.fields.{path}') IS NOT NEW.{column}")
        for field in numbers:
            checks.append(
                f"json_type(NEW.payload,'$.fields.{field}') IS NOT 'integer' OR json_extract(NEW.payload,'$.fields.{field}')<0 OR json_extract(NEW.payload,'$.fields.{field}')>9223372036854775807"
            )
        if name != "gaps":
            checks.append(
                "json_type(NEW.payload,'$.fields.confirmation_ref') IS NOT 'text' OR length(trim(json_extract(NEW.payload,'$.fields.confirmation_ref'))) NOT BETWEEN 1 AND 128"
            )
        if name in {"parent_budgets", "authorities"}:
            for unit in ("quota_unit", "cost_unit"):
                checks.append(
                    f"json_type(NEW.payload,'$.fields.{unit}') IS NOT 'text' OR length(trim(json_extract(NEW.payload,'$.fields.{unit}'))) NOT BETWEEN 1 AND 128"
                )
            checks.append(
                "json_type(NEW.payload,'$.fields.resources.tuple') IS NOT 'array' OR json_array_length(NEW.payload,'$.fields.resources.tuple') NOT BETWEEN 1 AND 100"
            )
            checks.append(
                "EXISTS(SELECT 1 FROM json_each(NEW.payload,'$.fields.resources.tuple') r WHERE json_type(r.value,'$.tuple') IS NOT 'array' OR json_array_length(r.value,'$.tuple')<>2 OR json_type(r.value,'$.tuple[0]') IS NOT 'text' OR json_type(r.value,'$.tuple[1]') IS NOT 'integer' OR json_extract(r.value,'$.tuple[1]')<0)"
            )
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS {table}_payload_valid BEFORE INSERT ON {table} WHEN {' OR '.join(checks)} BEGIN SELECT RAISE(ABORT,'Invalid finite admission identity'); END"
        )
    conn.execute("""CREATE TRIGGER IF NOT EXISTS mission_follow_up_commands_payload_valid BEFORE INSERT ON mission_follow_up_commands
      WHEN length(NEW.command_payload)>1048576 OR length(NEW.receipt_payload)>1048576
        OR json_type(NEW.command_payload) IS NOT 'object' OR json_type(NEW.receipt_payload) IS NOT 'object'
        OR (NEW.operation='ADMIT' AND (json_extract(NEW.command_payload,'$.fields.request.fields.mission_id.uuid') IS NOT NEW.parent_mission_id
          OR json_extract(NEW.command_payload,'$.fields.request.fields.follow_up_work_id.uuid') IS NOT NEW.work_id))
        OR (NEW.operation='RECORD' AND (json_extract(NEW.command_payload,'$.fields.work.fields.inputs.fields.mission_id.uuid') IS NOT NEW.parent_mission_id
          OR json_extract(NEW.command_payload,'$.fields.work.fields.work_id.uuid') IS NOT NEW.work_id))
        OR (NEW.operation='FACT' AND json_extract(NEW.command_payload,'$.fields.mission_id.uuid') IS NOT NEW.parent_mission_id)
      BEGIN SELECT RAISE(ABORT,'Invalid original admission command'); END""")
    conn.commit()
