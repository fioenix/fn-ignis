-- Migration 004: Deduplicate trend_signals on (platform, source_url) and record time-series in signal_metrics
-- Reversible & non-destructive: keeps earliest row in trend_signals as canonical, logs all time-series points.

CREATE TABLE IF NOT EXISTS signal_metrics (
    id BIGSERIAL PRIMARY KEY,
    signal_id BIGINT NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metric_value DOUBLE PRECISION DEFAULT 0,
    growth_velocity DOUBLE PRECISION DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_signal_metrics_sig ON signal_metrics (signal_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_metrics_captured ON signal_metrics (captured_at DESC);

-- Populate signal_metrics from existing duplicate signal rows
INSERT INTO signal_metrics (signal_id, captured_at, metric_value, growth_velocity)
SELECT ts.id, ts.captured_at, ts.metric_value, ts.growth_velocity
FROM trend_signals ts
WHERE NOT EXISTS (
    SELECT 1 FROM signal_metrics sm WHERE sm.signal_id = ts.id AND sm.captured_at = ts.captured_at
);
