"""Behavioral RED contracts for atomic probe facts and mission progress receipts.

Removing event publication, committing it separately, ordering by occurrence time, or
replaying a command as a new write must break these tests. No future module is imported
and no event schema or transaction implementation is fabricated by the test suite.
"""

import asyncio
import sqlite3
import threading
from contextlib import closing, contextmanager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio

from ignis.application.cancellation import await_settled
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import MissionProbeOutcome, ResearchWorkspace


NOW = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)


@contextmanager
def _connection(case):
    if case.name == "sqlite":
        with closing(sqlite3.connect(case.repository._db_path)) as conn:
            yield conn
    else:
        with psycopg.connect(case.dsn) as conn:
            yield conn


def _events(case, mission_id):
    """Read durable receipts independently; absent storage is zero receipts, not success."""
    with _connection(case) as conn:
        if case.name == "sqlite":
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'mission_progress_events'"
            ).fetchone()
        else:
            exists = conn.execute("SELECT to_regclass('mission_progress_events')").fetchone()[0]
        if not exists:
            return []
        placeholder = "?" if case.name == "sqlite" else "%s"
        rows = conn.execute(
            "SELECT revision, ordinal, run_id FROM mission_progress_events"
            f" WHERE mission_id = {placeholder} ORDER BY revision, ordinal",
            (str(mission_id),),
        ).fetchall()
        return [(int(revision), int(ordinal), str(run_id)) for revision, ordinal, run_id in rows]


def _outcome_count(case, run_id):
    return case.query_one(
        "SELECT count(*) FROM mission_probe_outcomes WHERE run_id = ?",
        "SELECT count(*) FROM mission_probe_outcomes WHERE run_id = %s",
        (str(run_id),),
    )[0]


@pytest_asyncio.fixture
async def progress_case(repository_case, tmp_path):
    repository = repository_case.repository
    workspace = ResearchWorkspace(slug="progress-contract", root_path=tmp_path / "workspace")
    await repository.save_research_workspace(workspace)
    mission = ResearchMission(
        title="Probe progress contract", keywords=["work bag"], workspace_id=workspace.workspace_id
    )
    await repository.save_mission(mission)
    outcomes = []
    for sequence in (1, 2):
        run_id = uuid4()
        await repository.record_run_journal(
            RunJournal(
                run_id=run_id,
                mission_id=mission.id,
                workspace_id=workspace.workspace_id,
                journal_path=tmp_path / f"{run_id}.md",
                sequence=sequence,
                status="COMPLETED",
                started_at=NOW,
                completed_at=NOW,
            )
        )
        outcomes.append(
            MissionProbeOutcome(
                run_id=run_id,
                platform="youtube",
                connector_surface="youtube.search",
                status=ChannelHealthStatus.EMPTY_NO_DATA,
                signals_collected=0,
                queried_keywords=("work bag",),
                queried_window="30d",
                query_fingerprint="a" * 64,
                completed_at=NOW,
            )
        )
    return repository_case, mission, outcomes


@contextmanager
def _deny_sqlite_insert(repository, table, monkeypatch):
    """Fault only the actual SQL write; preserve the real repository and its transactions."""
    original = repository._get_connection

    def connect():
        conn = original()

        def authorize(action, name, _column, _database, _trigger):
            if action == sqlite3.SQLITE_INSERT and name == table:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        return conn

    with monkeypatch.context() as patch:
        patch.setattr(repository, "_get_connection", connect)
        yield


class _ScheduledSqliteConnection:
    """Schedule real lock acquisition/commit without replacing any business SQL."""

    def __init__(self, connection, label, events, trace):
        self.connection = connection
        self.label = label
        self.events = events
        self.trace = trace
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def _wait(self, name):
        assert self.events[name].wait(5), f"SQL schedule did not release {name}"

    def execute(self, statement, *args, **kwargs):
        if self.label == "A" and statement.strip().upper() == "BEGIN IMMEDIATE":
            self.trace.append("A:begin-held")
            self.events["a_started"].set()
            self._wait("a_begin")
            timeout = self.connection.execute("PRAGMA busy_timeout").fetchone()[0]
            self.connection.execute("PRAGMA busy_timeout = 0")
            try:
                return self.connection.execute(statement, *args, **kwargs)
            except sqlite3.OperationalError as exc:
                if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                    raise
                self.trace.append("A:SQLITE_BUSY")
                self.events["a_busy"].set()
            finally:
                self.connection.execute(f"PRAGMA busy_timeout = {timeout}")
            # Only retry the same lock-acquisition statement for the controlled schedule.
            # Fact/event writes and commit/rollback still belong to the real repository.
            self._wait("b_committed")
        return self.connection.execute(statement, *args, **kwargs)

    def commit(self):
        assert self.connection.in_transaction, "Commit hold must own a real transaction"
        label = self.label.lower()
        self.trace.append(f"{self.label}:commit-held")
        self.events[f"{label}_held"].set()
        self._wait(f"{label}_commit")
        self.connection.commit()
        self.trace.append(f"{self.label}:committed")
        self.events[f"{label}_committed"].set()

    def close(self):
        self.connection.close()
        self.closed = True


async def _wait_for_sql_boundary(event, boundary):
    assert await asyncio.to_thread(event.wait, 5), f"SQL boundary not reached: {boundary}"


async def _settle_sql_workers(tasks):
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_committed_outcome_has_durable_progress_receipt(progress_case):
    case, mission, outcomes = progress_case
    before = _events(case, mission.id)
    await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    assert _outcome_count(case, outcomes[0].run_id) == 1
    new_events = [row for row in _events(case, mission.id) if row not in before]
    assert new_events, "A committed probe fact has no durable progress receipt"
    assert {row[2] for row in new_events} == {str(outcomes[0].run_id)}


@pytest.mark.asyncio
async def test_event_write_refusal_rolls_back_probe_fact(progress_case, monkeypatch):
    case, mission, outcomes = progress_case
    if case.name != "sqlite":
        await _assert_postgres_legacy_refusal(case, mission, outcomes, "mission_progress_events")
        return
    before = _events(case, mission.id)
    with _deny_sqlite_insert(case.repository, "mission_progress_events", monkeypatch):
        with pytest.raises((sqlite3.DatabaseError, RepositoryException)):
            await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    assert _outcome_count(case, outcomes[0].run_id) == 0
    assert _events(case, mission.id) == before
    await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    new_events = [row for row in _events(case, mission.id) if row not in before]
    assert new_events, "Retry after rollback must commit a receipt"
    high_water = max((row[0] for row in before), default=0)
    assert {row[0] for row in new_events} == {high_water + 1}


@pytest.mark.asyncio
async def test_fact_write_refusal_leaves_no_progress_receipt(progress_case, monkeypatch):
    case, mission, outcomes = progress_case
    if case.name != "sqlite":
        await _assert_postgres_legacy_refusal(case, mission, outcomes, "mission_probe_outcomes")
        return
    before = _events(case, mission.id)
    with _deny_sqlite_insert(case.repository, "mission_probe_outcomes", monkeypatch):
        with pytest.raises((sqlite3.DatabaseError, RepositoryException)):
            await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    assert _outcome_count(case, outcomes[0].run_id) == 0
    assert _events(case, mission.id) == before


@pytest.mark.asyncio
async def test_revision_order_follows_commit_not_occurrence_time(progress_case):
    case, mission, outcomes = progress_case
    before = _events(case, mission.id)
    first = outcomes[0]
    second = replace(outcomes[1], completed_at=NOW - timedelta(days=1))
    await case.repository.record_probe_outcomes(first.run_id, [first])
    first_events = [row for row in _events(case, mission.id) if row not in before]
    assert first_events, "First commit must publish its own revision"
    await case.repository.record_probe_outcomes(second.run_id, [second])
    second_events = [
        row for row in _events(case, mission.id) if row not in before + first_events
    ]
    assert second_events, "Second commit must publish its own revision"
    assert {row[2] for row in second_events} == {str(second.run_id)}
    assert min(row[0] for row in second_events) == max(row[0] for row in first_events) + 1


@pytest.mark.asyncio
async def test_distinct_commands_allocate_revisions_in_contended_commit_order(
    progress_case, monkeypatch
):
    """Pre-allocation in invocation order must fail when B commits before earlier A."""
    case, mission, outcomes = progress_case
    if case.name != "sqlite":
        await _assert_postgres_legacy_commit_order(case, mission, outcomes)
        return
    repository_a = case.repository
    repository_b = type(repository_a)(repository_a._db_path)
    events = {
        name: threading.Event()
        for name in (
            "a_started", "a_begin", "a_busy", "a_held", "a_commit", "a_committed",
            "b_held", "b_commit", "b_committed",
        )
    }
    trace, connections, tasks = [], [], []
    before = _events(case, mission.id)
    try:
        # Both repositories finish schema initialization before any transaction is held.
        await repository_b._ensure_schema()
        with monkeypatch.context() as patch:
            for repository, label in ((repository_a, "A"), (repository_b, "B")):
                original = repository._get_connection

                def connect(original=original, label=label):
                    connection = _ScheduledSqliteConnection(original(), label, events, trace)
                    connections.append(connection)
                    return connection

                patch.setattr(repository, "_get_connection", connect)
            try:
                tasks.append(asyncio.create_task(
                    repository_a.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
                ))
                await _wait_for_sql_boundary(events["a_started"], "A before BEGIN")
                tasks.append(asyncio.create_task(
                    repository_b.record_probe_outcomes(outcomes[1].run_id, outcomes[1:])
                ))
                await _wait_for_sql_boundary(events["b_held"], "B before COMMIT")
                events["a_begin"].set()
                await _wait_for_sql_boundary(events["a_busy"], "A observed SQLITE_BUSY")
                # A genuinely contended for B's write lock; neither open write is visible.
                contended_facts = [_outcome_count(case, outcome.run_id) for outcome in outcomes]
                contended_events = _events(case, mission.id)
                events["b_commit"].set()
                await tasks[1]
                await _wait_for_sql_boundary(events["a_held"], "A before COMMIT")
                # B's fact and receipt must be coherent while A remains uncommitted.
                middle_facts = [_outcome_count(case, outcome.run_id) for outcome in outcomes]
                middle_events = _events(case, mission.id)
                events["a_commit"].set()
                results = await asyncio.gather(*tasks)
            finally:
                # Release every held worker before awaiting settlement or restoring patches.
                # This also runs when a boundary assertion fails or this test is cancelled.
                for event in events.values():
                    event.set()
                await await_settled(_settle_sql_workers(tasks))
    finally:
        await repository_b.close()

    assert all(connection.closed for connection in connections)
    final_events = _events(case, mission.id)
    final_facts = [_outcome_count(case, outcome.run_id) for outcome in outcomes]
    print("SQLITE_OVERLAP " + " -> ".join(trace))
    print(
        f"SQLITE_VISIBILITY contended_facts={contended_facts} "
        f"first_commit_facts={middle_facts} final_facts={final_facts} "
        f"receipts={len(contended_events)},{len(middle_events)},{len(final_events)} "
        f"write_connections_closed={len(connections)}"
    )
    assert trace == [
        "A:begin-held", "B:commit-held", "A:SQLITE_BUSY", "B:committed",
        "A:commit-held", "A:committed",
    ]
    assert results == [1, 1]
    assert contended_facts == [0, 0]
    assert contended_events == before
    assert middle_facts == [0, 1]
    b_events = [row for row in middle_events if row not in before]
    assert b_events, "B committed first under real contention but has no durable receipt"
    assert {row[2] for row in b_events} == {str(outcomes[1].run_id)}
    high_water = max((row[0] for row in before), default=0)
    assert {row[0] for row in b_events} == {high_water + 1}
    a_events = [row for row in final_events if row not in middle_events]
    assert a_events, "A committed second but has no durable receipt"
    assert {row[2] for row in a_events} == {str(outcomes[0].run_id)}
    assert {row[0] for row in a_events} == {high_water + 2}
    assert len(final_events) == len({row[:2] for row in final_events})
    assert final_facts == [1, 1]


async def _assert_postgres_legacy_refusal(case, mission, outcomes, table):
    """Run the original legacy refusal/retry contract against real server writes."""
    from test_postgres_probe_outcome_commits import _refuse_write, _state

    before, original = _events(case, mission.id), _state(case)
    with _refuse_write(case, table):
        with pytest.raises((RepositoryException, psycopg.Error)):
            await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    assert _outcome_count(case, outcomes[0].run_id) == 0
    assert _events(case, mission.id) == before
    assert _state(case) == original
    assert await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1]) == 1
    new_events = [row for row in _events(case, mission.id) if row not in before]
    assert new_events, "Retry after rollback must commit a receipt"
    high_water = max((row[0] for row in before), default=0)
    assert {row[0] for row in new_events} == {high_water + 1}
    assert {row[2] for row in new_events} == {str(outcomes[0].run_id)}
    assert _outcome_count(case, outcomes[0].run_id) == 1
    assert _outcome_count(case, outcomes[1].run_id) == 0
    assert [len(rows) for rows in _state(case).values()] == [1, 1, 1, 1]


async def _assert_postgres_legacy_commit_order(case, mission, outcomes):
    """Hold actual SQL admission and COMMIT for two independently selected runs."""
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
    from test_postgres_probe_outcome_commits import _PoolBoundary, _reached, _state

    repository_a = case.repository
    repository_b = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    a = _PoolBoundary(await repository_a._get_pool(), delay_admission=True)
    b = _PoolBoundary(await repository_b._get_pool())
    repository_a._pool, repository_b._pool = a, b
    before = _events(case, mission.id)
    high_water = max((row[0] for row in before), default=0)
    tasks = []
    try:
        earlier = asyncio.create_task(repository_a.record_probe_outcomes(outcomes[0].run_id, outcomes[:1]))
        tasks.append(earlier)
        await _reached(a.admission)
        later = asyncio.create_task(repository_b.record_probe_outcomes(outcomes[1].run_id, outcomes[1:]))
        tasks.append(later)
        await _reached(b.entered)
        a.admit.set()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(earlier), 0.05)
        with psycopg.connect(case.dsn) as conn:
            blocked = conn.execute("SELECT pg_blocking_pids(%s)", (a.connection_handle.info.backend_pid,)).fetchone()[0]
        assert b.connection_handle.info.backend_pid in blocked
        assert [_outcome_count(case, outcome.run_id) for outcome in outcomes] == [0, 0]
        assert _events(case, mission.id) == before
        assert [len(rows) for rows in _state(case).values()] == [0, 0, 0, 0]
        b.release.set()
        assert await later == 1
        await _reached(a.entered)
        middle = _events(case, mission.id)
        assert [_outcome_count(case, outcome.run_id) for outcome in outcomes] == [0, 1]
        assert [row for row in middle if row not in before] == [(high_water + 1, 1, str(outcomes[1].run_id))]
        assert [len(rows) for rows in _state(case).values()] == [1, 1, 1, 1]
        a.release.set()
        assert await earlier == 1
        final = _events(case, mission.id)
        assert [row for row in final if row not in middle] == [(high_water + 2, 1, str(outcomes[0].run_id))]
        assert len(final) == len({row[:2] for row in final})
        assert [_outcome_count(case, outcome.run_id) for outcome in outcomes] == [1, 1]
        state = _state(case)
        assert [len(rows) for rows in state.values()] == [2, 1, 2, 2]
        assert state["mission_progress_revisions"][0]["revision"] == high_water + 2
        assert {str(row["run_id"]) for row in state["mission_progress_commands"]} == {str(outcome.run_id) for outcome in outcomes}
        print("T015_LEGACY_REAL_LOCK_ORDER B:held -> A:blocked -> B:committed:1 -> A:committed:2")
    finally:
        a.admit.set()
        a.release.set()
        b.release.set()
        await await_settled(_settle_sql_workers(tasks))
        repository_a._pool = a.pool
        repository_b._pool = b.pool
        await repository_b.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize("refuse_commit,cancel", [(False, False), (True, False), (False, True), (True, True)])
async def test_postgres_public_journal_writer_waits_for_legacy_publication_settlement(
    progress_case, refuse_commit, cancel
):
    """A competing public journal update cannot commit or change scope under publication."""
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
    from psycopg.pq import TransactionStatus
    from test_postgres_probe_outcome_commits import _PoolBoundary, _reached, _refuse_write, _state

    case, mission, outcomes = progress_case
    first = outcomes[0]
    other_mission = ResearchMission(title="Unrelated journal owner", keywords=["work bag"], workspace_id=mission.workspace_id)
    await case.repository.save_mission(other_mission)
    with psycopg.connect(case.dsn) as conn:
        journal_path = conn.execute("SELECT journal_path FROM mission_run_journals WHERE id=%s", (first.run_id,)).fetchone()[0]
    repository = case.repository
    competitor = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    owner_boundary = _PoolBoundary(await repository._get_pool())
    other_boundary = _PoolBoundary(await competitor._get_pool(), hold_commit=False)
    repository._pool, competitor._pool = owner_boundary, other_boundary
    original = _state(case)
    tasks = []
    refusal = _refuse_write(case, "mission_progress_events", deferred=True) if refuse_commit else nullcontext()
    try:
        with refusal:
            try:
                owner = asyncio.create_task(repository.record_probe_outcomes(first.run_id, [first]))
                tasks.append(owner)
                await _reached(owner_boundary.entered)
                if cancel:
                    owner.cancel()
                    await asyncio.sleep(0)
                    owner.cancel()
                competing = asyncio.create_task(competitor.record_run_journal(RunJournal(
                    run_id=uuid4(), mission_id=other_mission.id, workspace_id=mission.workspace_id,
                    journal_path=journal_path, sequence=99, status="FAILED", started_at=NOW, completed_at=NOW,
                )))
                tasks.append(competing)
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(competing), 0.05)
                with psycopg.connect(case.dsn) as conn:
                    blocked = conn.execute("SELECT pg_blocking_pids(%s)", (other_boundary.connection_handle.info.backend_pid,)).fetchone()[0]
                    assert conn.execute("SELECT id,mission_id,sequence,status FROM mission_run_journals WHERE journal_path=%s", (journal_path,)).fetchone() == (first.run_id, mission.id, 1, "COMPLETED")
                assert owner_boundary.connection_handle.info.backend_pid in blocked
                assert not owner.done()
                assert _state(case) == original
                owner_boundary.release.set()
                if cancel:
                    with pytest.raises(asyncio.CancelledError):
                        await owner
                elif refuse_commit:
                    with pytest.raises((RepositoryException, psycopg.Error)):
                        await owner
                else:
                    assert await owner == 1
                await competing
                assert owner_boundary.connection_handle.info.transaction_status == TransactionStatus.IDLE
                assert other_boundary.connection_handle.info.transaction_status == TransactionStatus.IDLE
                assert [len(rows) for rows in _state(case).values()] == ([0, 0, 0, 0] if refuse_commit else [1, 1, 1, 1])
            finally:
                # Trigger teardown needs the held transaction's lock; settle it first.
                owner_boundary.release.set()
                await await_settled(_settle_sql_workers(tasks))
        with psycopg.connect(case.dsn) as conn:
            assert conn.execute("SELECT id,mission_id,sequence,status FROM mission_run_journals WHERE journal_path=%s", (journal_path,)).fetchone() == (first.run_id, mission.id, 1, "FAILED")
        repository._pool = owner_boundary.pool
        assert await repository.record_probe_outcomes(first.run_id, [first]) == 1
        assert _events(case, mission.id) == [(1, 1, str(first.run_id))]
        assert _events(case, other_mission.id) == []
    finally:
        owner_boundary.release.set()
        await await_settled(_settle_sql_workers(tasks))
        repository._pool = owner_boundary.pool
        competitor._pool = other_boundary.pool
        await competitor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("repository_case", ["postgres"], indirect=True)
@pytest.mark.parametrize("interruption", ("assertion", "cancellation"))
async def test_public_journal_early_failure_releases_workers_before_trigger_teardown(
    progress_case, monkeypatch, interruption
):
    """A finite server timeout exposes wrong teardown order without hanging this loop."""
    import test_postgres_probe_outcome_commits as controls
    from psycopg.pq import TransactionStatus

    case, _mission, _outcomes = progress_case
    connect, reached = psycopg.connect, controls._reached
    injected = False

    def bounded_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        # SET LOCAL expires on transaction exit; no server/async-pool setting changes.
        try:
            connection.execute("SET LOCAL lock_timeout = '250ms'")
        except BaseException:
            connection.close()
            raise
        return connection

    async def interrupt_after_actual_commit_hold(event):
        nonlocal injected
        await reached(event)
        injected = True
        if interruption == "assertion":
            raise AssertionError("Controlled early journal assertion")
        asyncio.current_task().cancel()
        await asyncio.sleep(0)

    observed = None
    with monkeypatch.context() as patch:
        patch.setattr(psycopg, "connect", bounded_connect)
        patch.setattr(controls, "_reached", interrupt_after_actual_commit_hold)
        invocation = asyncio.create_task(
            test_postgres_public_journal_writer_waits_for_legacy_publication_settlement(
                progress_case, refuse_commit=True, cancel=False
            )
        )
        try:
            await invocation
        except (Exception, asyncio.CancelledError) as exc:
            observed = exc
        finally:
            # OLD teardown can leave fixture DDL after its bounded lock refusal. Workers
            # have now settled in the target's outer finally; clean only that orphan DDL.
            with psycopg.connect(case.dsn) as conn:
                trigger_count = conn.execute("SELECT count(*) FROM pg_trigger WHERE tgname='t011_refuse'").fetchone()[0]
                function_count = conn.execute("SELECT count(*) FROM pg_proc WHERE proname='t011_refuse' AND pronamespace='public'::regnamespace").fetchone()[0]
                conn.execute("DROP TRIGGER IF EXISTS t011_refuse ON mission_progress_events")
                conn.execute("DROP FUNCTION IF EXISTS t011_refuse()")
        async with (await case.repository._get_pool()).connection() as conn:
            assert conn.info.transaction_status == TransactionStatus.IDLE
            cursor = await conn.execute("SELECT 1")
            assert await cursor.fetchone() == (1,)
    print(
        f"T015_EARLY_TEARDOWN interruption={interruption} error={type(observed).__name__}"
        f" sqlstate={getattr(observed, 'sqlstate', None)} residual_trigger={trigger_count}"
        f" residual_function={function_count} task_settled={invocation.done()}"
    )
    assert injected and invocation.done()
    assert trigger_count == function_count == 0
    assert type(observed) is (AssertionError if interruption == "assertion" else asyncio.CancelledError)
    if interruption == "assertion":
        assert str(observed) == "Controlled early journal assertion"
    assert [len(rows) for rows in controls._state(case).values()] == [0, 0, 0, 0]


@pytest.mark.asyncio
async def test_identical_retry_reuses_fact_and_progress_revision(progress_case):
    case, mission, outcomes = progress_case
    original_result = await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    before = _events(case, mission.id)
    try:
        retry_result = await case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1])
    except RepositoryException:
        pytest.fail("Identical committed retry was refused instead of returning its original result")
    assert before, "Replay requires an original durable receipt"
    assert retry_result == original_result
    assert _outcome_count(case, outcomes[0].run_id) == 1
    assert _events(case, mission.id) == before


@pytest.mark.asyncio
async def test_concurrent_retries_commit_one_fact_and_one_revision(progress_case):
    case, mission, outcomes = progress_case
    before = _events(case, mission.id)
    results = await asyncio.gather(
        case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1]),
        case.repository.record_probe_outcomes(outcomes[0].run_id, outcomes[:1]),
        return_exceptions=True,
    )
    assert not any(isinstance(result, BaseException) for result in results), (
        "Racing identical retries must both resolve to the committed result"
    )
    assert results == [1, 1]
    assert _outcome_count(case, outcomes[0].run_id) == 1
    new_events = [row for row in _events(case, mission.id) if row not in before]
    assert new_events, "Racing retries must leave a durable receipt"
    assert len({row[0] for row in new_events}) == 1
    assert len(new_events) == len(set(new_events))


@pytest.mark.asyncio
async def test_conflicting_retry_preserves_original_fact_and_receipts(progress_case):
    case, mission, outcomes = progress_case
    original = outcomes[0]
    await case.repository.record_probe_outcomes(original.run_id, [original])
    before = _events(case, mission.id)
    conflicting = replace(original, status=ChannelHealthStatus.DEGRADED, note="Partial access")
    with pytest.raises(RepositoryException):
        await case.repository.record_probe_outcomes(original.run_id, [conflicting])
    stored = case.query_one(
        "SELECT count(*), min(status), min(note) FROM mission_probe_outcomes WHERE run_id = ?",
        "SELECT count(*), min(status), min(note) FROM mission_probe_outcomes WHERE run_id = %s",
        (str(original.run_id),),
    )
    assert stored == (1, "EMPTY_NO_DATA", None)
    assert _events(case, mission.id) == before
