"""Related-child references require original receipt proof even at a legacy event head."""

from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from tests.integration.follow_up_execution_setup import corrupt_disposable
from tests.integration.test_follow_up_execution import execution_ready
from tests.integration.test_mission_relay_read_boundary import _reader


@pytest.mark.asyncio
async def test_aligned_legacy_head_does_not_license_related_child_with_corrupt_admission_receipt(tmp_path):
    repository, parent, work, service, ingress, verifier = await execution_ready(tmp_path)
    try:
        ingress.release.set()
        result = await service.execute(str(parent.id), str(work.work_id), 1, 'related-proof-control')
        assert result.status == 'COMPLETED', result.to_payload()
        store = WorkspaceRepository(repository)
        canonical = await store.load_mission_evidence_snapshot(parent.id)
        # A genuine subsequent claim is required only to exercise the
        # legacy-head branch; the separate eventless-parent regression stays intact.
        from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
        from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
        from tests.unit.test_mission_claims import _observation_candidate
        frame = await load_current_evidence_frame(repository, store, parent)
        demand = next(s for s in canonical.signals if s.raw_title == 'Demand evidence')
        candidate = {**_observation_candidate(demand), 'client_claim_key': 't077-related-proof-new-claim'}
        receipt = await SubmitMissionClaimsUseCase(repository, store).execute(str(parent.id), frame.frame_digest,
            [candidate], created_by='t077-related-proof-offline-fixture')
        assert receipt['permitted'] == 1
        with closing(sqlite3.connect(repository._db_path)) as conn:
            committed = conn.execute('SELECT revision FROM mission_progress_revisions WHERE mission_id=?',
                                     (str(parent.id),)).fetchone()[0]
            legacy = conn.execute('SELECT MAX(revision) FROM mission_progress_events WHERE mission_id=?',
                                  (str(parent.id),)).fetchone()[0]
        assert committed == legacy
        run = (await repository.list_run_journals(parent.id))[-1]
        request = MissionRelayReadRequest(mission_id=parent.id, run_id=run.run_id, page_size=1)
        use_case = GetMissionRelaySnapshotUseCase(_reader(repository))
        before = (await use_case.execute(request)).to_payload()
        assert before['status'] == 'OK'
        assert len(before['related_results']) == 1
        corrupt_disposable(SimpleNamespace(name='sqlite', repository=repository), [
            ('mission_follow_up_commands', 'UPDATE mission_follow_up_commands SET fingerprint=? '
             'WHERE parent_mission_id=? AND operation=?', ('0' * 64, str(parent.id), 'ADMIT'))])
        with closing(sqlite3.connect(repository._db_path)) as conn:
            physical = tuple(conn.iterdump())
        after = (await use_case.execute(request)).to_payload()
        assert after == {'schema_version': 1, 'status': 'UNAVAILABLE', 'reason_code': 'READ_UNAVAILABLE'}
        with closing(sqlite3.connect(repository._db_path)) as conn:
            assert tuple(conn.iterdump()) == physical
        assert ingress.auth_initializations == ingress.connector_calls == 1
    finally:
        await repository.close()
