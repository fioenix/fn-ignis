-- Migration: 024_youtube_quota_ledger.sql
-- Description: Add one shared daily admission ledger for every fn-ignis process using YouTube.
--
-- Google moved search.list into its own daily call bucket in June 2026. Worker and MCP processes
-- share one provider key but previously kept only process-local caches and circuit breakers, so
-- neither could know what the other had already spent. This additive table stores no credential:
-- the owner confirmed that one Google project/key is exclusive to one fn-ignis installation.

CREATE TABLE IF NOT EXISTS youtube_quota_buckets (
    quota_day DATE NOT NULL,
    bucket VARCHAR(30) NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    scheduled_used INTEGER NOT NULL DEFAULT 0,
    exhausted BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT youtube_quota_buckets_pkey PRIMARY KEY (quota_day, bucket),
    CONSTRAINT youtube_quota_buckets_bucket_check CHECK (
        bucket IN ('search_list', 'default_units')
    ),
    CONSTRAINT youtube_quota_buckets_usage_check CHECK (
        used >= 0 AND scheduled_used >= 0 AND scheduled_used <= used
    )
);

ALTER TABLE public.youtube_quota_buckets ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    client_role text;
BEGIN
    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        EXECUTE format('REVOKE ALL ON public.youtube_quota_buckets FROM %I', client_role);
    END LOOP;
END $$;
