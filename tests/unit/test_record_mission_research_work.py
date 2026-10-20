"""Public command bridge controls; recording never confers execution authority."""

from copy import deepcopy
from uuid import UUID

import pytest

from ignis.application.use_cases.record_mission_research_work import parse_recording_command

MISSION = "30000000-0000-0000-0000-000000000001"
ASSIGNMENT = "10000000-0000-0000-0000-000000000001"
BRIEF = "20000000-0000-0000-0000-000000000001"


def assignment_command():
    return {
        "operation": "ASSIGN_RESEARCH",
        "idempotency_key": "stable-request",
        "expected_revision": 0,
        "expected_epoch": 1,
        "payload": {
            "assignment_id": ASSIGNMENT,
            "expected_manifest_digest": "a" * 64,
            "expected_brief_revision_id": BRIEF,
            "host_task_ref": "synthetic-host",
            "capability": "SEQUENTIAL",
            "authority": {
                "actions": ["ANALYZE"],
                "sources": ["youtube"],
                "deadline": "2027-01-01T00:00:00+00:00",
                "quota_ceiling": 0,
            },
        },
    }


def test_stable_assignment_binding_and_retry_fingerprint():
    body = assignment_command()
    first = parse_recording_command(MISSION, body, host_authorized=True)
    retry = parse_recording_command(MISSION, deepcopy(body), host_authorized=True)
    assert first == retry
    assert first.payload.assignment.assignment_id == UUID(ASSIGNMENT)
    assert first.payload.expected_manifest_digest == "a" * 64
    assert first.payload.expected_brief_revision_id == UUID(BRIEF)
    assert first.payload.assignment.state == "ASSIGNED"
    assert first.payload.assignment.version == 1
    assert first.fingerprint == retry.fingerprint


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "private",
        "bool_revision",
        "bool_epoch",
        "bool_quota",
        "huge_revision",
        "uuid_type",
        "bad_uuid",
        "naive_time",
        "time_type",
        "duplicate_sources",
        "too_many_sources",
        "source_type",
        "too_long_key",
        "too_long_ref",
        "provenance",
        "state",
    ],
)
def test_invalid_nested_or_primitive_body_never_forms_a_recording_command(mutation):
    body = assignment_command()
    payload, authority = body["payload"], body["payload"]["authority"]
    if mutation == "extra":
        body["host_authorized"] = True
    elif mutation == "private":
        authority["transcript"] = "private-marker"
    elif mutation == "bool_revision":
        body["expected_revision"] = True
    elif mutation == "bool_epoch":
        body["expected_epoch"] = True
    elif mutation == "bool_quota":
        authority["quota_ceiling"] = True
    elif mutation == "huge_revision":
        body["expected_revision"] = 2**63
    elif mutation == "uuid_type":
        payload["assignment_id"] = UUID(ASSIGNMENT)
    elif mutation == "bad_uuid":
        payload["assignment_id"] = "private-marker"
    elif mutation == "naive_time":
        authority["deadline"] = "2027-01-01T00:00:00"
    elif mutation == "time_type":
        authority["deadline"] = 1
    elif mutation == "duplicate_sources":
        authority["sources"] *= 2
    elif mutation == "too_many_sources":
        authority["sources"] = ["source" + str(i) for i in range(101)]
    elif mutation == "source_type":
        authority["sources"] = [True]
    elif mutation == "too_long_key":
        body["idempotency_key"] = "x" * 257
    elif mutation == "too_long_ref":
        payload["host_task_ref"] = "x" * 513
    else:
        payload[mutation] = "HARNESS_OBSERVED" if mutation == "provenance" else "RUNNING"
    with pytest.raises(ValueError, match="Invalid recording command"):
        parse_recording_command(MISSION, body, host_authorized=True)


def test_public_json_does_not_authorize_host_and_unknown_capability_stays_unknown():
    body = assignment_command()
    body["payload"]["capability"] = None
    command = parse_recording_command(MISSION, body, host_authorized=False)
    assert command.host_authorized is False
    assert command.payload.assignment.capability is None
    with pytest.raises(ValueError):
        parse_recording_command(MISSION, body, host_authorized=1)


def inputs():
    return {
        "mission_id": MISSION,
        "manifest_digest": "a" * 64,
        "brief_digest": None,
        "frame_digest": None,
        "observation_ids": [],
        "finding_revisions": [],
    }


def operation_command(operation):
    work = {"work_id": ASSIGNMENT, "expected_version": 1, "ownership_fence": "fence"}
    if operation in ("START_WORK", "RECORD_ACTIVITY"):
        payload = {
            **work,
            "execution_ref": "execution",
            "occurred_at": "2026-10-06T00:00:00+00:00",
            "fresh_until": "2026-10-07T00:00:00+00:00",
        }
    elif operation == "ASSIGN_WORK":
        payload = {
            "assignment_id": ASSIGNMENT,
            "work_id": BRIEF,
            "question": "Bounded question",
            "expertise": "Synthesis",
            "assignee_ref": None,
            "inputs": inputs(),
            "dependencies": [],
            "ownership_fence": "fence",
        }
    elif operation == "END_RESEARCH":
        payload = {
            "assignment_id": ASSIGNMENT,
            "expected_version": 1,
            "disposition": "FAILED",
            "reason": "INVALID_INPUT",
        }
    elif operation == "END_WORK":
        payload = {**work, "disposition": "FAILED", "reason": "INVALID_INPUT"}
    elif operation == "ACK_STOP":
        payload = {**work, "execution_ref": "execution", "reason": "INVALID_INPUT"}
    elif operation == "ACK_HANDOFF":
        payload = {
            "handoff_id": BRIEF,
            "consumer_ref": "consumer",
            "expected_version": 1,
            "disposition": "REJECTED",
            "reason_code": "INVALID_INPUT",
            "inputs": inputs(),
        }
    elif operation == "SUBMIT_HANDOFF":
        finding = {
            "finding_id": MISSION,
            "revision": 1,
            "predecessor_revision": None,
            "work_id": ASSIGNMENT,
            "handoff_id": BRIEF,
            "inputs": inputs(),
            "result_type": "DESCRIPTIVE",
            "statement": "Bounded result",
            "limitations": [],
            "open_questions": [],
            "supporting_observation_ids": [],
            "contradicting_observation_ids": [],
            "context_observation_ids": [],
            "alternative_explanation": None,
            "claim_id": None,
        }
        payload = {
            "handoff_id": BRIEF,
            **work,
            "consumer_ref": "consumer",
            "inputs": inputs(),
            "observation_sources": [],
            "outcome_ids": [],
            "claim_ids": [],
            "result": "Bounded result",
            "limitations": [],
            "open_questions": [],
            "findings": [finding],
            "occurred_at": None,
        }
    else:
        payload = {**work, "reason": "INVALID_INPUT"}
    return {
        "operation": operation,
        "idempotency_key": "key",
        "expected_revision": 0,
        "expected_epoch": 1,
        "payload": payload,
    }


@pytest.mark.parametrize(
    "operation",
    [
        "ASSIGN_WORK",
        "START_WORK",
        "RECORD_ACTIVITY",
        "WAIT_WORK",
        "RESUME_WORK",
        "REQUEST_CANCEL",
        "ACK_STOP",
        "END_WORK",
        "END_RESEARCH",
        "SUBMIT_HANDOFF",
        "ACK_HANDOFF",
    ],
)
def test_every_supported_operation_preserves_exact_typed_body(operation):
    body = operation_command(operation)
    result = parse_recording_command(MISSION, body, host_authorized=True)
    assert result.operation == operation
    assert result.expected_revision == 0 and result.expected_epoch == 1
    if operation == "ASSIGN_WORK":
        assert result.payload.run_id is None and result.payload.assignee_ref is None
        assert result.payload.state == "ASSIGNED" and result.payload.version == 1
    elif operation in ("START_WORK", "RECORD_ACTIVITY"):
        assert result.payload.receipt.provenance == "HOST_REPORTED"
    elif operation == "SUBMIT_HANDOFF":
        assert result.payload.recorded_at is None
        assert result.payload.findings[0].recorded_at is None


@pytest.mark.parametrize(
    "mutation",
    [
        "extra_input",
        "bool_observation",
        "extra_source",
        "source_identity_type",
        "extra_finding",
        "finding_revision_bool",
        "finding_revision_overflow",
        "recorded_finding_time",
        "bad_occurrence",
        "bool_claim",
        "bad_predecessor",
        "too_many_findings",
        "too_many_limitations",
    ],
)
def test_handoff_nested_shape_types_and_metadata_are_strict(mutation):
    body = operation_command("SUBMIT_HANDOFF")
    p, f = body["payload"], body["payload"]["findings"][0]
    if mutation == "extra_input":
        p["inputs"]["raw"] = "private-marker"
    elif mutation == "bool_observation":
        p["inputs"]["observation_ids"] = [True]
    elif mutation == "extra_source":
        p["observation_sources"] = [{"observation_id": BRIEF, "source_id": ASSIGNMENT, "raw": "private-marker"}]
    elif mutation == "source_identity_type":
        p["observation_sources"] = [{"observation_id": BRIEF, "source_id": True}]
    elif mutation == "extra_finding":
        f["hidden_reasoning"] = "private-marker"
    elif mutation == "finding_revision_bool":
        f["revision"] = True
    elif mutation == "finding_revision_overflow":
        f["revision"] = 2**63
    elif mutation == "recorded_finding_time":
        f["recorded_at"] = None
    elif mutation == "bad_occurrence":
        p["occurred_at"] = "2026-10-06"
    elif mutation == "bool_claim":
        f["claim_id"] = True
    elif mutation == "bad_predecessor":
        f["predecessor_revision"] = 1
    elif mutation == "too_many_findings":
        p["findings"] = [f] * 1001
    else:
        p["limitations"] = ["limit"] * 101
    with pytest.raises(ValueError, match="Invalid recording command"):
        parse_recording_command(MISSION, body, host_authorized=True)


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_primitive",
        "cycle",
        "oversized_utf8",
        "nested_depth",
        "invalid_mission",
        "unsupported",
        "unsafe_reason",
        "unsafe_ack_reason",
        "too_many_dependencies",
    ],
)
def test_request_global_bounds_and_safe_reason_codes(mutation):
    body = operation_command("SUBMIT_HANDOFF")
    if mutation == "foreign_primitive":
        body["payload"]["result"] = b"private-marker"
    elif mutation == "cycle":
        body["payload"]["findings"].append(body)
    elif mutation == "oversized_utf8":
        finding = body["payload"]["findings"][0]
        finding["statement"] = "\u754c" * 4096
        body["payload"]["findings"] = [deepcopy(finding) for _ in range(100)]
    elif mutation == "nested_depth":
        value = "private-marker"
        for _ in range(14):
            value = {"x": value}
        body["payload"]["unknown"] = value
    elif mutation == "unsupported":
        body["operation"] = "INVOKE_PROVIDER"
    elif mutation == "unsafe_reason":
        body = operation_command("WAIT_WORK")
        body["payload"]["reason"] = "private-marker"
    elif mutation == "unsafe_ack_reason":
        body = operation_command("ACK_HANDOFF")
        body["payload"]["reason_code"] = "private-marker"
    elif mutation == "too_many_dependencies":
        body = operation_command("ASSIGN_WORK")
        body["payload"]["dependencies"] = [BRIEF] * 1001
    with pytest.raises(ValueError):
        parse_recording_command(
            "private-marker" if mutation == "invalid_mission" else MISSION, body, host_authorized=True
        )


@pytest.mark.asyncio
async def test_unexpected_storage_exception_is_ephemeral_safe_refusal():
    from ignis.application.use_cases.record_mission_research_work import RecordMissionResearchWorkUseCase

    class FailingStore:
        async def commit_research_work(self, command):
            raise RuntimeError("private-marker")

    result = await RecordMissionResearchWorkUseCase(FailingStore()).execute(
        MISSION, assignment_command(), host_authorized=True
    )
    assert result["disposition"] == "REFUSED" and result["reason_code"] == "STORAGE_FAILURE"
    assert result["receipt_id"] is None and result["revision"] is None and result["event_ids"] == []
    assert "private-marker" not in str(result)


def test_binding_and_dependency_order_is_not_sorted_or_recaptured():
    body = operation_command("ASSIGN_WORK")
    body["payload"]["inputs"]["observation_ids"] = [BRIEF, ASSIGNMENT]
    body["payload"]["inputs"]["finding_revisions"] = [
        {"finding_id": BRIEF, "revision": 2},
        {"finding_id": ASSIGNMENT, "revision": 3},
    ]
    body["payload"]["dependencies"] = [MISSION, ASSIGNMENT]
    result = parse_recording_command(MISSION, body, host_authorized=True)
    assert result.payload.inputs.observation_ids == (UUID(BRIEF), UUID(ASSIGNMENT))
    assert result.payload.inputs.finding_revisions == ((UUID(BRIEF), 2), (UUID(ASSIGNMENT), 3))
    assert result.payload.dependencies == (UUID(MISSION), UUID(ASSIGNMENT))
