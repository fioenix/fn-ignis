"""Credential-free MCP argument-boundary controls; no execution or live host proof."""

import json
from types import SimpleNamespace

import pytest
from fastmcp.tools.base import ToolResult

from ignis.interfaces.mcp import server


MISSION_ID = '00000000-0000-0000-0000-000000000001'
WORK_ID = '00000000-0000-0000-0000-000000000002'
PRIVATE_SENTINEL = 'PRIVATE_ARGUMENT_SENTINEL'


def follow_up_arguments():
    return {'mission_id': MISSION_ID, 'follow_up_work_id': WORK_ID,
            'expected_research_epoch': 1, 'idempotency_key': 'request-1'}


def malformed_arguments(case):
    arguments = follow_up_arguments()
    if case == 'extra':
        arguments['access_token'] = PRIVATE_SENTINEL
    elif case == 'missing':
        del arguments['idempotency_key']
    elif case == 'not-object':
        return [PRIVATE_SENTINEL]
    elif case == 'bool-epoch':
        arguments['expected_research_epoch'] = True
    elif case == 'text-epoch':
        arguments['expected_research_epoch'] = PRIVATE_SENTINEL
    elif case == 'zero-epoch':
        arguments['expected_research_epoch'] = 0
    elif case == 'mission-type':
        arguments['mission_id'] = {'private': PRIVATE_SENTINEL}
    elif case == 'work-type':
        arguments['follow_up_work_id'] = [PRIVATE_SENTINEL]
    elif case == 'key-type':
        arguments['idempotency_key'] = {'private': PRIVATE_SENTINEL}
    elif case == 'invalid-mission':
        arguments['mission_id'] = PRIVATE_SENTINEL
    elif case == 'invalid-work':
        arguments['follow_up_work_id'] = PRIVATE_SENTINEL
    elif case == 'empty-key':
        arguments['idempotency_key'] = ''
    elif case == 'oversized-key':
        arguments['idempotency_key'] = PRIVATE_SENTINEL * 1000
    return arguments


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['extra', 'missing', 'not-object', 'bool-epoch', 'text-epoch',
    'zero-epoch', 'mission-type', 'work-type', 'key-type', 'invalid-mission', 'invalid-work',
    'empty-key', 'oversized-key'])
async def test_follow_up_argument_boundary_refuses_before_forwarding(case, monkeypatch):
    """Existing middleware must reject private malformed values before framework validation."""
    forwarded = []
    initialized = []

    async def forbidden_components(*args, **kwargs):
        initialized.append(True)
        raise AssertionError('Argument refusal must not initialize runtime components.')

    monkeypatch.setattr(server, 'get_components', forbidden_components)

    async def call_next(context):
        forwarded.append(context.message.arguments)
        return ToolResult(structured_content={'status': 'FORWARDED'})

    context = SimpleNamespace(message=SimpleNamespace(name='execute_mission_follow_up',
        arguments=malformed_arguments(case)))
    result = await server._ResearchRecordingArguments().on_call_tool(context, call_next)
    assert forwarded == []
    assert initialized == []
    assert result.structured_content == {
        'status': 'REFUSED', 'reason_code': 'INVALID_COMMAND', 'child_mission_id': None,
        'reservation_id': None, 'parent_work_id': None, 'gap_id': None, 'assignment_id': None,
        'follow_up_work_id': None, 'run_id': None, 'channel_outcomes': [],
    }
    assert PRIVATE_SENTINEL not in json.dumps(result.structured_content)


@pytest.mark.asyncio
@pytest.mark.parametrize('name,arguments', [
    ('execute_mission_follow_up', follow_up_arguments()),
    ('record_mission_research_work', {'mission_id': MISSION_ID, 'command': {}}),
    ('get_mission_relay_snapshot', {'mission_id': MISSION_ID}),
])
async def test_argument_boundary_preserves_valid_forwarding(name, arguments):
    forwarded = []
    expected = ToolResult(structured_content={'status': 'NEXT_RECEIPT'})

    async def call_next(context):
        forwarded.append(context.message.arguments)
        return expected

    context = SimpleNamespace(message=SimpleNamespace(name=name, arguments=arguments))
    result = await server._ResearchRecordingArguments().on_call_tool(context, call_next)
    assert result is expected
    assert forwarded == [arguments]


@pytest.mark.asyncio
async def test_follow_up_extension_preserves_recording_malformed_refusal():
    forwarded = []

    async def call_next(context):
        forwarded.append(True)
        return ToolResult(structured_content={'status': 'FORWARDED'})

    context = SimpleNamespace(message=SimpleNamespace(name='record_mission_research_work',
        arguments={'mission_id': MISSION_ID, 'command': {}, 'access_token': PRIVATE_SENTINEL}))
    result = await server._ResearchRecordingArguments().on_call_tool(context, call_next)
    assert forwarded == []
    assert result.structured_content['disposition'] == 'REFUSED'
    assert result.structured_content['reason_code'] == 'INVALID_COMMAND'
    assert PRIVATE_SENTINEL not in json.dumps(result.structured_content)


from tests.integration.follow_up_mcp_setup import native_executor


NATIVE_RUNNER = '''
import asyncio
import json
import sys
from pathlib import Path
from fastmcp.server.middleware import Middleware
from mcp.server.session import ServerSession
from ignis.interfaces.mcp import server
from tests.integration.follow_up_mcp_setup import native_executor
from tests.integration.test_follow_up_execution import OfflineExecutionVerifier
from tests.integration.test_follow_up_sqlite_admission import OfflineVerifier

class Proof(Middleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name == "execute_mission_follow_up":
            ctx = context.fastmcp_context
            runtime = ctx.lifespan_context["mission_relay"]
            Path(sys.argv[2]).write_text(json.dumps({"transport": ctx.transport,
                "lifespan_transport": runtime.transport,
                "request_session": isinstance(ctx.request_context.session, ServerSession),
                "exact_server": ctx.fastmcp is server.mcp and runtime.server is server.mcp,
                "owner_loop": runtime.owner_loop is asyncio.get_running_loop()}))
        return await call_next(context)

async def main():
    descriptor = json.loads(Path(sys.argv[1]).read_text())
    if descriptor['backend'] == 'postgres':
        from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
        from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
        repository = PostgresTimescaleRepository(descriptor['location'], min_pool_size=1, max_pool_size=2)
        await repository._get_pool()
        class NativeVerifier(OfflineExecutionVerifier):
            hold_current = AsyncVerifier.hold_current
        verifier = NativeVerifier()
    else:
        from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
        repository = SqliteTrendRepository(descriptor['location'])
        await repository._ensure_schema()
        verifier = OfflineExecutionVerifier()
    if descriptor['missing_provider']:
        verifier = OfflineVerifier()
    repository.configure_follow_up_verifier(verifier)
    executor, registry, store = native_executor(repository, sys.argv[3])
    plugin = registry.get_plugin_by_id('youtube')
    Path(sys.argv[4]).write_text(json.dumps({'module': type(plugin).__module__,
        'qualname': type(plugin).__qualname__}))
    components = {'repository': repository, 'execute_mission_use_case': executor,
                  'registry': registry, 'workspace_store': store}
    server._init_components = lambda: components
    server.get_components()
    def forbidden():
        raise AssertionError('Handler must borrow initialized components, never initialize.')
    server.get_components = forbidden
    server._init_components = forbidden
    server.mcp.add_middleware(Proof())
    # Test-only composition: the real caller middleware selects the explicit disposable root
    # and borrows this descriptor's exact repository/store; its scope guards stay active.
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware
    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            middleware.compose = lambda scope: components
    try:
        await server.mcp.run_stdio_async(show_banner=False)
    finally:
        await repository.close()

asyncio.run(main())
'''


def native_client(tmp_path, case, *, missing_provider=False):
    from pathlib import Path
    import sys
    import os
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
    root = Path(__file__).resolve().parents[2]
    descriptor = tmp_path / 'follow-up-storage.json'
    descriptor.write_text(json.dumps({'backend': case.name,
        'location': case.dsn if case.name == 'postgres' else case.repository._db_path,
        'missing_provider': missing_provider}))
    descriptor.chmod(0o600)
    runner = tmp_path / 'follow_up_stdio.py'
    runner.write_text(NATIVE_RUNNER)
    isolated = tmp_path / 'isolated.env'
    isolated.write_text('DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n')
    return Client(StdioTransport(command=sys.executable,
        args=[str(runner), str(descriptor), str(tmp_path / 'transport-proof.json'), str(tmp_path / 'probes.json'),
              str(tmp_path / 'connector-identity.json')],
        cwd=str(tmp_path), keep_alive=False,
        env={'IGNIS_ENV_FILE': str(isolated), 'IGNIS_ENV_ISOLATED': '1', 'IGNIS_CALLER_ROOT': str(tmp_path),
             'PYTHONPATH': os.pathsep.join(str(path) for path in (root / 'src', root, root / 'tests/integration', root / 'tests'))}, log_file=tmp_path / 'stdio.log'), timeout=20)


from tests.integration.test_mission_follow_up import relay_case


async def _native_arrange(case, tmp_path):
    # The recorded plan must bind the same synthetic plugin class/path the native
    # executor will actually use; another fixture's connector path is not authority.
    from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
    from tests.integration.follow_up_execution_setup import ready
    from tests.integration.test_mission_follow_up import _work_payload
    executor, registry, _ = native_executor(case.repository, tmp_path / 'probes.json')
    plugin = registry.get_plugin_by_id('youtube')
    (tmp_path / 'parent-connector-identity.json').write_text(json.dumps({
        'module': type(plugin).__module__, 'qualname': type(plugin).__qualname__}))
    _, parent, work, authority, _ = await ready(case.repository, tmp_path, executor, ExecuteMissionFollowUpUseCase)
    return parent, _work_payload(work, authority.cost)


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_native_follow_up_schema_child_provenance_and_original_alias_retry(relay_case, tmp_path):
    from pathlib import Path
    case, _, _ = relay_case
    parent, work = await _native_arrange(case, tmp_path)
    arguments = dict(mission_id=str(parent.id), follow_up_work_id=work['work_id'],
        expected_research_epoch=1, idempotency_key='native-one')
    async with native_client(tmp_path, case) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        schema = tools['execute_mission_follow_up'].input_schema
        assert set(schema['properties']) == set(schema['required']) == set(arguments)
        assert schema['properties']['expected_research_epoch']['type'] == 'integer'
        first = (await client.call_tool('execute_mission_follow_up', arguments)).data
        assert json.loads((tmp_path / 'connector-identity.json').read_text()) == json.loads(
            (tmp_path / 'parent-connector-identity.json').read_text())
        assert first['status'] == 'COMPLETED', (first.get('status'), first.get('reason_code'))
        assert first['parent_mission_id'] == str(parent.id)
        assert first['follow_up_work_id'] == work['work_id']
        assert first['parent_work_id'] is not None and first['gap_id'] == work['gap_id']
        assert first['assignment_id'] == work['assignment_id']
        assert first['run_id'] is not None and first['child_mission_id'] != str(parent.id)
        retry = (await client.call_tool('execute_mission_follow_up', arguments)).data
        alias = (await client.call_tool('execute_mission_follow_up', {**arguments, 'idempotency_key': 'native-alias'})).data
        immutable_fields = {'status', 'reason_code', 'parent_mission_id', 'child_mission_id',
            'reservation_id', 'parent_work_id', 'gap_id', 'assignment_id', 'follow_up_work_id', 'run_id'}
        assert {key: retry[key] for key in immutable_fields} == {key: first[key] for key in immutable_fields}
        assert {key: alias[key] for key in immutable_fields} == {key: first[key] for key in immutable_fields}
        assert retry['channel_outcomes'] == alias['channel_outcomes'] == []
        changed = (await client.call_tool('execute_mission_follow_up',
            {**arguments, 'expected_research_epoch': 2})).data
        assert changed['status'] == 'REFUSED' and changed['reason_code'] == 'IDEMPOTENCY_CONFLICT'
        assert all(changed[key] is None for key in ('child_mission_id', 'reservation_id', 'parent_work_id',
            'gap_id', 'assignment_id', 'follow_up_work_id', 'run_id'))
        assert 'parent_mission_id' not in changed
        assert changed['channel_outcomes'] == []
        malformed = (await client.call_tool('execute_mission_follow_up',
            {**arguments, 'access_token': PRIVATE_SENTINEL})).data
        assert malformed['status'] == 'REFUSED' and malformed['reason_code'] == 'INVALID_COMMAND'
        assert malformed['child_mission_id'] is None and malformed['run_id'] is None
    snapshot = await case.repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    link = snapshot.relationships[0]
    assert str(link.child_mission_id) == first['child_mission_id']
    assert str(link.reservation_id) == first['reservation_id']
    assert len(await case.repository.list_run_journals(link.child_mission_id)) == 1
    assert (await case.repository.get_mission(parent.id)).status == 'COMPLETED'
    assert json.loads((tmp_path / 'probes.json').read_text()) == [work['work_queries']]
    assert json.loads((tmp_path / 'transport-proof.json').read_text()) == {
        'transport': 'stdio', 'lifespan_transport': 'stdio', 'request_session': True,
        'exact_server': True, 'owner_loop': True}
    assert PRIVATE_SENTINEL not in (tmp_path / 'stdio.log').read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_actual_stdio_channel_cannot_replace_independent_execution_provider(relay_case, tmp_path):
    from tests.integration.test_mission_relay_read_boundary import _state
    case, _, _ = relay_case
    parent, work = await _native_arrange(case, tmp_path)
    before = await case.repository.load_mission_follow_ups(parent.id)
    physical_before = _state(case)
    async with native_client(tmp_path, case, missing_provider=True) as client:
        result = (await client.call_tool('execute_mission_follow_up', dict(mission_id=str(parent.id),
            follow_up_work_id=work['work_id'], expected_research_epoch=1, idempotency_key='no-provider'))).data
    assert result['status'] == 'REFUSED' and result['reason_code'] == 'SESSION_AUTHORITY_REQUIRED'
    assert result['child_mission_id'] is None and result['run_id'] is None
    assert await case.repository.load_mission_follow_ups(parent.id) == before
    assert _state(case) == physical_before
    assert not (tmp_path / 'probes.json').exists()
    assert PRIVATE_SENTINEL not in (tmp_path / 'stdio.log').read_text()


@pytest.mark.asyncio
async def test_in_process_follow_up_refuses_without_resource_initialization(monkeypatch):
    initialized = []
    def forbidden():
        initialized.append(True)
        raise AssertionError('Unauthorized request must not initialize components.')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, '_init_components', forbidden)
    from fastmcp import Context
    result = await server.execute_mission_follow_up(**follow_up_arguments(), ctx=Context(server.mcp))
    assert result['status'] == 'REFUSED' and result['reason_code'] == 'UNAUTHORIZED_HOST'
    assert initialized == []


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
@pytest.mark.parametrize('operation', ['caller-cancel', 'lifespan-close'])
async def test_owned_actual_collector_cancellation_settles_before_release(relay_case, tmp_path, monkeypatch, operation):
    """Actual accepted execution, synthetic blocked probe; ownership survives repeated cancellation."""
    import asyncio
    from tests.integration.test_follow_up_execution import OfflineExecutionVerifier
    case, _, _ = relay_case
    parent, work = await _native_arrange(case, tmp_path)
    entered, gate, cleanup_entered, cleanup_gate = (asyncio.Event() for _ in range(4))
    executor, registry, store = native_executor(case.repository, tmp_path / 'owned-probes.json',
        entered=entered, gate=gate, cleanup_entered=cleanup_entered, cleanup_gate=cleanup_gate)
    if case.name == 'postgres':
        from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
        # The accepted execution verifier inherits AsyncVerifier; retain its native
        # admission lease as well as the separate held execution capability.
        class NativeVerifier(OfflineExecutionVerifier):
            hold_current = AsyncVerifier.hold_current
        verifier = NativeVerifier()
    else:
        verifier = OfflineExecutionVerifier()
    case.repository.configure_follow_up_verifier(verifier)
    components = {'repository': case.repository, 'execute_mission_use_case': executor,
                  'registry': registry, 'workspace_store': store}
    monkeypatch.setattr(server, '_COMPONENTS', components)
    monkeypatch.setattr(server, '_COMPONENTS_OWNER', (components, case.repository, asyncio.get_running_loop()))
    runtime = server._MissionRelayRuntime()
    request = server._parse_follow_up_arguments(dict(mission_id=str(parent.id), follow_up_work_id=work['work_id'],
        expected_research_epoch=1, idempotency_key='owned-cancel'))
    parent_before = await case.repository.get_mission(parent.id)
    task = asyncio.create_task(runtime.follow_up(request))
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert len(runtime._executions) == 1
        active = await case.repository.load_mission_follow_ups(parent.id)
        assert len(active.relationships) == len(active.reservations) == 1
        link = active.relationships[0]
        running = await case.repository.list_run_journals(link.child_mission_id)
        assert len(running) == 1 and running[0].status == 'STARTED'
        assert (await case.repository.get_mission_writer_claim(link.child_mission_id)).run_id == running[0].run_id
        if operation == 'caller-cancel':
            task.cancel()
        else:
            closing = asyncio.create_task(runtime.close())
        await asyncio.wait_for(cleanup_entered.wait(), 5)
        assert len(runtime._executions) == 1
        assert not task.done()
        task.cancel()
        # A second caller cancellation cannot interrupt the original collector's cleanup.
        cleanup_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        if closing is not None:
            await asyncio.wait_for(closing, 5)
        assert runtime._executions == set()
        snapshot = await case.repository.load_mission_follow_ups(parent.id)
        assert len(snapshot.relationships) == len(snapshot.reservations) == 1
        assert snapshot.relationships == active.relationships
        reservation = snapshot.reservations[0]
        assert reservation.state == 'UNRESOLVED'
        assert reservation.reserved_quota == reservation.reserved_cost == 2
        assert reservation.encumbered == (2, 2)
        assert reservation.measurement_receipt_id is None
        assert reservation.measured_quota is None and reservation.measured_cost is None
        if case.name == 'postgres':
            import psycopg
            with psycopg.connect(case.dsn) as conn:
                resources = conn.execute('SELECT resource,allocated FROM mission_follow_up_reservation_resources '
                    'WHERE reservation_id=%s ORDER BY resource', (link.reservation_id,)).fetchall()
        else:
            import sqlite3
            from contextlib import closing as closing_connection
            with closing_connection(sqlite3.connect(case.repository._db_path)) as conn:
                resources = conn.execute('SELECT resource,allocated FROM mission_follow_up_reservation_resources '
                    'WHERE reservation_id=? ORDER BY resource', (str(link.reservation_id),)).fetchall()
        assert resources == [('queries', 2), ('youtube_search_calls', 2)]
        journals = await case.repository.list_run_journals(link.child_mission_id)
        assert len(journals) == 1 and journals[0].run_id == running[0].run_id
        assert journals[0].mission_id == link.child_mission_id
        assert journals[0].workspace_id == running[0].workspace_id
        assert journals[0].status == 'FAILED' and journals[0].completed_at is not None
        assert await case.repository.get_mission_writer_claim(link.child_mission_id) is None
        assert (await case.repository.get_mission(link.child_mission_id)).status == 'FAILED'
        assert await case.repository.get_mission(parent.id) == parent_before
        # Recovery of this actual cancelled run must not dispatch a second probe.
        from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
        recovery = ExecuteMissionFollowUpUseCase(case.repository, executor,
            selected_parent_id=parent.id, host_authorized=True)
        for key in ('owned-cancel', 'owned-cancel-alias'):
            result = await recovery.execute(str(parent.id), work['work_id'], 1, key)
            assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
            assert result.relationship == link and result.run_id == running[0].run_id
        assert await case.repository.load_mission_follow_ups(parent.id) == snapshot
        assert await case.repository.list_run_journals(link.child_mission_id) == journals
        assert json.loads((tmp_path / 'owned-probes.json').read_text()) == [work['work_queries']]
    finally:
        gate.set()
        cleanup_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if closing is not None:
            await asyncio.gather(closing, return_exceptions=True)
        if not runtime.closed:
            await runtime.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_actual_stdio_pre_admission_refusals_preserve_physical_state(relay_case, tmp_path):
    """Actual MCP rejects hostile/stale/unbound arguments before any child or probe exists."""
    from tests.integration.test_mission_relay_read_boundary import _state
    case, missions, _ = relay_case
    parent, work = await _native_arrange(case, tmp_path)
    arguments = dict(mission_id=str(parent.id), follow_up_work_id=work['work_id'],
        expected_research_epoch=1, idempotency_key='native-negative')
    before = await case.repository.load_mission_follow_ups(parent.id)
    physical_before = _state(case)
    controls = [
        ({**arguments, 'access_token': PRIVATE_SENTINEL}, 'INVALID_COMMAND'),
        ({**arguments, 'viewer_token': PRIVATE_SENTINEL}, 'INVALID_COMMAND'),
        ({**arguments, 'expected_research_epoch': 2}, 'STALE_EPOCH'),
        ({**arguments, 'follow_up_work_id': WORK_ID}, 'UNKNOWN_FOLLOW_UP'),
        ({**arguments, 'mission_id': str(missions[0].id)}, 'STORAGE_FAILURE'),
    ]
    async with native_client(tmp_path, case) as client:
        for raw, reason in controls:
            result = (await client.call_tool('execute_mission_follow_up', raw)).data
            assert result['status'] == 'REFUSED' and result['reason_code'] == reason
            assert all(result[key] is None for key in ('child_mission_id', 'reservation_id', 'parent_work_id',
                'gap_id', 'assignment_id', 'follow_up_work_id', 'run_id'))
            assert 'parent_mission_id' not in result
            assert result['channel_outcomes'] == []
            assert PRIVATE_SENTINEL not in json.dumps(result)
            assert await case.repository.load_mission_follow_ups(parent.id) == before
            assert _state(case) == physical_before
            assert not (tmp_path / 'probes.json').exists()
    assert PRIVATE_SENTINEL not in (tmp_path / 'stdio.log').read_text()
