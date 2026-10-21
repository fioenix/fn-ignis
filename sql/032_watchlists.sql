-- Migration: 032_watchlists.sql
-- Description: Watchlists a user follows across runs (Spec 016).
--
-- Additive. It transforms no stored evidence.
--
-- * watchlists names what a user follows inside one research workspace. name_key is the
--   case-folded name the application computes, so uniqueness means the same on SQLite, whose
--   lower() folds ASCII only.
-- * watchlist_versions holds each definition, immutable once written. The application validates
--   the definition and takes its digest; a later version may repeat an earlier digest, as when a
--   user goes back to an earlier definition.
-- * watchlist_runs binds one Attention mission to the version it collected.

CREATE TABLE IF NOT EXISTS public.watchlists (
    -- Caller-bound, like the 028-031 identities: the repository chooses the id.
    id UUID PRIMARY KEY,
    workspace_id UUID NOT NULL REFERENCES public.research_workspaces(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (btrim(name) <> '' AND name = btrim(name)),
    name_key TEXT NOT NULL CHECK (name_key <> ''),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlists_workspace_name_key UNIQUE (workspace_id, name_key)
);

CREATE TABLE IF NOT EXISTS public.watchlist_versions (
    watchlist_id UUID NOT NULL REFERENCES public.watchlists(id) ON DELETE CASCADE,
    version INTEGER NOT NULL CHECK (version >= 1),
    definition JSONB NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
    definition_digest CHAR(64) NOT NULL CHECK (definition_digest ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlist_versions_pkey PRIMARY KEY (watchlist_id, version)
);

CREATE TABLE IF NOT EXISTS public.watchlist_runs (
    mission_id UUID PRIMARY KEY REFERENCES public.research_missions(id) ON DELETE CASCADE,
    watchlist_id UUID NOT NULL,
    version INTEGER NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT watchlist_runs_version_fkey FOREIGN KEY (watchlist_id, version)
        REFERENCES public.watchlist_versions (watchlist_id, version) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_watchlist_runs_watchlist ON public.watchlist_runs (watchlist_id, started_at);

-- A version is what earlier runs collected; changing it would rewrite their history. Deletion stays
-- possible so that removing a workspace or watchlist cascades.
CREATE OR REPLACE FUNCTION refuse_watchlist_version_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'watchlist versions are immutable'
        USING ERRCODE = '23514';
END;
$$;

DROP TRIGGER IF EXISTS refuse_watchlist_version_update ON public.watchlist_versions;
CREATE TRIGGER refuse_watchlist_version_update
BEFORE UPDATE ON public.watchlist_versions
FOR EACH ROW EXECUTE FUNCTION refuse_watchlist_version_update();

-- Owner-only, as every other non-vocabulary table since 021.
DO $$
DECLARE
    t TEXT;
    client_role TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['watchlists', 'watchlist_versions', 'watchlist_runs'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', t);
        FOR client_role IN
            SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
        LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I', t, client_role);
        END LOOP;
    END LOOP;
END $$;
