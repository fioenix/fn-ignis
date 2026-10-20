"""Caller parent/child source route through the real stdio middleware and owning lifespan.

The runner builds the genuine host factory inside the server process; nothing is passed through
model arguments, configuration or receipts. Test-only tools registered in the runner act as the
trusted embedding root; they are not product tools.
"""
import json
import os
import sys
from pathlib import Path

import pytest

RUNNER = r'''
import asyncio
import json
import sys
from pathlib import Path
from uuid import UUID
from fastmcp import Context
from ignis.interfaces.mcp import server
from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage
from tests.unit import test_follow_up_caller_activation as helpers

root, state_path, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
calls, resolutions, made, owned = [], [], {}, {}

def dump(extra=None):
    objects = made.get('objects')
    state = {'calls': calls, 'resolutions': len(resolutions)}
    if objects is not None:
        state['counts'] = objects.accounting.counts(objects.host.confirmation.bounds)
        state['row'] = list(helpers._closed_row(objects.accounting))
        state['revoked'] = objects.host._revoked
    if extra:
        state.update(extra)
    state_path.write_text(json.dumps(state, default=str))

async def main():
    components = await helpers._caller_components(root / 'storage')
    events = []
    original_close = components['repository'].close
    async def recorded_close():
        objects = made.get('objects')
        events.append({'event': 'repository_closed', 'host_revoked': bool(objects and objects.host._revoked)})
        await original_close()
    components['repository'].close = recorded_close
    def compose(scope):
        owned['scope'] = scope
        return components
    async def factory(scope):
        if scope is not owned.get('scope'):
            raise AssertionError('Factory received a foreign scope')
        made['objects'] = await helpers._genuine_for(scope, UUID(owned['mission']), root / 'host', calls, resolutions)
        return made['objects'].build()
    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            middleware.compose = compose
            if mode == 'activated':
                def runtime_for_scope(scope, owner, original=middleware.runtime_for_scope):
                    runtime = original(scope, owner)
                    runtime.source_activation_factory = factory
                    return runtime
                middleware.runtime_for_scope = runtime_for_scope

    @server.mcp.tool(name='test_root_confirm_mission_parent')
    async def confirm_parent() -> dict:
        scope = current_caller_storage.get()
        mission = await helpers._confirmed_caller_parent(scope.components, root)
        owned['mission'] = str(mission.id)
        identity = scope.components['repository'] is components['repository'] and scope.components['workspace_store'] is components['workspace_store']
        return {'mission_id': str(mission.id), 'borrowed': identity}

    @server.mcp.tool(name='test_root_run_mission_parent')
    async def run_parent(mission_id: str) -> dict:
        scope = current_caller_storage.get()
        result = await scope.runtime.source_parent(mission_id)
        dump()
        return result

    @server.mcp.tool(name='test_root_record_mission_child')
    async def record_child(mission_id: str, stale: bool = False) -> dict:
        scope = current_caller_storage.get()
        activation = scope.runtime.source_activation
        try:
            work_id = await helpers._record_genuine_child(scope.components, activation, UUID(mission_id), stale=stale)
        except Exception as error:
            return {'status': 'REFUSED', 'type': type(error).__name__}
        return {'status': 'RECORDED', 'follow_up_work_id': str(work_id)}

    @server.mcp.tool(name='test_root_revoke_mission_source')
    async def revoke() -> dict:
        await made['objects'].host.revoke()
        return {'revoked': made['objects'].host._revoked}

    @server.mcp.tool(name='test_root_cancel_mission_owner_close')
    async def cancel_owner_close(ctx: Context) -> dict:
        scope = current_caller_storage.get()
        owner = ctx.lifespan_context['mission_relay']
        await scope.runtime.activate_source()
        gate = asyncio.Event()
        write = asyncio.create_task(gate.wait())
        owner._writes.add(write)
        closing = asyncio.create_task(owner.close())
        await asyncio.sleep(0.05)
        closing.cancel()
        await asyncio.sleep(0)
        gate.set()
        try:
            await closing
            observer = 'COMPLETED'
        except asyncio.CancelledError:
            observer = 'CANCELLED'
        for _ in range(150):
            if events:
                break
            await asyncio.sleep(0.02)
        objects = made['objects']
        return {'observer': observer, 'revoked': objects.host._revoked,
                'row': list(helpers._closed_row(objects.accounting)),
                'verifier_detached': getattr(components['repository'], '_follow_up_verifier', None) is None,
                'events': events, 'executions_after': len(scope.runtime._executions)}

    @server.mcp.tool(name='test_root_run_journals')
    async def run_journals(mission_ids: list[str]) -> dict:
        store = components['workspace_store']
        return {mission_id: [{'run_id': str(journal.run_id), 'mission_id': str(journal.mission_id)}
                             for journal in await store.list_run_journals(UUID(mission_id))]
                for mission_id in mission_ids}

    @server.mcp.tool(name='test_root_mission_state')
    async def state() -> dict:
        dump()
        return json.loads(state_path.read_text())

    try:
        await server.mcp.run_stdio_async(show_banner=False)
    finally:
        dump({'after_lifespan': True})
        await components['repository'].close()

asyncio.run(main())
'''


def _client(tmp_path, mode):
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    repo = Path(__file__).resolve().parents[2]
    runner = tmp_path / 'caller_runner.py'
    runner.write_text(RUNNER)
    isolated = tmp_path / 'isolated.env'
    isolated.write_text('DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n')
    return Client(StdioTransport(command=sys.executable,
        args=[str(runner), str(tmp_path), str(tmp_path / 'state.json'), mode], cwd=str(tmp_path), keep_alive=False,
        env={'IGNIS_ENV_FILE': str(isolated), 'IGNIS_ENV_ISOLATED': '1', 'IGNIS_CALLER_ROOT': str(tmp_path),
             'PYTHONPATH': os.pathsep.join(str(path) for path in (repo / 'src', repo))},
        log_file=tmp_path / 'stdio.log'), timeout=30)


def _data(result):
    return result.structured_content if result.structured_content is not None else json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_middleware_parent_and_genuine_gap_child_share_original_budget(tmp_path):
    async with _client(tmp_path, 'activated') as client:
        confirmed = _data(await client.call_tool('test_root_confirm_mission_parent', {}))
        assert confirmed['borrowed'] is True
        mission_id = confirmed['mission_id']
        parent = _data(await client.call_tool('test_root_run_mission_parent', {'mission_id': mission_id}))
        assert parent['status'] == 'PARENT_EXECUTION_RETURNED', parent
        replay = _data(await client.call_tool('test_root_run_mission_parent', {'mission_id': mission_id}))
        assert replay == {'status': 'REFUSED', 'reason_code': 'PARENT_ALREADY_TERMINAL'}
        stale = _data(await client.call_tool('test_root_record_mission_child', {'mission_id': mission_id, 'stale': True}))
        assert stale['status'] == 'REFUSED'
        recorded = _data(await client.call_tool('test_root_record_mission_child', {'mission_id': mission_id}))
        assert recorded['status'] == 'RECORDED', recorded
        child = _data(await client.call_tool('execute_mission_follow_up', {'mission_id': mission_id,
            'follow_up_work_id': recorded['follow_up_work_id'], 'expected_research_epoch': 1,
            'idempotency_key': 'middleware-child'}))
        assert child['status'] == 'COMPLETED', child
        assert child['child_mission_id'] != mission_id
        state = _data(await client.call_tool('test_root_mission_state', {}))
        assert [call[0] for call in state['calls']] == ['search', 'videos', 'search', 'videos']
        assert [call[1]['q'] for call in state['calls'] if call[0] == 'search'] == ['n8n Việt Nam', 'n8n tự động hóa']
        assert all(call[1]['maxResults'] == '5' for call in state['calls'] if call[0] == 'search')
        assert state['resolutions'] == 4 and state['counts'] == {'search': 2, 'other': 2}
        journals = _data(await client.call_tool('test_root_run_journals',
            {'mission_ids': [mission_id, child['child_mission_id']]}))
        parent_runs, child_runs = journals[mission_id], journals[child['child_mission_id']]
        assert [run['mission_id'] for run in parent_runs] == [mission_id]
        assert [run['mission_id'] for run in child_runs] == [child['child_mission_id']]
        assert parent_runs[0]['run_id'] != child_runs[0]['run_id']
    final = json.loads((tmp_path / 'state.json').read_text())
    assert final['after_lifespan'] and final['revoked'] and final['row'] == [2, 2, 1, 0]
    assert len(final['calls']) == 4


@pytest.mark.asyncio
async def test_middleware_without_injected_factory_refuses_before_any_source_spend(tmp_path):
    async with _client(tmp_path, 'default') as client:
        mission_id = _data(await client.call_tool('test_root_confirm_mission_parent', {}))['mission_id']
        parent = _data(await client.call_tool('test_root_run_mission_parent', {'mission_id': mission_id}))
        assert parent == {'status': 'REFUSED', 'reason_code': 'SESSION_AUTHORITY_REQUIRED'}
        state = _data(await client.call_tool('test_root_mission_state', {}))
        assert state['calls'] == [] and state['resolutions'] == 0 and 'counts' not in state


@pytest.mark.asyncio
async def test_revoked_source_refuses_child_and_restart_restores_no_authority(tmp_path):
    async with _client(tmp_path, 'activated') as client:
        mission_id = _data(await client.call_tool('test_root_confirm_mission_parent', {}))['mission_id']
        assert _data(await client.call_tool('test_root_run_mission_parent', {'mission_id': mission_id}))['status'] == 'PARENT_EXECUTION_RETURNED'
        work_id = _data(await client.call_tool('test_root_record_mission_child', {'mission_id': mission_id}))['follow_up_work_id']
        assert _data(await client.call_tool('test_root_revoke_mission_source', {}))['revoked'] is True
        request = {'mission_id': mission_id, 'follow_up_work_id': work_id, 'expected_research_epoch': 1,
                   'idempotency_key': 'revoked-child'}
        child = _data(await client.call_tool('execute_mission_follow_up', request))
        assert child['status'] == 'REFUSED' and child['child_mission_id'] is None, child
        state = _data(await client.call_tool('test_root_mission_state', {}))
        assert len(state['calls']) == 2 and state['resolutions'] == 2 and state['counts'] == {'search': 1, 'other': 1}
    first = json.loads((tmp_path / 'state.json').read_text())
    assert first['row'] == [1, 1, 1, 0]
    # A fresh process over the same retained caller storage, with no injected factory.
    async with _client(tmp_path, 'default') as client:
        retry = _data(await client.call_tool('execute_mission_follow_up', {**request, 'idempotency_key': 'restart-child'}))
        assert retry['status'] == 'REFUSED' and retry['child_mission_id'] is None, retry
        state = _data(await client.call_tool('test_root_mission_state', {}))
        assert state['calls'] == [] and state['resolutions'] == 0


def _harness_processes(tmp_path):
    import subprocess as _subprocess
    marker = str(tmp_path / 'caller_runner.py')
    listing = _subprocess.run(['ps', '-axo', 'pid,command'], capture_output=True, text=True).stdout
    return [line for line in listing.splitlines() if marker in line]


@pytest.mark.asyncio
async def test_stdio_outer_close_observer_cancel_still_settles_selected_caller(tmp_path):
    async with _client(tmp_path, 'activated') as client:
        _data(await client.call_tool('test_root_confirm_mission_parent', {}))
        result = _data(await client.call_tool('test_root_cancel_mission_owner_close', {}))
        assert result['observer'] == 'CANCELLED'
        assert result['revoked'] is True and result['row'] == [0, 0, 1, 0]
        assert result['verifier_detached'] is True and result['executions_after'] == 0
        assert result['events'] == [{'event': 'repository_closed', 'host_revoked': True}]
    import asyncio as _asyncio
    for _ in range(50):
        if not _harness_processes(tmp_path):
            break
        await _asyncio.sleep(0.1)
    assert _harness_processes(tmp_path) == [], 'Harness server process outlived its finite stdio client'
