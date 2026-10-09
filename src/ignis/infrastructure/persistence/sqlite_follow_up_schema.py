"""Explicit additive SQLite follow-up DDL; never installed by read-only projection."""

SCHEMA = """
-- Additive follow-up storage only. No canonical evidence or lifecycle row is transformed.
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_work_owner_identity
    ON research_work_items(mission_id,work_id,assignment_id,epoch,input_id);
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_brief_owner_identity
    ON market_brief_revisions(mission_id,id);

CREATE TABLE IF NOT EXISTS mission_follow_up_work (
    work_id TEXT NOT NULL CHECK (work_id IS NULL OR (typeof(work_id)='text' AND length(work_id)=36
        AND substr(work_id,9,1)='-' AND substr(work_id,14,1)='-'
        AND substr(work_id,19,1)='-' AND substr(work_id,24,1)='-'
        AND length(replace(work_id,'-',''))=32 AND lower(replace(work_id,'-','')) NOT GLOB '*[^0-9a-f]*')) PRIMARY KEY,
    parent_mission_id TEXT CHECK (parent_mission_id IS NULL OR (typeof(parent_mission_id)='text' AND length(parent_mission_id)=36
        AND substr(parent_mission_id,9,1)='-' AND substr(parent_mission_id,14,1)='-'
        AND substr(parent_mission_id,19,1)='-' AND substr(parent_mission_id,24,1)='-'
        AND length(replace(parent_mission_id,'-',''))=32 AND lower(replace(parent_mission_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    parent_work_id TEXT NOT NULL CHECK (parent_work_id IS NULL OR (typeof(parent_work_id)='text' AND length(parent_work_id)=36
        AND substr(parent_work_id,9,1)='-' AND substr(parent_work_id,14,1)='-'
        AND substr(parent_work_id,19,1)='-' AND substr(parent_work_id,24,1)='-'
        AND length(replace(parent_work_id,'-',''))=32 AND lower(replace(parent_work_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    assignment_id TEXT CHECK (assignment_id IS NULL OR (typeof(assignment_id)='text' AND length(assignment_id)=36
        AND substr(assignment_id,9,1)='-' AND substr(assignment_id,14,1)='-'
        AND substr(assignment_id,19,1)='-' AND substr(assignment_id,24,1)='-'
        AND length(replace(assignment_id,'-',''))=32 AND lower(replace(assignment_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    research_epoch INTEGER NOT NULL CHECK (typeof(research_epoch)='integer' AND research_epoch > 0),
    assignment_version INTEGER NOT NULL CHECK (typeof(assignment_version)='integer' AND assignment_version > 0),
    work_version INTEGER NOT NULL CHECK (typeof(work_version)='integer' AND work_version > 0),
    input_id TEXT CHECK (input_id IS NULL OR (typeof(input_id)='text' AND length(input_id)=36
        AND substr(input_id,9,1)='-' AND substr(input_id,14,1)='-'
        AND substr(input_id,19,1)='-' AND substr(input_id,24,1)='-'
        AND length(replace(input_id,'-',''))=32 AND lower(replace(input_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    brief_revision_id TEXT CHECK (brief_revision_id IS NULL OR (typeof(brief_revision_id)='text' AND length(brief_revision_id)=36
        AND substr(brief_revision_id,9,1)='-' AND substr(brief_revision_id,14,1)='-'
        AND substr(brief_revision_id,19,1)='-' AND substr(brief_revision_id,24,1)='-'
        AND length(replace(brief_revision_id,'-',''))=32 AND lower(replace(brief_revision_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    gap_id TEXT CHECK (gap_id IS NULL OR (typeof(gap_id)='text' AND length(gap_id)=36
        AND substr(gap_id,9,1)='-' AND substr(gap_id,14,1)='-'
        AND substr(gap_id,19,1)='-' AND substr(gap_id,24,1)='-'
        AND length(replace(gap_id,'-',''))=32 AND lower(replace(gap_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    approved_queries TEXT NOT NULL,
    approved_sources TEXT NOT NULL,
    requested_queries TEXT NOT NULL,
    requested_sources TEXT NOT NULL,
    authority_deadline TEXT NOT NULL CHECK (julianday(authority_deadline) IS NOT NULL),
    FOREIGN KEY (parent_mission_id,parent_work_id)
        REFERENCES research_work_items(mission_id,work_id),
    FOREIGN KEY (parent_mission_id,work_id,assignment_id,research_epoch,input_id)
        REFERENCES research_work_items(mission_id,work_id,assignment_id,epoch,input_id),
    FOREIGN KEY (parent_mission_id,brief_revision_id)
        REFERENCES market_brief_revisions(mission_id,id),
    UNIQUE (parent_mission_id,work_id)
);

CREATE TABLE IF NOT EXISTS mission_follow_ups (
    follow_up_id TEXT NOT NULL CHECK (follow_up_id IS NULL OR (typeof(follow_up_id)='text' AND length(follow_up_id)=36
        AND substr(follow_up_id,9,1)='-' AND substr(follow_up_id,14,1)='-'
        AND substr(follow_up_id,19,1)='-' AND substr(follow_up_id,24,1)='-'
        AND length(replace(follow_up_id,'-',''))=32 AND lower(replace(follow_up_id,'-','')) NOT GLOB '*[^0-9a-f]*')) PRIMARY KEY,
    parent_mission_id TEXT CHECK (parent_mission_id IS NULL OR (typeof(parent_mission_id)='text' AND length(parent_mission_id)=36
        AND substr(parent_mission_id,9,1)='-' AND substr(parent_mission_id,14,1)='-'
        AND substr(parent_mission_id,19,1)='-' AND substr(parent_mission_id,24,1)='-'
        AND length(replace(parent_mission_id,'-',''))=32 AND lower(replace(parent_mission_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    child_mission_id TEXT CHECK (child_mission_id IS NULL OR (typeof(child_mission_id)='text' AND length(child_mission_id)=36
        AND substr(child_mission_id,9,1)='-' AND substr(child_mission_id,14,1)='-'
        AND substr(child_mission_id,19,1)='-' AND substr(child_mission_id,24,1)='-'
        AND length(replace(child_mission_id,'-',''))=32 AND lower(replace(child_mission_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL UNIQUE REFERENCES research_missions(id),
    work_id TEXT NOT NULL CHECK (work_id IS NULL OR (typeof(work_id)='text' AND length(work_id)=36
        AND substr(work_id,9,1)='-' AND substr(work_id,14,1)='-'
        AND substr(work_id,19,1)='-' AND substr(work_id,24,1)='-'
        AND length(replace(work_id,'-',''))=32 AND lower(replace(work_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL UNIQUE,
    reservation_id TEXT NOT NULL CHECK (reservation_id IS NULL OR (typeof(reservation_id)='text' AND length(reservation_id)=36
        AND substr(reservation_id,9,1)='-' AND substr(reservation_id,14,1)='-'
        AND substr(reservation_id,19,1)='-' AND substr(reservation_id,24,1)='-'
        AND length(replace(reservation_id,'-',''))=32 AND lower(replace(reservation_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL UNIQUE,
    child_manifest_digest TEXT NOT NULL CHECK (length(child_manifest_digest)=64 AND child_manifest_digest NOT GLOB '*[^0-9a-f]*'),
    child_brief_digest TEXT NOT NULL CHECK (length(child_brief_digest)=64 AND child_brief_digest NOT GLOB '*[^0-9a-f]*'),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 256 AND length(trim(idempotency_key))>0),
    CHECK (parent_mission_id <> child_mission_id),
    FOREIGN KEY (parent_mission_id,work_id)
        REFERENCES mission_follow_up_work(parent_mission_id,work_id),
    UNIQUE (parent_mission_id,idempotency_key),
    UNIQUE (parent_mission_id,child_mission_id,follow_up_id),
    FOREIGN KEY (reservation_id,follow_up_id,parent_mission_id,child_mission_id)
        REFERENCES mission_follow_up_reservations(reservation_id,follow_up_id,parent_mission_id,child_mission_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS mission_follow_up_reservations (
    reservation_id TEXT NOT NULL CHECK (reservation_id IS NULL OR (typeof(reservation_id)='text' AND length(reservation_id)=36
        AND substr(reservation_id,9,1)='-' AND substr(reservation_id,14,1)='-'
        AND substr(reservation_id,19,1)='-' AND substr(reservation_id,24,1)='-'
        AND length(replace(reservation_id,'-',''))=32 AND lower(replace(reservation_id,'-','')) NOT GLOB '*[^0-9a-f]*')) PRIMARY KEY,
    follow_up_id TEXT NOT NULL CHECK (follow_up_id IS NULL OR (typeof(follow_up_id)='text' AND length(follow_up_id)=36
        AND substr(follow_up_id,9,1)='-' AND substr(follow_up_id,14,1)='-'
        AND substr(follow_up_id,19,1)='-' AND substr(follow_up_id,24,1)='-'
        AND length(replace(follow_up_id,'-',''))=32 AND lower(replace(follow_up_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL UNIQUE,
    parent_mission_id TEXT CHECK (parent_mission_id IS NULL OR (typeof(parent_mission_id)='text' AND length(parent_mission_id)=36
        AND substr(parent_mission_id,9,1)='-' AND substr(parent_mission_id,14,1)='-'
        AND substr(parent_mission_id,19,1)='-' AND substr(parent_mission_id,24,1)='-'
        AND length(replace(parent_mission_id,'-',''))=32 AND lower(replace(parent_mission_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    child_mission_id TEXT CHECK (child_mission_id IS NULL OR (typeof(child_mission_id)='text' AND length(child_mission_id)=36
        AND substr(child_mission_id,9,1)='-' AND substr(child_mission_id,14,1)='-'
        AND substr(child_mission_id,19,1)='-' AND substr(child_mission_id,24,1)='-'
        AND length(replace(child_mission_id,'-',''))=32 AND lower(replace(child_mission_id,'-','')) NOT GLOB '*[^0-9a-f]*')) NOT NULL,
    reserved_quota INTEGER NOT NULL CHECK (typeof(reserved_quota)='integer' AND reserved_quota >= 0),
    reserved_cost INTEGER NOT NULL CHECK (typeof(reserved_cost)='integer' AND reserved_cost >= 0),
    measured_quota INTEGER CHECK (measured_quota IS NULL OR (typeof(measured_quota)='integer' AND measured_quota >= 0)),
    measured_cost INTEGER CHECK (measured_cost IS NULL OR (typeof(measured_cost)='integer' AND measured_cost >= 0)),
    measurement_receipt_id TEXT CHECK (measurement_receipt_id IS NULL OR (typeof(measurement_receipt_id)='text' AND length(measurement_receipt_id)=36
        AND substr(measurement_receipt_id,9,1)='-' AND substr(measurement_receipt_id,14,1)='-'
        AND substr(measurement_receipt_id,19,1)='-' AND substr(measurement_receipt_id,24,1)='-'
        AND length(replace(measurement_receipt_id,'-',''))=32 AND lower(replace(measurement_receipt_id,'-','')) NOT GLOB '*[^0-9a-f]*')),
    state TEXT NOT NULL CHECK (state IN ('RESERVED','UNRESOLVED','SETTLED')),
    version INTEGER NOT NULL CHECK (typeof(version)='integer' AND version > 0),
    CHECK ((state='SETTLED' AND measured_quota IS NOT NULL AND measured_cost IS NOT NULL
            AND measurement_receipt_id IS NOT NULL)
        OR (state<>'SETTLED' AND measurement_receipt_id IS NULL)),
    FOREIGN KEY (parent_mission_id,child_mission_id,follow_up_id)
        REFERENCES mission_follow_ups(parent_mission_id,child_mission_id,follow_up_id)
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (reservation_id,follow_up_id,parent_mission_id,child_mission_id)
);

CREATE INDEX IF NOT EXISTS follow_up_reservation_parent_budget ON mission_follow_up_reservations(parent_mission_id,state);
"""


def install_follow_up_schema(conn):
    """Install only on an idle caller connection; execution/admission belong to later tasks."""
    if conn.in_transaction:
        raise ValueError('Follow-up installation requires an idle connection.')
    if conn.execute('PRAGMA foreign_keys').fetchone()[0] != 1:
        raise ValueError('Follow-up installation requires foreign keys.')
    try:
        conn.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
        for column in ('approved_queries', 'requested_queries', 'approved_sources', 'requested_sources'):
            maximum = 128 if column.endswith('sources') else 512
            source = ("OR j.value NOT GLOB '[A-Za-z]*' OR j.value GLOB '*[^A-Za-z0-9_-]*'"
                      if column.endswith('sources') else '')
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS follow_up_scope_{column}
                BEFORE INSERT ON mission_follow_up_work BEGIN
                    SELECT CASE WHEN json_valid(NEW.{column}) IS NOT TRUE
                        THEN RAISE(ABORT,'Invalid bounded follow-up scope') END;
                    SELECT CASE WHEN json_type(NEW.{column}) IS NOT 'array'
                        OR json_array_length(NEW.{column}) NOT BETWEEN 1 AND 100
                        THEN RAISE(ABORT,'Invalid bounded follow-up scope') END;
                    SELECT CASE WHEN EXISTS (
                        SELECT 1 FROM json_each(NEW.{column}) j
                        WHERE j.type<>'text' OR length(j.value) NOT BETWEEN 1 AND {maximum} OR length(trim(j.value))=0 {source}
                        OR EXISTS (WITH RECURSIVE control(c) AS (
                            SELECT 0 UNION ALL SELECT c+1 FROM control WHERE c<31
                        ) SELECT 1 FROM control WHERE instr(j.value,char(c))>0)
                    ) OR (SELECT count(DISTINCT value) FROM json_each(NEW.{column}))
                        <>json_array_length(NEW.{column})
                        THEN RAISE(ABORT,'Invalid bounded follow-up scope') END;
                END
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS follow_up_record_validate BEFORE INSERT ON mission_follow_ups BEGIN
                SELECT CASE WHEN EXISTS (SELECT 1 FROM research_missions WHERE id=NEW.child_mission_id)
                    AND ((SELECT workspace_id FROM research_missions WHERE id=NEW.parent_mission_id) IS NULL
                        OR (SELECT workspace_id FROM research_missions WHERE id=NEW.child_mission_id)
                            IS NOT (SELECT workspace_id FROM research_missions WHERE id=NEW.parent_mission_id))
                    THEN RAISE(ABORT,'Child research ownership mismatch') END;
                SELECT CASE WHEN EXISTS (SELECT 1 FROM mission_follow_up_work w
                    WHERE w.parent_mission_id=NEW.parent_mission_id AND w.work_id=NEW.work_id
                    AND (EXISTS (SELECT value FROM json_each(w.requested_queries)
                                 EXCEPT SELECT value FROM json_each(w.approved_queries))
                        OR EXISTS (SELECT value FROM json_each(w.requested_sources)
                                   EXCEPT SELECT value FROM json_each(w.approved_sources))))
                    THEN RAISE(ABORT,'Admitted follow-up scope exceeds approval') END;
            END
        """)
        tables = ('mission_follow_up_work', 'mission_follow_ups', 'mission_follow_up_reservations')
        mutable = {'state', 'version', 'measured_quota', 'measured_cost', 'measurement_receipt_id'}
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info({table})')]
            identities = [c for c in columns if table != tables[2] or c not in mutable]
            changed = ' OR '.join(f'NEW.{c} IS NOT OLD.{c}' for c in identities)
            if table == tables[2]:
                all_changed = ' OR '.join(f'NEW.{c} IS NOT OLD.{c}' for c in columns)
                changed += f""" OR (OLD.state='SETTLED' AND ({all_changed}))
                    OR (OLD.state='UNRESOLVED' AND NEW.state='RESERVED')
                    OR (OLD.measured_quota IS NOT NULL
                        AND (NEW.measured_quota IS NULL OR NEW.measured_quota<OLD.measured_quota))
                    OR (OLD.measured_cost IS NOT NULL
                        AND (NEW.measured_cost IS NULL OR NEW.measured_cost<OLD.measured_cost))
                    OR (({all_changed}) AND NEW.version<>OLD.version+1)"""
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_update BEFORE UPDATE ON {table}
                WHEN {changed} BEGIN SELECT RAISE(ABORT,'Follow-up identity or reservation transition is immutable'); END
            """)
            conn.execute(f"""
                CREATE TRIGGER IF NOT EXISTS {table}_immutable_delete BEFORE DELETE ON {table}
                WHEN EXISTS (SELECT 1 FROM research_missions WHERE id=OLD.parent_mission_id)
                BEGIN SELECT RAISE(ABORT,'Live follow-up history cannot be deleted'); END
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS follow_up_mission_owner_immutable
            BEFORE UPDATE OF workspace_id ON research_missions
            WHEN NEW.workspace_id IS NOT OLD.workspace_id AND EXISTS (
                SELECT 1 FROM mission_follow_ups WHERE parent_mission_id=OLD.id OR child_mission_id=OLD.id
            ) BEGIN SELECT RAISE(ABORT,'Linked follow-up mission owner is immutable'); END
        """)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
