-- Migration: 022_builtin_uuid_defaults.sql
-- Description: Default every Ignis UUID primary key to PostgreSQL's built-in gen_random_uuid()
--   instead of uuid-ossp's uuid_generate_v4().
--
-- 001 installs uuid-ossp into public, and 001, 016, 017 and 018 default nine primary keys to its
-- uuid_generate_v4(). 006 then revokes EXECUTE on every public function from PUBLIC, which is the
-- right posture for application RPCs and the wrong dependency for a column default: on an
-- installation where uuid-ossp is in public, a runtime that owns the tables without being a
-- superuser cannot insert a row unless it supplies the id itself.
--
-- gen_random_uuid() is built into PostgreSQL 13 and later, lives in pg_catalog, and is executable
-- by PUBLIC, so the defaults stop depending on a grant the 006 posture withholds. 003 already
-- uses it for market_lexicons and industry_taxonomies. Both generate random version-4 UUIDs, so
-- existing ids and the rows written from now on are the same kind of value.
--
-- Deliberately not done here: no EXECUTE is granted on anything, 006 is not weakened, and
-- uuid-ossp stays installed where it is, for anything outside Ignis that still calls it.
--
-- The tables are listed rather than discovered, so a database shared with another application
-- keeps that application's defaults as they are. SET DEFAULT changes catalog metadata only: it
-- rewrites no rows and holds each table's lock only for the statement. Running this file again
-- sets the same defaults and changes nothing. It must run as the tables' owner, as 021 does.

-- 001: missions and clusters
ALTER TABLE IF EXISTS public.research_missions ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE IF EXISTS public.topic_clusters ALTER COLUMN id SET DEFAULT gen_random_uuid();

-- 016: canonical sources, observations and mission evidence
ALTER TABLE IF EXISTS public.sources ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE IF EXISTS public.observations ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE IF EXISTS public.mission_evidence ALTER COLUMN id SET DEFAULT gen_random_uuid();

-- 017: research workspaces, Market Brief revisions and run journals
ALTER TABLE IF EXISTS public.research_workspaces ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE IF EXISTS public.market_brief_revisions ALTER COLUMN id SET DEFAULT gen_random_uuid();
ALTER TABLE IF EXISTS public.mission_run_journals ALTER COLUMN id SET DEFAULT gen_random_uuid();

-- 018: the identity-alias ledger
ALTER TABLE IF EXISTS public.source_identity_aliases ALTER COLUMN id SET DEFAULT gen_random_uuid();
