"""Real SQLite publication controls for immutable facts and original receipts.

Separate commits, payload aliasing, duplicate revisions, or early cancellation
ownership release must break these tests. No replacement transaction engine is used.
"""

import asyncio
import json
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import UUID, uuid4

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
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


@pytest_asyncio.fixture(params=("file", "memory"))
async def commit_case(request, tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "commits.sqlite") if request.param == "file" else ":memory:")
    workspace = ResearchWorkspace(slug="commit-contract", root_path=tmp_path / "workspace")
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
    try:
        yield repository, mission, outcome
    finally:
        await repository.close()


def _rows(repository, table):
    connection = repository._get_connection()
    try:
        return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
    finally:
        if repository._mem_conn is None:
            connection.close()


def _state(repository):
    return {
        table: _rows(repository, table)
        for table in (
            "mission_probe_outcomes",
            "mission_progress_revisions",
            "mission_progress_events",
            "mission_progress_commands",
        )
    }


def _command(mission, outcome, *more):
    return ProbeOutcomeCommitCommand(mission_id=mission.id, run_id=outcome.run_id, outcomes=(outcome, *more))


@pytest.mark.asyncio
async def test_reordered_retry_returns_all_original_receipt_fields(commit_case):
    repository, mission, first = commit_case
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    command = _command(mission, first, second)
    receipt = await repository.commit_probe_outcomes(command)
    original = _state(repository)
    retry = await repository.commit_probe_outcomes(_command(mission, second, first))
    assert retry == receipt
    assert receipt.command_key == command.command_key
    assert receipt.payload_fingerprint == command.payload_fingerprint
    assert receipt.outcome_count == 2
    assert receipt.event.kind is MissionProgressKind.PROBE_OUTCOMES_RECORDED
    assert receipt.event.provenance is RelayProvenance.HARNESS_OBSERVED
    assert receipt.event.run_id == first.run_id
    assert receipt.event.cursor.position == (1, 1)
    assert receipt.event.recorded_at.utcoffset() == timedelta(0)
    assert receipt.event.occurred_at is None
    assert receipt.event.evidence_references == ()
    assert _state(repository) == original
    assert {row["id"] for row in original["mission_probe_outcomes"]} == {str(first.outcome_id), str(second.outcome_id)}
    stored = original["mission_progress_events"][0]
    assert stored["id"] == str(receipt.event.event_id)
    assert stored["recorded_at"] == receipt.event.recorded_at.isoformat()
    third = replace(first, outcome_id=uuid4(), connector_surface="youtube.comments")
    later = await repository.commit_probe_outcomes(_command(mission, third))
    assert later.event.cursor.position == (2, 1)
    following = _state(repository)
    assert await repository.commit_probe_outcomes(command) == receipt
    assert _state(repository) == following


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_case", ["memory"], indirect=True)
@pytest.mark.parametrize("fail,cancel", [(False, False), (True, False), (False, True), (True, True)])
async def test_public_journal_writer_cannot_commit_held_memory_publication(commit_case, monkeypatch, fail, cancel):
    """A legacy journal commit must never end another owner's shared transaction."""
    repository, mission, outcome = commit_case
    await repository._ensure_progress_schema()
    journal_path = _rows(repository, "mission_run_journals")[0]["journal_path"]
    entered, release = threading.Event(), threading.Event()
    connect = repository._get_connection
    tasks = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_get_connection", lambda: _HeldCommit(connect(), entered, release, fail))
            owner = asyncio.create_task(repository.commit_probe_outcomes(_command(mission, outcome)))
            tasks.append(owner)
            assert await asyncio.to_thread(entered.wait, 5)
            patch.setattr(repository, "_get_connection", connect)
            if cancel:
                owner.cancel()
                await asyncio.sleep(0)
                owner.cancel()
            competing = asyncio.create_task(
                repository.record_run_journal(
                    RunJournal(
                        run_id=outcome.run_id,
                        mission_id=mission.id,
                        workspace_id=mission.workspace_id,
                        journal_path=journal_path,
                        sequence=1,
                        status="FAILED",
                        started_at=NOW,
                        completed_at=NOW,
                    )
                )
            )
            tasks.append(competing)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(competing), 0.05)
            assert not owner.done()
            assert repository._lock.locked()
            assert repository._mem_conn.in_transaction
            assert _rows(repository, "mission_run_journals")[0]["status"] == "COMPLETED"
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await owner
            elif fail:
                with pytest.raises(sqlite3.OperationalError):
                    await owner
            else:
                assert (await owner).event.cursor.position == (1, 1)
            await competing
    finally:
        release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
    assert not repository._mem_conn.in_transaction
    assert _rows(repository, "mission_run_journals")[0]["status"] == "FAILED"
    assert [len(rows) for rows in _state(repository).values()] == ([0, 0, 0, 0] if fail else [1, 1, 1, 1])
    receipt = await repository.commit_probe_outcomes(_command(mission, outcome))
    assert receipt.event.cursor.position == (1, 1)


class _CloseAudit:
    def __init__(self, connection):
        self.connection = connection
        self.closed = False
        self.counts = None
        self.in_transaction_at_close = None

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        self.counts = [
            self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "mission_probe_outcomes",
                "mission_progress_revisions",
                "mission_progress_events",
                "mission_progress_commands",
            )
        ]
        self.in_transaction_at_close = self.connection.in_transaction
        self.closed = True
        self.connection.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_case", ["memory"], indirect=True)
@pytest.mark.parametrize("fail,cancel", [(False, False), (True, False), (False, True), (True, True)])
async def test_public_close_waits_for_memory_publication_settlement(commit_case, monkeypatch, fail, cancel):
    """Closing the shared connection must wait for its actual mutation owner."""
    repository, mission, outcome = commit_case
    await repository._ensure_progress_schema()
    audit = _CloseAudit(repository._mem_conn)
    repository._mem_conn = audit
    entered, release = threading.Event(), threading.Event()
    connect = repository._get_connection
    tasks = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_get_connection", lambda: _HeldCommit(connect(), entered, release, fail))
            owner = asyncio.create_task(repository.commit_probe_outcomes(_command(mission, outcome)))
            tasks.append(owner)
            assert await asyncio.to_thread(entered.wait, 5)
            if cancel:
                owner.cancel()
                await asyncio.sleep(0)
                owner.cancel()
            closing = asyncio.create_task(repository.close())
            tasks.append(closing)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(closing), 0.05)
            assert not owner.done()
            assert not audit.closed
            assert repository._lock.locked()
            assert audit.in_transaction
            release.set()
            if cancel:
                with pytest.raises(asyncio.CancelledError):
                    await owner
            elif fail:
                with pytest.raises(sqlite3.OperationalError):
                    await owner
            else:
                assert (await owner).event.cursor.position == (1, 1)
            await closing
    finally:
        release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
    assert audit.closed
    assert not audit.in_transaction_at_close
    assert audit.counts == ([0, 0, 0, 0] if fail else [1, 1, 1, 1])
    assert repository._mem_conn is None


@pytest.mark.asyncio
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
async def test_changed_fact_conflicts_without_touching_original_commit(commit_case, changes):
    repository, mission, outcome = commit_case
    await repository.commit_probe_outcomes(_command(mission, outcome))
    original = _state(repository)
    with pytest.raises(RepositoryException):
        await repository.commit_probe_outcomes(_command(mission, replace(outcome, **changes)))
    assert _state(repository) == original


@pytest.mark.asyncio
async def test_disjoint_legacy_batches_commit_but_overlap_rolls_back_whole_batch(commit_case):
    repository, mission, first = commit_case
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    assert await repository.record_probe_outcomes(first.run_id, [first]) == 1
    assert await repository.record_probe_outcomes(first.run_id, [second]) == 1
    original = _state(repository)
    assert [row["revision"] for row in original["mission_progress_events"]] == [1, 2]
    assert len({row["command_key"] for row in original["mission_progress_commands"]}) == 2
    new_surface = replace(first, outcome_id=uuid4(), connector_surface="youtube.comments")
    with pytest.raises(RepositoryException):
        await repository.record_probe_outcomes(first.run_id, [new_surface, second])
    assert _state(repository) == original


@pytest.mark.asyncio
async def test_recursive_admitted_values_are_persisted_without_caller_aliases(commit_case):
    repository, mission, outcome = commit_case

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
    receipt = await repository.commit_probe_outcomes(command)
    row = _rows(repository, "mission_probe_outcomes")[0]
    assert json.loads(row["scope_attestation"]) == {
        "scope": {"geo": "VN", "samples": [1, 2]},
        "nested": [{"instant": "2026-10-04T00:00:00+00:00", "id": str(outcome.outcome_id)}],
        "unknown": None,
    }
    assert row["completed_at"] == "2026-10-04T00:00:00+00:00"
    assert receipt.payload_fingerprint == command.payload_fingerprint
    assert await repository.commit_probe_outcomes(command) == receipt


@pytest.mark.asyncio
async def test_authoritative_run_scope_refuses_caller_selected_mission(commit_case):
    repository, mission, outcome = commit_case
    other = ResearchMission(title="Other mission", keywords=["other scope"], workspace_id=mission.workspace_id)
    await repository.save_mission(other)
    await repository._ensure_progress_schema()
    original = _state(repository)
    with pytest.raises(RepositoryException):
        await repository.commit_probe_outcomes(_command(other, outcome))
    with pytest.raises(RepositoryException):
        await repository.commit_probe_outcomes(_command(mission, replace(outcome, run_id=uuid4())))
    assert _state(repository) == original


@pytest.mark.asyncio
async def test_empty_legacy_batch_with_unknown_run_remains_a_noop(commit_case):
    repository, _mission, _outcome = commit_case
    await repository._ensure_progress_schema()
    original = _state(repository)
    assert await repository.record_probe_outcomes(uuid4(), []) == 0
    assert _state(repository) == original


@pytest.mark.asyncio
async def test_manifest_requires_full_batch_and_empty_legacy_remains_no_event(commit_case):
    repository, mission, outcome = commit_case
    assert await repository.record_probe_outcomes(outcome.run_id, []) == 0
    await repository._ensure_progress_schema()
    original = _state(repository)
    await repository.save_mission_manifest(
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
    first = replace(outcome, scope_attestation={"geo": "VN"}, note="Empty query", collection_plan_digest="b" * 64)
    second = replace(first, outcome_id=uuid4(), platform="threads", connector_surface="threads")
    for batch in ([], [first], [first, replace(second, collection_plan_digest="c" * 64)]):
        with pytest.raises(InvalidEvidenceQualificationError):
            await repository.record_probe_outcomes(outcome.run_id, batch)
        assert _state(repository) == original
    assert await repository.record_probe_outcomes(outcome.run_id, [first, second]) == 2
    assert len(_rows(repository, "mission_progress_events")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("denied_table", ("mission_progress_revisions", "mission_progress_commands"))
async def test_receipt_or_revision_refusal_rolls_back_every_publication_row(commit_case, monkeypatch, denied_table):
    repository, mission, outcome = commit_case
    await repository._ensure_progress_schema()
    original = _state(repository)
    connect = repository._get_connection

    def denied_connection():
        connection = connect()
        connection.set_authorizer(
            lambda action, table, *_: (
                sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_INSERT and table == denied_table else sqlite3.SQLITE_OK
            )
        )
        return connection

    try:
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_get_connection", denied_connection)
            with pytest.raises((RepositoryException, sqlite3.DatabaseError)):
                await repository.commit_probe_outcomes(_command(mission, outcome))
    finally:
        if repository._mem_conn is not None:
            repository._mem_conn.set_authorizer(None)
    assert _state(repository) == original
    receipt = await repository.commit_probe_outcomes(_command(mission, outcome))
    assert receipt.event.cursor.position == (1, 1)


@pytest.mark.asyncio
async def test_cross_instance_identical_retries_return_one_original_receipt(commit_case):
    repository, mission, outcome = commit_case
    if repository._mem_conn is not None:
        pytest.skip("Independent private memory databases do not share a SQLite store")
    other = SqliteTrendRepository(repository._db_path)
    try:
        receipts = await asyncio.gather(
            repository.commit_probe_outcomes(_command(mission, outcome)),
            other.commit_probe_outcomes(_command(mission, outcome)),
        )
        assert receipts[0] == receipts[1]
        assert [len(rows) for rows in _state(repository).values()] == [1, 1, 1, 1]
    finally:
        await other.close()


class _HeldCommit:
    def __init__(self, connection, entered, release, fail):
        self.connection, self.entered, self.release, self.fail = connection, entered, release, fail
        self.closed = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def commit(self):
        assert self.connection.in_transaction
        self.entered.set()
        assert self.release.wait(5), "Commit was not released"
        if self.fail:
            raise sqlite3.OperationalError("Synthetic commit refusal")
        return self.connection.commit()

    def close(self):
        self.connection.close()
        self.closed = True


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", (False, True))
async def test_repeated_cancellation_keeps_writer_ownership_until_real_commit_settles(commit_case, monkeypatch, fail):
    repository, mission, outcome = commit_case
    await repository._ensure_progress_schema()
    entered, release = threading.Event(), threading.Event()
    wrappers, tasks = [], []
    connect = repository._get_connection
    command = _command(mission, outcome)

    def held_connection():
        wrapper = _HeldCommit(connect(), entered, release, fail)
        wrappers.append(wrapper)
        return wrapper

    try:
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_get_connection", held_connection)
            task = asyncio.create_task(repository.commit_probe_outcomes(command))
            tasks.append(task)
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert repository._lock.locked()
            assert wrappers[-1].connection.in_transaction
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
    assert not repository._lock.locked()
    if repository._mem_conn is None:
        assert all(wrapper.closed for wrapper in wrappers)
    state = _state(repository)
    assert [len(rows) for rows in state.values()] == ([0, 0, 0, 0] if fail else [1, 1, 1, 1])
    receipt = await repository.commit_probe_outcomes(command)
    assert receipt.event.cursor.position == (1, 1)
    if not fail:
        assert _state(repository) == state


@pytest.mark.asyncio
async def test_cancelled_writer_blocks_competing_retry_until_durable_publication(commit_case, monkeypatch):
    repository, mission, outcome = commit_case
    await repository._ensure_progress_schema()
    entered, release = threading.Event(), threading.Event()
    connect = repository._get_connection
    command = _command(mission, outcome)
    tasks = []
    try:
        with monkeypatch.context() as patch:
            patch.setattr(repository, "_get_connection", lambda: _HeldCommit(connect(), entered, release, False))
            cancelled = asyncio.create_task(repository.commit_probe_outcomes(command))
            tasks.append(cancelled)
            assert await asyncio.to_thread(entered.wait, 5)
            cancelled.cancel()
            await asyncio.sleep(0)
            cancelled.cancel()
            patch.setattr(repository, "_get_connection", connect)
            competing = asyncio.create_task(repository.commit_probe_outcomes(command))
            tasks.append(competing)
            await asyncio.sleep(0)
            assert not cancelled.done()
            assert not competing.done()
            assert repository._lock.locked()
            if repository._mem_conn is None:
                assert [len(rows) for rows in _state(repository).values()] == [0, 0, 0, 0]
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await cancelled
            receipt = await competing
    finally:
        release.set()

        async def settle():
            await asyncio.gather(*tasks, return_exceptions=True)

        await await_settled(settle())
    assert receipt.event.cursor.position == (1, 1)
    assert [len(rows) for rows in _state(repository).values()] == [1, 1, 1, 1]
    assert await repository.commit_probe_outcomes(command) == receipt
