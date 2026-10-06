-- Additive host-work storage. Immutable references point to canonical observations, never
-- mutable mission_evidence rows. Current eligibility and lifecycle CAS belong to admission.
CREATE TABLE IF NOT EXISTS public.research_assignments (
    assignment_id UUID PRIMARY KEY,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    host_task_ref TEXT NOT NULL CHECK (length(btrim(host_task_ref)) BETWEEN 1 AND 512),
    epoch BIGINT NOT NULL CHECK (epoch > 0),
    actions TEXT[] NOT NULL CHECK (cardinality(actions) BETWEEN 1 AND 100 AND actions <@ ARRAY['ANALYZE','FOLLOW_UP']),
    sources TEXT[] NOT NULL CHECK (cardinality(sources) BETWEEN 1 AND 100),
    deadline TIMESTAMPTZ NOT NULL CHECK (isfinite(deadline)),
    quota_ceiling BIGINT NOT NULL CHECK (quota_ceiling >= 0),
    reserved_usage BIGINT NOT NULL DEFAULT 0 CHECK (reserved_usage >= 0),
    settled_usage BIGINT NOT NULL DEFAULT 0 CHECK (settled_usage >= 0),
    capability TEXT CHECK (capability IS NULL OR length(btrim(capability)) BETWEEN 1 AND 128),
    capability_provenance TEXT NOT NULL DEFAULT 'HOST_REPORTED' CHECK (capability_provenance = 'HOST_REPORTED'),
    expected_manifest_digest TEXT NOT NULL CHECK (expected_manifest_digest ~ '^[0-9a-f]{64}$'),
    expected_brief_revision_id UUID REFERENCES public.market_brief_revisions(id),
    state TEXT NOT NULL CHECK (state IN ('ASSIGNED','ACTIVE','CANCEL_PENDING','COMPLETED','CANCELLED','FAILED','INSUFFICIENT_EVIDENCE','EXPIRED','INTERRUPTED')),
    version BIGINT NOT NULL CHECK (version > 0),
    reason TEXT,
    UNIQUE (mission_id, epoch),
    UNIQUE (mission_id, assignment_id, epoch),
    CHECK (reserved_usage + settled_usage <= quota_ceiling)
);
CREATE TABLE IF NOT EXISTS public.research_input_sets (
    input_id UUID PRIMARY KEY,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    manifest_digest TEXT NOT NULL CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    brief_digest TEXT CHECK (brief_digest ~ '^[0-9a-f]{64}$'),
    frame_digest TEXT CHECK (frame_digest ~ '^[0-9a-f]{64}$'),
    UNIQUE (mission_id, input_id)
);
-- This additive identity index changes no canonical values and lets the historical FK
-- prevent a bound observation from being silently reparented to another source.
CREATE UNIQUE INDEX IF NOT EXISTS research_observation_source_identity
    ON public.observations(id, source_id);
CREATE TABLE IF NOT EXISTS public.research_input_observations (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    input_id UUID NOT NULL,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    observation_id UUID NOT NULL REFERENCES public.observations(id),
    source_id UUID NOT NULL REFERENCES public.sources(id),
    UNIQUE (input_id, ordinal),
    PRIMARY KEY (input_id, observation_id),
    FOREIGN KEY (observation_id, source_id) REFERENCES public.observations(id, source_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES public.research_input_sets(mission_id, input_id)
);
CREATE TABLE IF NOT EXISTS public.research_work_items (
    work_id UUID PRIMARY KEY,
    assignment_id UUID NOT NULL,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    input_id UUID NOT NULL,
    run_id UUID REFERENCES public.mission_run_journals(id),
    question TEXT NOT NULL CHECK (length(btrim(question)) BETWEEN 1 AND 4096),
    expertise TEXT NOT NULL CHECK (length(btrim(expertise)) BETWEEN 1 AND 4096),
    assignee_ref TEXT CHECK (assignee_ref IS NULL OR length(btrim(assignee_ref)) BETWEEN 1 AND 512),
    epoch BIGINT NOT NULL CHECK (epoch > 0),
    state TEXT NOT NULL CHECK (state IN ('ASSIGNED','RUNNING','WAITING','CANCEL_PENDING','HANDOFF_READY','COMPLETED','CANCELLED','FAILED','INSUFFICIENT_EVIDENCE','EXPIRED','INTERRUPTED')),
    version BIGINT NOT NULL CHECK (version > 0),
    ownership_fence TEXT NOT NULL CHECK (length(btrim(ownership_fence)) BETWEEN 1 AND 256),
    reason TEXT,
    FOREIGN KEY (mission_id, assignment_id, epoch) REFERENCES public.research_assignments(mission_id, assignment_id, epoch),
    FOREIGN KEY (mission_id, input_id) REFERENCES public.research_input_sets(mission_id, input_id),
    UNIQUE (mission_id, work_id),
    UNIQUE (mission_id, work_id, input_id)
);
CREATE TABLE IF NOT EXISTS public.research_work_dependencies (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    dependency_work_id UUID NOT NULL,
    UNIQUE (work_id, ordinal),
    PRIMARY KEY (work_id, dependency_work_id),
    FOREIGN KEY (mission_id, work_id) REFERENCES public.research_work_items(mission_id, work_id),
    FOREIGN KEY (mission_id, dependency_work_id) REFERENCES public.research_work_items(mission_id, work_id),
    CHECK (work_id <> dependency_work_id)
);
CREATE TABLE IF NOT EXISTS public.research_handoffs (
    handoff_id UUID PRIMARY KEY,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    input_id UUID NOT NULL,
    expected_version BIGINT NOT NULL CHECK (expected_version >= 0),
    ownership_fence TEXT NOT NULL CHECK (length(btrim(ownership_fence)) BETWEEN 1 AND 256),
    consumer_ref TEXT NOT NULL CHECK (length(btrim(consumer_ref)) BETWEEN 1 AND 512),
    result TEXT NOT NULL CHECK (length(btrim(result)) BETWEEN 1 AND 4096),
    limitations TEXT[] NOT NULL DEFAULT '{}',
    open_questions TEXT[] NOT NULL DEFAULT '{}',
    occurred_at TIMESTAMPTZ CHECK (isfinite(occurred_at)),
    -- Submitted identity is retained verbatim; actual transaction time is separate metadata.
    submitted_recorded_at TIMESTAMPTZ CHECK (isfinite(submitted_recorded_at)),
    FOREIGN KEY (mission_id, work_id, input_id) REFERENCES public.research_work_items(mission_id, work_id, input_id),
    UNIQUE (mission_id, handoff_id),
    UNIQUE (mission_id, handoff_id, work_id, input_id)
);
CREATE TABLE IF NOT EXISTS public.research_handoff_references (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    handoff_id UUID NOT NULL,
    reference_kind TEXT NOT NULL CHECK (reference_kind IN ('OUTCOME','CLAIM')),
    reference_id UUID NOT NULL,
    claim_id UUID REFERENCES public.mission_claims(id),
    outcome_id UUID REFERENCES public.mission_probe_outcomes(id),
    CHECK ((reference_kind='CLAIM' AND claim_id IS NOT NULL AND reference_id=claim_id AND outcome_id IS NULL)
        OR (reference_kind='OUTCOME' AND outcome_id IS NOT NULL AND reference_id=outcome_id AND claim_id IS NULL)),
    UNIQUE (handoff_id, reference_kind, ordinal),
    PRIMARY KEY (handoff_id, reference_kind, reference_id),
    FOREIGN KEY (mission_id, handoff_id) REFERENCES public.research_handoffs(mission_id, handoff_id)
);
CREATE TABLE IF NOT EXISTS public.research_finding_revisions (
    handoff_ordinal INTEGER NOT NULL DEFAULT 1 CHECK (handoff_ordinal BETWEEN 1 AND 1000),
    finding_id UUID NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    predecessor_revision BIGINT,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    handoff_id UUID NOT NULL,
    input_id UUID NOT NULL,
    result_type TEXT NOT NULL CHECK (result_type IN ('DESCRIPTIVE','STRATEGIC_CANDIDATE')),
    statement TEXT NOT NULL CHECK (length(btrim(statement)) BETWEEN 1 AND 4096),
    limitations TEXT[] NOT NULL DEFAULT '{}',
    open_questions TEXT[] NOT NULL DEFAULT '{}',
    alternative_explanation TEXT,
    claim_id UUID REFERENCES public.mission_claims(id),
    submitted_recorded_at TIMESTAMPTZ CHECK (isfinite(submitted_recorded_at)),
    PRIMARY KEY (finding_id, revision),
    UNIQUE (handoff_id, handoff_ordinal),
    UNIQUE (handoff_id, finding_id),
    UNIQUE (mission_id, finding_id, revision),
    FOREIGN KEY (mission_id, handoff_id, work_id, input_id) REFERENCES public.research_handoffs(mission_id, handoff_id, work_id, input_id),
    FOREIGN KEY (mission_id, finding_id, predecessor_revision) REFERENCES public.research_finding_revisions(mission_id, finding_id, revision),
    CHECK ((revision = 1 AND predecessor_revision IS NULL) OR (revision > 1 AND predecessor_revision IS NOT NULL AND predecessor_revision = revision - 1))
);
CREATE TABLE IF NOT EXISTS public.research_input_findings (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    input_id UUID NOT NULL,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    finding_id UUID NOT NULL,
    revision BIGINT NOT NULL,
    UNIQUE (input_id, ordinal),
    PRIMARY KEY (input_id, finding_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES public.research_input_sets(mission_id, input_id),
    FOREIGN KEY (mission_id, finding_id, revision) REFERENCES public.research_finding_revisions(mission_id, finding_id, revision)
);
CREATE TABLE IF NOT EXISTS public.research_finding_observations (
    ordinal INTEGER NOT NULL DEFAULT 1 CHECK (ordinal BETWEEN 1 AND 1000),
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    finding_id UUID NOT NULL,
    revision BIGINT NOT NULL,
    observation_id UUID NOT NULL REFERENCES public.observations(id),
    direction TEXT NOT NULL CHECK (direction IN ('SUPPORT','CONTRADICTION','CONTEXT')),
    UNIQUE (finding_id, revision, direction, ordinal),
    PRIMARY KEY (finding_id, revision, direction, observation_id),
    FOREIGN KEY (mission_id, finding_id, revision) REFERENCES public.research_finding_revisions(mission_id, finding_id, revision)
);
CREATE TABLE IF NOT EXISTS public.research_activity_receipts (
    receipt_id UUID PRIMARY KEY,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    work_id UUID NOT NULL,
    epoch BIGINT NOT NULL CHECK (epoch > 0),
    ownership_fence TEXT NOT NULL CHECK (length(btrim(ownership_fence)) BETWEEN 1 AND 256),
    execution_ref TEXT NOT NULL CHECK (length(btrim(execution_ref)) BETWEEN 1 AND 512),
    occurred_at TIMESTAMPTZ NOT NULL CHECK (isfinite(occurred_at)),
    fresh_until TIMESTAMPTZ NOT NULL CHECK (isfinite(fresh_until) AND fresh_until > occurred_at),
    provenance TEXT NOT NULL CHECK (provenance = 'HOST_REPORTED'),
    FOREIGN KEY (mission_id, work_id) REFERENCES public.research_work_items(mission_id, work_id)
);
CREATE TABLE IF NOT EXISTS public.research_handoff_acknowledgements (
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    handoff_id UUID PRIMARY KEY,
    input_id UUID NOT NULL,
    consumer_ref TEXT NOT NULL CHECK (length(btrim(consumer_ref)) BETWEEN 1 AND 512),
    expected_version BIGINT NOT NULL CHECK (expected_version >= 0),
    disposition TEXT NOT NULL CHECK (disposition IN ('ACCEPTED','REJECTED')),
    reason_code TEXT,
    FOREIGN KEY (mission_id, handoff_id) REFERENCES public.research_handoffs(mission_id, handoff_id),
    FOREIGN KEY (mission_id, input_id) REFERENCES public.research_input_sets(mission_id, input_id)
);
CREATE TABLE IF NOT EXISTS public.research_recorded_metadata (
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    record_kind TEXT NOT NULL CHECK (record_kind IN ('ASSIGNMENT','WORK','HANDOFF','FINDING')),
    record_id UUID NOT NULL,
    record_version BIGINT NOT NULL CHECK (record_version > 0),
    mission_revision BIGINT NOT NULL CHECK (mission_revision > 0),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() CHECK (isfinite(recorded_at)),
    provenance TEXT NOT NULL DEFAULT 'HARNESS_OBSERVED' CHECK (provenance = 'HARNESS_OBSERVED'),
    PRIMARY KEY (record_kind, record_id, record_version)
);
-- These receipts never reuse collection commands, which require a probe-run identity.
CREATE TABLE IF NOT EXISTS public.research_work_commands (
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    command_key TEXT NOT NULL CHECK (length(btrim(command_key)) BETWEEN 1 AND 256),
    payload_fingerprint TEXT NOT NULL CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    operation TEXT NOT NULL CHECK (operation IN ('ASSIGN_RESEARCH','ASSIGN_WORK','START_WORK','RECORD_ACTIVITY','SUBMIT_HANDOFF','ACK_HANDOFF','WAIT_WORK','RESUME_WORK','REQUEST_CANCEL','ACK_STOP','END_WORK','END_RESEARCH')),
    receipt_id UUID NOT NULL UNIQUE,
    disposition TEXT NOT NULL CHECK (disposition IN ('APPLIED','REFUSED')),
    reason_code TEXT,
    revision BIGINT NOT NULL CHECK (revision >= 0),
    work_version BIGINT CHECK (work_version > 0),
    assignment_version BIGINT CHECK (assignment_version > 0),
    event_ids UUID[] NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT transaction_timestamp() CHECK (isfinite(recorded_at)),
    PRIMARY KEY (mission_id, command_key),
    CHECK (disposition <> 'REFUSED' OR (reason_code IS NOT NULL AND cardinality(event_ids) = 0))
);

CREATE OR REPLACE FUNCTION public.reject_research_history_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    -- Preserve existing owner mission deletion. A direct history edit while its mission
    -- exists remains forbidden; only the canonical root deletion can remove these rows.
    IF TG_OP='DELETE' AND NOT EXISTS (SELECT 1 FROM public.research_missions WHERE id=OLD.mission_id) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Research history is append-only' USING ERRCODE = '23514';
END $$;

-- Work lifecycle fields may evolve, but its submitted identity and input seal cannot.
CREATE OR REPLACE FUNCTION public.preserve_research_work_identity()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        IF NOT EXISTS (SELECT 1 FROM public.research_missions WHERE id=OLD.mission_id) THEN
            RETURN OLD;
        END IF;
        RAISE EXCEPTION 'Live research work identity cannot be deleted' USING ERRCODE='23514';
    END IF;
    IF (to_jsonb(NEW)-ARRAY['state','version','ownership_fence','reason'])
        IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','ownership_fence','reason']) THEN
        RAISE EXCEPTION 'Submitted research work identity is immutable' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER research_work_identity_immutable
    BEFORE UPDATE OR DELETE ON public.research_work_items
    FOR EACH ROW EXECUTE FUNCTION public.preserve_research_work_identity();

CREATE OR REPLACE FUNCTION public.validate_research_reference()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    scoped_mission UUID;
    expected_input UUID;
    maximum_version BIGINT;
    owner_handoff UUID;
    safe_reasons CONSTANT TEXT[] := ARRAY[
        'INPUT_REVISION_MISMATCH','INVALID_REASON_CODE','STORAGE_FAILURE','IDEMPOTENCY_CONFLICT',
        'STALE_REVISION','STALE_EPOCH','STALE_VERSION','STALE_WORK_VERSION','STALE_FENCE',
        'OWNERSHIP_FENCE_MISMATCH','INPUT_IDENTITY_MISMATCH','STALE_DEPENDENCY_REVISION',
        'STALE_INPUT_FRAME','SCOPE_MISMATCH','AUTHORITY_EXPIRED','AUTHORITY_WIDENING',
        'ASSIGNMENT_TERMINAL','CANCELLATION_PENDING','WORK_TERMINAL','ACTION_NOT_GRANTED',
        'UNKNOWN_ASSIGNEE','CAPABILITY_UNAVAILABLE','UNAUTHORIZED_HOST','EXECUTION_RECEIPT_REQUIRED',
        'EXECUTION_RECEIPT_NOT_CURRENT','INVALID_TRANSITION','DEPENDENCY_NOT_READY','INVALID_INPUT'
    ];
BEGIN
    -- Child inserts and metadata finalization acquire the same owner locks, then read
    -- the seal. A waiter must observe the committed seal before admitting any child.
    IF TG_TABLE_NAME='research_work_dependencies' THEN
        PERFORM 1 FROM public.research_work_items WHERE work_id=NEW.work_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM public.research_recorded_metadata
            WHERE record_kind='WORK' AND record_id=NEW.work_id) THEN
            RAISE EXCEPTION 'Finalized research collection is immutable' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME IN ('research_handoff_references','research_finding_revisions') THEN
        PERFORM 1 FROM public.research_handoffs WHERE handoff_id=NEW.handoff_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM public.research_recorded_metadata
            WHERE record_kind='HANDOFF' AND record_id=NEW.handoff_id) THEN
            RAISE EXCEPTION 'Finalized research collection is immutable' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='research_finding_observations' THEN
        SELECT handoff_id INTO owner_handoff FROM public.research_finding_revisions
            WHERE finding_id=NEW.finding_id AND revision=NEW.revision;
        -- Always handoff before finding, including the metadata path below.
        PERFORM 1 FROM public.research_handoffs WHERE handoff_id=owner_handoff FOR UPDATE;
        PERFORM 1 FROM public.research_finding_revisions
            WHERE finding_id=NEW.finding_id AND revision=NEW.revision FOR UPDATE;
        IF EXISTS (SELECT 1 FROM public.research_recorded_metadata
            WHERE (record_kind='HANDOFF' AND record_id=owner_handoff)
                OR (record_kind='FINDING' AND record_id=NEW.finding_id AND record_version=NEW.revision)) THEN
            RAISE EXCEPTION 'Finalized research collection is immutable' USING ERRCODE='23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME IN ('research_input_observations','research_input_findings') THEN
        PERFORM 1 FROM public.research_input_sets WHERE input_id=NEW.input_id FOR UPDATE;
        IF EXISTS (SELECT 1 FROM public.research_work_items WHERE input_id=NEW.input_id) THEN
            RAISE EXCEPTION 'Bound research inputs are immutable' USING ERRCODE='23514';
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'research_input_observations' THEN
        IF NOT EXISTS (SELECT 1 FROM public.observations WHERE id=NEW.observation_id AND source_id=NEW.source_id FOR SHARE)
            OR NOT EXISTS (SELECT 1 FROM public.mission_evidence WHERE mission_id=NEW.mission_id AND observation_id=NEW.observation_id FOR SHARE) THEN
            RAISE EXCEPTION 'Research observation identity or mission scope mismatch' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_assignments' THEN
        IF NEW.expected_brief_revision_id IS NOT NULL THEN
            SELECT mission_id INTO scoped_mission FROM public.market_brief_revisions WHERE id=NEW.expected_brief_revision_id FOR SHARE;
            IF scoped_mission IS DISTINCT FROM NEW.mission_id THEN
                RAISE EXCEPTION 'Research Brief scope mismatch' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'research_work_items' THEN
        PERFORM 1 FROM public.research_input_sets WHERE input_id=NEW.input_id FOR SHARE;
        IF NEW.run_id IS NOT NULL THEN
            SELECT mission_id INTO scoped_mission FROM public.mission_run_journals WHERE id=NEW.run_id FOR SHARE;
            IF scoped_mission IS DISTINCT FROM NEW.mission_id THEN
                RAISE EXCEPTION 'Research run scope mismatch' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'research_handoff_references' THEN
        IF NEW.reference_kind='CLAIM' THEN
            SELECT mission_id INTO scoped_mission FROM public.mission_claims WHERE id=NEW.reference_id FOR SHARE;
        ELSE
            SELECT j.mission_id INTO scoped_mission FROM public.mission_probe_outcomes o
                JOIN public.mission_run_journals j ON j.id=o.run_id WHERE o.id=NEW.reference_id FOR SHARE OF o,j;
        END IF;
        IF scoped_mission IS DISTINCT FROM NEW.mission_id THEN
            RAISE EXCEPTION 'Research outcome or claim scope mismatch' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_finding_revisions' THEN
        IF NEW.claim_id IS NOT NULL THEN
            SELECT mission_id INTO scoped_mission FROM public.mission_claims WHERE id=NEW.claim_id FOR SHARE;
            IF scoped_mission IS DISTINCT FROM NEW.mission_id THEN
                RAISE EXCEPTION 'Research finding claim scope mismatch' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'research_finding_observations' THEN
        SELECT input_id INTO expected_input FROM public.research_finding_revisions
            WHERE finding_id=NEW.finding_id AND revision=NEW.revision AND mission_id=NEW.mission_id;
        IF NOT EXISTS (SELECT 1 FROM public.research_input_observations
            WHERE input_id=expected_input AND observation_id=NEW.observation_id) THEN
            RAISE EXCEPTION 'Finding reference exceeds exact inputs' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_activity_receipts' THEN
        IF NOT EXISTS (SELECT 1 FROM public.research_work_items WHERE work_id=NEW.work_id
            AND mission_id=NEW.mission_id AND epoch=NEW.epoch AND ownership_fence=NEW.ownership_fence) THEN
            RAISE EXCEPTION 'Research activity fence mismatch' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_handoff_acknowledgements' THEN
        IF NEW.reason_code IS NOT NULL AND NOT NEW.reason_code=ANY(safe_reasons) THEN
            RAISE EXCEPTION 'Invalid safe reason code' USING ERRCODE='23514';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM public.research_handoffs WHERE handoff_id=NEW.handoff_id
            AND mission_id=NEW.mission_id AND input_id=NEW.input_id AND consumer_ref=NEW.consumer_ref) THEN
            RAISE EXCEPTION 'Research acknowledgement input mismatch' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_recorded_metadata' THEN
        CASE NEW.record_kind
            WHEN 'ASSIGNMENT' THEN SELECT version INTO maximum_version FROM public.research_assignments WHERE assignment_id=NEW.record_id AND mission_id=NEW.mission_id FOR UPDATE;
            WHEN 'WORK' THEN SELECT version INTO maximum_version FROM public.research_work_items WHERE work_id=NEW.record_id AND mission_id=NEW.mission_id FOR UPDATE;
            WHEN 'HANDOFF' THEN SELECT 1 INTO maximum_version FROM public.research_handoffs WHERE handoff_id=NEW.record_id AND mission_id=NEW.mission_id FOR UPDATE;
            WHEN 'FINDING' THEN
                SELECT handoff_id INTO owner_handoff FROM public.research_finding_revisions
                    WHERE finding_id=NEW.record_id AND revision=NEW.record_version AND mission_id=NEW.mission_id;
                PERFORM 1 FROM public.research_handoffs WHERE handoff_id=owner_handoff FOR UPDATE;
                SELECT revision INTO maximum_version FROM public.research_finding_revisions
                    WHERE finding_id=NEW.record_id AND revision=NEW.record_version AND mission_id=NEW.mission_id FOR UPDATE;
        END CASE;
        IF maximum_version IS NULL OR NEW.record_version>maximum_version
            OR NOT EXISTS (SELECT 1 FROM public.mission_progress_revisions WHERE mission_id=NEW.mission_id AND revision>=NEW.mission_revision)
            OR NEW.recorded_at<>transaction_timestamp() THEN
            RAISE EXCEPTION 'Invalid observed record metadata' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME = 'research_work_commands' THEN
        IF NEW.reason_code IS NOT NULL AND NOT NEW.reason_code=ANY(safe_reasons) THEN
            RAISE EXCEPTION 'Invalid safe reason code' USING ERRCODE='23514';
        END IF;
        IF cardinality(NEW.event_ids)<>(SELECT count(DISTINCT e.id) FROM public.mission_progress_events e
            WHERE e.id=ANY(NEW.event_ids) AND e.mission_id=NEW.mission_id AND e.revision=NEW.revision) THEN
            RAISE EXCEPTION 'Research receipt event identity mismatch' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;

DO $$
DECLARE
    table_name TEXT;
    client_role TEXT;
    tables CONSTANT TEXT[] := ARRAY[
        'research_assignments','research_work_items','research_input_sets','research_input_observations',
        'research_input_findings','research_work_dependencies','research_handoffs','research_handoff_references',
        'research_finding_revisions','research_finding_observations','research_activity_receipts',
        'research_handoff_acknowledgements','research_recorded_metadata','research_work_commands'
    ];
BEGIN
    FOREACH table_name IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', table_name);
        FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I', table_name, client_role);
        END LOOP;
        IF table_name NOT IN ('research_assignments','research_work_items') THEN
            EXECUTE format('CREATE OR REPLACE TRIGGER research_history_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_research_history_mutation()', table_name);
        END IF;
        IF table_name NOT IN ('research_input_sets','research_handoffs') THEN
            EXECUTE format('CREATE OR REPLACE TRIGGER research_reference_validate BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.validate_research_reference()', table_name);
        END IF;
    END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.reject_research_history_mutation(), public.preserve_research_work_identity(), public.validate_research_reference() FROM PUBLIC;
DO $$
DECLARE client_role TEXT;
BEGIN
    FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION public.reject_research_history_mutation(), public.preserve_research_work_identity(), public.validate_research_reference() FROM %I', client_role);
    END LOOP;
END $$;
