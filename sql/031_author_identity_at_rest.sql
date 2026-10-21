-- Migration: 031_author_identity_at_rest.sql
-- Description: Structure for keeping no author identity at rest (Spec 015).
--
-- Additive. It transforms no stored evidence: rows written before it keep their metadata and get
-- NULL author columns, which marks them as legacy. What to do with identity already stored is a
-- separate owner decision (Spec 015 FR-015, OG-3).
--
-- * mission_author_keys holds one random key per mission, Fernet-encrypted with
--   IGNIS_ENCRYPTION_KEY. Author markers are HMACs under it, so a copy of the database alone cannot
--   test a candidate handle against a marker.
-- * mission_declared_accounts holds the accounts a requester declares for one mission, such as a
--   brand's own account. They are the only identities Ignis keeps, and withdrawing one deletes it.
-- * mission_evidence gains the per-mission author facts; observations stay mission-free.
-- * identity_source gains unverifiable_content for an observation with no content reference.

CREATE TABLE IF NOT EXISTS public.mission_author_keys (
    mission_id UUID PRIMARY KEY REFERENCES public.research_missions(id) ON DELETE CASCADE,
    encrypted_key TEXT NOT NULL CHECK (length(encrypted_key) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.mission_declared_accounts (
    -- Caller-bound, like the 028-030 identities: the repository chooses the id.
    id UUID PRIMARY KEY,
    mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    platform VARCHAR(30) NOT NULL CHECK (platform <> '' AND platform = lower(platform)),
    -- A normalised handle (lower case, no leading @) or the platform's account identifier.
    account_key TEXT NOT NULL CHECK (
        account_key <> '' AND account_key = lower(account_key) AND left(account_key, 1) <> '@'
    ),
    declared_name TEXT NOT NULL CHECK (btrim(declared_name) <> ''),
    declared_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT mission_declared_accounts_account_key UNIQUE (mission_id, platform, account_key),
    -- Lets mission_evidence require a declaration from its own mission.
    CONSTRAINT mission_declared_accounts_mission_id_key UNIQUE (mission_id, id)
);

ALTER TABLE public.mission_evidence ADD COLUMN IF NOT EXISTS author_state VARCHAR(12);
ALTER TABLE public.mission_evidence ADD COLUMN IF NOT EXISTS author_marker VARCHAR(16);
ALTER TABLE public.mission_evidence ADD COLUMN IF NOT EXISTS declared_account_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'public.mission_evidence'::regclass AND conname = 'mission_evidence_author_state_check'
    ) THEN
        -- NULL marks a row written before this migration.
        ALTER TABLE public.mission_evidence ADD CONSTRAINT mission_evidence_author_state_check CHECK (
            author_state IS NULL OR author_state IN ('KNOWN', 'UNKNOWN', 'UNAVAILABLE', 'DECLARED')
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'public.mission_evidence'::regclass AND conname = 'mission_evidence_author_marker_check'
    ) THEN
        -- A marker exists exactly when the author is KNOWN, and is 16 lower-case hex characters.
        -- IS NOT DISTINCT FROM keeps a NULL state from passing with a marker, as SQLite's IS does.
        ALTER TABLE public.mission_evidence ADD CONSTRAINT mission_evidence_author_marker_check CHECK (
            (author_state IS NOT DISTINCT FROM 'KNOWN') = (author_marker IS NOT NULL)
            AND (author_marker IS NULL OR author_marker ~ '^[0-9a-f]{16}$')
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'public.mission_evidence'::regclass AND conname = 'mission_evidence_declared_account_check'
    ) THEN
        -- A withdrawn declaration leaves DECLARED with no id; the row then reads as UNKNOWN.
        ALTER TABLE public.mission_evidence ADD CONSTRAINT mission_evidence_declared_account_check CHECK (
            declared_account_id IS NULL OR author_state = 'DECLARED'
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conrelid = 'public.mission_evidence'::regclass AND conname = 'mission_evidence_declared_account_fkey'
    ) THEN
        -- Same mission by construction; withdrawal clears only the declaration reference.
        ALTER TABLE public.mission_evidence ADD CONSTRAINT mission_evidence_declared_account_fkey
            FOREIGN KEY (mission_id, declared_account_id)
            REFERENCES public.mission_declared_accounts (mission_id, id)
            ON DELETE SET NULL (declared_account_id);
    END IF;
END $$;

ALTER TABLE public.observations DROP CONSTRAINT IF EXISTS observations_identity_source_check;
ALTER TABLE public.observations ADD CONSTRAINT observations_identity_source_check CHECK (
    identity_source IN (
        'metadata_external_id', 'url_external_id', 'normalized_url_fallback', 'unverifiable_content'
    )
);

-- Content with no reference anyone could open is context, never support (research R6). The
-- domain refuses a support qualification for it; this refuses the binding, inserted or moved onto
-- such an observation, even when a support row was written around the domain.
CREATE OR REPLACE FUNCTION refuse_unverifiable_claim_support()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.role = 'SUPPORT' AND EXISTS (
        SELECT 1 FROM observations o
        WHERE o.id = NEW.observation_id AND o.identity_source = 'unverifiable_content'
    ) THEN
        RAISE EXCEPTION 'claim support must be content a reader can open'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS refuse_unverifiable_claim_support ON public.mission_claim_evidence;
CREATE TRIGGER refuse_unverifiable_claim_support
BEFORE INSERT OR UPDATE OF role, observation_id ON public.mission_claim_evidence
FOR EACH ROW EXECUTE FUNCTION refuse_unverifiable_claim_support();

-- Owner-only, as every other non-vocabulary table since 021.
DO $$
DECLARE
    t TEXT;
    client_role TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['mission_author_keys', 'mission_declared_accounts'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', t);
        FOR client_role IN
            SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
        LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I', t, client_role);
        END LOOP;
    END LOOP;
END $$;
