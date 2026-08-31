-- 1. Enable Extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- TimescaleDB (Conditional: If available, enable it; otherwise fallback to native Postgres)
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'TimescaleDB extension not available, using native PostgreSQL time-series indexes.';
END $$;

-- 2. Table research_missions (Mission-Driven Targeted Ingress)
CREATE TABLE IF NOT EXISTS research_missions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    platforms TEXT[] NOT NULL DEFAULT '{"google", "youtube", "tiktok", "threads", "reels"}',
    geo_code VARCHAR(10) DEFAULT 'VN',
    timeframe VARCHAR(20) DEFAULT '7d',
    status VARCHAR(30) DEFAULT 'PENDING',  -- 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED'
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Table topic_clusters (Entity / Topic Level)
CREATE TABLE IF NOT EXISTS topic_clusters (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_name TEXT NOT NULL,
    summary_text TEXT,
    category VARCHAR(50) DEFAULT 'general',
    cross_platform_score DOUBLE PRECISION DEFAULT 0,
    embedding vector(384),
    first_seen_at TIMESTAMPTZ DEFAULT NOW(),
    last_updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Table trend_signals (Time-Series Metric Level)
CREATE TABLE IF NOT EXISTS trend_signals (
    id BIGSERIAL,
    mission_id UUID REFERENCES research_missions(id) ON DELETE CASCADE,
    platform VARCHAR(30) NOT NULL,       -- 'youtube', 'google', 'tiktok', 'threads', 'reels'
    raw_title TEXT NOT NULL,             -- Video title, hashtag name, search term
    cluster_id UUID REFERENCES topic_clusters(id) ON DELETE SET NULL,
    metric_value DOUBLE PRECISION DEFAULT 0,
    growth_velocity DOUBLE PRECISION DEFAULT 0,
    source_url TEXT,
    geo_code VARCHAR(10) DEFAULT 'VN',
    metadata JSONB DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Hypertable (Optional on TimescaleDB, safe fallback on Supabase/Vanilla Postgres)
DO $$
BEGIN
    PERFORM create_hypertable('trend_signals', 'captured_at', if_not_exists => TRUE);
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'Skipping create_hypertable: Native Postgres indexing will be used.';
END $$;

-- 6. Ultra-fast Composite Indexes
CREATE INDEX IF NOT EXISTS idx_signals_mission ON trend_signals (mission_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_platform_geo ON trend_signals (platform, geo_code, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_cluster ON trend_signals (cluster_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_captured_at ON trend_signals (captured_at DESC);
