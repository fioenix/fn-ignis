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
    ('run_minutes',16),('retention_days',8),('source','unapproved'),('geo','GeoCode.US')])
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
        if description_present:snippet['description']='Synthetic public description; no quality or adoption proof.'
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
        assert bounds.retention_until-bounds.started_at==timedelta(days=7)
        assert (bounds.search_calls,bounds.other_calls)==(2,4)
        assert result['bridge'].budget._used=={'search':1,'other':1}
        assert snapshot.signals[0].raw_title=='Hướng dẫn n8n: tạo workflow thử nghiệm'
        assert snapshot.signals[0].source_url=='https://www.youtube.com/watch?v=synthetic-tutorial'
        assert 'description' not in snapshot.signals[0].metadata
        journal=await store.latest_run_journal(snapshot.mission.id)
        plan=json.loads(journal.journal_path.read_text())['collection_plan']
        assert result['executor']._collection_queries(plan)==instruction['queries'][:1]
        research=await result['repository'].load_research_work(snapshot.mission.id)
        assert len(research.work_items)==1
        follow_ups=await result['repository'].load_mission_follow_ups(snapshot.mission.id)
        assert not follow_ups.work_items and not follow_ups.relationships
        refusal=await driver.run_canonical_parent(host=host,bridge=result['bridge'],
            executor=result['executor'],parent_work_id=result['work_id'])
        assert refusal=={'status':'REFUSED','reason_code':'PARENT_ALREADY_TERMINAL'}
        host.clock=lambda:bounds.retention_until
        audit=await driver.expire_owned_storage(host,result['canonical'],result['repository'],result['accounting'])
        assert audit['metadata_audit']['purged'] and host._revoked
        assert not result['canonical'].path.exists() and not journal.journal_path.exists()
        assert len(calls)==len(credentials)==2
        return {'status':'OFFLINE_CANONICAL_COMPOSITION_VERIFIED','observations':1,
            'description_state':'DESCRIPTION_NOT_RETAINED','provider_fields_received':
                ['title','description'] if description_present else ['title'],
            'retained_content_fields':['raw_title'],'provider_endpoints':['search','videos'],
            'search_calls':1,'other_calls':1,'child_status':'NOT_ADMITTED','expiry':'EXPLICIT_LOCAL_PURGE_VERIFIED',
            'brief_digest':digest(brief),'scope_digest':digest(instruction),'live_readiness':'NOT_ESTABLISHED'}
    finally:
        await result['host'].revoke()
        await result['repository'].close()


@pytest.mark.parametrize('description_present',[False,True])
@pytest.mark.asyncio
async def test_tutorial_brief_is_bound_but_description_missingness_remains_explicit(tmp_path,description_present):
    brief=json.loads((Path(__file__).parents[1]/'fixtures'/'follow_up_tutorial_brief.json').read_text())
    receipt={'status':'CONFIRMED','reference':'SYNTHETIC_ONLY_TUTORIAL_BINDING',
        'owner_reference':INSTRUCTION['reference'],'payload_digest':digest(brief),
        'collection_scope_digest':digest(INSTRUCTION),'confirmed_by':'synthetic-test-owner'}
    summary=await tutorial_parent_control(tmp_path,brief=brief,receipt=receipt,instruction=INSTRUCTION,
        description_present=description_present)
    assert summary['description_state']=='DESCRIPTION_NOT_RETAINED'


@pytest.mark.asyncio
async def test_after_seal_pre_host_failure_delivers_expiry_only_recovery(tmp_path,monkeypatch):
    from datetime import datetime
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention
    root=tmp_path/'failed-sealed-startup'
    original_open=Path.open
    def fail_scope(path,*args,**kwargs):
        if path==root/'root-scope.json':raise OSError('Synthetic original root-scope startup failure')
        return original_open(path,*args,**kwargs)
    calls=[]
    def resolve():calls.append('forbidden-resolution');raise AssertionError('Startup failure reached credential')
    brief,receipt=framing()
    class Clusterer:
        async def cluster_signals(self,signals):return []
    with monkeypatch.context() as patch:
        patch.setattr(Path,'open',fail_scope)
        with pytest.raises(FollowUpExecutionBoundaryError) as failed:
            await driver.bootstrap_confirmed_parent(root=root,brief=brief,receipt=receipt,instruction=INSTRUCTION,
                resolve_credential=resolve,transport=None,quota_manager=None,clusterer=Clusterer())
    canonical=root/'canonical'/'canonical.sqlite3'
    marker=json.loads((canonical.parent/'ownership.json').read_text())
    identity=(canonical.stat().st_dev,canonical.stat().st_ino)
    assert identity==tuple(marker['identity']) and canonical.exists()
    owned=json.loads((root/'generated-ownership.json').read_text())
    expiry=datetime.fromisoformat(owned['retention_until'])
    metadata=GeneratedWorkspaceRetention(root,owner_reference=owned['owner_reference'],
        scope_digest=owned['scope_digest'],retention_until=expiry)
    manifest=root/next(key for key in metadata._load()['files'] if key.endswith('/workspace.json'))
    assert manifest.is_file() and calls==[]
    assert metadata._load()['files']['canonical/canonical.sqlite3']['kind']=='canonical-delegated'
    with pytest.raises(FollowUpExecutionBoundaryError):metadata.purge(now=expiry)
    assert canonical.exists() and manifest.exists(), 'The original receipt alone cannot discharge delegated DB deletion'
    recovery=getattr(failed.value,'recovery',None)
    # Exercise whichever supported expiry action the failed call actually delivers.
    # The oracle is physical removal, not existence of a new helper/API.
    try:
        if recovery is None:metadata.purge(now=expiry)
        else:await recovery.purge(now=expiry)
    except FollowUpExecutionBoundaryError:
        pass
    assert not canonical.exists(), 'Failed sealed startup cannot discharge its owned DB at expiry'
    assert not manifest.exists() and calls==[]


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
async def test_failed_startup_recovery_refuses_early_ingress_and_preserves_foreign(tmp_path,monkeypatch,phase):
    from datetime import timedelta
    import sqlite3
    from ignis.infrastructure.follow_up_host_activation import open_owned_canonical_repository
    root,recovery,calls=await failed_startup_control(tmp_path,monkeypatch,phase)
    canonical=recovery._canonical
    original=canonical.path.read_bytes();marker=canonical.marker.read_bytes()
    foreign=root/'foreign-user-note.txt';foreign.write_bytes(b'Foreign owner bytes')
    with sqlite3.connect(canonical.path.as_uri()+'?mode=ro',uri=True) as connection:
        assert connection.execute('SELECT id FROM research_missions').fetchall()==[(str(recovery.confirmation.selected_parent_id),)]
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0]==0
    with pytest.raises(FollowUpExecutionBoundaryError):open_owned_canonical_repository(canonical)
    with pytest.raises(FollowUpExecutionBoundaryError):recovery._metadata.write(root/'new.json','Forbidden ingress')
    with pytest.raises(FollowUpExecutionBoundaryError):
        await recovery.purge(now=recovery.confirmation.bounds.retention_until-timedelta(seconds=1))
    assert canonical.path.read_bytes()==original and canonical.marker.read_bytes()==marker
    if phase=='scope':assert recovery._host is None and recovery._accounting is None
    else:assert recovery._host._revoked and recovery._host._tokens==0
    audit=await recovery.purge(now=recovery.confirmation.bounds.retention_until)
    assert audit['canonical_audit']['purged'] and audit['metadata_audit']['purged']
    assert not canonical.path.exists() and foreign.read_bytes()==b'Foreign owner bytes' and calls==[]
    assert canonical.marker.read_bytes()==marker
    if phase=='registry':
        assert audit['private_audit'] and recovery._accounting.counts(recovery.confirmation.bounds)=={'search':0,'other':0}
        with pytest.raises(FollowUpExecutionBoundaryError):recovery._accounting.current(recovery.confirmation.bounds)


@pytest.mark.parametrize('change',['metadata-bytes','canonical-bytes','replacement','symlink','ownership-receipt'])
@pytest.mark.asyncio
async def test_failed_startup_expiry_refuses_changed_owned_state_before_deleting_db(tmp_path,monkeypatch,change):
    root,recovery,calls=await failed_startup_control(tmp_path,monkeypatch)
    canonical=recovery._canonical
    original=canonical.path.read_bytes()
    manifest=root/next(key for key in recovery._metadata._load()['files'] if key.endswith('/workspace.json'))
    foreign=root/'foreign-state';foreign.write_bytes(b'Foreign state')
    if change=='metadata-bytes':manifest.write_bytes(b'Changed registered manifest')
    elif change=='canonical-bytes':
        # Preserve physical identity while changing otherwise valid SQLite content.
        import sqlite3
        with sqlite3.connect(canonical.path) as connection:connection.execute('PRAGMA user_version=123')
    elif change=='replacement':
        replacement=root/'replacement';replacement.write_bytes(original);replacement.replace(canonical.path)
    elif change=='symlink':canonical.path.unlink();canonical.path.symlink_to(foreign)
    else:canonical.marker.write_bytes(canonical.marker.read_bytes()+b'\n')
    with pytest.raises(FollowUpExecutionBoundaryError):await recovery.purge(now=recovery.confirmation.bounds.retention_until)
    assert canonical.path.exists() and manifest.exists() and foreign.read_bytes()==b'Foreign state' and calls==[]
    if change=='metadata-bytes':assert canonical.path.read_bytes()==original


@pytest.mark.asyncio
async def test_failed_startup_metadata_unlink_retry_remains_closed_after_canonical_purge(tmp_path,monkeypatch):
    root,recovery,calls=await failed_startup_control(tmp_path,monkeypatch)
    manifest=root/next(key for key in recovery._metadata._load()['files'] if key.endswith('/workspace.json'))
    original_unlink=Path.unlink
    def fail_manifest(path,*args,**kwargs):
        if path==manifest:raise OSError('Synthetic retained manifest unlink failure')
        return original_unlink(path,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path,'unlink',fail_manifest)
        with pytest.raises(OSError):await recovery.purge(now=recovery.confirmation.bounds.retention_until)
    assert not recovery._canonical.path.exists() and manifest.exists()
    assert recovery._canonical.closed and recovery._metadata.closed
    with pytest.raises(FollowUpExecutionBoundaryError):recovery._canonical.check()
    audit=await recovery.purge(now=recovery.confirmation.bounds.retention_until)
    assert audit['canonical_audit']['purged'] and audit['metadata_audit']['purged'] and not manifest.exists()
    assert calls==[]
