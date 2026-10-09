"""Native PostgreSQL receipt-head and related-reference boundary controls."""

import json

import psycopg
import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from tests.integration.follow_up_execution_setup import ready, corrupt_disposable
from tests.integration.follow_up_mcp_setup import native_executor
from tests.integration.test_follow_up_execution import OfflineExecutionVerifier
from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
from tests.integration.test_mission_follow_up import relay_case
from tests.integration.test_mission_relay_read_boundary import _reader, _state
from tests.unit.test_mission_claims import _observation_candidate


class NativeVerifier(OfflineExecutionVerifier):
    """Use the accepted PostgreSQL generation guard with its actual superclass."""
    hold_current = AsyncVerifier.hold_current


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('postgres',), indirect=True)
@pytest.mark.parametrize('control', ['eventless', 'orphan-revision', 'fingerprint', 'wrong-parent', 'aligned-fingerprint', 'partial-commands-schema'])
async def test_native_postgres_follow_up_projection_receipt_proof(relay_case, tmp_path, control):
    case, _, _ = relay_case
    repository = case.repository
    probe_file = tmp_path / 'private-offline-probes.json'
    executor, _, store = native_executor(repository, probe_file)
    _, parent, work, authority, _ = await ready(repository, tmp_path, executor, ExecuteMissionFollowUpUseCase)
    verifier = NativeVerifier()
    repository.configure_follow_up_verifier(verifier)
    service = ExecuteMissionFollowUpUseCase(repository, executor, selected_parent_id=parent.id, host_authorized=True)
    result = await service.execute(str(parent.id), str(work.work_id), 1, 'pg-projection-control')
    assert result.status == 'COMPLETED', result.to_payload()
    link = result.relationship
    assert (await repository.load_mission_follow_ups(parent.id)).relationships == (link,)
    parent_run = (await repository.list_run_journals(parent.id))[-1]
    request = MissionRelayReadRequest(mission_id=parent.id, run_id=parent_run.run_id, page_size=1)
    use_case = GetMissionRelaySnapshotUseCase(_reader(repository))
    baseline = (await use_case.execute(request)).to_payload()
    assert baseline['status'] == 'OK'
    assert baseline['event_page']['resync_required'] is True
    assert baseline['event_page']['events'] == []
    assert baseline['event_page']['next_cursor'] is None
    assert baseline['related_results'] == [{
        'relation': 'FOLLOW_UP_CHILD', 'mission_id': str(link.child_mission_id),
        'run_id': None, 'frame_digest': None, 'finding_references': [],
        'inspection_status': 'SELECT_CHILD_REQUIRED',
    }]
    if control in {'aligned-fingerprint', 'partial-commands-schema'}:
        canonical = await store.load_mission_evidence_snapshot(parent.id)
        frame = await load_current_evidence_frame(repository, store, parent)
        demand = next(s for s in canonical.signals if s.raw_title == 'Demand evidence')
        candidate = {**_observation_candidate(demand), 'client_claim_key': 't077-pg-proof-new-claim'}
        receipt = await SubmitMissionClaimsUseCase(repository, store).execute(str(parent.id), frame.frame_digest,
            [candidate], created_by='t077-pg-offline-fixture')
        assert receipt['permitted'] == 1
        with psycopg.connect(case.dsn) as conn:
            head = conn.execute('SELECT revision FROM mission_progress_revisions WHERE mission_id=%s', (parent.id,)).fetchone()[0]
            legacy = conn.execute('SELECT MAX(revision) FROM mission_progress_events WHERE mission_id=%s', (parent.id,)).fetchone()[0]
        assert head == legacy
        aligned = (await use_case.execute(request)).to_payload()
        assert aligned['status'] == 'OK'
    if control == 'orphan-revision':
        with psycopg.connect(case.dsn) as conn:
            conn.execute('UPDATE mission_progress_revisions SET revision=revision+1 WHERE mission_id=%s', (parent.id,))
    elif control == 'partial-commands-schema':
        with psycopg.connect(case.dsn) as conn:
            conn.execute('ALTER TABLE mission_follow_up_commands RENAME COLUMN fingerprint TO partial_fingerprint')
    elif control != 'eventless':
        field = 'parent_mission_id' if control == 'wrong-parent' else 'fingerprint'
        value = str(link.child_mission_id) if control == 'wrong-parent' else '0' * 64
        corrupt_disposable(case, [('mission_follow_up_commands',
            f'UPDATE mission_follow_up_commands SET {field}=? WHERE parent_mission_id=? AND operation=?',
            (value, str(parent.id), 'ADMIT'))])
    physical = _state(case)
    proof_calls = verifier.calls
    probes = probe_file.read_text()
    after = (await use_case.execute(request)).to_payload()
    if control == 'partial-commands-schema':
        assert after['status'] == 'OK', (after['status'], after.get('reason_code'))
        assert after['related_results'] == []
        assert after['related_results_coverage'] == {'availability': 'SCHEMA_UNAVAILABLE', 'total': None}
        for field in ('mission_id', 'run_id', 'high_water', 'frame_digest', 'counts', 'evidence', 'claim_gate'):
            assert after[field] == aligned[field]
    elif control == 'eventless':
        assert after['related_results'] == baseline['related_results']
        assert after['high_water'] == baseline['high_water']
    else:
        assert after == {'schema_version': 1, 'status': 'UNAVAILABLE', 'reason_code': 'READ_UNAVAILABLE'}
    assert _state(case) == physical
    assert verifier.calls == proof_calls
    assert probe_file.read_text() == probes
    assert json.loads(probes) == [list(work.requested_scope.queries)]
