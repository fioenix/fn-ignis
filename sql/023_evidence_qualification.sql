-- Migration: 023_evidence_qualification.sql
-- Description: Record what each connector surface did during a run, and the semantic judgment a
--   mission made about each observation it holds.
--
-- A valid observation identifier proves that a citation is traceable. It does not prove that the
-- cited observation supports the conclusion: the post-v0.5 validation found traceable citations on
-- films, drama and motivational videos that merely repeated a probe keyword. Two facts close that
-- gap, and both are additive:
--
--   mission_probe_outcomes           one factual result per connector surface per workspace run
--   mission_evidence_qualifications  one semantic judgment per mission-evidence association
--
-- Nothing existing is rewritten and nothing is backfilled. A migration cannot know historical
-- connector health or a judgment nobody made, and inventing either would be fabricated evidence.
-- sources, observations and mission_evidence are unchanged: an observation stays immutable, and
-- whether it supports a question is a property of the question, never of the observation.
--
-- Both tables are owner only, with the posture 021 gives every other runtime table: RLS on with no
-- policy, and no privilege for the Supabase client roles where they exist. Ids default to the
-- built-in gen_random_uuid(), as 022 made every other key do. Running this file again changes
-- nothing.

-- 1. mission_probe_outcomes -- what one connector surface did during one run.
--
-- Zero supply is a measured claim, not the absence of a row: EMPTY_NO_DATA says the surface ran
-- and found nothing for the query named by query_fingerprint, while AUTH_REQUIRED, RATE_LIMITED and
-- DEGRADED say it could not measure at all. Reading current registry health at analysis time would
-- let a reopened report change, so the outcome is recorded against the run that produced it.
--
-- There is no mission_id column. The mission is derived through the run journal; a second foreign
-- key could name a mission different from the run that actually probed.
CREATE TABLE IF NOT EXISTS mission_probe_outcomes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL REFERENCES mission_run_journals(id) ON DELETE CASCADE,
    platform VARCHAR(50) NOT NULL,
    connector_surface VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    signals_collected INTEGER NOT NULL,
    -- A digest of the keywords, geo and timeframe sent to the surface. Never a credential.
    query_fingerprint VARCHAR(128) NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT mission_probe_outcomes_run_surface_key UNIQUE (run_id, connector_surface),
    CONSTRAINT mission_probe_outcomes_status_check CHECK (
        status IN ('HEALTHY', 'EMPTY_NO_DATA', 'AUTH_REQUIRED', 'RATE_LIMITED', 'DEGRADED')
    ),
    -- HEALTHY means signals came back; every other outcome collected none. A failed surface that
    -- claimed a count would make its failure indistinguishable from a partial success.
    CONSTRAINT mission_probe_outcomes_count_check CHECK (
        signals_collected >= 0
        AND (status = 'HEALTHY') = (signals_collected > 0)
    )
);

-- 2. mission_evidence_qualifications -- one mission's judgment of one observation it holds.
--
-- The composite foreign key names the mission_evidence association, so a mission cannot judge an
-- observation it does not hold, and pruning the association removes the judgment with it. The same
-- observation may support one question and be irrelevant to another, which is why the judgment is
-- keyed by mission rather than stored on the observation.
--
-- brief_revision_id is the exact Market frame the judgment was made against; an Attention mission
-- has none. frame_fingerprint is a digest of that immutable frame, not an authorization secret.
-- reason_code is a bounded enum: no prompt transcript or model reasoning is ever stored here.
-- confidence is DOUBLE PRECISION so a byte-equivalent replay compares equal to what was stored.
CREATE TABLE IF NOT EXISTS mission_evidence_qualifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL,
    observation_id UUID NOT NULL,
    brief_revision_id UUID REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
    frame_fingerprint VARCHAR(128) NOT NULL,
    relation VARCHAR(30) NOT NULL,
    purpose VARCHAR(20) NOT NULL,
    confidence DOUBLE PRECISION,
    reason_code VARCHAR(40) NOT NULL,
    judged_by VARCHAR(128) NOT NULL,
    model VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mission_evidence_qualifications_mission_observation_key
        UNIQUE (mission_id, observation_id),
    CONSTRAINT mission_evidence_qualifications_evidence_fkey
        FOREIGN KEY (mission_id, observation_id)
        REFERENCES mission_evidence (mission_id, observation_id) ON DELETE CASCADE,
    CONSTRAINT mission_evidence_qualifications_relation_check CHECK (
        relation IN ('QUALIFIED_SUPPORT', 'CONTEXT_ONLY', 'EXCLUDED_IRRELEVANT', 'UNASSESSED')
    ),
    CONSTRAINT mission_evidence_qualifications_purpose_check CHECK (
        purpose IN ('DEMAND', 'SUPPLY', 'VOC', 'CONTEXT')
    ),
    CONSTRAINT mission_evidence_qualifications_reason_check CHECK (
        reason_code IN (
            'DIRECT_TO_FRAME', 'ADJACENT_ONLY', 'KEYWORD_ONLY', 'WRONG_AUDIENCE_OR_PROBLEM',
            'FICTION_NEWS_OR_ENTERTAINMENT', 'INSUFFICIENT_CONTENT', 'EVALUATOR_UNAVAILABLE'
        )
    ),
    -- Support measures something; context measures nothing.
    CONSTRAINT mission_evidence_qualifications_relation_purpose_check CHECK (
        (relation <> 'QUALIFIED_SUPPORT' OR purpose <> 'CONTEXT')
        AND (relation <> 'CONTEXT_ONLY' OR purpose = 'CONTEXT')
    ),
    -- An unassessed row admits it holds no judgment: no confidence, and a reason saying why.
    CONSTRAINT mission_evidence_qualifications_confidence_check CHECK (
        CASE
            WHEN relation = 'UNASSESSED' THEN
                confidence IS NULL
                AND reason_code IN ('INSUFFICIENT_CONTENT', 'EVALUATOR_UNAVAILABLE')
            ELSE confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1
        END
    )
);

-- 3. Access posture, as 021 states it for every other runtime table.
DO $$
DECLARE
    owner_only CONSTANT text[] := ARRAY['mission_probe_outcomes', 'mission_evidence_qualifications'];
    table_name text;
    client_role text;
BEGIN
    FOREACH table_name IN ARRAY owner_only LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    END LOOP;

    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        FOREACH table_name IN ARRAY owner_only LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I', table_name, client_role);
        END LOOP;
    END LOOP;
END $$;
