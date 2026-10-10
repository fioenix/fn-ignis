"""T074 actual deterministic child execution; capability and ingress are offline doubles."""

from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import patch
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionContext
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
from ignis.domain.follow_up_admission import WorkAuthority
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from ignis.infrastructure.persistence.follow_up_admission_rules import child_records
from tests.integration import test_follow_up_sqlite_admission as setup
from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
from tests.integration.test_mission_follow_up import Ingress, OfflinePlugin, EmptyClusterer
from tests.integration.test_mission_follow_up import relay_case


class OfflineExecutionPlugin(OfflinePlugin):
    platform = PlatformType.GOOGLE_TRENDS
    connector_revision = "offline-v1"

    @property
    def plugin_id(self):
        return "offline"


class OfflineExecutionVerifier(AsyncVerifier):
    """Explicit synthetic proof; SQLite admission keeps its synchronous verifier semantics."""
    def hold_current(self, authority):
        return setup.OfflineVerifier.hold_current(self, authority)

    @asynccontextmanager
    async def hold_execution(self, authority, plan):
        assert all(source.plan_digest == plan.digest for source in authority.sources)
        async with AsyncVerifier.hold_current(self, authority) as lease:
            yield lease


async def execution_ready(tmp_path):
    ingress = Ingress()
    captured = {}
    original = setup.register

    async def register(repository, mission_id, record, key=None):
        if type(record) is WorkAuthority:
            registry = ConnectorPluginRegistry(repository)
            registry.register(OfflineExecutionPlugin(ingress))
            store = WorkspaceRepository(repository)
            executor = ExecuteMissionUseCase(repository, registry, EmptyClusterer(), store)
            canonical = await store.load_mission_evidence_snapshot(mission_id)
            candidate = child_records(canonical, record, 1, uuid4(), uuid4())
            context = FollowUpExecutionContext(record, canonical, await repository.load_research_work(mission_id),
                                               None, None, *candidate)
            service = ExecuteMissionFollowUpUseCase(repository, executor, selected_parent_id=mission_id,
                                                     host_authorized=True)
            plan, _ = await service._plan(context)
            record = replace(record, sources=tuple(replace(s, plan_digest=plan.digest) for s in record.sources))
            captured.update(executor=executor, authority=record)
        return await original(repository, mission_id, record, key)

    with patch.object(setup, "register", register):
        repository, mission, work, _, _ = await setup.ready(tmp_path, source_id="offline", source_platform="google")
    verifier = OfflineExecutionVerifier()
    repository.configure_follow_up_verifier(verifier)

    async def initialize(sources):
        assert sources == frozenset({"offline"})
        ingress.initialize_session()

    service = ExecuteMissionFollowUpUseCase(repository, captured["executor"], selected_parent_id=mission.id,
                                            host_authorized=True, session_initializer=initialize)
    return repository, mission, work, service, ingress, verifier


@pytest_asyncio.fixture
async def executor_parity_case(relay_case, tmp_path):
    """Retain SQLite recipe; bind native PG's exact youtube plugin and recorded plan."""
    case, _, _ = relay_case
    if case.name != 'postgres':
        values = await execution_ready(tmp_path)
        try:
            yield replace(case, repository=values[0]), values, 'offline'
        finally:
            await values[0].close()
        return
    from tests.integration.follow_up_execution_setup import ready
    ingress = Ingress()
    registry = ConnectorPluginRegistry(case.repository)
    registry.register(OfflinePlugin(ingress))
    executor = ExecuteMissionUseCase(case.repository, registry, EmptyClusterer(), WorkspaceRepository(case.repository))
    repository, parent, work, _, _ = await ready(case.repository, tmp_path, executor, ExecuteMissionFollowUpUseCase)

    class NativeVerifier(OfflineExecutionVerifier):
        hold_current = AsyncVerifier.hold_current

    verifier = NativeVerifier()
    repository.configure_follow_up_verifier(verifier)

    async def initialize(sources):
        assert sources == frozenset({'youtube'})
        ingress.initialize_session()

    service = ExecuteMissionFollowUpUseCase(repository, executor, selected_parent_id=parent.id,
        host_authorized=True, session_initializer=initialize)
    yield case, (repository, parent, work, service, ingress, verifier), 'youtube'


@pytest.mark.asyncio
async def test_actual_child_collection_and_original_retry_do_not_dispatch_twice(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    result = await service.execute(str(parent.id), str(work.work_id), 1, "one")
    assert result.status == "COMPLETED", result.to_payload()
    retry = await service.execute(str(parent.id), str(work.work_id), 1, "one")
    alias = await service.execute(str(parent.id), str(work.work_id), 1, "alias")
    assert retry.relationship == alias.relationship == result.relationship
    assert ingress.auth_initializations == ingress.connector_calls == 1
    assert ingress.queries == [work.requested_scope.queries]
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    assert (await repository.get_mission(parent.id)).status == "COMPLETED"
    assert len(await repository.list_run_journals(result.relationship.child_mission_id)) == 1
    assert verifier.tokens == set()
    await repository.close()


@pytest.mark.asyncio
async def test_missing_execution_provider_refuses_before_physical_admission(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    repository.configure_follow_up_verifier(setup.OfflineVerifier())
    before = await repository.load_mission_follow_ups(parent.id)
    result = await service.execute(str(parent.id), str(work.work_id), 1, "one")
    assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert ingress.auth_initializations == ingress.connector_calls == 0
    await repository.close()


@pytest.mark.asyncio
async def test_expired_awaited_capability_check_prevents_plugin_boundary(tmp_path, monkeypatch):
    import asyncio
    from ignis.application.use_cases.execute_mission_follow_up import FollowUpRefusal
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    registry = service._executor._registry
    plugin = registry.get_plugin_by_id("offline")
    entered, release = asyncio.Event(), asyncio.Event()
    current = True

    async def health():
        entered.set()
        await release.wait()
        return None

    def guard():
        if not current:
            raise FollowUpRefusal("AUTHORITY_EXPIRED")

    monkeypatch.setattr(plugin, "keyword_search_blocked_reason", health, raising=False)
    operation = getattr(registry, "_search_with_outcomes_guarded", None)
    assert operation is not None, "Guarded registry implementation is unavailable; behavior not exercised"
    task = asyncio.create_task(operation(keywords=list(work.requested_scope.queries),
                                        target_platforms=[plugin.platform], target_surfaces=("offline",),
                                        boundary_guard=guard))
    await asyncio.wait_for(entered.wait(), 5)
    current = False
    release.set()
    with pytest.raises(FollowUpRefusal, match="AUTHORITY_EXPIRED"):
        await task
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert registry._breakers["offline"].failure_count == 0
    await repository.close()


@pytest.mark.asyncio
async def test_completed_retry_key_cannot_borrow_original_child_for_changed_epoch(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    first = await service.execute(str(parent.id), str(work.work_id), 1, "bound-key")
    assert first.status == "COMPLETED"
    refused = await service.execute(str(parent.id), str(work.work_id), 2, "bound-key")
    assert refused.status == "REFUSED" and refused.reason_code == "IDEMPOTENCY_CONFLICT"
    assert refused.relationship is None
    assert ingress.auth_initializations == ingress.connector_calls == 1
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_missing_execution_provider_never_resolves_credential_runtime(executor_parity_case, monkeypatch):
    from ignis.application.ports.connector_port import IngestRuntime
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    before = await repository.load_mission_follow_ups(parent.id)
    lookups = []
    health_calls = []

    async def runtime():
        lookups.append("credential lookup")
        return IngestRuntime.HTTP_API

    async def health():
        health_calls.append('health')
        return None

    plugin = service._executor._registry.get_plugin_by_id(source)
    monkeypatch.setattr(plugin, "resolve_ingest_runtime", runtime)
    monkeypatch.setattr(plugin, 'keyword_search_blocked_reason', health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)
    repository.configure_follow_up_verifier(setup.OfflineVerifier())
    result = await service.execute(str(parent.id), str(work.work_id), 1, "missing-provider")
    assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert lookups == []
    assert health_calls == []
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert (await repository.load_mission_follow_ups(parent.id)).relationships == ()
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_false_execution_proof_never_resolves_credential_runtime(executor_parity_case, monkeypatch):
    from ignis.application.ports.connector_port import IngestRuntime
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    lookups = []
    health_calls = []

    async def runtime():
        lookups.append("credential lookup")
        return IngestRuntime.HTTP_API

    async def health():
        health_calls.append('health')
        return None

    plugin = service._executor._registry.get_plugin_by_id(source)
    monkeypatch.setattr(plugin, "resolve_ingest_runtime", runtime)
    monkeypatch.setattr(plugin, 'keyword_search_blocked_reason', health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)
    verifier.allowed = False
    before = await repository.load_mission_follow_ups(parent.id)
    result = await service.execute(str(parent.id), str(work.work_id), 1, "false-provider")
    assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert lookups == []
    assert health_calls == []
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert verifier.tokens == set()
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
@pytest.mark.parametrize("drift", ["tier", "revision", "paid", "sampling"])
async def test_actual_runtime_metadata_drift_prevents_health_and_search(executor_parity_case, monkeypatch, drift):
    from ignis.application.ports.connector_port import IngestRuntime
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    context = await repository._follow_up_execution_context(parent.id, work.work_id)
    plan, _ = await service._plan(context)
    registry = service._executor._registry
    plugin = registry.get_plugin_by_id(source)
    health_calls = []
    runtime_resolutions = []
    original_runtime = plugin.resolve_ingest_runtime

    async def runtime():
        runtime_resolutions.append('runtime resolution')
        return IngestRuntime.BROWSER if drift == 'tier' else await original_runtime()

    async def health():
        health_calls.append("health")
        return None

    monkeypatch.setattr(plugin, "keyword_search_blocked_reason", health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)
    monkeypatch.setattr(plugin, 'resolve_ingest_runtime', runtime)
    if drift == "revision":
        monkeypatch.setattr(type(plugin), "connector_revision", "changed-v2")
    elif drift == "paid":
        monkeypatch.setattr(type(plugin), "requires_paid_quota", True)
    elif drift == 'sampling':
        original = registry._search_requirement
        def requirement(*args):
            record = original(*args)
            record["sampling"] = {"limit": 21, "ordering": "platform_default"}
            return record
        monkeypatch.setattr(registry, "_search_requirement", requirement)
        monkeypatch.setattr(ConnectorPluginRegistry, "_search_requirement", staticmethod(requirement))
    with pytest.raises(FollowUpExecutionBoundaryError):
        await registry._search_with_outcomes_guarded(
            keywords=list(plan.queries), target_platforms=[plugin.platform], target_surfaces=(source,),
            boundary_guard=lambda: None, approved_plan=plan)
    assert health_calls == []
    assert runtime_resolutions == ['runtime resolution']
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert registry._breakers[source].failure_count == 0
    assert _state(case) == physical


@pytest.mark.asyncio
async def test_uninitialized_execution_context_refuses_before_worker_or_database_create(tmp_path, monkeypatch):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    from ignis.domain.exceptions import RepositoryException
    path = tmp_path / "never-created.db"
    repository = SqliteTrendRepository(str(path))
    entered = []

    async def worker(operation):
        entered.append("worker")
        raise AssertionError("Uninitialized owner reached locked worker")

    monkeypatch.setattr(repository, "_run_write", worker)
    with pytest.raises(RepositoryException):
        await repository._follow_up_execution_context(uuid4(), uuid4())
    assert entered == []
    assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_cancelled_execution_token_acquisition_creates_no_child_or_probe(executor_parity_case, monkeypatch):
    import asyncio
    from ignis.application.ports.connector_port import IngestRuntime
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    runtime_calls, health_calls = [], []

    async def runtime():
        runtime_calls.append('runtime')
        return IngestRuntime.HTTP_API

    async def health():
        health_calls.append('health')
        return None

    plugin = service._executor._registry.get_plugin_by_id(source)
    monkeypatch.setattr(plugin, 'resolve_ingest_runtime', runtime)
    monkeypatch.setattr(plugin, 'keyword_search_blocked_reason', health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)
    entered = asyncio.Event()

    @asynccontextmanager
    async def wait_for_token(authority, plan):
        entered.set()
        await asyncio.Event().wait()
        yield

    verifier.hold_execution = wait_for_token
    before = await repository.load_mission_follow_ups(parent.id)
    task = asyncio.create_task(service.execute(str(parent.id), str(work.work_id), 1, "cancel-before-token"))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert verifier.tokens == set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert verifier.tokens == set()
    assert runtime_calls == health_calls == []
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_cancelled_journal_setup_settles_before_execution_token_release(executor_parity_case, monkeypatch):
    import asyncio
    _, values, _ = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    parent_before = await repository.get_mission(parent.id)
    store = service._executor._workspace_store
    allocated, release = asyncio.Event(), asyncio.Event()
    original = store.allocate_run_journal

    async def allocate(*args, **kwargs):
        journal = await original(*args, **kwargs)
        allocated.set()
        await release.wait()
        return journal

    monkeypatch.setattr(store, "allocate_run_journal", allocate)
    task = asyncio.create_task(service.execute(str(parent.id), str(work.work_id), 1, "cancel-setup"))
    try:
        await asyncio.wait_for(allocated.wait(), 5)
        assert len(verifier.tokens) == 1
        task.cancel()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 5)
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    link = snapshot.relationships[0]
    assert snapshot.reservations[0].state == "UNRESOLVED"
    assert snapshot.reservations[0].reserved_quota == snapshot.reservations[0].reserved_cost == 2
    assert await repository.get_mission_writer_claim(link.child_mission_id) is None
    assert [j.status for j in await repository.list_run_journals(link.child_mission_id)] == ["FAILED"]
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert verifier.tokens == set()
    assert (await repository.get_mission(parent.id)).status == "COMPLETED"
    retry = await service.execute(str(parent.id), str(work.work_id), 1, "alias-after-cancel")
    assert retry.status == "RECONCILIATION_REQUIRED"
    assert retry.reason_code == "UNRESOLVED_EXECUTION" and retry.relationship == link
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert await repository.get_mission(parent.id) == parent_before


@pytest.mark.asyncio
async def test_interrupted_external_probe_cannot_be_folded_into_completed_empty_child(tmp_path):
    from tests.integration.test_mission_follow_up import InterruptedProbe
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.interrupt = True
    ingress.release.set()
    with pytest.raises(InterruptedProbe):
        await service.execute(str(parent.id), str(work.work_id), 1, "interrupt")
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    assert snapshot.reservations[0].state == "UNRESOLVED"
    child = await repository.get_mission(snapshot.relationships[0].child_mission_id)
    assert child.status != "COMPLETED"
    assert ingress.auth_initializations == ingress.connector_calls == 1
    retry = await service.execute(str(parent.id), str(work.work_id), 1, "interrupt-alias")
    assert retry.status == "RECONCILIATION_REQUIRED" and retry.reason_code == "UNRESOLVED_EXECUTION"
    assert ingress.auth_initializations == ingress.connector_calls == 1
    assert verifier.tokens == set()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_incomplete_execution_resource_proof_refuses_before_admission_or_ingress(executor_parity_case, monkeypatch):
    from ignis.application.ports.connector_port import IngestRuntime
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    runtime_calls, health_calls = [], []

    async def runtime():
        runtime_calls.append('runtime')
        return IngestRuntime.HTTP_API

    async def health():
        health_calls.append('health')
        return None

    plugin = service._executor._registry.get_plugin_by_id(source)
    monkeypatch.setattr(plugin, 'resolve_ingest_runtime', runtime)
    monkeypatch.setattr(plugin, 'keyword_search_blocked_reason', health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)
    original = verifier.hold_execution

    @asynccontextmanager
    async def incomplete(authority, plan):
        async with original(authority, plan) as lease:
            lease.proof = replace(lease.proof, resources=(("queries", 0),))
            yield lease

    verifier.hold_execution = incomplete
    ingress.release.set()
    before = await repository.load_mission_follow_ups(parent.id)
    result = await service.execute(str(parent.id), str(work.work_id), 1, "incomplete-proof")
    assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert verifier.tokens == set()
    assert runtime_calls == health_calls == []
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
@pytest.mark.parametrize("phase", ["provider", "guard"])
async def test_unavailable_execution_provider_refuses_without_runtime_or_admission(executor_parity_case, monkeypatch, phase):
    from ignis.application.ports.connector_port import IngestRuntime
    from tests.integration.test_mission_relay_read_boundary import _state
    case, values, source = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    physical = _state(case)
    runtime_calls, health_calls = [], []

    async def runtime():
        runtime_calls.append('runtime')
        return IngestRuntime.HTTP_API

    async def health():
        health_calls.append('health')
        return None

    plugin = service._executor._registry.get_plugin_by_id(source)
    monkeypatch.setattr(plugin, 'resolve_ingest_runtime', runtime)
    monkeypatch.setattr(plugin, 'keyword_search_blocked_reason', health, raising=False)
    monkeypatch.setattr(plugin, 'is_healthy', health)

    original = verifier.hold_execution

    @asynccontextmanager
    async def rejected_guard():
        raise ValueError("Synthetic current generation unavailable.")
        yield

    @asynccontextmanager
    async def unavailable(authority, plan):
        if phase == "provider":
            raise ValueError("Synthetic current generation unavailable.")
        async with original(authority, plan) as lease:
            lease.async_guard = rejected_guard
            yield lease

    verifier.hold_execution = unavailable
    before = await repository.load_mission_follow_ups(parent.id)
    result = await service.execute(str(parent.id), str(work.work_id), 1, "provider-unavailable")
    assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert await repository.load_mission_follow_ups(parent.id) == before
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert verifier.tokens == set()
    assert runtime_calls == health_calls == []
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'postgres'), indirect=True)
async def test_missing_actual_child_brief_refuses_before_journal_and_ingress(executor_parity_case, monkeypatch):
    _, values, _ = executor_parity_case
    repository, parent, work, service, ingress, verifier = values
    parent_before = await repository.get_mission(parent.id)

    async def missing_brief(mission_id):
        return None

    monkeypatch.setattr(service._executor._workspace_store, "get_brief_revision_for_mission", missing_brief)
    result = await service.execute(str(parent.id), str(work.work_id), 1, "missing-child-brief")
    assert result.status == "REFUSED" and result.reason_code == "SCOPE_MISMATCH"
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    child_id = snapshot.relationships[0].child_mission_id
    assert await repository.list_run_journals(child_id) == []
    assert await repository.get_mission_writer_claim(child_id) is None
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert verifier.tokens == set()
    assert await repository.get_mission(parent.id) == parent_before


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_reopened_initialized_owner_recovers_original_child_without_provider_or_reprobe(tmp_path, interrupted):
    from tests.integration.test_mission_follow_up import InterruptedProbe
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    ingress.interrupt = interrupted
    if interrupted:
        with pytest.raises(InterruptedProbe):
            await service.execute(str(parent.id), str(work.work_id), 1, "reopen")
    else:
        assert (await service.execute(str(parent.id), str(work.work_id), 1, "reopen")).status == "COMPLETED"
    original = await repository.load_mission_follow_ups(parent.id)
    path = repository._db_path
    await repository.close()
    reopened = setup.SqliteTrendRepository(path)
    await reopened._ensure_schema()
    registry = ConnectorPluginRegistry(reopened)
    registry.register(OfflineExecutionPlugin(ingress))
    executor = ExecuteMissionUseCase(reopened, registry, EmptyClusterer(), WorkspaceRepository(reopened))
    retry_service = ExecuteMissionFollowUpUseCase(reopened, executor, selected_parent_id=parent.id,
                                                 host_authorized=True)
    for key in ("reopen", "reopen-alias"):
        result = await retry_service.execute(str(parent.id), str(work.work_id), 1, key)
        assert result.status == ("RECONCILIATION_REQUIRED" if interrupted else "COMPLETED")
        assert result.relationship == original.relationships[0]
    current = await reopened.load_mission_follow_ups(parent.id)
    assert current.relationships == original.relationships
    assert current.reservations == original.reservations
    assert len(await reopened.list_run_journals(original.relationships[0].child_mission_id)) == 1
    assert ingress.auth_initializations == ingress.connector_calls == 1
    await reopened.close()


@pytest.mark.asyncio
async def test_cross_thread_operational_publication_waits_for_actual_execution_cleanup(tmp_path):
    import asyncio
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    task = asyncio.create_task(service.execute(str(parent.id), str(work.work_id), 1, "publication"))
    await asyncio.wait_for(ingress.entered.wait(), 5)
    publisher = asyncio.create_task(asyncio.to_thread(verifier.publish, operational=True))
    assert await asyncio.wait_for(asyncio.to_thread(verifier.publication_started.wait, 5), 6)
    assert not publisher.done()
    assert verifier.operational_generation == 1 and len(verifier.tokens) == 1
    ingress.release.set()
    result = await asyncio.wait_for(task, 5)
    await asyncio.wait_for(publisher, 5)
    assert result.status == "COMPLETED"
    assert verifier.operational_generation == 2 and verifier.tokens == set()
    assert await repository.get_mission_writer_claim(result.relationship.child_mission_id) is None
    assert ingress.auth_initializations == ingress.connector_calls == 1
    await repository.close()
