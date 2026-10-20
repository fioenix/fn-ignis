"""Native PostgreSQL immutable result and physical settlement controls."""

import asyncio
from dataclasses import replace

import psycopg
import pytest
from psycopg import sql

from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from tests.integration.test_mission_relay_read_boundary import _state, relay_case as canonical_relay_case
from tests.integration.test_research_work_persistence import _arrange, _commit
from tests.integration.test_research_work_result_controls import (
    test_result_retains_independent_source_order_and_submitted_times as test_result_retains_independent_source_order_and_submitted_times,
    test_completion_settles_only_current_unrejected_result as test_completion_settles_only_current_unrejected_result,
    test_handoff_finding_order_and_zero_result_collections as test_handoff_finding_order_and_zero_result_collections,
    test_result_masks_all_typed_text_fields as test_result_masks_all_typed_text_fields,
    test_mask_expansion_refusal_is_original_after_later_activity as test_mask_expansion_refusal_is_original_after_later_activity,
    test_predecessor_lineage_does_not_invent_dependency_currentness as test_predecessor_lineage_does_not_invent_dependency_currentness,
    test_masked_consumer_can_acknowledge_original_public_safe_identity as test_masked_consumer_can_acknowledge_original_public_safe_identity,
)

relay_case = canonical_relay_case
pytestmark = pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault_table",
    [
        "research_handoffs",
        "research_finding_revisions",
        "mission_progress_events",
        "research_recorded_metadata",
        "research_work_commands",
    ],
)
async def test_native_result_late_failure_has_no_durable_receipt_and_original_retry(relay_case, tmp_path, fault_table):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="SUBMIT_HANDOFF",
        payload=handoff,
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="result-late-fault",
        host_authorized=True,
    )
    with psycopg.connect(case.dsn) as conn:
        conn.execute("CREATE SEQUENCE t050_fault_calls")
        conn.execute(
            "CREATE FUNCTION t050_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM nextval('t050_fault_calls'); RAISE EXCEPTION 'T050 late result fault' USING ERRCODE='23514'; END $$"
        )
        conn.execute(
            sql.SQL("CREATE TRIGGER t050_fault BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION t050_fault()").format(
                sql.Identifier(fault_table)
            )
        )
    before = _state(case)
    refused = await case.repository.commit_research_work(command)
    assert refused.reason_code == "STORAGE_FAILURE" and refused.revision == revision and not refused.event_ids
    assert _state(case) == before
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute("SELECT last_value,is_called FROM t050_fault_calls").fetchone() == (1, True)
        conn.execute(sql.SQL("DROP TRIGGER t050_fault ON {}").format(sql.Identifier(fault_table)))
    accepted = await case.repository.commit_research_work(command)
    assert accepted.disposition == "APPLIED" and accepted.revision == revision + 1
    assert accepted.receipt_id != refused.receipt_id
    assert await case.repository.commit_research_work(command) == accepted
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings


@pytest.mark.asyncio
async def test_native_result_independent_pool_wait_graph_and_single_cas(relay_case, tmp_path, monkeypatch):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    contender = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    await contender._get_pool()
    command = port.ResearchWorkCommitCommand(
        mission_id=mission.id,
        operation="SUBMIT_HANDOFF",
        payload=handoff,
        expected_revision=revision,
        expected_epoch=1,
        idempotency_key="result-holder",
        host_authorized=True,
    )
    entered, release = asyncio.Event(), asyncio.Event()
    original = case.repository._research_snapshot
    contender_gate = contender._lock_relay_tables
    owner_pid = contender_pid = None

    async def held(conn, mission_id, **kwargs):
        nonlocal owner_pid
        snapshot = await original(conn, mission_id, **kwargs)
        owner_pid = conn.info.backend_pid
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        return snapshot

    async def observed_gate(cur, **kwargs):
        nonlocal contender_pid
        contender_pid = cur.connection.info.backend_pid
        await contender_gate(cur, **kwargs)

    monkeypatch.setattr(case.repository, "_research_snapshot", held)
    monkeypatch.setattr(contender, "_lock_relay_tables", observed_gate)
    holder = asyncio.create_task(case.repository.commit_research_work(command))
    loser_command = replace(command, idempotency_key="result-contender")
    loser = None
    try:
        await asyncio.wait_for(entered.wait(), 5)
        loser = asyncio.create_task(contender.commit_research_work(loser_command))
        async with await psycopg.AsyncConnection.connect(case.dsn) as observer:
            # Bounded event-loop yielding observes an actual server wait graph, not elapsed overlap.
            async def physical_wait():
                while True:
                    if contender_pid:
                        row = await (
                            await observer.execute("SELECT %s = ANY(pg_blocking_pids(%s))", (owner_pid, contender_pid))
                        ).fetchone()
                        if row == (True,):
                            return
                    await asyncio.sleep(0)

            await asyncio.wait_for(physical_wait(), 5)
            assert owner_pid != contender_pid and contender._pool is not case.repository._pool
            modes = await (
                await observer.execute(
                    "SELECT mode FROM pg_locks WHERE pid=%s AND relation='observations'::regclass AND granted",
                    (owner_pid,),
                )
            ).fetchall()
            assert ("ShareRowExclusiveLock",) in modes
        assert not holder.done() and not loser.done()
        release.set()
        accepted, refused = await asyncio.gather(holder, loser)
        assert accepted.disposition == "APPLIED" and refused.reason_code == "STALE_REVISION"
        snapshot = await contender.load_research_work(mission.id)
        assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
        assert len([e for e in snapshot.events if e.kind.value == "HANDOFF_COMMITTED"]) == 1
        assert await contender.commit_research_work(loser_command) == refused
        assert await contender.commit_research_work(command) == accepted
        conflict = await contender.commit_research_work(
            replace(loser_command, payload=replace(handoff, result="Changed result"))
        )
        assert conflict.reason_code == "IDEMPOTENCY_CONFLICT"
    finally:
        release.set()
        await asyncio.gather(holder, *([loser] if loser else []), return_exceptions=True)
        monkeypatch.setattr(case.repository, "_research_snapshot", original)
        await contender.close()


@pytest.mark.asyncio
async def test_native_handoff_references_sealed_and_retained_after_withdrawal(relay_case, tmp_path):
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    receipt = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert receipt.disposition == "APPLIED"
    before = _state(case)[1]["research_handoff_observations"]
    assert len(before) == len(handoff.observation_sources)
    with psycopg.connect(case.dsn) as conn:
        for statement in (
            "UPDATE research_handoff_observations SET ordinal=999 WHERE handoff_id=%s",
            "DELETE FROM research_handoff_observations WHERE handoff_id=%s",
        ):
            with pytest.raises(psycopg.errors.CheckViolation, match="append-only"):
                conn.execute(statement, (handoff.handoff_id,))
            conn.rollback()
        conn.execute(
            "DELETE FROM mission_evidence WHERE mission_id=%s AND observation_id=%s",
            (mission.id, handoff.observation_sources[0][0]),
        )
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,) and snapshot.current_finding_revisions == ()
    assert _state(case)[1]["research_handoff_observations"] == before


@pytest.mark.asyncio
async def test_admitted_history_reuses_one_held_canonical_snapshot(relay_case, tmp_path, monkeypatch):
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    saved = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert saved.disposition == "APPLIED"
    original = case.repository._commit_snapshot
    connections = []

    async def held_canonical(conn, mission_id):
        connections.append(conn.info.backend_pid)
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS
        with psycopg.connect(case.dsn) as observer:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                observer.execute(
                    "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE NOWAIT",
                    (mission_id,),
                )
        return await original(conn, mission_id)

    monkeypatch.setattr(case.repository, "_commit_snapshot", held_canonical)
    end = domain.EndWorkPayload(
        work_id=work.work_id,
        expected_version=saved.work_version,
        ownership_fence=work.ownership_fence,
        disposition="COMPLETED",
        reason="Current result complete",
    )
    completed = await _commit(case.repository, port, mission, "END_WORK", end, revision=saved.revision)
    assert completed.disposition == "APPLIED" and len(connections) == 1
    monkeypatch.setattr(case.repository, "_commit_snapshot", original)
    snapshots = []

    async def readonly_canonical(conn, mission_id):
        snapshots.append(conn.info.backend_pid)
        assert (await (await conn.execute("SHOW transaction_read_only")).fetchone())[0] == "on"
        assert (await (await conn.execute("SHOW transaction_isolation")).fetchone())[0] == "repeatable read"
        return await original(conn, mission_id)

    monkeypatch.setattr(case.repository, "_commit_snapshot", readonly_canonical)
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
    assert snapshot.current_finding_revisions == ((handoff.findings[0].finding_id, 1),)
    assert len(snapshots) == 1


@pytest.mark.asyncio
async def test_native_plain_owner_result_fault_retry_and_ack_without_elevation(relay_case, tmp_path):
    from conftest import RepositoryCase, runtime_owner

    case, missions, runs = relay_case
    await case.repository.close()
    with runtime_owner(case.dsn) as owner_dsn:
        repository = PostgresTimescaleRepository(owner_dsn, min_pool_size=1, max_pool_size=2)
        owner_case = RepositoryCase("postgres", repository, owner_dsn)
        try:
            owner, mission, _, port, _, handoff, revision = await _arrange((owner_case, missions, runs), tmp_path)
            with psycopg.connect(owner_dsn) as conn:
                assert conn.execute(
                    "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False)
                assert conn.execute(
                    "SELECT count(*) FROM pg_proc WHERE proname IN ('reject_research_history_mutation','preserve_research_work_identity','validate_research_reference') AND prosecdef"
                ).fetchone() == (0,)
            # Test-only fault instrumentation uses fixture administration; admissions stay plain owner.
            with psycopg.connect(case.dsn) as admin:
                admin.execute("CREATE SEQUENCE t050_owner_calls")
                admin.execute("ALTER SEQUENCE t050_owner_calls OWNER TO ignis_test_runtime_owner")
                admin.execute(
                    "CREATE FUNCTION t050_owner_fault() RETURNS trigger LANGUAGE plpgsql SECURITY INVOKER AS $$ BEGIN PERFORM nextval('t050_owner_calls'); RAISE EXCEPTION 'T050 plain owner fault' USING ERRCODE='23514'; END $$"
                )
                admin.execute(
                    "CREATE TRIGGER t050_owner_fault BEFORE INSERT ON research_work_commands FOR EACH ROW EXECUTE FUNCTION t050_owner_fault()"
                )
            command = port.ResearchWorkCommitCommand(
                mission_id=mission.id,
                operation="SUBMIT_HANDOFF",
                payload=handoff,
                expected_revision=revision,
                expected_epoch=1,
                idempotency_key="plain-owner-result",
                host_authorized=True,
            )
            before = _state(owner)
            refusal = await repository.commit_research_work(command)
            assert refusal.reason_code == "STORAGE_FAILURE" and not refusal.event_ids
            assert _state(owner) == before
            with psycopg.connect(owner_dsn) as conn:
                assert conn.execute("SELECT last_value,is_called FROM t050_owner_calls").fetchone() == (1, True)
                conn.execute("DROP TRIGGER t050_owner_fault ON research_work_commands")
            accepted = await repository.commit_research_work(command)
            assert accepted.disposition == "APPLIED" and accepted.receipt_id != refusal.receipt_id
            assert await repository.commit_research_work(command) == accepted
            snapshot = await repository.load_research_work(mission.id)
            assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
            ack = port.ResearchHandoffAcknowledgement(
                handoff_id=handoff.handoff_id,
                consumer_ref=handoff.consumer_ref,
                expected_version=accepted.work_version,
                disposition="ACCEPTED",
                reason_code=None,
                inputs=handoff.inputs,
            )
            completed = await _commit(repository, port, mission, "ACK_HANDOFF", ack, revision=accepted.revision)
            assert completed.disposition == "APPLIED"
            snapshot = await repository.load_research_work(mission.id)
            assert snapshot.acknowledgements == (ack,) and snapshot.work_items[0].state == "COMPLETED"
            assert [e.kind.value for e in snapshot.events if e.cursor.revision == completed.revision] == [
                "HANDOFF_ACKNOWLEDGED",
                "WORK_ENDED",
            ]
        finally:
            await repository.close()
