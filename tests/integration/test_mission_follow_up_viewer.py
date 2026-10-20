"""T069 child-view isolation on canonical stores and actual typed child admission.

Read observation follows offline owner fixture writes and canonical finding
receipts. No viewer receives execution authority or live credentials.
"""

import json
import importlib
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import uuid4

import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.domain.research_workspace import compute_frame_fingerprint
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from tests.integration.test_mission_relay_read_boundary import (
    NOW, _reader, _setup_traps, _state,
)
from tests.integration.test_research_work_persistence import _api, _commit, _sql
from tests.unit.test_mission_claims import _eligible_mission, _observation_candidate, _manifest
from tests.integration.test_mission_follow_up import relay_case

@dataclass
class Record:
    mission: object
    run: object
    frame: object
    evidence: object
    finding: object
    assignment: object
    work: object

    @property
    def pairs(self):
        return {(str(signal.observation_id), str(signal.source_id)) for signal in self.evidence.signals}

    @property
    def claims(self):
        return [claim.to_payload() for claim in self.evidence.claims if claim.status.value == 'PERMITTED']


def _request(record, *, page_size=200):
    return MissionRelayReadRequest(mission_id=record.mission.id, run_id=record.run.run_id, page_size=page_size)


async def _record(case, tmp_path, ordinal, *, permitted, admitted_child=None, seed=None):
    """Fixture mutation precedes read observation; preserve real qualification/claim paths."""
    repository = case.repository
    if admitted_child is None:
        from unittest.mock import patch
        with patch('tests.unit.test_mission_claims._manifest', return_value=replace(
                _manifest(), quota_budget={'queries': 20, 'youtube_search_calls': 20})):
            _, store, mission, _, _ = await _eligible_mission(tmp_path, repository=repository)
        original = await store.load_mission_evidence_snapshot(mission.id)
    else:
        from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
        from ignis.application.ports.research_workspace_port import RunJournal
        from pathlib import Path
        store = WorkspaceRepository(repository)
        mission = admitted_child
        canonical = await store.load_mission_evidence_snapshot(mission.id)
        original = replace(seed.evidence, mission=mission, brief=canonical.brief, manifest=canonical.manifest)
        run_id = uuid4()
        await store.record_run_journal(RunJournal(run_id=run_id, mission_id=mission.id,
            workspace_id=mission.workspace_id, journal_path=Path(f'/tmp/{run_id}.md'), sequence=1,
            status='COMPLETED', started_at=NOW, completed_at=NOW))
        await store.record_probe_outcomes(run_id, [replace(o, run_id=run_id, outcome_id=uuid4())
            for o in seed.evidence.outcomes])
        mission.status = 'COMPLETED'
        await repository.update_mission(mission)
    await _sql(case, 'DELETE FROM mission_evidence WHERE mission_id=?', (mission.id,))
    # One shared external object, distinct sightings; other sources are disjoint.
    fresh = [replace(signal, mission_id=mission.id, observation_id=None, source_id=None,
                     captured_at=signal.captured_at - timedelta(minutes=ordinal + 1),
                     source_url=(signal.source_url if signal.raw_title == 'Demand evidence'
                                 else f'https://example.invalid/{mission.id}/{index}'))
             for index, signal in enumerate(original.signals)]
    await repository.save_signals(fresh)
    signals = await repository.get_mission_signals(mission.id)
    old_by_id = {signal.observation_id: signal.raw_title for signal in original.signals}
    new_by_title = {signal.raw_title: signal for signal in signals}
    await store.save_evidence_qualifications(mission.id, [
        replace(qualification, mission_id=mission.id, brief_revision_id=original.brief.brief_revision_id,
                frame_fingerprint=compute_frame_fingerprint(mission, original.brief),
                observation_id=new_by_title[old_by_id[qualification.observation_id]].observation_id)
        for qualification in original.qualifications
    ])
    frame = await load_current_evidence_frame(repository, store, mission)
    if permitted:
        candidate = _observation_candidate(new_by_title['Demand evidence'], wording=f'Canonical mission {ordinal} claim.')
        receipt = await SubmitMissionClaimsUseCase(repository, store).execute(
            str(mission.id), frame.frame_digest, [candidate], created_by='t069-offline-fixture')
        assert receipt['permitted'] == 1
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    run = (await store.list_run_journals(mission.id))[0]
    domain, port, findings = _api(repository)
    demand = new_by_title['Demand evidence']
    inputs = domain.ResearchInputBindings(mission_id=mission.id, manifest_digest=frame.manifest_digest,
        brief_digest=compute_frame_fingerprint(mission, evidence.brief), frame_digest=frame.frame_digest,
        observation_ids=(demand.observation_id,), finding_revisions=())
    assignment = domain.ResearchAssignment(assignment_id=uuid4(), mission_id=mission.id,
        host_task_ref='t069-offline-owner', epoch=1, authority=domain.ResearchAuthority(
            actions=frozenset({'ANALYZE', 'FOLLOW_UP'}), sources=frozenset({'google', 'youtube'}),
            deadline=NOW + timedelta(days=300), quota_ceiling=2),
        capability='SEQUENTIAL', state='ASSIGNED', version=1)
    state = await repository.load_research_work(mission.id)
    admitted = await _commit(repository, port, mission, 'ASSIGN_RESEARCH', port.ResearchAssignmentAdmission(
        assignment=assignment, expected_manifest_digest=inputs.manifest_digest,
        expected_brief_revision_id=evidence.brief.brief_revision_id), revision=state.revision)
    assert admitted.disposition == 'APPLIED'
    work = domain.ResearchWorkItem(work_id=uuid4(), assignment_id=assignment.assignment_id,
        mission_id=mission.id, run_id=run.run_id, question='Describe the selected canonical result', expertise='Synthesis',
        assignee_ref='t069-offline-specialist', inputs=inputs, dependencies=(), epoch=1,
        state='ASSIGNED', version=1, ownership_fence='t069-fence')
    assigned = await _commit(repository, port, mission, 'ASSIGN_WORK', work, revision=admitted.revision)
    activity = domain.ResearchActivityReceipt(work_id=work.work_id, epoch=1, ownership_fence=work.ownership_fence,
        execution_ref='t069-offline-result', occurred_at=NOW, fresh_until=NOW + timedelta(days=300), provenance='HOST_REPORTED')
    started = await _commit(repository, port, mission, 'START_WORK', port.ResearchWorkStartAdmission(
        work_id=work.work_id, expected_version=1, ownership_fence=work.ownership_fence, receipt=activity), revision=assigned.revision)
    assert started.disposition == 'APPLIED'
    work = replace(work, state='RUNNING', version=started.work_version)
    finding = findings.ResearchFindingRevision(finding_id=uuid4(), revision=1, predecessor_revision=None,
        work_id=work.work_id, handoff_id=uuid4(), inputs=inputs, result_type='STRATEGIC_CANDIDATE',
        statement=f'UNLICENSED_MISSION_{ordinal}_CANDIDATE', limitations=('Bounded offline sample',), open_questions=(),
        supporting_observation_ids=(demand.observation_id,), contradicting_observation_ids=(),
        context_observation_ids=(),
        alternative_explanation='Sampling variation', claim_id=evidence.claims[0].claim_id if permitted else None)
    handoff = findings.ResearchHandoff(handoff_id=finding.handoff_id, work_id=work.work_id,
        expected_version=work.version, ownership_fence=work.ownership_fence, consumer_ref='t069-offline-consumer',
        inputs=inputs, observation_sources=((demand.observation_id, demand.source_id),),
        outcome_ids=(), claim_ids=(finding.claim_id,) if finding.claim_id else (),
        result=finding.statement, limitations=finding.limitations, open_questions=(), findings=(finding,), occurred_at=NOW)
    receipt = await _commit(repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=started.revision)
    assert receipt.disposition == 'APPLIED'
    return Record(mission, run, frame, evidence, finding, assignment, work)


async def _records(relay_case, tmp_path, *, parent_permitted=True, child_permitted=True):
    case, _, _ = relay_case
    parent = await _record(case, tmp_path, 0, permitted=parent_permitted)
    from tests.integration.follow_up_viewer_setup import admit_child
    admitted = await admit_child(case.repository, parent)
    child = await _record(case, tmp_path, 1, permitted=child_permitted, admitted_child=admitted, seed=parent)
    foreign = await _record(case, tmp_path, 2, permitted=True)
    assert len({record.frame.frame_digest for record in (parent, child, foreign)}) == 3
    observation_sets = [{pair[0] for pair in record.pairs} for record in (parent, child, foreign)]
    assert not observation_sets[0] & observation_sets[1] and not observation_sets[1] & observation_sets[2]
    assert {pair[1] for pair in parent.pairs} & {pair[1] for pair in child.pairs}
    return case, parent, child, foreign


async def _link(case, parent, child):
    """Validate the actual admitted link; no historical result mutation seam exists."""
    stored = await case.repository.load_mission_follow_ups(parent.mission.id)
    assert len(stored.relationships) == 1
    assert stored.relationships[0].child_mission_id == child.mission.id


def _related(payload):
    if 'related_results' not in payload:
        pytest.fail('T069 API unavailable: related_results projection; no related-frame assertion executed', pytrace=False)
    return payload['related_results']


def _assert_selected(payload, record, *, page_size=200):
    assert payload['mission_id'] == str(record.mission.id)
    assert payload['run_id'] == str(record.run.run_id)
    assert payload['high_water']['mission_id'] == str(record.mission.id)
    assert payload['frame_digest'] == record.frame.frame_digest
    assert payload['counts'] == {'observations': 6, 'sources': 6}
    pairs = {(row['observation_id'], row['source_id']) for row in payload['evidence']}
    assert len(payload['evidence']) == min(page_size, 6)
    assert pairs <= record.pairs
    if page_size >= 6:
        assert pairs == record.pairs
    assert all(row['mission_id'] == str(record.mission.id) for row in payload['evidence'])
    gate = payload['claim_gate']
    expected = record.claims
    assert gate['render_status'] == ('PERMITTED' if expected else 'WITHHELD')
    assert [row['claim_id'] for row in gate['claims']] == [row['claim_id'] for row in expected]
    for actual, claim in zip(gate['claims'], expected, strict=True):
        for key in ('mission_id', 'frame_digest', 'brief_revision_id', 'wording', 'evidence_bindings'):
            assert actual[key] == claim[key]


def _assert_finding(payload, record, *, eligible=True):
    rows = payload['research']['findings']
    assert len(rows) == 1
    finding = rows[0]
    assert finding['finding_id'] == str(record.finding.finding_id)
    for key in ('work_id', 'handoff_id', 'claim_id'):
        expected = getattr(record.finding, key)
        assert finding[key] == (str(expected) if expected is not None else None)
    assert finding['current_eligible'] is eligible
    assert finding['inputs']['mission_id'] == str(record.mission.id)
    assert finding['inputs']['frame_digest'] == record.frame.frame_digest
    assert finding['inputs']['manifest_digest'] == record.finding.inputs.manifest_digest
    assert finding['inputs']['brief_digest'] == record.finding.inputs.brief_digest
    assert finding['inputs']['observation_ids'] == [str(identity) for identity in record.finding.inputs.observation_ids]
    permission = bool(record.claims) and eligible
    assert finding['text_withheld'] is not permission
    assert finding['statement'] == (record.claims[0]['wording'] if permission else None)
    assert finding['narrative_origin'] == ('CURRENT_CLAIM_LEDGER' if permission else 'WITHHELD')
    assert record.finding.statement not in json.dumps(payload)


def _assert_summary(row, parent, child):
    assert set(row) == {'relation', 'mission_id', 'run_id', 'frame_digest',
                        'finding_references', 'inspection_status'}
    assert row['relation'] == 'FOLLOW_UP_CHILD'
    assert row['mission_id'] == str(child.mission.id) != str(parent.mission.id)
    assert row['run_id'] == str(child.run.run_id)
    assert row['frame_digest'] == child.frame.frame_digest
    assert row['finding_references'] == [{'finding_id': str(child.finding.finding_id), 'revision': 1}]
    assert row['inspection_status'] == 'SELECT_CHILD_REQUIRED'


def _readonly(monkeypatch, case):
    counters = {'execute': 0, 'probe': 0, 'auth': 0}

    def trap(key):
        def forbidden(*args, **kwargs):
            counters[key] += 1
            raise AssertionError(f'Read-only viewing invoked {key}')
        return forbidden

    _setup_traps(monkeypatch, case.repository)
    monkeypatch.setattr(ExecuteMissionUseCase, 'execute', trap('execute'))
    monkeypatch.setattr(ConnectorPluginRegistry, 'search_with_outcomes', trap('probe'))
    for name in ('get_platform_credentials', 'list_platform_credentials'):
        if hasattr(type(case.repository), name):
            monkeypatch.setattr(type(case.repository), name, trap('auth'))
    # Once T074 exists, viewer must still never call its admission/execution path.
    name = 'ignis.application.use_cases.execute_mission_follow_up'
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        module = None
    if module is not None and hasattr(module, 'ExecuteMissionFollowUpUseCase'):
        monkeypatch.setattr(module.ExecuteMissionFollowUpUseCase, 'execute', trap('execute'))
    return counters


@pytest.mark.asyncio
async def test_canonical_fixture_has_separate_frames_and_real_permission(relay_case, tmp_path):
    case, parent, child, foreign = await _records(relay_case, tmp_path)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    for record in (parent, child, foreign):
        payload = (await use_case.execute(_request(record))).to_payload()
        _assert_selected(payload, record)
        _assert_finding(payload, record)


@pytest.mark.asyncio
async def test_parent_permission_cannot_authorize_unpermitted_child(relay_case, tmp_path):
    case, parent, child, _ = await _records(relay_case, tmp_path, child_permitted=False)
    await _link(case, parent, child)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    parent_payload = (await use_case.execute(_request(parent))).to_payload()
    child_payload = (await use_case.execute(_request(child))).to_payload()
    _assert_selected(parent_payload, parent)
    _assert_selected(child_payload, child)
    _assert_finding(child_payload, child)
    assert len(_related(parent_payload)) == 1
    _assert_summary(_related(parent_payload)[0], parent, child)
    assert parent.claims[0]['claim_id'] not in {row['claim_id'] for row in child_payload['claim_gate']['claims']}


@pytest.mark.asyncio
async def test_child_permission_cannot_authorize_unpermitted_parent(relay_case, tmp_path):
    case, parent, child, _ = await _records(relay_case, tmp_path, parent_permitted=False)
    await _link(case, parent, child)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    parent_payload = (await use_case.execute(_request(parent))).to_payload()
    child_payload = (await use_case.execute(_request(child))).to_payload()
    _assert_selected(parent_payload, parent)
    _assert_selected(child_payload, child)
    _assert_finding(parent_payload, parent)
    assert len(_related(parent_payload)) == 1
    _assert_summary(_related(parent_payload)[0], parent, child)


@pytest.mark.asyncio
@pytest.mark.parametrize('selected,target', (('parent', 'child'), ('child', 'parent'), ('child', 'foreign')))
async def test_related_link_does_not_expose_foreign_observation(relay_case, tmp_path, selected, target):
    case, parent, child, foreign = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    records = {'parent': parent, 'child': child, 'foreign': foreign}
    before = _state(case)
    # These sightings share a source ID: source equality must not grant membership.
    target_signal = next(signal for signal in records[target].evidence.signals if signal.raw_title == 'Demand evidence')
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    result = (await use_case.execute(_request(records[selected]))).to_payload()
    assert result['status'] == 'OK'
    assert str(target_signal.observation_id) not in {row['observation_id'] for row in result['evidence']}
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('page_size', (1, 200))
async def test_selected_child_and_labeled_relation_never_create_composite_frame(relay_case, tmp_path, page_size):
    case, parent, child, _ = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    parent_payload = (await use_case.execute(_request(parent, page_size=page_size))).to_payload()
    child_payload = (await use_case.execute(_request(child, page_size=page_size))).to_payload()
    _assert_selected(parent_payload, parent, page_size=page_size)
    _assert_selected(child_payload, child, page_size=page_size)
    _assert_finding(child_payload, child)
    related = _related(parent_payload)
    assert len(related) == 1
    row = related[0]
    _assert_summary(row, parent, child)
    assert parent.finding.statement not in json.dumps(child_payload)
    assert child.finding.statement not in json.dumps(parent_payload)


@pytest.mark.asyncio
async def test_changed_child_frame_withholds_child_permission_without_changing_parent(relay_case, tmp_path):
    case, parent, child, _ = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    parent_before = (await use_case.execute(_request(parent))).to_payload()
    removed = next(signal for signal in child.evidence.signals if signal.raw_title == 'Demand evidence')
    await _sql(case, 'DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?',
               (child.mission.id, removed.observation_id))
    after = (await use_case.execute(_request(child))).to_payload()
    assert after['frame_digest'] != child.frame.frame_digest
    assert after['counts']['observations'] == 5
    assert after['claim_gate']['render_status'] == 'WITHHELD' and after['claim_gate']['claims'] == []
    _assert_finding(after, child, eligible=False)
    parent_after = (await use_case.execute(_request(parent))).to_payload()
    for key in ('frame_digest', 'counts', 'evidence', 'claim_gate'):
        assert parent_after[key] == parent_before[key]
    assert _related(parent_after)[0]['frame_digest'] != after['frame_digest']


@pytest.mark.asyncio
async def test_readonly_child_view_cannot_execute_followup_or_mutate_authority(relay_case, tmp_path, monkeypatch):
    case, parent, child, foreign = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    before = _state(case)
    counters = _readonly(monkeypatch, case)
    use_case = GetMissionRelaySnapshotUseCase(_reader(case.repository))
    parent_payload = (await use_case.execute(_request(parent))).to_payload()
    child_payload = (await use_case.execute(_request(child))).to_payload()
    _assert_selected(parent_payload, parent)
    _assert_selected(child_payload, child)
    assert _related(parent_payload)
    for selected, target in ((parent, child), (child, foreign)):
        visible = (await use_case.execute(_request(selected))).to_payload()
        assert str(target.evidence.signals[0].observation_id) not in {row['observation_id'] for row in visible['evidence']}
    assert counters == {'execute': 0, 'probe': 0, 'auth': 0}
    assert _state(case) == before
