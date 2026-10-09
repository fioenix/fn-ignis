-- Additive follow-up storage only. No canonical evidence or lifecycle row is transformed.
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_work_owner_identity
    ON public.research_work_items(mission_id,work_id,assignment_id,epoch,input_id);
CREATE UNIQUE INDEX IF NOT EXISTS follow_up_brief_owner_identity
    ON public.market_brief_revisions(mission_id,id);

CREATE TABLE IF NOT EXISTS public.mission_follow_up_work (
    work_id UUID PRIMARY KEY,
    parent_mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    parent_work_id UUID NOT NULL,
    assignment_id UUID NOT NULL,
    research_epoch BIGINT NOT NULL CHECK (research_epoch > 0),
    assignment_version BIGINT NOT NULL CHECK (assignment_version > 0),
    work_version BIGINT NOT NULL CHECK (work_version > 0),
    input_id UUID NOT NULL,
    brief_revision_id UUID NOT NULL,
    gap_id UUID NOT NULL,
    approved_queries TEXT NOT NULL,
    approved_sources TEXT NOT NULL,
    requested_queries TEXT NOT NULL,
    requested_sources TEXT NOT NULL,
    authority_deadline TIMESTAMPTZ NOT NULL CHECK (isfinite(authority_deadline)),
    FOREIGN KEY (parent_mission_id,parent_work_id)
        REFERENCES public.research_work_items(mission_id,work_id),
    FOREIGN KEY (parent_mission_id,work_id,assignment_id,research_epoch,input_id)
        REFERENCES public.research_work_items(mission_id,work_id,assignment_id,epoch,input_id),
    FOREIGN KEY (parent_mission_id,brief_revision_id)
        REFERENCES public.market_brief_revisions(mission_id,id),
    UNIQUE (parent_mission_id,work_id)
);

CREATE TABLE IF NOT EXISTS public.mission_follow_ups (
    follow_up_id UUID PRIMARY KEY,
    parent_mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    child_mission_id UUID NOT NULL UNIQUE REFERENCES public.research_missions(id),
    work_id UUID NOT NULL UNIQUE,
    reservation_id UUID NOT NULL UNIQUE,
    child_manifest_digest TEXT NOT NULL CHECK (child_manifest_digest ~ '^[0-9a-f]{64}$'),
    child_brief_digest TEXT NOT NULL CHECK (child_brief_digest ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 256 AND length(btrim(idempotency_key))>0),
    CHECK (parent_mission_id <> child_mission_id),
    FOREIGN KEY (parent_mission_id,work_id)
        REFERENCES public.mission_follow_up_work(parent_mission_id,work_id),
    UNIQUE (parent_mission_id,idempotency_key),
    UNIQUE (parent_mission_id,child_mission_id,follow_up_id)
);

CREATE TABLE IF NOT EXISTS public.mission_follow_up_reservations (
    reservation_id UUID PRIMARY KEY,
    follow_up_id UUID NOT NULL UNIQUE,
    parent_mission_id UUID NOT NULL REFERENCES public.research_missions(id) ON DELETE CASCADE,
    child_mission_id UUID NOT NULL,
    reserved_quota BIGINT NOT NULL CHECK (reserved_quota >= 0),
    reserved_cost BIGINT NOT NULL CHECK (reserved_cost >= 0),
    measured_quota BIGINT CHECK (measured_quota >= 0),
    measured_cost BIGINT CHECK (measured_cost >= 0),
    measurement_receipt_id UUID,
    state TEXT NOT NULL CHECK (state IN ('RESERVED','UNRESOLVED','SETTLED')),
    version BIGINT NOT NULL CHECK (version > 0),
    CHECK ((state='SETTLED' AND measured_quota IS NOT NULL AND measured_cost IS NOT NULL
            AND measurement_receipt_id IS NOT NULL)
        OR (state<>'SETTLED' AND measurement_receipt_id IS NULL)),
    FOREIGN KEY (parent_mission_id,child_mission_id,follow_up_id)
        REFERENCES public.mission_follow_ups(parent_mission_id,child_mission_id,follow_up_id)
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (reservation_id,follow_up_id,parent_mission_id,child_mission_id)
);
DO $$
BEGIN
    ALTER TABLE public.mission_follow_ups ADD CONSTRAINT follow_up_exact_reservation
        FOREIGN KEY (reservation_id,follow_up_id,parent_mission_id,child_mission_id)
        REFERENCES public.mission_follow_up_reservations(reservation_id,follow_up_id,parent_mission_id,child_mission_id)
        DEFERRABLE INITIALLY DEFERRED;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
CREATE INDEX IF NOT EXISTS follow_up_reservation_parent_budget
    ON public.mission_follow_up_reservations(parent_mission_id,state);

CREATE OR REPLACE FUNCTION public.follow_up_scope_valid(value TEXT, source_scope BOOLEAN)
RETURNS BOOLEAN LANGUAGE plpgsql IMMUTABLE SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE payload JSONB;
BEGIN
    payload := value::jsonb;
    IF jsonb_typeof(payload)<>'array' THEN RETURN FALSE; END IF;
    IF jsonb_array_length(payload) NOT BETWEEN 1 AND 100 THEN RETURN FALSE; END IF;
    RETURN NOT EXISTS (
        SELECT 1 FROM jsonb_array_elements(payload) e
        WHERE jsonb_typeof(e)<>'string' OR length(btrim(e#>>'{}'))=0 OR length(e#>>'{}') NOT BETWEEN 1 AND
            CASE WHEN source_scope THEN 128 ELSE 512 END
            OR (e#>>'{}') ~ '[[:cntrl:]]'
            OR (source_scope AND (e#>>'{}') !~ '^[A-Za-z][A-Za-z0-9_-]*$')
    ) AND (SELECT count(DISTINCT e) FROM jsonb_array_elements(payload) e)=jsonb_array_length(payload);
EXCEPTION WHEN invalid_text_representation THEN RETURN FALSE;
END $$;

CREATE OR REPLACE FUNCTION public.validate_follow_up_record()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE parent_workspace UUID; child_workspace UUID; work_record RECORD;
BEGIN
    IF TG_TABLE_NAME='mission_follow_up_work' THEN
        IF NOT public.follow_up_scope_valid(NEW.approved_queries,FALSE)
            OR NOT public.follow_up_scope_valid(NEW.requested_queries,FALSE)
            OR NOT public.follow_up_scope_valid(NEW.approved_sources,TRUE)
            OR NOT public.follow_up_scope_valid(NEW.requested_sources,TRUE) THEN
            RAISE EXCEPTION 'Invalid bounded follow-up scope' USING ERRCODE='23514';
        END IF;
    ELSIF TG_TABLE_NAME='mission_follow_ups' THEN
        SELECT workspace_id INTO parent_workspace FROM public.research_missions WHERE id=NEW.parent_mission_id;
        SELECT workspace_id INTO child_workspace FROM public.research_missions WHERE id=NEW.child_mission_id;
        -- Unknown child is left to its FK; an existing unrelated child is never adopted.
        IF EXISTS (SELECT 1 FROM public.research_missions WHERE id=NEW.child_mission_id)
            AND (parent_workspace IS NULL OR child_workspace IS DISTINCT FROM parent_workspace) THEN
            RAISE EXCEPTION 'Child research ownership mismatch' USING ERRCODE='23514';
        END IF;
        SELECT * INTO work_record FROM public.mission_follow_up_work
            WHERE parent_mission_id=NEW.parent_mission_id AND work_id=NEW.work_id;
        IF FOUND AND (
            EXISTS (SELECT value FROM jsonb_array_elements(work_record.requested_queries::jsonb)
                EXCEPT SELECT value FROM jsonb_array_elements(work_record.approved_queries::jsonb))
            OR EXISTS (SELECT value FROM jsonb_array_elements(work_record.requested_sources::jsonb)
                EXCEPT SELECT value FROM jsonb_array_elements(work_record.approved_sources::jsonb))) THEN
            RAISE EXCEPTION 'Admitted follow-up scope exceeds approval' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.preserve_follow_up_record()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
    IF TG_OP='DELETE' THEN
        IF NOT EXISTS (SELECT 1 FROM public.research_missions WHERE id=OLD.parent_mission_id) THEN RETURN OLD; END IF;
        RAISE EXCEPTION 'Live follow-up history cannot be deleted' USING ERRCODE='23514';
    END IF;
    IF TG_TABLE_NAME<>'mission_follow_up_reservations' THEN
        IF NEW IS DISTINCT FROM OLD THEN
            RAISE EXCEPTION 'Follow-up identity and scope are immutable' USING ERRCODE='23514';
        END IF;
    ELSE
        IF (to_jsonb(NEW)-ARRAY['state','version','measured_quota','measured_cost','measurement_receipt_id'])
            IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','version','measured_quota','measured_cost','measurement_receipt_id'])
            OR (OLD.state='SETTLED' AND NEW IS DISTINCT FROM OLD)
            OR (OLD.state='UNRESOLVED' AND NEW.state='RESERVED')
            OR (OLD.measured_quota IS NOT NULL AND (NEW.measured_quota IS NULL OR NEW.measured_quota<OLD.measured_quota))
            OR (OLD.measured_cost IS NOT NULL AND (NEW.measured_cost IS NULL OR NEW.measured_cost<OLD.measured_cost))
            OR (NEW IS DISTINCT FROM OLD AND NEW.version<>OLD.version+1) THEN
            RAISE EXCEPTION 'Invalid conservative reservation transition' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION public.preserve_follow_up_mission_owner()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
    IF NEW.workspace_id IS DISTINCT FROM OLD.workspace_id AND EXISTS (
        SELECT 1 FROM public.mission_follow_ups WHERE parent_mission_id=OLD.id OR child_mission_id=OLD.id
    ) THEN RAISE EXCEPTION 'Linked follow-up mission owner is immutable' USING ERRCODE='23514'; END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE TRIGGER follow_up_mission_owner_immutable
    BEFORE UPDATE OF workspace_id ON public.research_missions
    FOR EACH ROW EXECUTE FUNCTION public.preserve_follow_up_mission_owner();

DO $$
DECLARE t TEXT; client_role TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['mission_follow_up_work','mission_follow_ups','mission_follow_up_reservations'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',t);
        FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
            EXECUTE format('REVOKE ALL ON public.%I FROM %I',t,client_role);
        END LOOP;
        EXECUTE format('CREATE OR REPLACE TRIGGER follow_up_work_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.preserve_follow_up_record()',t);
        IF t<>'mission_follow_up_reservations' THEN
            EXECUTE format('CREATE OR REPLACE TRIGGER follow_up_record_validate BEFORE INSERT OR UPDATE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.validate_follow_up_record()',t);
        END IF;
    END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.follow_up_scope_valid(TEXT,BOOLEAN),public.validate_follow_up_record(),
    public.preserve_follow_up_record(),public.preserve_follow_up_mission_owner() FROM PUBLIC;
DO $$
DECLARE client_role TEXT;
BEGIN
    FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION public.follow_up_scope_valid(TEXT,BOOLEAN),public.validate_follow_up_record(),public.preserve_follow_up_record(),public.preserve_follow_up_mission_owner() FROM %I',client_role);
    END LOOP;
END $$;
