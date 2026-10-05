"""Run-scoped error paths retain canonical collection receipts on each backend."""

import asyncio
import sqlite3
import threading

import psycopg
import pytest

from test_mission_progress_ingress import (
    ingress_case as _shared_ingress_case,
    _attention,
    _events,
    _connection,
    _rows,
    _refuse_write,
    _assert_revision_matches_events,
)
from ignis.domain.exceptions import RepositoryException, VocabularySynchronizationError


ingress_case = _shared_ingress_case


@pytest.mark.asyncio
@pytest.mark.parametrize("repeat_cancel", (False, True))
async def test_cancelled_collection_keeps_start_and_failed_receipts(
    ingress_case, tmp_path, monkeypatch, repeat_cancel,
):
    """Bypassing the atomic failure writer loses the terminal receipt after cancellation."""
    case = ingress_case
    store, mission, executor = await _attention(case, tmp_path)
    entered = asyncio.Event()
    search_cancelled = asyncio.Event()
    cleanup_entered = asyncio.Event()
    cleanup_release = asyncio.Event()
    original_read = case.repository.get_mission

    async def gated_read(mission_id):
        if repeat_cancel and search_cancelled.is_set():
            cleanup_entered.set()
            await cleanup_release.wait()
        return await original_read(mission_id)

    monkeypatch.setattr(case.repository, "get_mission", gated_read)

    async def blocked_search(**_kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            search_cancelled.set()

    executor._registry.search_with_outcomes = blocked_search
    task = asyncio.create_task(executor.execute(mission.id))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    if repeat_cancel:
        try:
            await asyncio.wait_for(cleanup_entered.wait(), 5)
            task.cancel()
        finally:
            cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    events = _events(case, mission.id)
    assert [(event[0], event[7]) for event in events] == [
        ("COLLECTION_STARTED", "RUNNING"),
        ("COLLECTION_STATE_CHANGED", "FAILED"),
    ]
    assert events[0][1] == events[1][1]
    assert _rows(case, "research_missions", mission.id, "status", key="id") == [("FAILED",)]
    assert _rows(case, "mission_evidence", mission.id) == []
    assert await store.get_mission_writer_claim(mission.id) is None
    journals = await store.list_run_journals(mission.id)
    assert len(journals) == 1 and journals[0].status == "FAILED"
    _assert_revision_matches_events(case, mission.id)


@pytest.mark.asyncio
async def test_vocabulary_failure_has_terminal_receipt_without_start_or_probe(ingress_case, tmp_path):
    """A legacy pre-ingress failure write must not leave a run without its state receipt."""
    case = ingress_case
    store, mission, executor = await _attention(case, tmp_path)

    class FailingVocabulary:
        async def synchronize(self):
            raise VocabularySynchronizationError("Controlled vocabulary failure")

    executor._vocabulary_sync = FailingVocabulary()
    with pytest.raises(VocabularySynchronizationError):
        await executor.execute(mission.id)
    events = _events(case, mission.id)
    assert [(event[0], event[7]) for event in events] == [
        ("COLLECTION_STATE_CHANGED", "FAILED"),
    ]
    assert _rows(case, "research_missions", mission.id, "status", key="id") == [("FAILED",)]
    assert _rows(case, "mission_evidence", mission.id) == []
    with _connection(case) as conn:
        assert conn.execute("SELECT count(*) FROM mission_probe_outcomes").fetchone()[0] == 0
    assert await store.get_mission_writer_claim(mission.id) is None
    _assert_revision_matches_events(case, mission.id)


@pytest.mark.asyncio
async def test_probe_event_refusal_keeps_earlier_arrival_and_no_outcome_fact(ingress_case, tmp_path):
    """A late outcome failure cannot roll back an earlier observation commit."""
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    with _refuse_write(case, "mission_progress_events", kind="PROBE_OUTCOMES_RECORDED") as hits:
        with pytest.raises((sqlite3.DatabaseError, psycopg.Error, RepositoryException)):
            await executor.execute(mission.id)
        assert hits() > 0
    assert len(_rows(case, "mission_evidence", mission.id)) == 1
    with _connection(case) as conn:
        assert conn.execute("SELECT count(*) FROM mission_probe_outcomes").fetchone()[0] == 0
    assert _events(case, mission.id, "PROBE_OUTCOMES_RECORDED") == []
    assert [(event[0], event[7]) for event in _events(case, mission.id)] == [
        ("COLLECTION_STARTED", "RUNNING"),
        ("OBSERVATIONS_COMMITTED", None),
        ("COLLECTION_STATE_CHANGED", "FAILED"),
    ]
    _assert_revision_matches_events(case, mission.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("rollback", (False, True))
async def test_cancellation_during_terminal_transaction_retains_physical_settlement(
    ingress_case, tmp_path, monkeypatch, rollback,
):
    """Cancel after event insertion, before commit; canonical settlement owns the journal."""
    case = ingress_case
    store, mission, executor = await _attention(case, tmp_path)
    original = case.repository._record_progress
    entered, release = threading.Event(), threading.Event()

    def pause():
        entered.set()
        assert release.wait(5), "The bounded transaction gate was not released"
        if rollback:
            raise RepositoryException("Controlled terminal rollback")

    if case.name == "postgres":
        async def gated_progress(*args, **kwargs):
            result = await original(*args, **kwargs)
            if kwargs.get("reason") == "COMPLETED":
                await asyncio.to_thread(pause)
            return result
    else:
        def gated_progress(*args, **kwargs):
            result = original(*args, **kwargs)
            if kwargs.get("reason") == "COMPLETED":
                pause()
            return result

    monkeypatch.setattr(case.repository, "_record_progress", gated_progress)
    task = asyncio.create_task(executor.execute(mission.id))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    expected = "FAILED" if rollback else "COMPLETED"
    assert _rows(case, "research_missions", mission.id, "status", key="id") == [(expected,)]
    assert [(event[0], event[7]) for event in _events(case, mission.id)] == [
        ("COLLECTION_STARTED", "RUNNING"),
        ("OBSERVATIONS_COMMITTED", None),
        ("PROBE_OUTCOMES_RECORDED", None),
        ("COLLECTION_STATE_CHANGED", expected),
    ]
    journals = await store.list_run_journals(mission.id)
    assert len(journals) == 1 and journals[0].status == expected
    assert await store.get_mission_writer_claim(mission.id) is None
    _assert_revision_matches_events(case, mission.id)
