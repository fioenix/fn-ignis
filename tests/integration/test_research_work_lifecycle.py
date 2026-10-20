"""Public service lifecycle acceptance on canonical physical stores.

Existing T051/core/result behavior is exercised, not reimplemented or dispatched.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.integration.test_mission_relay_read_boundary import relay_case as _relay_case, _state
from tests.integration.test_research_work_persistence import _arrange, _sql
from tests.integration.test_research_work_command_service import command, execute
from tests.unit.test_record_mission_research_work import assignment_command

relay_case = _relay_case


def bound(work, version=None):
    return {
        "work_id": str(work.work_id),
        "expected_version": version or work.version,
        "ownership_fence": work.ownership_fence,
        "reason": "INVALID_INPUT",
    }


def result_body(handoff):
    payload = handoff.to_payload()
    del payload["recorded_at"]
    for finding in payload["findings"]:
        del finding["recorded_at"]
    return payload


def activity(work, version=None):
    now = datetime.now(timezone.utc)
    payload = bound(work, version)
    del payload["reason"]
    return {
        **payload,
        "execution_ref": "synthetic-execution",
        "occurred_at": now.isoformat(),
        "fresh_until": (now + timedelta(minutes=5)).isoformat(),
    }


async def refused(case, mission, body, reason):
    before = _state(case)
    snapshot = await case.repository.load_research_work(mission.id)
    receipt = await execute(case, mission, body)
    assert receipt["disposition"] == "REFUSED" and receipt["reason_code"] == reason
    assert receipt["event_ids"] == [] and receipt["receipt_id"] is not None
    assert await case.repository.load_research_work(mission.id) == snapshot
    after = _state(case)
    assert after[0] == before[0]
    for name in before[1]:
        if name != "research_work_commands":
            assert after[1][name] == before[1][name]
    assert len(after[1]["research_work_commands"]) == len(before[1]["research_work_commands"]) + 1
    assert "REJECTED_PRIVATE_SENTINEL" not in repr(after)
    assert await execute(case, mission, deepcopy(body)) == receipt
    assert _state(case) == after
    return receipt


async def end_research(case, mission, revision, disposition="INTERRUPTED"):
    snapshot = await case.repository.load_research_work(mission.id)
    assignment = snapshot.assignments[0]
    body = command(
        "END_RESEARCH",
        {
            "assignment_id": str(assignment.assignment_id),
            "expected_version": assignment.version,
            "disposition": disposition,
            "reason": "INVALID_INPUT",
        },
        revision,
    )
    receipt = await execute(case, mission, body)
    assert receipt["disposition"] == "APPLIED"
    return body, receipt


async def new_grant(case, mission, revision):
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    body = assignment_command()
    body["expected_epoch"] = 2
    body["expected_revision"] = revision
    body["payload"]["expected_manifest_digest"] = evidence.manifest.manifest_digest
    body["payload"]["expected_brief_revision_id"] = str(evidence.brief.brief_revision_id)
    body["payload"]["authority"]["deadline"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    receipt = await execute(case, mission, body)
    assert receipt["disposition"] == "APPLIED"
    return body, receipt


@pytest.mark.asyncio
async def test_cancel_request_fences_activity_result_and_requires_bound_stop(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    body = command("REQUEST_CANCEL", bound(work), revision)
    pending = await execute(case, mission, body)
    assert pending["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == "CANCEL_PENDING"
    assert snapshot.assignments[0].state == "ACTIVE"
    assert [e.kind for e in snapshot.events if str(e.event_id) in pending["event_ids"]] == ["CANCELLATION_REQUESTED"]
    for operation in ("START_WORK", "RESUME_WORK", "RECORD_ACTIVITY", "SUBMIT_HANDOFF"):
        payload = (
            activity(work, pending["work_version"])
            if operation in {"START_WORK", "RECORD_ACTIVITY"}
            else bound(work, pending["work_version"])
        )
        if operation == "SUBMIT_HANDOFF":
            payload = result_body(handoff)
            payload["expected_version"] = pending["work_version"]
            payload["result"] = "REJECTED_PRIVATE_SENTINEL"
        await refused(case, mission, command(operation, payload, pending["revision"]), "CANCELLATION_PENDING")
    end_body, ended = await end_research(case, mission, pending["revision"])
    grant_body, grant = await new_grant(case, mission, ended["revision"])
    stop_payload = {**bound(work, pending["work_version"]), "execution_ref": "synthetic-execution"}
    for control, reason in [
        ("epoch", "STALE_EPOCH"),
        ("version", "STALE_VERSION"),
        ("fence", "STALE_FENCE"),
        ("execution", "EXECUTION_RECEIPT_NOT_CURRENT"),
    ]:
        wrong = command("ACK_STOP", deepcopy(stop_payload), grant["revision"])
        if control == "epoch":
            wrong["expected_epoch"] = 2
        if control == "version":
            wrong["payload"]["expected_version"] -= 1
        if control == "fence":
            wrong["payload"]["ownership_fence"] = "foreign-fence"
        if control == "execution":
            wrong["payload"]["execution_ref"] = "foreign-execution"
        await refused(case, mission, wrong, reason)
    stop_body = command("ACK_STOP", stop_payload, grant["revision"])
    stopped = await execute(case, mission, stop_body)
    assert stopped["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == "CANCELLED"
    assert snapshot.current_epoch == 2
    assert snapshot.assignments[0].state == "INTERRUPTED"
    assert snapshot.assignments[1].state == "ASSIGNED" and snapshot.assignments[1].version == 1
    assert [e.kind for e in snapshot.events if str(e.event_id) in stopped["event_ids"]] == ["CANCELLATION_ACKNOWLEDGED"]
    before = _state(case)
    for original, receipt in [(body, pending), (end_body, ended), (grant_body, grant), (stop_body, stopped)]:
        assert await execute(case, mission, deepcopy(original)) == receipt
        assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["COMPLETED", "CANCELLED", "FAILED", "INSUFFICIENT_EVIDENCE"])
@pytest.mark.parametrize("new_epoch", [False, True])
@pytest.mark.parametrize("operation", ["ASSIGN_WORK", "START_WORK", "RESUME_WORK", "RECORD_ACTIVITY", "SUBMIT_HANDOFF"])
async def test_termination_forbids_all_new_admissions(relay_case, tmp_path, new_epoch, operation, terminal):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    _, ended = await end_research(case, mission, revision, terminal)
    last = ended
    if new_epoch:
        _, last = await new_grant(case, mission, ended["revision"])
    if operation == "ASSIGN_WORK":
        payload = {
            "assignment_id": str(work.assignment_id),
            "work_id": str(uuid4()),
            "question": "REJECTED_PRIVATE_SENTINEL",
            "expertise": "Synthesis",
            "assignee_ref": None,
            "inputs": work.inputs.to_payload(),
            "dependencies": [],
            "ownership_fence": "new-fence",
        }
    elif operation == "SUBMIT_HANDOFF":
        payload = result_body(handoff)
        payload["result"] = "REJECTED_PRIVATE_SENTINEL"
    elif operation in {"START_WORK", "RECORD_ACTIVITY"}:
        payload = activity(work)
    else:
        payload = bound(work)
    await refused(
        case,
        mission,
        command(operation, payload, last["revision"]),
        "STALE_EPOCH" if new_epoch else "ASSIGNMENT_TERMINAL",
    )
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0] == work


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["FAILED", "INTERRUPTED", "INSUFFICIENT_EVIDENCE"])
async def test_old_bound_failure_settles_without_reviving_new_authority(relay_case, tmp_path, disposition):
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    _, ended = await end_research(case, mission, revision)
    _, grant = await new_grant(case, mission, ended["revision"])
    payload = {**bound(work), "disposition": disposition}
    wrong = command("END_WORK", payload, grant["revision"])
    wrong["expected_epoch"] = 2
    await refused(case, mission, wrong, "STALE_EPOCH")
    body = command("END_WORK", payload, grant["revision"])
    closed = await execute(case, mission, body)
    assert closed["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == disposition
    assert snapshot.assignments[1].state == "ASSIGNED" and snapshot.assignments[1].version == 1
    assert snapshot.current_epoch == 2
    before = _state(case)
    assert await execute(case, mission, deepcopy(body)) == closed
    assert _state(case) == before


@pytest.mark.asyncio
async def test_completion_requires_admitted_result_ack_is_optional(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    completion = command("END_WORK", {**bound(work), "disposition": "COMPLETED"}, revision)
    missing = await refused(case, mission, completion, "RESULT_REQUIRED")
    submitted = await execute(case, mission, command("SUBMIT_HANDOFF", result_body(handoff), revision))
    assert submitted["disposition"] == "APPLIED"
    completed = await execute(
        case,
        mission,
        command(
            "END_WORK", {**bound(work, submitted["work_version"]), "disposition": "COMPLETED"}, submitted["revision"]
        ),
    )
    assert completed["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == "COMPLETED"
    assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
    assert snapshot.acknowledgements == ()
    before = _state(case)
    assert await execute(case, mission, completion) == missing
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["START_WORK", "RESUME_WORK", "RECORD_ACTIVITY", "SUBMIT_HANDOFF"])
async def test_current_deadline_fences_execution_but_preserves_closure(relay_case, tmp_path, operation):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    # Owner mutation creates genuinely expired persisted authority on both physical stores.
    await _sql(
        case,
        "UPDATE research_assignments SET deadline=? WHERE assignment_id=?",
        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), str(work.assignment_id)),
    )
    payload = (
        activity(work)
        if operation in {"START_WORK", "RECORD_ACTIVITY"}
        else result_body(handoff)
        if operation == "SUBMIT_HANDOFF"
        else bound(work)
    )
    await refused(case, mission, command(operation, payload, revision), "AUTHORITY_EXPIRED")
    closed = await execute(case, mission, command("END_WORK", {**bound(work), "disposition": "INTERRUPTED"}, revision))
    assert closed["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == "INTERRUPTED"
    assert snapshot.assignments[0].state == "ACTIVE"
    assert snapshot.assignments[0].authority.deadline < datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_explicit_analysis_after_collection_complete_activates_assignment_once(relay_case, tmp_path):
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    _, ended = await end_research(case, mission, revision)
    # Canonical collection status is independent from a separately explicit research grant.
    await _sql(case, "UPDATE research_missions SET status=? WHERE id=?", ("COMPLETED", str(mission.id)))
    assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"
    _, grant = await new_grant(case, mission, ended["revision"])
    snapshot = await case.repository.load_research_work(mission.id)
    assignment = snapshot.assignments[1]
    assert assignment.state == "ASSIGNED" and assignment.version == 1
    last = grant
    for index in range(2):
        identity = str(uuid4())
        body = command(
            "ASSIGN_WORK",
            {
                "assignment_id": str(assignment.assignment_id),
                "work_id": identity,
                "question": "Bounded post-collection analysis",
                "expertise": "Synthesis",
                "assignee_ref": "synthetic-worker",
                "inputs": work.inputs.to_payload(),
                "dependencies": [],
                "ownership_fence": f"post-fence-{index}",
            },
            last["revision"],
        )
        body["expected_epoch"] = 2
        assigned = await execute(case, mission, body)
        assert assigned["disposition"] == "APPLIED"
        snapshot = await case.repository.load_research_work(mission.id)
        new_work = next(w for w in snapshot.work_items if str(w.work_id) == identity)
        start_body = command("START_WORK", activity(new_work), assigned["revision"])
        start_body["expected_epoch"] = 2
        last = await execute(case, mission, start_body)
        assert last["disposition"] == "APPLIED"
        snapshot = await case.repository.load_research_work(mission.id)
        actual_assignment = snapshot.assignments[1]
        assert actual_assignment.state == "ACTIVE" and actual_assignment.version == 2
        metadata = [
            m
            for m in snapshot.recorded_metadata
            if m.record_kind == "ASSIGNMENT" and m.record_id == assignment.assignment_id and m.record_version == 2
        ]
        assert len(metadata) == 1 and metadata[0].provenance == "HARNESS_OBSERVED"
        before = _state(case)
        assert await execute(case, mission, deepcopy(start_body)) == last
        assert _state(case) == before
    # Persisted host receipt stays HOST_REPORTED, even though its transaction metadata is observed.
    rows = _state(case)[1]["research_activity_receipts"]
    assert len(rows) == 3
    assert all("HOST_REPORTED" in row for row in rows)
    assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"


@pytest.mark.asyncio
async def test_rejected_handoff_cannot_supply_completion(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    submitted = await execute(case, mission, command("SUBMIT_HANDOFF", result_body(handoff), revision))
    assert submitted["disposition"] == "APPLIED"
    ack = await execute(
        case,
        mission,
        command(
            "ACK_HANDOFF",
            {
                "handoff_id": str(handoff.handoff_id),
                "consumer_ref": handoff.consumer_ref,
                "expected_version": submitted["work_version"],
                "disposition": "REJECTED",
                "reason_code": "INVALID_INPUT",
                "inputs": work.inputs.to_payload(),
            },
            submitted["revision"],
        ),
    )
    assert ack["disposition"] == "APPLIED"
    await refused(
        case,
        mission,
        command("END_WORK", {**bound(work, ack["work_version"]), "disposition": "COMPLETED"}, ack["revision"]),
        "RESULT_REQUIRED",
    )


@pytest.mark.asyncio
async def test_persisted_activity_has_finite_host_provenance_and_no_implicit_renewal(relay_case, tmp_path):
    from uuid import UUID
    import psycopg
    from ignis.domain.research_work import ResearchActivityReceipt, project_work_activity

    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    payload = activity(work)
    receipt = await execute(case, mission, command("RECORD_ACTIVITY", payload, revision))
    assert receipt["disposition"] == "APPLIED"
    statement = "SELECT work_id,epoch,ownership_fence,execution_ref,occurred_at,fresh_until,provenance FROM research_activity_receipts WHERE work_id=? AND occurred_at=?"
    params = (str(work.work_id), payload["occurred_at"])
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as connection:
            row = connection.execute(statement.replace("?", "%s"), params).fetchone()
    else:
        connection = case.repository._get_connection()
        try:
            row = connection.execute(statement, params).fetchone()
        finally:
            if case.repository._mem_conn is None:
                connection.close()
    assert row is not None
    occurred = row[4] if isinstance(row[4], datetime) else datetime.fromisoformat(row[4])
    fresh = row[5] if isinstance(row[5], datetime) else datetime.fromisoformat(row[5])
    actual = ResearchActivityReceipt(
        work_id=UUID(str(row[0])),
        epoch=row[1],
        ownership_fence=row[2],
        execution_ref=row[3],
        occurred_at=occurred,
        fresh_until=fresh,
        provenance=row[6],
    )
    assert actual.work_id == work.work_id and actual.epoch == 1
    assert actual.ownership_fence == work.ownership_fence and actual.provenance == "HOST_REPORTED"
    assert occurred.isoformat() == payload["occurred_at"] and fresh.isoformat() == payload["fresh_until"]
    snapshot = await case.repository.load_research_work(mission.id)
    current = snapshot.work_items[0]
    assert project_work_activity(work=current, receipt=actual, now=occurred).state == "ACTIVE"
    assert project_work_activity(work=current, receipt=actual, now=fresh).state == "STALE"
    assert project_work_activity(work=current, receipt=None, now=occurred).state == "UNKNOWN"
    before = _state(case)
    await refused(
        case,
        mission,
        command("RECORD_ACTIVITY", payload, revision, key="obsolete-version"),
        "STALE_REVISION",
    )
    assert _state(case)[1]["research_activity_receipts"] == before[1]["research_activity_receipts"]


@pytest.mark.asyncio
async def test_bad_reason_control_rejects_generic_refusal(relay_case, tmp_path):
    """A real terminal refusal cannot satisfy an unrelated exact epoch assertion."""
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    _, ended = await end_research(case, mission, revision)
    body = command("RECORD_ACTIVITY", activity(work), ended["revision"])
    with pytest.raises(AssertionError):
        await refused(case, mission, body, "STALE_EPOCH")
    actual = await execute(case, mission, body)
    assert actual["disposition"] == "REFUSED" and actual["reason_code"] == "ASSIGNMENT_TERMINAL"
