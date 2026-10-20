-- Additive private admission support; no evidence backfill or authority adoption.
CREATE TABLE IF NOT EXISTS public.mission_follow_up_gaps (
 gap_id UUID PRIMARY KEY, parent_mission_id UUID NOT NULL REFERENCES public.research_missions(id),
 parent_work_id UUID NOT NULL, payload TEXT NOT NULL CHECK(jsonb_typeof(payload::jsonb)='object'),
 FOREIGN KEY(parent_mission_id,parent_work_id) REFERENCES public.research_work_items(mission_id,work_id),
 UNIQUE(parent_mission_id,gap_id)
);
CREATE TABLE IF NOT EXISTS public.mission_follow_up_parent_budgets (
 budget_id UUID PRIMARY KEY,parent_mission_id UUID NOT NULL UNIQUE REFERENCES public.research_missions(id),
 payload TEXT NOT NULL CHECK(jsonb_typeof(payload::jsonb)='object'),UNIQUE(parent_mission_id,budget_id)
);
CREATE TABLE IF NOT EXISTS public.mission_follow_up_assignment_budgets (
 binding_id UUID PRIMARY KEY,parent_mission_id UUID NOT NULL,budget_id UUID NOT NULL,
 assignment_id UUID NOT NULL,epoch INTEGER NOT NULL CHECK(epoch>0),payload TEXT NOT NULL CHECK(jsonb_typeof(payload::jsonb)='object'),
 FOREIGN KEY(parent_mission_id,budget_id) REFERENCES public.mission_follow_up_parent_budgets(parent_mission_id,budget_id),
 FOREIGN KEY(parent_mission_id,assignment_id,epoch) REFERENCES public.research_assignments(mission_id,assignment_id,epoch),
 UNIQUE(parent_mission_id,binding_id),UNIQUE(assignment_id,epoch)
);
CREATE TABLE IF NOT EXISTS public.mission_follow_up_authorities (
 work_id UUID PRIMARY KEY,parent_mission_id UUID NOT NULL,gap_id UUID NOT NULL,budget_id UUID NOT NULL,
 binding_id UUID NOT NULL,payload TEXT NOT NULL CHECK(jsonb_typeof(payload::jsonb)='object'),
 FOREIGN KEY(parent_mission_id,work_id) REFERENCES public.research_work_items(mission_id,work_id),
 FOREIGN KEY(parent_mission_id,gap_id) REFERENCES public.mission_follow_up_gaps(parent_mission_id,gap_id),
 FOREIGN KEY(parent_mission_id,budget_id) REFERENCES public.mission_follow_up_parent_budgets(parent_mission_id,budget_id),
 FOREIGN KEY(parent_mission_id,binding_id) REFERENCES public.mission_follow_up_assignment_budgets(parent_mission_id,binding_id),
 UNIQUE(parent_mission_id,work_id)
);
CREATE TABLE IF NOT EXISTS public.mission_follow_up_commands (
 parent_mission_id UUID NOT NULL REFERENCES public.research_missions(id),operation TEXT NOT NULL CHECK(operation IN ('FACT','RECORD','ADMIT')),
 command_key TEXT NOT NULL,fingerprint TEXT NOT NULL,work_id UUID NOT NULL,
 command_payload TEXT NOT NULL CHECK(jsonb_typeof(command_payload::jsonb)='object'),
 receipt_payload TEXT NOT NULL CHECK(jsonb_typeof(receipt_payload::jsonb)='object'),
 PRIMARY KEY(parent_mission_id,operation,command_key)
);
CREATE TABLE IF NOT EXISTS public.mission_follow_up_reservation_resources (
 reservation_id UUID NOT NULL REFERENCES public.mission_follow_up_reservations(reservation_id),
 resource TEXT NOT NULL,allocated INTEGER NOT NULL CHECK(allocated>=0),
 PRIMARY KEY(reservation_id,resource)
);

CREATE OR REPLACE FUNCTION public.preserve_follow_up_admission_history()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
BEGIN
 RAISE EXCEPTION 'Admission history is immutable' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION public.preserve_follow_up_admission_history() FROM PUBLIC;
DO $$
DECLARE t TEXT; client_role TEXT;
BEGIN
 FOREACH t IN ARRAY ARRAY['mission_follow_up_gaps','mission_follow_up_parent_budgets',
 'mission_follow_up_assignment_budgets','mission_follow_up_authorities','mission_follow_up_commands',
 'mission_follow_up_reservation_resources'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',t);
  EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC',t);
  EXECUTE format('CREATE OR REPLACE TRIGGER admission_history_immutable BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.preserve_follow_up_admission_history()',t);
  FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
   EXECUTE format('REVOKE ALL ON public.%I FROM %I',t,client_role);
  END LOOP;
 END LOOP;
 FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION public.preserve_follow_up_admission_history() FROM %I',client_role);
 END LOOP;
END $$;

CREATE OR REPLACE FUNCTION public.validate_follow_up_admission_payload()
RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER SET search_path=pg_catalog,public AS $$
DECLARE p JSONB; f JSONB; expected_type TEXT; number_name TEXT; row_data JSONB;
BEGIN
 IF TG_TABLE_NAME='mission_follow_up_reservation_resources' THEN RETURN NEW; END IF;
 IF TG_TABLE_NAME='mission_follow_up_commands' THEN
  IF length(NEW.command_payload)>1048576 OR length(NEW.receipt_payload)>1048576 THEN
   RAISE EXCEPTION 'Invalid bounded admission command' USING ERRCODE='23514';
  END IF;
  p:=NEW.command_payload::jsonb;
  IF NEW.operation='ADMIT' AND ((p#>>'{fields,request,fields,mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id')
   OR (p#>>'{fields,request,fields,follow_up_work_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'work_id')) THEN
   RAISE EXCEPTION 'Admission command identity mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.operation='RECORD' AND ((p#>>'{fields,work,fields,inputs,fields,mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id')
   OR (p#>>'{fields,work,fields,work_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'work_id')) THEN
   RAISE EXCEPTION 'Recording command identity mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.operation='FACT' AND (p#>>'{fields,mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id') THEN
   RAISE EXCEPTION 'Fact command identity mismatch' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
 END IF;
 IF length(NEW.payload)>1048576 THEN RAISE EXCEPTION 'Admission payload too large' USING ERRCODE='23514'; END IF;
 p:=NEW.payload::jsonb; f:=p->'fields';
 expected_type:=CASE TG_TABLE_NAME
  WHEN 'mission_follow_up_gaps' THEN 'OperationalGap'
  WHEN 'mission_follow_up_parent_budgets' THEN 'ParentBudget'
  WHEN 'mission_follow_up_assignment_budgets' THEN 'AssignmentBudget'
  WHEN 'mission_follow_up_authorities' THEN 'WorkAuthority' END;
 IF jsonb_typeof(p) IS DISTINCT FROM 'object' OR (p->>'type') IS DISTINCT FROM expected_type THEN
  RAISE EXCEPTION 'Invalid exact admission record' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME='mission_follow_up_gaps' AND ((f#>>'{gap_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'gap_id')
  OR (f#>>'{parent_work_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_work_id')
  OR (f#>>'{inputs,fields,mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id')) THEN
  RAISE EXCEPTION 'Gap ownership mismatch' USING ERRCODE='23514';
 ELSIF TG_TABLE_NAME='mission_follow_up_parent_budgets' AND ((f#>>'{budget_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'budget_id')
  OR (f#>>'{mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id')) THEN
  RAISE EXCEPTION 'Parent budget ownership mismatch' USING ERRCODE='23514';
 ELSIF TG_TABLE_NAME='mission_follow_up_assignment_budgets' AND ((f#>>'{binding_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'binding_id')
  OR (f#>>'{budget_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'budget_id')
  OR (f#>>'{assignment_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'assignment_id')
  OR (f->>'epoch') IS DISTINCT FROM (to_jsonb(NEW)->>'epoch')) THEN
  RAISE EXCEPTION 'Assignment budget ownership mismatch' USING ERRCODE='23514';
 ELSIF TG_TABLE_NAME='mission_follow_up_authorities' AND ((f#>>'{work,fields,work_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'work_id')
  OR (f#>>'{work,fields,gap_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'gap_id')
  OR (f#>>'{work,fields,inputs,fields,mission_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'parent_mission_id')
  OR (f#>>'{budget_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'budget_id') OR (f#>>'{binding_id,uuid}') IS DISTINCT FROM (to_jsonb(NEW)->>'binding_id')) THEN
  RAISE EXCEPTION 'Work authority ownership mismatch' USING ERRCODE='23514';
 END IF;
 FOREACH number_name IN ARRAY CASE expected_type
  WHEN 'ParentBudget' THEN ARRAY['quota_ceiling','cost_ceiling']
  WHEN 'AssignmentBudget' THEN ARRAY['epoch','assignment_version','assignment_quota','cost_ceiling']
  WHEN 'WorkAuthority' THEN ARRAY['quota','cost','quota_ceiling','cost_ceiling'] ELSE ARRAY[]::TEXT[] END LOOP
  IF jsonb_typeof(f->number_name) IS DISTINCT FROM 'number' OR (f->>number_name) !~ '^[0-9]+$'
   OR (f->>number_name)::numeric>9223372036854775807 THEN
   RAISE EXCEPTION 'Invalid finite admission amount' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF expected_type IN ('ParentBudget','WorkAuthority') THEN
  IF jsonb_typeof(f#>'{resources,tuple}') IS DISTINCT FROM 'array'
   OR jsonb_array_length(f#>'{resources,tuple}') NOT BETWEEN 1 AND 100 THEN
   RAISE EXCEPTION 'Finite resource allocation required' USING ERRCODE='23514';
  END IF;
  FOR row_data IN SELECT value FROM jsonb_array_elements(f#>'{resources,tuple}') LOOP
   IF jsonb_typeof(row_data->'tuple') IS DISTINCT FROM 'array' OR jsonb_array_length(row_data->'tuple')<>2
    OR jsonb_typeof(row_data#>'{tuple,0}') IS DISTINCT FROM 'string'
    OR (row_data#>>'{tuple,1}') !~ '^[0-9]+$' OR (row_data#>>'{tuple,1}')::numeric>9223372036854775807 THEN
    RAISE EXCEPTION 'Invalid finite resource allocation' USING ERRCODE='23514';
   END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.validate_follow_up_admission_payload() FROM PUBLIC;
DO $$
DECLARE t TEXT; client_role TEXT;
BEGIN
 FOREACH t IN ARRAY ARRAY['mission_follow_up_gaps','mission_follow_up_parent_budgets','mission_follow_up_assignment_budgets',
 'mission_follow_up_authorities','mission_follow_up_commands'] LOOP
  EXECUTE format('CREATE OR REPLACE TRIGGER admission_payload_valid BEFORE INSERT ON public.%I FOR EACH ROW EXECUTE FUNCTION public.validate_follow_up_admission_payload()',t);
 END LOOP;
 FOR client_role IN SELECT rolname FROM pg_roles WHERE rolname IN ('anon','authenticated') LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION public.validate_follow_up_admission_payload() FROM %I',client_role);
 END LOOP;
END $$;
