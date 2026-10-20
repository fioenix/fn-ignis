"""Private caller-scope source activation; synthetic host objects only, never a live grant."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ignis.interfaces.mcp import server


class _Scope:
    """Disposable caller scope exposing only the checked component identities."""

    def __init__(self, components):
        self.components = components
        self.checks = 0

    def check(self):
        self.checks += 1


async def _caller_components(tmp_path):
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    repository = SqliteTrendRepository(str(tmp_path / 'caller.sqlite3'))
    await repository._ensure_schema()
    store = WorkspaceRepository(repository=repository)
    registry = ConnectorPluginRegistry(repository=repository)
    class Clusterer:
        async def cluster_signals(self, signals):
            return []
    clusterer = Clusterer()
    executor = ExecuteMissionUseCase(repository=repository, registry=registry, clusterer=clusterer,
        workspace_store=store)
    return {'repository': repository, 'workspace_store': store, 'registry': registry,
            'execute_mission_use_case': executor, 'clusterer': clusterer}


def _host_objects(mission_id):
    from tests.unit.test_follow_up_root_composition import INSTRUCTION
    from tests.unit.test_follow_up_provider_bridge import Quota
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_root_composition import confirmation_at_approved_invocation
    confirmation = confirmation_at_approved_invocation(INSTRUCTION, mission_id=mission_id, run_id=uuid4())
    host_registry = ConnectorPluginRegistry()
    calls, resolutions = [], []
    def handler(request):
        calls.append(request.url.path)
        raise AssertionError('Synthetic provider must not be reached by activation')
    def resolve():
        resolutions.append('synthetic')
        return 'synthetic-only'
    return confirmation, host_registry, calls, resolutions, handler, resolve, Quota


async def _activation(scope, mission_id, tmp_path):
    from datetime import datetime, timezone
    import httpx
    from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    from ignis.infrastructure.follow_up_provider_bridge import HostProviderBridge, HostBoundYouTubePlugin
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    confirmation, host_registry, calls, resolutions, handler, resolve, Quota = _host_objects(mission_id)
    host = RootHostController(confirmation, host_registry, scope_path=tmp_path / 'root-scope.json', create=True,
                              clock=lambda: datetime.now(timezone.utc))
    accounting = PrivateRunStorage(tmp_path / 'accounting', authorize=host.authorize_storage, create=True)
    host.enroll_storage(accounting)
    budget = DurableRunCallBudget(confirmation.bounds, storage=accounting, register=True, clock=host.clock)
    bridge = HostProviderBridge(host, budget, selected_parent_id=mission_id)
    plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=resolve,
                                    transport=httpx.MockTransport(handler), quota_manager=Quota())
    host_registry.register(plugin)
    activation = CallerSourceActivation(scope=scope, host=host, bridge=bridge, plugin=plugin)
    return activation, host, bridge, accounting, calls, resolutions


def _request(mission_id):
    from ignis.domain.mission_follow_up import FollowUpExecutionRequest
    return FollowUpExecutionRequest(mission_id=mission_id, follow_up_work_id=uuid4(),
                                    expected_research_epoch=1, idempotency_key='synthetic-activation')


@pytest.mark.asyncio
async def test_default_caller_runtime_has_no_source_activation_and_refuses(tmp_path):
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    owner = server._MissionRelayRuntime()
    runtime = server._caller_runtime(scope, owner)
    try:
        assert runtime.source_activation is None
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
        result = await runtime.follow_up(_request(uuid4()))
        assert result['status'] == 'REFUSED'
    finally:
        runtime.closed = True
        await components['repository'].close()


@pytest.mark.asyncio
async def test_lifespan_factory_binds_genuine_host_to_exact_caller_storage(tmp_path):
    from ignis.application.use_cases import execute_mission_follow_up as follow_up_module
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    mission_id = uuid4()
    built = {}
    async def factory(selected_scope):
        built['value'] = await _activation(selected_scope, mission_id, tmp_path)
        return built['value'][0]
    owner = server._MissionRelayRuntime(source_activation_factory=factory)
    runtime = server._caller_runtime(scope, owner)
    try:
        await runtime.activate_source()
        activation, host, bridge, accounting, calls, resolutions = built['value']
        assert runtime.source_activation is activation
        assert activation.repository is components['repository']
        assert activation.workspace_store is components['workspace_store']
        assert activation.executor._repo is components['repository']
        assert activation.executor._workspace_store is components['workspace_store']
        assert activation.executor._registry is not components['registry']
        assert [plugin.plugin_id for plugin in activation.executor._registry.list_plugins()] == ['youtube']
        assert components['registry'].list_plugins() == []
        assert components['repository']._follow_up_verifier is bridge
        used = []
        original = follow_up_module.ExecuteMissionFollowUpUseCase.__init__
        def capture(self, repository, executor, **kwargs):
            used.append((repository, executor))
            original(self, repository, executor, **kwargs)
        follow_up_module.ExecuteMissionFollowUpUseCase.__init__ = capture
        try:
            result = await runtime.follow_up(_request(mission_id))
        finally:
            follow_up_module.ExecuteMissionFollowUpUseCase.__init__ = original
        assert used == [(components['repository'], activation.executor)]
        assert result['status'] == 'REFUSED'
        assert calls == [] and resolutions == []
        assert accounting.counts(host.confirmation.bounds) == {'search': 0, 'other': 0}
        foreign = await runtime.follow_up(_request(uuid4()))
        assert foreign == {**foreign, 'status': 'REFUSED', 'reason_code': 'SCOPE_MISMATCH'}
    finally:
        await runtime.close()
        await components['repository'].close()
    assert host._revoked and accounting.counts(host.confirmation.bounds) == {'search': 0, 'other': 0}
    assert activation.accounting_close == 'CLOSED'


@pytest.mark.asyncio
async def test_activation_refuses_foreign_storage_and_cross_loop_identity(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    components = await _caller_components(tmp_path)
    other = await _caller_components(tmp_path / 'other') if (tmp_path / 'other').mkdir() is None else None
    mission_id = uuid4()
    try:
        activation, host, *_ = await _activation(_Scope(components), mission_id, tmp_path)
        owner = server._MissionRelayRuntime(source_activation_factory=lambda scope: _return(activation))
        runtime = server._caller_runtime(_Scope(other), owner)
        with pytest.raises(FollowUpExecutionBoundaryError):
            await runtime.activate_source()
        assert runtime.source_activation is None
        assert getattr(other['repository'], '_follow_up_verifier', None) is None
        await host.revoke()
    finally:
        await components['repository'].close()
        await other['repository'].close()


async def _return(value):
    return value


async def _genuine(scope, mission_id, tmp_path, *, host_plugin=True, durable=True):
    """Trusted-root style construction: one private registry shared by host and executor."""
    from datetime import datetime, timezone
    import httpx
    from tests.unit.test_follow_up_root_composition import INSTRUCTION
    from tests.unit.test_follow_up_provider_bridge import Quota
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
    from ignis.infrastructure.follow_up_host_activation import RootHostController
    from ignis.infrastructure.follow_up_provider_bridge import HostProviderBridge, HostBoundYouTubePlugin, RunCallBudget
    from ignis.infrastructure.follow_up_root_composition import confirmation_at_approved_invocation
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    tmp_path.mkdir(parents=True, exist_ok=True)
    confirmation = confirmation_at_approved_invocation(INSTRUCTION, mission_id=mission_id, run_id=uuid4())
    registry = ConnectorPluginRegistry()
    host = RootHostController(confirmation, registry, scope_path=tmp_path / 'root-scope.json', create=True,
                              clock=lambda: datetime.now(timezone.utc))
    accounting = PrivateRunStorage(tmp_path / 'accounting', authorize=host.authorize_storage, create=True)
    host.enroll_storage(accounting)
    if durable:
        budget = DurableRunCallBudget(confirmation.bounds, storage=accounting, register=True, clock=host.clock)
    else:
        budget = RunCallBudget(confirmation.bounds, admit_fresh_run=lambda *args: True, clock=host.clock)
    bridge = HostProviderBridge(host, budget, selected_parent_id=mission_id)
    calls = []
    def handler(request):
        calls.append(request.url.path)
        raise AssertionError('Synthetic provider must not be reached by lifecycle controls')
    plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=lambda: 'synthetic-only',
                                    transport=httpx.MockTransport(handler), quota_manager=Quota())
    if host_plugin:
        registry.register(plugin)
    return SimpleNamespace(host=host, bridge=bridge, plugin=plugin, accounting=accounting, calls=calls,
        build=lambda: CallerSourceActivation(scope=scope, host=host, bridge=bridge, plugin=plugin))


def _closed_row_unlocked_later(locks):
    return None if locks else 'no lock held'


def _closed_row(accounting):
    import sqlite3
    with sqlite3.connect(accounting.path.as_uri() + '?mode=ro', uri=True) as connection:
        return connection.execute('SELECT searches,others,closed,purged FROM runs').fetchone()


@pytest.mark.parametrize('defect', ['absent-host-plugin', 'in-memory-budget'])
@pytest.mark.asyncio
async def test_activation_requires_host_attested_plugin_and_original_durable_accounting(tmp_path, defect):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    components = await _caller_components(tmp_path)
    try:
        objects = await _genuine(_Scope(components), uuid4(), tmp_path / 'host',
            host_plugin=defect != 'absent-host-plugin', durable=defect != 'in-memory-budget')
        with pytest.raises(FollowUpExecutionBoundaryError):
            objects.build()
        await objects.host.revoke()
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_factory_finishing_after_close_never_attaches_and_is_disposed(tmp_path):
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    gate, entered, made = asyncio.Event(), asyncio.Event(), {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        entered.set()
        await gate.wait()
        return made['objects'].build()
    runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        activation = asyncio.create_task(runtime.activate_source())
        await entered.wait()
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0)
        gate.set()
        await closing
        with pytest.raises(Exception):
            await activation
        objects = made['objects']
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
        assert objects.host._revoked, 'Factory result published after shutdown kept a live host'
        assert _closed_row(objects.accounting) == (0, 0, 1, 0)
        assert objects.calls == []
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_concurrent_activation_is_single_flight(tmp_path):
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    gate, built = asyncio.Event(), []
    async def factory(selected):
        objects = await _genuine(selected, uuid4(), tmp_path / f'host-{len(built)}')
        built.append(objects)
        await gate.wait()
        return objects.build()
    runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        first = asyncio.create_task(runtime.activate_source())
        second = asyncio.create_task(runtime.activate_source())
        await asyncio.sleep(0.05)
        gate.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        assert len(built) == 1, f'Concurrent activation constructed {len(built)} source runs'
        assert results[0] is results[1] is runtime.source_activation
    finally:
        await runtime.close()
        await components['repository'].close()
    assert all(objects.host._revoked for objects in built)


@pytest.mark.asyncio
async def test_rejected_attach_disposes_the_returned_activation(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    other = object()
    components['repository'].configure_follow_up_verifier(other)
    made = {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        return made['objects'].build()
    runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        with pytest.raises(FollowUpExecutionBoundaryError):
            await runtime.activate_source()
        assert components['repository']._follow_up_verifier is other
        assert made['objects'].host._revoked, 'Refused activation was left with a live host'
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
    finally:
        await runtime.close()
        await components['repository'].close()
    assert components['repository']._follow_up_verifier is other


@pytest.mark.asyncio
async def test_cancelled_caller_does_not_orphan_shared_acquisition(tmp_path):
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    gate, entered, made = asyncio.Event(), asyncio.Event(), {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        entered.set()
        await gate.wait()
        return made['objects'].build()
    runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        caller = asyncio.create_task(runtime.activate_source())
        await entered.wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        gate.set()
        await asyncio.sleep(0.05)
    finally:
        await runtime.close()
        await components['repository'].close()
    assert made['objects'].host._revoked, 'Cancelled acquisition left an unowned live host'
    assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)


@pytest.mark.asyncio
async def test_pending_accounting_close_is_retained_with_close_only_retry(tmp_path):
    import sqlite3
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    made = {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        return made['objects'].build()
    runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        activation = await runtime.activate_source()
        lock = sqlite3.connect(made['objects'].accounting.path, timeout=0)
        lock.execute('BEGIN IMMEDIATE')
        try:
            await runtime.close()
        finally:
            lock.rollback()
            lock.close()
        assert runtime.source_activation is activation, 'Runtime dropped the only cleanup handle'
        assert activation.accounting_close == 'PENDING'
        assert _closed_row(made['objects'].accounting) == (0, 0, 0, 0)
        assert made['objects'].host._revoked
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
        assert activation.retry_close() == 'CLOSED'
        assert activation.retry_close() == 'CLOSED'
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_rejected_attach_with_locked_ledger_keeps_cleanup_until_runtime_close(tmp_path):
    import sqlite3
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    components = await _caller_components(tmp_path)
    other = object()
    components['repository'].configure_follow_up_verifier(other)
    made, locks = {}, []
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        activation = made['objects'].build()
        # Construction reopens the ledger; the lock is held only from attach onwards.
        lock = sqlite3.connect(made['objects'].accounting.path, timeout=0)
        lock.execute('BEGIN IMMEDIATE')
        locks.append(lock)
        return activation
    runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
    with pytest.raises(FollowUpExecutionBoundaryError):
        await runtime.activate_source()
    assert _closed_row_unlocked_later(locks) is None
    for lock in locks:
        lock.rollback()
        lock.close()
    try:
        await runtime.close()
        assert made['objects'].host._revoked
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0), (
            'Rejected activation cleanup was not retained for runtime closure')
        assert components['repository']._follow_up_verifier is other
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_cancelled_close_observer_does_not_cancel_source_settlement(tmp_path):
    components = await _caller_components(tmp_path)
    made = {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        return made['objects'].build()
    runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
    gate = asyncio.Event()
    try:
        await runtime.activate_source()
        write = asyncio.create_task(gate.wait())
        runtime._writes.add(write)
        closing = asyncio.create_task(runtime.close())
        await asyncio.sleep(0.05)
        closing.cancel()
        await asyncio.sleep(0)
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        for _ in range(100):
            if _closed_row(made['objects'].accounting)[2] == 1:
                break
            await asyncio.sleep(0.02)
        assert made['objects'].host._revoked, 'Cancelled close observer skipped source revocation'
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_cancellation_resistant_factory_cannot_block_bounded_close(tmp_path, monkeypatch):
    components = await _caller_components(tmp_path)
    monkeypatch.setattr(server._MissionRelayRuntime, '_SOURCE_SETTLE_SECONDS', 0.1, raising=False)
    release, entered, made = asyncio.Event(), asyncio.Event(), {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        entered.set()
        while True:
            try:
                await release.wait()
                break
            except asyncio.CancelledError:
                continue
        return made['objects'].build()
    runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
    try:
        waiter = asyncio.create_task(runtime.activate_source())
        await entered.wait()
        try:
            await asyncio.wait_for(runtime.close(), timeout=3)
            bounded = True
        except TimeoutError:
            bounded = False
        release.set()
        await asyncio.gather(waiter, return_exceptions=True)
        for _ in range(100):
            if made['objects'].host._revoked:
                break
            await asyncio.sleep(0.02)
        assert bounded, 'Shutdown waited indefinitely for a cancellation-resistant factory'
        assert made['objects'].host._revoked and _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_same_bounds_substitute_ledger_is_not_original_accounting(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
    from ignis.infrastructure.follow_up_provider_bridge import HostProviderBridge, HostBoundYouTubePlugin
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    import httpx
    from tests.unit.test_follow_up_provider_bridge import Quota
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    try:
        original = await _genuine(scope, uuid4(), tmp_path / 'host')
        bounds = original.host.confirmation.bounds
        for authorize in (lambda *args: True, original.host.authorize_storage):
            substitute = PrivateRunStorage(tmp_path / f'substitute-{len(str(authorize))}', authorize=authorize, create=True)
            try:
                budget = DurableRunCallBudget(bounds, storage=substitute, register=True)
            except FollowUpExecutionBoundaryError:
                continue
            bridge = HostProviderBridge(original.host, budget, selected_parent_id=bounds and original.bridge.selected_parent_id)
            plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=lambda: 'synthetic-only',
                transport=httpx.MockTransport(lambda request: None), quota_manager=Quota())
            original.host.registry._plugins.clear()
            original.host.registry.register(plugin)
            with pytest.raises(FollowUpExecutionBoundaryError):
                CallerSourceActivation(scope=scope, host=original.host, bridge=bridge, plugin=plugin)
        await original.host.revoke()
    finally:
        await components['repository'].close()


async def _confirmed_caller_parent(components, tmp_path):
    """Confirm the approved tutorial Brief through the caller's own canonical use cases."""
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path
    from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
    from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
    from ignis.domain.research_workspace import MissionManifest, AuthorityBoundary, MissionOutputType
    brief = _json.loads((Path(__file__).parents[1] / 'fixtures' / 'follow_up_tutorial_brief.json').read_text())
    store, repository = components['workspace_store'], components['repository']
    proposal = await CreateResearchWorkspaceUseCase(store).propose(tmp_path / 'caller-workspace', 'Caller pilot')
    from ignis.domain.research_workspace import ResearchWorkspace
    workspace = ResearchWorkspace(slug=proposal.slug, root_path=proposal.proposed_path, name=proposal.research_name)
    workspace.root_path.mkdir(parents=True, exist_ok=True)
    workspace.manifest_path.write_text(workspace.manifest_json())
    workspace = await store.save_research_workspace(workspace)
    manifest = MissionManifest(outcome=brief['decision'], decision_context=brief['decision'],
        required_channels=('youtube',), optional_channels=(),
        authority_boundary=AuthorityBoundary(public_http=False, official_api=True, browser_session=False, paid_quota=False),
        quota_budget={'queries': 2, 'youtube_search_calls': 2}, output_type=MissionOutputType.MARKET_ANALYSIS,
        stop_conditions=('deadline or aggregate budget or missing authority',), analysis_policy='evidence-gated-v1',
        retention_policy='caller-retained-until-explicit-user-deletion', created_by='synthetic-test-owner',
        confirmed_at=datetime.now(timezone.utc))
    mission, revision = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, manifest=manifest, confirmed_by='synthetic-test-owner',
        keywords=['n8n Việt Nam'], **brief)
    return mission


def _video_transport(calls):
    import httpx
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    async def handler(request):
        calls.append((request.url.path.rsplit('/', 1)[-1], dict(request.url.params)))
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={'items': [{'id': {'videoId': 'caller-parent'}}]})
        return httpx.Response(200, json={'items': [{'id': 'caller-parent', 'snippet': {
            'title': 'Hướng dẫn n8n cho người mới', 'description': 'Synthetic caller description.',
            'publishedAt': now.isoformat()}, 'statistics': {'viewCount': '10'}}]})
    return httpx.MockTransport(handler)


async def _genuine_for(scope, mission_id, tmp_path, calls, resolutions):
    objects = await _genuine(scope, mission_id, tmp_path)
    objects.plugin._transport = _video_transport(calls)
    def resolve():
        resolutions.append('synthetic')
        return 'synthetic-only'
    objects.plugin._resolve_credential = resolve
    return objects


@pytest.mark.asyncio
async def test_caller_parent_runs_guarded_route_on_borrowed_canonical_storage(tmp_path):
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    calls, resolutions, made = [], [], {}
    try:
        mission = await _confirmed_caller_parent(components, tmp_path)
        async def factory(selected):
            made['objects'] = await _genuine_for(selected, mission.id, tmp_path / 'host', calls, resolutions)
            return made['objects'].build()
        runtime = server._caller_runtime(scope, server._MissionRelayRuntime(source_activation_factory=factory))
        result = await runtime.source_parent(str(mission.id))
        assert result['status'] == 'PARENT_EXECUTION_RETURNED', result
        snapshot = await components['workspace_store'].load_mission_evidence_snapshot(mission.id)
        assert snapshot.mission.status == 'COMPLETED' and len(snapshot.signals) == 1
        assert snapshot.signals[0].metadata['description'] == 'Synthetic caller description.'
        assert [endpoint for endpoint, _ in calls] == ['search', 'videos'] and len(resolutions) == 2
        assert calls[0][1]['q'] == 'n8n Việt Nam' and calls[0][1]['maxResults'] == '5'
        assert calls[0][1]['regionCode'] == 'VN' and calls[0][1]['relevanceLanguage'] == 'vi'
        assert made['objects'].accounting.counts(made['objects'].host.confirmation.bounds) == {'search': 1, 'other': 1}
        again = await runtime.source_parent(str(mission.id))
        assert again == {'status': 'REFUSED', 'reason_code': 'PARENT_ALREADY_TERMINAL'}
        assert len(calls) == 2
        await runtime.close()
        assert made['objects'].host._revoked and _closed_row(made['objects'].accounting) == (1, 1, 1, 0)
        retained = await components['workspace_store'].load_mission_evidence_snapshot(mission.id)
        assert len(retained.signals) == 1, 'Caller canonical data must remain usable after source close'
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_caller_parent_refuses_without_injection_or_for_foreign_mission(tmp_path):
    components = await _caller_components(tmp_path)
    calls, resolutions = [], []
    try:
        mission = await _confirmed_caller_parent(components, tmp_path)
        runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime())
        assert await runtime.source_parent(str(mission.id)) == {'status': 'REFUSED', 'reason_code': 'SESSION_AUTHORITY_REQUIRED'}
        runtime.closed = True
        made = {}
        async def factory(selected):
            made['objects'] = await _genuine_for(selected, uuid4(), tmp_path / 'host', calls, resolutions)
            return made['objects'].build()
        activated = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
        assert await activated.source_parent(str(mission.id)) == {'status': 'REFUSED', 'reason_code': 'SCOPE_MISMATCH'}
        await activated.close()
        assert calls == [] and resolutions == []
        assert made['objects'].accounting.counts(made['objects'].host.confirmation.bounds) == {'search': 0, 'other': 0}
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_caller_child_from_genuine_gap_shares_original_aggregate_budget(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
    from ignis.application.ports.research_work_port import (ResearchWorkCommitCommand,
        ResearchAssignmentAdmission, FollowUpWorkCommand)
    from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
    from ignis.domain.follow_up_admission import OperationalGap, ParentBudget, AssignmentBudget, SourceGrant, WorkAuthority
    from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope, FollowUpExecutionRequest
    from ignis.domain.research_work import ResearchAssignment, ResearchAuthority, ResearchInputBindings, ResearchWorkItem
    from ignis.domain.research_workspace import compute_frame_fingerprint
    components = await _caller_components(tmp_path)
    repository, store = components['repository'], components['workspace_store']
    calls, resolutions, made = [], [], {}
    try:
        mission = await _confirmed_caller_parent(components, tmp_path)
        async def factory(selected):
            made['objects'] = await _genuine_for(selected, mission.id, tmp_path / 'host', calls, resolutions)
            return made['objects'].build()
        runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
        parent = await runtime.source_parent(str(mission.id))
        assert parent['status'] == 'PARENT_EXECUTION_RETURNED'
        objects = made['objects']
        host, bounds = objects.host, objects.host.confirmation.bounds
        evidence = await store.load_mission_evidence_snapshot(mission.id)
        frame = frame_from_snapshot(evidence)
        inputs = ResearchInputBindings(mission_id=mission.id, manifest_digest=evidence.manifest.manifest_digest,
            brief_digest=compute_frame_fingerprint(evidence.mission, evidence.brief), frame_digest=frame.frame_digest,
            observation_ids=tuple(sorted((s.observation_id for s in evidence.signals), key=str)), finding_revisions=())
        assignment = ResearchAssignment(assignment_id=uuid4(), mission_id=mission.id, host_task_ref='synthetic-root',
            epoch=1, authority=ResearchAuthority(actions=frozenset({'ANALYZE', 'FOLLOW_UP'}), sources=frozenset({'youtube'}),
                deadline=bounds.deadline, quota_ceiling=1), capability='SEQUENTIAL', state='ASSIGNED', version=1)
        revision = (await repository.load_research_work(mission.id)).revision
        async def commit(operation, payload):
            nonlocal revision
            receipt = await repository.commit_research_work(ResearchWorkCommitCommand(mission_id=mission.id,
                operation=operation, payload=payload, expected_revision=revision, expected_epoch=1,
                idempotency_key=uuid4().hex, host_authorized=True))
            assert receipt.disposition == 'APPLIED', receipt
            revision = receipt.revision
        await commit('ASSIGN_RESEARCH', ResearchAssignmentAdmission(assignment=assignment,
            expected_manifest_digest=inputs.manifest_digest, expected_brief_revision_id=evidence.brief.brief_revision_id))
        work = ResearchWorkItem(work_id=uuid4(), assignment_id=assignment.assignment_id, mission_id=mission.id,
            run_id=None, question='Is relevant automation material present beyond the parent query?',
            expertise='Synthesis', assignee_ref='synthetic-root', inputs=inputs, dependencies=(), epoch=1,
            state='ASSIGNED', version=1, ownership_fence='synthetic-root')
        await commit('ASSIGN_WORK', work)
        child_item = ResearchWorkItem(**{**{f: getattr(work, f) for f in work.__dataclass_fields__}, 'work_id': uuid4()})
        await commit('ASSIGN_WORK', child_item)
        reference = host.confirmation.reference
        gap = OperationalGap(gap_id=uuid4(), parent_work_id=work.work_id, inputs=inputs, question=work.question)
        root = ParentBudget(budget_id=uuid4(), mission_id=mission.id, manifest_digest=inputs.manifest_digest,
            brief_digest=inputs.brief_digest, quota_unit='query', cost_unit='call', quota_ceiling=1, cost_ceiling=1,
            resources=(('queries', 1), ('youtube_search_calls', 1)), confirmation_ref=reference)
        binding = AssignmentBudget(binding_id=uuid4(), budget_id=root.budget_id, assignment_id=assignment.assignment_id,
            epoch=1, assignment_version=1, assignment_quota=1, quota_unit='query', cost_ceiling=1, confirmation_ref=reference)
        scope = FollowUpScope(queries=('n8n tự động hóa',), sources=frozenset({'youtube'}))
        follow = FollowUpWork(work_id=child_item.work_id, parent_work_id=work.work_id, assignment_id=assignment.assignment_id,
            gap_id=gap.gap_id, inputs=inputs, research_epoch=1, assignment_version=1, work_version=1,
            brief_revision_id=evidence.brief.brief_revision_id, approved_scope=scope, requested_scope=scope,
            authority_deadline=bounds.deadline)
        source = SourceGrant(source='youtube', platform='youtube', tier='official_api', paid=False, plan_digest='0' * 64,
            connector_revision=objects.plugin.connector_revision, capability_id=host.capability_id, capability_epoch=host.generation)
        authority = WorkAuthority(work=follow, budget_id=root.budget_id, binding_id=binding.binding_id, quota_unit='query',
            cost_unit='call', quota=1, cost=1, quota_ceiling=1, cost_ceiling=1,
            resources=(('queries', 1), ('youtube_search_calls', 1)), sources=(source,), confirmation_ref=reference)
        stale = WorkAuthority(**{**{f: getattr(authority, f) for f in authority.__dataclass_fields__},
            'work': FollowUpWork(**{**{f: getattr(follow, f) for f in follow.__dataclass_fields__},
                'inputs': ResearchInputBindings(**{**{f: getattr(inputs, f) for f in inputs.__dataclass_fields__}, 'frame_digest': 'f' * 64})})})
        with pytest.raises(FollowUpExecutionBoundaryError):
            await runtime.source_activation.enroll_child(stale, parent_budget=root, assignment_budget=binding)
        bound = await runtime.source_activation.enroll_child(authority, parent_budget=root, assignment_budget=binding)
        for record in (gap, root, binding, bound):
            receipt = await repository.record_follow_up_fact(FollowUpFactCommand(mission_id=mission.id, record=record,
                expected_revision=(await repository.load_research_work(mission.id)).revision,
                idempotency_key=uuid4().hex, host_authorized=True))
            assert receipt.disposition == 'APPLIED', receipt
        receipt = await repository.record_follow_up_work(FollowUpWorkCommand(work=follow,
            expected_revision=(await repository.load_research_work(mission.id)).revision,
            idempotency_key='synthetic-child', host_authorized=True))
        assert receipt.disposition == 'APPLIED', receipt
        result = await runtime.follow_up(FollowUpExecutionRequest(mission_id=mission.id, follow_up_work_id=follow.work_id,
            expected_research_epoch=1, idempotency_key='synthetic-child-run'))
        assert result['status'] == 'COMPLETED', result
        assert result['child_mission_id'] and result['child_mission_id'] != str(mission.id)
        assert [endpoint for endpoint, _ in calls] == ['search', 'videos', 'search', 'videos'] and len(resolutions) == 4
        assert calls[2][1]['q'] == 'n8n tự động hóa' and calls[2][1]['maxResults'] == '5'
        assert objects.accounting.counts(bounds) == {'search': 2, 'other': 2}
        with pytest.raises(FollowUpExecutionBoundaryError):
            objects.bridge.budget.charge('search')
        parent_after = await store.load_mission_evidence_snapshot(mission.id)
        assert parent_after.mission.status == 'COMPLETED' and len(parent_after.signals) == 1
        await runtime.close()
        assert host._revoked and _closed_row(objects.accounting) == (2, 2, 1, 0)
    finally:
        await components['repository'].close()


async def _record_genuine_child(components, activation, mission_id, *, stale=False):
    """Trusted-root fixture: persist the terminal parent's gap and child work via canonical APIs.

    Assumption recorded for review: the gap is supplied explicitly by the trusted root; this
    proves the admission/execution contract, not semantic gap discovery.
    """
    from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
    from ignis.application.ports.research_work_port import (ResearchWorkCommitCommand,
        ResearchAssignmentAdmission, FollowUpWorkCommand)
    from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
    from ignis.domain.follow_up_admission import OperationalGap, ParentBudget, AssignmentBudget, SourceGrant, WorkAuthority
    from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope
    from ignis.domain.research_work import ResearchAssignment, ResearchAuthority, ResearchInputBindings, ResearchWorkItem
    from ignis.domain.research_workspace import compute_frame_fingerprint
    repository, store = components['repository'], components['workspace_store']
    host, bounds = activation.host, activation.bounds
    evidence = await store.load_mission_evidence_snapshot(mission_id)
    frame = frame_from_snapshot(evidence)
    inputs = ResearchInputBindings(mission_id=mission_id, manifest_digest=evidence.manifest.manifest_digest,
        brief_digest=compute_frame_fingerprint(evidence.mission, evidence.brief),
        frame_digest='f' * 64 if stale else frame.frame_digest,
        observation_ids=tuple(sorted((s.observation_id for s in evidence.signals), key=str)), finding_revisions=())
    current = ResearchInputBindings(**{**{f: getattr(inputs, f) for f in inputs.__dataclass_fields__}, 'frame_digest': frame.frame_digest})
    research = await repository.load_research_work(mission_id)
    epoch = max(research.current_epoch, 1)
    assignment = ResearchAssignment(assignment_id=uuid4(), mission_id=mission_id, host_task_ref='synthetic-root',
        epoch=epoch, authority=ResearchAuthority(actions=frozenset({'ANALYZE', 'FOLLOW_UP'}), sources=frozenset({'youtube'}),
            deadline=bounds.deadline, quota_ceiling=1), capability='SEQUENTIAL', state='ASSIGNED', version=1)
    revision = research.revision
    async def commit(operation, payload):
        nonlocal revision
        receipt = await repository.commit_research_work(ResearchWorkCommitCommand(mission_id=mission_id,
            operation=operation, payload=payload, expected_revision=revision, expected_epoch=epoch,
            idempotency_key=uuid4().hex, host_authorized=True))
        if receipt.disposition != 'APPLIED':
            raise ValueError(receipt.reason_code)
        revision = receipt.revision
    if not stale:
        await commit('ASSIGN_RESEARCH', ResearchAssignmentAdmission(assignment=assignment,
            expected_manifest_digest=current.manifest_digest, expected_brief_revision_id=evidence.brief.brief_revision_id))
    work = ResearchWorkItem(work_id=uuid4(), assignment_id=assignment.assignment_id, mission_id=mission_id, run_id=None,
        question='Is relevant automation material present beyond the parent query?', expertise='Synthesis',
        assignee_ref='synthetic-root', inputs=current, dependencies=(), epoch=epoch, state='ASSIGNED', version=1,
        ownership_fence='synthetic-root')
    child_item = ResearchWorkItem(**{**{f: getattr(work, f) for f in work.__dataclass_fields__}, 'work_id': uuid4()})
    if not stale:
        await commit('ASSIGN_WORK', work)
        await commit('ASSIGN_WORK', child_item)
    reference = host.confirmation.reference
    gap = OperationalGap(gap_id=uuid4(), parent_work_id=work.work_id, inputs=inputs, question=work.question)
    root = ParentBudget(budget_id=uuid4(), mission_id=mission_id, manifest_digest=inputs.manifest_digest,
        brief_digest=inputs.brief_digest, quota_unit='query', cost_unit='call', quota_ceiling=1, cost_ceiling=1,
        resources=(('queries', 1), ('youtube_search_calls', 1)), confirmation_ref=reference)
    binding = AssignmentBudget(binding_id=uuid4(), budget_id=root.budget_id, assignment_id=assignment.assignment_id,
        epoch=epoch, assignment_version=1, assignment_quota=1, quota_unit='query', cost_ceiling=1, confirmation_ref=reference)
    scope = FollowUpScope(queries=('n8n tự động hóa',), sources=frozenset({'youtube'}))
    follow = FollowUpWork(work_id=child_item.work_id, parent_work_id=work.work_id, assignment_id=assignment.assignment_id,
        gap_id=gap.gap_id, inputs=inputs, research_epoch=epoch, assignment_version=1, work_version=1,
        brief_revision_id=evidence.brief.brief_revision_id, approved_scope=scope, requested_scope=scope,
        authority_deadline=bounds.deadline)
    source = SourceGrant(source='youtube', platform='youtube', tier='official_api', paid=False, plan_digest='0' * 64,
        connector_revision=activation.plugin.connector_revision, capability_id=host.capability_id, capability_epoch=host.generation)
    authority = WorkAuthority(work=follow, budget_id=root.budget_id, binding_id=binding.binding_id, quota_unit='query',
        cost_unit='call', quota=1, cost=1, quota_ceiling=1, cost_ceiling=1,
        resources=(('queries', 1), ('youtube_search_calls', 1)), sources=(source,), confirmation_ref=reference)
    bound = await activation.enroll_child(authority, parent_budget=root, assignment_budget=binding)
    for record in (gap, root, binding, bound):
        receipt = await repository.record_follow_up_fact(FollowUpFactCommand(mission_id=mission_id, record=record,
            expected_revision=(await repository.load_research_work(mission_id)).revision,
            idempotency_key=uuid4().hex, host_authorized=True))
        if receipt.disposition != 'APPLIED':
            raise ValueError(receipt.reason_code)
    receipt = await repository.record_follow_up_work(FollowUpWorkCommand(work=follow,
        expected_revision=(await repository.load_research_work(mission_id)).revision,
        idempotency_key=uuid4().hex, host_authorized=True))
    if receipt.disposition != 'APPLIED':
        raise ValueError(receipt.reason_code)
    return follow.work_id


def _owner_with_caller(components, factory):
    owner = server._MissionRelayRuntime(source_activation_factory=factory)
    scope = _Scope(components)
    scope.log_handler = None
    scope.runtime = server._caller_runtime(scope, owner)
    owner.caller_scopes['disposable'] = scope
    events = []
    original_close = components['repository'].close
    async def close():
        events.append('repository_closed')
        await original_close()
    components['repository'].close = close
    return owner, scope, events, original_close


@pytest.mark.asyncio
async def test_cancelled_parent_observer_keeps_worker_owned_until_settled(tmp_path):
    import httpx
    components = await _caller_components(tmp_path)
    calls, resolutions, made = [], [], {}
    entered, release = asyncio.Event(), asyncio.Event()
    try:
        mission = await _confirmed_caller_parent(components, tmp_path)
        async def handler(request):
            calls.append(request.url.path)
            entered.set()
            await release.wait()
            return httpx.Response(200, json={'items': []})
        async def factory(selected):
            made['objects'] = await _genuine_for(selected, mission.id, tmp_path / 'host', [], resolutions)
            made['objects'].plugin._transport = httpx.MockTransport(handler)
            return made['objects'].build()
        runtime = server._caller_runtime(_Scope(components), server._MissionRelayRuntime(source_activation_factory=factory))
        observer = asyncio.create_task(runtime.source_parent(str(mission.id)))
        await entered.wait()
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert runtime._executions, 'Cancelled parent observer dropped ownership of a running worker'
        release.set()
        await runtime.close()
        assert not runtime._executions and made['objects'].host._revoked
        settled_calls = len(calls)
        await asyncio.sleep(0.05)
        assert len(calls) == settled_calls <= 1
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_cancelled_outer_owner_still_closes_caller_source_before_repository(tmp_path):
    components = await _caller_components(tmp_path)
    made = {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        return made['objects'].build()
    owner, scope, events, original_close = _owner_with_caller(components, factory)
    gate = asyncio.Event()
    try:
        await scope.runtime.activate_source()
        write = asyncio.create_task(gate.wait())
        owner._writes.add(write)
        closing = asyncio.create_task(owner.close())
        await asyncio.sleep(0.05)
        closing.cancel()
        await asyncio.sleep(0)
        gate.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        for _ in range(100):
            if events:
                break
            await asyncio.sleep(0.02)
        assert made['objects'].host._revoked, 'Outer owner cancellation skipped caller source revocation'
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
        assert getattr(components['repository'], '_follow_up_verifier', None) is None
        assert events == ['repository_closed']
    finally:
        if not events:
            await original_close()


@pytest.mark.asyncio
async def test_resistant_acquisition_reports_pending_and_keeps_borrowed_repository_open(tmp_path, monkeypatch):
    components = await _caller_components(tmp_path)
    monkeypatch.setattr(server._MissionRelayRuntime, '_SOURCE_SETTLE_SECONDS', 0.05)
    release, entered, made = asyncio.Event(), asyncio.Event(), {}
    async def factory(selected):
        made['objects'] = await _genuine(selected, uuid4(), tmp_path / 'host')
        entered.set()
        while True:
            try:
                await release.wait()
                break
            except asyncio.CancelledError:
                continue
        return made['objects'].build()
    owner, scope, events, original_close = _owner_with_caller(components, factory)
    try:
        waiter = asyncio.create_task(scope.runtime.activate_source())
        await entered.wait()
        await asyncio.wait_for(owner.close(), timeout=3)
        assert getattr(scope.runtime, 'source_state', None) == 'PENDING'
        assert events == [], 'Borrowed caller repository closed under a live acquisition'
        release.set()
        await asyncio.gather(waiter, return_exceptions=True)
        for _ in range(150):
            if events:
                break
            await asyncio.sleep(0.02)
        assert made['objects'].host._revoked and _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
        assert events == ['repository_closed'] and scope.runtime.source_state == 'QUIESCENT'
    finally:
        release.set()
        await asyncio.sleep(0.05)
        if not events:
            await original_close()


@pytest.mark.asyncio
async def test_copied_stale_ledger_with_original_callback_is_refused(tmp_path):
    import shutil
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    from ignis.infrastructure.follow_up_caller_activation import CallerSourceActivation
    from ignis.infrastructure.follow_up_provider_bridge import HostProviderBridge
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    components = await _caller_components(tmp_path)
    scope = _Scope(components)
    try:
        original = await _genuine(scope, uuid4(), tmp_path / 'host')
        bounds = original.host.confirmation.bounds
        copy_root = tmp_path / 'copied-ledger'
        copy_root.mkdir()
        shutil.copy2(original.accounting.path, copy_root / original.accounting.path.name)
        original.bridge.budget.charge('search')
        copied = PrivateRunStorage(copy_root, authorize=original.host.authorize_storage)
        budget = DurableRunCallBudget(bounds, storage=copied)
        assert copied.counts(bounds) == {'search': 0, 'other': 0}
        bridge = HostProviderBridge(original.host, budget, selected_parent_id=original.bridge.selected_parent_id)
        original.plugin._bridge = bridge
        with pytest.raises(FollowUpExecutionBoundaryError):
            CallerSourceActivation(scope=scope, host=original.host, bridge=bridge, plugin=original.plugin)
        assert original.accounting.counts(bounds) == {'search': 1, 'other': 0}
        assert copied.counts(bounds) == {'search': 0, 'other': 0}
        await original.host.revoke()
    finally:
        await components['repository'].close()


@pytest.mark.asyncio
async def test_parent_observer_cancelled_before_lease_settles_worker_without_spend(tmp_path):
    components = await _caller_components(tmp_path)
    calls, resolutions, made = [], [], {}
    gate, entered = asyncio.Event(), asyncio.Event()
    store = components['workspace_store']
    try:
        mission = await _confirmed_caller_parent(components, tmp_path)
        original_load = store.load_mission_evidence_snapshot
        async def gated_load(mission_id):
            entered.set()
            await gate.wait()
            return await original_load(mission_id)
        async def factory(selected):
            made['objects'] = await _genuine_for(selected, mission.id, tmp_path / 'host', calls, resolutions)
            return made['objects'].build()
        owner, scope, events, original_close = _owner_with_caller(components, factory)
        await scope.runtime.activate_source()
        store.load_mission_evidence_snapshot = gated_load
        observer = asyncio.create_task(scope.runtime.source_parent(str(mission.id)))
        await entered.wait()
        observer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert scope.runtime._executions, 'Pre-lease worker must stay owned after its observer is cancelled'
        worker = next(iter(scope.runtime._executions))
        gate.set()
        await asyncio.gather(worker, return_exceptions=True)
        await asyncio.sleep(0)  # done-callbacks run on the next loop iteration
        assert worker.cancelled() and not scope.runtime._executions
        store.load_mission_evidence_snapshot = original_load
        assert made['objects'].host._enrollments == {}, 'Cancelled parent enrolled a source binding'
        await owner.close()
        assert calls == [] and resolutions == []
        assert _closed_row(made['objects'].accounting) == (0, 0, 1, 0)
        assert events == ['repository_closed']
        reopened = await helpers_reopen_status(components, tmp_path, mission.id)
        assert reopened == 'PENDING', f'Cancelled parent changed canonical mission status to {reopened}'
    finally:
        pass


async def helpers_reopen_status(components, tmp_path, mission_id):
    import sqlite3
    with sqlite3.connect((tmp_path / 'caller.sqlite3').as_uri() + '?mode=ro', uri=True) as connection:
        row = connection.execute('SELECT status FROM research_missions WHERE id=?', (str(mission_id),)).fetchone()
    return row[0]


@pytest.mark.asyncio
async def test_original_budget_refuses_fifth_other_call_and_any_call_after_deadline(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    components = await _caller_components(tmp_path)
    try:
        objects = await _genuine(_Scope(components), uuid4(), tmp_path / 'host')
        budget, bounds = objects.bridge.budget, objects.host.confirmation.bounds
        assert (bounds.search_calls, bounds.other_calls, bounds.video_limit) == (2, 4, 5)
        assert (bounds.deadline - bounds.started_at).total_seconds() == 15 * 60
        for _ in range(4):
            budget.charge('other')
        with pytest.raises(FollowUpExecutionBoundaryError):
            budget.charge('other')
        assert objects.accounting.counts(bounds) == {'search': 0, 'other': 4}
        budget.clock = lambda: bounds.deadline
        assert budget.current() is False
        with pytest.raises(FollowUpExecutionBoundaryError):
            budget.charge('search')
        assert objects.accounting.counts(bounds) == {'search': 0, 'other': 4}
        await objects.host.revoke()
    finally:
        await components['repository'].close()
