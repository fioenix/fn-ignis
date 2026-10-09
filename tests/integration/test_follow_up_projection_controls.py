"""T077 behavioral projection controls on existing admitted child execution."""

import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from tests.integration.test_follow_up_execution import execution_ready
from tests.integration.test_mission_relay_read_boundary import _reader


@pytest.mark.asyncio
async def test_completed_admitted_child_is_labeled_without_joining_parent_frame(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    try:
        ingress.release.set()
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'projection-control')
        assert result.status == 'COMPLETED', result.to_payload()
        link = result.relationship
        stored = await repository.load_mission_follow_ups(parent.id)
        assert stored.relationships == (link,)
        child_journals = await repository.list_run_journals(link.child_mission_id)
        parent_journals = await repository.list_run_journals(parent.id)
        assert len(child_journals) == 1 and child_journals[0].status == 'COMPLETED'
        parent_run = parent_journals[-1]
        use_case = GetMissionRelaySnapshotUseCase(_reader(repository))
        parent_payload = (await use_case.execute(MissionRelayReadRequest(
            mission_id=parent.id, run_id=parent_run.run_id, page_size=1))).to_payload()
        child_payload = (await use_case.execute(MissionRelayReadRequest(
            mission_id=link.child_mission_id, run_id=child_journals[0].run_id, page_size=1))).to_payload()
        assert parent_payload['status'] == child_payload['status'] == 'OK', (
            (parent_payload['status'], parent_payload.get('reason_code')),
            (child_payload['status'], child_payload.get('reason_code')))
        assert child_payload['frame_digest'] is not None
        assert parent_payload['mission_id'] == str(parent.id)
        assert parent_payload['event_page']['resync_required'] is True
        assert parent_payload['event_page']['events'] == []
        assert parent_payload['event_page']['next_cursor'] is None
        assert parent_payload['run_id'] == str(parent_run.run_id)
        assert all(row['mission_id'] == str(parent.id) for row in parent_payload['evidence'])
        assert ingress.connector_calls == ingress.auth_initializations == 1
        assert parent_payload.get('related_results', []) == [{
            'relation': 'FOLLOW_UP_CHILD', 'mission_id': str(link.child_mission_id),
            'run_id': None, 'frame_digest': None,
            'finding_references': [], 'inspection_status': 'SELECT_CHILD_REQUIRED',
        }]
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('corruption', ['orphan-revision', 'fingerprint', 'wrong-parent'])
async def test_orphaned_parent_revision_is_not_licensed_by_prior_follow_up_receipt(tmp_path, corruption):
    import sqlite3
    from contextlib import closing
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    try:
        ingress.release.set()
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'orphan-control')
        assert result.status == 'COMPLETED', result.to_payload()
        parent_run = (await repository.list_run_journals(parent.id))[-1]
        request = MissionRelayReadRequest(mission_id=parent.id, run_id=parent_run.run_id, page_size=1)
        use_case = GetMissionRelaySnapshotUseCase(_reader(repository))
        assert (await use_case.execute(request)).to_payload()['status'] == 'OK'
        # Deliberately corrupt only this disposable fixture: no immutable receipt
        # or event attests the added revision. Prior valid receipts cannot license it.
        if corruption == 'orphan-revision':
            with closing(sqlite3.connect(repository._db_path)) as conn:
                conn.execute('UPDATE mission_progress_revisions SET revision=revision+1 WHERE mission_id=?',
                             (str(parent.id),))
                conn.commit()
        else:
            from types import SimpleNamespace
            from tests.integration.follow_up_execution_setup import corrupt_disposable
            field = 'fingerprint' if corruption == 'fingerprint' else 'parent_mission_id'
            value = '0' * 64 if corruption == 'fingerprint' else str(result.relationship.child_mission_id)
            corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
                ('mission_follow_up_commands', f'UPDATE mission_follow_up_commands SET {field}=? '
                 'WHERE parent_mission_id=? AND operation=?', (value, str(parent.id), 'ADMIT'))])
        with closing(sqlite3.connect(repository._db_path)) as conn:
            before = tuple(conn.iterdump())
        payload = (await use_case.execute(request)).to_payload()
        assert payload == {'schema_version': 1, 'status': 'UNAVAILABLE', 'reason_code': 'READ_UNAVAILABLE'}
        with closing(sqlite3.connect(repository._db_path)) as conn:
            assert tuple(conn.iterdump()) == before
        assert ingress.connector_calls == ingress.auth_initializations == 1
    finally:
        await repository.close()
