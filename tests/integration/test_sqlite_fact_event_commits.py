"""T019 adapter contracts using T016's real databases and physical refusal gates.

Producer wiring stays with T021/T022. A split fact/event commit, false arrival,
foreign run, stale frame, or duplicate replay must break these assertions.
"""

import asyncio
import threading
import sqlite3
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import psycopg
from test_mission_progress_ingress import ingress_case as _shared_ingress_case

from test_mission_progress_ingress import (
    NOW,
    _attention,
    _market,
    _signal,
    _qualification,
    _connection,
    _events,
    _revision,
    _refuse_write,
)
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.submit_evidence_qualifications import SubmitEvidenceQualificationsUseCase
from ignis.domain.research_workspace import (
    InvalidEvidenceQualificationError,
    InvalidMissionClaimError,
    MissionClaim,
    MissionClaimEvidence,
    compute_frame_fingerprint,
)
from ignis.domain.exceptions import RepositoryException

ingress_case = _shared_ingress_case

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.parametrize("ingress_case", ("sqlite-file", "sqlite-memory"), indirect=True),
]


async def _collection(case, tmp_path):
    store, mission, _ = await _attention(case, tmp_path)
    run_id = uuid4()
    await store.record_run_journal(
        RunJournal(
            run_id=run_id,
            mission_id=mission.id,
            workspace_id=mission.workspace_id,
            journal_path=tmp_path / "adapter-run.json",
            sequence=1,
            status="STARTED",
            started_at=NOW,
        )
    )
    return mission, run_id


def _durable(case):
    with _connection(case) as conn:
        return {
            table: [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY rowid")]
            for table in (
                "sources",
                "observations",
                "mission_evidence",
                "mission_evidence_qualifications",
                "mission_claims",
                "mission_claim_evidence",
                "research_missions",
                "mission_progress_events",
                "mission_progress_revisions",
            )
        }


@pytest.mark.parametrize("unit", ("observation", "membership", "start", "terminal"))
@pytest.mark.parametrize("fault", ("fact", "event"))
async def test_sqlite_collection_fact_event_rollback(ingress_case, tmp_path, unit, fault):
    case = ingress_case
    mission, run_id = await _collection(case, tmp_path)
    signal = _signal()
    if unit == "membership":
        await case.repository.save_signals([signal])
    if unit == "terminal":
        await case.repository.commit_collection_state(replace(mission, status="RUNNING"), run_id)
    kinds = {
        "observation": "OBSERVATIONS_COMMITTED",
        "membership": "OBSERVATIONS_COMMITTED",
        "start": "COLLECTION_STARTED",
        "terminal": "COLLECTION_STATE_CHANGED",
    }
    table = {
        "observation": "observations",
        "membership": "mission_evidence",
        "start": "research_missions",
        "terminal": "research_missions",
    }[unit]
    before = _durable(case)
    identity_before = (signal.observation_id, signal.source_id, signal.identity_source, signal.time_provenance)
    with _refuse_write(
        case,
        "mission_progress_events" if fault == "event" else table,
        kind=kinds[unit] if fault == "event" else None,
        operation="UPDATE" if fault == "fact" and unit in ("start", "terminal") else "INSERT",
    ) as hits:
        with pytest.raises((RepositoryException, sqlite3.DatabaseError, psycopg.DatabaseError)):
            if unit == "observation":
                await case.repository.commit_collection_observations(mission.id, run_id, [signal])
            elif unit == "membership":
                await case.repository.commit_collection_membership(mission.id, run_id, [signal])
            else:
                await case.repository.commit_collection_state(
                    replace(mission, status="RUNNING" if unit == "start" else "COMPLETED"), run_id
                )
        if fault == "event":
            assert hits() == 1
    assert _durable(case) == before
    assert (signal.observation_id, signal.source_id, signal.identity_source, signal.time_provenance) == identity_before


async def test_sqlite_collection_lineage_replay_and_membership_delta(ingress_case, tmp_path):
    case = ingress_case
    mission, run_id = await _collection(case, tmp_path)
    assert await case.repository.commit_collection_state(replace(mission, status="RUNNING"), run_id) is None
    signal = _signal()
    assert await case.repository.commit_collection_observations(mission.id, run_id, [signal]) == 1
    events = _events(case, mission.id)
    refs = events[-1][3]
    with _connection(case) as conn:
        lineage = conn.execute("SELECT id, source_id FROM observations").fetchone()
    assert refs == [
        {
            "mission_id": str(mission.id),
            "observation_id": str(lineage[0]),
            "source_id": str(lineage[1]),
            "evidence_role": "ATTENTION_CONTEXT",
            "direction": None,
            "qualification_relation": None,
            "qualification_frame_fingerprint": None,
        }
    ]
    assert events[-1][1] == str(run_id)
    assert signal.observation_id is not None and signal.source_id is not None
    before = _durable(case)
    assert await case.repository.commit_collection_observations(mission.id, run_id, [signal]) == 0
    assert await case.repository.commit_collection_membership(mission.id, run_id, [signal]) == 0
    await case.repository.commit_collection_state(replace(mission, status="RUNNING"), run_id)
    assert _durable(case) == before
    await case.repository.prune_mission_evidence(mission.id, [])
    assert await case.repository.commit_collection_membership(mission.id, run_id, [signal]) == 1
    receipts = _events(case, mission.id, "OBSERVATIONS_COMMITTED")
    assert len(receipts) == 2 and receipts[-1][7] == "MEMBERSHIP_REATTACHED"
    assert receipts[-1][3] == refs
    await case.repository.commit_collection_state(replace(mission, status="COMPLETED"), run_id)
    assert [(e[0], e[7]) for e in _events(case, mission.id)] == [
        ("COLLECTION_STARTED", "RUNNING"),
        ("OBSERVATIONS_COMMITTED", None),
        ("OBSERVATIONS_COMMITTED", "MEMBERSHIP_REATTACHED"),
        ("COLLECTION_STATE_CHANGED", "COMPLETED"),
    ]
    assert _revision(case, mission.id) == 4


@pytest.mark.parametrize("unit", ("observation", "membership", "state"))
async def test_sqlite_foreign_run_refuses_every_collection_unit(ingress_case, tmp_path, unit):
    case = ingress_case
    mission, _run_id = await _collection(case, tmp_path)
    signal = _signal()
    if unit == "membership":
        await case.repository.save_signals([signal])
    before = _durable(case)
    with pytest.raises(RepositoryException):
        if unit == "state":
            await case.repository.commit_collection_state(replace(mission, status="RUNNING"), uuid4())
        else:
            method = getattr(
                case.repository, f"commit_collection_{'observations' if unit == 'observation' else 'membership'}"
            )
            await method(mission.id, uuid4(), [signal])
    assert _durable(case) == before


async def _judgment(case, tmp_path):
    store, mission, brief, signal = await _market(case, tmp_path)
    judgment = SubmitEvidenceQualificationsUseCase._judgment(
        mission.id, compute_frame_fingerprint(mission, brief), brief, _qualification(signal)
    )
    return store, mission, brief, signal, judgment


@pytest.mark.parametrize("unit", ("qualification", "claim"))
@pytest.mark.parametrize("fault", (None, "fact", "event", "stale"))
async def test_sqlite_analysis_fact_event_transaction(ingress_case, tmp_path, unit, fault):
    case = ingress_case
    store, mission, brief, signal, judgment = await _judgment(case, tmp_path)
    if unit == "qualification":
        batch = [replace(judgment, frame_fingerprint="0" * 64)] if fault == "stale" else [judgment]

        async def commit():
            return await case.repository.commit_evidence_qualifications(mission.id, batch)

        table, kind = "mission_evidence_qualifications", "QUALIFICATION_RECORDED"
    else:
        await case.repository.commit_evidence_qualifications(mission.id, [judgment])
        frame = await load_current_evidence_frame(case.repository, store, mission)
        claim_id = uuid4()
        claim = MissionClaim(
            mission_id=mission.id,
            frame_digest=frame.frame_digest,
            client_claim_key="adapter-candidate",
            claim_type="OBSERVATION",
            wording="Recorded observation.",
            status="WITHHELD",
            withheld_reasons=("INSUFFICIENT_EVIDENCE",),
            created_by="integration-host",
            brief_revision_id=brief.brief_revision_id,
            claim_id=claim_id,
            evidence_bindings=(
                MissionClaimEvidence(
                    claim_id=claim_id,
                    observation_id=signal.observation_id,
                    probe_outcome_id=None,
                    role="SUPPORT",
                    hypothesis_target="core",
                ),
            ),
        )
        if fault == "stale":
            later = _signal("Changed evidence frame")
            later.mission_id = mission.id
            await case.repository.save_signals([later])

        async def commit():
            return await case.repository.commit_mission_claims(mission.id, frame.frame_digest, [claim])

        table, kind = "mission_claims", "CLAIM_GATE_CHANGED"
    before = _durable(case)
    if fault in ("fact", "event"):
        with _refuse_write(
            case, "mission_progress_events" if fault == "event" else table, kind=kind if fault == "event" else None
        ) as hits:
            with pytest.raises(
                (
                    InvalidEvidenceQualificationError,
                    InvalidMissionClaimError,
                    RepositoryException,
                    sqlite3.DatabaseError,
                    psycopg.DatabaseError,
                )
            ):
                await commit()
            if fault == "event":
                assert hits() == 1
        assert _durable(case) == before
    elif fault == "stale":
        with pytest.raises((InvalidEvidenceQualificationError, InvalidMissionClaimError)):
            await commit()
        assert _durable(case) == before
    else:
        await commit()
        events = _events(case, mission.id, kind)
        assert len(events) == 1 and events[0][1] is None
        assert events[0][3][0]["observation_id"] == str(signal.observation_id)
        assert events[0][3][0]["source_id"] == str(signal.source_id)
        assert events[0][3][0]["qualification_frame_fingerprint"] == judgment.frame_fingerprint
        assert events[0][3][0]["direction"] == "SUPPORT"
        if unit == "claim":
            assert events[0][2] == str(claim_id)
        original = _durable(case)
        await commit()
        assert _durable(case) == original


@pytest.mark.parametrize("cancel", (False, True))
async def test_sqlite_same_sighting_retry_after_concurrent_or_cancelled_commit(
    ingress_case,
    tmp_path,
    monkeypatch,
    cancel,
):
    case = ingress_case
    mission, run_id = await _collection(case, tmp_path)
    signal = _signal()
    entered, release = threading.Event(), threading.Event()
    connect = case.repository._get_connection

    def pause():
        entered.set()
        assert release.wait(5), "The bounded test gate was not released"
        return 1

    def gated_connection():
        conn = connect()
        conn.create_function("t019_pause", 0, pause)
        return conn

    with _connection(case) as conn:
        conn.execute(
            "CREATE TRIGGER t019_pause BEFORE INSERT ON mission_progress_events"
            " WHEN NEW.kind = 'OBSERVATIONS_COMMITTED' BEGIN SELECT t019_pause(); END"
        )
    tasks = []
    try:
        monkeypatch.setattr(case.repository, "_get_connection", gated_connection)
        first = asyncio.create_task(case.repository.commit_collection_observations(mission.id, run_id, [signal]))
        tasks.append(first)
        assert await asyncio.to_thread(entered.wait, 5)
        assert signal.observation_id is None
        if cancel:
            first.cancel()
        second = asyncio.create_task(case.repository.commit_collection_observations(mission.id, run_id, [signal]))
        tasks.append(second)
        await asyncio.sleep(0)
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            assert await first == 1
        assert await second == 0
        with _connection(case) as conn:
            assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert len(_events(case, mission.id, "OBSERVATIONS_COMMITTED")) == 1
        assert signal.observation_id is not None
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        with _connection(case) as conn:
            conn.execute("DROP TRIGGER t019_pause")
        monkeypatch.setattr(case.repository, "_get_connection", connect)


@pytest.mark.parametrize("fault", (None, "fact", "event"))
async def test_sqlite_pruning_has_atomic_membership_change_receipt(ingress_case, tmp_path, fault):
    case = ingress_case
    mission, run_id = await _collection(case, tmp_path)
    signal = _signal()
    await case.repository.commit_collection_observations(mission.id, run_id, [signal])
    original_refs = _events(case, mission.id)[0][3]
    before = _durable(case)
    if fault:
        with _refuse_write(
            case,
            "mission_progress_events" if fault == "event" else "mission_evidence",
            kind="OBSERVATIONS_COMMITTED" if fault == "event" else None,
            operation="INSERT" if fault == "event" else "DELETE",
        ) as hits:
            with pytest.raises((sqlite3.DatabaseError, psycopg.DatabaseError)):
                await case.repository.commit_collection_pruning(mission.id, run_id, [])
            if fault == "event":
                assert hits() == 1
        assert _durable(case) == before
    else:
        assert await case.repository.commit_collection_pruning(mission.id, run_id, []) == 1
        events = _events(case, mission.id)
        assert events[-1][7] == "MEMBERSHIP_PRUNED" and events[-1][3] == original_refs
        after = _durable(case)
        assert after["observations"] == before["observations"] and after["mission_evidence"] == []
        assert await case.repository.commit_collection_pruning(mission.id, run_id, []) == 0
        assert _durable(case) == after


@pytest.mark.parametrize("fault", (None, "OBSERVATIONS_COMMITTED", "CLAIM_GATE_CHANGED"))
async def test_sqlite_prune_cascades_and_claim_gate_share_one_transaction(ingress_case, tmp_path, fault):
    """A seeded permitted row exercises physical invalidation, not strategic permission."""
    from test_mission_progress_ingress import _submit_claim

    case = ingress_case
    store, mission, _brief, signal = await _market(case, tmp_path)
    assert (await _submit_claim(case, store, mission))["status"] == "RECORDED"
    with _connection(case) as conn:
        conn.execute("UPDATE mission_claims SET status = 'PERMITTED', withheld_reasons = '[]'")
        run_id = conn.execute("SELECT id FROM mission_run_journals").fetchone()[0]
    before = _durable(case)
    if fault:
        with _refuse_write(case, "mission_progress_events", kind=fault) as hits:
            with pytest.raises((sqlite3.DatabaseError, psycopg.DatabaseError)):
                await case.repository.commit_collection_pruning(mission.id, UUID(run_id), [])
            assert hits() == 1
        assert _durable(case) == before
    else:
        assert await case.repository.commit_collection_pruning(mission.id, UUID(run_id), []) == 1
        after = _durable(case)
        assert (
            after["mission_evidence"]
            == after["mission_evidence_qualifications"]
            == after["mission_claim_evidence"]
            == []
        )
        assert after["observations"] == before["observations"]
        with _connection(case) as conn:
            row = conn.execute("SELECT id, status, withheld_reasons FROM mission_claims").fetchone()
        assert row[1:] == ("WITHHELD", '["EVIDENCE_BINDING_INVALIDATED"]')
        events = _events(case, mission.id)
        assert [(e[0], e[5]) for e in events[-2:]] == [("OBSERVATIONS_COMMITTED", 1), ("CLAIM_GATE_CHANGED", 2)]
        assert events[-1][4] == events[-2][4]
        assert events[-1][2] == row[0]
        assert events[-1][3][0]["observation_id"] == str(signal.observation_id)
