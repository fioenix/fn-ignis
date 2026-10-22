-- Migration: 033_connector_request_days.sql
-- Description: Count keyword searches per channel per day so each channel can stop at its daily
-- request ceiling (Spec 016 US4, FR-013).
--
-- One request is one keyword searched on one channel. The day is the calendar day in
-- Asia/Ho_Chi_Minh. The ceiling itself lives in runtime_configs as
-- connector.<platform>.daily_request_ceiling; this table holds counters only, no credential and no
-- query text. YouTube's API-unit quota keeps its own ledger (024). Additive: no stored evidence
-- is rewritten.

CREATE TABLE IF NOT EXISTS public.connector_request_days (
    request_day DATE NOT NULL,
    platform VARCHAR(30) NOT NULL,
    used INTEGER NOT NULL DEFAULT 0 CHECK (used >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT connector_request_days_pkey PRIMARY KEY (request_day, platform)
);

ALTER TABLE public.connector_request_days ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.connector_request_days FROM PUBLIC;

DO $$
DECLARE
    client_role text;
BEGIN
    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        EXECUTE format('REVOKE ALL ON public.connector_request_days FROM %I', client_role);
    END LOOP;
END $$;
