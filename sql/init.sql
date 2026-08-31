-- Enable TimescaleDB & pgvector extensions
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Table topic_clusters (Entity / Topic Level)
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

-- 2. Table trend_signals (Time-Series Metric Level)
CREATE TABLE IF NOT EXISTS trend_signals (
    id BIGSERIAL,
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

-- Convert trend_signals into TimescaleDB Hypertable
SELECT create_hypertable('trend_signals', 'captured_at', if_not_exists => TRUE);

-- Indexes for ultra-fast time-series and platform queries
CREATE INDEX IF NOT EXISTS idx_signals_platform_geo ON trend_signals (platform, geo_code, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_cluster ON trend_signals (cluster_id, captured_at DESC);
