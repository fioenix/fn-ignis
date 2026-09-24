-- Migration: 006_supabase_security_hardening.sql
-- Description: Fix Supabase Security Linter issues:
--   1. Fix Security Definer Views (change to security_invoker = true)
--   2. Enable Row Level Security (RLS) on public schema tables
--   3. Add baseline access policies

-- ====================================================================
-- 1. FIX SECURITY DEFINER VIEWS -> SECURITY INVOKER
-- ====================================================================
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'memories') THEN
        ALTER VIEW public.memories SET (security_invoker = true);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'message_runs') THEN
        ALTER VIEW public.message_runs SET (security_invoker = true);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'tool_call_logs') THEN
        ALTER VIEW public.tool_call_logs SET (security_invoker = true);
    END IF;
    IF EXISTS (SELECT 1 FROM pg_views WHERE schemaname = 'public' AND viewname = 'group_members') THEN
        ALTER VIEW public.group_members SET (security_invoker = true);
    END IF;
END $$;

-- ====================================================================
-- 2. ENABLE ROW LEVEL SECURITY (RLS) ON PUBLIC TABLES
-- ====================================================================
ALTER TABLE IF EXISTS public.research_missions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.system_audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.topic_clusters ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.trend_signals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.platform_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.market_lexicons ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.industry_taxonomies ENABLE ROW LEVEL SECURITY;

-- ====================================================================
-- 3. BASELINE POLICIES
-- ====================================================================

-- 3.1 Allow Read-Only access for public taxonomies & lexicons (safe for client queries)
--
-- `authenticated` and `anon` are Supabase's PostgREST roles. A plain PostgreSQL or TimescaleDB
-- server does not have them, and a policy naming a missing role fails the whole script -- which
-- on the Compose initdb path stopped every later migration. The policies therefore name only the
-- roles that exist, through dynamic SQL, because a static CREATE POLICY resolves its role list
-- before any IF could protect it. Where neither role exists no policy is created: RLS stays on,
-- and only the table owner can read. No role is ever created here.
DO $$
DECLARE
    supabase_roles text;
BEGIN
    SELECT string_agg(quote_ident(rolname), ', ' ORDER BY rolname)
      INTO supabase_roles
      FROM pg_roles
     WHERE rolname IN ('authenticated', 'anon');

    IF supabase_roles IS NULL THEN
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'market_lexicons'
          AND policyname = 'allow_read_market_lexicons'
    ) THEN
        EXECUTE format(
            'CREATE POLICY allow_read_market_lexicons ON public.market_lexicons'
            ' FOR SELECT TO %s USING (true)',
            supabase_roles
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'industry_taxonomies'
          AND policyname = 'allow_read_industry_taxonomies'
    ) THEN
        EXECUTE format(
            'CREATE POLICY allow_read_industry_taxonomies ON public.industry_taxonomies'
            ' FOR SELECT TO %s USING (true)',
            supabase_roles
        );
    END IF;
END $$;

-- ====================================================================
-- 4. MOVE EXTENSION vector OUT OF PUBLIC SCHEMA
-- ====================================================================
CREATE SCHEMA IF NOT EXISTS extensions;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension e 
        JOIN pg_namespace n ON e.extnamespace = n.oid 
        WHERE e.extname = 'vector' AND n.nspname = 'public'
    ) THEN
        ALTER EXTENSION vector SET SCHEMA extensions;
    END IF;
END $$;

-- ====================================================================
-- 5. HARDEN SECURITY DEFINER RPC FUNCTION (match_memories)
-- ====================================================================
DO $$
DECLARE
    client_role text;
BEGIN
    -- Revoke EXECUTE from PUBLIC everywhere, so no client role reaches a public-schema function
    -- through the PostgREST API by default.
    EXECUTE 'REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC';

    -- Supabase also grants EXECUTE to its client roles directly, which the PUBLIC revoke does not
    -- remove. Both are revoked, signed-in users included: an RPC exception for `authenticated`
    -- would be a decision to record, not a line to leave out. Only roles that exist are named.
    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM %I', client_role);
    END LOOP;

    -- To make match_memories apply RLS as the calling user (SECURITY INVOKER):
    -- ALTER FUNCTION public.match_memories SECURITY INVOKER;
END $$;
