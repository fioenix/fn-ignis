"""Analysis producers must preserve stale-frame refusals at the committing boundary.

Changing the use-case write to a legacy save, or misclassifying the transactional
frame refusal as invalid input, must fail these real-storage controls.
"""

import pytest

from test_mission_progress_ingress import (
    _attention,
    _events,
    _market,
    _revision,
    _rows,
    _signal,
    _submit_claim,
    _submit_qualification,
    ingress_case,
)

__all__ = ["ingress_case"]


@pytest.mark.asyncio
@pytest.mark.parametrize("unit", ("qualification", "claim"))
async def test_frame_change_between_validation_and_commit_refuses_whole_batch(
    ingress_case, tmp_path, monkeypatch, unit
):
    case = ingress_case
    if unit == "qualification":
        store, mission, executor = await _attention(case, tmp_path)
        assert (await executor.execute(mission.id))["status"] == "COMPLETED"
        signal = (await case.repository.get_mission_signals(mission.id))[0]
        real_commit = store.commit_evidence_qualifications

        async def changed_commit(mission_id, judgments):
            current = await case.repository.get_mission(mission_id)
            current.title = "Changed Attention question"
            await case.repository.update_mission(current)
            return await real_commit(mission_id, judgments)

        monkeypatch.setattr(store, "commit_evidence_qualifications", changed_commit)
        table, kind = "mission_evidence_qualifications", "QUALIFICATION_RECORDED"
    else:
        store, mission, brief, signal = await _market(case, tmp_path)
        assert (await _submit_qualification(case, store, mission, brief, signal))["status"] == "RECORDED"
        real_commit = store.commit_mission_claims

        async def changed_commit(mission_id, digest, claims):
            later = _signal("Changed claim evidence")
            later.mission_id = mission_id
            await case.repository.save_signals([later])
            return await real_commit(mission_id, digest, claims)

        monkeypatch.setattr(store, "commit_mission_claims", changed_commit)
        table, kind = "mission_claims", "CLAIM_GATE_CHANGED"

    before = (_rows(case, table, mission.id), _events(case, mission.id, kind), _revision(case, mission.id))
    if unit == "qualification":
        result = await _submit_qualification(case, store, mission, None, signal)
    else:
        result = await _submit_claim(case, store, mission)
    assert result["status"] == "CONFLICT"
    assert result["reason_code"] == "STALE_FRAME"
    assert (_rows(case, table, mission.id), _events(case, mission.id, kind), _revision(case, mission.id)) == before
