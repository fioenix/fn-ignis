"""Real PostgreSQL publication controls: split commits, early reuse and replay must fail."""

import asyncio
from contextlib import asynccontextmanager, contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus
import pytest
import pytest_asyncio

from ignis.application.cancellation import await_settled
from ignis.application.ports.mission_relay_port import ProbeOutcomeCommitCommand
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.mission_relay import MissionProgressKind, RelayProvenance
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    InvalidEvidenceQualificationError,
    MissionManifest,
    MissionOutputType,
    MissionProbeOutcome,
    ResearchWorkspace,
)
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from conftest import runtime_owner


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
TABLES = (
    "mission_probe_outcomes",
    "mission_progress_revisions",
    "mission_progress_events",
    "mission_progress_commands",
)


@pytest_asyncio.fixture
async def commit_case(repository_case, tmp_path):
    case = repository_case
    repository = case.repository
    workspace = ResearchWorkspace(slug="postgres-commits", root_path=tmp_path / "workspace")
    await repository.save_research_workspace(workspace)
    mission = ResearchMission(title="Atomic publication", keywords=["work bag"], workspace_id=workspace.workspace_id)
    await repository.save_mission(mission)
    run_id = uuid4()
    await repository.record_run_journal(
        RunJournal(
            run_id=run_id,
            mission_id=mission.id,
            workspace_id=workspace.workspace_id,
            journal_path=tmp_path / "run.md",
            sequence=1,
            status="COMPLETED",
            started_at=NOW,
            completed_at=NOW,
        )
    )
    outcome = MissionProbeOutcome(
        run_id=run_id,
        platform="youtube",
        connector_surface="youtube",
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        signals_collected=0,
        queried_keywords=("work bag",),
        query_fingerprint="a" * 64,
        completed_at=NOW,
    )
    return case, mission, outcome


def _command(mission, outcome, *more):
    return ProbeOutcomeCommitCommand(mission_id=mission.id, run_id=outcome.run_id, outcomes=(outcome, *more))


def _state(case):
    with psycopg.connect(case.dsn, row_factory=psycopg.rows.dict_row) as conn:
        return {
            table: conn.execute(
                sql.SQL("SELECT * FROM {} ORDER BY {}").format(
                    sql.Identifier(table),
                    sql.Identifier(
                        "mission_id"
                        if table == "mission_progress_revisions"
                        else "id"
                        if table != "mission_progress_commands"
                        else "command_key"
                    ),
                )
            ).fetchall()
            for table in TABLES
        }


@contextmanager
def _refuse_write(case, table, *, deferred=False):
    """A real server trigger refuses statement/COMMIT, without replacing adapter SQL."""
    with psycopg.connect(case.dsn) as conn:
        conn.execute(
            "CREATE FUNCTION t011_refuse() RETURNS trigger LANGUAGE plpgsql AS $$"
            " BEGIN RAISE EXCEPTION 'Controlled publication refusal' USING ERRCODE='23514'; END $$"
        )
        if deferred:
            statement = "CREATE CONSTRAINT TRIGGER t011_refuse AFTER INSERT ON {} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION t011_refuse()"
        else:
            statement = (
                "CREATE TRIGGER t011_refuse BEFORE INSERT OR UPDATE ON {} FOR EACH ROW EXECUTE FUNCTION t011_refuse()"
            )
        conn.execute(sql.SQL(statement).format(sql.Identifier(table)))
    try:
        yield
    finally:
        with psycopg.connect(case.dsn) as conn:
            conn.execute(sql.SQL("DROP TRIGGER t011_refuse ON {}").format(sql.Identifier(table)))
            conn.execute("DROP FUNCTION t011_refuse()")


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_reordered_retry_retains_original_receipt_after_later_revision(commit_case):
    case, mission, first = commit_case
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    command = _command(mission, first, second)
    receipt = await case.repository.commit_probe_outcomes(command)
    original = _state(case)
    assert receipt.event.cursor.position == (1, 1)
    assert receipt.event.kind is MissionProgressKind.PROBE_OUTCOMES_RECORDED
    assert receipt.event.provenance is RelayProvenance.HARNESS_OBSERVED
    assert receipt.event.run_id == first.run_id
    assert receipt.event.recorded_at.utcoffset() == timedelta(0)
    assert receipt.event.occurred_at is None and receipt.event.evidence_references == ()
    assert receipt.command_key == command.command_key and receipt.payload_fingerprint == command.payload_fingerprint
    assert receipt.outcome_count == 2
    assert {row["id"] for row in original[TABLES[0]]} == {first.outcome_id, second.outcome_id}
    fact = next(row for row in original[TABLES[0]] if row["id"] == first.outcome_id)
    assert fact == {
        "id": first.outcome_id,
        "run_id": first.run_id,
        "platform": "youtube",
        "connector_surface": "youtube",
        "status": "EMPTY_NO_DATA",
        "signals_collected": 0,
        "queried_keywords": ["work bag"],
        "queried_window": None,
        "query_fingerprint": "a" * 64,
        "scope_attestation": None,
        "note": None,
        "collection_plan_digest": None,
        "evidence_contract_version": 1,
        "completed_at": NOW,
    }
    assert original[TABLES[2]][0]["recorded_at"] == receipt.event.recorded_at
    assert all(
        original[TABLES[2]][0][key] is None
        for key in (
            "occurred_at",
            "work_id",
            "handoff_id",
            "finding_id",
            "claim_id",
            "reason",
        )
    )
    assert original[TABLES[2]][0]["evidence_references"] == []
    assert await case.repository.commit_probe_outcomes(_command(mission, second, first)) == receipt
    assert _state(case) == original
    third = replace(first, outcome_id=uuid4(), connector_surface="youtube.comments")
    assert (await case.repository.commit_probe_outcomes(_command(mission, third))).event.cursor.position == (2, 1)
    following = _state(case)
    assert await case.repository.commit_probe_outcomes(command) == receipt
    assert _state(case) == following


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize(
    "changes",
    (
        {"outcome_id": UUID("00000000-0000-4000-8000-000000000001")},
        {"status": ChannelHealthStatus.DEGRADED, "note": "Partial access"},
        {"scope_attestation": {"geo": "US"}},
        {"completed_at": NOW + timedelta(seconds=1)},
        {"query_fingerprint": "b" * 64},
    ),
)
async def test_changed_fact_refuses_without_overwriting_original(commit_case, changes):
    case, mission, outcome = commit_case
    await case.repository.commit_probe_outcomes(_command(mission, outcome))
    original = _state(case)
    with pytest.raises(RepositoryException):
        await case.repository.commit_probe_outcomes(_command(mission, replace(outcome, **changes)))
    assert _state(case) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_disjoint_legacy_batches_publish_and_overlap_refuses_all(commit_case):
    case, mission, first = commit_case
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    assert await case.repository.record_probe_outcomes(first.run_id, [first]) == 1
    assert await case.repository.record_probe_outcomes(first.run_id, [second]) == 1
    original = _state(case)
    assert sorted(row["revision"] for row in original[TABLES[2]]) == [1, 2]
    assert len({row["command_key"] for row in original[TABLES[3]]}) == 2
    third = replace(first, outcome_id=uuid4(), connector_surface="youtube.comments")
    with pytest.raises(RepositoryException):
        await case.repository.record_probe_outcomes(first.run_id, [third, second])
    assert _state(case) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_recursive_values_persist_from_admitted_immutable_snapshot(commit_case):
    case, mission, outcome = commit_case

    class Scope(Enum):
        DETAILS = {"geo": "VN", "samples": [1, 2]}

    metadata = {
        "scope": Scope.DETAILS,
        "nested": [{"instant": NOW.astimezone(timezone(timedelta(hours=7))), "id": outcome.outcome_id}],
        "unknown": None,
    }
    command = _command(mission, replace(outcome, scope_attestation=metadata))
    Scope.DETAILS.value["geo"] = "US"
    Scope.DETAILS.value["samples"].append(3)
    metadata["nested"].clear()
    receipt = await case.repository.commit_probe_outcomes(command)
    row = _state(case)[TABLES[0]][0]
    assert row["scope_attestation"] == {
        "scope": {"geo": "VN", "samples": [1, 2]},
        "nested": [{"instant": "2026-10-04T00:00:00+00:00", "id": str(outcome.outcome_id)}],
        "unknown": None,
    }
    assert row["completed_at"] == NOW
    assert await case.repository.commit_probe_outcomes(command) == receipt


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_journal_authority_and_empty_legacy_unknown_run(commit_case):
    case, mission, outcome = commit_case
    other = ResearchMission(title="Other mission", keywords=["other scope"], workspace_id=mission.workspace_id)
    await case.repository.save_mission(other)
    original = _state(case)
    with pytest.raises(RepositoryException):
        await case.repository.commit_probe_outcomes(_command(other, outcome))
    with pytest.raises(RepositoryException):
        await case.repository.commit_probe_outcomes(_command(mission, replace(outcome, run_id=uuid4())))
    assert await case.repository.record_probe_outcomes(uuid4(), []) == 0
    assert await case.repository.record_probe_outcomes(outcome.run_id, []) == 0
    assert _state(case) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_manifest_complete_batch_required_and_empty_refused(commit_case):
    case, mission, outcome = commit_case
    await case.repository.save_mission_manifest(
        MissionManifest(
            mission_id=mission.id,
            outcome="Record every allowed surface",
            decision_context=None,
            required_channels=("youtube",),
            optional_channels=("threads",),
            authority_boundary=AuthorityBoundary(
                public_http=True, official_api=True, browser_session=False, paid_quota=False
            ),
            quota_budget={},
            output_type=MissionOutputType.COLLECTION_FRAME,
            stop_conditions=("one run",),
            analysis_policy="evidence-gated-v1",
            retention_policy="mission-only",
            created_by="commit-test",
            confirmed_at=NOW,
        )
    )
    original = _state(case)
    first = replace(outcome, scope_attestation={"geo": "VN"}, note="Empty query", collection_plan_digest="b" * 64)
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    for batch in ([], [first], [first, replace(second, collection_plan_digest="c" * 64)]):
        with pytest.raises(InvalidEvidenceQualificationError):
            await case.repository.record_probe_outcomes(outcome.run_id, batch)
        assert _state(case) == original
    assert await case.repository.record_probe_outcomes(outcome.run_id, [first, second]) == 2
    assert [len(rows) for rows in _state(case).values()] == [2, 1, 1, 1]
    assert all(
        row["scope_attestation"] == {"geo": "VN"}
        and row["note"] == "Empty query"
        and row["collection_plan_digest"] == "b" * 64
        and row["evidence_contract_version"] == 2
        for row in _state(case)[TABLES[0]]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize("table", TABLES)
async def test_real_server_write_refusal_rolls_back_every_publication_row(commit_case, table):
    case, mission, outcome = commit_case
    original = _state(case)
    with _refuse_write(case, table):
        with pytest.raises((RepositoryException, psycopg.Error)):
            await case.repository.commit_probe_outcomes(_command(mission, outcome))
    assert _state(case) == original
    assert (await case.repository.commit_probe_outcomes(_command(mission, outcome))).event.cursor.position == (1, 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_plain_table_owner_can_publish_with_progress_rls_intact(commit_case):
    case, mission, outcome = commit_case
    await case.repository.close()
    with runtime_owner(case.dsn) as owner_dsn:
        repository = PostgresTimescaleRepository(owner_dsn, min_pool_size=1, max_pool_size=1)
        try:
            receipt = await repository.commit_probe_outcomes(_command(mission, outcome))
            assert receipt.event.cursor.position == (1, 1)
            assert await repository.commit_probe_outcomes(_command(mission, outcome)) == receipt
            with psycopg.connect(owner_dsn) as conn:
                assert conn.execute(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                ).fetchone() == (False, False)
                assert (
                    conn.execute(
                        "SELECT count(*) FROM pg_class WHERE relname = ANY(%s) AND relrowsecurity AND NOT relforcerowsecurity",
                        (list(TABLES[1:]),),
                    ).fetchone()[0]
                    == 3
                )
        finally:
            await repository.close()


class _CursorBoundary:
    def __init__(self, cursor, boundary):
        self.cursor, self.boundary = cursor, boundary

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    async def execute(self, statement, *args, **kwargs):
        if "INSERT INTO mission_progress_revisions" in str(statement) and self.boundary.admission is not None:
            self.boundary.admission.set()
            await self.boundary.admit.wait()
        if "SELECT revision FROM mission_progress_revisions" in str(statement):
            assert self.boundary.bootstrap_completed.is_set()
            self.boundary.revision_select_started.set()
        result = await self.cursor.execute(statement, *args, **kwargs)
        if "INSERT INTO mission_progress_revisions" in str(statement):
            self.boundary.bootstrap_completed.set()
        if "SELECT revision FROM mission_progress_revisions" in str(statement) and self.boundary.hold_revision_lock:
            self.boundary.revision_locked.set()
            await self.boundary.continue_revision.wait()
        return result


class _ConnectionBoundary:
    def __init__(self, connection, boundary):
        self.connection, self.boundary = connection, boundary

    def __getattr__(self, name):
        return getattr(self.connection, name)

    @asynccontextmanager
    async def cursor(self, *args, **kwargs):
        async with self.connection.cursor(*args, **kwargs) as cursor:
            yield _CursorBoundary(cursor, self.boundary)


class _PoolBoundary:
    """Schedule only physical admission and context COMMIT; SQL/rollback stay real."""

    def __init__(self, pool, *, delay_admission=False, hold_revision_lock=False, hold_commit=True):
        self.pool = pool
        self.admission = asyncio.Event() if delay_admission else None
        self.hold_revision_lock, self.hold_commit = hold_revision_lock, hold_commit
        self.bootstrap_completed, self.revision_select_started = asyncio.Event(), asyncio.Event()
        self.revision_locked, self.continue_revision = asyncio.Event(), asyncio.Event()
        self.admit, self.entered, self.release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        self.connection_handle = None

    def __getattr__(self, name):
        return getattr(self.pool, name)

    @asynccontextmanager
    async def connection(self, *args, **kwargs):
        async with self.pool.connection(*args, **kwargs) as connection:
            self.connection_handle = connection
            yield _ConnectionBoundary(connection, self)
            assert connection.info.transaction_status == TransactionStatus.INTRANS
            if self.hold_commit:
                self.entered.set()
                await self.release.wait()


async def _reached(event):
    await asyncio.wait_for(event.wait(), 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_contended_revisions_follow_real_lock_and_commit_order(commit_case):
    case, mission, first = commit_case
    second = replace(
        first, outcome_id=uuid4(), connector_surface="youtube.comments", completed_at=NOW - timedelta(days=1)
    )
    repository_a = case.repository
    repository_b = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    a = _PoolBoundary(await repository_a._get_pool(), delay_admission=True)
    b = _PoolBoundary(await repository_b._get_pool())
    repository_a._pool, repository_b._pool = a, b
    tasks = []
    try:
        earlier = asyncio.create_task(repository_a.commit_probe_outcomes(_command(mission, first)))
        tasks.append(earlier)
        await _reached(a.admission)
        later = asyncio.create_task(repository_b.commit_probe_outcomes(_command(mission, second)))
        tasks.append(later)
        await _reached(b.entered)
        a.admit.set()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(earlier), 0.05)
        with psycopg.connect(case.dsn) as conn:
            blocked = conn.execute("SELECT pg_blocking_pids(%s)", (a.connection_handle.info.backend_pid,)).fetchone()[0]
        assert b.connection_handle.info.backend_pid in blocked
        assert [len(rows) for rows in _state(case).values()] == [0, 0, 0, 0]
        b.release.set()
        receipt_b = await later
        assert receipt_b.event.cursor.position == (1, 1)
        await _reached(a.entered)
        visible = _state(case)
        assert [len(rows) for rows in visible.values()] == [1, 1, 1, 1]
        assert visible[TABLES[0]][0]["id"] == second.outcome_id
        a.release.set()
        assert (await earlier).event.cursor.position == (2, 1)
        print("T011_REAL_LOCK_ORDER B:held -> A:blocked -> B:committed:1 -> A:committed:2")
    finally:
        a.admit.set()
        a.release.set()
        b.release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
        await repository_b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
async def test_cross_connection_identical_retries_commit_one_original_receipt(commit_case):
    case, mission, outcome = commit_case
    other = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    try:
        receipts = await asyncio.gather(
            case.repository.commit_probe_outcomes(_command(mission, outcome)),
            other.commit_probe_outcomes(_command(mission, outcome)),
        )
        assert receipts[0] == receipts[1]
        assert [len(rows) for rows in _state(case).values()] == [1, 1, 1, 1]
    finally:
        await other.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize("replay", [False, True], ids=["distinct-publication", "original-replay"])
async def test_existing_control_row_serializes_at_revision_select_before_receipt(commit_case, replay):
    """Removing the row lock must expose an unblocked SELECT or an early original receipt."""
    case, mission, first = commit_case
    seed = replace(first, outcome_id=uuid4(), connector_surface="youtube.seed")
    original_receipt = await case.repository.commit_probe_outcomes(_command(mission, seed))
    assert original_receipt.event.cursor.position == (1, 1)
    seeded = _state(case)
    second = replace(first, outcome_id=uuid4(), connector_surface="youtube.comments")
    repository_a = case.repository
    repository_b = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    a = _PoolBoundary(await repository_a._get_pool(), delay_admission=True, hold_commit=not replay)
    b = _PoolBoundary(await repository_b._get_pool(), hold_revision_lock=True)
    repository_a._pool, repository_b._pool = a, b
    tasks = []
    try:
        earlier = asyncio.create_task(repository_a.commit_probe_outcomes(_command(mission, seed if replay else first)))
        tasks.append(earlier)
        await _reached(a.admission)
        later = asyncio.create_task(repository_b.commit_probe_outcomes(_command(mission, second)))
        tasks.append(later)
        # B holds a real row lock before writing facts or updating the revision tuple.
        await _reached(b.revision_locked)
        assert not b.entered.is_set()
        assert _state(case) == seeded
        a.admit.set()
        # A demonstrably passed INSERT; the measured blocker belongs to the SELECT.
        await _reached(a.bootstrap_completed)
        await _reached(a.revision_select_started)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(earlier), 0.05)
        with psycopg.connect(case.dsn) as conn:
            blocked = conn.execute("SELECT pg_blocking_pids(%s)", (a.connection_handle.info.backend_pid,)).fetchone()[0]
        assert b.connection_handle.info.backend_pid in blocked, (
            "Existing revision SELECT did not wait for its real row-lock owner"
        )
        assert not a.entered.is_set()
        assert _state(case) == seeded
        b.continue_revision.set()
        await _reached(b.entered)
        assert _state(case) == seeded
        b.release.set()
        receipt_b = await later
        assert receipt_b.event.cursor.position == (2, 1)
        if replay:
            assert await earlier == original_receipt
            assert [len(rows) for rows in _state(case).values()] == [2, 1, 2, 2]
            assert _state(case)[TABLES[1]][0]["revision"] == 2
        else:
            await _reached(a.entered)
            visible = _state(case)
            assert [len(rows) for rows in visible.values()] == [2, 1, 2, 2]
            assert {row["id"] for row in visible[TABLES[0]]} == {seed.outcome_id, second.outcome_id}
            assert visible[TABLES[1]][0]["revision"] == 2
            a.release.set()
            assert (await earlier).event.cursor.position == (3, 1)
            assert [len(rows) for rows in _state(case).values()] == [3, 1, 3, 3]
            assert _state(case)[TABLES[1]][0]["revision"] == 3
        print(
            "T011_EXISTING_ROW_LOCK seed:1 -> B:SELECT-locked-before-UPDATE -> A:INSERT-passed -> A:SELECT-blocked -> B:committed:2 -> A:"
            + ("original-receipt:1" if replay else "committed:3")
        )
    finally:
        a.admit.set()
        a.release.set()
        b.continue_revision.set()
        b.release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
        await repository_b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize("refuse_commit,cancel", [(False, False), (True, False), (False, True), (True, True)])
async def test_commit_settles_before_receipt_or_reuse_despite_repeated_cancellation(commit_case, refuse_commit, cancel):
    case, mission, outcome = commit_case
    await case.repository.close()
    repository = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    real_pool = await repository._get_pool()
    boundary = _PoolBoundary(real_pool)
    repository._pool = boundary
    tasks = []
    refusal = _refuse_write(case, "mission_progress_events", deferred=True) if refuse_commit else nullcontext()
    try:
        with refusal:
            owner = asyncio.create_task(repository.commit_probe_outcomes(_command(mission, outcome)))
            tasks.append(owner)
            await _reached(boundary.entered)
            if cancel:
                owner.cancel()
                await asyncio.sleep(0)
                owner.cancel()

            async def reuse():
                async with real_pool.connection() as conn:
                    assert conn.info.transaction_status == TransactionStatus.IDLE
                    return conn.info.backend_pid

            competing = asyncio.create_task(reuse())
            tasks.append(competing)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(competing), 0.05)
            assert not owner.done()
            assert boundary.connection_handle.info.transaction_status == TransactionStatus.INTRANS
            assert [len(rows) for rows in _state(case).values()] == [0, 0, 0, 0]
            pid = boundary.connection_handle.info.backend_pid
            boundary.release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await owner
            elif refuse_commit:
                with pytest.raises((psycopg.Error, RepositoryException)):
                    await owner
            else:
                assert (await owner).event.cursor.position == (1, 1)
            assert await competing == pid
            assert boundary.connection_handle.info.transaction_status == TransactionStatus.IDLE
            assert [len(rows) for rows in _state(case).values()] == ([0, 0, 0, 0] if refuse_commit else [1, 1, 1, 1])
        repository._pool = real_pool
        assert (await repository.commit_probe_outcomes(_command(mission, outcome))).event.cursor.position == (1, 1)
    finally:
        boundary.release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
        await repository.close()
