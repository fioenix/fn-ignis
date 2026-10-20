"""T020 runs T019 fact/event invariants on physical disposable PostgreSQL storage."""

import psycopg
import pytest
import test_sqlite_fact_event_commits as shared
from test_mission_progress_ingress import ingress_case as ingress_case

pytestmark = [pytest.mark.asyncio, pytest.mark.parametrize('ingress_case', ('postgres',), indirect=True)]


def _durable(case):
    with psycopg.connect(case.dsn) as conn:
        return {table: [tuple(row) for row in conn.execute(f'SELECT * FROM {table} ORDER BY 1')]
                for table in ('sources', 'observations', 'mission_evidence',
                              'mission_evidence_qualifications', 'mission_claims',
                              'mission_claim_evidence', 'research_missions', 'mission_progress_events',
                              'mission_progress_revisions')}


@pytest.fixture(autouse=True)
def parity_helpers(monkeypatch):
    monkeypatch.setattr(shared, '_durable', _durable)


test_collection_fact_event_rollback = shared.test_sqlite_collection_fact_event_rollback
test_collection_lineage_replay_and_membership_delta = shared.test_sqlite_collection_lineage_replay_and_membership_delta
test_foreign_run_refuses_every_collection_unit = shared.test_sqlite_foreign_run_refuses_every_collection_unit
test_analysis_fact_event_transaction = shared.test_sqlite_analysis_fact_event_transaction
test_pruning_has_atomic_membership_change_receipt = shared.test_sqlite_pruning_has_atomic_membership_change_receipt


@pytest.mark.parametrize('cancel', (False, True))
async def test_same_sighting_retry_waits_for_physical_commit(ingress_case, tmp_path, cancel):
    import asyncio
    from test_postgres_probe_outcome_commits import _PoolBoundary, _reached
    from test_mission_progress_ingress import _events, _signal

    case = ingress_case
    mission, run_id = await shared._collection(case, tmp_path)
    signal = _signal()
    pool = await case.repository._get_pool()
    boundary = _PoolBoundary(pool)
    case.repository._pool = boundary
    tasks = []
    try:
        first = asyncio.create_task(case.repository.commit_collection_observations(mission.id, run_id, [signal]))
        tasks.append(first)
        await _reached(boundary.entered)
        assert signal.observation_id is None
        assert _durable(case)['observations'] == []
        if cancel:
            first.cancel()
            await asyncio.sleep(0)
            first.cancel()
        second = asyncio.create_task(case.repository.commit_collection_observations(mission.id, run_id, [signal]))
        tasks.append(second)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(second), 0.05)
        case.repository._pool = pool
        boundary.release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await first
        else:
            assert await first == 1
        assert await second == 0
        assert len(_durable(case)['observations']) == 1
        assert len(_events(case, mission.id, 'OBSERVATIONS_COMMITTED')) == 1
        assert signal.observation_id is not None and signal.source_id is not None
    finally:
        boundary.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        case.repository._pool = pool


@pytest.mark.parametrize('fault', (None, 'OBSERVATIONS_COMMITTED', 'CLAIM_GATE_CHANGED'))
async def test_pruning_cascade_and_gate_share_revision(ingress_case, tmp_path, fault):
    from uuid import UUID
    from test_mission_progress_ingress import _connection, _events, _market, _refuse_write, _submit_claim

    case = ingress_case
    store, mission, _brief, signal = await _market(case, tmp_path)
    assert (await _submit_claim(case, store, mission))['status'] == 'RECORDED'
    with _connection(case) as conn:
        conn.execute("UPDATE mission_claims SET status = 'PERMITTED', withheld_reasons = '{}'::text[]")
        run_id = conn.execute('SELECT id FROM mission_run_journals').fetchone()[0]
    before = _durable(case)
    if fault:
        with _refuse_write(case, 'mission_progress_events', kind=fault) as hits:
            with pytest.raises(psycopg.DatabaseError):
                await case.repository.commit_collection_pruning(mission.id, UUID(str(run_id)), [])
            assert hits() == 1
        assert _durable(case) == before
    else:
        assert await case.repository.commit_collection_pruning(mission.id, UUID(str(run_id)), []) == 1
        after = _durable(case)
        assert after['mission_evidence'] == after['mission_evidence_qualifications'] == after['mission_claim_evidence'] == []
        assert after['observations'] == before['observations']
        with _connection(case) as conn:
            row = conn.execute('SELECT id, status, withheld_reasons FROM mission_claims').fetchone()
        assert row[1:] == ('WITHHELD', ['EVIDENCE_BINDING_INVALIDATED'])
        events = _events(case, mission.id)
        assert [(e[0], e[5]) for e in events[-2:]] == [('OBSERVATIONS_COMMITTED', 1), ('CLAIM_GATE_CHANGED', 2)]
        assert events[-1][4] == events[-2][4] and events[-1][2] == str(row[0])
        assert events[-1][3][0]['observation_id'] == str(signal.observation_id)


async def test_duplicate_judgments_emit_one_reference_per_insert(ingress_case, tmp_path):
    from test_mission_progress_ingress import _events

    case = ingress_case
    _store, mission, _brief, signal, judgment = await shared._judgment(case, tmp_path)
    assert await case.repository.commit_evidence_qualifications(mission.id, [judgment, judgment]) == 2
    refs = _events(case, mission.id, 'QUALIFICATION_RECORDED')[-1][3]
    assert len(refs) == 1 and refs[0]['observation_id'] == str(signal.observation_id)
    before = _durable(case)
    assert len(before['mission_evidence_qualifications']) == 1
    assert await case.repository.commit_evidence_qualifications(mission.id, [judgment, judgment]) == 2
    assert _durable(case) == before


@pytest.mark.parametrize('unit', ('qualification', 'claim'))
async def test_frame_validation_fences_legacy_observation_writer(ingress_case, tmp_path, monkeypatch, unit):
    import asyncio
    from test_mission_progress_ingress import _signal

    case = ingress_case
    store, mission, brief, _signal_record, judgment = await shared._judgment(case, tmp_path)
    if unit == 'claim':
        from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
        from ignis.domain.research_workspace import MissionClaim
        await case.repository.commit_evidence_qualifications(mission.id, [judgment])
        frame = await load_current_evidence_frame(case.repository, store, mission)
        candidate = MissionClaim(mission_id=mission.id, frame_digest=frame.frame_digest,
                                client_claim_key='fenced-claim', claim_type='OBSERVATION',
                                wording='Recorded observation.', status='WITHHELD',
                                withheld_reasons=('INSUFFICIENT_EVIDENCE',), created_by='integration-host',
                                brief_revision_id=brief.brief_revision_id)
    validated, release = asyncio.Event(), asyncio.Event()
    snapshot = case.repository._commit_snapshot

    async def pause(conn, mission_id):
        result = await snapshot(conn, mission_id)
        validated.set()
        await release.wait()
        return result

    monkeypatch.setattr(case.repository, '_commit_snapshot', pause)
    tasks = []
    try:
        operation = (case.repository.commit_evidence_qualifications(mission.id, [judgment]) if unit == 'qualification'
                     else case.repository.commit_mission_claims(mission.id, frame.frame_digest, [candidate]))
        commit = asyncio.create_task(operation)
        tasks.append(commit)
        await asyncio.wait_for(validated.wait(), 5)
        later = _signal('Concurrent legacy observation')
        later.mission_id = mission.id
        writer = asyncio.create_task(case.repository.save_signals([later]))
        tasks.append(writer)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(writer), 0.1)
        assert not commit.done()
        release.set()
        result = await commit
        assert result == 1 if unit == 'qualification' else len(result) == 1
        assert await writer == 1
        if unit == 'claim':
            from ignis.domain.research_workspace import InvalidMissionClaimError
            before = _durable(case)
            with pytest.raises(InvalidMissionClaimError, match='stale'):
                await case.repository.commit_mission_claims(mission.id, frame.frame_digest, [candidate])
            assert _durable(case) == before
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_probe_publication_and_analysis_use_same_lock_order(ingress_case, tmp_path):
    import asyncio
    from dataclasses import replace
    from uuid import uuid4
    from test_postgres_probe_outcome_commits import _PoolBoundary, _command, _reached
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

    case = ingress_case
    _store, mission, _brief, _signal_record, judgment = await shared._judgment(case, tmp_path)
    outcome = (await case.repository.get_latest_completed_probe_outcomes(mission.id))[0]
    from ignis.application.ports.research_workspace_port import RunJournal
    from test_mission_progress_ingress import NOW
    run_id = uuid4()
    await case.repository.record_run_journal(RunJournal(
        run_id=run_id, mission_id=mission.id, workspace_id=mission.workspace_id,
        journal_path=tmp_path / 'second-run.json', sequence=2, status='COMPLETED',
        started_at=NOW, completed_at=NOW,
    ))
    outcome = replace(outcome, outcome_id=uuid4(), run_id=run_id)
    pool = await case.repository._get_pool()
    boundary = _PoolBoundary(pool, hold_revision_lock=True, hold_commit=False)
    case.repository._pool = boundary
    other = PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=1)
    tasks = []
    try:
        publisher = asyncio.create_task(case.repository.commit_probe_outcomes(_command(mission, outcome)))
        tasks.append(publisher)
        try:
            await _reached(boundary.revision_locked)
        except asyncio.TimeoutError:
            if publisher.done():
                await publisher
            raise
        analysis = asyncio.create_task(other.commit_evidence_qualifications(mission.id, [judgment]))
        tasks.append(analysis)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(analysis), 0.1)
        boundary.continue_revision.set()
        assert (await asyncio.wait_for(publisher, 5)).outcome_count == 1
        assert await asyncio.wait_for(analysis, 5) == 1
    finally:
        boundary.continue_revision.set()
        boundary.release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        case.repository._pool = pool
        await other.close()
