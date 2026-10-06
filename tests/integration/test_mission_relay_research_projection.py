"""T054 physical research reads and privacy/currentness projection controls."""

import pytest

from ignis.domain.entities import ResearchMission
from ignis.application.ports.mission_relay_port import MissionRelayRead
from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from tests.integration.test_mission_relay_read_boundary import (
    _reader, _request, _state,
)
from tests.integration import test_mission_relay_read_boundary as physical
from tests.integration.test_research_work_persistence import _arrange, _commit

relay_case = physical.relay_case


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'memory'), indirect=True)
async def test_uninstalled_research_is_unknown_without_breaking_canonical_read(relay_case):
    case, missions, runs = relay_case
    mission = ResearchMission(title='Canonical before research', keywords=['synthetic'],
                              workspace_id=missions[0].workspace_id, surface='ATTENTION')
    await case.repository.save_mission(mission)
    before = _state(case)
    request = _request(mission, None)
    raw = await _reader(case.repository).load_snapshot(request)
    assert type(raw) is MissionRelayRead
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(request)).to_payload()
    assert payload.get('research') == {'availability': 'SCHEMA_UNAVAILABLE'}
    assert _state(case) == before


@pytest.mark.asyncio
async def test_admitted_result_projects_exact_current_revision_and_observed_time(relay_case, tmp_path):
    case, mission, _, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    request = _request(mission, None)
    raw = await _reader(case.repository).load_snapshot(request)
    assert type(raw) is MissionRelayRead
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(request)).to_payload()
    research = payload.get('research')
    assert research is not None, 'Committed research is absent from coherent viewer projection.'
    assert research['availability'] == 'AVAILABLE'
    assert research['revision'] == payload['high_water']['revision'] == receipt.revision
    assert research['work_items'][0]['work_id'] == str(work.work_id)
    finding = research['findings'][0]
    assert finding['statement'] == handoff.findings[0].statement
    assert finding['current_eligible'] is True and finding['latest_recorded'] is True
    assert finding['recorded_at'] == receipt.recorded_at.isoformat()
    assert finding['recorded_provenance'] == 'HARNESS_OBSERVED'
    assert research['observation_count'] == len(handoff.observation_sources)


@pytest.mark.asyncio
async def test_unpermitted_strategic_candidate_has_no_text_in_any_result_panel(relay_case, tmp_path):
    from dataclasses import replace
    import json
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    sentinel = 'STRATEGIC_SECRET_SENTINEL'
    candidate = replace(handoff.findings[0], result_type='STRATEGIC_CANDIDATE', statement=sentinel,
                        limitations=(sentinel,), open_questions=(sentinel,), alternative_explanation=sentinel)
    handoff = replace(handoff, result=sentinel, findings=(candidate,), limitations=(sentinel,), open_questions=(sentinel,))
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    assert receipt.disposition == 'APPLIED'
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))).to_payload()
    assert sentinel not in json.dumps(payload)
    research = payload['research']
    assert research['findings'][0]['text_withheld'] is True
    assert research['findings'][0]['statement'] is None
    assert research['handoffs'][0]['result'] is None
    assert research['handoffs'][0]['findings'][0]['statement'] is None


@pytest.mark.asyncio
async def test_start_activity_is_finite_host_report_and_not_new_evidence(relay_case, tmp_path):
    from dataclasses import replace
    from datetime import timedelta
    from tests.integration.test_mission_relay_read_boundary import NOW
    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    raw = await _reader(case.repository).load_snapshot(_request(mission, None))
    assert type(raw) is MissionRelayRead
    raw = replace(raw, read_at=NOW + timedelta(days=1))
    from ignis.application.use_cases.get_mission_relay_snapshot import _project
    def view(read):
        return _project(selected_mission_id=mission.id, selected_run_id=None,
                        evidence=read.evidence, run=read.run, revision=read.high_water.revision,
                        read_at=read.read_at, page_size=read.request.page_size,
                        coherent_read=read).to_payload()
    payload = view(raw)
    activity = payload['research']['work_items'][0]['activity']
    assert activity['state'] == 'ACTIVE' and activity['provenance'] == 'HOST_REPORTED'
    assert activity['receipt']['work_id'] == str(work.work_id)
    assert payload['research']['capacity'] is None
    assert raw.high_water.revision == revision and payload['counts']['observations'] == raw.total_observations
    stale = view(replace(raw, read_at=NOW + timedelta(days=301)))
    assert stale['research']['work_items'][0]['activity']['state'] == 'STALE'
    unknown = view(replace(raw, research_activities=()))
    assert unknown['research']['work_items'][0]['activity'] == {'state': 'UNKNOWN', 'provenance': None, 'receipt': None}


@pytest.mark.asyncio
async def test_permitted_identity_never_licenses_changed_candidate_or_aggregate_prose(relay_case, tmp_path):
    import json
    from dataclasses import replace
    from uuid import uuid4
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from tests.unit.test_mission_claims import _observation_candidate
    from tests.integration.test_research_work_persistence import _another_work
    case, mission, domain, port, work, handoff, _ = await _arrange(relay_case, tmp_path)
    store = WorkspaceRepository(repository=case.repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    signal = next(s for s in evidence.signals if s.raw_title == 'Demand evidence')
    submitted = await SubmitMissionClaimsUseCase(case.repository, store).execute(
        str(mission.id), work.inputs.frame_digest, [_observation_candidate(signal)], created_by='t054-fixture')
    assert submitted['permitted'] == 1
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    claim = evidence.claims[0]
    state = await case.repository.load_research_work(mission.id)
    inputs = replace(work.inputs, observation_ids=(signal.observation_id,))
    producer, revision = await _another_work(case, mission, domain, port, work, inputs, state.revision)
    sentinel = 'UNLICENSED_CANDIDATE_PROSE'
    finding = replace(handoff.findings[0], finding_id=uuid4(), handoff_id=uuid4(), work_id=producer.work_id,
                      inputs=inputs, result_type='STRATEGIC_CANDIDATE', claim_id=claim.claim_id,
                      statement=sentinel, supporting_observation_ids=(signal.observation_id,),
                      contradicting_observation_ids=(), context_observation_ids=())
    result = replace(handoff, handoff_id=finding.handoff_id, work_id=producer.work_id,
                     expected_version=producer.version, inputs=inputs, result=sentinel,
                     observation_sources=((signal.observation_id, signal.source_id),),
                     claim_ids=(claim.claim_id,), findings=(finding,))
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', result, revision=revision)
    assert receipt.disposition == 'APPLIED'
    run = (await store.list_run_journals(mission.id))[0]
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, run.run_id))).to_payload()
    assert payload['claim_gate']['state'] == 'CURRENT'
    row = payload['research']['findings'][0]
    assert row['statement'] == claim.wording and row['text_withheld'] is False
    assert sentinel not in json.dumps(payload)
    assert payload['research']['handoffs'][0]['result'] is None


@pytest.mark.asyncio
async def test_shared_inputs_keep_one_identity_and_membership_withdrawal_preserves_history(relay_case, tmp_path):
    from tests.integration.test_research_work_persistence import _another_work, _sql
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    other, revision = await _another_work(case, mission, domain, port, work, work.inputs, revision)
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    assert receipt.disposition == 'APPLIED'
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    before = (await use_case.execute(_request(mission, None))).to_payload()
    research = before['research']
    assert len(research['work_items']) == 2
    assert {w['work_id'] for w in research['work_items']} == {str(work.work_id), str(other.work_id)}
    assert research['observation_count'] == len(work.inputs.observation_ids) == 6
    assert research['source_count'] == 6
    await _sql(case, 'DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?',
               (mission.id, handoff.observation_sources[0][0]))
    after = (await use_case.execute(_request(mission, None))).to_payload()['research']
    assert after['current_finding_revisions'] == []
    assert after['findings'][0]['latest_recorded'] is True
    assert after['findings'][0]['current_eligible'] is False
    assert after['handoffs'][0]['observation_sources'] == research['handoffs'][0]['observation_sources']
    assert after['observation_count'] == 5


@pytest.mark.asyncio
async def test_decoder_reuses_exact_acquired_corpus_without_bootstrap_or_second_repository_load(relay_case, tmp_path, monkeypatch):
    case, mission, _, _, _, _, _ = await _arrange(relay_case, tmp_path)
    cls = type(case.repository)
    decoder = cls._decode_research_snapshot
    canonical_bundles = []
    if case.name == 'postgres':
        async def observed(conn, identity, *, canonical):
            canonical_bundles.append(canonical)
            return await decoder(conn, identity, canonical=canonical)
    else:
        def observed(conn, identity, *, canonical):
            canonical_bundles.append(canonical)
            return decoder(conn, identity, canonical=canonical)
    monkeypatch.setattr(cls, '_decode_research_snapshot', staticmethod(observed))
    def forbidden(*args, **kwargs):
        raise AssertionError('Viewer must not bootstrap or load a second repository/corpus.')
    for name in ('_commit_snapshot', '_ensure_schema', '_ensure_research_schema', 'load_research_work', 'get_mission_signals'):
        if hasattr(cls, name):
            monkeypatch.setattr(cls, name, forbidden)
    request = _request(mission, None)
    observer = physical._observe_postgres(monkeypatch) if case.name == 'postgres' else physical._observe_sqlite(monkeypatch, case.repository)
    with observer as observation:
        raw = await _reader(case.repository).load_snapshot(request)
    assert type(raw) is MissionRelayRead
    assert len(canonical_bundles) == 1
    assert canonical_bundles[0].signals is raw.frame_evidence.signals
    assert canonical_bundles[0].manifest is raw.evidence.manifest
    assert raw.research.revision == raw.high_water.revision
    if case.name == 'postgres':
        physical._assert_postgres_reads(observation)
    else:
        observation.assert_no_writes()


@pytest.mark.asyncio
@pytest.mark.parametrize('relay_case', ('file', 'memory'), indirect=True)
async def test_partial_research_schema_does_not_become_empty_or_bootstrap(relay_case):
    from tests.integration.test_research_work_persistence import _sql
    case, missions, _ = relay_case
    mission = ResearchMission(title='Partial optional research', keywords=['synthetic'],
                              workspace_id=missions[0].workspace_id, surface='ATTENTION')
    await case.repository.save_mission(mission)
    await _sql(case, 'CREATE TABLE research_assignments (assignment_id TEXT)')
    before = _state(case)
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))).to_payload()
    assert payload['research'] == {'availability': 'SCHEMA_UNAVAILABLE'}
    assert _state(case) == before


@pytest.mark.asyncio
async def test_dependency_fixed_point_keeps_latest_history_distinct_from_current(relay_case, tmp_path):
    from dataclasses import replace
    from uuid import uuid4
    from tests.integration.test_research_work_persistence import _another_work
    case, mission, domain, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    original = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    finding = handoff.findings[0]
    inputs = replace(work.inputs, finding_revisions=((finding.finding_id, 1),))
    producer, revision = await _another_work(case, mission, domain, port, work, inputs, original.revision)
    revised = replace(finding, revision=2, predecessor_revision=1, inputs=inputs,
                      work_id=producer.work_id, handoff_id=uuid4())
    result = replace(handoff, handoff_id=revised.handoff_id, work_id=producer.work_id,
                     expected_version=producer.version, inputs=inputs, findings=(revised,))
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', result, revision=revision)
    assert receipt.disposition == 'APPLIED'
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))).to_payload()
    research = payload['research']
    assert research['current_finding_revisions'] == []
    assert research['latest_finding_revisions'] == [{'finding_id': str(finding.finding_id), 'revision': 2}]
    assert [(f['revision'], f['latest_recorded'], f['current_eligible']) for f in research['findings']] == [(1, False, False), (2, True, False)]


@pytest.mark.asyncio
async def test_real_heartbeat_between_canonical_and_research_reads_cannot_mix_snapshots(relay_case, tmp_path, monkeypatch):
    import asyncio
    import threading
    import sqlite3
    from datetime import timedelta
    from tests.integration.test_mission_relay_read_boundary import NOW
    case, mission, domain, port, work, _, revision = await _arrange(relay_case, tmp_path)
    if case.name == 'sqlite' and case.repository._mem_conn is None:
        with sqlite3.connect(case.repository._db_path) as conn:
            assert conn.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    cls = type(case.repository)
    decoder = cls._decode_research_snapshot
    entered, release = asyncio.Event(), asyncio.Event()
    thread_release = threading.Event()
    loop = asyncio.get_running_loop()
    held = False
    if case.name == 'postgres':
        async def observed(conn, identity, *, canonical):
            nonlocal held
            if not held:
                held = True
                entered.set()
                await release.wait()
            return await decoder(conn, identity, canonical=canonical)
    else:
        def observed(conn, identity, *, canonical):
            nonlocal held
            if not held:
                held = True
                loop.call_soon_threadsafe(entered.set)
                assert thread_release.wait(5), 'Pinned reader was not released.'
            return decoder(conn, identity, canonical=canonical)
    monkeypatch.setattr(cls, '_decode_research_snapshot', staticmethod(observed))
    task = asyncio.create_task(_reader(case.repository).load_snapshot(_request(mission, None)))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        receipt = domain.ResearchActivityReceipt(work_id=work.work_id, epoch=1, ownership_fence=work.ownership_fence,
            execution_ref='later-heartbeat', occurred_at=NOW, fresh_until=NOW + timedelta(days=301), provenance='HOST_REPORTED')
        updated = await _commit(case.repository, port, mission, 'RECORD_ACTIVITY', port.ResearchWorkStartAdmission(
            work_id=work.work_id, expected_version=work.version, ownership_fence=work.ownership_fence, receipt=receipt), revision=revision)
        assert updated.disposition == 'APPLIED' and updated.revision == revision + 1
        release.set()
        thread_release.set()
        old = await asyncio.wait_for(task, 5)
        assert type(old) is MissionRelayRead
        assert old.research.revision == old.high_water.revision == revision
        assert old.research.work_items[0].version == work.version
        fresh = await _reader(case.repository).load_snapshot(_request(mission, None))
        assert fresh.research.revision == fresh.high_water.revision == updated.revision
        assert fresh.research.work_items[0].version == updated.work_version
        assert old.research_frame_digest == fresh.research_frame_digest == work.inputs.frame_digest
        assert old.total_observations == fresh.total_observations
    finally:
        release.set()
        thread_release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_available_empty_is_measured_zero_not_schema_unknown(relay_case):
    case, missions, _ = relay_case
    if case.name != 'postgres':
        await case.repository._ensure_research_schema()
    mission = ResearchMission(title='Measured empty research', keywords=['synthetic'],
                              workspace_id=missions[0].workspace_id, surface='ATTENTION')
    await case.repository.save_mission(mission)
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))).to_payload()
    research = payload['research']
    assert research['availability'] == 'AVAILABLE'
    assert research['work_items'] == research['handoffs'] == research['findings'] == []
    assert research['observation_count'] == research['source_count'] == 0
    assert research['capacity'] is None and research['current_run_id'] is None and research['frame_digest'] is None


@pytest.mark.asyncio
async def test_projection_masks_all_private_labels_even_for_unsanitized_internal_records(relay_case, tmp_path):
    from dataclasses import replace
    import json
    from ignis.application.use_cases.get_mission_relay_snapshot import _project
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    raw = await _reader(case.repository).load_snapshot(_request(mission, None))
    secret = 'person@example.com'
    finding = replace(raw.research.findings[0], statement=secret, limitations=(secret,),
                      open_questions=(secret,), alternative_explanation=secret)
    state = replace(raw.research,
        assignments=tuple(replace(a, host_task_ref=secret, capability=secret) for a in raw.research.assignments),
        work_items=tuple(replace(w, question=secret, expertise=secret, assignee_ref=secret,
                                ownership_fence=secret) for w in raw.research.work_items),
        findings=(finding,), handoffs=tuple(replace(h, consumer_ref=secret, ownership_fence=secret,
            result=secret, limitations=(secret,), open_questions=(secret,), findings=(finding,)) for h in raw.research.handoffs))
    read = replace(raw, research=state)
    result = _project(selected_mission_id=mission.id, selected_run_id=None, evidence=read.evidence,
                      run=read.run, revision=read.high_water.revision, read_at=read.read_at,
                      page_size=read.request.page_size, coherent_read=read)
    payload = result.to_payload()
    assert 'research' in payload and secret not in json.dumps(payload)
    assert secret not in repr(result)
    assert '[REDACTED' in json.dumps(payload)


@pytest.mark.asyncio
async def test_research_projection_rejects_oversized_response_without_partial_private_dump(relay_case, tmp_path):
    from dataclasses import replace
    from uuid import uuid4
    from ignis.application.use_cases.get_mission_relay_snapshot import _project
    case, mission, _, port, _, handoff, revision = await _arrange(relay_case, tmp_path)
    receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    raw = await _reader(case.repository).load_snapshot(_request(mission, None))
    findings = tuple(replace(raw.research.findings[0], finding_id=uuid4(), statement='x' * 4096) for _ in range(300))
    base = next(m for m in raw.research.recorded_metadata if m.record_kind == 'FINDING')
    metadata = tuple(m for m in raw.research.recorded_metadata if m.record_kind != 'FINDING') + tuple(
        replace(base, record_id=f.finding_id) for f in findings)
    state = replace(raw.research, findings=findings, recorded_metadata=metadata,
                    current_finding_revisions=tuple((f.finding_id, 1) for f in findings))
    read = replace(raw, research=state)
    result = _project(selected_mission_id=mission.id, selected_run_id=None, evidence=read.evidence,
                      run=read.run, revision=receipt.revision, read_at=read.read_at,
                      page_size=read.request.page_size, coherent_read=read).to_payload()
    assert result == {'schema_version': 1, 'status': 'REFUSED', 'reason_code': 'RESPONSE_TOO_LARGE'}


@pytest.mark.asyncio
async def test_research_activity_from_foreign_work_cannot_enter_coherent_read(relay_case, tmp_path):
    from dataclasses import replace
    from uuid import uuid4
    case, mission, _, _, _, _, _ = await _arrange(relay_case, tmp_path)
    raw = await _reader(case.repository).load_snapshot(_request(mission, None))
    assert raw.research_activities
    with pytest.raises(ValueError, match='activity scope'):
        replace(raw, research_activities=(replace(raw.research_activities[0], work_id=uuid4()),))


@pytest.mark.asyncio
async def test_unrelated_mission_never_inherits_research_work_or_sources(relay_case, tmp_path):
    case, mission, _, _, _, _, _ = await _arrange(relay_case, tmp_path)
    unrelated = ResearchMission(title='Unrelated scope', keywords=['synthetic'],
                                workspace_id=mission.workspace_id, surface='ATTENTION')
    await case.repository.save_mission(unrelated)
    payload = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(unrelated, None))).to_payload()
    assert payload['research']['mission_id'] == str(unrelated.id)
    assert payload['research']['work_items'] == []
    assert payload['research']['findings'] == []
    assert payload['research']['observation_count'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('incompatibility', ('views', 'column_type'))
async def test_incompatible_relations_preserve_canonical_gate_and_unknown_research(relay_case, incompatibility):
    """Explicit fixture DDL, never read-triggered setup; real same-name relations reject false zero."""
    import re
    from pathlib import Path
    from tests.integration.test_research_work_persistence import _sql
    from ignis.infrastructure.persistence.sqlite_research_schema import SCHEMA
    case, missions, _ = relay_case
    mission = ResearchMission(title='Canonical with incompatible optional research', keywords=['synthetic'],
                              workspace_id=missions[0].workspace_id, surface='ATTENTION')
    await case.repository.save_mission(mission)
    request = _request(mission, None)
    before = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(request)).to_payload()
    source = Path('sql/028_research_work.sql').read_text() if case.name == 'postgres' else SCHEMA
    declarations = {}
    for name, body in re.findall(r'CREATE TABLE IF NOT EXISTS (?:public\.)?(research_\w+) \((.*?)\n\);', source, re.S):
        declarations[name] = [(m.group(1), m.group(2)) for line in body.splitlines()
                             if (m := re.match(r'\s+(\w+) (UUID\[\]|TEXT\[\]|UUID|TEXT|TIMESTAMPTZ|INTEGER|BIGINT)(?=\s|,)', line))]
    assert len(declarations) == 15
    from ignis.infrastructure.persistence.mission_relay_reader import _RESEARCH_SCHEMA_COLUMNS, _RESEARCH_COLUMN_TYPES
    assert {table: {name for name, _ in columns} for table, columns in declarations.items()} == {
        table: set(columns.split(',')) for table, columns in _RESEARCH_SCHEMA_COLUMNS.items()}
    representation_index = 1 if case.name == 'postgres' else 0
    assert {table: dict(columns) for table, columns in declarations.items()} == {
        table: {name: kinds[representation_index] for name, kinds in columns.items()}
        for table, columns in _RESEARCH_COLUMN_TYPES.items()}
    for table, columns in declarations.items():
        if case.name == 'postgres':
            await _sql(case, f'ALTER TABLE {table} RENAME TO t054_original_{table}')
        if incompatibility == 'views':
            select = ','.join(f'CAST(NULL AS {kind}) AS {name}' for name, kind in columns)
            await _sql(case, f'CREATE VIEW {table} AS SELECT {select} WHERE 1=0')
        else:
            # Existing committed representations remain exact except one same-name column.
            typed = ','.join(f'{name} {"REAL" if table == "research_assignments" and name == "version" else kind}' for name, kind in columns)
            await _sql(case, f'CREATE TABLE {table} ({typed})')
    state = _state(case)
    after = (await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(request)).to_payload()
    assert 'claim_gate' in after, 'Optional research incompatibility must preserve canonical/gating reads.'
    assert after['research'] == {'availability': 'SCHEMA_UNAVAILABLE'}
    assert after['claim_gate'] == before['claim_gate']
    assert after['counts'] == before['counts'] and after['high_water'] == before['high_water']
    assert _state(case) == state
