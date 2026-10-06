"""Future US4 transactional contracts on physical stores, never synthetic schemas.

Absent APIs fail inside each test. API RED is not evidence that rollback or CAS ran.
The imported fixture owns real file/memory SQLite and disposable local PostgreSQL.
"""
import asyncio
import importlib
import sqlite3
import threading
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql

from tests.integration.test_mission_relay_read_boundary import NOW, _state, relay_case


TABLES = ("research_assignments", "research_work_items", "research_handoffs", "research_finding_revisions")


def _api(repository):
    for name in ("commit_research_work", "load_research_work"):
        if not callable(getattr(repository, name, None)):
            pytest.fail(f"T042 API RED: repository.{name} is not implemented", pytrace=False)
    modules = []
    for name in ("ignis.domain.research_work", "ignis.application.ports.research_work_port"):
        try:
            modules.append(importlib.import_module(name))
        except ModuleNotFoundError as exc:
            if exc.name != name:
                raise
            pytest.fail(f"T042 API RED: {name} is not implemented", pytrace=False)
    domain, persistence = modules
    try:
        findings = importlib.import_module("ignis.domain.research_findings")
    except ModuleNotFoundError as exc:
        if exc.name != "ignis.domain.research_findings": raise
        pytest.fail("T042 API RED: ignis.domain.research_findings is not implemented", pytrace=False)
    for module, names in ((domain, ("ResearchAuthority", "ResearchInputBindings", "ResearchAssignment",
                                    "ResearchWorkItem", "ResearchActivityReceipt")),
                          (persistence, ("ResearchWorkCommitCommand", "ResearchHandoffAcknowledgement", "ResearchAssignmentAdmission", "ResearchWorkStartAdmission"))):
        for name in names:
            if not hasattr(module, name):
                pytest.fail(f"T042 API RED: {module.__name__}.{name} is not implemented", pytrace=False)
    return domain, persistence, findings


async def _commit(repository, persistence, mission, operation, payload, *, revision, epoch=1, key=None):
    return await repository.commit_research_work(persistence.ResearchWorkCommitCommand(
        mission_id=mission.id, operation=operation, payload=payload,
        expected_revision=revision, expected_epoch=epoch,
        idempotency_key=key or uuid4().hex, host_authorized=True,
    ))


def _rows(case, table):
    return _state(case)[1][table]


async def _sql(case, statement, params=()):
    """Execute owner mutation or a SQL fault on the actual store connection."""
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as conn:
            return conn.execute(statement.replace("?", "%s"), params).rowcount
    def write():
        repository = case.repository
        conn = repository._get_connection()
        try:
            count = conn.execute(statement, tuple(str(p) if isinstance(p, UUID) else p for p in params)).rowcount
            conn.commit()
            return count
        except BaseException:
            conn.rollback()
            raise
        finally:
            if repository._mem_conn is None:
                conn.close()
    return await case.repository._run_write(write)


async def _arrange(relay_case, tmp_path):
    case, missions, runs = relay_case
    repository, mission = case.repository, missions[0]
    from tests.unit.test_mission_claims import _eligible_mission
    from ignis.domain.research_workspace import compute_frame_fingerprint
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path, repository=repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    identities = tuple(sorted(((s.observation_id, s.source_id) for s in evidence.signals), key=lambda x: str(x[0])))
    domain, persistence, findings = _api(repository)
    inputs = domain.ResearchInputBindings(mission_id=mission.id, manifest_digest=frame.manifest_digest,
        brief_digest=compute_frame_fingerprint(mission, evidence.brief), frame_digest=frame.frame_digest,
        observation_ids=tuple(o for o, _ in identities), finding_revisions=())
    snapshot = await repository.load_research_work(mission.id)
    assignment = domain.ResearchAssignment(assignment_id=uuid4(), mission_id=mission.id,
        host_task_ref="synthetic-host", epoch=1, authority=domain.ResearchAuthority(
            actions=frozenset({"ANALYZE"}), sources=frozenset({"youtube"}),
            deadline=NOW + timedelta(days=300), quota_ceiling=0), capability="SEQUENTIAL", state="ASSIGNED", version=1)
    admitted = await _commit(repository, persistence, mission, "ASSIGN_RESEARCH", persistence.ResearchAssignmentAdmission(assignment=assignment,
        expected_manifest_digest=inputs.manifest_digest, expected_brief_revision_id=evidence.brief.brief_revision_id), revision=snapshot.revision)
    assert admitted.disposition == "APPLIED"
    work = domain.ResearchWorkItem(work_id=uuid4(), assignment_id=assignment.assignment_id,
        mission_id=mission.id, run_id=None, question="Describe recorded observations", expertise="Synthesis",
        assignee_ref="synthetic-worker", inputs=inputs, dependencies=(), epoch=1,
        state="RUNNING", version=1, ownership_fence="fence-1")
    # ASSIGN_WORK cannot fabricate RUNNING; actual START_WORK follows with a typed host receipt.
    assigned = replace(work, state="ASSIGNED")
    receipt = await _commit(repository, persistence, mission, "ASSIGN_WORK", assigned, revision=admitted.revision)
    assert receipt.disposition == "APPLIED"
    activity = domain.ResearchActivityReceipt(work_id=work.work_id, epoch=1, ownership_fence=work.ownership_fence,
        execution_ref="synthetic-execution", occurred_at=NOW, fresh_until=NOW + timedelta(days=300), provenance="HOST_REPORTED")
    started = await _commit(repository, persistence, mission, "START_WORK", persistence.ResearchWorkStartAdmission(
        work_id=work.work_id, expected_version=assigned.version, ownership_fence=work.ownership_fence, receipt=activity), revision=receipt.revision)
    assert started.disposition == "APPLIED"
    work = replace(work, version=started.work_version)
    finding = findings.ResearchFindingRevision(finding_id=uuid4(), revision=1, predecessor_revision=None,
        work_id=work.work_id, handoff_id=uuid4(), inputs=inputs, result_type="DESCRIPTIVE",
        statement="Recorded observations differ", limitations=("Bounded synthetic sample",), open_questions=(),
        supporting_observation_ids=(identities[0][0],), contradicting_observation_ids=(identities[1][0],),
        context_observation_ids=tuple(o for o, _ in identities[2:]), alternative_explanation="Sampling variation", claim_id=None)
    handoff = findings.ResearchHandoff(handoff_id=finding.handoff_id, work_id=work.work_id,
        expected_version=work.version, ownership_fence=work.ownership_fence, consumer_ref="synthetic-consumer",
        inputs=inputs, observation_sources=identities, outcome_ids=(), claim_ids=(),
        result="Recorded observations differ", limitations=finding.limitations, open_questions=(),
        findings=(finding,), occurred_at=NOW)
    return case, mission, domain, persistence, work, handoff, started.revision


@pytest.mark.asyncio
async def test_atomic_result_handoff_finding_and_event(relay_case, tmp_path):
    case, mission, _, persistence, work, handoff, revision = await _arrange(relay_case, tmp_path)
    before = _state(case)
    result = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert result.disposition == "APPLIED" and result.revision == revision + 1
    for table in ("research_handoffs", "research_finding_revisions"):
        assert len(_rows(case, table)) == len(before[1][table]) + 1
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.work_items[0].work_id == work.work_id
    assert snapshot.work_items[0].state == "HANDOFF_READY"
    assert snapshot.handoffs == (handoff,) and snapshot.findings == handoff.findings
    events = tuple(e for e in snapshot.events if e.cursor.revision == result.revision)
    assert len(events) == 2
    assert sorted(e.kind for e in events) == ["FINDING_REVISED", "HANDOFF_COMMITTED"]
    assert {e.cursor.mission_id for e in events} == {mission.id}
    assert {e.cursor.revision for e in events} == {result.revision}
    assert sorted(e.cursor.ordinal for e in events) == [1, 2]
    assert len({(e.cursor.mission_id, e.cursor.revision, e.cursor.ordinal) for e in events}) == 2
    assert all(e.work_id == work.work_id and e.handoff_id == handoff.handoff_id for e in events)
    finding_event = next(e for e in events if e.kind == "FINDING_REVISED")
    assert finding_event.finding_id == handoff.findings[0].finding_id
    assert len(result.event_ids) == len(set(result.event_ids)) == len({e.event_id for e in events}) == 2
    assert set(result.event_ids) == {e.event_id for e in events}


@pytest.mark.asyncio
@pytest.mark.parametrize("fault_table", ("research_handoffs", "research_finding_revisions", "mission_progress_events"))
async def test_late_sql_failure_rolls_back_every_atomic_effect(relay_case, tmp_path, fault_table, monkeypatch):
    case, mission, _, persistence, _, handoff, revision = await _arrange(relay_case, tmp_path)
    # Trigger counters survive rollback, proving the targeted write stage was reached.
    touches = []
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as conn:
            conn.execute("CREATE SEQUENCE t042_fault_calls")
            conn.execute("CREATE FUNCTION t042_abort() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM nextval('t042_fault_calls'); RAISE EXCEPTION 'T042 injected fault'; END $$")
            conn.execute(sql.SQL("CREATE TRIGGER t042_abort BEFORE INSERT ON {} FOR EACH ROW EXECUTE FUNCTION t042_abort()").format(sql.Identifier(fault_table)))
        def reached():
            with psycopg.connect(case.dsn) as conn:
                value, called = conn.execute("SELECT last_value,is_called FROM t042_fault_calls").fetchone()
                return value if called else 0
    else:
        original = case.repository._get_connection
        def connection_with_counter():
            conn = original()
            conn.create_function("t042_touch", 0, lambda: touches.append(True) or 1)
            return conn
        monkeypatch.setattr(case.repository, "_get_connection", connection_with_counter)
        await _sql(case, f"CREATE TRIGGER t042_abort BEFORE INSERT ON {fault_table} BEGIN SELECT t042_touch(); SELECT RAISE(ABORT, 'T042 injected fault'); END")
        def reached():
            return len(touches)
    assert reached() == 0
    # BEFORE INSERT runs before NOT NULL checking: the target trigger itself must reject.
    with pytest.raises((psycopg.Error, __import__("sqlite3").DatabaseError), match="T042 injected fault"):
        await _sql(case, f"INSERT INTO {fault_table} DEFAULT VALUES")
    assert reached() == 1
    before = _state(case)
    try:
        result = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    except (psycopg.Error, __import__("sqlite3").DatabaseError) as exc:
        assert "T042 injected fault" in str(exc)
    else:
        assert result.disposition == "REFUSED" and result.reason_code == "STORAGE_FAILURE"
    assert reached() == 2
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("control,reason", (("revision", "STALE_REVISION"), ("version", "STALE_WORK_VERSION"),
    ("epoch", "STALE_EPOCH"), ("fence", "OWNERSHIP_FENCE_MISMATCH"), ("observation", "INPUT_IDENTITY_MISMATCH"),
    ("source", "INPUT_IDENTITY_MISMATCH")))
async def test_obsolete_result_refuses_without_retaining_payload(relay_case, tmp_path, control, reason):
    case, mission, _, persistence, _, handoff, revision = await _arrange(relay_case, tmp_path)
    epoch = 1
    if control == "revision": revision -= 1
    elif control == "version": handoff = replace(handoff, expected_version=handoff.expected_version - 1)
    elif control == "epoch": epoch = 2
    elif control == "fence": handoff = replace(handoff, ownership_fence="obsolete-fence")
    else:
        # Use a real foreign mission observation and its exact canonical source. Replacing
        # bindings coherently avoids testing constructor inconsistency instead of admission.
        foreign_mission = relay_case[1][1]
        foreign = (await case.repository.load_mission_evidence_snapshot(foreign_mission.id)).signals[0]
        if control == "source":
            handoff = replace(handoff, observation_sources=((handoff.observation_sources[0][0],
                foreign.source_id), *handoff.observation_sources[1:]))
        else:
            pairs = ((foreign.observation_id, foreign.source_id), *handoff.observation_sources[1:])
            replacement_inputs = replace(handoff.inputs,
                observation_ids=(foreign.observation_id, *handoff.inputs.observation_ids[1:]))
            finding = replace(handoff.findings[0], inputs=replacement_inputs,
                supporting_observation_ids=(foreign.observation_id,))
            handoff = replace(handoff, observation_sources=pairs, inputs=replacement_inputs, findings=(finding,))
    sentinel = "T042_REJECTED_RESULT_SENTINEL"
    handoff = replace(handoff, result=sentinel)
    before = _state(case)
    receipt = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision, epoch=epoch)
    assert receipt.disposition == "REFUSED" and receipt.reason_code == reason
    after = _state(case)
    assert sentinel not in repr(after) and sentinel not in repr(receipt.to_payload())
    for table in TABLES:
        assert after[1][table] == before[1][table]


@pytest.mark.asyncio
async def test_identical_retry_returns_original_persisted_receipt(relay_case, tmp_path):
    case, mission, _, persistence, _, handoff, revision = await _arrange(relay_case, tmp_path)
    key = uuid4().hex
    first = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key=key)
    before = _state(case)
    retry = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision, key=key)
    assert retry == first and retry.to_payload() == first.to_payload()
    assert retry.receipt_id == first.receipt_id and retry.event_ids == first.event_ids and retry.recorded_at == first.recorded_at
    assert _state(case) == before
    conflict = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", replace(handoff, result="Changed"), revision=revision, key=key)
    assert conflict.disposition == "REFUSED" and conflict.reason_code == "IDEMPOTENCY_CONFLICT"
    assert _state(case)[1]["research_handoffs"] == before[1]["research_handoffs"]
    changed_revision = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff,
        revision=revision + 1, key=key)
    assert changed_revision.disposition == "REFUSED" and changed_revision.reason_code == "IDEMPOTENCY_CONFLICT"
    assert _state(case)[1]["research_handoffs"] == before[1]["research_handoffs"]


def _assert_safe_control_read(statement, *, in_transaction=True, serial_owner=True):
    """Reject an actual control-row read performed outside atomic admission."""
    upper = statement.upper()
    if "MISSION_PROGRESS_REVISIONS" not in upper or not upper.lstrip().startswith("SELECT"):
        return
    assert in_transaction and serial_owner, "Revision read escaped serialized transaction admission"


def _assert_locking_revision_admission(statement, *, already_locked=False):
    upper = statement.lstrip().upper()
    if "MISSION_PROGRESS_REVISIONS" in upper and upper.startswith("SELECT"):
        assert already_locked or "FOR UPDATE" in upper, "Revision read preceded locking/CAS admission"


def _wait_path_reaches(pid, owner, graph):
    """Walk the server's observed wait graph, including canonical table-gate chains."""
    pending, seen = [pid], set()
    while pending:
        current = pending.pop()
        if current == owner:
            return True
        if current not in seen:
            seen.add(current)
            pending.extend(graph.get(current, ()))
    return False


class _BusyAdmissionConnection:
    """Observe real SQLITE_BUSY before waiting outside a write transaction."""
    def __init__(self, conn, reached, release):
        self.conn, self.reached, self.release = conn, reached, release

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, statement, *args, **kwargs):
        if statement.strip().upper() == "BEGIN IMMEDIATE" and not self.release.is_set():
            timeout = self.conn.execute("PRAGMA busy_timeout").fetchone()[0]
            self.conn.execute("PRAGMA busy_timeout=0")
            try:
                self.conn.execute(statement)
            except sqlite3.OperationalError as exc:
                assert exc.sqlite_errorcode == sqlite3.SQLITE_BUSY
                assert not self.conn.in_transaction
                self.reached.set()
            else:
                raise AssertionError("Competing admission bypassed the physical write lock")
            finally:
                self.conn.execute(f"PRAGMA busy_timeout={timeout}")
            assert self.release.wait(10), "Blocked admission was not released"
        return self.conn.execute(statement, *args, **kwargs)


async def _contended_results(case, mission, persistence, handoff, revision, monkeypatch):
    """Hold real backend admission, observe both competitors, then release once."""
    repository, tasks = case.repository, []
    traces, release = [], threading.Event()
    competitors = []
    blocker = None
    memory_locked = False
    try:
        if case.name == "sqlite":
            if repository._mem_conn is not None:
                await repository._lock.acquire()
                memory_locked = True
                entered = [asyncio.Event(), asyncio.Event()]
                count = 0
                original_write = repository._run_write
                async def observed_write(operation):
                    nonlocal count
                    index = count
                    count += 1
                    if index < 2:
                        entered[index].set()
                    return await original_write(operation)
                monkeypatch.setattr(repository, "_run_write", observed_write)
                repositories = [repository, repository]
            else:
                competitor = type(repository)(repository._db_path)
                competitors.append(competitor)
                await competitor._ensure_schema()
                await competitor._ensure_progress_schema()
                repositories = [repository, competitor]
                entered = [threading.Event(), threading.Event()]
                blocker = sqlite3.connect(repository._db_path)
                blocker.execute("BEGIN IMMEDIATE")
            for index, writer in enumerate(dict.fromkeys(repositories)):
                original_connection = writer._get_connection
                def connect(original=original_connection, index=index, writer=writer):
                    conn = original()
                    def trace(statement):
                        if "mission_progress_revisions" in statement.lower() and statement.lstrip().upper().startswith("SELECT"):
                            traces.append((statement, conn.in_transaction, writer._lock.locked()))
                    conn.set_trace_callback(trace)
                    return conn if writer._mem_conn is not None else _BusyAdmissionConnection(conn, entered[index], release)
                monkeypatch.setattr(writer, "_get_connection", connect)
            if repository._mem_conn is not None:
                repository._get_connection()  # Install trace before detecting an unsafe pre-lock read.
            tasks = [asyncio.create_task(_commit(writer, persistence, mission, "SUBMIT_HANDOFF",
                handoff, revision=revision, key=uuid4().hex)) for writer in repositories]
            for event in entered:
                if isinstance(event, asyncio.Event):
                    await asyncio.wait_for(event.wait(), 3)
                else:
                    assert await asyncio.to_thread(event.wait, 3), "Competitor never observed physical SQLITE_BUSY"
            assert not any(task.done() for task in tasks)
            assert traces == [], "Revision was read before blocked transaction admission"
            if memory_locked:
                repository._lock.release()
                memory_locked = False
            else:
                blocker.rollback()
            release.set()
        else:
            # Independent local admission owners preserve each repository's correct lock.
            competitor = type(repository)(case.dsn, min_pool_size=1, max_pool_size=1)
            competitors.append(competitor)
            await competitor._get_pool()
            assert competitor._pool is not repository._pool
            assert competitor._relay_fact_lock is not repository._relay_fact_lock
            blocker = psycopg.connect(case.dsn)
            blocker.execute("SET LOCAL lock_timeout='1s'")
            blocker.execute("SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE", (mission.id,))
            blocker_pid = blocker.info.backend_pid
            entered = [asyncio.Event(), asyncio.Event()]
            pids, revision_locked = [], set()
            execute = psycopg.AsyncCursor.execute
            async def observed(cursor, query, *args, **kwargs):
                statement = query.as_string(cursor) if isinstance(query, sql.Composable) else str(query)
                upper = statement.lstrip().upper()
                control = "MISSION_PROGRESS_REVISIONS" in upper
                # Canonical table gates legally precede revision-row admission. Register at
                # that attempted gate, so the second writer may wait transitively on the first.
                admission = (upper.startswith("LOCK TABLE") and "RESEARCH_MISSIONS" in upper) or (
                    control and ("FOR UPDATE" in upper or upper.startswith("UPDATE")))
                pid = cursor.connection.info.backend_pid
                if control:
                    traces.append((pid, statement))
                    _assert_locking_revision_admission(statement, already_locked=pid in revision_locked)
                if admission and pid not in pids:
                    pids.append(pid)
                    if len(pids) <= 2:
                        entered[len(pids) - 1].set()
                result = await execute(cursor, query, *args, **kwargs)
                if control and ((upper.startswith("SELECT") and "FOR UPDATE" in upper) or upper.startswith("UPDATE")):
                    revision_locked.add(pid)
                return result
            monkeypatch.setattr(psycopg.AsyncCursor, "execute", observed)
            tasks = [asyncio.create_task(_commit(writer, persistence, mission, "SUBMIT_HANDOFF",
                handoff, revision=revision, key=uuid4().hex)) for writer in (repository, competitor)]
            for event in entered:
                await asyncio.wait_for(event.wait(), 3)
            def both_blocked():
                with psycopg.connect(case.dsn) as observer:
                    graph = dict(observer.execute(
                        "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity WHERE datname=current_database()"
                    ).fetchall())
                    return all(_wait_path_reaches(pid, blocker_pid, graph) for pid in pids)
            async with asyncio.timeout(3):
                while not await asyncio.to_thread(both_blocked):
                    assert not any(task.done() for task in tasks), "Caller escaped held revision-row lock"
                    await asyncio.sleep(0.01)
            assert len(pids) == 2 and not any(task.done() for task in tasks)
            blocker.rollback()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        if case.name == "postgres":
            assert revision_locked == set(pids), "Every caller must consume its revision under transaction ownership"
        if case.name == "sqlite":
            assert len(traces) >= 2, "Both callers must read the canonical revision after admission"
            for statement, in_transaction, serial_owner in traces:
                _assert_safe_control_read(statement, in_transaction=in_transaction, serial_owner=serial_owner)
        return results
    finally:
        if memory_locked:
            repository._lock.release()
        if blocker is not None:
            blocker.rollback()
            blocker.close()
        release.set()
        # Release blockers before settling workers or closing competing repository resources.
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 6)
        if repository._mem_conn is not None:
            repository._mem_conn.set_trace_callback(None)
        for competitor in competitors:
            await competitor.close()


@pytest.mark.asyncio
async def test_nonatomic_revision_read_control_is_detected_on_physical_store(relay_case):
    """A real unlocked read must fail the same admission guard used by contenders."""
    case, missions, _ = relay_case
    statement = "SELECT revision FROM mission_progress_revisions WHERE mission_id=?"
    if case.name == "postgres":
        with psycopg.connect(case.dsn, autocommit=True) as conn:
            initialize = "INSERT INTO mission_progress_revisions (mission_id,revision) VALUES (%s,0) ON CONFLICT (mission_id) DO NOTHING"
            _assert_locking_revision_admission(initialize)
            assert conn.execute(initialize, (missions[0].id,)).rowcount == 0
            with conn.transaction():
                locked_read = statement.replace("?", "%s") + " FOR UPDATE"
                _assert_locking_revision_admission(locked_read)
                assert conn.execute(locked_read, (missions[0].id,)).fetchone() is not None
                _assert_locking_revision_admission(statement, already_locked=True)
                assert conn.execute(statement.replace("?", "%s"), (missions[0].id,)).fetchone() is not None
            row = conn.execute(statement.replace("?", "%s"), (missions[0].id,)).fetchone()
            assert row is not None
            with pytest.raises(AssertionError, match="preceded locking/CAS admission"):
                _assert_locking_revision_admission(statement)
    else:
        conn = case.repository._get_connection()
        try:
            row = conn.execute(statement, (str(missions[0].id),)).fetchone()
            assert row is not None and not conn.in_transaction
            with pytest.raises(AssertionError, match="escaped serialized transaction"):
                _assert_safe_control_read(statement, in_transaction=conn.in_transaction, serial_owner=False)
        finally:
            if case.repository._mem_conn is None:
                conn.close()


@pytest.mark.asyncio
async def test_concurrent_compare_and_swap_has_exactly_one_winner(relay_case, tmp_path, monkeypatch):
    case, mission, _, persistence, _, handoff, revision = await _arrange(relay_case, tmp_path)
    before = _state(case)
    results = await _contended_results(case, mission, persistence, handoff, revision, monkeypatch)
    assert sorted(r.disposition for r in results) == ["APPLIED", "REFUSED"]
    loser = next(r for r in results if r.disposition == "REFUSED")
    assert loser.reason_code == "STALE_REVISION"
    assert len(_rows(case, "research_handoffs")) == len(before[1]["research_handoffs"]) + 1
    assert len(_rows(case, "research_finding_revisions")) == len(before[1]["research_finding_revisions"]) + 1


@pytest.mark.asyncio
async def test_physical_fixture_control_uses_canonical_frame_and_brief(relay_case, tmp_path):
    from tests.unit.test_mission_claims import _eligible_mission
    from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
    case, _, _ = relay_case
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path, repository=case.repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    canonical = await load_current_evidence_frame(repository, store, mission)
    assert canonical.frame_digest == frame.frame_digest
    assert canonical.manifest_digest == evidence.manifest.manifest_digest
    assert canonical.brief_revision_id == evidence.brief.brief_revision_id
    assert len(signals) == len(evidence.signals) == 6
    ids = {(str(s.observation_id), str(s.source_id)) for s in signals}
    assert len(ids) == 6
    _, rows = _state(case)
    assert len(rows["mission_evidence"]) == len(rows["observations"]) == 12
    assert all(observation in repr(rows["observations"]) and source in repr(rows["sources"]) for observation, source in ids)


async def _another_work(case, mission, domain, persistence, original, inputs, revision):
    work = replace(original, work_id=uuid4(), state="ASSIGNED", version=1, inputs=inputs,
                   dependencies=(original.work_id,) if inputs.finding_revisions else ())
    assigned = await _commit(case.repository, persistence, mission, "ASSIGN_WORK", work, revision=revision)
    assert assigned.disposition == "APPLIED"
    activity = domain.ResearchActivityReceipt(work_id=work.work_id, epoch=1, ownership_fence=work.ownership_fence,
        execution_ref=f"synthetic-{work.work_id}", occurred_at=NOW, fresh_until=NOW + timedelta(days=300), provenance="HOST_REPORTED")
    started = await _commit(case.repository, persistence, mission, "START_WORK", persistence.ResearchWorkStartAdmission(
        work_id=work.work_id, expected_version=work.version, ownership_fence=work.ownership_fence, receipt=activity), revision=assigned.revision)
    assert started.disposition == "APPLIED"
    return replace(work, version=started.work_version, state="RUNNING"), started.revision


@pytest.mark.asyncio
async def test_shared_workers_preserve_identity_without_corroboration_inflation(relay_case, tmp_path):
    case, mission, domain, persistence, work, handoff, revision = await _arrange(relay_case, tmp_path)
    other, revision = await _another_work(case, mission, domain, persistence, work, work.inputs, revision)
    before = _state(case)
    snapshot = await case.repository.load_research_work(mission.id)
    assert {w.work_id for w in snapshot.work_items} == {work.work_id, other.work_id}
    assert all(w.inputs.observation_ids == work.inputs.observation_ids for w in snapshot.work_items)
    assert snapshot.observation_sources == handoff.observation_sources
    assert snapshot.observation_count == len(handoff.observation_sources) == 6
    assert snapshot.source_count == len({s for _, s in handoff.observation_sources}) == 6
    assert _state(case) == before


@pytest.mark.asyncio
async def test_dependency_revision_is_stale_and_history_survives_membership_pruning(relay_case, tmp_path):
    case, mission, domain, persistence, work, handoff, revision = await _arrange(relay_case, tmp_path)
    first = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert first.disposition == "APPLIED"
    finding = handoff.findings[0]
    original_rows = tuple(_rows(case, "research_finding_revisions"))
    assert len(original_rows) == 1
    inputs = replace(work.inputs, finding_revisions=((finding.finding_id, 1),))
    downstream, revision = await _another_work(case, mission, domain, persistence, work, inputs, first.revision)
    producer, revision = await _another_work(case, mission, domain, persistence, work, work.inputs, revision)
    revised_id = uuid4()
    revised_finding = replace(finding, revision=2, predecessor_revision=1, work_id=producer.work_id,
        handoff_id=revised_id, statement="Revised descriptive observation")
    revised_handoff = replace(handoff, handoff_id=revised_id, work_id=producer.work_id,
        expected_version=producer.version, findings=(revised_finding,), result=revised_finding.statement)
    revised = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", revised_handoff, revision=revision)
    assert revised.disposition == "APPLIED"
    revised_rows = tuple(_rows(case, "research_finding_revisions"))
    assert len(revised_rows) == 2 and all(row in revised_rows for row in original_rows)
    revised_snapshot = await case.repository.load_research_work(mission.id)
    assert tuple(f for f in revised_snapshot.findings if f.finding_id == finding.finding_id) == (finding, revised_finding)
    before = _state(case)
    obsolete = replace(handoff, handoff_id=uuid4(), work_id=downstream.work_id, expected_version=downstream.version,
        inputs=inputs, result="T042_STALE_DEPENDENCY_SENTINEL", findings=())
    rejected = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", obsolete, revision=revised.revision)
    assert rejected.disposition == "REFUSED" and rejected.reason_code == "STALE_DEPENDENCY_REVISION"
    assert _rows(case, "research_finding_revisions") == before[1]["research_finding_revisions"]
    assert obsolete.result not in repr(_state(case))
    observation = handoff.observation_sources[0][0]
    assert await _sql(case, "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?", (mission.id, observation)) == 1
    snapshot = await case.repository.load_research_work(mission.id)
    history = tuple(f for f in snapshot.findings if f.finding_id == finding.finding_id)
    assert history == (finding, revised_finding)
    assert tuple(_rows(case, "research_finding_revisions")) == revised_rows
    assert all(row in _rows(case, "research_finding_revisions") for row in original_rows)
    assert all(observation in f.inputs.observation_ids for f in history)
    assert snapshot.current_finding_ids == ()
    assert str(observation) in repr(_rows(case, "observations"))
    assert len(_rows(case, "research_finding_revisions")) == len(before[1]["research_finding_revisions"])
    membership_rejected = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF",
        replace(obsolete, inputs=replace(inputs, finding_revisions=((finding.finding_id, 2),))), revision=snapshot.revision)
    assert membership_rejected.disposition == "REFUSED" and membership_rejected.reason_code == "STALE_INPUT_FRAME"
    assert obsolete.result not in repr(_state(case))


@pytest.mark.asyncio
async def test_consumer_rejection_retains_exact_safe_reason_and_no_rejected_text(relay_case, tmp_path):
    case, mission, _, persistence, work, handoff, revision = await _arrange(relay_case, tmp_path)
    committed = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert committed.disposition == "APPLIED"
    acknowledgement = persistence.ResearchHandoffAcknowledgement(handoff_id=handoff.handoff_id,
        consumer_ref=handoff.consumer_ref, expected_version=committed.work_version,
        disposition="REJECTED", reason_code="INPUT_REVISION_MISMATCH", inputs=handoff.inputs)
    before = _state(case)
    rejected = await _commit(case.repository, persistence, mission, "ACK_HANDOFF", acknowledgement, revision=committed.revision)
    assert rejected.disposition == "APPLIED"
    snapshot = await case.repository.load_research_work(mission.id)
    ack = snapshot.acknowledgements[0]
    assert ack == acknowledgement and ack.reason_code == "INPUT_REVISION_MISMATCH"
    assert ack.inputs == handoff.inputs
    assert snapshot.work_items[0].state != "COMPLETED"
    assert _rows(case, "research_finding_revisions") == before[1]["research_finding_revisions"]
    assert set(ack.to_payload()) == {"handoff_id", "consumer_ref", "expected_version", "disposition", "reason_code", "inputs"}
    assert len(snapshot.acknowledgements) == 1


@pytest.mark.asyncio
async def test_unsafe_consumer_reason_is_refused_without_any_text_retention(relay_case, tmp_path):
    case, mission, _, persistence, _, handoff, revision = await _arrange(relay_case, tmp_path)
    committed = await _commit(case.repository, persistence, mission, "SUBMIT_HANDOFF", handoff, revision=revision)
    assert committed.disposition == "APPLIED"
    sentinel = "T042_UNSAFE_REJECTED_REASON_SENTINEL"
    acknowledgement = persistence.ResearchHandoffAcknowledgement(handoff_id=handoff.handoff_id,
        consumer_ref=handoff.consumer_ref, expected_version=committed.work_version,
        disposition="REJECTED", reason_code=sentinel, inputs=handoff.inputs)
    before = _state(case)
    rejected = await _commit(case.repository, persistence, mission, "ACK_HANDOFF", acknowledgement, revision=committed.revision)
    assert rejected.disposition == "REFUSED" and rejected.reason_code == "INVALID_REASON_CODE"
    assert sentinel not in repr(rejected.to_payload()) and sentinel not in repr(_state(case))
    assert _rows(case, "research_handoffs") == before[1]["research_handoffs"]
    assert _rows(case, "research_finding_revisions") == before[1]["research_finding_revisions"]
