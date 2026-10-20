"""Actual coherent permission readback through the snapshot tool, isolated from real-mission UAT.

R2 retired the viewer and its display-latency goal; an agent's tracking artifact reads the same
snapshot, so permission must reach the next read exactly and never leak into history.
"""
import json

import pytest
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from tests.unit.test_mission_claims import _eligible_mission, _observation_candidate, _signal_named
from test_mission_relay_read_boundary import relay_case  # noqa: F401 -- fixture
from test_mission_relay_mcp import _caller_client, _view_only


@pytest.mark.asyncio
async def test_us3_actual_permission_readback(relay_case, tmp_path, monkeypatch):  # noqa: F811 -- fixture
    from ignis.interfaces.mcp import server
    case, _, _ = relay_case
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path, repository=case.repository)
    use_case = SubmitMissionClaimsUseCase(repository, store)
    candidate = _observation_candidate(_signal_named(signals, 'Demand evidence'))
    result = await use_case.execute(str(mission.id), frame.frame_digest, [candidate], created_by='readback-control')
    assert result.get('permitted') == 1
    run = (await store.list_run_journals(mission.id))[0]
    def forbidden(*args, **kwargs):
        raise AssertionError('Readback initialized components or credentials')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)

    async def read(client):
        return (await client.call_tool('get_mission_relay_snapshot', {'mission_id': str(mission.id),
            'run_id': str(run.run_id), 'page_size': 100})).structured_content

    async with _caller_client(monkeypatch, tmp_path, {'repository': repository}) as client:
        with _view_only(case, monkeypatch):
            first = await read(client)
            assert first['claim_gate']['state'] == 'CURRENT' and first['frame_digest'] == frame.frame_digest
            assert candidate['wording'] in [claim['wording'] for claim in first['claim_gate']['claims']]
        wording = 'A newly persisted fixture statement with exact observation support.'
        candidate = {**candidate, 'client_claim_key': 'timed-current-fixture', 'wording': wording}
        result = await use_case.execute(str(mission.id), frame.frame_digest, [candidate], created_by='readback-control')
        assert result.get('permitted') == 1
        with _view_only(case, monkeypatch):
            second = await read(client)
            gate = second['claim_gate']
            current = next(claim for claim in gate['claims'] if claim['wording'] == wording)
            assert current['status'] == 'PERMITTED' and current['frame_digest'] == frame.frame_digest
            assert wording not in json.dumps(gate['history'])
            observation = str(_signal_named(signals, 'Demand evidence').observation_id)
            assert observation in json.dumps(current['evidence_bindings'])
            assert second['revision'] >= first['revision'] and second['read_at'] >= first['read_at']
