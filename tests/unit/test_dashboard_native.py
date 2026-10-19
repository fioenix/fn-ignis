"""Native rooted mission admission must expose a local read-only dashboard before collection settles."""
import asyncio
import json
import os
import sqlite3
import sys
from urllib.parse import urlsplit
from pathlib import Path
import pytest
import httpx
from fastmcp import Client
from fastmcp.client.transports import StdioTransport


def _payload(result):return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_native_dashboard_available_during_actual_running_delayed_collection(tmp_path):
    root=tmp_path/'caller';root.mkdir();storage=root/'.fnignis';storage.mkdir()
    config=storage/'.env';config.write_text('YOUTUBE_API_KEY=DUMMY_OFFLINE\n');config.chmod(0o600)
    isolated=tmp_path/'isolated.env';isolated.write_text('DATABASE_URL=sqlite:///'+str(tmp_path/'unselected.sqlite3')+'\n')
    control=tmp_path/'control';control.mkdir();notices=[]
    async def notice(message):
        if isinstance(message.data,dict):notices.append(message.data)
    repository=Path(__file__).resolve().parents[2]
    client=Client(StdioTransport(command=sys.executable,args=[str(repository/'tests/fixtures/dashboard_native_host.py')],
        cwd=str(root),keep_alive=False,env={'IGNIS_ENV_FILE':str(isolated),'IGNIS_ENV_ISOLATED':'1',
        'IGNIS_OFFLINE_CONTROL':str(control),'PYTHONPATH':str(repository/'src')},log_file=tmp_path/'stdio.log'),
        mode='legacy',log_handler=notice,timeout=25)
    async with client:
        proposal=_payload(await client.call_tool('propose_research_workspace',{'host_workspace':str(root),'research_name':'Offline dashboard'}))
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
            assert any(item.get('event')=='IGNIS_DASHBOARD_READY' for item in notices), 'Admitted RUNNING mission exposed no dashboard before collector settlement.'
            receipt=next(item for item in notices if item.get('event')=='IGNIS_DASHBOARD_READY')
            assert receipt['mission_id']==mission['mission_id'] and receipt['read_only'] is True
            calls_before=(control/'calls.jsonl').read_text().splitlines()
            async with httpx.AsyncClient(trust_env=False) as viewer:
                response=await viewer.get(receipt['url']+'snapshot?page_size=100')
                assert response.status_code==200
                running=response.json()
                assert running['mission_id']==mission['mission_id'] and running['run_id']==receipt['run_id']
                assert running['collection_state']=='STARTED' and running['counts']['observations']==0
                document=await viewer.get(receipt['url'])
                assert document.status_code==200 and 'Recorded arrivals' in document.text
                selected=urlsplit(receipt['url'])
                denied=await viewer.get(selected.scheme+'://'+selected.netloc+'/view/foreign/snapshot?page_size=100')
                assert denied.status_code==403 and denied.json()['reason_code']=='SCOPE_MISMATCH'
            assert (control/'calls.jsonl').read_text().splitlines()==calls_before
            assert not execution.done()
            from playwright.async_api import async_playwright
            async with async_playwright() as browser_runtime:
                browser=await browser_runtime.chromium.launch(headless=True)
                context=await browser.new_context(service_workers='block')
                async def local_only(route):
                    if urlsplit(route.request.url).hostname=='127.0.0.1': await route.continue_()
                    else: await route.abort()
                await context.route('**/*',local_only)
                page=await context.new_page()
                await page.goto(receipt['url'])
                assert await page.get_by_test_id('stage-inspector').is_visible()
                assert 'no refresh or deletion' in await page.locator('body').inner_text()
                await context.close()
                await browser.close()
            assert not execution.done(), 'Closing the viewer cancelled independent collection.'
        finally:
            (control/'release-collector').touch()
            await execution
        async with httpx.AsyncClient(trust_env=False) as viewer:
            completed=(await viewer.get(receipt['url']+'snapshot?page_size=100')).json()
        assert completed['collection_state']=='COMPLETED'
        assert completed['counts']['observations']==1
        row=completed['evidence'][0]
        assert row['source_policy']['status']=='WITHIN_30_DAY_WINDOW'
        assert row['source_policy']['captured_at']==row['captured_at']
        assert row['source_policy']['automatic_action'] is False
        assert len((control/'calls.jsonl').read_text().splitlines())==2
        async with async_playwright() as browser_runtime:
            browser=await browser_runtime.chromium.launch(headless=True)
            context=await browser.new_context(service_workers='block')
            await context.route('**/*',local_only)
            page=await context.new_page()
            await page.goto(receipt['url'])
            await page.get_by_test_id('stage-inspector').get_by_text('WITHIN_30_DAY_WINDOW',exact=False).wait_for()
            assert 'Warnings do not extend retention permission' in await page.locator('body').inner_text()
            await page.get_by_role('button',name='Mission authority',exact=True).click()
            await page.get_by_role('button',name='Sources',exact=True).click()
            assert 'WITHIN_30_DAY_WINDOW' in await page.get_by_test_id('stage-inspector').inner_text()
            await context.close()
            await browser.close()
        assert len((control/'calls.jsonl').read_text().splitlines())==2
    async with httpx.AsyncClient(trust_env=False) as viewer:
        with pytest.raises(httpx.ConnectError): await viewer.get(receipt['url'])
    original_identity=(storage/'canonical.sqlite3').stat().st_ino
    original_calls=(control/'calls.jsonl').read_text().splitlines()
    async with client:
        reopened=_payload(await client.call_tool('get_mission_relay_snapshot',{
            'mission_id':mission['mission_id'],'run_id':receipt['run_id'],'page_size':100}))
        assert reopened['collection_state']=='COMPLETED' and reopened['evidence'][0]['observation_id']==row['observation_id']
    assert (storage/'canonical.sqlite3').stat().st_ino==original_identity
    assert (control/'calls.jsonl').read_text().splitlines()==original_calls
    assert not (tmp_path/'unselected.sqlite3').exists()
