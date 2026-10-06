"""Explicit additive SQLite research DDL; authorized writes alone install it."""

SCHEMA = """
-- Additive host-work storage. Immutable references point to canonical observations, never
-- mutable mission_evidence rows. Current eligibility and lifecycle CAS belong to admission.
CREATE TABLE IF NOT EXISTS research_assignments (
    assignment_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    host_task_ref TEXT NOT NULL CHECK (length(trim(host_task_ref)) BETWEEN 1 AND 512),
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    actions TEXT NOT NULL CHECK (json_valid(actions) AND json_type(actions)='array' AND json_array_length(actions) BETWEEN 1 AND 100),
    sources TEXT NOT NULL CHECK (json_array_length(sources) BETWEEN 1 AND 100),
    deadline TEXT NOT NULL CHECK (julianday(deadline) IS NOT NULL),
    quota_ceiling INTEGER NOT NULL CHECK (quota_ceiling >= 0),
    reserved_usage INTEGER NOT NULL DEFAULT 0 CHECK (reserved_usage >= 0),
    settled_usage INTEGER NOT NULL DEFAULT 0 CHECK (settled_usage >= 0),
    capability TEXT CHECK (capability IS NULL OR length(trim(capability)) BETWEEN 1 AND 128),
    capability_provenance TEXT NOT NULL DEFAULT 'HOST_REPORTED' CHECK (capability_provenance = 'HOST_REPORTED'),
    expected_manifest_digest TEXT NOT NULL CHECK ((length(expected_manifest_digest)=64 AND expected_manifest_digest NOT GLOB '*[^0-9a-f]*')),
    expected_brief_revision_id TEXT REFERENCES market_brief_revisions(id),
    state TEXT NOT NULL CHECK (state IN ('ASSIGNED','ACTIVE','CANCEL_PENDING','COMPLETED','CANCELLED','FAILED','INSUFFICIENT_EVIDENCE','EXPIRED','INTERRUPTED')),
    version INTEGER NOT NULL CHECK (version > 0),
    reason TEXT,
    UNIQUE (mission_id, epoch),
    UNIQUE (mission_id, assignment_id, epoch),
    CHECK (reserved_usage + settled_usage <= quota_ceiling)
);
CREATE TABLE IF NOT EXISTS research_input_sets (
    input_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    manifest_digest TEXT NOT NULL CHECK ((length(manifest_digest)=64 AND manifest_digest NOT GLOB '*[^0-9a-f]*')),
    brief_digest TEXT CHECK ((length(brief_digest)=64 AND brief_digest NOT GLOB '*[^0-9a-f]*')),
    frame_digest TEXT CHECK ((length(frame_digest)=64 AND frame_digest NOT GLOB '*[^0-9a-f]*')),
    UNIQUE (mission_id, input_id)
);
-- This additive identity index changes no canonical values and lets the historical FK
-- prevent a bound observation from being silently reparented to another source.
CREATE UNIQUE INDEX IF NOT EXISTS research_observation_source_identity
    ON observations(id, source_id);
CREATE TABLE IF NOT EXISTS research_input_observations (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    input_id TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES observations(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    UNIQUE (input_id, ordinal),
    PRIMARY KEY (input_id, observation_id),
    FOREIGN KEY (observation_id, source_id) REFERENCES observations(id, source_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES research_input_sets(mission_id, input_id)
);
CREATE TABLE IF NOT EXISTS research_work_items (
    work_id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    input_id TEXT NOT NULL,
    run_id TEXT REFERENCES mission_run_journals(id),
    question TEXT NOT NULL CHECK (length(trim(question)) BETWEEN 1 AND 4096),
    expertise TEXT NOT NULL CHECK (length(trim(expertise)) BETWEEN 1 AND 4096),
    assignee_ref TEXT CHECK (assignee_ref IS NULL OR length(trim(assignee_ref)) BETWEEN 1 AND 512),
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    state TEXT NOT NULL CHECK (state IN ('ASSIGNED','RUNNING','WAITING','CANCEL_PENDING','HANDOFF_READY','COMPLETED','CANCELLED','FAILED','INSUFFICIENT_EVIDENCE','EXPIRED','INTERRUPTED')),
    version INTEGER NOT NULL CHECK (version > 0),
    ownership_fence TEXT NOT NULL CHECK (length(trim(ownership_fence)) BETWEEN 1 AND 256),
    reason TEXT,
    FOREIGN KEY (mission_id, assignment_id, epoch) REFERENCES research_assignments(mission_id, assignment_id, epoch),
    FOREIGN KEY (mission_id, input_id) REFERENCES research_input_sets(mission_id, input_id),
    UNIQUE (mission_id, work_id),
    UNIQUE (mission_id, work_id, input_id)
);
CREATE TABLE IF NOT EXISTS research_work_dependencies (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    dependency_work_id TEXT NOT NULL,
    UNIQUE (work_id, ordinal),
    PRIMARY KEY (work_id, dependency_work_id),
    FOREIGN KEY (mission_id, work_id) REFERENCES research_work_items(mission_id, work_id),
    FOREIGN KEY (mission_id, dependency_work_id) REFERENCES research_work_items(mission_id, work_id),
    CHECK (work_id <> dependency_work_id)
);
CREATE TABLE IF NOT EXISTS research_handoffs (
    handoff_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    input_id TEXT NOT NULL,
    expected_version INTEGER NOT NULL CHECK (expected_version >= 0),
    ownership_fence TEXT NOT NULL CHECK (length(trim(ownership_fence)) BETWEEN 1 AND 256),
    consumer_ref TEXT NOT NULL CHECK (length(trim(consumer_ref)) BETWEEN 1 AND 512),
    result TEXT NOT NULL CHECK (length(trim(result)) BETWEEN 1 AND 4096),
    limitations TEXT NOT NULL DEFAULT '[]',
    open_questions TEXT NOT NULL DEFAULT '[]',
    occurred_at TEXT CHECK (occurred_at IS NULL OR julianday(occurred_at) IS NOT NULL),
    -- Submitted identity is retained verbatim; actual transaction time is separate metadata.
    submitted_recorded_at TEXT CHECK (submitted_recorded_at IS NULL OR julianday(submitted_recorded_at) IS NOT NULL),
    FOREIGN KEY (mission_id, work_id, input_id) REFERENCES research_work_items(mission_id, work_id, input_id),
    UNIQUE (mission_id, handoff_id),
    UNIQUE (mission_id, handoff_id, input_id),
    UNIQUE (mission_id, handoff_id, work_id, input_id)
);
CREATE TABLE IF NOT EXISTS research_handoff_observations (
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    handoff_id TEXT NOT NULL,
    input_id TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (handoff_id, observation_id),
    UNIQUE (handoff_id, ordinal),
    FOREIGN KEY (mission_id, handoff_id, input_id) REFERENCES research_handoffs(mission_id, handoff_id, input_id),
    FOREIGN KEY (input_id, observation_id) REFERENCES research_input_observations(input_id, observation_id),
    FOREIGN KEY (observation_id, source_id) REFERENCES observations(id, source_id)
);
CREATE TABLE IF NOT EXISTS research_handoff_references (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    handoff_id TEXT NOT NULL,
    reference_kind TEXT NOT NULL CHECK (reference_kind IN ('OUTCOME','CLAIM')),
    reference_id TEXT NOT NULL,
    claim_id TEXT REFERENCES mission_claims(id),
    outcome_id TEXT REFERENCES mission_probe_outcomes(id),
    CHECK ((reference_kind='CLAIM' AND claim_id IS NOT NULL AND reference_id=claim_id AND outcome_id IS NULL)
        OR (reference_kind='OUTCOME' AND outcome_id IS NOT NULL AND reference_id=outcome_id AND claim_id IS NULL)),
    UNIQUE (handoff_id, reference_kind, ordinal),
    PRIMARY KEY (handoff_id, reference_kind, reference_id),
    FOREIGN KEY (mission_id, handoff_id) REFERENCES research_handoffs(mission_id, handoff_id)
);
CREATE TABLE IF NOT EXISTS research_finding_revisions (
    handoff_ordinal INTEGER NOT NULL DEFAULT 1 CHECK (handoff_ordinal BETWEEN 1 AND 1000),
    finding_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0),
    predecessor_revision INTEGER,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    handoff_id TEXT NOT NULL,
    input_id TEXT NOT NULL,
    result_type TEXT NOT NULL CHECK (result_type IN ('DESCRIPTIVE','STRATEGIC_CANDIDATE')),
    statement TEXT NOT NULL CHECK (length(trim(statement)) BETWEEN 1 AND 4096),
    limitations TEXT NOT NULL DEFAULT '[]',
    open_questions TEXT NOT NULL DEFAULT '[]',
    alternative_explanation TEXT,
    claim_id TEXT REFERENCES mission_claims(id),
    submitted_recorded_at TEXT CHECK (submitted_recorded_at IS NULL OR julianday(submitted_recorded_at) IS NOT NULL),
    PRIMARY KEY (finding_id, revision),
    UNIQUE (handoff_id, handoff_ordinal),
    UNIQUE (handoff_id, finding_id),
    UNIQUE (mission_id, finding_id, revision),
    FOREIGN KEY (mission_id, handoff_id, work_id, input_id) REFERENCES research_handoffs(mission_id, handoff_id, work_id, input_id),
    FOREIGN KEY (mission_id, finding_id, predecessor_revision) REFERENCES research_finding_revisions(mission_id, finding_id, revision),
    CHECK ((revision = 1 AND predecessor_revision IS NULL) OR (revision > 1 AND predecessor_revision IS NOT NULL AND predecessor_revision = revision - 1))
);
CREATE TABLE IF NOT EXISTS research_input_findings (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    input_id TEXT NOT NULL,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    UNIQUE (input_id, ordinal),
    PRIMARY KEY (input_id, finding_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES research_input_sets(mission_id, input_id),
    FOREIGN KEY (mission_id, finding_id, revision) REFERENCES research_finding_revisions(mission_id, finding_id, revision)
);
CREATE TABLE IF NOT EXISTS research_finding_observations (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    observation_id TEXT NOT NULL REFERENCES observations(id),
    direction TEXT NOT NULL CHECK (direction IN ('SUPPORT','CONTRADICTION','CONTEXT')),
    UNIQUE (finding_id, revision, direction, ordinal),
    PRIMARY KEY (finding_id, revision, direction, observation_id),
    FOREIGN KEY (mission_id, finding_id, revision) REFERENCES research_finding_revisions(mission_id, finding_id, revision)
);
CREATE TABLE IF NOT EXISTS research_activity_receipts (
    receipt_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    work_id TEXT NOT NULL,
    epoch INTEGER NOT NULL CHECK (epoch > 0),
    ownership_fence TEXT NOT NULL CHECK (length(trim(ownership_fence)) BETWEEN 1 AND 256),
    execution_ref TEXT NOT NULL CHECK (length(trim(execution_ref)) BETWEEN 1 AND 512),
    occurred_at TEXT NOT NULL CHECK (occurred_at IS NULL OR julianday(occurred_at) IS NOT NULL),
    fresh_until TEXT NOT NULL CHECK (julianday(fresh_until) IS NOT NULL AND julianday(fresh_until) > julianday(occurred_at)),
    provenance TEXT NOT NULL CHECK (provenance = 'HOST_REPORTED'),
    FOREIGN KEY (mission_id, work_id) REFERENCES research_work_items(mission_id, work_id)
);
CREATE TABLE IF NOT EXISTS research_handoff_acknowledgements (
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    handoff_id TEXT PRIMARY KEY,
    input_id TEXT NOT NULL,
    consumer_ref TEXT NOT NULL CHECK (length(trim(consumer_ref)) BETWEEN 1 AND 512),
    expected_version INTEGER NOT NULL CHECK (expected_version >= 0),
    disposition TEXT NOT NULL CHECK (disposition IN ('ACCEPTED','REJECTED')),
    reason_code TEXT,
    FOREIGN KEY (mission_id, handoff_id) REFERENCES research_handoffs(mission_id, handoff_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES research_input_sets(mission_id, input_id)
);
CREATE TABLE IF NOT EXISTS research_recorded_metadata (
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    record_kind TEXT NOT NULL CHECK (record_kind IN ('ASSIGNMENT','WORK','HANDOFF','FINDING')),
    record_id TEXT NOT NULL,
    record_version INTEGER NOT NULL CHECK (record_version > 0),
    mission_revision INTEGER NOT NULL CHECK (mission_revision > 0),
    recorded_at TEXT NOT NULL DEFAULT (research_transaction_time()) CHECK (julianday(recorded_at) IS NOT NULL),
    provenance TEXT NOT NULL DEFAULT 'HARNESS_OBSERVED' CHECK (provenance = 'HARNESS_OBSERVED'),
    PRIMARY KEY (record_kind, record_id, record_version)
);
-- These receipts never reuse collection commands, which require a probe-run identity.
CREATE TABLE IF NOT EXISTS research_work_commands (
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    command_key TEXT NOT NULL CHECK (length(trim(command_key)) BETWEEN 1 AND 256),
    payload_fingerprint TEXT NOT NULL CHECK ((length(payload_fingerprint)=64 AND payload_fingerprint NOT GLOB '*[^0-9a-f]*')),
    operation TEXT NOT NULL CHECK (operation IN ('ASSIGN_RESEARCH','ASSIGN_WORK','START_WORK','RECORD_ACTIVITY','SUBMIT_HANDOFF','ACK_HANDOFF','WAIT_WORK','RESUME_WORK','REQUEST_CANCEL','ACK_STOP','END_WORK','END_RESEARCH')),
    receipt_id TEXT NOT NULL UNIQUE,
    disposition TEXT NOT NULL CHECK (disposition IN ('APPLIED','REFUSED')),
    reason_code TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    work_version INTEGER CHECK (work_version > 0),
    assignment_version INTEGER CHECK (assignment_version > 0),
    event_ids TEXT NOT NULL DEFAULT '[]',
    recorded_at TEXT NOT NULL DEFAULT (research_transaction_time()) CHECK (julianday(recorded_at) IS NOT NULL),
    PRIMARY KEY (mission_id, command_key),
    CHECK (disposition <> 'REFUSED' OR (reason_code IS NOT NULL AND json_array_length(event_ids) = 0))
);

"""


def install_research_schema(conn):
    """Install explicit tables and equivalent live-history/collection guards."""
    from ignis.application.ports.research_work_port import SAFE_REASONS

    try:
        conn.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        tables = (
            "research_assignments",
            "research_work_items",
            "research_input_sets",
            "research_input_observations",
            "research_input_findings",
            "research_work_dependencies",
            "research_handoffs",
            "research_handoff_references",
            "research_handoff_observations",
            "research_finding_revisions",
            "research_finding_observations",
            "research_activity_receipts",
            "research_handoff_acknowledgements",
            "research_recorded_metadata",
            "research_work_commands",
        )
        uuid_pattern = "-".join("[0-9a-f]" * size for size in (8, 4, 4, 4, 12))
        for table in tables:
            # SQLite affinities are not PostgreSQL types: reject coercion-resistant invalid
            # identities and numerics at the physical boundary, including direct SQL writes.
            checks = []
            for column in conn.execute(f"PRAGMA table_info({table})"):
                name, declared, required = column[1], column[2], column[3]
                if name.endswith("_id"):
                    valid = f"(typeof(NEW.{name})='text' AND instr(NEW.{name},char(0))=0 AND NEW.{name} GLOB '{uuid_pattern}')"
                    checks.append(f"NOT {valid}" if required else f"(NEW.{name} IS NOT NULL AND NOT {valid})")
                elif declared == "INTEGER":
                    checks.append(f"(NEW.{name} IS NOT NULL AND typeof(NEW.{name})<>'integer')")
            condition = " OR ".join(checks)
            if condition:
                for operation in ("INSERT", "UPDATE"):
                    conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_types BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Invalid research physical type'); END"
                    )
        for operation in ("INSERT", "UPDATE"):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS research_assignment_{operation.lower()}_authority BEFORE {operation} ON research_assignments WHEN NOT json_valid(NEW.actions) OR json_type(NEW.actions)<>'array' OR EXISTS (SELECT 1 FROM json_each(NEW.actions) WHERE type<>'text' OR value NOT IN ('ANALYZE','FOLLOW_UP')) OR NOT json_valid(NEW.sources) OR json_type(NEW.sources)<>'array' OR EXISTS (SELECT 1 FROM json_each(NEW.sources) WHERE type<>'text' OR length(value) NOT BETWEEN 1 AND 128) BEGIN SELECT RAISE(ABORT,'Invalid research authority'); END"
            )
        for table in tables:
            if table not in ("research_assignments", "research_work_items"):
                for operation in ("UPDATE", "DELETE"):
                    condition = (
                        "1"
                        if operation == "UPDATE"
                        else "EXISTS (SELECT 1 FROM research_missions WHERE id=OLD.mission_id)"
                    )
                    conn.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_immutable BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Research history is immutable'); END"
                    )
        columns = (
            "work_id",
            "assignment_id",
            "mission_id",
            "input_id",
            "run_id",
            "question",
            "expertise",
            "assignee_ref",
            "epoch",
        )
        changed = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in columns)
        conn.execute(
            f"CREATE TRIGGER IF NOT EXISTS research_work_identity_update BEFORE UPDATE ON research_work_items WHEN {changed} BEGIN SELECT RAISE(ABORT,'Submitted research work identity is immutable'); END"
        )
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS research_work_identity_delete BEFORE DELETE ON research_work_items WHEN EXISTS (SELECT 1 FROM research_missions WHERE id=OLD.mission_id) BEGIN SELECT RAISE(ABORT,'Live research work identity cannot be deleted'); END"
        )
        # SQLite BEGIN IMMEDIATE serializes owner and child writers through settlement.
        seals = {
            "research_input_observations": "EXISTS (SELECT 1 FROM research_work_items WHERE input_id=NEW.input_id)",
            "research_input_findings": "EXISTS (SELECT 1 FROM research_work_items WHERE input_id=NEW.input_id)",
            "research_work_dependencies": "EXISTS (SELECT 1 FROM research_recorded_metadata WHERE record_kind='WORK' AND record_id=NEW.work_id)",
            "research_handoff_observations": "EXISTS (SELECT 1 FROM research_recorded_metadata WHERE record_kind='HANDOFF' AND record_id=NEW.handoff_id)",
            "research_handoff_references": "EXISTS (SELECT 1 FROM research_recorded_metadata WHERE record_kind='HANDOFF' AND record_id=NEW.handoff_id)",
            "research_finding_revisions": "EXISTS (SELECT 1 FROM research_recorded_metadata WHERE record_kind='HANDOFF' AND record_id=NEW.handoff_id)",
            "research_finding_observations": "EXISTS (SELECT 1 FROM research_recorded_metadata m LEFT JOIN research_finding_revisions f ON f.finding_id=NEW.finding_id AND f.revision=NEW.revision WHERE (m.record_kind='HANDOFF' AND m.record_id=f.handoff_id) OR (m.record_kind='FINDING' AND m.record_id=NEW.finding_id AND m.record_version=NEW.revision))",
        }
        for table, condition in seals.items():
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS {table}_seal BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Finalized research collection is immutable'); END"
            )
        guards = {
            "research_input_observations": "NOT EXISTS (SELECT 1 FROM mission_evidence WHERE mission_id=NEW.mission_id AND observation_id=NEW.observation_id)",
            "research_assignments": "NEW.expected_brief_revision_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM market_brief_revisions WHERE id=NEW.expected_brief_revision_id AND mission_id=NEW.mission_id)",
            "research_work_items": "NEW.run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_run_journals WHERE id=NEW.run_id AND mission_id=NEW.mission_id)",
            "research_activity_receipts": "NOT EXISTS (SELECT 1 FROM research_work_items WHERE work_id=NEW.work_id AND mission_id=NEW.mission_id AND epoch=NEW.epoch AND ownership_fence=NEW.ownership_fence)",
            "research_finding_revisions": "NEW.claim_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM mission_claims WHERE id=NEW.claim_id AND mission_id=NEW.mission_id)",
            "research_finding_observations": "NOT EXISTS (SELECT 1 FROM research_finding_revisions f JOIN research_input_observations i ON i.input_id=f.input_id WHERE f.finding_id=NEW.finding_id AND f.revision=NEW.revision AND f.mission_id=NEW.mission_id AND i.observation_id=NEW.observation_id)",
            "research_handoff_references": "(NEW.reference_kind='CLAIM' AND NOT EXISTS (SELECT 1 FROM mission_claims WHERE id=NEW.reference_id AND mission_id=NEW.mission_id)) OR (NEW.reference_kind='OUTCOME' AND NOT EXISTS (SELECT 1 FROM mission_probe_outcomes o JOIN mission_run_journals j ON j.id=o.run_id WHERE o.id=NEW.reference_id AND j.mission_id=NEW.mission_id))",
            "research_handoff_acknowledgements": "NOT EXISTS (SELECT 1 FROM research_handoffs WHERE handoff_id=NEW.handoff_id AND mission_id=NEW.mission_id AND input_id=NEW.input_id AND consumer_ref=NEW.consumer_ref)",
            "research_recorded_metadata": "NEW.recorded_at IS NOT research_transaction_time() OR NOT EXISTS (SELECT 1 FROM mission_progress_revisions WHERE mission_id=NEW.mission_id AND revision>=NEW.mission_revision) OR NOT ((NEW.record_kind='ASSIGNMENT' AND EXISTS (SELECT 1 FROM research_assignments WHERE assignment_id=NEW.record_id AND mission_id=NEW.mission_id AND version>=NEW.record_version)) OR (NEW.record_kind='WORK' AND EXISTS (SELECT 1 FROM research_work_items WHERE work_id=NEW.record_id AND mission_id=NEW.mission_id AND version>=NEW.record_version)) OR (NEW.record_kind='HANDOFF' AND NEW.record_version=1 AND EXISTS (SELECT 1 FROM research_handoffs WHERE handoff_id=NEW.record_id AND mission_id=NEW.mission_id)) OR (NEW.record_kind='FINDING' AND EXISTS (SELECT 1 FROM research_finding_revisions WHERE finding_id=NEW.record_id AND mission_id=NEW.mission_id AND revision=NEW.record_version)))",
            "research_work_commands": "NEW.recorded_at IS NOT research_transaction_time() OR NOT json_valid(NEW.event_ids) OR json_type(NEW.event_ids)<>'array' OR json_array_length(NEW.event_ids)<>(SELECT count(DISTINCT e.id) FROM mission_progress_events e JOIN json_each(NEW.event_ids) j ON j.value=e.id WHERE e.mission_id=NEW.mission_id AND e.revision=NEW.revision)",
        }
        reasons = ",".join("'" + v + "'" for v in sorted(SAFE_REASONS))
        for table in ("research_work_commands", "research_handoff_acknowledgements"):
            guards[table] = (
                "(" + guards[table] + f") OR (NEW.reason_code IS NOT NULL AND NEW.reason_code NOT IN ({reasons}))"
            )
        for table, condition in guards.items():
            for operation in ("INSERT", "UPDATE"):
                conn.execute(
                    f"CREATE TRIGGER IF NOT EXISTS {table}_{operation.lower()}_scope BEFORE {operation} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'Research reference scope mismatch'); END"
                )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
