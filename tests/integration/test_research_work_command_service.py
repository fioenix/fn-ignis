"""Actual command service admission and original receipt replay on physical stores."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from tests.integration.test_mission_relay_read_boundary import relay_case as _relay_case, _state
from tests.integration.test_research_work_persistence import _arrange, _sql
from tests.unit.test_record_mission_research_work import assignment_command
from ignis.application.use_cases.record_mission_research_work import RecordMissionResearchWorkUseCase


relay_case = _relay_case


def command(operation, payload, revision, key=None):
    return {
        "operation": operation,
        "payload": payload,
        "expected_revision": revision,
        "expected_epoch": 1,
        "idempotency_key": key or uuid4().hex,
    }


async def execute(case, mission, body, *, authorized=True):
    return await RecordMissionResearchWorkUseCase(case.repository).execute(
        str(mission.id), body, host_authorized=authorized
    )


@pytest.mark.asyncio
async def test_public_handoff_ack_roundtrip_and_original_retry_after_terminal(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    payload = handoff.to_payload()
    del payload["recorded_at"]
    for finding in payload["findings"]:
        del finding["recorded_at"]
    body = command("SUBMIT_HANDOFF", payload, revision)
    first = await execute(case, mission, body)
    assert first["disposition"] == "APPLIED"
    assert first["handoff_id"] == str(handoff.handoff_id)
    assert first["work_id"] == str(work.work_id)
    assert set(first) == {
        "disposition",
        "reason_code",
        "revision",
        "work_version",
        "assignment_version",
        "receipt_id",
        "event_ids",
        "recorded_at",
        "assignment_id",
        "work_id",
        "handoff_id",
    }
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,)
    assert snapshot.findings == handoff.findings
    ack = command(
        "ACK_HANDOFF",
        {
            "handoff_id": str(handoff.handoff_id),
            "consumer_ref": handoff.consumer_ref,
            "expected_version": first["work_version"],
            "disposition": "ACCEPTED",
            "reason_code": None,
            "inputs": work.inputs.to_payload(),
        },
        first["revision"],
    )
    accepted = await execute(case, mission, ack)
    assert accepted["disposition"] == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].state == "COMPLETED"
    before = _state(case)
    assert await execute(case, mission, deepcopy(body)) == first
    assert _state(case) == before
    changed = deepcopy(body)
    changed["payload"]["result"] = "Different safe submitted result"
    conflict = await execute(case, mission, changed)
    assert conflict["reason_code"] == "IDEMPOTENCY_CONFLICT"
    assert _state(case) == before


@pytest.mark.asyncio
async def test_stable_public_assignment_replays_after_newer_frame_and_assignment_end(relay_case, tmp_path):
    case, mission, _, persistence, work, _, revision = await _arrange(relay_case, tmp_path)
    from tests.integration.test_research_work_persistence import _commit
    from ignis.domain.research_work import EndResearchPayload

    ended = await _commit(
        case.repository,
        persistence,
        mission,
        "END_RESEARCH",
        EndResearchPayload(
            assignment_id=work.assignment_id, expected_version=2, disposition="COMPLETED", reason="INVALID_INPUT"
        ),
        revision=revision,
    )
    assert ended.disposition == "APPLIED"
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    body = assignment_command()
    body["expected_revision"] = ended.revision
    body["expected_epoch"] = 2
    body["payload"]["expected_manifest_digest"] = evidence.manifest.manifest_digest
    body["payload"]["expected_brief_revision_id"] = str(evidence.brief.brief_revision_id)
    body["payload"]["authority"]["deadline"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    first = await execute(case, mission, body)
    assert first["disposition"] == "APPLIED"
    assert first["assignment_id"] == body["payload"]["assignment_id"]
    terminal = command(
        "END_RESEARCH",
        {
            "assignment_id": first["assignment_id"],
            "expected_version": 1,
            "disposition": "FAILED",
            "reason": "INVALID_INPUT",
        },
        first["revision"],
    )
    terminal["expected_epoch"] = 2
    assert (await execute(case, mission, terminal))["disposition"] == "APPLIED"
    # Canonical membership changes after both retained admission and termination.
    await _sql(
        case,
        "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?",
        (str(mission.id), str(work.inputs.observation_ids[0])),
    )
    before = _state(case)
    assert await execute(case, mission, deepcopy(body)) == first
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control,reason",
    [
        ("host", "UNAUTHORIZED_HOST"),
        ("scope", "SCOPE_MISMATCH"),
        ("frame", "STALE_INPUT_FRAME"),
        ("authority", "AUTHORITY_WIDENING"),
        ("revision", "STALE_REVISION"),
    ],
)
async def test_service_uses_held_backend_admission(relay_case, tmp_path, control, reason):
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    payload = {
        "assignment_id": str(work.assignment_id),
        "work_id": str(uuid4()),
        "question": "Bounded question",
        "expertise": "Synthesis",
        "assignee_ref": None,
        "inputs": work.inputs.to_payload(),
        "dependencies": [],
        "ownership_fence": "new-fence",
    }
    body = command("ASSIGN_WORK", payload, revision)
    if control == "scope":
        payload["assignment_id"] = str(uuid4())
    elif control == "frame":
        payload["inputs"]["frame_digest"] = "b" * 64
    elif control == "revision":
        body["expected_revision"] -= 1
    elif control == "authority":
        body = assignment_command()
        body["expected_revision"] = revision
        body["expected_epoch"] = 2
        evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
        body["payload"]["expected_manifest_digest"] = evidence.manifest.manifest_digest
        body["payload"]["expected_brief_revision_id"] = str(evidence.brief.brief_revision_id)
        body["payload"]["authority"]["actions"] = ["COLLECT"]
    before = _state(case)
    result = await execute(case, mission, body, authorized=control != "host")
    assert result["disposition"] == "REFUSED" and result["reason_code"] == reason
    after = _state(case)
    assert after[0] == before[0]
    for table in before[1]:
        if table != "research_work_commands":
            assert after[1][table] == before[1][table]
    assert len(after[1]["research_work_commands"]) == len(before[1]["research_work_commands"]) + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["private", "reason", "observations", "recorded_at"])
async def test_invalid_public_body_never_reaches_storage_or_echoes_private_text(relay_case, tmp_path, control):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    if control == "reason":
        body = command(
            "WAIT_WORK",
            {
                "work_id": str(work.work_id),
                "expected_version": work.version,
                "ownership_fence": work.ownership_fence,
                "reason": "private-marker",
            },
            revision,
        )
    else:
        payload = handoff.to_payload()
        del payload["recorded_at"]
        for finding in payload["findings"]:
            del finding["recorded_at"]
        if control == "private":
            payload["findings"][0]["transcript"] = "private-marker"
        elif control == "recorded_at":
            payload["recorded_at"] = "private-marker"
        else:
            payload["inputs"]["observation_ids"][0] = True
        body = command("SUBMIT_HANDOFF", payload, revision)
    before = _state(case)
    result = await execute(case, mission, body)
    assert result["disposition"] == "REFUSED"
    assert result["reason_code"] == ("INVALID_REASON_CODE" if control == "reason" else "INVALID_COMMAND")
    assert result["receipt_id"] is None
    assert "private-marker" not in str(result)
    assert _state(case) == before


@pytest.mark.asyncio
async def test_public_assign_start_wait_resume_activity_records_only_actual_transitions(relay_case, tmp_path):
    case, mission, _, _, template, _, revision = await _arrange(relay_case, tmp_path)
    identity = str(uuid4())
    payload = {
        "assignment_id": str(template.assignment_id),
        "work_id": identity,
        "question": "Contact person@example.com",
        "expertise": "Synthesis",
        "assignee_ref": "synthetic-worker",
        "inputs": template.inputs.to_payload(),
        "dependencies": [],
        "ownership_fence": "new-fence",
    }
    assigned = await execute(case, mission, command("ASSIGN_WORK", payload, revision))
    assert assigned["disposition"] == "APPLIED" and assigned["work_id"] == identity
    snapshot = await case.repository.load_research_work(mission.id)
    work = next(w for w in snapshot.work_items if str(w.work_id) == identity)
    assert work.state == "ASSIGNED"
    assert "person@example.com" not in work.question
    assert [e.kind for e in snapshot.events if e.cursor.revision == assigned["revision"]] == ["WORK_ASSIGNED"]
    now = datetime.now(timezone.utc)
    activity = {
        "work_id": identity,
        "expected_version": 1,
        "ownership_fence": "new-fence",
        "execution_ref": "synthetic-new-execution",
        "occurred_at": now.isoformat(),
        "fresh_until": (now + timedelta(hours=1)).isoformat(),
    }
    started = await execute(case, mission, command("START_WORK", activity, assigned["revision"]))
    assert started["disposition"] == "APPLIED"
    last = started
    for operation, version, kind in [("WAIT_WORK", 2, "WORK_WAITING"), ("RESUME_WORK", 3, "WORK_RESUMED")]:
        last = await execute(
            case,
            mission,
            command(
                operation,
                {
                    "work_id": identity,
                    "expected_version": version,
                    "ownership_fence": "new-fence",
                    "reason": "DEPENDENCY_NOT_READY",
                },
                last["revision"],
            ),
        )
        assert last["disposition"] == "APPLIED"
        snapshot = await case.repository.load_research_work(mission.id)
        assert [e.kind for e in snapshot.events if e.cursor.revision == last["revision"]] == [kind]
    heartbeat = {**activity, "expected_version": 4}
    recorded = await execute(case, mission, command("RECORD_ACTIVITY", heartbeat, last["revision"]))
    assert recorded["disposition"] == "APPLIED" and recorded["work_version"] == 5
    before = _state(case)
    stale = await execute(case, mission, command("RECORD_ACTIVITY", heartbeat, last["revision"], key="changed-key"))
    assert stale["disposition"] == "REFUSED" and stale["reason_code"] == "STALE_REVISION"
    assert len((await case.repository.load_research_work(mission.id)).work_items) == 2
    assert _state(case)[1]["research_activity_receipts"] == before[1]["research_activity_receipts"]


@pytest.mark.asyncio
async def test_service_performs_no_unlocked_read_before_actual_admission(relay_case, tmp_path, monkeypatch):
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Unlocked service pre-read would admit stale authority.")

    monkeypatch.setattr(case.repository, "load_research_work", forbidden)
    monkeypatch.setattr(case.repository, "load_mission_evidence_snapshot", forbidden)
    body = command(
        "WAIT_WORK",
        {
            "work_id": str(work.work_id),
            "expected_version": work.version,
            "ownership_fence": work.ownership_fence,
            "reason": "DEPENDENCY_NOT_READY",
        },
        revision,
    )
    result = await execute(case, mission, body)
    assert result["disposition"] == "APPLIED" and result["work_version"] == work.version + 1
    assert await execute(case, mission, body) == result


@pytest.mark.asyncio
async def test_actual_late_storage_failure_is_ephemeral_and_original_retry_can_apply(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    if case.name == "postgres":
        await _sql(
            case,
            "CREATE FUNCTION t051_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'private-marker'; END $$",
        )
        await _sql(
            case,
            "CREATE TRIGGER t051_abort BEFORE INSERT ON research_work_commands FOR EACH ROW EXECUTE FUNCTION t051_abort()",
        )
    else:
        await _sql(
            case,
            "CREATE TRIGGER t051_abort BEFORE INSERT ON research_work_commands BEGIN SELECT RAISE(ABORT, 'private-marker'); END",
        )
    payload = handoff.to_payload()
    del payload["recorded_at"]
    for finding in payload["findings"]:
        del finding["recorded_at"]
    body = command("SUBMIT_HANDOFF", payload, revision)
    before = _state(case)
    failed = await execute(case, mission, body)
    assert failed["disposition"] == "REFUSED" and failed["reason_code"] == "STORAGE_FAILURE"
    assert failed["receipt_id"] is None and failed["revision"] is None and failed["event_ids"] == []
    assert "private-marker" not in str(failed)
    assert _state(case) == before
    await _sql(
        case,
        "DROP TRIGGER t051_abort ON research_work_commands" if case.name == "postgres" else "DROP TRIGGER t051_abort",
    )
    result = await execute(case, mission, body)
    assert result["disposition"] == "APPLIED" and result["work_version"] == work.version + 1
    before = _state(case)
    assert await execute(case, mission, body) == result
    assert _state(case) == before
