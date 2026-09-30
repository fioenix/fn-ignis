-- Migration: 025_evidence_grounded_claim_ledger.sql
-- Description: Add mission authority manifests, evidence-frame metadata, and a claim ledger.
--
-- This migration is additive. It does not inspect, promote, rewrite, archive, or delete baseline
-- trend records. Historical Briefs, probe outcomes, and qualifications remain readable as legacy
-- contract rows; the runtime creates a new revision before using them for evidence-grounded
-- analysis.

-- 1. One immutable authority and execution boundary per surfaced mission.
CREATE TABLE IF NOT EXISTS mission_manifests (
    mission_id UUID PRIMARY KEY REFERENCES research_missions(id) ON DELETE CASCADE,
    outcome TEXT NOT NULL,
    decision_context TEXT,
    required_channels TEXT[] NOT NULL,
    optional_channels TEXT[] NOT NULL DEFAULT '{}',
    authority_boundary JSONB NOT NULL,
    quota_budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_type VARCHAR(30) NOT NULL,
    stop_conditions TEXT[] NOT NULL,
    analysis_policy VARCHAR(128) NOT NULL,
    retention_policy TEXT NOT NULL,
    created_by VARCHAR(128) NOT NULL,
    confirmed_at TIMESTAMPTZ NOT NULL,
    manifest_digest VARCHAR(128) NOT NULL,
    CONSTRAINT mission_manifests_digest_key UNIQUE (manifest_digest),
    CONSTRAINT mission_manifests_required_channels_check
        CHECK (cardinality(required_channels) >= 1),
    CONSTRAINT mission_manifests_channel_sets_check
        CHECK (NOT required_channels && optional_channels),
    CONSTRAINT mission_manifests_stop_conditions_check
        CHECK (cardinality(stop_conditions) >= 1),
    CONSTRAINT mission_manifests_output_type_check CHECK (
        output_type IN ('COLLECTION_FRAME', 'ATTENTION_REPORT', 'MARKET_ANALYSIS', 'STRATEGIC_ARTIFACT')
    ),
    CONSTRAINT mission_manifests_authority_object_check
        CHECK (jsonb_typeof(authority_boundary) = 'object'),
    CONSTRAINT mission_manifests_quota_object_check
        CHECK (jsonb_typeof(quota_budget) = 'object'),
    CONSTRAINT mission_manifests_market_context_check CHECK (
        output_type NOT IN ('MARKET_ANALYSIS', 'STRATEGIC_ARTIFACT')
        OR NULLIF(btrim(decision_context), '') IS NOT NULL
    )
);

-- 2. Extend the immutable Market Brief. All five extension fields are either absent together for
-- a legacy row or complete together for the evidence-grounded contract. No historical value is
-- fabricated by the migration.
ALTER TABLE market_brief_revisions
    ADD COLUMN IF NOT EXISTS alternative_hypotheses TEXT[];
ALTER TABLE market_brief_revisions
    ADD COLUMN IF NOT EXISTS null_hypothesis TEXT;
ALTER TABLE market_brief_revisions
    ADD COLUMN IF NOT EXISTS kill_criteria TEXT[];
ALTER TABLE market_brief_revisions
    ADD COLUMN IF NOT EXISTS revision_rule TEXT;
ALTER TABLE market_brief_revisions
    ADD COLUMN IF NOT EXISTS evidence_contract_version SMALLINT NOT NULL DEFAULT 1;

DO $$
BEGIN
    ALTER TABLE market_brief_revisions
        ADD CONSTRAINT market_brief_revisions_evidence_contract_check CHECK (
            (evidence_contract_version = 1
                AND alternative_hypotheses IS NULL
                AND null_hypothesis IS NULL
                AND kill_criteria IS NULL
                AND revision_rule IS NULL)
            OR
            (evidence_contract_version = 2
                AND cardinality(alternative_hypotheses) >= 2
                AND NULLIF(btrim(null_hypothesis), '') IS NOT NULL
                AND cardinality(kill_criteria) >= 1
                AND NULLIF(btrim(revision_rule), '') IS NOT NULL)
        );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- 3. Complete channel outcomes without rewriting historical run results.
ALTER TABLE mission_probe_outcomes
    ADD COLUMN IF NOT EXISTS scope_attestation JSONB;
ALTER TABLE mission_probe_outcomes
    ADD COLUMN IF NOT EXISTS note TEXT;
ALTER TABLE mission_probe_outcomes
    ADD COLUMN IF NOT EXISTS collection_plan_digest VARCHAR(128);
ALTER TABLE mission_probe_outcomes
    ADD COLUMN IF NOT EXISTS evidence_contract_version SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE mission_probe_outcomes
    DROP CONSTRAINT IF EXISTS mission_probe_outcomes_status_check;
ALTER TABLE mission_probe_outcomes
    DROP CONSTRAINT IF EXISTS mission_probe_outcomes_count_check;
ALTER TABLE mission_probe_outcomes
    DROP CONSTRAINT IF EXISTS mission_probe_outcomes_measured_query_check;
ALTER TABLE mission_probe_outcomes
    DROP CONSTRAINT IF EXISTS mission_probe_outcomes_v2_completeness_check;

ALTER TABLE mission_probe_outcomes
    ADD CONSTRAINT mission_probe_outcomes_status_check CHECK (
        status IN (
            'HEALTHY', 'EMPTY_NO_DATA', 'AUTH_REQUIRED', 'RATE_LIMITED', 'DEGRADED',
            'FAILED', 'NOT_REQUESTED'
        )
    );
ALTER TABLE mission_probe_outcomes
    ADD CONSTRAINT mission_probe_outcomes_count_check CHECK (
        signals_collected >= 0
        AND (status = 'HEALTHY') = (signals_collected > 0)
    );
ALTER TABLE mission_probe_outcomes
    ADD CONSTRAINT mission_probe_outcomes_measured_query_check CHECK (
        status <> 'EMPTY_NO_DATA'
        OR cardinality(queried_keywords) >= 1
    );
ALTER TABLE mission_probe_outcomes
    ADD CONSTRAINT mission_probe_outcomes_v2_completeness_check CHECK (
        evidence_contract_version = 1
        OR (
            evidence_contract_version = 2
            AND collection_plan_digest IS NOT NULL
            AND (
                (status IN ('HEALTHY', 'EMPTY_NO_DATA') AND scope_attestation IS NOT NULL)
                OR (status NOT IN ('HEALTHY', 'EMPTY_NO_DATA') AND NULLIF(btrim(note), '') IS NOT NULL)
            )
        )
    );

-- 4. Add contradiction and hypothesis targeting to mission-scoped qualifications.
ALTER TABLE mission_evidence_qualifications
    ADD COLUMN IF NOT EXISTS hypothesis_target VARCHAR(128);
ALTER TABLE mission_evidence_qualifications
    ADD COLUMN IF NOT EXISTS evidence_role VARCHAR(20);
ALTER TABLE mission_evidence_qualifications
    ADD COLUMN IF NOT EXISTS evidence_contract_version SMALLINT NOT NULL DEFAULT 1;

ALTER TABLE mission_evidence_qualifications
    DROP CONSTRAINT IF EXISTS mission_evidence_qualifications_relation_check;
ALTER TABLE mission_evidence_qualifications
    DROP CONSTRAINT IF EXISTS mission_evidence_qualifications_relation_purpose_check;
ALTER TABLE mission_evidence_qualifications
    DROP CONSTRAINT IF EXISTS mission_evidence_qualifications_v2_role_check;

ALTER TABLE mission_evidence_qualifications
    ADD CONSTRAINT mission_evidence_qualifications_relation_check CHECK (
        relation IN (
            'QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION', 'CONTEXT_ONLY',
            'EXCLUDED_IRRELEVANT', 'UNASSESSED'
        )
    );
ALTER TABLE mission_evidence_qualifications
    ADD CONSTRAINT mission_evidence_qualifications_relation_purpose_check CHECK (
        (relation NOT IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION') OR purpose <> 'CONTEXT')
        AND (relation <> 'CONTEXT_ONLY' OR purpose = 'CONTEXT')
    );
ALTER TABLE mission_evidence_qualifications
    ADD CONSTRAINT mission_evidence_qualifications_v2_role_check CHECK (
        (evidence_contract_version = 1
            AND relation <> 'QUALIFIED_CONTRADICTION'
            AND evidence_role IS NULL
            AND hypothesis_target IS NULL)
        OR (
            evidence_contract_version = 2
            AND evidence_role IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT')
            AND (
                (relation = 'QUALIFIED_SUPPORT'
                    AND evidence_role = 'SUPPORT'
                    AND NULLIF(btrim(hypothesis_target), '') IS NOT NULL)
                OR (relation = 'QUALIFIED_CONTRADICTION'
                    AND evidence_role = 'CONTRADICTION'
                    AND NULLIF(btrim(hypothesis_target), '') IS NOT NULL)
                OR (relation NOT IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION'))
            )
        )
    );

-- 5. Persist candidate and permitted analytical statements against one exact evidence frame.
CREATE TABLE IF NOT EXISTS mission_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id UUID NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    brief_revision_id UUID REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
    frame_digest VARCHAR(128) NOT NULL,
    client_claim_key VARCHAR(128) NOT NULL,
    claim_type VARCHAR(30) NOT NULL,
    wording TEXT NOT NULL,
    inference_method VARCHAR(128),
    confidence DOUBLE PRECISION,
    limitations TEXT[] NOT NULL DEFAULT '{}',
    change_conditions TEXT[] NOT NULL DEFAULT '{}',
    status VARCHAR(20) NOT NULL,
    withheld_reasons TEXT[] NOT NULL DEFAULT '{}',
    created_by VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mission_claims_idempotency_key
        UNIQUE (mission_id, frame_digest, client_claim_key),
    CONSTRAINT mission_claims_type_check CHECK (
        claim_type IN ('OBSERVATION', 'MEASUREMENT', 'INFERENCE', 'ASSUMPTION', 'RECOMMENDATION', 'UNKNOWN')
    ),
    CONSTRAINT mission_claims_status_check CHECK (
        status IN ('PERMITTED', 'WITHHELD', 'SUPERSEDED')
    ),
    CONSTRAINT mission_claims_confidence_check CHECK (
        confidence IS NULL OR (confidence >= 0 AND confidence <= 1)
    ),
    CONSTRAINT mission_claims_method_check CHECK (
        claim_type NOT IN ('MEASUREMENT', 'INFERENCE', 'RECOMMENDATION')
        OR NULLIF(btrim(inference_method), '') IS NOT NULL
    ),
    CONSTRAINT mission_claims_change_conditions_check CHECK (
        claim_type NOT IN ('INFERENCE', 'RECOMMENDATION')
        OR (cardinality(limitations) >= 1 AND cardinality(change_conditions) >= 1)
    )
);

CREATE INDEX IF NOT EXISTS idx_mission_claims_current
    ON mission_claims (mission_id, frame_digest, status, created_at);

-- Exactly one evidence identity is present. Partial unique indexes make replay idempotent for
-- either identity without pretending NULL is an identity.
CREATE TABLE IF NOT EXISTS mission_claim_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES mission_claims(id) ON DELETE CASCADE,
    observation_id UUID REFERENCES observations(id) ON DELETE CASCADE,
    probe_outcome_id UUID REFERENCES mission_probe_outcomes(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    hypothesis_target VARCHAR(128),
    CONSTRAINT mission_claim_evidence_identity_check CHECK (
        (observation_id IS NOT NULL)::integer + (probe_outcome_id IS NOT NULL)::integer = 1
    ),
    CONSTRAINT mission_claim_evidence_role_check CHECK (
        role IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT')
    ),
    CONSTRAINT mission_claim_evidence_target_check CHECK (
        role = 'CONTEXT' OR NULLIF(btrim(hypothesis_target), '') IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_claim_evidence_observation
    ON mission_claim_evidence (claim_id, observation_id) WHERE observation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_claim_evidence_outcome
    ON mission_claim_evidence (claim_id, probe_outcome_id) WHERE probe_outcome_id IS NOT NULL;

-- 6. A binding must be evidence for the claim's mission. A bare foreign key to observations
-- proves only that the object exists; it does not establish mission authority. Probe outcomes
-- are eligible only when they record same-mission measured absence under the v2 plan contract.
CREATE OR REPLACE FUNCTION validate_mission_claim_evidence_binding()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM mission_claims c
        JOIN mission_evidence e
          ON e.mission_id = c.mission_id
         AND e.observation_id = NEW.observation_id
        JOIN mission_evidence_qualifications q
          ON q.mission_id = e.mission_id
         AND q.observation_id = e.observation_id
        WHERE c.id = NEW.claim_id
          AND q.evidence_contract_version = 2
          AND (
              (NEW.role = 'SUPPORT'
               AND q.relation = 'QUALIFIED_SUPPORT'
               AND q.evidence_role = 'SUPPORT'
               AND q.hypothesis_target = NEW.hypothesis_target)
              OR (NEW.role = 'CONTRADICTION'
                  AND q.relation = 'QUALIFIED_CONTRADICTION'
                  AND q.evidence_role = 'CONTRADICTION'
                  AND q.hypothesis_target = NEW.hypothesis_target)
              OR (NEW.role = 'CONTEXT'
                  AND q.relation = 'CONTEXT_ONLY'
                  AND q.evidence_role = 'CONTEXT')
          )
    ) THEN
        RAISE EXCEPTION 'claim observation lacks a compatible mission qualification'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.probe_outcome_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM mission_claims c
        JOIN mission_probe_outcomes o ON o.id = NEW.probe_outcome_id
        JOIN mission_run_journals j ON j.id = o.run_id
        WHERE c.id = NEW.claim_id
          AND j.mission_id = c.mission_id
          AND o.status = 'EMPTY_NO_DATA'
          AND o.collection_plan_digest IS NOT NULL
          AND NEW.role = 'SUPPORT'
          AND o.run_id = (
              SELECT latest.id
              FROM mission_run_journals latest
              WHERE latest.mission_id = c.mission_id
                AND latest.status = 'COMPLETED'
              ORDER BY latest.started_at DESC, latest.sequence DESC
              LIMIT 1
          )
    ) THEN
        RAISE EXCEPTION 'claim outcome is not same-mission measured absence'
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS validate_mission_claim_evidence_binding
    ON mission_claim_evidence;
CREATE TRIGGER validate_mission_claim_evidence_binding
BEFORE INSERT ON mission_claim_evidence
FOR EACH ROW EXECUTE FUNCTION validate_mission_claim_evidence_binding();

-- Pruning a mission association revokes that observation only for claims in the same mission.
CREATE OR REPLACE FUNCTION prune_claim_binding_with_mission_evidence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    DELETE FROM mission_claim_evidence b
    USING mission_claims c
    WHERE b.claim_id = c.id
      AND c.mission_id = OLD.mission_id
      AND b.observation_id = OLD.observation_id;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS prune_claim_binding_with_mission_evidence ON mission_evidence;
CREATE TRIGGER prune_claim_binding_with_mission_evidence
AFTER DELETE ON mission_evidence
FOR EACH ROW EXECUTE FUNCTION prune_claim_binding_with_mission_evidence();

-- Once its final supporting binding disappears, a claim remains auditable but is no longer
-- renderable. This also covers an observation or measured-absence row removed by cascade.
CREATE OR REPLACE FUNCTION withhold_claim_without_support()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.role = 'SUPPORT' THEN
        UPDATE mission_claims
        SET status = 'WITHHELD',
            withheld_reasons = ARRAY['EVIDENCE_BINDING_INVALIDATED']
        WHERE id = OLD.claim_id
          AND status = 'PERMITTED'
          AND NOT EXISTS (
              SELECT 1 FROM mission_claim_evidence
              WHERE claim_id = OLD.claim_id AND role = 'SUPPORT'
          );
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS withhold_claim_without_support ON mission_claim_evidence;
CREATE TRIGGER withhold_claim_without_support
AFTER DELETE ON mission_claim_evidence
FOR EACH ROW EXECUTE FUNCTION withhold_claim_without_support();

-- 7. New canonical tables have the same owner-only posture as the existing evidence tables.
REVOKE ALL ON FUNCTION validate_mission_claim_evidence_binding() FROM PUBLIC;
REVOKE ALL ON FUNCTION prune_claim_binding_with_mission_evidence() FROM PUBLIC;
REVOKE ALL ON FUNCTION withhold_claim_without_support() FROM PUBLIC;

DO $$
DECLARE
    owner_only CONSTANT text[] := ARRAY['mission_manifests', 'mission_claims', 'mission_claim_evidence'];
    trigger_functions CONSTANT text[] := ARRAY[
        'validate_mission_claim_evidence_binding',
        'prune_claim_binding_with_mission_evidence',
        'withhold_claim_without_support'
    ];
    table_name text;
    function_name text;
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
        FOREACH function_name IN ARRAY trigger_functions LOOP
            EXECUTE format('REVOKE ALL ON FUNCTION public.%I() FROM %I', function_name, client_role);
        END LOOP;
    END LOOP;
END $$;
