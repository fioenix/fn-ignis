-- Migration: 035_watchlist_listening_plans.sql
-- Additive, append-only listening plans (Spec 018). No stored evidence is transformed.
CREATE TABLE IF NOT EXISTS public.watchlist_listening_plans (
    watchlist_id UUID NOT NULL REFERENCES public.watchlists(id) ON DELETE CASCADE,
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    goal TEXT NOT NULL CHECK (goal = btrim(goal) AND char_length(goal) BETWEEN 1 AND 300),
    period_kind TEXT NOT NULL CHECK (period_kind IN ('day', 'week', 'month')),
    snapshots_per_period INTEGER NOT NULL CHECK (
        snapshots_per_period >= 1 AND snapshots_per_period <=
        CASE period_kind WHEN 'day' THEN 1 WHEN 'week' THEN 7 WHEN 'month' THEN 28 END
    ),
    PRIMARY KEY (watchlist_id, effective_from)
);

CREATE OR REPLACE FUNCTION public.refuse_watchlist_listening_plan_update()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'watchlist listening plans are immutable' USING ERRCODE = '23514';
END;
$$;
DROP TRIGGER IF EXISTS refuse_watchlist_listening_plan_update ON public.watchlist_listening_plans;
CREATE TRIGGER refuse_watchlist_listening_plan_update
BEFORE UPDATE ON public.watchlist_listening_plans
FOR EACH ROW EXECUTE FUNCTION public.refuse_watchlist_listening_plan_update();
REVOKE ALL ON FUNCTION public.refuse_watchlist_listening_plan_update() FROM PUBLIC;

-- Owner-only, as every other non-vocabulary table since 021.
DO $$
DECLARE
    t TEXT;
    client_role TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['watchlist_listening_plans'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC', t);
        FOR client_role IN
            SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
        LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I', t, client_role);
        END LOOP;
    END LOOP;
    FOR client_role IN
        SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated') ORDER BY rolname
    LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION public.refuse_watchlist_listening_plan_update() FROM %I', client_role);
    END LOOP;
END $$;
