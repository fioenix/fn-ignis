"""A native rooted mission is readable through the snapshot tool while collection is still running.

Ignis serves no tracking page (Spec 014 R2): an agent reads get_mission_relay_snapshot and builds
its own artifact. Reading never calls a collector and never cancels the running collection.
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def _payload(result):return json.loads(result.content[0].text)


def _snapshot(result):return result.structured_content


@pytest.mark.asyncio
async def test_native_snapshot_reads_an_actually_running_delayed_collection(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    config=storage/'.env';config.write_text('YOUTUBE_API_KEY=DUMMY_OFFLINE\n');config.chmod(0o600)
    isolated=tmp_path/'isolated.env';isolated.write_text('DATABASE_URL=sqlite:///'+str(tmp_path/'unselected.sqlite3')+'\n')
    control=tmp_path/'control';control.mkdir()
    repository=Path(__file__).resolve().parents[2]
    client=Client(StdioTransport(command=sys.executable,args=[str(repository/'tests/fixtures/offline_native_host.py')],
        cwd=str(root),keep_alive=False,env={'IGNIS_ENV_FILE':str(isolated),'IGNIS_ENV_ISOLATED':'1',
        'IGNIS_OFFLINE_CONTROL':str(control),'PYTHONPATH':str(repository/'src')},log_file=tmp_path/'stdio.log'),
        mode='legacy',timeout=25)
    async with client:
        proposal=_payload(await client.call_tool('propose_research_workspace',{'host_workspace':str(root),'research_name':'Offline tracking'}))
        workspace=_payload(await client.call_tool('confirm_research_workspace',{'proposed_path':proposal['proposed_path'],'confirmation':True}))
        mission=_payload(await client.call_tool('create_attention_mission',{'workspace_id':workspace['workspace_id'],
            'title':'Offline bounded mission','keywords':['offline tutorial'],'requested_outcome':'Observe offline tutorial material',
            'allowed_resources':['youtube'],'authority_boundary':{'official_api':True,'public_http':False,'browser_session':False,'paid_quota':False},
            'output_type':'COLLECTION_FRAME','stop_conditions':['explicit completion'],'retention_policy':'Retain until explicit owner deletion',
            'platforms':['youtube'],'quota_budget':{'youtube.search':2,'youtube':4}}))
        execution=asyncio.create_task(client.call_tool('execute_mission_ingress',{'mission_id':mission['mission_id']}))
        try:
            async with asyncio.timeout(12):
                while not (control/'collector-entered').exists():
                    if execution.done():raise AssertionError('Execution ended before delayed collector admission')
                    await asyncio.sleep(.02)
            with sqlite3.connect('file:'+str(storage/'canonical.sqlite3')+'?mode=ro',uri=True) as database:
                state=database.execute('SELECT status FROM research_missions WHERE id=?',(mission['mission_id'],)).fetchone()[0]
            assert state=='RUNNING' and not execution.done()
            calls_before=(control/'calls.jsonl').read_text().splitlines()
            running=_snapshot(await client.call_tool('get_mission_relay_snapshot',
                {'mission_id':mission['mission_id'],'page_size':100}))
            assert running['status']=='OK' and running['mission_id']==mission['mission_id']
            assert running['collection_state']=='RUNNING' and running['counts']['observations']==0
            malformed=_snapshot(await client.call_tool('get_mission_relay_snapshot',
                {'mission_id':'not-a-mission','page_size':100}))
            assert malformed=={'schema_version':1,'status':'REFUSED','reason_code':'SCOPE_MISMATCH'}
            assert (control/'calls.jsonl').read_text().splitlines()==calls_before, 'Reading must not call a collector'
            assert not execution.done(), 'Reading cancelled independent collection'
        finally:
            (control/'release-collector').touch()
            executed=await execution
        run_id=_payload(executed)['run']['run_id']
        completed=_snapshot(await client.call_tool('get_mission_relay_snapshot',
            {'mission_id':mission['mission_id'],'run_id':run_id,'page_size':100}))
        assert completed['run_id']==run_id
        assert completed['collection_state']=='COMPLETED'
        assert completed['counts']['observations']==1
        row=completed['evidence'][0]
        assert row['source_policy']['status']=='WITHIN_30_DAY_WINDOW'
        assert row['source_policy']['captured_at']==row['captured_at']
        assert row['source_policy']['automatic_action'] is False
        assert len((control/'calls.jsonl').read_text().splitlines())==2
    original_identity=(storage/'canonical.sqlite3').stat().st_ino
    original_calls=(control/'calls.jsonl').read_text().splitlines()
    async with client:
        reopened=_snapshot(await client.call_tool('get_mission_relay_snapshot',{
            'mission_id':mission['mission_id'],'run_id':run_id,'page_size':100}))
        assert reopened['collection_state']=='COMPLETED' and reopened['evidence'][0]['observation_id']==row['observation_id']
    assert (storage/'canonical.sqlite3').stat().st_ino==original_identity
    assert (control/'calls.jsonl').read_text().splitlines()==original_calls
    assert not (tmp_path/'unselected.sqlite3').exists()
