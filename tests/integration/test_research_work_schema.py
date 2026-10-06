"""T046 additive PostgreSQL schema controls; adapter parity belongs to later tasks."""
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from tests.integration.conftest import SCHEMA_MIGRATIONS, runtime_owner

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / 'sql/028_research_work.sql'
TABLES = ('research_assignments', 'research_work_items', 'research_input_sets',
          'research_input_observations', 'research_input_findings', 'research_work_dependencies',
          'research_handoffs', 'research_handoff_references', 'research_finding_revisions',
          'research_finding_observations', 'research_activity_receipts',
          'research_handoff_acknowledgements', 'research_recorded_metadata', 'research_work_commands')


def test_explicit_schema_inventory_includes_research_work():
    assert MIGRATION.name in SCHEMA_MIGRATIONS
    assert MIGRATION.is_file()


def install(conn):
    for migration in SCHEMA_MIGRATIONS:
        if migration != MIGRATION.name:
            conn.execute((ROOT / 'sql' / migration).read_text())
    assert MIGRATION.is_file(), 'T046 schema absence, not a behavioral RED'
    conn.execute(MIGRATION.read_text())


@pytest.fixture
def schema_db(supabase_like_dsn):
    with psycopg.connect(supabase_like_dsn) as conn:
        install(conn)
    with runtime_owner(supabase_like_dsn) as dsn:
        with psycopg.connect(dsn, autocommit=True) as conn:
            yield conn


def rejected(conn, statement, params=(), error=psycopg.errors.CheckViolation):
    with pytest.raises(error) as failure:
        with conn.transaction():
            conn.execute(statement, params)
    return failure.value


def rows(conn, table):
    return conn.execute(sql.SQL('SELECT * FROM {} ORDER BY 1, 2').format(sql.Identifier(table))).fetchall()


def arrange(conn):
    mission, foreign, assignment, work, inputs, source, other_source, observation, handoff, finding = [uuid4() for _ in range(10)]
    for identity in (mission, foreign):
        conn.execute("INSERT INTO research_missions(id,title,keywords,geo_code) VALUES (%s,'Schema control',ARRAY['schema'], 'VN')", (identity,))
    for identity in (source, other_source):
        conn.execute("INSERT INTO sources(id,platform,external_id) VALUES (%s,'YOUTUBE',%s)", (identity,str(identity)))
    conn.execute("INSERT INTO observations(id,source_id,time_provenance,identity_source) VALUES (%s,%s,'unknown','metadata_external_id')", (observation,source))
    conn.execute('INSERT INTO mission_evidence(mission_id,observation_id) VALUES (%s,%s)', (mission,observation))
    conn.execute("INSERT INTO research_assignments(assignment_id,mission_id,host_task_ref,epoch,actions,sources,deadline,quota_ceiling,state,version,expected_manifest_digest) VALUES (%s,%s,'host',1,ARRAY['ANALYZE'],ARRAY['youtube'],now()+interval '1 day',0,'ASSIGNED',1,%s)", (assignment,mission,'a'*64))
    conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)', (inputs,mission,'a'*64))
    conn.execute('INSERT INTO research_input_observations(input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s)', (inputs,mission,observation,source))
    conn.execute("INSERT INTO research_work_items(work_id,assignment_id,mission_id,input_id,question,expertise,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,'Question','Synthesis',1,'RUNNING',2,'fence')", (work,assignment,mission,inputs))
    conn.execute("INSERT INTO research_handoffs(handoff_id,mission_id,work_id,input_id,expected_version,ownership_fence,consumer_ref,result,submitted_recorded_at) VALUES (%s,%s,%s,%s,2,'fence','consumer','Safe result','2020-01-01T00:00:00Z')", (handoff,mission,work,inputs))
    conn.execute("INSERT INTO research_finding_revisions(finding_id,revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,1,%s,%s,%s,%s,'DESCRIPTIVE','Safe finding')", (finding,mission,work,handoff,inputs))
    return locals()


def test_membership_pruning_preserves_exact_history_and_canonical_rows(schema_db, record_property):
    conn = schema_db
    ids = arrange(conn)
    canonical = {t: rows(conn,t) for t in ('sources','observations','research_missions')}
    history = {t: rows(conn,t) for t in TABLES}
    record_property('canonical_counts', str({t: len(v) for t,v in canonical.items()}))
    record_property('canonical_sha256', sha256(repr(canonical).encode()).hexdigest())
    record_property('history_sha256', sha256(repr(history).encode()).hexdigest())
    assert conn.execute('DELETE FROM mission_evidence WHERE mission_id=%s', (ids['mission'],)).rowcount == 1
    assert {t: rows(conn,t) for t in TABLES} == history
    assert {t: rows(conn,t) for t in canonical} == canonical
    assert conn.execute('SELECT count(*) FROM mission_evidence').fetchone() == (0,)
    assert conn.execute('SELECT submitted_recorded_at FROM research_handoffs').fetchone()[0].year == 2020


def test_exact_scope_source_and_predecessor_constraints(schema_db):
    conn = schema_db
    x = arrange(conn)
    fresh = uuid4()
    conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)',(fresh,x['foreign'],'b'*64))
    rejected(conn,'INSERT INTO research_input_observations(input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s)', (fresh,x['foreign'],x['observation'],x['source']))
    second = uuid4()
    conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)',(second,x['mission'],'b'*64))
    rejected(conn,'INSERT INTO research_input_observations(input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s)', (second,x['mission'],x['observation'],x['other_source']))
    rejected(conn,"INSERT INTO research_work_items(work_id,assignment_id,mission_id,input_id,question,expertise,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,'q','e',1,'ASSIGNED',1,'f')", (uuid4(),x['assignment'],x['foreign'],fresh),psycopg.errors.ForeignKeyViolation)
    revised_handoff = uuid4()
    conn.execute("INSERT INTO research_handoffs(handoff_id,mission_id,work_id,input_id,expected_version,ownership_fence,consumer_ref,result) VALUES (%s,%s,%s,%s,2,'fence','consumer','Revised result')",(revised_handoff,x['mission'],x['work'],x['inputs']))
    failure = rejected(conn,"INSERT INTO research_finding_revisions(finding_id,revision,predecessor_revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,3,2,%s,%s,%s,%s,'DESCRIPTIVE','Skipped')", (x['finding'],x['mission'],x['work'],revised_handoff,x['inputs']),psycopg.errors.ForeignKeyViolation)
    assert failure.diag.message_detail == f'Key (mission_id, finding_id, predecessor_revision)=({x["mission"]}, {x["finding"]}, 2) is not present in table "research_finding_revisions".'
    conn.execute("INSERT INTO research_finding_revisions(finding_id,revision,predecessor_revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,2,1,%s,%s,%s,%s,'DESCRIPTIVE','Revised')", (x['finding'],x['mission'],x['work'],revised_handoff,x['inputs']))
    conn.execute('INSERT INTO research_input_findings(input_id,mission_id,finding_id,revision) VALUES (%s,%s,%s,1)',(second,x['mission'],x['finding']))
    assert conn.execute('SELECT revision FROM research_input_findings').fetchall() == [(1,)]
    rejected(conn,"UPDATE research_finding_revisions SET statement='Rewrite' WHERE finding_id=%s",(x['finding'],))
    rejected(conn,'DELETE FROM research_handoffs WHERE handoff_id=%s',(x['handoff'],))
    rejected(conn,'UPDATE research_input_observations SET source_id=%s',(x['other_source'],))


def test_owner_only_actual_read_write_denial_and_repeat_install(supabase_like_dsn):
    with psycopg.connect(supabase_like_dsn, autocommit=True) as conn:
        install(conn)
        arrange(conn)
        before = {t: rows(conn,t) for t in TABLES + ('sources','observations','mission_evidence','research_missions')}
        conn.execute(MIGRATION.read_text())
        assert {t: rows(conn,t) for t in before} == before
        for role in ('anon','authenticated'):
            with conn.transaction():
                conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                for table in TABLES:
                    rejected(conn,sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)),error=psycopg.errors.InsufficientPrivilege)
                    rejected(conn,sql.SQL('DELETE FROM {}').format(sql.Identifier(table)),error=psycopg.errors.InsufficientPrivilege)
                    rejected(conn,sql.SQL('INSERT INTO {} DEFAULT VALUES').format(sql.Identifier(table)),error=psycopg.errors.InsufficientPrivilege)
                    rejected(conn,sql.SQL('TRUNCATE {}').format(sql.Identifier(table)),error=psycopg.errors.InsufficientPrivilege)
        assert {t: rows(conn,t) for t in before} == before


def test_mission_owner_delete_cascades_only_owned_research_history(schema_db):
    conn = schema_db
    x = arrange(conn)
    canonical = {t: rows(conn,t) for t in ('sources','observations')}
    assert conn.execute('DELETE FROM research_missions WHERE id=%s',(x['mission'],)).rowcount == 1
    assert all(rows(conn,t) == [] for t in TABLES)
    assert {t: rows(conn,t) for t in canonical} == canonical


def test_recorded_metadata_and_original_safe_receipt_identity(schema_db):
    conn = schema_db
    x = arrange(conn)
    conn.execute('INSERT INTO mission_progress_revisions(mission_id,revision) VALUES (%s,4)',(x['mission'],))
    statement = "INSERT INTO research_recorded_metadata(mission_id,record_kind,record_id,record_version,mission_revision) VALUES (%s,'WORK',%s,%s,4)"
    conn.execute(statement,(x['mission'],x['work'],1))
    conn.execute(statement,(x['mission'],x['work'],2))
    rejected(conn,statement,(x['mission'],x['work'],3))
    rejected(conn,statement,(x['mission'],uuid4(),1))
    rejected(conn,"INSERT INTO research_recorded_metadata(mission_id,record_kind,record_id,record_version,mission_revision,recorded_at) VALUES (%s,'HANDOFF',%s,1,4,'2020-01-01T00:00:00Z')",(x['mission'],x['handoff']))
    rejected(conn,"INSERT INTO research_recorded_metadata(mission_id,record_kind,record_id,record_version,mission_revision,provenance) VALUES (%s,'HANDOFF',%s,1,4,'HOST_REPORTED')",(x['mission'],x['handoff']))
    receipt = uuid4()
    insert = "INSERT INTO research_work_commands(mission_id,command_key,payload_fingerprint,operation,receipt_id,disposition,reason_code,revision) VALUES (%s,'retry-key',%s,'SUBMIT_HANDOFF',%s,'REFUSED',%s,4)"
    rejected(conn,insert,(x['mission'],'c'*64,receipt,'PRIVATE_SENTINEL'))
    conn.execute(insert,(x['mission'],'c'*64,receipt,'STALE_VERSION'))
    before = rows(conn,'research_work_commands')
    rejected(conn,insert,(x['mission'],'d'*64,uuid4(),'STALE_VERSION'),psycopg.errors.UniqueViolation)
    rejected(conn,'UPDATE research_work_commands SET payload_fingerprint=%s',('e'*64,))
    assert rows(conn,'research_work_commands') == before
    assert before[0][4] == receipt
    assert conn.execute('SELECT record_version FROM research_recorded_metadata ORDER BY record_version').fetchall() == [(1,),(2,)]


def test_bound_observation_cannot_be_reparented_or_input_extended(schema_db):
    conn = schema_db
    x = arrange(conn)
    rejected(conn,'UPDATE observations SET source_id=%s WHERE id=%s',(x['other_source'],x['observation']),psycopg.errors.ForeignKeyViolation)
    extra = uuid4()
    conn.execute("INSERT INTO observations(id,source_id,time_provenance,identity_source) VALUES (%s,%s,'unknown','metadata_external_id')",(extra,x['source']))
    conn.execute('INSERT INTO mission_evidence(mission_id,observation_id) VALUES (%s,%s)',(x['mission'],extra))
    rejected(conn,'INSERT INTO research_input_observations(input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s)',(x['inputs'],x['mission'],extra,x['source']))



def test_late_finding_input_extension_is_refused(schema_db):
    conn = schema_db
    x = arrange(conn)
    rejected(conn,'INSERT INTO research_input_findings(input_id,mission_id,finding_id,revision) VALUES (%s,%s,%s,1)',(x['inputs'],x['mission'],x['finding']))
    assert rows(conn,'research_input_findings') == []


def test_initial_additive_install_preserves_nonempty_canonical_data(supabase_like_dsn, record_property):
    with psycopg.connect(supabase_like_dsn, autocommit=True) as conn:
        for migration in SCHEMA_MIGRATIONS:
            if migration != MIGRATION.name:
                conn.execute((ROOT / 'sql' / migration).read_text())
        mission, source, observation = [uuid4() for _ in range(3)]
        conn.execute("INSERT INTO research_missions(id,title,keywords) VALUES (%s,'Preexisting mission',ARRAY['control'])",(mission,))
        conn.execute("INSERT INTO sources(id,platform,external_id) VALUES (%s,'YOUTUBE','existing')",(source,))
        conn.execute("INSERT INTO observations(id,source_id,time_provenance,identity_source,published_at,observed_title) VALUES (%s,%s,'legacy_publish_only','metadata_external_id','2020-01-01T00:00:00Z','Preserved title')",(observation,source))
        conn.execute('INSERT INTO mission_evidence(mission_id,observation_id) VALUES (%s,%s)',(mission,observation))
        before = {t: rows(conn,t) for t in ('sources','observations','mission_evidence','research_missions','mission_evidence_qualifications','mission_claims')}
        before_digest = sha256(repr(before).encode()).hexdigest()
        conn.execute(MIGRATION.read_text())
        after = {t: rows(conn,t) for t in before}
        assert after == before
        assert sha256(repr(after).encode()).hexdigest() == before_digest
        record_property('canonical_counts',str({t: len(v) for t,v in before.items()}))
        record_property('before_sha256',before_digest)
        record_property('after_sha256',sha256(repr(after).encode()).hexdigest())
        assert conn.execute('SELECT observed_at,time_provenance FROM observations').fetchone() == (None,'legacy_publish_only')


def test_missing_finding_predecessor_is_refused(schema_db):
    conn = schema_db
    x = arrange(conn)
    handoff = uuid4()
    conn.execute("INSERT INTO research_handoffs(handoff_id,mission_id,work_id,input_id,expected_version,ownership_fence,consumer_ref,result) VALUES (%s,%s,%s,%s,2,'fence','consumer','Next result')",(handoff,x['mission'],x['work'],x['inputs']))
    rejected(conn,"INSERT INTO research_finding_revisions(finding_id,revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,2,%s,%s,%s,%s,'DESCRIPTIVE','Missing predecessor')",(x['finding'],x['mission'],x['work'],handoff,x['inputs']))


def test_submitted_tuple_order_survives_reverse_uuid_readback(schema_db):
    conn = schema_db
    x = arrange(conn)
    input_id, work, handoff, dependent_input, dependent_work = [uuid4() for _ in range(5)]
    for identity in (input_id,dependent_input):
        conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)',(identity,x['mission'],'a'*64))
    observations = tuple(sorted((uuid4(),uuid4()),reverse=True))
    for ordinal, observation in enumerate(observations,1):
        conn.execute("INSERT INTO observations(id,source_id,time_provenance,identity_source) VALUES (%s,%s,'unknown','metadata_external_id')",(observation,x['source']))
        conn.execute('INSERT INTO mission_evidence(mission_id,observation_id) VALUES (%s,%s)',(x['mission'],observation))
        conn.execute('INSERT INTO research_input_observations(ordinal,input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s,%s)',(ordinal,input_id,x['mission'],observation,x['source']))
    conn.execute("INSERT INTO research_work_items(work_id,assignment_id,mission_id,input_id,question,expertise,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,'q','e',1,'RUNNING',2,'fence')",(work,x['assignment'],x['mission'],input_id))
    conn.execute("INSERT INTO research_handoffs(handoff_id,mission_id,work_id,input_id,expected_version,ownership_fence,consumer_ref,result) VALUES (%s,%s,%s,%s,2,'fence','consumer','Result')",(handoff,x['mission'],work,input_id))
    findings = tuple(sorted((uuid4(),uuid4()),reverse=True))
    for ordinal, finding in enumerate(findings,1):
        conn.execute("INSERT INTO research_finding_revisions(handoff_ordinal,finding_id,revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,%s,1,%s,%s,%s,%s,'DESCRIPTIVE','Finding')",(ordinal,finding,x['mission'],work,handoff,input_id))
        conn.execute('INSERT INTO research_input_findings(ordinal,input_id,mission_id,finding_id,revision) VALUES (%s,%s,%s,%s,1)',(ordinal,dependent_input,x['mission'],finding))
    for ordinal, observation in enumerate(observations,1):
        conn.execute("INSERT INTO research_finding_observations(ordinal,mission_id,finding_id,revision,observation_id,direction) VALUES (%s,%s,%s,1,%s,'SUPPORT')",(ordinal,x['mission'],findings[0],observation))
    conn.execute("INSERT INTO research_work_items(work_id,assignment_id,mission_id,input_id,question,expertise,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,'q','e',1,'ASSIGNED',1,'fence')",(dependent_work,x['assignment'],x['mission'],dependent_input))
    dependencies = tuple(sorted((x['work'],work),reverse=True))
    for ordinal, dependency in enumerate(dependencies,1):
        conn.execute('INSERT INTO research_work_dependencies(ordinal,mission_id,work_id,dependency_work_id) VALUES (%s,%s,%s,%s)',(ordinal,x['mission'],dependent_work,dependency))
    claims = tuple(sorted((uuid4(),uuid4()),reverse=True))
    for ordinal, claim in enumerate(claims,1):
        conn.execute("INSERT INTO mission_claims(id,mission_id,frame_digest,client_claim_key,claim_type,wording,status,created_by) VALUES (%s,%s,%s,%s,'OBSERVATION','Claim','WITHHELD','schema-control')",(claim,x['mission'],'a'*64,str(claim)))
        conn.execute("INSERT INTO research_handoff_references(ordinal,mission_id,handoff_id,reference_kind,reference_id,claim_id) VALUES (%s,%s,%s,'CLAIM',%s,%s)",(ordinal,x['mission'],handoff,claim,claim))
    queries = (
        ('SELECT observation_id FROM research_input_observations WHERE input_id=%s ORDER BY ordinal',input_id,observations),
        ('SELECT finding_id FROM research_finding_revisions WHERE handoff_id=%s ORDER BY handoff_ordinal',handoff,findings),
        ('SELECT finding_id FROM research_input_findings WHERE input_id=%s ORDER BY ordinal',dependent_input,findings),
        ('SELECT observation_id FROM research_finding_observations WHERE finding_id=%s ORDER BY ordinal',findings[0],observations),
        ('SELECT dependency_work_id FROM research_work_dependencies WHERE work_id=%s ORDER BY ordinal',dependent_work,dependencies),
        ('SELECT reference_id FROM research_handoff_references WHERE handoff_id=%s ORDER BY ordinal',handoff,claims),
    )
    for statement, identity, expected in queries:
        assert tuple(row[0] for row in conn.execute(statement,(identity,))) == expected
    rejected(conn,'DELETE FROM mission_claims WHERE id=%s',(claims[0],),psycopg.errors.ForeignKeyViolation)


def unfinalized_work(conn, x):
    input_id, work = uuid4(), uuid4()
    conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)',(input_id,x['mission'],'a'*64))
    conn.execute('INSERT INTO research_input_observations(input_id,mission_id,observation_id,source_id) VALUES (%s,%s,%s,%s)',(input_id,x['mission'],x['observation'],x['source']))
    conn.execute("INSERT INTO research_work_items(work_id,assignment_id,mission_id,input_id,question,expertise,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,'q','e',1,'ASSIGNED',1,'initial-fence')",(work,x['assignment'],x['mission'],input_id))
    return input_id, work


@pytest.mark.parametrize('operation',('REBIND','DELETE'))
def test_live_work_identity_cannot_reopen_submitted_input_seal(schema_db, operation):
    conn = schema_db
    x = arrange(conn)
    old_input, work = unfinalized_work(conn,x)
    replacement = uuid4()
    conn.execute('INSERT INTO research_input_sets(input_id,mission_id,manifest_digest) VALUES (%s,%s,%s)',(replacement,x['mission'],'b'*64))
    if operation == 'REBIND':
        rejected(conn,'UPDATE research_work_items SET input_id=%s WHERE work_id=%s',(replacement,work))
    else:
        rejected(conn,'DELETE FROM research_work_items WHERE work_id=%s',(work,))
    assert conn.execute('SELECT input_id FROM research_work_items WHERE work_id=%s',(work,)).fetchone() == (old_input,)
    rejected(conn,'INSERT INTO research_input_findings(input_id,mission_id,finding_id,revision) VALUES (%s,%s,%s,1)',(old_input,x['mission'],x['finding']))
    conn.execute("UPDATE research_work_items SET state='RUNNING',version=2,ownership_fence='next-fence',reason='Started' WHERE work_id=%s",(work,))
    assert conn.execute('SELECT state,version,ownership_fence FROM research_work_items WHERE work_id=%s',(work,)).fetchone() == ('RUNNING',2,'next-fence')


def finalize(conn, x, kind, identity, version=1):
    conn.execute('INSERT INTO mission_progress_revisions(mission_id,revision) VALUES (%s,4) ON CONFLICT(mission_id) DO NOTHING',(x['mission'],))
    conn.execute('INSERT INTO research_recorded_metadata(mission_id,record_kind,record_id,record_version,mission_revision) VALUES (%s,%s,%s,%s,4)',(x['mission'],kind,identity,version))


@pytest.mark.parametrize('collection',('HANDOFF_FINDINGS','HANDOFF_CLAIMS','HANDOFF_OUTCOMES','FINDING_DIRECTIONS','FINDING_DIRECTIONS_HANDOFF','WORK_DEPENDENCIES'))
def test_store_metadata_finalizes_exact_child_collection(schema_db, collection):
    conn = schema_db
    x = arrange(conn)
    if collection == 'WORK_DEPENDENCIES':
        _, work = unfinalized_work(conn,x)
        finalize(conn,x,'WORK',work)
        conn.execute("UPDATE research_work_items SET state='RUNNING',version=2,ownership_fence='changed-fence' WHERE work_id=%s",(work,))
        rejected(conn,'INSERT INTO research_work_dependencies(mission_id,work_id,dependency_work_id) VALUES (%s,%s,%s)',(x['mission'],work,x['work']))
    elif collection == 'HANDOFF_FINDINGS':
        finalize(conn,x,'HANDOFF',x['handoff'])
        rejected(conn,"INSERT INTO research_finding_revisions(handoff_ordinal,finding_id,revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (2,%s,1,%s,%s,%s,%s,'DESCRIPTIVE','Late')",(uuid4(),x['mission'],x['work'],x['handoff'],x['inputs']))
    elif collection == 'HANDOFF_CLAIMS':
        claim = uuid4()
        conn.execute("INSERT INTO mission_claims(id,mission_id,frame_digest,client_claim_key,claim_type,wording,status,created_by) VALUES (%s,%s,%s,%s,'OBSERVATION','Claim','WITHHELD','schema-control')",(claim,x['mission'],'a'*64,str(claim)))
        finalize(conn,x,'HANDOFF',x['handoff'])
        rejected(conn,"INSERT INTO research_handoff_references(mission_id,handoff_id,reference_kind,reference_id,claim_id) VALUES (%s,%s,'CLAIM',%s,%s)",(x['mission'],x['handoff'],claim,claim))
    elif collection == 'HANDOFF_OUTCOMES':
        workspace, run, outcome = uuid4(),uuid4(),uuid4()
        conn.execute("INSERT INTO research_workspaces(id,slug,root_path) VALUES (%s,%s,'/schema-control')",(workspace,str(workspace)))
        conn.execute("INSERT INTO mission_run_journals(id,workspace_id,mission_id,journal_path,sequence) VALUES (%s,%s,%s,%s,1)",(run,workspace,x['mission'],str(run)))
        conn.execute("INSERT INTO mission_probe_outcomes(id,run_id,platform,connector_surface,status,signals_collected,query_fingerprint,completed_at) VALUES (%s,%s,'youtube','schema-outcome','AUTH_REQUIRED',0,%s,now())",(outcome,run,'a'*64))
        finalize(conn,x,'HANDOFF',x['handoff'])
        rejected(conn,"INSERT INTO research_handoff_references(mission_id,handoff_id,reference_kind,reference_id,outcome_id) VALUES (%s,%s,'OUTCOME',%s,%s)",(x['mission'],x['handoff'],outcome,outcome))
    else:
        if collection == 'FINDING_DIRECTIONS_HANDOFF':
            finalize(conn,x,'HANDOFF',x['handoff'])
        else:
            finalize(conn,x,'FINDING',x['finding'])
        rejected(conn,"INSERT INTO research_finding_observations(mission_id,finding_id,revision,observation_id,direction) VALUES (%s,%s,1,%s,'SUPPORT')",(x['mission'],x['finding'],x['observation']))


def test_atomic_child_population_then_finalization_and_fresh_revision(schema_db):
    conn = schema_db
    x = arrange(conn)
    with conn.transaction():
        _, work = unfinalized_work(conn,x)
        conn.execute('INSERT INTO research_work_dependencies(mission_id,work_id,dependency_work_id) VALUES (%s,%s,%s)',(x['mission'],work,x['work']))
        finalize(conn,x,'WORK',work)
        conn.execute("INSERT INTO research_finding_observations(mission_id,finding_id,revision,observation_id,direction) VALUES (%s,%s,1,%s,'SUPPORT')",(x['mission'],x['finding'],x['observation']))
        finalize(conn,x,'FINDING',x['finding'])
        claim = uuid4()
        conn.execute("INSERT INTO mission_claims(id,mission_id,frame_digest,client_claim_key,claim_type,wording,status,created_by) VALUES (%s,%s,%s,%s,'OBSERVATION','Claim','WITHHELD','schema-control')",(claim,x['mission'],'a'*64,str(claim)))
        conn.execute("INSERT INTO research_handoff_references(mission_id,handoff_id,reference_kind,reference_id,claim_id) VALUES (%s,%s,'CLAIM',%s,%s)",(x['mission'],x['handoff'],claim,claim))
        finalize(conn,x,'HANDOFF',x['handoff'])
    fresh = uuid4()
    with conn.transaction():
        conn.execute("INSERT INTO research_handoffs(handoff_id,mission_id,work_id,input_id,expected_version,ownership_fence,consumer_ref,result) VALUES (%s,%s,%s,%s,2,'fence','consumer','Revised')",(fresh,x['mission'],x['work'],x['inputs']))
        conn.execute("INSERT INTO research_finding_revisions(finding_id,revision,predecessor_revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (%s,2,1,%s,%s,%s,%s,'DESCRIPTIVE','Revised')",(x['finding'],x['mission'],x['work'],fresh,x['inputs']))
        conn.execute("INSERT INTO research_finding_observations(mission_id,finding_id,revision,observation_id,direction) VALUES (%s,%s,2,%s,'CONTRADICTION')",(x['mission'],x['finding'],x['observation']))
        finalize(conn,x,'FINDING',x['finding'],2)
        finalize(conn,x,'HANDOFF',fresh)
    assert conn.execute('SELECT revision FROM research_finding_revisions WHERE finding_id=%s ORDER BY revision',(x['finding'],)).fetchall() == [(1,),(2,)]
    canonical = {t: rows(conn,t) for t in ('sources','observations')}
    conn.execute('DELETE FROM research_missions WHERE id=%s',(x['mission'],))
    assert all(rows(conn,t) == [] for t in TABLES)
    assert {t: rows(conn,t) for t in canonical} == canonical


def test_handoff_child_waits_for_finalization_and_refuses_committed_seal(schema_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    conn = schema_db
    x = arrange(conn)
    conn.execute('INSERT INTO mission_progress_revisions(mission_id,revision) VALUES (%s,4)',(x['mission'],))
    entered = Event()
    worker_pid = []

    def append_child():
        with psycopg.connect(conn.info.dsn, password=conn.info.password, autocommit=True) as child:
            child.execute("SET statement_timeout='5s'")
            worker_pid.append(child.info.backend_pid)
            entered.set()
            try:
                child.execute("INSERT INTO research_finding_revisions(handoff_ordinal,finding_id,revision,mission_id,work_id,handoff_id,input_id,result_type,statement) VALUES (2,%s,1,%s,%s,%s,%s,'DESCRIPTIVE','Late racing finding')",(uuid4(),x['mission'],x['work'],x['handoff'],x['inputs']))
            except psycopg.errors.CheckViolation as failure:
                return failure.diag.message_primary
            return 'INSERT_ACCEPTED'

    with ThreadPoolExecutor(max_workers=1) as executor:
        with conn.transaction():
            # Only production metadata finalization may acquire the owner lock.
            finalize(conn,x,'HANDOFF',x['handoff'])
            future = executor.submit(append_child)
            assert entered.wait(3), 'Contender did not enter actual database connection'
            deadline = monotonic()+3
            while conn.info.backend_pid not in conn.execute('SELECT pg_blocking_pids(%s)',(worker_pid[0],)).fetchone()[0]:
                assert not future.done(), 'Child escaped physical owner lock before finalization commit'
                assert monotonic() < deadline, 'Contender did not reach physical owner lock'
                sleep(0.01)
        assert future.result(timeout=3) == 'Finalized research collection is immutable'
    assert conn.execute('SELECT count(*) FROM research_finding_revisions WHERE handoff_id=%s',(x['handoff'],)).fetchone() == (1,)
