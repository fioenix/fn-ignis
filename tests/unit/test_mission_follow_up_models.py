"""Follow-up contracts reject widened scope, ambiguous spend and foreign evidence."""
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timezone
import importlib
from uuid import uuid4

import pytest

from ignis.domain.research_work import ResearchInputBindings


@pytest.fixture
def domain():
    try:
        return importlib.import_module('ignis.domain.mission_follow_up')
    except ModuleNotFoundError:
        pytest.fail('T070 domain API is unavailable; not behavioral RED.')


def relationship(d, **changes):
    parent = uuid4()
    scope = d.FollowUpScope(queries=('bounded question', 'falsifier'), sources=frozenset({'youtube'}))
    work = d.FollowUpWork(
        work_id=uuid4(), parent_work_id=uuid4(), assignment_id=uuid4(), gap_id=uuid4(),
        inputs=ResearchInputBindings(mission_id=parent, manifest_digest='a' * 64,
                                    brief_digest='b' * 64, frame_digest=None,
                                    observation_ids=(), finding_revisions=()),
        research_epoch=1, assignment_version=1, work_version=1,
        brief_revision_id=uuid4(), approved_scope=scope, requested_scope=scope,
        authority_deadline=datetime(2030, 1, 1, tzinfo=timezone.utc))
    values = dict(follow_up_id=uuid4(), work=work, child_mission_id=uuid4(),
                  child_manifest_digest='c' * 64, child_brief_digest='b' * 64, reservation_id=uuid4(), idempotency_key='first')
    values.update(changes)
    return d.FollowUpRelationship(**values)


def reservation(d, relation=None, **changes):
    values = dict(relationship=relation or relationship(d), reserved_quota=4, reserved_cost=6,
                  state='RESERVED', measured_quota=None, measured_cost=None, measurement_receipt_id=None)
    values.update(changes)
    return d.FollowUpReservation(**values)


def result(d, relation=None, **changes):
    relation = relation or relationship(d)
    observation, source, finding = uuid4(), uuid4(), uuid4()
    inputs = ResearchInputBindings(mission_id=relation.child_mission_id,
                                  manifest_digest=relation.child_manifest_digest,
                                  brief_digest=relation.child_brief_digest, frame_digest='d' * 64,
                                  observation_ids=(observation,), finding_revisions=((finding, 1),))
    values = dict(relationship=relation, child_run_id=uuid4(), state='COMPLETED', inputs=inputs,
                  observation_sources=((observation, source),), outcome_ids=(uuid4(),), claim_ids=(uuid4(),))
    values.update(changes)
    return d.FollowUpResult(**values)


def test_execution_input_has_only_four_fields_and_no_authority(domain):
    request = domain.FollowUpExecutionRequest(mission_id=uuid4(), follow_up_work_id=uuid4(),
                                             expected_research_epoch=1, idempotency_key='retry')
    assert set(request.to_payload()) == {
        'mission_id', 'follow_up_work_id', 'expected_research_epoch', 'idempotency_key'}
    assert len(fields(request)) == 4
    for extra in ('queries', 'credential', 'host_authorized'):
        with pytest.raises(TypeError):
            domain.FollowUpExecutionRequest(**{f.name: getattr(request, f.name) for f in fields(request)}, **{extra: True})


@pytest.mark.parametrize('change', [{'expected_research_epoch': True}, {'mission_id': 'not-uuid'},
                                    {'idempotency_key': ''}, {'idempotency_key': 'x\ny'}])
def test_execution_input_rejects_ambiguous_or_unsafe_values(domain, change):
    values = dict(mission_id=uuid4(), follow_up_work_id=uuid4(), expected_research_epoch=1, idempotency_key='retry')
    with pytest.raises(ValueError):
        domain.FollowUpExecutionRequest(**(values | change))


@pytest.mark.parametrize('sources,queries', [(frozenset({'threads'}), ('bounded question',)),
                                            (frozenset({'youtube'}), ('unapproved question',))])
def test_admitted_relationship_cannot_widen_recorded_scope(domain, sources, queries):
    rel = relationship(domain)
    candidate = replace(rel.work, requested_scope=domain.FollowUpScope(sources=sources, queries=queries))
    with pytest.raises(ValueError, match='scope'):
        replace(rel, work=candidate)


def test_relation_is_immutable_and_child_never_parent(domain):
    rel = relationship(domain)
    with pytest.raises(FrozenInstanceError):
        rel.work.requested_scope = domain.FollowUpScope(queries=('changed',), sources=frozenset({'threads'}))
    with pytest.raises(ValueError, match='child'):
        replace(rel, child_mission_id=rel.work.inputs.mission_id)


@pytest.mark.parametrize('change', [{'queries': []}, {'queries': ('q', 'q')}, {'queries': ('',)},
                                    {'sources': frozenset()}, {'sources': frozenset({'bad source'})}])
def test_scope_rejects_mutable_duplicate_empty_or_invalid_identity(domain, change):
    with pytest.raises(ValueError):
        domain.FollowUpScope(**(dict(queries=('q',), sources=frozenset({'youtube'})) | change))


def test_unknown_and_measured_zero_do_not_release_reservation(domain):
    unknown = reservation(domain)
    zero = unknown.reconcile(measured_quota=0, measured_cost=0)
    assert unknown.measured_quota is None
    assert zero.measured_quota == 0
    assert zero.state == 'UNRESOLVED'
    assert zero.encumbered == (4, 6)
    settled = zero.reconcile(measured_quota=0, measured_cost=0, measurement_receipt_id=uuid4())
    assert settled.state == 'SETTLED'
    assert settled.encumbered == (0, 0)


def test_partial_receipt_cannot_release_unknown_cost(domain):
    current = reservation(domain).reconcile(measured_quota=2)
    with pytest.raises(ValueError, match='measurement'):
        current.reconcile(measured_quota=2, measurement_receipt_id=uuid4())
    assert current.encumbered == (4, 6)


def test_reconciliation_preserves_known_usage_and_rejects_decrease(domain):
    current = reservation(domain).reconcile(measured_quota=3, measured_cost=8)
    unchanged = current.reconcile()
    assert (unchanged.measured_quota, unchanged.measured_cost) == (3, 8)
    assert unchanged.encumbered == (4, 8)
    with pytest.raises(ValueError, match='decrease'):
        current.reconcile(measured_quota=2)
    settled = current.reconcile(measurement_receipt_id=uuid4())
    assert settled.encumbered == (3, 8)
    with pytest.raises(ValueError, match='settled'):
        settled.reconcile(measured_cost=9)


@pytest.mark.parametrize('change', [{'reserved_quota': True}, {'reserved_cost': -1},
                                    {'measured_cost': -1}, {'state': 'SETTLED'},
                                    {'measurement_receipt_id': uuid4()}])
def test_invalid_reservation_cannot_manufacture_budget_release(domain, change):
    with pytest.raises(ValueError):
        reservation(domain, **change)


def test_budget_counts_siblings_across_epochs_and_rejects_duplicates(domain):
    first = reservation(domain).reconcile(measured_quota=1, measured_cost=2, measurement_receipt_id=uuid4())
    rel = relationship(domain)
    second_work = replace(rel.work, inputs=first.relationship.work.inputs, research_epoch=2)
    second = reservation(domain, replace(rel, work=second_work))
    parent = first.relationship.work.inputs.mission_id
    assert domain.encumbered_budget(parent, (first, second)) == (5, 8)
    with pytest.raises(ValueError, match='[Dd]uplicate'):
        domain.encumbered_budget(parent, (first, first))
    with pytest.raises(ValueError, match='parent'):
        domain.encumbered_budget(uuid4(), (first,))


@pytest.mark.parametrize('change', ['mission', 'manifest', 'brief', 'observations', 'frame'])
def test_result_rejects_foreign_or_unframed_child_evidence(domain, change):
    current = result(domain)
    updates = {'mission': {'mission_id': uuid4()}, 'manifest': {'manifest_digest': 'e' * 64},
               'brief': {'brief_digest': 'f' * 64}, 'observations': {'observation_ids': (uuid4(),)},
               'frame': {'frame_digest': None}}
    with pytest.raises(ValueError):
        replace(current, inputs=replace(current.inputs, **updates[change]))


def test_parent_summary_is_exact_metadata_only_and_has_no_permission(domain):
    current = result(domain)
    assert current.related_payload() == {
        'relation': 'FOLLOW_UP_CHILD', 'mission_id': str(current.relationship.child_mission_id),
        'run_id': str(current.child_run_id), 'frame_digest': 'd' * 64,
        'finding_references': [{'finding_id': str(current.inputs.finding_revisions[0][0]), 'revision': 1}],
        'inspection_status': 'SELECT_CHILD_REQUIRED'}
    assert not {'permission', 'current_eligible', 'statement', 'queries'} & set(current.to_payload())


def test_uncertain_result_stays_visible_without_fabricated_run_or_frame(domain):
    rel = relationship(domain)
    current = domain.FollowUpResult(relationship=rel, child_run_id=None, state='UNRESOLVED',
                                   inputs=None, observation_sources=(), outcome_ids=(), claim_ids=())
    assert current.related_payload()['frame_digest'] is None
    assert current.related_payload()['run_id'] is None
    with pytest.raises(ValueError):
        replace(current, state='COMPLETED')
    with pytest.raises(ValueError):
        replace(current, claim_ids=(uuid4(),))


def test_canonical_same_question_child_has_its_own_brief_fingerprint(domain):
    from ignis.domain.entities import ResearchMission
    from ignis.domain.research_workspace import compute_frame_fingerprint
    from test_market_brief import _revision
    rel = relationship(domain)
    parent = ResearchMission(id=rel.work.inputs.mission_id, title='Question', keywords=['question'], surface='MARKET')
    child = ResearchMission(id=rel.child_mission_id, title='Question', keywords=['question'], surface='MARKET')
    brief = _revision()
    parent_digest = compute_frame_fingerprint(parent, brief)
    child_digest = compute_frame_fingerprint(child, brief)
    assert child_digest != parent_digest
    work = replace(rel.work, inputs=replace(rel.work.inputs, brief_digest=parent_digest))
    rel = replace(rel, work=work, child_brief_digest=child_digest)
    current = result(domain, rel)
    assert current.inputs.brief_digest == child_digest
    with pytest.raises(ValueError):
        replace(current, inputs=replace(current.inputs, brief_digest=parent_digest))
    foreign = ResearchMission(title='Question', keywords=['question'], surface='MARKET')
    with pytest.raises(ValueError):
        replace(current, inputs=replace(current.inputs, brief_digest=compute_frame_fingerprint(foreign, brief)))
