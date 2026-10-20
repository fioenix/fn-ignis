-- Add only transactional progress state and original command receipts. No canonical evidence
-- is rewritten, and no historical event or revision is fabricated. The mutating adapter locks
-- the mission control row before allocating a revision in its fact/event transaction; readers
-- derive that revision's final ordinal from events in their coherent read transaction.
CREATE TABLE IF NOT EXISTS public.mission_progress_revisions (
    mission_id UUID PRIMARY KEY REFERENCES public.research_missions(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL DEFAULT 0 CHECK (revision >= 0)
);

CREATE TABLE IF NOT EXISTS public.mission_progress_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    revision BIGINT NOT NULL CHECK (revision > 0),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    kind TEXT NOT NULL CHECK (kind IN (
        'COLLECTION_STARTED', 'COLLECTION_STATE_CHANGED', 'PROBE_OUTCOMES_RECORDED', 'OBSERVATIONS_COMMITTED',
        'QUALIFICATION_RECORDED', 'CLAIM_GATE_CHANGED', 'WORK_STARTED', 'WORK_WAITING',
        'HANDOFF_COMMITTED', 'FINDING_REVISED', 'CANCELLATION_REQUESTED',
        'CANCELLATION_ACKNOWLEDGED'
    )),
    provenance TEXT NOT NULL CHECK (provenance IN ('HARNESS_OBSERVED', 'HOST_REPORTED')),
    causation_key TEXT NOT NULL CHECK (length(btrim(causation_key)) > 0),
    occurred_at TIMESTAMPTZ,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_id UUID REFERENCES public.mission_run_journals(id),
    work_id UUID,
    handoff_id UUID,
    finding_id UUID,
    claim_id UUID REFERENCES public.mission_claims(id),
    evidence_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    reason TEXT,
    CONSTRAINT mission_progress_events_position_key UNIQUE (mission_id, revision, ordinal),
    -- The receipt binds identity, position, run, causation and the actual kind/provenance,
    -- rather than trusting a separate caller-supplied copy of the original result.
    CONSTRAINT mission_progress_events_receipt_key UNIQUE (
        mission_id, id, revision, ordinal, run_id, causation_key, kind, provenance
    ),
    CONSTRAINT mission_progress_events_probe_run_check CHECK (
        kind <> 'PROBE_OUTCOMES_RECORDED' OR run_id IS NOT NULL
    )
);

CREATE TABLE IF NOT EXISTS public.mission_progress_commands (
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    command_key TEXT NOT NULL,
    payload_fingerprint TEXT NOT NULL CHECK (payload_fingerprint ~ '^[0-9a-f]{64}$'),
    outcome_count INTEGER NOT NULL CHECK (outcome_count > 0),
    run_id UUID NOT NULL,
    event_id UUID NOT NULL,
    revision BIGINT NOT NULL CHECK (revision > 0),
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    event_kind TEXT NOT NULL DEFAULT 'PROBE_OUTCOMES_RECORDED'
        CHECK (event_kind = 'PROBE_OUTCOMES_RECORDED'),
    event_provenance TEXT NOT NULL DEFAULT 'HARNESS_OBSERVED'
        CHECK (event_provenance = 'HARNESS_OBSERVED'),
    PRIMARY KEY (mission_id, command_key),
    CONSTRAINT mission_progress_commands_key_check CHECK (
        command_key ~ ('^probe-outcomes:' || mission_id::text || ':' || run_id::text || ':[0-9a-f]{64}$')
    ),
    CONSTRAINT mission_progress_commands_event_fkey FOREIGN KEY (
        mission_id, event_id, revision, ordinal, run_id, command_key, event_kind, event_provenance
    ) REFERENCES public.mission_progress_events (
        mission_id, id, revision, ordinal, run_id, causation_key, kind, provenance
    ) ON DELETE CASCADE
);

-- Existing canonical tables have no composite mission/run or mission/claim unique keys.
-- An invoker trigger checks those known scopes without changing them or elevating privileges.
-- Exact reference shape is checked here; canonical membership/source and future work identities
-- remain admission checks inside the later fact/event adapters. References contain no content.
CREATE OR REPLACE FUNCTION public.validate_mission_progress_event()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path = pg_catalog, public AS $$
DECLARE
    referenced_mission UUID;
    reference JSONB;
    uuid_shape CONSTANT TEXT := '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
    reference_keys CONSTANT TEXT[] := ARRAY[
        'mission_id', 'observation_id', 'source_id', 'evidence_role', 'direction',
        'qualification_relation', 'qualification_frame_fingerprint'
    ];
BEGIN
    IF NEW.run_id IS NOT NULL THEN
        SELECT mission_id INTO referenced_mission FROM public.mission_run_journals
            WHERE id = NEW.run_id FOR SHARE;
        IF referenced_mission IS NOT NULL AND referenced_mission <> NEW.mission_id THEN
            RAISE EXCEPTION 'Progress run belongs to another mission' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF NEW.claim_id IS NOT NULL THEN
        SELECT mission_id INTO referenced_mission FROM public.mission_claims
            WHERE id = NEW.claim_id FOR SHARE;
        IF referenced_mission IS NOT NULL AND referenced_mission <> NEW.mission_id THEN
            RAISE EXCEPTION 'Progress claim belongs to another mission' USING ERRCODE = '23514';
        END IF;
    END IF;
    IF jsonb_typeof(NEW.evidence_references) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Progress references must be a typed array' USING ERRCODE = '23514';
    END IF;
    FOR reference IN SELECT value FROM jsonb_array_elements(NEW.evidence_references) LOOP
        IF (jsonb_typeof(reference) = 'object'
            AND reference ?& reference_keys AND reference - reference_keys = '{}'::jsonb
            AND jsonb_typeof(reference->'mission_id') = 'string'
            AND (reference->>'mission_id') ~ uuid_shape
            AND reference->>'mission_id' = NEW.mission_id::text
            AND jsonb_typeof(reference->'observation_id') = 'string'
            AND (reference->>'observation_id') ~ uuid_shape
            AND jsonb_typeof(reference->'source_id') = 'string'
            AND (reference->>'source_id') ~ uuid_shape
            AND reference->>'evidence_role' IN ('MARKET_EVIDENCE', 'ATTENTION_CONTEXT')
            AND (reference->'direction' = 'null'::jsonb
                OR reference->>'direction' IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT'))
            AND ((reference->'qualification_relation' = 'null'::jsonb
                    AND reference->'qualification_frame_fingerprint' = 'null'::jsonb)
                OR (reference->>'qualification_relation' IN (
                        'QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION', 'CONTEXT_ONLY',
                        'EXCLUDED_IRRELEVANT', 'UNASSESSED'
                    ) AND jsonb_typeof(reference->'qualification_frame_fingerprint') = 'string'
                    AND (reference->>'qualification_frame_fingerprint') ~ '^[0-9a-f]{64}$'))
        ) IS NOT TRUE THEN
            RAISE EXCEPTION 'Progress reference has invalid typed fields' USING ERRCODE = '23514';
        END IF;
    END LOOP;
    RETURN NEW;
END $$;

CREATE OR REPLACE TRIGGER mission_progress_events_validate
    BEFORE INSERT OR UPDATE ON public.mission_progress_events
    FOR EACH ROW EXECUTE FUNCTION public.validate_mission_progress_event();

-- Only the existing table-owner runtime may access these tables. RLS has no FORCE or policy;
-- explicit revocation also closes TRUNCATE and inherited PUBLIC privilege bypasses.
ALTER TABLE public.mission_progress_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mission_progress_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mission_progress_commands ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.mission_progress_revisions, public.mission_progress_events,
    public.mission_progress_commands FROM PUBLIC;
REVOKE ALL ON FUNCTION public.validate_mission_progress_event() FROM PUBLIC;
DO $$
DECLARE
    client_role TEXT;
BEGIN
    FOR client_role IN SELECT rolname FROM pg_roles
        WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname LOOP
        EXECUTE format('REVOKE ALL ON public.mission_progress_revisions, '
            'public.mission_progress_events, public.mission_progress_commands FROM %I', client_role);
        EXECUTE format('REVOKE ALL ON FUNCTION public.validate_mission_progress_event() FROM %I', client_role);
    END LOOP;
END $$;
