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
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'market_lexicons' AND policyname = 'allow_read_market_lexicons'
    ) THEN
        CREATE POLICY allow_read_market_lexicons ON public.market_lexicons
            FOR SELECT TO authenticated, anon USING (true);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'industry_taxonomies' AND policyname = 'allow_read_industry_taxonomies'
    ) THEN
        CREATE POLICY allow_read_industry_taxonomies ON public.industry_taxonomies
            FOR SELECT TO authenticated, anon USING (true);
    END IF;
END $$;
