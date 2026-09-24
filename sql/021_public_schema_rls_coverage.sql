-- Migration: 021_public_schema_rls_coverage.sql
-- Description: Give every table the migration chain creates in the public schema an explicit
--   access posture, including the ten tables created after 006.
--
-- 006 could only enable row-level security on the tables that existed when it ran. Supabase grants
-- every new public table to `anon` and `authenticated` by default privilege, so the tables added
-- by later migrations were readable and writable by those client roles. Editing 006 would not
-- reach a database that has already run it; this migration does, and running it again changes
-- nothing.
--
-- Posture, per table class:
--   client read-only vocabulary: market_lexicons, industry_taxonomies. RLS on; the two SELECT
--     policies from 006 are the only access the client roles keep.
--   owner only: every other table. RLS on with no policy, and no client privilege at all.
--
-- RLS alone is not the whole boundary. It does not govern TRUNCATE, and TimescaleDB does not copy
-- the RLS flag onto hypertable chunks, which inherit the hypertable's grants in a schema every
-- role may use. Revoking the client roles' privileges closes both, and a REVOKE on a hypertable
-- reaches its chunks, present and future. This migration only takes privileges away; it grants
-- nothing, so it cannot widen access on a server whose operator granted less than Supabase does.
--
-- Tables are listed rather than discovered, so a database shared with another application keeps
-- that application's tables as they are. tests/integration/test_postgres_rls_coverage.py compares
-- this posture with the catalog and fails on any public table it does not cover.
--
-- Role-dependent statements run only for the roles that exist, and no role is ever created, so
-- plain PostgreSQL and TimescaleDB run this file unchanged. RLS is enabled without FORCE, so the
-- table owner -- the runtime -- keeps reading and writing without a policy.

DO $$
DECLARE
    vocabulary CONSTANT text[] := ARRAY['industry_taxonomies', 'market_lexicons'];
    owner_only CONSTANT text[] := ARRAY[
        -- credentials, runtime configuration and the audit log
        'platform_credentials', 'runtime_configs', 'system_audit_logs',
        -- missions, their evidence, run journals and writer claims
        'research_missions', 'mission_evidence', 'mission_run_journals', 'mission_writer_claims',
        -- research workspaces and Market Brief revisions
        'research_workspaces', 'market_brief_revisions',
        -- canonical sources, observations and the identity-alias ledger
        'sources', 'observations', 'source_identity_aliases',
        -- clusters, and the legacy signal tables kept as migration history
        'topic_clusters', 'trend_signals', 'signal_metrics'
    ];
    table_name text;
    client_role text;
    owned_sequence regclass;
BEGIN
    FOREACH table_name IN ARRAY vocabulary || owner_only LOOP
        EXECUTE format('ALTER TABLE IF EXISTS public.%I ENABLE ROW LEVEL SECURITY', table_name);
    END LOOP;

    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        FOREACH table_name IN ARRAY vocabulary LOOP
            IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
                -- SELECT stays, for the 006 policies; every way of changing the rows goes.
                EXECUTE format(
                    'REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER'
                    ' ON public.%I FROM %I',
                    table_name, client_role
                );
            END IF;
        END LOOP;

        FOREACH table_name IN ARRAY owner_only LOOP
            IF to_regclass(format('public.%I', table_name)) IS NOT NULL THEN
                EXECUTE format('REVOKE ALL ON public.%I FROM %I', table_name, client_role);

                -- A serial column's sequence is granted separately, and UPDATE on it lets a
                -- client move the counter under the runtime's next insert.
                FOR owned_sequence IN
                    SELECT d.objid::regclass
                      FROM pg_depend d
                      JOIN pg_class s ON s.oid = d.objid AND s.relkind = 'S'
                     WHERE d.classid = 'pg_class'::regclass
                       AND d.refclassid = 'pg_class'::regclass
                       AND d.refobjid = to_regclass(format('public.%I', table_name))
                       AND d.deptype IN ('a', 'i')
                LOOP
                    EXECUTE format(
                        'REVOKE ALL ON SEQUENCE %s FROM %I', owned_sequence, client_role
                    );
                END LOOP;
            END IF;
        END LOOP;
    END LOOP;
END $$;
