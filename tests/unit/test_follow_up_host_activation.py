"""Offline root activation boundaries; all owner records/transport/keys are synthetic."""

import asyncio
from dataclasses import replace

import pytest

from tests.unit.test_follow_up_provider_bridge import setup_bridge
from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError, FollowUpExecutionPlan
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.follow_up_host_activation import (
    RootOwnerConfirmation, RootHostController, IsolatedCanonicalSQLite, open_owned_canonical_repository,
)
from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
from ignis.domain.follow_up_admission import digest


def root_setup(tmp_path):
    bridge, _, bindings, _, plugin, calls, credentials, quota, clock, _ = setup_bridge()
    registry = ConnectorPluginRegistry()
    registry.register(plugin)
    confirmation = RootOwnerConfirmation(reference='synthetic-explicit-root-instruction',
        credential_reference='synthetic-deferred-key-reference', bounds=bridge.budget.bounds,
        selected_parent_id=bridge.selected_parent_id, source='youtube', platform='youtube',
        tier='official_api', revision='unversioned', geo=bindings[0].geo, timeframe=bindings[0].timeframe)
    controller = RootHostController(confirmation, registry, scope_path=tmp_path/'root-scope.json',
        create=True, clock=lambda: clock[0])
    metadata = registry._search_requirement(plugin, 'official_api', list(bindings[0].queries))
    plan = FollowUpExecutionPlan(queries=bindings[0].queries,
        connectors=((plugin.plugin_id,plugin.platform.value,plugin.http_authority,plugin.connector_revision,
                     metadata['connector_path'],20,'platform_default',False),),
        resources=(('queries',1),('youtube_search_calls',1)), geo=bindings[0].geo, timeframe=bindings[0].timeframe)
    binding = replace(bindings[0], confirmation_ref=confirmation.reference, plan_digest=plan.digest,
        sources=(replace(bindings[0].sources[0], plan_digest=plan.digest,
                         capability_id=controller.capability_id, capability_epoch=1),))
    controller.enroll_parent(binding, plan)
    bridge._host = controller
    bridge._bindings.clear()
    storage = PrivateRunStorage(tmp_path/'accounting', authorize=controller.authorize_storage, create=True)
    bridge.budget = DurableRunCallBudget(confirmation.bounds, storage=storage, register=True, clock=lambda: clock[0])
    bridge.register(binding)
    return bridge, controller, registry, binding, plan, plugin, calls, credentials, quota, clock


@pytest.mark.asyncio
async def test_removed_registered_provider_refuses_before_private_credential_resolution(tmp_path):
    bridge, host, registry, binding, _, plugin, calls, credentials, quota, _ = root_setup(tmp_path)
    async with host.hold_parent(binding) as lease:
        async with bridge.hold_parent_transport(binding, lease):
            registry._plugins.pop(plugin.plugin_id)
            assert await plugin.is_healthy() is False
    assert credentials == calls == []
    assert quota.calls == 0
    assert bridge.budget._used == {'search':0,'other':0}


@pytest.mark.asyncio
async def test_actual_root_controller_produces_held_parent_permission_and_durable_charge(tmp_path):
    bridge, host, _, binding, _, plugin, calls, credentials, _, _ = root_setup(tmp_path)
    async with host.hold_parent(binding) as lease:
        assert lease.proof.process_id == host.process_id
        async with bridge.hold_parent_transport(binding, lease):
            assert len(await plugin.search_signals(list(binding.queries))) == 5
    assert host._tokens == 0
    assert len(calls) == len(credentials) == 2
    assert bridge.budget._used == {'search':1,'other':1}
    assert host.verify_owner('unknown-instruction', digest((binding, bridge.budget.bounds))) is False


@pytest.mark.asyncio
async def test_parent_enrollment_does_not_license_child_or_changed_plan(tmp_path):
    _, host, _, binding, plan, _, calls, credentials, _, _ = root_setup(tmp_path)
    with pytest.raises(FollowUpExecutionBoundaryError):
        host.enroll_parent(replace(binding, queries=host.confirmation.bounds.queries[1:]), plan)
    with pytest.raises(FollowUpExecutionBoundaryError):
        host.enroll_parent(binding, replace(plan, geo='GeoCode.US'))
    with pytest.raises(FollowUpExecutionBoundaryError):
        async with host.hold_parent(replace(binding, work_id=host.confirmation.bounds.run_id)):
            pass
    assert calls == credentials == []


@pytest.mark.asyncio
async def test_revocation_cancels_only_held_owned_task_and_settles_tokens(tmp_path):
    bridge, host, _, binding, _, plugin, calls, credentials, _, _ = root_setup(tmp_path)
    entered = asyncio.Event()
    async def held():
        async with host.hold_parent(binding) as lease:
            async with bridge.hold_parent_transport(binding, lease):
                entered.set()
                await asyncio.Event().wait()
                await plugin.is_healthy()
    worker = asyncio.create_task(held())
    await asyncio.wait_for(entered.wait(), 1)
    await host.revoke(timeout=1)
    with pytest.raises(asyncio.CancelledError):
        await worker
    assert host._tokens == 0 and host._tasks == {}
    assert calls == credentials == []
    assert host.authorize_storage('reopen', bridge.budget.bounds.run_id, digest(bridge.budget.bounds)) is False


@pytest.mark.asyncio
async def test_restart_scope_does_not_restore_lease_or_reset_original_accounting(tmp_path):
    bridge, host, registry, binding, _, _, _, _, _, clock = root_setup(tmp_path)
    bridge.budget.charge('search')
    fresh = RootHostController(host.confirmation, registry, scope_path=tmp_path/'root-scope.json', clock=lambda: clock[0])
    assert fresh.process_id != host.process_id
    assert fresh._enrollments == {}
    with pytest.raises(FollowUpExecutionBoundaryError):
        async with fresh.hold_parent(binding):
            pass
    storage = PrivateRunStorage(tmp_path/'accounting', authorize=fresh.authorize_storage)
    reopened = DurableRunCallBudget(host.confirmation.bounds, storage=storage, clock=lambda: clock[0])
    assert reopened._used == {'search':1,'other':0}
    with pytest.raises(FollowUpExecutionBoundaryError):
        RootHostController(replace(host.confirmation, reference='different-root-confirmation'), registry,
                           scope_path=tmp_path/'root-scope.json', clock=lambda: clock[0])


@pytest.mark.asyncio
async def test_canonical_expiry_physically_purges_owned_observations_and_blocks_recreation(tmp_path):
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    bridge, host, _, _, _, _, _, _, _, clock = root_setup(tmp_path)
    enrollment = IsolatedCanonicalSQLite(tmp_path/'canonical', host.confirmation, create=True)
    repository = open_owned_canonical_repository(enrollment)
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    assert type(repository) is SqliteTrendRepository
    assert await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title='SYNTHETIC_CANONICAL_RETENTION_SENTINEL', source_url='https://example.invalid/owned')]) == 1
    assert b'SYNTHETIC_CANONICAL_RETENTION_SENTINEL' in enrollment.path.read_bytes()
    with repository._get_connection() as connection:
        assert connection.execute('SELECT COUNT(*) FROM observations').fetchone()[0] == 1
        assert connection.execute('SELECT COUNT(*) FROM sources').fetchone()[0] == 1
    foreign = tmp_path/'foreign.sqlite3'
    foreign.write_bytes(b'Unrelated owner store')
    with pytest.raises(FollowUpExecutionBoundaryError):
        await enrollment.purge(host, repository)
    assert enrollment.path.exists()
    clock[0] = host.confirmation.bounds.retention_until
    audit = await enrollment.purge(host, repository)
    assert audit['purged'] is True and audit['stores_deleted'] == 1
    assert not enrollment.path.exists()
    assert foreign.read_bytes() == b'Unrelated owner store'
    with pytest.raises(FollowUpExecutionBoundaryError):
        await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Must not recreate closed storage')])
    assert not enrollment.path.exists()
    with pytest.raises(FollowUpExecutionBoundaryError):
        IsolatedCanonicalSQLite(tmp_path/'canonical', host.confirmation)


@pytest.mark.asyncio
async def test_sync_commit_guard_excludes_revocation_publication(tmp_path):
    import sqlite3
    import threading
    _, host, _, binding, _, _, calls, credentials, _, _ = root_setup(tmp_path)
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    writer_id = []
    original_lock = host._lock
    class ObservedLock:
        def __enter__(self):
            if writer_id and threading.get_ident() != writer_id[0]:
                attempted.set()
            return original_lock.__enter__()
        def __exit__(self, *args):
            return original_lock.__exit__(*args)
    host._lock = ObservedLock()
    async with host.hold_parent(binding) as lease:
        def writer():
            writer_id.append(threading.get_ident())
            with sqlite3.connect(tmp_path/'guarded-commit.sqlite3') as connection:
                connection.execute('CREATE TABLE receipt(value INTEGER)')
                connection.commit()
                with lease.guard():
                    connection.execute('INSERT INTO receipt VALUES(1)')
                    assert lease.is_current() is True
                    entered.set()
                    assert release.wait(2), 'Owned writer release deadline exceeded'
                    connection.commit()
        worker = asyncio.create_task(asyncio.to_thread(writer))
        publisher = None
        try:
            assert await asyncio.to_thread(entered.wait, 1)
            publisher = asyncio.create_task(host.revoke(timeout=2))
            assert await asyncio.to_thread(attempted.wait, 1)
            assert host._revoked is False, 'Generation publication crossed held final-check/commit guard'
            assert host.generation == 1
        finally:
            release.set()
            await asyncio.wait_for(worker, 2)
            if publisher is not None:
                await asyncio.wait_for(publisher, 2)
    with sqlite3.connect(tmp_path/'guarded-commit.sqlite3') as connection:
        assert connection.execute('SELECT value FROM receipt').fetchall() == [(1,)]
    assert host._revoked is True and host.generation == 2 and host._tokens == 0
    assert calls == credentials == []


@pytest.mark.asyncio
async def test_canonical_purge_retry_deletes_after_unlink_failure_without_restoring_ingress(tmp_path, monkeypatch):
    from pathlib import Path
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    _, host, _, binding, _, _, calls, credentials, _, clock = root_setup(tmp_path)
    enrollment = IsolatedCanonicalSQLite(tmp_path/'retry-canonical', host.confirmation, create=True)
    repository = open_owned_canonical_repository(enrollment)
    assert await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title='SYNTHETIC_RETRY_RETENTION_PAYLOAD', source_url='https://example.invalid/retry-owned')]) == 1
    foreign = tmp_path/'foreign-retained.sqlite3'
    foreign.write_bytes(b'Foreign owner store')
    clock[0] = host.confirmation.bounds.retention_until
    original_unlink = Path.unlink
    def failed_unlink(path, *args, **kwargs):
        if path == enrollment.path:
            raise OSError('Synthetic first owned unlink failure')
        return original_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, 'unlink', failed_unlink)
        with pytest.raises(OSError):
            await enrollment.purge(host, repository)
    assert enrollment.path.exists() and enrollment.closed is True and host._revoked is True
    with pytest.raises(FollowUpExecutionBoundaryError):
        async with host.hold_parent(binding):
            pass
    with pytest.raises(FollowUpExecutionBoundaryError):
        await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Must remain closed')])
    reopened = IsolatedCanonicalSQLite(enrollment.root, host.confirmation)
    assert reopened.closed is True
    with pytest.raises(FollowUpExecutionBoundaryError):
        open_owned_canonical_repository(reopened)
    audit = await reopened.purge(host, repository)
    assert audit['purged'] is True and audit['stores_deleted'] == 1
    assert not enrollment.path.exists()
    assert foreign.read_bytes() == b'Foreign owner store'
    assert host._revoked is True and enrollment.closed is True
    assert calls == credentials == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['marker-write', 'marker-fsync'])
async def test_canonical_purge_marker_failure_preserves_owned_receipt_and_retry(tmp_path, monkeypatch, failure):
    import json
    import os
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    _, host, _, binding, _, _, calls, credentials, _, clock = root_setup(tmp_path)
    enrollment = IsolatedCanonicalSQLite(tmp_path/'marker-failure-canonical', host.confirmation, create=True)
    repository = open_owned_canonical_repository(enrollment)
    assert await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title='SYNTHETIC_MARKER_FAILURE_PAYLOAD', source_url='https://example.invalid/marker-owned')]) == 1
    original_receipt = enrollment.marker.read_bytes()
    identity = enrollment._identity
    foreign = tmp_path/'foreign-marker-store'
    foreign.write_bytes(b'Foreign owner payload')
    clock[0] = host.confirmation.bounds.retention_until
    original_dump = json.dump
    def interrupted_dump(value, stream, *args, **kwargs):
        if value.get('deletion_pending') is True:
            stream.write('{"owner_scope":')
            raise OSError('Synthetic owned marker write interruption')
        return original_dump(value, stream, *args, **kwargs)
    def interrupted_fsync(fd):
        raise OSError('Synthetic owned marker fsync interruption')
    with monkeypatch.context() as patch:
        if failure == 'marker-write':
            patch.setattr(json, 'dump', interrupted_dump)
        else:
            patch.setattr(os, 'fsync', interrupted_fsync)
        with pytest.raises(OSError):
            await enrollment.purge(host, repository)
    assert host._revoked is True and enrollment.closed is True
    assert enrollment.path.exists() and enrollment._identity == identity
    assert enrollment.marker.read_bytes() == original_receipt, 'Immutable ownership receipt was overwritten before durable deletion disposition'
    with pytest.raises(FollowUpExecutionBoundaryError):
        IsolatedCanonicalSQLite(enrollment.root, host.confirmation)
    with pytest.raises(FollowUpExecutionBoundaryError):
        async with host.hold_parent(binding):
            pass
    with pytest.raises(FollowUpExecutionBoundaryError):
        await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
            raw_title='Must not restore ingress', source_url='https://example.invalid/no-reopen')])
    audit = await enrollment.purge(host, repository)
    assert audit['purged'] is True and not enrollment.path.exists()
    assert foreign.read_bytes() == b'Foreign owner payload'
    assert calls == credentials == []


@pytest.mark.asyncio
async def test_canonical_purge_completion_failure_reopens_deletion_only_without_recreation(tmp_path, monkeypatch):
    import json
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    _, host, _, _, _, _, calls, credentials, _, clock = root_setup(tmp_path)
    enrollment = IsolatedCanonicalSQLite(tmp_path/'completion-failure-canonical', host.confirmation, create=True)
    repository = open_owned_canonical_repository(enrollment)
    assert await repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title='SYNTHETIC_COMPLETION_FAILURE_PAYLOAD', source_url='https://example.invalid/completion-owned')]) == 1
    original_receipt = enrollment.marker.read_bytes()
    foreign = tmp_path/'foreign-completion-store'
    foreign.write_bytes(b'Foreign owner payload')
    clock[0] = host.confirmation.bounds.retention_until
    original_dump = json.dump
    def interrupted_completion(value, stream, *args, **kwargs):
        if value.get('purged') is True:
            raise OSError('Synthetic completion publication failure')
        return original_dump(value, stream, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(json, 'dump', interrupted_completion)
        with pytest.raises(OSError):
            await enrollment.purge(host, repository)
    assert not enrollment.path.exists() and enrollment.closed and host._revoked
    assert enrollment.marker.read_bytes() == original_receipt
    pending = json.loads(enrollment.disposition.read_text())
    assert pending['deletion_pending'] is True and pending['purged'] is False
    reopened = IsolatedCanonicalSQLite.reopen_for_deletion(enrollment.root, host.confirmation)
    with pytest.raises(FollowUpExecutionBoundaryError):
        open_owned_canonical_repository(reopened)
    audit = await reopened.purge(host)
    assert audit['purged'] is True and audit['stores_deleted'] == 1
    assert not enrollment.path.exists() and foreign.read_bytes() == b'Foreign owner payload'
    assert json.loads(enrollment.disposition.read_text()) == audit
    assert enrollment.marker.read_bytes() == original_receipt
    assert calls == credentials == []
