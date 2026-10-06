"""Physical SQLite result controls beyond unchanged T042 acceptance assertions."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.integration.test_research_work_persistence import _arrange, _commit, _sql
from tests.integration import test_mission_relay_read_boundary as physical

_state = physical._state
relay_case = physical.relay_case


@pytest.mark.asyncio
async def test_result_retains_independent_source_order_and_submitted_times(relay_case, tmp_path):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    handoff = replace(
        handoff,
        observation_sources=tuple(reversed(handoff.observation_sources)),
        recorded_at=handoff.occurred_at - timedelta(days=1),
        findings=(replace(handoff.findings[0], recorded_at=handoff.occurred_at - timedelta(days=2)),),
    )
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,)
    assert snapshot.findings == handoff.findings
    metadata = [m for m in snapshot.recorded_metadata if m.record_kind in {"HANDOFF", "FINDING"}]
    assert len(metadata) == 2 and all(
        m.recorded_at == receipt.recorded_at and m.provenance == "HARNESS_OBSERVED" for m in metadata
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["accepted", "rejected", "without_ack"])
async def test_completion_settles_only_current_unrejected_result(relay_case, tmp_path, mode):
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    committed = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert committed.disposition == "APPLIED"
    revision, version = committed.revision, committed.work_version
    if mode != "without_ack":
        ack = port.ResearchHandoffAcknowledgement(
            handoff_id=handoff.handoff_id,
            consumer_ref=handoff.consumer_ref,
            expected_version=version,
            disposition="ACCEPTED" if mode == "accepted" else "REJECTED",
            reason_code=None if mode == "accepted" else "INPUT_REVISION_MISMATCH",
            inputs=handoff.inputs,
        )
        result = await _commit(case.repository, port, mission, "ACK_HANDOFF", ack, revision=revision)
        assert result.disposition == "APPLIED"
        snapshot = await case.repository.load_research_work(mission.id)
        assert snapshot.acknowledgements == (ack,)
        events = [e for e in snapshot.events if e.cursor.revision == result.revision]
        assert [e.kind.value for e in events] == (
            ["HANDOFF_ACKNOWLEDGED", "WORK_ENDED"] if mode == "accepted" else ["HANDOFF_ACKNOWLEDGED"]
        )
        assert snapshot.work_items[0].state == ("COMPLETED" if mode == "accepted" else "HANDOFF_READY")
        if mode == "accepted":
            return
        revision, version = result.revision, result.work_version
    end = domain.EndWorkPayload(
        work_id=work.work_id,
        expected_version=version,
        ownership_fence=work.ownership_fence,
        reason="Result settled",
        disposition="COMPLETED",
    )
    result = await _commit(case.repository, port, mission, "END_WORK", end, revision=revision)
    assert result.disposition == ("REFUSED" if mode == "rejected" else "APPLIED")
    if mode == "rejected":
        assert result.reason_code == "RESULT_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, 3])
async def test_handoff_finding_order_and_zero_result_collections(relay_case, tmp_path, count):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    findings = tuple(replace(handoff.findings[0], finding_id=uuid4(), statement=f"Finding {i}") for i in range(count))
    handoff = replace(handoff, findings=findings, occurred_at=None, recorded_at=None)
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,) and snapshot.findings == findings
    assert snapshot.current_finding_revisions == tuple((f.finding_id, 1) for f in findings)
    events = [e for e in snapshot.events if e.cursor.revision == receipt.revision]
    assert [e.kind.value for e in events] == ["HANDOFF_COMMITTED"] + ["FINDING_REVISED"] * count
    assert [e.finding_id for e in events[1:]] == [f.finding_id for f in findings]
    assert [e.cursor.ordinal for e in events] == list(range(1, count + 2))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field", ["result", "statement", "consumer_ref", "limitations", "open_questions", "alternative_explanation"]
)
async def test_result_masks_all_typed_text_fields(relay_case, tmp_path, field):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    private = "person@example.com"
    finding = handoff.findings[0]
    if field == "statement":
        handoff = replace(handoff, findings=(replace(finding, statement=private),))
    elif field == "alternative_explanation":
        handoff = replace(handoff, findings=(replace(finding, alternative_explanation=private),))
    elif field in {"limitations", "open_questions"}:
        handoff = replace(handoff, **{field: (private,)}, findings=(replace(finding, **{field: (private,)}),))
    else:
        handoff = replace(handoff, **{field: private})
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert private not in repr(snapshot.to_payload()) and private not in repr(_state(case))


@pytest.mark.asyncio
async def test_mask_expansion_refusal_is_original_after_later_activity(relay_case, tmp_path):
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    # Existing sanitizer replacement expands these short email matches beyond4096.
    handoff = replace(handoff, result=" ".join(["a@b.co"] * 580))
    assert len(handoff.result) <= 4096
    first = await _commit(
        case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key="expanded-result"
    )
    assert first.disposition == "REFUSED" and first.reason_code == "INVALID_INPUT"
    waited = await _commit(
        case.repository,
        port,
        mission,
        "WAIT_WORK",
        domain.ReasonWorkPayload(
            work_id=work.work_id,
            expected_version=work.version,
            ownership_fence=work.ownership_fence,
            reason="Await review",
        ),
        revision=revision,
    )
    assert waited.disposition == "APPLIED"
    before = _state(case)
    retry = await _commit(
        case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key="expanded-result"
    )
    assert retry == first and _state(case) == before
    assert handoff.result not in repr(before)


@pytest.mark.asyncio
async def test_handoff_observation_rows_are_scoped_sealed_and_history_retained(relay_case, tmp_path):
    import sqlite3

    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    rows = _state(case)[1]["research_handoff_observations"]
    assert len(rows) == len(handoff.observation_sources)
    input_id = _state(case)[1]["research_input_sets"][0][0]
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(
            case,
            "INSERT INTO research_handoff_observations VALUES (?,?,?,?,?,?)",
            (999, mission.id, handoff.handoff_id, input_id, *handoff.observation_sources[0]),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(
            case, "UPDATE research_handoff_observations SET ordinal=999 WHERE handoff_id=?", (handoff.handoff_id,)
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(case, "DELETE FROM research_handoff_observations WHERE handoff_id=?", (handoff.handoff_id,))
    observation = handoff.observation_sources[0][0]
    assert (
        await _sql(
            case, "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?", (mission.id, observation)
        )
        == 1
    )
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,) and snapshot.current_finding_revisions == ()
    assert _state(case)[1]["research_handoff_observations"] == rows


@pytest.mark.asyncio
async def test_predecessor_lineage_does_not_invent_dependency_currentness(relay_case, tmp_path):
    from tests.integration.test_research_work_persistence import _another_work

    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    original = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert original.disposition == "APPLIED"
    finding = handoff.findings[0]
    inputs = replace(work.inputs, finding_revisions=((finding.finding_id, 1),))
    producer, revision = await _another_work(case, mission, domain, port, work, inputs, original.revision)
    identity = uuid4()
    revised = replace(
        finding, revision=2, predecessor_revision=1, inputs=inputs, work_id=producer.work_id, handoff_id=identity
    )
    result = replace(
        handoff,
        handoff_id=identity,
        work_id=producer.work_id,
        expected_version=producer.version,
        inputs=inputs,
        findings=(revised,),
    )
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", result, revision=revision)
    assert receipt.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.findings == (finding, revised)
    assert snapshot.current_finding_revisions == ()
    assert snapshot.work_items[-1].dependencies == (work.work_id,)
    # Exact submitted predecessor input is retained; latest2 supersedes that input1.
    assert revised.inputs.finding_revisions == ((finding.finding_id, 1),)


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ["memory"], indirect=True)
async def test_cancelled_private_memory_result_holds_owner_through_settlement(relay_case, tmp_path, monkeypatch):
    import asyncio
    import threading

    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    assert case.repository._mem_conn is not None
    entered, release = threading.Event(), threading.Event()
    original = case.repository._record_progress

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(case.repository, "_record_progress", blocked)
    task = asyncio.create_task(
        _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key="settled-result")
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        reader = asyncio.create_task(case.repository.load_research_work(mission.id))
        await asyncio.sleep(0)
        assert case.repository._lock.locked() and not reader.done() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        snapshot = await reader
        assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
        retry = await _commit(
            case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key="settled-result"
        )
        assert retry.disposition == "APPLIED" and retry.revision == snapshot.revision
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_masked_consumer_can_acknowledge_original_public_safe_identity(relay_case, tmp_path):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    handoff = replace(handoff, consumer_ref="person@example.com")
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    ack = port.ResearchHandoffAcknowledgement(
        handoff_id=handoff.handoff_id,
        consumer_ref=handoff.consumer_ref,
        expected_version=receipt.work_version,
        disposition="REJECTED",
        reason_code="INPUT_REVISION_MISMATCH",
        inputs=handoff.inputs,
    )
    result = await _commit(case.repository, port, mission, "ACK_HANDOFF", ack, revision=receipt.revision)
    assert result.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert len(snapshot.acknowledgements) == 1
    assert snapshot.acknowledgements[0].consumer_ref == snapshot.handoffs[0].consumer_ref
    assert "person@example.com" not in repr(_state(case))
