"""Synthetic-confirmation offline driver controls; not owner approval or real provider UAT."""
from pathlib import Path
from dataclasses import replace
from uuid import uuid4
import pytest
from ignis.domain.follow_up_admission import digest
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.follow_up_host_activation import PreparedCanonicalSQLite
from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
from tests.unit.test_follow_up_provider_bridge import setup_bridge
from tests.unit.test_mission_claims import BRIEF, _manifest

from ignis.infrastructure import follow_up_root_composition as driver
import json
INSTRUCTION=json.loads((Path(__file__).parents[1]/'fixtures'/'follow_up_root_scope.json').read_text())


def framing():
    brief = dict(BRIEF, geo='VN', timeframe='30d', decision='Synthetic descriptive sample decision')
    receipt = {'status':'CONFIRMED','reference':'SYNTHETIC_ONLY_BRIEF_CONFIRMATION',
        'owner_reference':INSTRUCTION['reference'], 'payload_digest':digest(brief),
        'collection_scope_digest':digest(INSTRUCTION),'confirmed_by':'synthetic-test-owner'}
    return brief, receipt


def _retained(paths):
    """Physical identity and exact bytes of retained owned files."""
    return [(path.stat().st_dev,path.stat().st_ino,path.read_bytes()) for path in paths]


@pytest.mark.parametrize('change', ['proposed','tampered','scope','missing'])
@pytest.mark.asyncio
async def test_unconfirmed_or_changed_brief_refuses_before_storage_or_credential(tmp_path,change):
    brief, receipt = framing()
    if change=='proposed':receipt['status']='PROPOSED'
    if change=='tampered':brief['hypothesis']='Changed after synthetic confirmation'
    if change=='scope':brief['geo']='US';receipt['payload_digest']=digest(brief)
    if change=='missing':receipt=None
    root=tmp_path/'must-not-create'
    def resolve():raise AssertionError('Credential resolver crossed refused Brief boundary')
    with pytest.raises(ValueError,match='EXPLICIT_COMPATIBLE_BRIEF_CONFIRMATION_REQUIRED'):
        await driver.bootstrap_confirmed_parent(root=root,brief=brief,receipt=receipt,
            instruction=INSTRUCTION,resolve_credential=resolve,
            transport=None,quota_manager=None,clusterer=None)
    assert not root.exists()


@pytest.mark.asyncio
async def test_prepared_store_refuses_foreign_adoption_and_source_payload_before_seal(tmp_path):
    root=tmp_path/'foreign';root.mkdir();(root/'canonical.sqlite3').write_bytes(b'Foreign owner bytes')
    with pytest.raises(FileExistsError):
        PreparedCanonicalSQLite(root,owner_reference='synthetic-owner',collection_scope_digest='a'*64)
    assert (root/'canonical.sqlite3').read_bytes()==b'Foreign owner bytes'
    prepared=PreparedCanonicalSQLite(tmp_path/'owned',owner_reference='synthetic-owner',collection_scope_digest='a'*64)
    await prepared.repository._ensure_schema()
    with pytest.raises(Exception):
        await prepared.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
            raw_title='Forbidden pre-seal source payload',source_url='https://example.invalid/pre-seal')])
    with prepared.repository._get_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
        assert connection.execute('SELECT COUNT(*) FROM sources').fetchone()[0]==0
    await prepared.repository.close()


@pytest.mark.asyncio
async def test_actual_parent_driver_executes_bounded_plan_then_assigns_completed_frame(tmp_path):
    _,_,_,_,plugin,calls,credentials,quota,_,_=setup_bridge()
    brief,receipt=framing()
    class Clusterer:
        async def cluster_signals(self,signals):return []
    result=await driver.bootstrap_confirmed_parent(root=tmp_path/'actual-driver',brief=brief,receipt=receipt,
        instruction=INSTRUCTION,resolve_credential=plugin._resolve_credential,
        transport=plugin._transport,quota_manager=quota,clusterer=Clusterer())
    try:
        assert result['status']=='PARENT_EXECUTED_ANALYSIS_ASSIGNED'
        assert result['observations']==5 and result['child_status']=='NOT_ADMITTED'
        assert result['precollection_identity_kind']=='CANONICAL_MISSION_CORRELATION_NOT_RESEARCH_WORK'
        assert result['precollection_scope_fingerprint']!=result['frame_digest']
        snapshot=await result['executor']._workspace_store.load_mission_evidence_snapshot(result['host'].confirmation.selected_parent_id)
        assert snapshot.mission.status=='COMPLETED' and snapshot.brief.falsifiers==tuple(brief['falsifiers'])
        assert all(outcome.collection_plan_digest for outcome in snapshot.outcomes)
        import json
        journal=await result['executor']._workspace_store.latest_run_journal(snapshot.mission.id)
        persisted=json.loads(journal.journal_path.read_text())['collection_plan']
        assert result['executor']._collection_queries(persisted)==['n8n Việt Nam']
        assert {outcome.collection_plan_digest for outcome in snapshot.outcomes}=={persisted['plan_digest']}
        safe={key:value for key,value in result.items() if isinstance(value,(str,int))}
        safe['provider_endpoints']=[path.rsplit('/',1)[-1] for path,params in calls]
        safe['credential_resolutions']=len(credentials)
        safe['durable_calls']=result['bridge'].budget._used
        (tmp_path/'synthetic-outcome.json').write_text(json.dumps(safe,indent=2)+'\n')
        research=await result['repository'].load_research_work(snapshot.mission.id)
        assert len(research.work_items)==1 and research.work_items[0].inputs.frame_digest==result['frame_digest']
        assert research.work_items[0].run_id==snapshot.outcomes[0].run_id
        searches=[params for path,params in calls if path.endswith('/search')]
        assert len(searches)==1 and searches[0]['q']=='n8n Việt Nam' and searches[0]['maxResults']=='5'
        assert searches[0]['regionCode']=='VN' and searches[0]['relevanceLanguage']=='vi'
        assert len(calls)==len(credentials)<=4
        refused=await driver.run_canonical_parent(host=result['host'],bridge=result['bridge'],
            executor=result['executor'],parent_work_id=result['work_id'])
        assert refused=={'status':'REFUSED','reason_code':'PARENT_ALREADY_TERMINAL'}
        assert len(calls)==len(credentials)<=4
    finally:
        await result['host'].revoke()
        await result['repository'].close()


def test_default_market_policy_includes_falsifier_query():
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.domain.research_workspace import MarketBriefRevision
    from datetime import datetime,timezone
    mission=ResearchMission(title='Synthetic bounded query control',keywords=['n8n Việt Nam'],platforms=[PlatformType.YOUTUBE],geo_code='VN',timeframe='30d')
    manifest=replace(_manifest(),mission_id=mission.id,required_channels=('youtube',),quota_budget={'queries':2})
    brief,_=framing()
    revision=MarketBriefRevision(workspace_id=uuid4(),mission_id=mission.id,revision_number=1,
        confirmed_by='synthetic-test-owner',**brief)
    executor=ExecuteMissionUseCase(None,None,None)
    plan=executor._collection_plan_for_brief(mission,manifest,{},revision)
    assert executor._collection_queries(plan)==['n8n Việt Nam','Retailers report no material stockout cost']


@pytest.mark.parametrize('field,value', [('video_limit',6),('search_calls',3),('other_calls',5),
    ('run_minutes',16),('retention','SEVEN_DAYS'),('source','unapproved'),('geo','GeoCode.US')])
@pytest.mark.asyncio
async def test_private_root_scope_refuses_expansion_before_any_storage(tmp_path,field,value):
    instruction=dict(INSTRUCTION,**{field:value})
    brief,receipt=framing()
    receipt['collection_scope_digest']=digest(instruction)
    def resolve():raise AssertionError('Expanded scope resolved a credential')
    with pytest.raises(ValueError,match='OWNER_SCOPE_CONFIRMATION_REQUIRED'):
        await driver.bootstrap_confirmed_parent(root=tmp_path/'no-expanded-storage',brief=brief,
            receipt=receipt,instruction=instruction,resolve_credential=resolve,
            transport=None,quota_manager=None,clusterer=None)
    assert not (tmp_path/'no-expanded-storage').exists()


def _synthetic_tutorial_transport(calls):
    import httpx
    from datetime import datetime,timezone
    now=datetime.now(timezone.utc)
    async def response(request):
        calls.append(request.url.path.rsplit('/',1)[-1])
        if request.url.path.endswith('/search'):
            return httpx.Response(200,json={'items':[{'id':{'videoId':'synthetic-retained'}}]})
        return httpx.Response(200,json={'items':[{'id':'synthetic-retained','snippet':{
            'title':'Hướng dẫn n8n: workflow được lưu giữ','description':'Synthetic retained description.',
            'publishedAt':now.isoformat()},'statistics':{'viewCount':'10'}}]})
    return httpx.MockTransport(response)


@pytest.mark.asyncio
async def test_obsolete_seven_day_instruction_cannot_enroll_new_pilot_data_for_deletion(tmp_path):
    from tests.unit.test_follow_up_provider_bridge import Quota
    seven_day={key:value for key,value in INSTRUCTION.items() if key!='retention'}|{'retention_days':7}
    brief,receipt=framing()
    receipt['collection_scope_digest']=digest(seven_day)
    calls,credentials=[],[]
    def resolve():credentials.append('synthetic-lookup');return 'synthetic-only'
    class Clusterer:
        async def cluster_signals(self,signals):return []
    root=tmp_path/'no-seven-day-storage'
    try:
        result=await driver.bootstrap_confirmed_parent(root=root,brief=brief,receipt=receipt,
            instruction=seven_day,resolve_credential=resolve,transport=_synthetic_tutorial_transport(calls),
            quota_manager=Quota(),clusterer=Clusterer())
    except ValueError as error:
        refusal=str(error)
    else:
        refusal=None
        await result['host'].revoke()
        await result['repository'].close()
    assert refusal=='OWNER_SCOPE_CONFIRMATION_REQUIRED' and not root.exists() and calls==credentials==[], (
        'Obsolete seven-day retention admitted new pilot data for expiry deletion: '
        f'deletion_receipt={(root/"canonical"/"ownership.json").exists()}, provider_calls={len(calls)}')


@pytest.mark.asyncio
async def test_persistent_pilot_completion_closes_resources_and_retains_data_across_restart(tmp_path):
    import sqlite3
    from datetime import timedelta
    from tests.unit.test_follow_up_provider_bridge import Quota
    from ignis.infrastructure.follow_up_host_activation import IsolatedCanonicalSQLite
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention
    brief=json.loads((Path(__file__).parents[1]/'fixtures'/'follow_up_tutorial_brief.json').read_text())
    receipt={'status':'CONFIRMED','reference':'SYNTHETIC_ONLY_PERSISTENT_BINDING',
        'owner_reference':INSTRUCTION['reference'],'payload_digest':digest(brief),
        'collection_scope_digest':digest(INSTRUCTION),'confirmed_by':'synthetic-test-owner'}
    calls,credentials=[],[]
    def resolve():credentials.append('synthetic-lookup');return 'synthetic-only'
    class Clusterer:
        async def cluster_signals(self,signals):return []
    root=tmp_path/'persistent-owned'
    result=await driver.bootstrap_confirmed_parent(root=root,brief=brief,receipt=receipt,
        instruction=INSTRUCTION,resolve_credential=resolve,transport=_synthetic_tutorial_transport(calls),
        quota_manager=Quota(),clusterer=Clusterer())
    host,canonical,accounting=result['host'],result['canonical'],result['accounting']
    metadata=canonical.generated_metadata
    try:
        bounds=host.confirmation.bounds
        assert bounds.retention_until is None
        assert bounds.deadline-bounds.started_at==timedelta(minutes=15)
        assert (bounds.queries,bounds.video_limit,bounds.search_calls,bounds.other_calls)==(
            ('n8n Việt Nam','n8n tự động hóa'),5,2,4)
        assert json.loads((root/'generated-ownership.json').read_text())['retention_until'] is None
        store=result['executor']._workspace_store
        snapshot=await store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
        assert snapshot.manifest.retention_policy=='caller-retained-until-explicit-user-deletion'
        workspace=await store.get_research_workspace(snapshot.mission.workspace_id)
        journal=await store.latest_run_journal(snapshot.mission.id)
        signal=snapshot.signals[0]
        finished=await driver.finish_canonical_parent_analysis(result,assessments=[{
            'observation_id':str(signal.observation_id),'relation':'CONTEXT_ONLY','purpose':'CONTEXT',
            'confidence':1.0,'reason_code':'ADJACENT_ONLY','judged_by':'synthetic-retention-control',
            'evidence_role':'CONTEXT'}],candidates=[],judged_by='synthetic-retention-control')
    finally:
        await host.revoke()
        await result['repository'].close()
    recovery=finished['recovery']
    assert finished['accounting_close']==recovery.accounting_close=='CLOSED'
    assert host._revoked and not host._tokens and not host._tasks
    assert canonical.closed and metadata.closed and not metadata.active_run
    paths=(canonical.path,canonical.marker,workspace.manifest_path,journal.journal_path,accounting.path)
    before=_retained(paths)
    later=bounds.deadline+timedelta(days=8)
    host.clock=lambda:later
    with pytest.raises(FollowUpExecutionBoundaryError):await recovery.purge(now=later)
    with pytest.raises(FollowUpExecutionBoundaryError):
        await driver.expire_owned_storage(host,canonical,result['repository'],accounting)
    with pytest.raises(FollowUpExecutionBoundaryError):accounting.purge(bounds,now=later)
    with pytest.raises(FollowUpExecutionBoundaryError):canonical._purge_closed(now=later)
    with pytest.raises(FollowUpExecutionBoundaryError):metadata.purge(now=later)
    assert _retained(paths)==before
    assert not (canonical.root/'deletion.json').exists()
    with sqlite3.connect(canonical.path.as_uri()+'?mode=ro',uri=True) as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==1
        assert connection.execute('SELECT COUNT(*) FROM mission_evidence_qualifications').fetchone()[0]==1
    with sqlite3.connect(accounting.path.as_uri()+'?mode=ro',uri=True) as connection:
        assert connection.execute('SELECT searches,others,closed,purged FROM runs').fetchall()==[(1,1,1,0)]
        assert connection.execute('SELECT COUNT(*) FROM cache').fetchone()[0]>=1
        assert connection.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==0
    # A fresh process reads retained state; it restores no writer, source budget or deletion.
    reopened=GeneratedWorkspaceRetention(root,owner_reference=metadata.owner_reference,
        scope_digest=metadata.scope_digest,retention_until=None)
    assert reopened.closed
    with pytest.raises(FollowUpExecutionBoundaryError):reopened.write(root/'forbidden.json','Forbidden write')
    with pytest.raises(FollowUpExecutionBoundaryError):reopened.purge(now=later)
    with pytest.raises(FollowUpExecutionBoundaryError):IsolatedCanonicalSQLite(canonical.root,host.confirmation)
    restarted=PrivateRunStorage(root/'accounting',authorize=lambda *args:False)
    assert restarted.counts(bounds)=={'search':1,'other':1}
    with pytest.raises(FollowUpExecutionBoundaryError):DurableRunCallBudget(bounds,storage=restarted)
    with pytest.raises(FollowUpExecutionBoundaryError):restarted.purge(bounds,now=later)
    assert _retained(paths)==before and not (root/'forbidden.json').exists()
    assert calls==['search','videos'] and len(credentials)==2


async def tutorial_parent_control(tmp_path, *, brief, receipt, instruction, description_present):
    """Actual private consumer with synthetic HTTP; supplied receipt is never invented here."""
    import httpx
    from datetime import datetime,timedelta,timezone
    from tests.unit.test_follow_up_provider_bridge import Quota
    calls=[];credentials=[];now=datetime.now(timezone.utc)
    async def response(request):
        calls.append((request.url.path,dict(request.url.params)))
        if request.url.path.endswith('/search'):
            return httpx.Response(200,json={'items':[{'id':{'videoId':'synthetic-tutorial'}}]})
        snippet={'title':'Hướng dẫn n8n: tạo workflow thử nghiệm','publishedAt':now.isoformat(),
            'channelTitle':'Synthetic tutorial channel'}
        if description_present is not False:
            snippet['description']=(description_present if isinstance(description_present,str)
                else 'Synthetic public description; no quality or adoption proof.')
        return httpx.Response(200,json={'items':[{'id':'synthetic-tutorial','snippet':snippet,
            'statistics':{'viewCount':'10','likeCount':'1','commentCount':'0'}}]})
    def resolve():credentials.append('synthetic-lookup');return 'synthetic-only'
    class Clusterer:
        async def cluster_signals(self,signals):return []
    result=await driver.bootstrap_confirmed_parent(root=tmp_path/'tutorial-owned',brief=brief,receipt=receipt,
        instruction=instruction,resolve_credential=resolve,transport=httpx.MockTransport(response),
        quota_manager=Quota(),clusterer=Clusterer())
    try:
        host=result['host'];bounds=host.confirmation.bounds
        store=result['executor']._workspace_store
        snapshot=await store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
        assert snapshot.mission.keywords==instruction['queries'][:1]
        assert snapshot.brief.decision==brief['decision'] and snapshot.brief.hypothesis==brief['hypothesis']
        assert snapshot.brief.falsifiers==tuple(brief['falsifiers'])
        assert result['observations']==1 and result['child_status']=='NOT_ADMITTED'
        assert len(calls)==len(credentials)==2
        assert [path.rsplit('/',1)[-1] for path,params in calls]==['search','videos']
        searches=[params for path,params in calls if path.endswith('/search')]
        assert searches[0]['q']==instruction['queries'][0] and searches[0]['maxResults']=='5'
        assert searches[0]['regionCode']=='VN' and searches[0]['relevanceLanguage']=='vi'
        assert 'pageToken' not in searches[0]
        assert searches[0]['publishedAfter']==(bounds.started_at-timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert bounds.deadline-bounds.started_at==timedelta(minutes=15)
        assert bounds.retention_until is None
        assert (bounds.search_calls,bounds.other_calls)==(2,4)
        assert result['bridge'].budget._used=={'search':1,'other':1}
        assert snapshot.signals[0].raw_title=='Hướng dẫn n8n: tạo workflow thử nghiệm'
        assert snapshot.signals[0].source_url=='https://www.youtube.com/watch?v=synthetic-tutorial'
        signal=snapshot.signals[0]
        expected_description=(description_present if isinstance(description_present,str)
            else 'Synthetic public description; no quality or adoption proof.')
        if description_present is False:
            assert 'description' not in signal.metadata
        else:
            assert signal.metadata['description']==expected_description
        assert signal.observation_id is not None and signal.source_id is not None
        readback=await result['repository'].get_mission_signals(snapshot.mission.id)
        assert len(readback)==1
        assert (readback[0].observation_id,readback[0].source_id,readback[0].metadata)==(
            signal.observation_id,signal.source_id,signal.metadata)
        assert not snapshot.qualifications and not snapshot.claims
        terminal_refusal=await driver.run_canonical_parent(host=host,bridge=result['bridge'],
            executor=result['executor'],parent_work_id=result['work_id'])
        assert terminal_refusal=={'status':'REFUSED','reason_code':'PARENT_ALREADY_TERMINAL'}
        from ignis.domain.research_workspace import (EvidenceQualification,EvidencePurpose,
            QualificationRelation,QualificationReason,EvidenceDirection,compute_frame_fingerprint,
            StaleEvidenceQualificationError)
        qualification=EvidenceQualification(mission_id=snapshot.mission.id,
            observation_id=signal.observation_id,brief_revision_id=snapshot.brief.brief_revision_id,
            frame_fingerprint=compute_frame_fingerprint(snapshot.mission,snapshot.brief),
            relation=QualificationRelation.CONTEXT_ONLY,purpose=EvidencePurpose.CONTEXT,
            confidence=1.0,reason_code=QualificationReason.ADJACENT_ONLY,
            judged_by='offline-description-control',evidence_role=EvidenceDirection.CONTEXT)
        with pytest.raises(StaleEvidenceQualificationError):
            await result['repository'].commit_evidence_qualifications(snapshot.mission.id,
                [replace(qualification,frame_fingerprint='f'*64)])
        await result['repository'].commit_evidence_qualifications(snapshot.mission.id,[qualification])
        qualified=await store.load_mission_evidence_snapshot(snapshot.mission.id)
        assert len(qualified.qualifications)==1 and not qualified.claims
        assert qualified.qualifications[0].observation_id==signal.observation_id
        assert qualified.qualifications[0].frame_fingerprint==qualification.frame_fingerprint
        assert qualified.qualifications[0].relation is QualificationRelation.CONTEXT_ONLY
        assert qualified.signals[0].source_id==signal.source_id
        journal=await store.latest_run_journal(snapshot.mission.id)
        plan=json.loads(journal.journal_path.read_text())['collection_plan']
        assert result['executor']._collection_queries(plan)==instruction['queries'][:1]
        research=await result['repository'].load_research_work(snapshot.mission.id)
        assert len(research.work_items)==1
        follow_ups=await result['repository'].load_mission_follow_ups(snapshot.mission.id)
        assert not follow_ups.work_items and not follow_ups.relationships
        refusal=await driver.run_canonical_parent(host=host,bridge=result['bridge'],
            executor=result['executor'],parent_work_id=result['work_id'])
        assert refusal=={'status':'REFUSED','reason_code':'CURRENT_CANONICAL_PARENT_FRAME_REQUIRED'}
        retained=_retained((result['canonical'].path,journal.journal_path))
        host.clock=lambda:bounds.deadline+timedelta(days=8)
        with pytest.raises(FollowUpExecutionBoundaryError):
            await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
        assert _retained((result['canonical'].path,journal.journal_path))==retained
        assert len(calls)==len(credentials)==2
        return {'status':'OFFLINE_CANONICAL_COMPOSITION_VERIFIED','observations':1,
            'description_state':('MISSING' if description_present is False else
                'EMPTY' if expected_description=='' else 'RETAINED'),'provider_fields_received':
                ['title','description'] if description_present is not False else ['title'],
            'retained_content_fields':(['raw_title'] if description_present is False else
                ['raw_title','description']),'provider_endpoints':['search','videos'],
            'search_calls':1,'other_calls':1,'child_status':'NOT_ADMITTED','retention':'UNTIL_EXPLICIT_USER_DELETION',
            'brief_digest':digest(brief),'scope_digest':digest(instruction),'live_readiness':'NOT_ESTABLISHED'}
    finally:
        await result['host'].revoke()
        await result['repository'].close()


@pytest.mark.parametrize('description_present',[False,True,''])
@pytest.mark.asyncio
async def test_tutorial_brief_is_bound_but_description_missingness_remains_explicit(tmp_path,description_present):
    brief=json.loads((Path(__file__).parents[1]/'fixtures'/'follow_up_tutorial_brief.json').read_text())
    receipt={'status':'CONFIRMED','reference':'SYNTHETIC_ONLY_TUTORIAL_BINDING',
        'owner_reference':INSTRUCTION['reference'],'payload_digest':digest(brief),
        'collection_scope_digest':digest(INSTRUCTION),'confirmed_by':'synthetic-test-owner'}
    summary=await tutorial_parent_control(tmp_path,brief=brief,receipt=receipt,instruction=INSTRUCTION,
        description_present=description_present)
    assert summary['description_state']==('MISSING' if description_present is False else
        'EMPTY' if description_present=='' else 'RETAINED')


async def failed_startup_control(tmp_path,monkeypatch,phase='scope'):
    from tests.unit.test_follow_up_provider_bridge import Quota
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    root=tmp_path/'startup-recovery'
    original_open=Path.open
    def fail_scope(path,*args,**kwargs):
        if path==root/'root-scope.json':raise OSError('Synthetic scope startup failure')
        return original_open(path,*args,**kwargs)
    def fail_registration(*args,**kwargs):raise OSError('Synthetic registry startup failure')
    calls=[]
    def resolve():calls.append('forbidden');raise AssertionError('Failed startup resolved a credential')
    brief,receipt=framing()
    with monkeypatch.context() as patch:
        if phase=='scope':patch.setattr(Path,'open',fail_scope)
        else:patch.setattr(ConnectorPluginRegistry,'register',fail_registration)
        with pytest.raises(driver.StartupRetentionFailure) as failed:
            await driver.bootstrap_confirmed_parent(root=root,brief=brief,receipt=receipt,instruction=INSTRUCTION,
                resolve_credential=resolve,transport=None,quota_manager=Quota(),clusterer=None)
    recovery=failed.value.recovery
    assert recovery._metadata.closed and not recovery._metadata.active_run and recovery._canonical.closed
    assert calls==[]
    return root,recovery,calls


@pytest.mark.parametrize('phase',['scope','registry'])
@pytest.mark.asyncio
async def test_failed_startup_closes_and_retains_owned_data_without_expiry_purge(tmp_path,monkeypatch,phase):
    from datetime import timedelta
    import sqlite3
    from ignis.infrastructure.follow_up_host_activation import open_owned_canonical_repository
    root,recovery,calls=await failed_startup_control(tmp_path,monkeypatch,phase)
    canonical=recovery._canonical
    bounds=recovery.confirmation.bounds
    assert bounds.retention_until is None
    manifest=root/next(key for key in recovery._metadata._load()['files'] if key.endswith('/workspace.json'))
    paths=(canonical.path,canonical.marker,manifest)
    before=_retained(paths)
    foreign=root/'foreign-user-note.txt';foreign.write_bytes(b'Foreign owner bytes')
    with sqlite3.connect(canonical.path.as_uri()+'?mode=ro',uri=True) as connection:
        assert connection.execute('SELECT id FROM research_missions').fetchall()==[(str(recovery.confirmation.selected_parent_id),)]
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
    with pytest.raises(FollowUpExecutionBoundaryError):open_owned_canonical_repository(canonical)
    with pytest.raises(FollowUpExecutionBoundaryError):recovery._metadata.write(root/'new.json','Forbidden ingress')
    later=bounds.deadline+timedelta(days=8)
    with pytest.raises(FollowUpExecutionBoundaryError):await recovery.purge(now=later)
    assert _retained(paths)==before and foreign.read_bytes()==b'Foreign owner bytes' and calls==[]
    assert not (canonical.root/'deletion.json').exists() and not (root/'new.json').exists()
    if phase=='scope':
        assert recovery._host is None and recovery._accounting is None
        assert recovery.accounting_close=='NOT_ALLOCATED'
    else:
        assert recovery._host._revoked and recovery._host._tokens==0
        assert recovery.accounting_close=='CLOSED'
        assert recovery._accounting.counts(bounds)=={'search':0,'other':0}
        with pytest.raises(FollowUpExecutionBoundaryError):recovery._accounting.purge(bounds,now=later)
        with pytest.raises(FollowUpExecutionBoundaryError):recovery._accounting.current(bounds)


async def _persistent_parent(tmp_path,calls,credentials):
    from tests.unit.test_follow_up_provider_bridge import Quota
    brief=json.loads((Path(__file__).parents[1]/'fixtures'/'follow_up_tutorial_brief.json').read_text())
    receipt={'status':'CONFIRMED','reference':'SYNTHETIC_ONLY_CLOSURE_BINDING',
        'owner_reference':INSTRUCTION['reference'],'payload_digest':digest(brief),
        'collection_scope_digest':digest(INSTRUCTION),'confirmed_by':'synthetic-test-owner'}
    def resolve():credentials.append('synthetic-lookup');return 'synthetic-only'
    class Clusterer:
        async def cluster_signals(self,signals):return []
    return await driver.bootstrap_confirmed_parent(root=tmp_path/'closure-owned',brief=brief,receipt=receipt,
        instruction=INSTRUCTION,resolve_credential=resolve,transport=_synthetic_tutorial_transport(calls),
        quota_manager=Quota(),clusterer=Clusterer())


def _accounting_row(accounting):
    import sqlite3
    with sqlite3.connect(accounting.path.as_uri()+'?mode=ro',uri=True) as connection:
        return (connection.execute('SELECT searches,others,closed,purged FROM runs').fetchone(),
            connection.execute('SELECT COUNT(*) FROM cache').fetchone()[0])


@pytest.mark.parametrize('outcome',['completed','exception','cancellation'])
@pytest.mark.asyncio
async def test_locked_accounting_close_reports_pending_then_close_only_retry_verifies_closed(tmp_path,monkeypatch,outcome):
    import asyncio
    import sqlite3
    from datetime import timedelta
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    calls,credentials=[],[]
    result=await _persistent_parent(tmp_path,calls,credentials)
    host,canonical,accounting=result['host'],result['canonical'],result['accounting']
    bounds=host.confirmation.bounds
    binding=next(iter(host._enrollments.values()))[0]
    store=result['executor']._workspace_store
    snapshot=await store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
    signal=snapshot.signals[0]
    before_row=_accounting_row(accounting)
    assert before_row==((1,1,0,0),before_row[1]) and before_row[1]>=1
    if outcome!='completed':
        async def fail(self,*args,**kwargs):
            if outcome=='cancellation':raise asyncio.CancelledError()
            raise ValueError('SYNTHETIC_ANALYSIS_FAILURE')
        monkeypatch.setattr(GetMissionAnalysisUseCase,'execute',fail)
    # A disposable second writer holds the accounting database during closure.
    lock=sqlite3.connect(accounting.path,timeout=0)
    lock.execute('BEGIN IMMEDIATE')
    try:
        expected=(driver.CanonicalAnalysisRetentionFailure if outcome=='exception'
            else asyncio.CancelledError if outcome=='cancellation' else None)
        assessments=[{'observation_id':str(signal.observation_id),'relation':'CONTEXT_ONLY','purpose':'CONTEXT',
            'confidence':1.0,'reason_code':'ADJACENT_ONLY','judged_by':'synthetic-closure-control',
            'evidence_role':'CONTEXT'}]
        if expected is None:
            finished=await driver.finish_canonical_parent_analysis(result,assessments=assessments,
                candidates=[],judged_by='synthetic-closure-control')
            recovery,disposition=finished['recovery'],finished.get('accounting_close')
        else:
            with pytest.raises(expected) as caught:
                await driver.finish_canonical_parent_analysis(result,assessments=assessments,
                    candidates=[],judged_by='synthetic-closure-control')
            recovery=caught.value.recovery
            disposition=getattr(recovery,'accounting_close',None)
    finally:
        lock.rollback();lock.close()
    row=_accounting_row(accounting)
    assert row==before_row, 'Failed closure changed counts, closure state or cache rows'
    assert disposition=='PENDING', (
        f'Accounting row closed={row[0][2]} after a failed durable close, but disposition={disposition!r}')
    assert getattr(recovery,'accounting_close',None)=='PENDING'
    assert host._revoked and canonical.closed and canonical.generated_metadata.closed
    with pytest.raises(FollowUpExecutionBoundaryError):
        async with host.hold_parent(binding):pass
    paths=(canonical.path,canonical.marker,accounting.path)
    retained=_retained(paths)
    assert recovery.close_accounting()=='CLOSED'
    assert recovery.accounting_close=='CLOSED'
    assert _accounting_row(accounting)==((1,1,1,0),before_row[1])
    assert recovery.close_accounting()=='CLOSED'
    assert _accounting_row(accounting)==((1,1,1,0),before_row[1])
    with pytest.raises(FollowUpExecutionBoundaryError):accounting.current(bounds)
    with pytest.raises(FollowUpExecutionBoundaryError):await recovery.purge(now=bounds.deadline+timedelta(days=8))
    assert _retained(paths)[:2]==retained[:2] and not (canonical.root/'deletion.json').exists()
    assert calls==['search','videos'] and len(credentials)==2


@pytest.mark.asyncio
async def test_failed_startup_with_failing_accounting_close_reports_pending_and_retry_closes(tmp_path,monkeypatch):
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage
    original_close=PrivateRunStorage.close
    def failing_close(self,bounds):raise FollowUpExecutionBoundaryError()
    with monkeypatch.context() as patch:
        patch.setattr(PrivateRunStorage,'close',failing_close)
        root,recovery,calls=await failed_startup_control(tmp_path,monkeypatch,'registry')
    bounds=recovery.confirmation.bounds
    row=_accounting_row(recovery._accounting)
    assert row[0]==(0,0,0,0)
    assert getattr(recovery,'accounting_close',None)=='PENDING', (
        f'Accounting row closed={row[0][2]} after startup failure, but disposition was not PENDING')
    assert PrivateRunStorage.close is original_close
    assert recovery.close_accounting()=='CLOSED'
    assert _accounting_row(recovery._accounting)==((0,0,1,0),row[1])
    with pytest.raises(FollowUpExecutionBoundaryError):recovery._accounting.current(bounds)
    assert calls==[]


async def _registry_startup_failure(tmp_path,failures):
    """Fail bootstrap after host and accounting allocation; return the propagated failure."""
    from tests.unit.test_follow_up_provider_bridge import Quota
    calls=[]
    def resolve():
        calls.append('forbidden')
        raise AssertionError('Failed startup resolved a credential')
    brief,receipt=framing()
    with pytest.raises(driver.StartupRetentionFailure) as failed:
        await driver.bootstrap_confirmed_parent(root=tmp_path/'startup-recovery',brief=brief,receipt=receipt,
            instruction=INSTRUCTION,resolve_credential=resolve,transport=None,quota_manager=Quota(),clusterer=None)
    assert calls==[]
    # The typed wrapper keeps the exact original failure as its private context, never a cleanup error.
    assert failed.value.__context__ is failures[0] and failed.value.__suppress_context__
    return failed.value.recovery


def _failing_registration(failures):
    def fail_registration(*args,**kwargs):
        failures.append(OSError('Synthetic registry startup failure'))
        raise failures[-1]
    return fail_registration


@pytest.mark.asyncio
async def test_failed_startup_revoke_failure_keeps_original_failure_and_retains_unrevoked_storage(tmp_path,monkeypatch):
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    original_revoke=RootHostController.revoke
    attempts,failures=[],[]
    async def failing_revoke(self,*,timeout=5):
        attempts.append(self)
        if len(attempts)==1:
            raise RuntimeError('Synthetic revoke failure before publication')
        await original_revoke(self,timeout=timeout)
    monkeypatch.setattr(RootHostController,'revoke',failing_revoke)
    with monkeypatch.context() as patch:
        patch.setattr(ConnectorPluginRegistry,'register',_failing_registration(failures))
        recovery=await _registry_startup_failure(tmp_path,failures)
    host,bounds=recovery._host,recovery.confirmation.bounds
    assert attempts==[host] and host.confirmation==recovery.confirmation
    # Authority was never revoked, so storage stays open and pending; accounting closes independently.
    assert not host._revoked and recovery.host_close=='PENDING'
    assert recovery.accounting_close=='CLOSED' and recovery.storage_close=='PENDING'
    assert not recovery._metadata.closed and not recovery._canonical.closed
    assert recovery._database_hash is None
    assert _accounting_row(recovery._accounting)[0]==(0,0,1,0)
    assert await recovery.settle()=={'host':'CLOSED','accounting':'CLOSED','storage':'CLOSED'}
    assert attempts==[host,host] and host._revoked
    assert recovery._metadata.closed and recovery._canonical.closed
    assert recovery._database_hash==driver.sha256(recovery._canonical.path.read_bytes()).hexdigest()
    assert _accounting_row(recovery._accounting)[0]==(0,0,1,0)
    with pytest.raises(FollowUpExecutionBoundaryError):
        recovery._accounting.current(bounds)


async def _pending_holder_recovery(tmp_path,monkeypatch,reads):
    """Startup failure whose published revocation times out on a still-held original token."""
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    original_revoke=RootHostController.revoke
    original_read=Path.read_bytes
    holders,failures=[],[]
    def guarded_read(path):
        # Pending cleanup must not attest active canonical bytes.
        if holders and holders[0]._tokens and path.name=='canonical.sqlite3':
            reads.append(path)
            raise OSError('Synthetic refusal of a pending canonical read')
        return original_read(path)
    async def unsettled_revoke(self,*,timeout=5):
        if not holders:
            # Disposable stand-in for a guarded holder that has not settled when revocation publishes.
            with self._lock:
                self._tokens+=1
                self._settled.clear()
            holders.append(self)
        await original_revoke(self,timeout=0.05)
    monkeypatch.setattr(RootHostController,'revoke',unsettled_revoke)
    if reads is not None:
        monkeypatch.setattr(Path,'read_bytes',guarded_read)
    with monkeypatch.context() as patch:
        patch.setattr(ConnectorPluginRegistry,'register',_failing_registration(failures))
        recovery=await _registry_startup_failure(tmp_path,failures)
    assert holders==[recovery._host]
    return recovery


def _release_holder(host):
    with host._lock:
        host._tokens-=1
    host._settled.set()


@pytest.mark.asyncio
async def test_failed_startup_revoke_timeout_retains_storage_and_digests_only_after_holder_settles(tmp_path,monkeypatch):
    import sqlite3
    from datetime import timedelta
    reads=[]
    recovery=await _pending_holder_recovery(tmp_path,monkeypatch,reads)
    host,bounds=recovery._host,recovery.confirmation.bounds
    # Revocation is published, but quiescence is not observed: host and storage remain pending.
    assert host._revoked and host._tokens==1 and recovery.host_close=='PENDING'
    assert recovery.accounting_close=='CLOSED' and recovery.storage_close=='PENDING'
    assert not recovery._metadata.closed and not recovery._canonical.closed
    assert recovery._database_hash is None and reads==[]
    with pytest.raises(FollowUpExecutionBoundaryError):
        await recovery.purge(now=bounds.deadline+timedelta(days=8))
    # The admitted original holder finishes a final write before settlement.
    with sqlite3.connect(recovery._canonical.path) as connection:
        connection.execute('PRAGMA user_version=7')
    _release_holder(host)
    assert await recovery.settle()=={'host':'CLOSED','accounting':'CLOSED','storage':'CLOSED'}
    assert recovery._metadata.closed and recovery._canonical.closed and reads==[]
    final=recovery._canonical.path.read_bytes()
    assert recovery._database_hash==driver.sha256(final).hexdigest()
    assert _accounting_row(recovery._accounting)[0]==(0,0,1,0)


@pytest.mark.asyncio
async def test_close_only_retry_survives_repeated_cancellation_with_truthful_phases(tmp_path,monkeypatch):
    import asyncio
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    recovery=await _pending_holder_recovery(tmp_path,monkeypatch,None)
    host,accounting=recovery._host,recovery._accounting
    identity=(host,accounting,recovery._canonical,recovery._metadata,recovery.confirmation)
    _release_holder(host)
    blocked=RootHostController.revoke
    entered,release=asyncio.Event(),asyncio.Event()
    async def blocking_revoke(self,*,timeout=5):
        entered.set()
        await release.wait()
        await blocked(self,timeout=timeout)
    monkeypatch.setattr(RootHostController,'revoke',blocking_revoke)
    retry=asyncio.ensure_future(recovery.settle())
    await asyncio.wait_for(entered.wait(),5)
    for _ in range(2):
        retry.cancel()
        await asyncio.sleep(0)
    assert not retry.done(), 'Repeated cancellation abandoned the owned close-only retry'
    release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await retry
    assert caught.value.recovery is recovery
    assert (recovery._host,recovery._accounting,recovery._canonical,recovery._metadata,recovery.confirmation)==identity
    assert (recovery.host_close,recovery.accounting_close,recovery.storage_close)==('CLOSED','CLOSED','CLOSED')
    assert recovery._metadata.closed and recovery._canonical.closed
    monkeypatch.setattr(RootHostController,'revoke',blocked)
    assert await recovery.settle()=={'host':'CLOSED','accounting':'CLOSED','storage':'CLOSED'}
    assert _accounting_row(accounting)[0]==(0,0,1,0)


@pytest.mark.parametrize('mode',['revoke-failure','repeated-cancellation','original-cancellation',
                                  'unpublished-initial-revoke'])
@pytest.mark.asyncio
async def test_analysis_failure_cleanup_survives_revoke_failure_and_repeated_cancellation(tmp_path,monkeypatch,mode):
    import asyncio
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    calls,credentials=[],[]
    result=await _persistent_parent(tmp_path,calls,credentials)
    host,canonical,accounting=result['host'],result['canonical'],result['accounting']
    binding=next(iter(host._enrollments.values()))[0]
    snapshot=await result['executor']._workspace_store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
    signal=snapshot.signals[0]
    before_row=_accounting_row(accounting)
    originals=[]
    async def fail(self,*args,**kwargs):
        originals.append(asyncio.CancelledError() if mode=='original-cancellation'
                         else ValueError('SYNTHETIC_ANALYSIS_FAILURE'))
        raise originals[-1]
    monkeypatch.setattr(GetMissionAnalysisUseCase,'execute',fail)
    original_revoke=RootHostController.revoke
    entered,release,revocations=asyncio.Event(),asyncio.Event(),[]
    async def cleanup_revoke(self,*,timeout=5):
        revocations.append(self)
        if mode=='unpublished-initial-revoke':
            originals.append(RuntimeError('Synthetic revoke failure before publication'))
            raise originals[-1]
        await original_revoke(self,timeout=timeout)
        if len(revocations)>1:
            if mode=='revoke-failure':
                raise RuntimeError('Synthetic revoke failure after publication')
            if mode=='repeated-cancellation':
                entered.set()
                await release.wait()
    monkeypatch.setattr(RootHostController,'revoke',cleanup_revoke)
    assessments=[{'observation_id':str(signal.observation_id),'relation':'CONTEXT_ONLY','purpose':'CONTEXT',
        'confidence':1.0,'reason_code':'ADJACENT_ONLY','judged_by':'synthetic-cleanup-control',
        'evidence_role':'CONTEXT'}]
    task=asyncio.ensure_future(driver.finish_canonical_parent_analysis(result,assessments=assessments,
        candidates=[],judged_by='synthetic-cleanup-control'))
    if mode=='repeated-cancellation':
        await asyncio.wait_for(entered.wait(),5)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
        assert not task.done(), 'Repeated cancellation abandoned owned cleanup before settlement'
        release.set()
    expected=asyncio.CancelledError if 'cancellation' in mode else driver.CanonicalAnalysisRetentionFailure
    with pytest.raises(expected) as caught:
        await task
    recovery=caught.value.recovery
    if mode=='original-cancellation':
        assert caught.value is originals[0]
    elif mode!='repeated-cancellation':
        assert caught.value.__context__ is originals[0] and caught.value.__suppress_context__
    assert revocations==[host,host] and recovery._accounting is accounting
    assert recovery.accounting_close=='CLOSED'
    assert _accounting_row(accounting)==((1,1,1,0),before_row[1])
    if mode=='unpublished-initial-revoke':
        # Neither revoke published: the original lease is still admissible, so storage stays open.
        assert not host._revoked and recovery.host_close=='PENDING' and recovery.storage_close=='PENDING'
        assert not canonical.closed and not canonical.generated_metadata.closed
        assert recovery._database_hash is None
        async with host.hold_parent(binding):
            pass
        monkeypatch.setattr(RootHostController,'revoke',original_revoke)
        assert await recovery.settle()=={'host':'CLOSED','accounting':'CLOSED','storage':'CLOSED'}
        with pytest.raises(FollowUpExecutionBoundaryError):
            async with host.hold_parent(binding):
                pass
    # Observed state, not the revoke call outcome: published and quiescent.
    assert host._revoked and recovery.host_close=='CLOSED' and recovery.storage_close=='CLOSED'
    assert canonical.closed and canonical.generated_metadata.closed
    assert calls==['search','videos'] and len(credentials)==2


@pytest.mark.asyncio
async def test_failed_startup_metadata_close_failure_keeps_canonical_closure_and_retries(tmp_path,monkeypatch):
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention
    original_close=GeneratedWorkspaceRetention.close
    closes,failures=[],[]
    def failing_close(self):
        closes.append(self)
        if len(closes)==1:
            raise OSError('Synthetic metadata close failure')
        original_close(self)
    monkeypatch.setattr(GeneratedWorkspaceRetention,'close',failing_close)
    with monkeypatch.context() as patch:
        patch.setattr(ConnectorPluginRegistry,'register',_failing_registration(failures))
        recovery=await _registry_startup_failure(tmp_path,failures)
    # A later metadata failure leaves only that phase pending; canonical closure is not stranded.
    assert recovery.host_close=='CLOSED' and recovery.accounting_close=='CLOSED'
    assert recovery.storage_close=='PENDING' and recovery._canonical.closed and not recovery._metadata.closed
    assert recovery._database_hash is None
    assert await recovery.settle()=={'host':'CLOSED','accounting':'CLOSED','storage':'CLOSED'}
    assert closes==[recovery._metadata,recovery._metadata] and recovery._metadata.closed
    assert recovery._database_hash==driver.sha256(recovery._canonical.path.read_bytes()).hexdigest()
