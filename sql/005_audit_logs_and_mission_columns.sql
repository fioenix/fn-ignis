-- Migration: 005_audit_logs_and_mission_columns.sql
-- Description: Add shortcode, agent, session_id to research_missions and create system_audit_logs

ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS shortcode VARCHAR(50);
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS agent VARCHAR(50) DEFAULT 'claude';
ALTER TABLE research_missions ADD COLUMN IF NOT EXISTS session_id TEXT;

CREATE TABLE IF NOT EXISTS system_audit_logs (
    id BIGSERIAL PRIMARY KEY,
    level VARCHAR(20) NOT NULL DEFAULT 'INFO',
    component VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON system_audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_component_level ON system_audit_logs (component, level);
