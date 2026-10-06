"""T048 core lifecycle parity and actual PostgreSQL transaction controls."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from tests.integration.test_mission_relay_read_boundary import NOW, _state, relay_case as canonical_relay_case
from tests.integration.test_research_work_persistence import _arrange, _commit, _sql
from tests.integration.test_research_work_lifecycle_persistence import (
    test_core_exact_binding_events_metadata_and_retry as test_core_exact_binding_events_metadata_and_retry,
    test_refusal_original_receipt_without_body_or_fake_event as test_refusal_original_receipt_without_body_or_fake_event,
    test_epoch_next_only_terminal_replay_and_bound_old_closure as test_epoch_next_only_terminal_replay_and_bound_old_closure,
    test_expired_and_widened_assignment_do_not_persist_body as test_expired_and_widened_assignment_do_not_persist_body,
    test_mask_accepted_text_and_refuse_unsafe_exact_execution_identity as test_mask_accepted_text_and_refuse_unsafe_exact_execution_identity,
    test_start_requires_current_canonical_inputs_after_membership_change as test_start_requires_current_canonical_inputs_after_membership_change,
    test_first_start_atomically_activates_assignment_without_fabricated_liveness as test_first_start_atomically_activates_assignment_without_fabricated_liveness,
    test_mask_expansion_refuses_safely_with_original_retry as test_mask_expansion_refuses_safely_with_original_retry,
    test_real_lifecycle_events_activity_stop_and_result_required_roundtrip as test_real_lifecycle_events_activity_stop_and_result_required_roundtrip,
    test_completion_without_result_has_durable_finite_safe_original_receipt as test_completion_without_result_has_durable_finite_safe_original_receipt,
)

relay_case = canonical_relay_case
pytestmark = pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault_table", ["mission_progress_events", "research_recorded_metadata", "research_work_commands"]
)
async def test_postgres_late_trigger_fault_rolls_back_actual_facts(relay_case, tmp_path, fault_table):
    case, mission, _, port, work, _, revision = await _arrange(relay_case, tmp_path)
    with psycopg.connect(case.dsn) as conn:
        conn.execute("CREATE SEQUENCE t048_fault_calls")
        conn.execute(
            "CREATE FUNCTION t048_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM nextval('t048_fault_calls'); RAISE EXCEPTION 'T048 late fault' USING ERRCODE='23514'; END $$"
        )
        conn.execute(
            sql.SQL("CREATE TRIGGER t048_fault BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION t048_fault()").format(
                sql.Identifier(fault_table)
            )
        )
    before = _state(case)
    result = await _commit(
        case.repository,
        port,
        mission,
        "ASSIGN_WORK",
        replace(work, work_id=uuid4(), state="ASSIGNED", version=1),
        revision=revision,
        key="late-fault",
    )
    assert result.reason_code == "STORAGE_FAILURE" and result.revision == revision and not result.event_ids
    assert _state(case) == before
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute("SELECT last_value,is_called FROM t048_fault_calls").fetchone() == (1, True)
        conn.execute(sql.SQL("DROP TRIGGER t048_fault ON {}").format(sql.Identifier(fault_table)))
    saved = await _commit(
        case.repository,
        port,
        mission,
        "ASSIGN_WORK",
        replace(work, work_id=uuid4(), state="ASSIGNED", version=1),
        revision=revision,
        key="late-fault",
    )
    assert saved.disposition == "APPLIED" and saved.revision == revision + 1


@pytest.mark.asyncio
async def test_postgres_two_pool_physical_lock_and_single_start_cas(relay_case, tmp_path, monkeypatch):
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    saved = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    activity = domain.ResearchActivityReceipt(
        work_id=assigned.work_id,
        epoch=1,
        ownership_fence=assigned.ownership_fence,
        execution_ref="physical-start",
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
    contender = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    entered, release = asyncio.Event(), asyncio.Event()
    original = case.repository._research_snapshot
    original_gate = contender._lock_relay_tables
    owner_pid = None

    async def held(conn, mission_id):
        nonlocal owner_pid
        result = await original(conn, mission_id)
        owner_pid = conn.info.backend_pid
        entered.set()
        await asyncio.wait_for(release.wait(), 5)
        return result

    async def bounded_gate(cur, **kwargs):
        await cur.execute("SET LOCAL lock_timeout='100ms'")
        await original_gate(cur, **kwargs)

    monkeypatch.setattr(case.repository, "_research_snapshot", held)
    monkeypatch.setattr(contender, "_lock_relay_tables", bounded_gate)
    holder = asyncio.create_task(case.repository.commit_research_work(command))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # Independent server connection verifies the held gate and mission row, not a Python lock.
        with psycopg.connect(case.dsn) as observer:
            assert observer.info.backend_pid != owner_pid
            modes = observer.execute(
                "SELECT mode FROM pg_locks WHERE pid=%s AND relation='observations'::regclass AND granted", (owner_pid,)
            ).fetchall()
            assert ("ShareRowExclusiveLock",) in modes
            with pytest.raises(psycopg.errors.LockNotAvailable):
                observer.execute(
                    "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE NOWAIT",
                    (mission.id,),
                )
            observer.rollback()
            with pytest.raises(psycopg.errors.LockNotAvailable):
                observer.execute("LOCK TABLE observations IN ROW EXCLUSIVE MODE NOWAIT")
        blocked = await contender.commit_research_work(replace(command, idempotency_key="contender"))
        assert blocked.reason_code == "STORAGE_FAILURE" and not blocked.event_ids
        assert not holder.done()
        assert contender._pool is not case.repository._pool
    finally:
        release.set()
        first = await holder
        monkeypatch.setattr(case.repository, "_research_snapshot", original)
    try:
        second = await contender.commit_research_work(replace(command, idempotency_key="contender"))
        assert first.disposition == "APPLIED" and second.reason_code == "STALE_REVISION"
        snapshot = await contender.load_research_work(mission.id)
        actual = next(w for w in snapshot.work_items if w.work_id == assigned.work_id)
        assert actual.version == 2 and actual.state == "RUNNING"
        assert (
            len([e for e in snapshot.events if e.work_id == assigned.work_id and e.kind.value == "WORK_STARTED"]) == 1
        )
        assert await contender.commit_research_work(command) == first
    finally:
        await contender.close()


@pytest.mark.asyncio
async def test_postgres_refused_original_after_new_revision_and_future_result_boundary(relay_case, tmp_path):
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="SUBMIT_HANDOFF",
        payload=replace(handoff, result="UNSUPPORTED_SENTINEL"),
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="future-result",
        host_authorized=True,
    )
    before = await case.repository.load_research_work(mission.id)
    refusal = await case.repository.commit_research_work(command)
    assert refusal.reason_code == "INVALID_TRANSITION" and not refusal.event_ids
    assert await case.repository.load_research_work(mission.id) == before
    changed = await _commit(
        case.repository,
        port,
        mission,
        "WAIT_WORK",
        domain.ReasonWorkPayload(
            work_id=work.work_id, expected_version=work.version, ownership_fence=work.ownership_fence, reason="Wait"
        ),
        revision=revision,
    )
    assert changed.disposition == "APPLIED"
    state = _state(case)
    assert "UNSUPPORTED_SENTINEL" not in repr(state)
    assert await case.repository.commit_research_work(command) == refusal
    assert _state(case) == state
    ack = port.ResearchHandoffAcknowledgement(
        handoff_id=handoff.handoff_id,
        consumer_ref="rejected-consumer",
        expected_version=work.version,
        disposition="REJECTED",
        reason_code="UNSUPPORTED_ACK_SENTINEL",
        inputs=work.inputs,
    )
    ack_receipt = await _commit(case.repository, port, mission, "ACK_HANDOFF", ack, revision=changed.revision)
    assert ack_receipt.reason_code == "INVALID_TRANSITION" and not ack_receipt.event_ids
    assert "UNSUPPORTED_ACK_SENTINEL" not in repr(_state(case))
    for name in ("research_handoffs", "research_finding_revisions", "research_handoff_acknowledgements"):
        assert not state[1][name]


@pytest.mark.asyncio
async def test_postgres_immutable_bindings_order_pruning_and_root_cascade(relay_case, tmp_path):
    case, mission, _, _, work, handoff, _ = await _arrange(relay_case, tmp_path)
    snapshot = await case.repository.load_research_work(mission.id)
    with psycopg.connect(case.dsn) as conn:
        input_id = conn.execute(
            "SELECT input_id FROM research_work_items WHERE work_id=%s", (work.work_id,)
        ).fetchone()[0]
        refs = conn.execute(
            "SELECT observation_id,source_id FROM research_input_observations WHERE input_id=%s ORDER BY ordinal",
            (input_id,),
        ).fetchall()
    assert tuple(refs) == handoff.observation_sources
    mutations = [
        ("UPDATE research_work_items SET question=%s WHERE work_id=%s", ("changed", work.work_id)),
        ("DELETE FROM research_work_items WHERE work_id=%s", (work.work_id,)),
        (
            "UPDATE observations SET source_id=%s WHERE id=%s",
            (snapshot.observation_sources[1][1], snapshot.observation_sources[0][0]),
        ),
        ("INSERT INTO research_work_dependencies VALUES (%s,%s,%s,%s)", (1, mission.id, work.work_id, work.work_id)),
        (
            "INSERT INTO research_input_observations VALUES (%s,%s,%s,%s,%s)",
            (999, input_id, mission.id, *handoff.observation_sources[0]),
        ),
    ]
    for statement, params in mutations:
        with pytest.raises(psycopg.IntegrityError):
            await _sql(case, statement, params)
    await case.repository.delete_mission_signals(mission.id)
    pruned = await case.repository.load_research_work(mission.id)
    assert pruned.work_items == snapshot.work_items and not pruned.observation_sources
    counts = {name: len(_state(case)[1][name]) for name in ("sources", "observations")}
    await _sql(case, "DELETE FROM research_missions WHERE id=%s", (mission.id,))
    state = _state(case)
    # The fixture also holds two unrelated missions; only this mission's history must vanish.
    with psycopg.connect(case.dsn) as conn:
        for name in state[1]:
            if name.startswith("research_") and name not in {"research_missions", "research_workspaces"}:
                assert (
                    conn.execute(
                        sql.SQL("SELECT count(*) FROM {} WHERE mission_id=%s").format(sql.Identifier(name)),
                        (mission.id,),
                    ).fetchone()[0]
                    == 0
                )
    assert {name: len(state[1][name]) for name in counts} == counts


@pytest.mark.asyncio
async def test_postgres_loader_is_held_readonly_repeatable_read_and_never_bootstraps(relay_case, tmp_path, monkeypatch):
    case, mission, _, _, _, _, _ = await _arrange(relay_case, tmp_path)
    before = _state(case)
    original = case.repository._research_snapshot

    async def checked(conn, mission_id):
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        async with conn.cursor() as cur:
            await cur.execute("SHOW transaction_isolation")
            assert (await cur.fetchone())[0] == "repeatable read"
            await cur.execute("SHOW transaction_read_only")
            assert (await cur.fetchone())[0] == "on"
        return await original(conn, mission_id)

    monkeypatch.setattr(case.repository, "_research_snapshot", checked)
    await case.repository.load_research_work(mission.id)
    assert _state(case) == before
    with psycopg.connect(case.dsn) as conn:
        conn.execute("DROP TABLE research_work_commands")
    missing = _state(case)
    await case.repository.load_research_work(mission.id)
    assert _state(case) == missing and "research_work_commands" not in missing[1]


@pytest.mark.asyncio
async def test_postgres_plain_owner_operations_and_fault_without_elevation(relay_case, tmp_path):
    from conftest import RepositoryCase, runtime_owner

    case, missions, runs = relay_case
    await case.repository.close()
    with runtime_owner(case.dsn) as owner_dsn:
        repository = PostgresTimescaleRepository(owner_dsn, min_pool_size=1, max_pool_size=2)
        owner_case = RepositoryCase("postgres", repository, owner_dsn)
        try:
            owner, mission, _, port, work, _, revision = await _arrange((owner_case, missions, runs), tmp_path)
            with psycopg.connect(owner_dsn) as conn:
                assert conn.execute(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False)
                assert (
                    conn.execute(
                        "SELECT count(*) FROM pg_proc WHERE proname IN ('reject_research_history_mutation','preserve_research_work_identity','validate_research_reference') AND prosecdef"
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    conn.execute(
                        "SELECT count(*) FROM pg_class WHERE relname LIKE 'research_%' AND relrowsecurity AND relforcerowsecurity"
                    ).fetchone()[0]
                    == 0
                )
            with psycopg.connect(case.dsn) as admin:
                admin.execute(
                    "CREATE FUNCTION t048_owner_fault() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$ BEGIN RAISE EXCEPTION 'T048 owner fault' USING ERRCODE='23514'; END $$"
                )
                admin.execute(
                    "CREATE TRIGGER t048_owner_fault BEFORE INSERT ON research_work_commands FOR EACH ROW EXECUTE FUNCTION t048_owner_fault()"
                )
            before = _state(owner)
            result = await _commit(
                repository,
                port,
                mission,
                "ASSIGN_WORK",
                replace(work, work_id=uuid4(), state="ASSIGNED", version=1),
                revision=revision,
            )
            assert result.reason_code == "STORAGE_FAILURE" and result.revision == revision
            assert _state(owner) == before
        finally:
            await repository.close()


@pytest.mark.asyncio
async def test_postgres_canonical_snapshot_uses_locked_writer_connection(relay_case, tmp_path, monkeypatch):
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    canonical = case.repository._commit_snapshot
    physical = case.repository._research_snapshot
    connections = []

    async def checked(conn, mission_id):
        connections.append(conn.info.backend_pid)
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        with psycopg.connect(case.dsn) as observer:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                observer.execute(
                    "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE NOWAIT",
                    (mission_id,),
                )
        return await canonical(conn, mission_id)

    async def research(conn, mission_id):
        assert conn.info.backend_pid == connections[0]
        return await physical(conn, mission_id)

    monkeypatch.setattr(case.repository, "_commit_snapshot", checked)
    monkeypatch.setattr(case.repository, "_research_snapshot", research)
    payload = domain.ReasonWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        reason="Wait on recorded input",
    )
    saved = await _commit(case.repository, port, mission, "WAIT_WORK", payload, revision=revision)
    assert saved.disposition == "APPLIED" and len(connections) == 1


@pytest.mark.asyncio
async def test_postgres_unknown_mission_refuses_without_control_or_body(relay_case, tmp_path):
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    payload = domain.ReasonWorkPayload(
        work_id=work.work_id,
        expected_version=work.version,
        ownership_fence=work.ownership_fence,
        reason="UNKNOWN_SCOPE_SENTINEL",
    )
    command = port.ResearchWorkCommitCommand(
        mission_id=uuid4(),
        operation="WAIT_WORK",
        payload=payload,
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="unknown-scope",
        host_authorized=True,
    )
    before = _state(case)
    result = await case.repository.commit_research_work(command)
    assert result.reason_code == "SCOPE_MISMATCH" and not result.event_ids
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("held_lock", ["canonical", "mission"])
@pytest.mark.parametrize("boundary", ["authority", "freshness", "later_occurrence"])
async def test_postgres_admission_clock_after_observed_physical_wait(
    relay_case, tmp_path, monkeypatch, held_lock, boundary
):
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    assigned = replace(work, work_id=uuid4(), state="ASSIGNED", version=1)
    saved = await _commit(case.repository, port, mission, "ASSIGN_WORK", assigned, revision=revision)
    with psycopg.connect(case.dsn) as setup:
        setup.execute("""CREATE FUNCTION t048_observe_wait(waiter integer, blocker integer) RETURNS timestamptz LANGUAGE plpgsql AS $$
        DECLARE limit_at timestamptz := clock_timestamp() + interval '5 seconds';
        BEGIN
            LOOP
                IF blocker = ANY(pg_blocking_pids(waiter)) THEN RETURN clock_timestamp(); END IF;
                IF clock_timestamp() > limit_at THEN RAISE EXCEPTION 'Physical waiter not observed'; END IF;
                PERFORM pg_sleep(0.005);
            END LOOP;
        END $$""")
    holder = await psycopg.AsyncConnection.connect(case.dsn)
    contender = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    began = asyncio.Event()
    captured = {}
    original_gate = contender._lock_relay_tables

    async def gate(cur, **kwargs):
        await cur.execute("SELECT transaction_timestamp(), clock_timestamp(), pg_backend_pid()")
        captured["transaction"], captured["begin_clock"], captured["pid"] = await cur.fetchone()
        began.set()
        return await original_gate(cur, **kwargs)

    monkeypatch.setattr(contender, "_lock_relay_tables", gate)
    try:
        if held_lock == "canonical":
            await holder.execute("LOCK TABLE observations IN ROW EXCLUSIVE MODE")
        else:
            await holder.execute(
                "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE", (mission.id,)
            )
        async with holder.cursor() as cur:
            await cur.execute("SELECT clock_timestamp()")
            actual_clock = (await cur.fetchone())[0]
        boundary_at = actual_clock + timedelta(seconds=1)
        if boundary == "authority":
            # Change the explicit grant before the queued START, without changing its revision.
            with psycopg.connect(case.dsn) as setup:
                setup.execute(
                    "UPDATE research_assignments SET deadline=%s WHERE assignment_id=%s",
                    (boundary_at, assigned.assignment_id),
                )
        occurrence = boundary_at if boundary == "later_occurrence" else actual_clock
        freshness = boundary_at if boundary == "freshness" else actual_clock + timedelta(minutes=1)
        activity = domain.ResearchActivityReceipt(
            work_id=assigned.work_id,
            epoch=1,
            ownership_fence=assigned.ownership_fence,
            execution_ref="clock-bound-start",
            occurred_at=occurrence,
            fresh_until=freshness,
            provenance="HOST_REPORTED",
        )
        payload = port.ResearchWorkStartAdmission(
            work_id=assigned.work_id, expected_version=1, ownership_fence=assigned.ownership_fence, receipt=activity
        )
        command = port.ResearchWorkCommitCommand(
            mission_id=mission.id,
            operation="START_WORK",
            payload=payload,
            expected_revision=saved.revision,
            expected_epoch=1,
            idempotency_key="physical-clock",
            host_authorized=True,
        )
        before = await case.repository.load_research_work(mission.id)
        before_state = _state(case)
        task = asyncio.create_task(contender.commit_research_work(command))
        await asyncio.wait_for(began.wait(), 5)
        assert captured["transaction"] <= captured["begin_clock"] < boundary_at
        async with await psycopg.AsyncConnection.connect(case.dsn) as observer:
            async with observer.cursor() as cur:
                await cur.execute("SELECT t048_observe_wait(%s,%s)", (captured["pid"], holder.info.backend_pid))
                observed_wait = (await cur.fetchone())[0]
                assert observed_wait < boundary_at and not task.done()
                # A bounded database clock barrier, not a Python clock override or pre-command sleep.
                await cur.execute(
                    "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM %s::timestamptz-clock_timestamp())) + 0.03)",
                    (boundary_at,),
                )
                await cur.execute("SELECT clock_timestamp()")
                released_clock = (await cur.fetchone())[0]
                assert released_clock > boundary_at
        await holder.rollback()
        result = await asyncio.wait_for(task, 5)
        if boundary == "later_occurrence":
            assert result.disposition == "APPLIED", "A valid occurrence after BEGIN must use fresh admission time"
            assert captured["transaction"] < occurrence < released_clock
            after = await contender.load_research_work(mission.id)
            actual = next(w for w in after.work_items if w.work_id == assigned.work_id)
            assert actual.state == "RUNNING" and actual.version == 2
            metadata = [m for m in after.recorded_metadata if m.record_id == assigned.work_id and m.record_version == 2]
            assert len(metadata) == 1 and metadata[0].recorded_at == captured["transaction"] == result.recorded_at
        else:
            reason = "AUTHORITY_EXPIRED" if boundary == "authority" else "EXECUTION_RECEIPT_NOT_CURRENT"
            assert result.reason_code == reason and result.disposition == "REFUSED" and not result.event_ids
            assert await contender.load_research_work(mission.id) == before
            assert result.recorded_at == captured["transaction"]
            after_state = _state(case)
            assert after_state[0] == before_state[0]
            assert {n: rows for n, rows in after_state[1].items() if n != "research_work_commands"} == {
                n: rows for n, rows in before_state[1].items() if n != "research_work_commands"
            }
        state = _state(case)
        assert await contender.commit_research_work(command) == result
        assert _state(case) == state
    finally:
        await holder.rollback()
        await holder.close()
        await contender.close()
