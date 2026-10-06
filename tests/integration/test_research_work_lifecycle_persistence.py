"""T047 physical SQLite lifecycle controls; accepted result tests remain T049."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.integration.test_mission_relay_read_boundary import NOW, _state, relay_case as canonical_relay_case

from tests.integration.test_research_work_persistence import _arrange, _commit, _sql

relay_case = canonical_relay_case


async def _ready(relay_case, tmp_path):
    return await _arrange(relay_case, tmp_path)


@pytest.mark.asyncio
async def test_core_exact_binding_events_metadata_and_retry(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.current_epoch == 1 and snapshot.revision == revision
    assert snapshot.work_items == (work,)
    assert {e.kind.value for e in snapshot.events if e.work_id == work.work_id} == {"WORK_ASSIGNED", "WORK_STARTED"}
    assert len(snapshot.recorded_metadata) == 4
    assert all(m.provenance == "HARNESS_OBSERVED" for m in snapshot.recorded_metadata)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    receipt = await _commit(
        case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision, key="original-work"
    )
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="ASSIGN_WORK",
        payload=assigned,
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="original-work",
        host_authorized=True,
    )
    before = _state(case)
    assert await case.repository.commit_research_work(command) == receipt
    assert _state(case) == before
    conflict = await case.repository.commit_research_work(
        replace(command, payload=replace(assigned, question="changed"))
    )
    assert conflict.reason_code == "IDEMPOTENCY_CONFLICT" and not conflict.event_ids
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control,reason",
    [
        ("revision", "STALE_REVISION"),
        ("version", "STALE_VERSION"),
        ("epoch", "STALE_EPOCH"),
        ("fence", "STALE_FENCE"),
        ("host", "UNAUTHORIZED_HOST"),
        ("identity", "INPUT_IDENTITY_MISMATCH"),
        ("frame", "STALE_INPUT_FRAME"),
    ],
)
async def test_refusal_original_receipt_without_body_or_fake_event(relay_case, tmp_path, control, reason):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    if control in {"identity", "frame"}:
        inputs = (
            replace(work.inputs, observation_ids=(uuid4(),))
            if control == "identity"
            else replace(work.inputs, frame_digest="0" * 64)
        )
        payload = replace(
            work,
            work_id=uuid4(),
            inputs=inputs,
            question="REJECTED_SENTINEL password=unsafe",
            state="ASSIGNED",
            version=1,
        )
        operation = "ASSIGN_WORK"
    else:
        activity = domain.ResearchActivityReceipt(
            work_id=work.work_id,
            epoch=1,
            ownership_fence=work.ownership_fence,
            execution_ref="REJECTED_SENTINEL password=unsafe",
            occurred_at=NOW,
            fresh_until=NOW + timedelta(days=300),
            provenance="HOST_REPORTED",
        )
        payload = port.ResearchWorkStartAdmission(
            work_id=work.work_id, expected_version=work.version, ownership_fence=work.ownership_fence, receipt=activity
        )
        if control == "version":
            payload = replace(payload, expected_version=0)
        if control == "fence":
            payload = replace(payload, ownership_fence="wrong", receipt=replace(activity, ownership_fence="wrong"))
        operation = "RECORD_ACTIVITY"
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation=operation,
        payload=payload,
        expected_revision=revision - 1 if control == "revision" else revision,
        expected_epoch=2 if control == "epoch" else 1,
        idempotency_key="rejected",
        host_authorized=control != "host",
    )
    before = await case.repository.load_research_work(mission.id)
    result = await case.repository.commit_research_work(command)
    assert result.reason_code == reason and result.disposition == "REFUSED" and not result.event_ids
    assert await case.repository.load_research_work(mission.id) == before
    state = _state(case)
    assert "REJECTED_SENTINEL" not in repr(state) and "unsafe" not in repr(state)
    assert await case.repository.commit_research_work(command) == result
    assert _state(case) == state


@pytest.mark.asyncio
async def test_real_start_contention_one_cas_winner(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    receipt = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    activity = domain.ResearchActivityReceipt(
        work_id=assigned.work_id,
        epoch=1,
        ownership_fence=assigned.ownership_fence,
        execution_ref="execution",
        occurred_at=NOW,
        fresh_until=NOW + timedelta(days=300),
        provenance="HOST_REPORTED",
    )
    payload = port.ResearchWorkStartAdmission(
        work_id=assigned.work_id, expected_version=1, ownership_fence=assigned.ownership_fence, receipt=activity
    )
    repository = case.repository
    if repository._mem_conn is None:
        from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

        contender = SqliteTrendRepository(repository._db_path)
        contender._initialized = True
    else:
        contender = repository
    results = await asyncio.gather(
        *[
            r.commit_research_work(
                port.ResearchWorkCommitCommand(
                    mission_id=mission.id,
                    operation="START_WORK",
                    payload=payload,
                    expected_revision=receipt.revision,
                    expected_epoch=1,
                    idempotency_key=f"race-{index}",
                    host_authorized=True,
                )
            )
            for index, r in enumerate((repository, contender))
        ]
    )
    assert sorted(r.disposition for r in results) == ["APPLIED", "REFUSED"]
    assert next(r for r in results if r.disposition == "REFUSED").reason_code == "STALE_REVISION"
    snapshot = await repository.load_research_work(mission.id)
    assert next(w for w in snapshot.work_items if w.work_id == assigned.work_id).version == 2
    assert len([e for e in snapshot.events if e.work_id == assigned.work_id and e.kind.value == "WORK_STARTED"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault_table", ["mission_progress_events", "research_recorded_metadata", "research_work_commands"]
)
async def test_late_progress_failure_rolls_back_all_core_effects(relay_case, tmp_path, fault_table):
    case, mission, _, port, work, _, revision = await _ready(relay_case, tmp_path)
    await _sql(
        case, f"CREATE TRIGGER t047_fault BEFORE INSERT ON {fault_table} BEGIN SELECT RAISE(ABORT,'T047 fault'); END"
    )
    before = _state(case)
    result = await _commit(
        case.repository,
        port,
        mission,
        "ASSIGN_WORK",
        replace(work, work_id=uuid4(), state="ASSIGNED", version=1),
        revision=revision,
    )
    assert result.reason_code == "STORAGE_FAILURE" and result.revision == revision and not result.event_ids
    assert _state(case) == before


@pytest.mark.asyncio
async def test_input_seal_source_identity_pruning_and_root_cascade(relay_case, tmp_path):
    case, mission, _, _, work, _, _ = await _ready(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    # Physical SQL mutations test actual guards; the adapter is not the guard substitute.
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(case, "UPDATE research_work_items SET question=? WHERE work_id=?", ("changed", work.work_id))
    with pytest.raises(sqlite3.IntegrityError, match="deleted"):
        await _sql(case, "DELETE FROM research_work_items WHERE work_id=?", (work.work_id,))
    with pytest.raises(sqlite3.IntegrityError):
        await _sql(
            case,
            "UPDATE observations SET source_id=? WHERE id=?",
            (snapshot.observation_sources[1][1], snapshot.observation_sources[0][0]),
        )
    await case.repository.delete_mission_signals(mission.id)
    pruned = await case.repository.load_research_work(mission.id)
    assert pruned.work_items == snapshot.work_items and not pruned.observation_sources
    counts = {name: len(_state(case)[1][name]) for name in ("sources", "observations")}
    await _sql(case, "DELETE FROM research_missions WHERE id=?", (mission.id,))
    assert all(
        not rows
        for name, rows in _state(case)[1].items()
        if name.startswith("research_") and name not in {"research_missions", "research_workspaces"}
    )
    assert {name: len(_state(case)[1][name]) for name in counts} == counts


@pytest.mark.asyncio
async def test_epoch_next_only_terminal_replay_and_bound_old_closure(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    assignment = snapshot.assignments[0]
    end = domain.EndResearchPayload(
        assignment_id=assignment.assignment_id,
        expected_version=assignment.version,
        disposition="INTERRUPTED",
        reason="Bounded task ended",
    )
    ended = await _commit(case.repository, port, mission, "END_RESEARCH", end, revision=revision)
    assert ended.disposition == "APPLIED"

    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    admission = port.ResearchAssignmentAdmission(
        assignment=replace(assignment, assignment_id=uuid4(), epoch=3, state="ASSIGNED", version=1),
        expected_manifest_digest=work.inputs.manifest_digest,
        expected_brief_revision_id=evidence.brief.brief_revision_id,
    )
    refused = await _commit(
        case.repository, port, mission, "ASSIGN_RESEARCH", admission, revision=ended.revision, epoch=3
    )
    assert refused.reason_code == "STALE_EPOCH"
    admission = replace(admission, assignment=replace(admission.assignment, epoch=2))
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="ASSIGN_RESEARCH",
        payload=admission,
        expected_revision=ended.revision,
        expected_epoch=2,
        idempotency_key="epoch-two",
        host_authorized=True,
    )
    second = await case.repository.commit_research_work(command)
    assert second.disposition == "APPLIED"
    # Bound cessation of the first host execution cannot renew its old assignment.
    cancel = domain.ReasonWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        reason="Old execution",
    )
    start_refused = await _commit(
        case.repository, port, mission, "RESUME_WORK", cancel, revision=second.revision, epoch=1
    )
    assert start_refused.reason_code == "STALE_EPOCH"
    close = domain.EndWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        disposition="INTERRUPTED",
        reason="Host stopped",
    )
    closed = await _commit(case.repository, port, mission, "END_WORK", close, revision=second.revision, epoch=1)
    assert closed.disposition == "APPLIED"
    before = _state(case)
    assert await case.repository.commit_research_work(command) == second
    assert _state(case) == before
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.assignments[0].state == "INTERRUPTED" and snapshot.work_items[0].state == "INTERRUPTED"
    assert snapshot.current_epoch == 2


@pytest.mark.asyncio
async def test_expired_and_widened_assignment_do_not_persist_body(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    a = snapshot.assignments[0]
    ended = await _commit(
        case.repository,
        port,
        mission,
        "END_RESEARCH",
        domain.EndResearchPayload(
            assignment_id=a.assignment_id, expected_version=a.version, disposition="FAILED", reason="Finished"
        ),
        revision=revision,
    )
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    for authority, reason in [
        (replace(a.authority, deadline=NOW), "AUTHORITY_EXPIRED"),
        (replace(a.authority, sources=frozenset({"foreign"})), "AUTHORITY_WIDENING"),
        (replace(a.authority, quota_ceiling=999999), "AUTHORITY_WIDENING"),
    ]:
        admission = port.ResearchAssignmentAdmission(
            assignment=replace(
                a,
                assignment_id=uuid4(),
                epoch=2,
                state="ASSIGNED",
                version=1,
                host_task_ref="REJECTED_AUTH_SENTINEL",
                authority=authority,
            ),
            expected_manifest_digest=work.inputs.manifest_digest,
            expected_brief_revision_id=evidence.brief.brief_revision_id,
        )
        result = await _commit(
            case.repository, port, mission, "ASSIGN_RESEARCH", admission, revision=ended.revision, epoch=2
        )
        assert result.reason_code == reason
        assert "REJECTED_AUTH_SENTINEL" not in repr(_state(case))


@pytest.mark.asyncio
async def test_mask_accepted_text_and_refuse_unsafe_exact_execution_identity(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    assigned = replace(
        work,
        work_id=uuid4(),
        version=1,
        state="ASSIGNED",
        question="Contact person@example.com password=unsafe",
        expertise="Call 0931405002",
    )
    saved = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    assert saved.disposition == "APPLIED"
    loaded = await case.repository.load_research_work(mission.id)
    actual = next(w for w in loaded.work_items if w.work_id == assigned.work_id)
    assert (
        "[REDACTED_EMAIL]" in actual.question
        and "[REDACTED_SECRET]" in actual.question
        and "[REDACTED_PHONE]" in actual.expertise
    )
    assert "person@example.com" not in repr(_state(case)) and "unsafe" not in repr(_state(case))
    activity = domain.ResearchActivityReceipt(
        work_id=assigned.work_id,
        epoch=1,
        ownership_fence=assigned.ownership_fence,
        execution_ref="password=execution-secret",
        occurred_at=NOW,
        fresh_until=NOW + timedelta(days=300),
        provenance="HOST_REPORTED",
    )
    admission = port.ResearchWorkStartAdmission(
        work_id=assigned.work_id, expected_version=1, ownership_fence=assigned.ownership_fence, receipt=activity
    )
    result = await _commit(case.repository, port, mission, "START_WORK", admission, revision=saved.revision)
    assert result.reason_code == "INVALID_INPUT"
    assert "execution-secret" not in repr(_state(case))


@pytest.mark.asyncio
async def test_physical_seals_and_safe_reason_roundtrip(relay_case, tmp_path):
    case, mission, _, port, work, handoff, revision = await _ready(relay_case, tmp_path)
    import sqlite3

    conn = case.repository._get_connection()
    try:
        input_id = conn.execute(
            "SELECT input_id FROM research_work_items WHERE work_id=?", (str(work.work_id),)
        ).fetchone()[0]
    finally:
        if case.repository._mem_conn is None:
            conn.close()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(
            case, "INSERT INTO research_work_dependencies VALUES (?,?,?,?)", (1, mission.id, work.work_id, work.work_id)
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        await _sql(
            case,
            "INSERT INTO research_input_observations VALUES (?,?,?,?,?)",
            (999, input_id, mission.id, *handoff.observation_sources[0]),
        )
    before = await case.repository.load_research_work(mission.id)
    refused = await _commit(
        case.repository,
        port,
        mission,
        "SUBMIT_HANDOFF",
        replace(handoff, result="UNSUPPORTED_SENTINEL"),
        revision=revision,
        key="future-result",
    )
    assert refused.reason_code == "INVALID_TRANSITION"
    assert await case.repository.load_research_work(mission.id) == before
    assert "UNSUPPORTED_SENTINEL" not in repr(_state(case))
    assert (
        await _commit(
            case.repository,
            port,
            mission,
            "SUBMIT_HANDOFF",
            replace(handoff, result="UNSUPPORTED_SENTINEL"),
            revision=revision,
            key="future-result",
        )
        == refused
    )
    with pytest.raises(sqlite3.DatabaseError):
        await _sql(
            case,
            "UPDATE research_work_commands SET reason_code=? WHERE receipt_id=?",
            ("password=unsafe", refused.receipt_id),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["uuid", "integer", "action", "metadata_time"])
async def test_physical_type_authority_and_metadata_guards(relay_case, tmp_path, control):
    case, mission, _, _, work, _, _ = await _ready(relay_case, tmp_path)
    import sqlite3

    if control == "metadata_time":
        await _sql(case, "UPDATE research_work_items SET version=version+1 WHERE work_id=?", (work.work_id,))
    with pytest.raises(sqlite3.DatabaseError):
        if control == "uuid":
            await _sql(
                case, "UPDATE research_assignments SET assignment_id=? WHERE mission_id=?", ("invalid", mission.id)
            )
        elif control == "integer":
            await _sql(
                case, "UPDATE research_assignments SET version=? WHERE mission_id=?", ("not-integer", mission.id)
            )
        elif control == "action":
            await _sql(
                case, "UPDATE research_assignments SET actions=? WHERE mission_id=?", ('["DISPATCH"]', mission.id)
            )
        else:
            await _sql(
                case,
                "INSERT INTO research_recorded_metadata VALUES (?,?,?,?,?,?,?)",
                (mission.id, "WORK", work.work_id, work.version + 1, 1, NOW.isoformat(), "HARNESS_OBSERVED"),
            )


@pytest.mark.asyncio
async def test_start_requires_current_canonical_inputs_after_membership_change(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    receipt = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    await case.repository.delete_mission_signals(mission.id)
    activity = domain.ResearchActivityReceipt(
        work_id=assigned.work_id,
        epoch=1,
        ownership_fence=assigned.ownership_fence,
        execution_ref="current-check",
        occurred_at=NOW,
        fresh_until=NOW + timedelta(days=300),
        provenance="HOST_REPORTED",
    )
    admission = port.ResearchWorkStartAdmission(
        work_id=assigned.work_id, expected_version=1, ownership_fence=assigned.ownership_fence, receipt=activity
    )
    result = await _commit(case.repository, port, mission, "START_WORK", admission, revision=receipt.revision)
    assert result.reason_code == "INPUT_IDENTITY_MISMATCH"
    snapshot = await case.repository.load_research_work(mission.id)
    assert next(w for w in snapshot.work_items if w.work_id == assigned.work_id).state == "ASSIGNED"


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ["memory"], indirect=True)
async def test_private_memory_cancellation_holds_owner_until_physical_settlement(relay_case, tmp_path, monkeypatch):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    import threading

    entered, release = threading.Event(), threading.Event()
    original = case.repository._record_progress

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5), "Physical writer was not released"
        return original(*args, **kwargs)

    monkeypatch.setattr(case.repository, "_record_progress", blocked)
    payload = domain.ReasonWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        reason="Waiting for host",
    )
    task = asyncio.create_task(
        _commit(case.repository, port, mission, "WAIT_WORK", payload, revision=revision, key="settle")
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    reader = asyncio.create_task(case.repository.load_research_work(mission.id))
    await asyncio.sleep(0)
    assert case.repository._lock.locked() and not reader.done() and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    snapshot = await reader
    assert snapshot.work_items[0].state == "WAITING" and snapshot.work_items[0].version == work.version + 1
    retry = await _commit(case.repository, port, mission, "WAIT_WORK", payload, revision=revision, key="settle")
    assert retry.disposition == "APPLIED" and retry.revision == snapshot.revision


@pytest.mark.asyncio
async def test_first_start_atomically_activates_assignment_without_fabricated_liveness(relay_case, tmp_path):
    case, mission, _, _, work, _, revision = await _ready(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    assignment = snapshot.assignments[0]
    assert assignment.state == "ACTIVE" and assignment.version == 2
    assert [
        (m.record_version, m.mission_revision) for m in snapshot.recorded_metadata if m.record_kind == "ASSIGNMENT"
    ] == [(1, revision - 2), (2, revision)]
    assert len([e for e in snapshot.events if e.kind.value == "WORK_STARTED"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ["file"], indirect=True)
async def test_file_contender_waits_on_actual_start_transaction_then_refuses_cas(relay_case, tmp_path, monkeypatch):
    import threading
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    saved = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    contender = SqliteTrendRepository(case.repository._db_path)
    await contender._ensure_schema()
    await contender._ensure_progress_schema()
    await contender._ensure_research_schema()

    # Warm setup is completed on the actual shared file; isolate the admitted CAS lock.
    async def warm():
        pass

    monkeypatch.setattr(contender, "_ensure_progress_schema", warm)
    monkeypatch.setattr(contender, "_ensure_research_schema", warm)
    entered, attempted, release = threading.Event(), threading.Event(), threading.Event()
    original_snapshot = case.repository._commit_snapshot

    def held(*args):
        entered.set()
        assert release.wait(5)
        return original_snapshot(*args)

    monkeypatch.setattr(case.repository, "_commit_snapshot", held)
    original_open = contender._get_connection

    def observed():
        conn = original_open()
        conn.set_trace_callback(lambda statement: attempted.set() if statement == "BEGIN IMMEDIATE" else None)
        return conn

    monkeypatch.setattr(contender, "_get_connection", observed)
    activity = domain.ResearchActivityReceipt(
        work_id=assigned.work_id,
        epoch=1,
        ownership_fence=assigned.ownership_fence,
        execution_ref="file-contender",
        occurred_at=NOW,
        fresh_until=NOW + timedelta(days=300),
        provenance="HOST_REPORTED",
    )
    admission = port.ResearchWorkStartAdmission(
        work_id=assigned.work_id, expected_version=1, ownership_fence=assigned.ownership_fence, receipt=activity
    )
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="START_WORK",
        payload=admission,
        expected_revision=saved.revision,
        expected_epoch=1,
        idempotency_key="holder",
        host_authorized=True,
    )
    holder = asyncio.create_task(case.repository.commit_research_work(command))
    assert await asyncio.to_thread(entered.wait, 5)
    waiter = asyncio.create_task(contender.commit_research_work(replace(command, idempotency_key="contender")))
    try:
        assert await asyncio.to_thread(attempted.wait, 5)
        assert not waiter.done()
    finally:
        release.set()
    first, second = await asyncio.gather(holder, waiter)
    assert first.disposition == "APPLIED" and second.reason_code == "STALE_REVISION"
    snapshot = await contender.load_research_work(mission.id)
    assert next(w for w in snapshot.work_items if w.work_id == assigned.work_id).version == 2
    assert len([e for e in snapshot.events if e.work_id == assigned.work_id and e.kind.value == "WORK_STARTED"]) == 1
    await contender.close()


@pytest.mark.asyncio
async def test_mask_expansion_refuses_safely_with_original_retry(relay_case, tmp_path):
    case, mission, _, port, work, _, revision = await _ready(relay_case, tmp_path)
    submitted = replace(work, work_id=uuid4(), state="ASSIGNED", version=1, question="a@b.co " * 500)
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="ASSIGN_WORK",
        payload=submitted,
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="mask-bound",
        host_authorized=True,
    )
    result = await case.repository.commit_research_work(command)
    assert result.reason_code == "INVALID_INPUT" and not result.event_ids
    assert "a@b.co" not in repr(_state(case))
    assert await case.repository.commit_research_work(command) == result


@pytest.mark.asyncio
async def test_physical_uuid_rejects_embedded_null_suffix(relay_case, tmp_path):
    import sqlite3

    case, mission, _, _, _, _, _ = await _ready(relay_case, tmp_path)
    malformed = str(uuid4()) + "\x00unretained"
    with pytest.raises(sqlite3.IntegrityError, match="physical type"):
        await _sql(
            case, "INSERT INTO research_input_sets VALUES (?,?,?,?,?)", (malformed, mission.id, "a" * 64, None, None)
        )
    assert "unretained" not in repr(_state(case))


@pytest.mark.asyncio
async def test_real_lifecycle_events_activity_stop_and_result_required_roundtrip(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    operations = [
        ("WAIT_WORK", "WORK_WAITING"),
        ("RESUME_WORK", "WORK_RESUMED"),
        ("RECORD_ACTIVITY", "WORK_ACTIVITY_RECORDED"),
        ("REQUEST_CANCEL", "CANCELLATION_REQUESTED"),
        ("ACK_STOP", "CANCELLATION_ACKNOWLEDGED"),
    ]
    version = work.version
    for operation, kind in operations:
        if operation == "RECORD_ACTIVITY":
            activity = domain.ResearchActivityReceipt(
                work_id=work.work_id,
                epoch=1,
                ownership_fence=work.ownership_fence,
                execution_ref="synthetic-execution",
                occurred_at=NOW,
                fresh_until=NOW + timedelta(days=300),
                provenance="HOST_REPORTED",
            )
            payload = port.ResearchWorkStartAdmission(
                work_id=work.work_id, expected_version=version, ownership_fence=work.ownership_fence, receipt=activity
            )
        elif operation == "ACK_STOP":
            snapshot = await case.repository.load_research_work(mission.id)
            ended = await _commit(
                case.repository,
                port,
                mission,
                "END_RESEARCH",
                domain.EndResearchPayload(
                    assignment_id=snapshot.assignments[0].assignment_id,
                    expected_version=snapshot.assignments[0].version,
                    disposition="CANCELLED",
                    reason="No further authority",
                ),
                revision=revision,
            )
            assert ended.disposition == "APPLIED"
            revision = ended.revision
            payload = domain.StopWorkPayload(
                work_id=work.work_id,
                expected_version=version,
                ownership_fence=work.ownership_fence,
                execution_ref="synthetic-execution",
                reason="Host stopped",
            )
        else:
            payload = domain.ReasonWorkPayload(
                work_id=work.work_id,
                expected_version=version,
                ownership_fence=work.ownership_fence,
                reason="Host report",
            )
        result = await _commit(case.repository, port, mission, operation, payload, revision=revision)
        assert result.disposition == "APPLIED" and result.work_version == version + 1
        snapshot = await case.repository.load_research_work(mission.id)
        events = [e for e in snapshot.events if e.event_id in result.event_ids]
        assert len(events) == 1 and events[0].kind.value == kind
        version, revision = result.work_version, result.revision
    assert snapshot.work_items[0].state == "CANCELLED" and snapshot.assignments[0].state == "CANCELLED"


@pytest.mark.asyncio
async def test_completion_without_result_has_durable_finite_safe_original_receipt(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _ready(relay_case, tmp_path)
    payload = domain.EndWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        disposition="COMPLETED",
        reason="REJECTED_NO_RESULT_SENTINEL",
    )
    first = await _commit(case.repository, port, mission, "END_WORK", payload, revision=revision, key="result-required")
    assert first.reason_code == "RESULT_REQUIRED" and first.disposition == "REFUSED" and not first.event_ids
    assert "REJECTED_NO_RESULT_SENTINEL" not in repr(_state(case))
    assert (
        await _commit(case.repository, port, mission, "END_WORK", payload, revision=revision, key="result-required")
        == first
    )
