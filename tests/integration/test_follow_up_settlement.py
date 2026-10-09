"""T075 conservative closure: durable admission is never lost or inferred as usage."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from ignis.application.ports.research_work_port import FollowUpAdmissionCommand
from ignis.domain.mission_follow_up import FollowUpExecutionRequest
from tests.integration.follow_up_execution_setup import corrupt_disposable
from tests.integration.test_follow_up_execution import execution_ready


@pytest.mark.asyncio
async def test_late_authority_refusal_preserves_durable_link_and_run(tmp_path, monkeypatch):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    parent_before = await repository.get_mission(parent.id)
    revoked = False
    original_hold = verifier.hold_execution
    original_allocate = service._executor._workspace_store.allocate_run_journal

    @asynccontextmanager
    async def hold(authority, plan):
        async with original_hold(authority, plan) as lease:
            current = lease.is_current
            lease.is_current = lambda: current() and not revoked
            yield lease

    async def allocate(*args, **kwargs):
        nonlocal revoked
        journal = await original_allocate(*args, **kwargs)
        revoked = True
        return journal

    monkeypatch.setattr(verifier, "hold_execution", hold)
    monkeypatch.setattr(service._executor._workspace_store, "allocate_run_journal", allocate)
    try:
        result = await service.execute(str(parent.id), str(work.work_id), 1, "late-refusal")
        snapshot = await repository.load_mission_follow_ups(parent.id)
        assert revoked and len(snapshot.relationships) == len(snapshot.reservations) == 1
        link, reservation = snapshot.relationships[0], snapshot.reservations[0]
        journals = await repository.list_run_journals(link.child_mission_id)
        assert len(journals) == 1 and journals[0].status == "FAILED"
        assert await repository.get_mission_writer_claim(link.child_mission_id) is None
        assert reservation.state == "UNRESOLVED"
        assert reservation.reserved_quota == reservation.reserved_cost == 2
        assert reservation.encumbered == (2, 2) and reservation.measurement_receipt_id is None
        assert ingress.auth_initializations == ingress.connector_calls == 0
        assert await repository.get_mission(parent.id) == parent_before
        assert result.status == "REFUSED" and result.reason_code == "SESSION_AUTHORITY_REQUIRED"
        assert result.relationship == link
        assert result.run_id == journals[0].run_id
        retry = await service.execute(str(parent.id), str(work.work_id), 1, "late-alias")
        assert retry.relationship == link and retry.run_id == journals[0].run_id
        assert retry.status == "RECONCILIATION_REQUIRED" and retry.reason_code == "UNRESOLVED_EXECUTION"
        assert await repository.load_mission_follow_ups(parent.id) == snapshot
        assert ingress.auth_initializations == ingress.connector_calls == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_completed_child_without_final_journal_requires_reconciliation(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    parent_before = await repository.get_mission(parent.id)
    try:
        context = await repository._follow_up_execution_context(parent.id, work.work_id)
        receipt = await repository.admit_mission_follow_up(FollowUpAdmissionCommand(
            request=FollowUpExecutionRequest(mission_id=parent.id, follow_up_work_id=work.work_id,
                expected_research_epoch=1, idempotency_key="legacy-completed"),
            selected_parent_id=parent.id, expected_revision=context.research.revision, host_authorized=True))
        assert receipt.disposition == "APPLIED"
        link = receipt.relationship
        assert await repository.list_run_journals(link.child_mission_id) == []
        # Explicit disposable legacy state; exact table guards are restored before recovery.
        corrupt_disposable(SimpleNamespace(name="sqlite", repository=repository), [
            ("research_missions", "UPDATE research_missions SET status=? WHERE id=?",
             ("COMPLETED", str(link.child_mission_id)))])
        before = await repository.load_mission_follow_ups(parent.id)
        result = await service.execute(str(parent.id), str(work.work_id), 1, "legacy-alias")
        after = await repository.load_mission_follow_ups(parent.id)
        assert len(after.relationships) == len(after.reservations) == 1
        assert after.relationships == before.relationships == (link,)
        reservation = after.reservations[0]
        assert reservation.reserved_quota == reservation.reserved_cost == 2
        assert reservation.encumbered == (2, 2) and reservation.measurement_receipt_id is None
        assert await repository.list_run_journals(link.child_mission_id) == []
        assert await repository.get_mission_writer_claim(link.child_mission_id) is None
        assert ingress.auth_initializations == ingress.connector_calls == 0
        assert await repository.get_mission(parent.id) == parent_before
        assert result.relationship == link and result.run_id is None
        assert result.status == "RECONCILIATION_REQUIRED" and result.reason_code == "UNRESOLVED_EXECUTION"
        assert reservation.state == "UNRESOLVED"
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_storage_failure_after_durable_journal_preserves_traceability(tmp_path, monkeypatch):
    from ignis.domain.exceptions import RepositoryException
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    original = service._executor._workspace_store.allocate_run_journal
    allocated = []

    async def allocate(*args, **kwargs):
        journal = await original(*args, **kwargs)
        allocated.append(journal)
        raise RepositoryException("Synthetic post-journal storage failure")

    monkeypatch.setattr(service._executor._workspace_store, "allocate_run_journal", allocate)
    try:
        result = await service.execute(str(parent.id), str(work.work_id), 1, "storage")
        snapshot = await repository.load_mission_follow_ups(parent.id)
        assert len(allocated) == len(snapshot.relationships) == len(snapshot.reservations) == 1
        link = snapshot.relationships[0]
        assert result.status == "REFUSED" and result.reason_code == "STORAGE_FAILURE"
        assert result.relationship == link and result.run_id == allocated[0].run_id
        assert snapshot.reservations[0].state == "UNRESOLVED"
        assert snapshot.reservations[0].encumbered == (2, 2)
        assert snapshot.reservations[0].measurement_receipt_id is None
        for key in ("storage", "storage-alias"):
            retry = await service.execute(str(parent.id), str(work.work_id), 1, key)
            assert retry.status == "RECONCILIATION_REQUIRED" and retry.reason_code == "UNRESOLVED_EXECUTION"
            assert retry.relationship == link and retry.run_id == allocated[0].run_id
        assert len(await repository.list_run_journals(link.child_mission_id)) == 1
        assert ingress.auth_initializations == ingress.connector_calls == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["completed", "cancelled", "opaque"])
async def test_actual_file_reopen_preserves_unknown_spend_and_run_without_reprobe(tmp_path, mode):
    import asyncio
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_follow_up_execution import OfflineExecutionPlugin, setup
    from tests.integration.test_mission_follow_up import EmptyClusterer, InterruptedProbe

    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    if mode == "completed":
        ingress.release.set()
        assert (await service.execute(str(parent.id), str(work.work_id), 1, "reopen")).status == "COMPLETED"
    elif mode == "opaque":
        ingress.interrupt = True
        ingress.release.set()
        with pytest.raises(InterruptedProbe):
            await service.execute(str(parent.id), str(work.work_id), 1, "reopen")
    else:
        task = asyncio.create_task(service.execute(str(parent.id), str(work.work_id), 1, "reopen"))
        await asyncio.wait_for(ingress.entered.wait(), 5)
        task.cancel()
        ingress.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    link = snapshot.relationships[0]
    journals = await repository.list_run_journals(link.child_mission_id)
    assert len(journals) == 1
    assert snapshot.reservations[0].state == "UNRESOLVED"
    assert snapshot.reservations[0].encumbered == (2, 2)
    assert snapshot.reservations[0].measurement_receipt_id is None
    assert await repository.get_mission_writer_claim(link.child_mission_id) is None
    counts = ingress.auth_initializations, ingress.connector_calls
    path = repository._db_path
    await repository.close()
    reopened = setup.SqliteTrendRepository(path)
    await reopened._ensure_schema()
    registry = ConnectorPluginRegistry(reopened)
    registry.register(OfflineExecutionPlugin(ingress))
    executor = ExecuteMissionUseCase(reopened, registry, EmptyClusterer(), WorkspaceRepository(reopened))
    retry_service = ExecuteMissionFollowUpUseCase(reopened, executor, selected_parent_id=parent.id, host_authorized=True)
    try:
        for key in ("reopen", "reopen-alias"):
            result = await retry_service.execute(str(parent.id), str(work.work_id), 1, key)
            assert result.relationship == link and result.run_id == journals[0].run_id
            assert result.status == ("COMPLETED" if mode == "completed" else "RECONCILIATION_REQUIRED")
            if mode != "completed":
                assert result.reason_code == "UNRESOLVED_EXECUTION"
        assert await reopened.load_mission_follow_ups(parent.id) == snapshot
        assert await reopened.list_run_journals(link.child_mission_id) == journals
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
        assert (await reopened.get_mission(parent.id)).status == "COMPLETED"
    finally:
        await reopened.close()


async def _persist_before_ingress_process(directory):
    """Owned disposable child stops after writer/journal persistence and before auth."""
    import asyncio
    import json
    from pathlib import Path
    import ignis.config as config
    assert config._ENV_ISOLATED
    assert config._ENV_FILES == (str(Path(directory) / 'crash-test.env'),)
    assert not any(config.reveal_secret(getattr(config.settings, name)) for name in (
        'YOUTUBE_API_KEY', 'THREADS_APP_SECRET', 'INSTAGRAM_APP_SECRET',
        'IGNIS_ENCRYPTION_KEY', 'PLAYWRIGHT_PROXY_SERVER'))
    directory = Path(directory)
    (directory / 'child-phase.json').write_text(json.dumps({'phase': 'typed-setup-start'}))
    repository, parent, work, service, ingress, verifier = await execution_ready(directory)
    (directory / 'child-phase.json').write_text(json.dumps({'phase': 'typed-setup-complete'}))
    original = service._executor._execute_authorized

    async def execute(*args, **kwargs):
        async def stop(journal):
            snapshot = await repository.load_mission_follow_ups(parent.id)
            link = snapshot.relationships[0]
            claim = await repository.get_mission_writer_claim(link.child_mission_id)
            assert claim.run_id == journal.run_id
            assert ingress.auth_initializations == ingress.connector_calls == 0
            marker = dict(path=repository._db_path, parent=str(parent.id), work=str(work.work_id),
                          child=str(link.child_mission_id), reservation=str(link.reservation_id),
                          run=str(journal.run_id), auth=0, probe=0)
            (directory / 'durable-marker.json').write_text(json.dumps(marker))
            (directory / 'child-phase.json').write_text(json.dumps({'phase': 'durable-pre-ingress'}))
            await asyncio.Event().wait()
        kwargs['scope_guard'] = stop
        return await original(*args, **kwargs)

    service._executor._execute_authorized = execute
    await service.execute(str(parent.id), str(work.work_id), 1, 'process-death')


@pytest.mark.asyncio
async def test_owned_process_death_retains_unknown_writer_and_allocation(tmp_path):
    import asyncio
    import json
    import os
    import sys
    from pathlib import Path
    from uuid import UUID
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_follow_up_execution import OfflineExecutionPlugin, setup
    from tests.integration.test_mission_follow_up import EmptyClusterer, Ingress

    # Allowlist removes inherited credentials and proxies; child repeats isolated config checks.
    env = {key: os.environ[key] for key in ('PATH',)
           if key in os.environ}
    # Use a test-owned inert configuration, independent of the parent installation or env path.
    isolated_env = tmp_path / 'crash-test.env'
    isolated_env.write_text('DATABASE_URL=sqlite:///ignis.db\nYOUTUBE_API_KEY=\n'
                            'THREADS_APP_SECRET=\nINSTAGRAM_APP_SECRET=\n'
                            'IGNIS_ENCRYPTION_KEY=\nPLAYWRIGHT_PROXY_SERVER=\n')
    env['IGNIS_ENV_ISOLATED'] = '1'
    env['IGNIS_ENV_FILE'] = str(isolated_env)
    env['PYTHONPATH'] = os.pathsep.join((str(Path(__file__).resolve().parents[2]),
        str(Path(__file__).resolve().parents[2] / 'src'), str(Path(__file__).resolve().parent)))
    process = await asyncio.create_subprocess_exec(sys.executable, '-c',
        'import asyncio,sys,traceback,json; from pathlib import Path; '
        'Path(sys.argv[1], "child-phase.json").write_text(json.dumps({"phase":"module-import-start"})); '
        'from tests.integration.test_follow_up_settlement import _persist_before_ingress_process; '
        'Path(sys.argv[1], "child-phase.json").write_text(json.dumps({"phase":"module-import-complete"})); '
        '\ntry: asyncio.run(_persist_before_ingress_process(sys.argv[1]))'
        '\nexcept BaseException as error: '
        'Path(sys.argv[1], "child-error.json").write_text(json.dumps({'
        '"type":type(error).__name__,"frames":[[f.name,f.lineno] for f in traceback.extract_tb(error.__traceback__)]})); raise SystemExit(1)',
        str(tmp_path), env=env, cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    (tmp_path / 'process-owner.json').write_text(json.dumps({'pid': process.pid, 'reaped': False}))
    try:
        async def marker_ready():
            while not (tmp_path / 'durable-marker.json').exists():
                if process.returncode is not None:
                    _, error_output = await process.communicate()
                    lines = error_output.decode(errors='replace').splitlines()
                    assert False, ('Child import failure type: ' +
                        (lines[-1] if lines and lines[-1].startswith('ModuleNotFoundError:') else
                         lines[-1].split(':')[0] if lines else 'unknown'))
                assert process.returncode is None, ('Owned child exited before durable marker: ' +
                    (tmp_path / 'child-error.json').read_text() if (tmp_path / 'child-error.json').exists()
                    else 'Owned child exited before durable marker')
                await asyncio.sleep(.02)
        await asyncio.wait_for(marker_ready(), 10)
        marker = json.loads((tmp_path / 'durable-marker.json').read_text())
        import sqlite3
        with sqlite3.connect(marker['path']) as physical:
            link_row = physical.execute(
                'SELECT child_mission_id,reservation_id FROM mission_follow_ups '
                'WHERE parent_mission_id=? AND work_id=?', (marker['parent'], marker['work'])).fetchone()
            assert link_row == (marker['child'], marker['reservation'])
            assert physical.execute('SELECT mission_id,status,completed_at FROM mission_run_journals WHERE id=?',
                (marker['run'],)).fetchone() == (marker['child'], 'STARTED', None)
            assert physical.execute('SELECT run_id FROM mission_writer_claims WHERE mission_id=?',
                (marker['child'],)).fetchone() == (marker['run'],)
            assert physical.execute('SELECT reserved_quota,reserved_cost,measurement_receipt_id '
                'FROM mission_follow_up_reservations WHERE reservation_id=?',
                (marker['reservation'],)).fetchone() == (2, 2, None)
        assert marker['auth'] == marker['probe'] == 0
        process.kill()
        assert await asyncio.wait_for(process.wait(), 5) < 0
    finally:
        if process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)
        (tmp_path / 'process-owner.json').write_text(json.dumps(
            {'pid': process.pid, 'reaped': process.returncode is not None, 'exit': process.returncode}))
    repository = setup.SqliteTrendRepository(marker['path'])
    await repository._ensure_schema()
    ingress = Ingress()
    registry = ConnectorPluginRegistry(repository)
    registry.register(OfflineExecutionPlugin(ingress))
    executor = ExecuteMissionUseCase(repository, registry, EmptyClusterer(), WorkspaceRepository(repository))
    service = ExecuteMissionFollowUpUseCase(repository, executor, selected_parent_id=UUID(marker['parent']),
                                           host_authorized=True)
    try:
        snapshot = await repository.load_mission_follow_ups(UUID(marker['parent']))
        assert len(snapshot.relationships) == len(snapshot.reservations) == 1
        link = snapshot.relationships[0]
        assert str(link.child_mission_id) == marker['child']
        assert str(link.reservation_id) == marker['reservation']
        journals = await repository.list_run_journals(link.child_mission_id)
        claim = await repository.get_mission_writer_claim(link.child_mission_id)
        assert len(journals) == 1 and str(journals[0].run_id) == marker['run']
        assert journals[0].status == 'STARTED' and journals[0].completed_at is None
        assert claim.run_id == journals[0].run_id
        parent = await repository.get_mission(UUID(marker['parent']))
        conn = repository._get_connection()
        resources = tuple(map(tuple, conn.execute(
            'SELECT resource,allocated FROM mission_follow_up_reservation_resources '
            'WHERE reservation_id=? ORDER BY resource', (marker['reservation'],)).fetchall()))
        assert resources and dict(resources)['queries'] == 2
        for key in ('process-death', 'process-death-alias'):
            result = await service.execute(marker['parent'], marker['work'], 1, key)
            assert result.status == 'ADMITTED' and result.reason_code == 'EXECUTION_STATUS_UNKNOWN'
            assert result.relationship == link and result.run_id == journals[0].run_id
        after = await repository.load_mission_follow_ups(UUID(marker['parent']))
        assert after.relationships == snapshot.relationships
        reservation = after.reservations[0]
        assert reservation.state == 'UNRESOLVED' and reservation.encumbered == (2, 2)
        assert reservation.measurement_receipt_id is None
        assert tuple(map(tuple, conn.execute(
            'SELECT resource,allocated FROM mission_follow_up_reservation_resources '
            'WHERE reservation_id=? ORDER BY resource', (marker['reservation'],)).fetchall())) == resources
        assert await repository.get_mission_writer_claim(link.child_mission_id) == claim
        assert await repository.list_run_journals(link.child_mission_id) == journals
        assert await repository.get_mission(UUID(marker['parent'])) == parent
        assert ingress.auth_initializations == ingress.connector_calls == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('history', ['nonfinal', 'chronology', 'workspace', 'multiple', 'held-writer'])
async def test_terminal_child_cannot_override_incoherent_canonical_history(tmp_path, history):
    from uuid import uuid4
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    try:
        first = await service.execute(str(parent.id), str(work.work_id), 1, 'history')
        assert first.status == 'COMPLETED'
        link = first.relationship
        journals = await repository.list_run_journals(link.child_mission_id)
        assert len(journals) == 1
        run = journals[0]
        if history == 'nonfinal':
            statements = [('mission_run_journals',
                'UPDATE mission_run_journals SET status=?,completed_at=NULL WHERE id=?', ('STARTED', str(run.run_id)))]
        elif history == 'chronology':
            statements = [('mission_run_journals',
                'UPDATE mission_run_journals SET completed_at=? WHERE id=?',
                ('2000-01-01T00:00:00+00:00', str(run.run_id)))]
        elif history == 'workspace':
            foreign = str(uuid4())
            statements = [('research_workspaces',
                'INSERT INTO research_workspaces SELECT ?,slug||?,name,root_path,format_version,status,created_at '
                'FROM research_workspaces WHERE id=?', (foreign, '-foreign', str(run.workspace_id))),
                ('mission_run_journals', 'UPDATE mission_run_journals SET workspace_id=? WHERE id=?',
                 (foreign, str(run.run_id)))]
        elif history == 'multiple':
            statements = [('mission_run_journals',
                'INSERT INTO mission_run_journals SELECT ?,workspace_id,mission_id,journal_path||?,sequence+1,'
                'status,started_at,completed_at FROM mission_run_journals WHERE id=?',
                (str(uuid4()), '-foreign', str(run.run_id)))]
        else:
            statements = [('mission_writer_claims',
                'INSERT INTO mission_writer_claims (mission_id,run_id,claimed_at) VALUES (?,?,?)',
                (str(link.child_mission_id), str(run.run_id), run.started_at.isoformat()))]
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), statements)
        counts = ingress.auth_initializations, ingress.connector_calls
        before = await repository.load_mission_follow_ups(parent.id)
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'history-alias')
        assert result.relationship == link
        if history == 'held-writer':
            assert result.status == 'ADMITTED' and result.reason_code == 'EXECUTION_STATUS_UNKNOWN'
            assert result.run_id == run.run_id
            assert (await repository.get_mission_writer_claim(link.child_mission_id)).run_id == run.run_id
        else:
            assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
        after = await repository.load_mission_follow_ups(parent.id)
        assert after.relationships == before.relationships
        assert after.reservations[0].state == 'UNRESOLVED'
        assert after.reservations[0].encumbered == (2, 2)
        assert after.reservations[0].measurement_receipt_id is None
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
        assert len(await repository.list_run_journals(link.child_mission_id)) == (2 if history == 'multiple' else 1)
        assert (await repository.get_mission(parent.id)).status == 'COMPLETED'
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_concurrent_unknown_recovery_changes_reservation_version_once(tmp_path):
    import asyncio
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    try:
        context = await repository._follow_up_execution_context(parent.id, work.work_id)
        receipt = await repository.admit_mission_follow_up(FollowUpAdmissionCommand(
            request=FollowUpExecutionRequest(mission_id=parent.id, follow_up_work_id=work.work_id,
                expected_research_epoch=1, idempotency_key='cas'), selected_parent_id=parent.id,
            expected_revision=context.research.revision, host_authorized=True))
        assert receipt.disposition == 'APPLIED'
        link = receipt.relationship
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('research_missions', 'UPDATE research_missions SET status=? WHERE id=?',
             ('COMPLETED', str(link.child_mission_id)))])
        conn = repository._get_connection()
        before = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                   (str(link.reservation_id),)).fetchone())
        columns = [row[1] for row in conn.execute('PRAGMA table_info(mission_follow_up_reservations)')]
        resources = tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall()))
        results = await asyncio.gather(*(service.execute(str(parent.id), str(work.work_id), 1, key)
                                        for key in ('cas', 'cas-alias-one', 'cas-alias-two')))
        assert all(r.status == 'RECONCILIATION_REQUIRED' and r.reason_code == 'UNRESOLVED_EXECUTION'
                   and r.relationship == link and r.run_id is None for r in results)
        after = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                  (str(link.reservation_id),)).fetchone())
        old, new = dict(zip(columns, before)), dict(zip(columns, after))
        assert new['state'] == 'UNRESOLVED' and new['version'] == old['version'] + 1
        assert {k: v for k, v in new.items() if k not in ('state', 'version')} == {
            k: v for k, v in old.items() if k not in ('state', 'version')}
        assert tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall())) == resources
        assert (await repository.load_mission_follow_ups(parent.id)).relationships == (link,)
        assert await repository.list_run_journals(link.child_mission_id) == []
        assert ingress.auth_initializations == ingress.connector_calls == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_arbitrary_settled_receipt_is_not_execution_or_measurement_authority(tmp_path):
    from uuid import uuid4
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    try:
        first = await service.execute(str(parent.id), str(work.work_id), 1, 'unsupported-settled')
        assert first.status == 'COMPLETED'
        link = first.relationship
        receipt_id = str(uuid4())
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('mission_follow_up_reservations', 'UPDATE mission_follow_up_reservations '
             'SET state=?,measured_quota=?,measured_cost=?,measurement_receipt_id=? WHERE reservation_id=?',
             ('SETTLED', 0, 0, receipt_id, str(link.reservation_id)))])
        conn = repository._get_connection()
        before = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                   (str(link.reservation_id),)).fetchone())
        resources = tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall()))
        counts = ingress.auth_initializations, ingress.connector_calls
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'unsupported-alias')
        assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
        assert result.relationship == link and result.run_id == first.run_id
        assert tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                  (str(link.reservation_id),)).fetchone()) == before
        assert tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall())) == resources
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
        assert len(await repository.list_run_journals(link.child_mission_id)) == 1
        # Existing T073 scalar projection of the corrupt row is not proof of measured usage.
        # This control asserts no executor mutation; sibling budget semantics await PO scope.
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_malformed_durable_journal_fails_closed_without_rewriting_history(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    try:
        first = await service.execute(str(parent.id), str(work.work_id), 1, 'malformed')
        assert first.status == 'COMPLETED'
        link = first.relationship
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('mission_run_journals', 'UPDATE mission_run_journals SET completed_at=? WHERE id=?',
             ('not-a-timestamp', str(first.run_id)))])
        conn = repository._get_connection()
        before = tuple(conn.execute('SELECT * FROM mission_run_journals WHERE id=?',
                                    (str(first.run_id),)).fetchone())
        reservation = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                         (str(link.reservation_id),)).fetchone())
        counts = ingress.auth_initializations, ingress.connector_calls
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'malformed-alias')
        assert result.status == 'REFUSED' and result.reason_code == 'STORAGE_FAILURE'
        assert tuple(conn.execute('SELECT * FROM mission_run_journals WHERE id=?',
                                  (str(first.run_id),)).fetchone()) == before
        assert tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                  (str(link.reservation_id),)).fetchone()) == reservation
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_failed_actual_journal_finalization_cannot_claim_first_response_closure(tmp_path, monkeypatch):
    from ignis.domain.exceptions import RepositoryException
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    store = service._executor._workspace_store
    original = store.record_run_journal
    rejected = []

    async def record(journal):
        if journal.status == 'COMPLETED':
            rejected.append(journal.run_id)
            raise RepositoryException('Synthetic final journal persistence failure')
        return await original(journal)

    monkeypatch.setattr(store, 'record_run_journal', record)
    ingress.release.set()
    try:
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'finalization')
        snapshot = await repository.load_mission_follow_ups(parent.id)
        assert len(snapshot.relationships) == len(snapshot.reservations) == 1
        link = snapshot.relationships[0]
        journals = await repository.list_run_journals(link.child_mission_id)
        assert len(journals) == len(rejected) == 1 and journals[0].run_id == rejected[0]
        assert journals[0].status == 'STARTED' and journals[0].completed_at is None
        assert await repository.get_mission_writer_claim(link.child_mission_id) is None
        assert snapshot.reservations[0].state == 'UNRESOLVED'
        assert snapshot.reservations[0].encumbered == (2, 2)
        assert result.relationship == link and result.run_id == journals[0].run_id
        assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
        counts = ingress.auth_initializations, ingress.connector_calls
        assert counts == (1, 1)
        retry = await service.execute(str(parent.id), str(work.work_id), 1, 'finalization-alias')
        assert retry.relationship == link and retry.run_id == journals[0].run_id
        assert retry.status == 'RECONCILIATION_REQUIRED'
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_unverified_settled_usage_cannot_fund_real_distinct_sibling(tmp_path, monkeypatch):
    from uuid import uuid4
    from tests.integration.test_follow_up_execution import setup
    from tests.integration.follow_up_execution_setup import sibling
    original_ready = setup.ready

    async def tight_ready(*args, **kwargs):
        return await original_ready(*args, **kwargs, budget=2, resource_budget=20)

    # Valid typed authority gets tight scalar budgets and independently ample resource ceilings.
    monkeypatch.setattr(setup, 'ready', tight_ready)
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    try:
        authority = (await repository._follow_up_execution_context(parent.id, work.work_id)).authority
        first = await service.execute(str(parent.id), str(work.work_id), 1, 'budget-original')
        assert first.status == 'COMPLETED'
        link = first.relationship
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('mission_follow_up_reservations', 'UPDATE mission_follow_up_reservations '
             'SET state=?,measured_quota=?,measured_cost=?,measurement_receipt_id=? WHERE reservation_id=?',
             ('SETTLED', 0, 0, str(uuid4()), str(link.reservation_id)))])
        following = await sibling(repository, parent, authority)
        assert following.work_id != work.work_id and following.gap_id != work.gap_id
        conn = repository._get_connection()
        before = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                    (str(link.reservation_id),)).fetchone())
        resources = tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall()))
        counts = ingress.auth_initializations, ingress.connector_calls
        result = await service.execute(str(parent.id), str(following.work_id), 1, 'budget-sibling')
        assert result.status == 'REFUSED' and result.reason_code == 'RECONCILIATION_REQUIRED'
        assert result.relationship is None and result.run_id is None
        snapshot = await repository.load_mission_follow_ups(parent.id)
        assert snapshot.relationships == (link,) and len(snapshot.reservations) == 1
        assert tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                  (str(link.reservation_id),)).fetchone()) == before
        assert tuple(map(tuple, conn.execute(
            'SELECT * FROM mission_follow_up_reservation_resources WHERE reservation_id=? ORDER BY resource',
            (str(link.reservation_id),)).fetchall())) == resources
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_fresh_actual_success_rechecks_canonical_journal_before_reporting_closure(tmp_path, monkeypatch):
    from uuid import UUID
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    original = service._executor._execute_authorized
    returned = []

    async def execute(*args, **kwargs):
        result = await original(*args, **kwargs)
        assert result['terminal_state'] == 'COMPLETED'
        run_id = UUID(result['run']['run_id'])
        returned.append(run_id)
        # Actual result stays unchanged; canonical durable closure drifts before use-case readback.
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('mission_run_journals', 'UPDATE mission_run_journals SET status=?,completed_at=NULL WHERE id=?',
             ('STARTED', str(run_id)))])
        return result

    monkeypatch.setattr(service._executor, '_execute_authorized', execute)
    try:
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'fresh-drift')
        snapshot = await repository.load_mission_follow_ups(parent.id)
        assert len(returned) == len(snapshot.relationships) == len(snapshot.reservations) == 1
        link = snapshot.relationships[0]
        journals = await repository.list_run_journals(link.child_mission_id)
        assert len(journals) == 1 and journals[0].run_id == returned[0]
        assert journals[0].status == 'STARTED' and journals[0].completed_at is None
        assert await repository.get_mission_writer_claim(link.child_mission_id) is None
        assert snapshot.reservations[0].state == 'UNRESOLVED'
        assert snapshot.reservations[0].encumbered == (2, 2)
        assert result.relationship == link and result.run_id == returned[0]
        assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
        assert ingress.auth_initializations == ingress.connector_calls == 1
    finally:
        await repository.close()


import pytest_asyncio


@pytest_asyncio.fixture(params=['postgres'])
async def pg_settlement_case(request, tmp_path):
    """Native accepted disposable PG setup; no replacement SQLite runtime."""
    from tests.integration.test_mission_follow_up import relay_case
    async for case, _, _ in relay_case.__wrapped__(request, tmp_path):
        yield case


async def _native_pg_ready(case, tmp_path, *, tight=False):
    from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
    from tests.integration.follow_up_execution_setup import ready
    from tests.integration.test_follow_up_execution import OfflineExecutionVerifier
    from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
    from tests.integration.test_mission_follow_up import Ingress, _executor

    class NativeVerifier(OfflineExecutionVerifier):
        hold_current = AsyncVerifier.hold_current

    ingress = Ingress()
    executor = _executor(case.repository, ingress)
    repository, parent, work, authority, _ = await ready(case.repository, tmp_path, executor,
        ExecuteMissionFollowUpUseCase, budget=2 if tight else 4, cost_budget=2 if tight else 4,
        resource_budget=20)
    verifier = NativeVerifier()
    repository.configure_follow_up_verifier(verifier)

    async def initialize(sources):
        assert sources == frozenset({'youtube'})
        ingress.initialize_session()

    service = ExecuteMissionFollowUpUseCase(repository, executor, selected_parent_id=parent.id,
        host_authorized=True, session_initializer=initialize)
    return repository, parent, work, authority, service, ingress, verifier


@pytest.mark.asyncio
@pytest.mark.parametrize('boundary', ['proof', 'storage', 'finalization', 'fresh-drift'])
async def test_postgres_admitted_boundary_preserves_actual_trace_and_allocation(pg_settlement_case, tmp_path,
                                                                             monkeypatch, boundary):
    from ignis.domain.exceptions import RepositoryException
    from uuid import UUID
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(pg_settlement_case, tmp_path)
    store = service._executor._workspace_store
    revoked = False
    fired = []
    if boundary in ('proof', 'storage'):
        original = store.allocate_run_journal
        if boundary == 'proof':
            original_hold = verifier.hold_execution

            @asynccontextmanager
            async def hold(grant, plan):
                async with original_hold(grant, plan) as lease:
                    current = lease.is_current
                    lease.is_current = lambda: current() and not revoked
                    yield lease
            monkeypatch.setattr(verifier, 'hold_execution', hold)

        async def allocate(*args, **kwargs):
            nonlocal revoked
            journal = await original(*args, **kwargs)
            fired.append(journal.run_id)
            revoked = True
            if boundary == 'storage':
                raise RepositoryException('Synthetic native postjournal storage failure')
            return journal
        monkeypatch.setattr(store, 'allocate_run_journal', allocate)
    elif boundary == 'finalization':
        original = store.record_run_journal

        async def record(journal):
            if journal.status == 'COMPLETED':
                fired.append(journal.run_id)
                raise RepositoryException('Synthetic native finalization persistence failure')
            return await original(journal)
        monkeypatch.setattr(store, 'record_run_journal', record)
    else:
        original = service._executor._execute_authorized

        async def execute(*args, **kwargs):
            result = await original(*args, **kwargs)
            assert result['terminal_state'] == 'COMPLETED'
            run_id = UUID(result['run']['run_id'])
            fired.append(run_id)
            corrupt_disposable(pg_settlement_case, [('mission_run_journals',
                'UPDATE mission_run_journals SET status=?,completed_at=NULL WHERE id=?', ('STARTED', run_id))])
            return result
        monkeypatch.setattr(service._executor, '_execute_authorized', execute)
    ingress.release.set()
    result = await service.execute(str(parent.id), str(work.work_id), 1, 'native-boundary')
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert len(fired) == len(snapshot.relationships) == len(snapshot.reservations) == 1
    link = snapshot.relationships[0]
    journals = await repository.list_run_journals(link.child_mission_id)
    assert len(journals) == 1 and journals[0].run_id == fired[0]
    assert result.relationship == link and result.run_id == fired[0]
    if boundary in ('proof', 'storage'):
        assert result.status == 'REFUSED'
        assert result.reason_code == ('SESSION_AUTHORITY_REQUIRED' if boundary == 'proof' else 'STORAGE_FAILURE')
        assert ingress.auth_initializations == ingress.connector_calls == 0
    else:
        assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
        assert ingress.auth_initializations == ingress.connector_calls == 1
    assert snapshot.reservations[0].state == 'UNRESOLVED'
    assert snapshot.reservations[0].encumbered == (2, 2)
    assert snapshot.reservations[0].measurement_receipt_id is None
    counts = ingress.auth_initializations, ingress.connector_calls
    for key in ('native-boundary', 'native-boundary-alias'):
        retry = await service.execute(str(parent.id), str(work.work_id), 1, key)
        assert retry.relationship == link and retry.run_id == fired[0]
        assert retry.status == 'RECONCILIATION_REQUIRED'
    assert (ingress.auth_initializations, ingress.connector_calls) == counts
    assert len(await repository.list_run_journals(link.child_mission_id)) == 1
    assert (await repository.get_mission(parent.id)).status == 'COMPLETED'


@pytest.mark.asyncio
@pytest.mark.parametrize('history', ['nonfinal', 'chronology', 'workspace', 'multiple', 'held-writer'])
async def test_postgres_terminal_history_never_infers_closure(pg_settlement_case, tmp_path, history):
    from uuid import uuid4
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(pg_settlement_case, tmp_path)
    ingress.release.set()
    first = await service.execute(str(parent.id), str(work.work_id), 1, 'native-history')
    assert first.status == 'COMPLETED'
    link = first.relationship
    run = (await repository.list_run_journals(link.child_mission_id))[0]
    if history == 'nonfinal':
        statements = [('mission_run_journals', 'UPDATE mission_run_journals SET status=?,completed_at=NULL WHERE id=?',
                       ('STARTED', run.run_id))]
    elif history == 'chronology':
        statements = [('mission_run_journals', 'UPDATE mission_run_journals SET completed_at=? WHERE id=?',
                       ('2000-01-01T00:00:00+00:00', run.run_id))]
    elif history == 'workspace':
        foreign = uuid4()
        statements = [('research_workspaces',
            'INSERT INTO research_workspaces SELECT ?,slug||?,name,root_path,format_version,status,created_at '
            'FROM research_workspaces WHERE id=?', (foreign, '-foreign', run.workspace_id)),
            ('mission_run_journals', 'UPDATE mission_run_journals SET workspace_id=? WHERE id=?', (foreign, run.run_id))]
    elif history == 'multiple':
        statements = [('mission_run_journals',
            'INSERT INTO mission_run_journals SELECT ?,workspace_id,mission_id,journal_path||?,sequence+1,'
            'status,started_at,completed_at FROM mission_run_journals WHERE id=?',
            (uuid4(), '-foreign', run.run_id))]
    else:
        statements = [('mission_writer_claims', 'INSERT INTO mission_writer_claims (mission_id,run_id,claimed_at) '
                       'VALUES (?,?,?)', (link.child_mission_id, run.run_id, run.started_at))]
    corrupt_disposable(pg_settlement_case, statements)
    before = await repository.load_mission_follow_ups(parent.id)
    counts = ingress.auth_initializations, ingress.connector_calls
    for key in ('native-history', 'native-history-alias'):
        result = await service.execute(str(parent.id), str(work.work_id), 1, key)
        assert result.relationship == link
        if history == 'held-writer':
            assert result.status == 'ADMITTED' and result.reason_code == 'EXECUTION_STATUS_UNKNOWN'
            assert result.run_id == run.run_id
        else:
            assert result.status == 'RECONCILIATION_REQUIRED' and result.reason_code == 'UNRESOLVED_EXECUTION'
    after = await repository.load_mission_follow_ups(parent.id)
    assert after.relationships == before.relationships
    assert after.reservations[0].state == 'UNRESOLVED' and after.reservations[0].encumbered == (2, 2)
    assert after.reservations[0].measurement_receipt_id is None
    assert (ingress.auth_initializations, ingress.connector_calls) == counts
    assert len(await repository.list_run_journals(link.child_mission_id)) == (2 if history == 'multiple' else 1)
    if history == 'held-writer':
        assert (await repository.get_mission_writer_claim(link.child_mission_id)).run_id == run.run_id


def _pg_reservation_rows(case, reservation_id):
    import psycopg
    with psycopg.connect(case.dsn) as conn:
        row = conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=%s',
                           (reservation_id,)).fetchone()
        columns = [column.name for column in conn.execute(
            'SELECT * FROM mission_follow_up_reservations LIMIT 0').description]
        resources = conn.execute('SELECT * FROM mission_follow_up_reservation_resources '
                                 'WHERE reservation_id=%s ORDER BY resource', (reservation_id,)).fetchall()
        return dict(zip(columns, row)), resources


@pytest.mark.asyncio
async def test_postgres_unknown_recovery_cas_preserves_all_other_physical_rows(pg_settlement_case, tmp_path):
    import asyncio
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(pg_settlement_case, tmp_path)
    context = await repository._follow_up_execution_context(parent.id, work.work_id)
    receipt = await repository.admit_mission_follow_up(FollowUpAdmissionCommand(
        request=FollowUpExecutionRequest(mission_id=parent.id, follow_up_work_id=work.work_id,
            expected_research_epoch=1, idempotency_key='native-cas'), selected_parent_id=parent.id,
        expected_revision=context.research.revision, host_authorized=True))
    assert receipt.disposition == 'APPLIED'
    link = receipt.relationship
    corrupt_disposable(pg_settlement_case, [('research_missions', 'UPDATE research_missions SET status=? WHERE id=?',
                                          ('COMPLETED', link.child_mission_id))])
    before, resources = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
    results = await asyncio.gather(*(service.execute(str(parent.id), str(work.work_id), 1, key)
        for key in ('native-cas', 'native-cas-alias-one', 'native-cas-alias-two')))
    assert all(r.status == 'RECONCILIATION_REQUIRED' and r.reason_code == 'UNRESOLVED_EXECUTION'
               and r.relationship == link and r.run_id is None for r in results)
    after, current_resources = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
    assert after['state'] == 'UNRESOLVED' and after['version'] == before['version'] + 1
    assert {k: v for k, v in after.items() if k not in ('state', 'version')} == {
        k: v for k, v in before.items() if k not in ('state', 'version')}
    assert current_resources == resources
    assert (await repository.load_mission_follow_ups(parent.id)).relationships == (link,)
    assert await repository.list_run_journals(link.child_mission_id) == []
    assert ingress.auth_initializations == ingress.connector_calls == 0


@pytest.mark.asyncio
async def test_postgres_unverified_usage_cannot_fund_distinct_sibling(pg_settlement_case, tmp_path):
    from uuid import uuid4
    from tests.integration.follow_up_execution_setup import sibling
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(
        pg_settlement_case, tmp_path, tight=True)
    ingress.release.set()
    first = await service.execute(str(parent.id), str(work.work_id), 1, 'native-budget')
    assert first.status == 'COMPLETED'
    link = first.relationship
    corrupt_disposable(pg_settlement_case, [('mission_follow_up_reservations',
        'UPDATE mission_follow_up_reservations SET state=?,measured_quota=?,measured_cost=?,'
        'measurement_receipt_id=? WHERE reservation_id=?', ('SETTLED', 0, 0, uuid4(), link.reservation_id))])
    following = await sibling(repository, parent, authority)
    assert following.work_id != work.work_id and following.gap_id != work.gap_id
    before = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
    counts = ingress.auth_initializations, ingress.connector_calls
    result = await service.execute(str(parent.id), str(following.work_id), 1, 'native-budget-sibling')
    assert result.status == 'REFUSED' and result.reason_code == 'RECONCILIATION_REQUIRED'
    assert result.relationship is None and result.run_id is None
    snapshot = await repository.load_mission_follow_ups(parent.id)
    assert snapshot.relationships == (link,) and len(snapshot.reservations) == 1
    assert _pg_reservation_rows(pg_settlement_case, link.reservation_id) == before
    assert (ingress.auth_initializations, ingress.connector_calls) == counts


@pytest.mark.asyncio
async def test_postgres_held_context_repeats_actual_writer_snapshot(pg_settlement_case, tmp_path, monkeypatch):
    from uuid import uuid4
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(pg_settlement_case, tmp_path)
    context = await repository._follow_up_execution_context(parent.id, work.work_id)
    receipt = await repository.admit_mission_follow_up(FollowUpAdmissionCommand(
        request=FollowUpExecutionRequest(mission_id=parent.id, follow_up_work_id=work.work_id,
            expected_research_epoch=1, idempotency_key='writer-snapshot'), selected_parent_id=parent.id,
        expected_revision=context.research.revision, host_authorized=True))
    assert receipt.disposition == 'APPLIED'
    link = receipt.relationship
    before, resources = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
    actor = PostgresTimescaleRepository(pg_settlement_case.dsn, min_pool_size=1, max_pool_size=1)
    await actor._get_pool()
    own_run = uuid4()
    original = repository._commit_snapshot
    observations = []
    owned = False

    async def snapshot(conn, mission_id):
        nonlocal owned
        actual = await original(conn, mission_id)
        if mission_id == link.child_mission_id and not observations:
            query = 'SELECT mission_id,run_id,claimed_at FROM mission_writer_claims WHERE mission_id=%s'
            first = await (await conn.execute(query, (link.child_mission_id,))).fetchone()
            assert first is None
            owned = await actor.claim_mission_writer(link.child_mission_id, own_run)
            assert owned
            physical = await actor.get_mission_writer_claim(link.child_mission_id)
            assert physical.run_id == own_run
            second = await (await conn.execute(query, (link.child_mission_id,))).fetchone()
            observations.append((first, second))
        return actual

    monkeypatch.setattr(repository, '_commit_snapshot', snapshot)
    try:
        import asyncio
        current = await asyncio.wait_for(repository._follow_up_execution_context(
            parent.id, work.work_id, unresolved=True), 10)
        assert len(observations) == 1
        assert observations[0] == (None, None)
        assert current.execution_history.writer is None
        assert (await actor.get_mission_writer_claim(link.child_mission_id)).run_id == own_run
        after, current_resources = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
        assert after['state'] == 'UNRESOLVED' and after['version'] == before['version'] + 1
        assert {k: v for k, v in after.items() if k not in ('state', 'version')} == {
            k: v for k, v in before.items() if k not in ('state', 'version')}
        assert current_resources == resources
        assert ingress.auth_initializations == ingress.connector_calls == 0
    finally:
        if owned:
            await actor.release_mission_writer(link.child_mission_id, own_run)
            assert await actor.get_mission_writer_claim(link.child_mission_id) is None
        await actor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('naive', ['mixed', 'both'])
async def test_naive_physical_journal_timestamps_fail_closed(tmp_path, naive):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    ingress.release.set()
    try:
        first = await service.execute(str(parent.id), str(work.work_id), 1, 'naive')
        assert first.status == 'COMPLETED'
        link = first.relationship
        journal = (await repository.list_run_journals(link.child_mission_id))[0]
        if naive == 'mixed':
            statement = ('mission_run_journals', 'UPDATE mission_run_journals SET completed_at=? WHERE id=?',
                (journal.completed_at.replace(tzinfo=None).isoformat(), str(first.run_id)))
        else:
            statement = ('mission_run_journals', 'UPDATE mission_run_journals SET started_at=?,completed_at=? WHERE id=?',
                (journal.started_at.replace(tzinfo=None).isoformat(),
                 journal.completed_at.replace(tzinfo=None).isoformat(), str(first.run_id)))
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [statement])
        conn = repository._get_connection()
        before = tuple(conn.execute('SELECT * FROM mission_run_journals WHERE id=?',
                                    (str(first.run_id),)).fetchone())
        reservation = tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                         (str(link.reservation_id),)).fetchone())
        counts = ingress.auth_initializations, ingress.connector_calls
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'naive-alias')
        assert result.status == 'REFUSED' and result.reason_code == 'STORAGE_FAILURE'
        assert tuple(conn.execute('SELECT * FROM mission_run_journals WHERE id=?',
                                  (str(first.run_id),)).fetchone()) == before
        assert tuple(conn.execute('SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?',
                                  (str(link.reservation_id),)).fetchone()) == reservation
        assert (ingress.auth_initializations, ingress.connector_calls) == counts
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('naive', ['mixed', 'both'])
async def test_postgres_naive_sql_inputs_normalize_to_aware_canonical_timestamps(pg_settlement_case, tmp_path, naive):
    """TIMESTAMPTZ normalization is parity evidence, not a stored naive-row control."""
    repository, parent, work, authority, service, ingress, verifier = await _native_pg_ready(pg_settlement_case, tmp_path)
    ingress.release.set()
    first = await service.execute(str(parent.id), str(work.work_id), 1, 'native-naive')
    assert first.status == 'COMPLETED'
    link = first.relationship
    journal = (await repository.list_run_journals(link.child_mission_id))[0]
    if naive == 'mixed':
        statement = ('mission_run_journals', 'UPDATE mission_run_journals SET completed_at=? WHERE id=?',
            (journal.completed_at.replace(tzinfo=None).isoformat(), first.run_id))
    else:
        statement = ('mission_run_journals', 'UPDATE mission_run_journals SET started_at=?,completed_at=? WHERE id=?',
            (journal.started_at.replace(tzinfo=None).isoformat(),
             journal.completed_at.replace(tzinfo=None).isoformat(), first.run_id))
    corrupt_disposable(pg_settlement_case, [statement])
    actual = (await repository.list_run_journals(link.child_mission_id))[0]
    assert actual.started_at.utcoffset() is not None and actual.completed_at.utcoffset() is not None
    before = _pg_reservation_rows(pg_settlement_case, link.reservation_id)
    counts = ingress.auth_initializations, ingress.connector_calls
    result = await service.execute(str(parent.id), str(work.work_id), 1, 'native-naive-alias')
    assert result.status == 'COMPLETED' and result.relationship == link and result.run_id == first.run_id
    assert _pg_reservation_rows(pg_settlement_case, link.reservation_id) == before
    assert (await repository.list_run_journals(link.child_mission_id))[0] == actual
    assert (ingress.auth_initializations, ingress.connector_calls) == counts
