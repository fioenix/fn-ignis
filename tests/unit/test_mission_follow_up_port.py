"""Typed follow-up port boundaries preserve exact recorded authority and child links."""
from dataclasses import replace
import importlib
from uuid import uuid4

import pytest

from test_mission_follow_up_models import relationship, reservation, result

DOMAIN = 'ignis.domain.mission_follow_up'
PORT = 'ignis.application.ports.research_work_port'


def modules():
    d = importlib.import_module(DOMAIN)
    p = importlib.import_module(PORT)
    assert hasattr(p, 'FollowUpAdmissionCommand'), 'T070 additive port API unavailable.'
    return d, p


def command(d, p, rel=None, **changes):
    rel = rel or relationship(d)
    values = dict(request=d.FollowUpExecutionRequest(mission_id=rel.work.inputs.mission_id,
                   follow_up_work_id=rel.work.work_id, expected_research_epoch=rel.work.research_epoch,
                   idempotency_key=rel.idempotency_key),
                  selected_parent_id=rel.work.inputs.mission_id, expected_revision=2, host_authorized=True)
    return p.FollowUpAdmissionCommand(**(values | changes))


def test_private_authority_cannot_be_added_to_execution_request():
    d, p = modules()
    current = command(d, p)
    assert current.host_authorized is True
    assert 'host_authorized' not in current.request.to_payload()
    with pytest.raises(ValueError):
        replace(current, selected_parent_id=uuid4())
    with pytest.raises(ValueError):
        replace(current, host_authorized=1)
    with pytest.raises(ValueError):
        replace(current, request=current.request.to_payload())


def test_recording_retry_identity_includes_scope_without_exporting_queries():
    d, p = modules()
    rel = relationship(d)
    first = p.FollowUpWorkCommand(work=rel.work, expected_revision=1, idempotency_key='record', host_authorized=True)
    changed = replace(first, work=replace(rel.work, requested_scope=d.FollowUpScope(
        queries=('other question',), sources=frozenset({'youtube'}))))
    assert first.fingerprint != changed.fingerprint
    assert 'other question' not in str(changed.to_payload())
    assert 'bounded question' not in str(first.to_payload())


def test_result_settlement_rejects_another_child_even_same_parent():
    d, p = modules()
    rel = relationship(d)
    reserve = reservation(d, rel)
    current = p.FollowUpSettlementCommand(reservation=reserve, result=result(d, rel),
                    expected_revision=2, expected_reservation_version=1, idempotency_key='settle', host_authorized=True)
    foreign = replace(rel, child_mission_id=uuid4())
    with pytest.raises(ValueError, match='binding'):
        replace(current, result=result(d, foreign))
    unresolved = result(d, rel, child_run_id=None, state='UNRESOLVED', inputs=None,
                        observation_sources=(), outcome_ids=(), claim_ids=())
    settled = reserve.reconcile(measured_quota=0, measured_cost=0, measurement_receipt_id=uuid4())
    with pytest.raises(ValueError, match='terminal'):
        replace(current, reservation=settled, result=unresolved)


def test_refusal_receipt_cannot_carry_child_or_unsafe_reason():
    d, p = modules()
    from datetime import datetime, timezone
    values = dict(disposition='REFUSED', reason_code='STALE_EPOCH', revision=2,
                  receipt_id=uuid4(), recorded_at=datetime.now(timezone.utc), relationship=None, reservation=None)
    receipt = p.FollowUpCommitReceipt(**values)
    assert receipt.relationship is None and receipt.reservation is None
    for update in ({'relationship': relationship(d)}, {'reason_code': 'private exception'},
                   {'reason_code': None}, {'reservation': reservation(d)}):
        with pytest.raises(ValueError):
            replace(receipt, **update)


def test_snapshot_binds_work_reservation_and_result_to_exact_relation():
    d, p = modules()
    rel = relationship(d)
    snapshot = p.FollowUpSnapshot(mission_id=rel.work.inputs.mission_id, revision=3,
              work_items=(rel.work,), relationships=(rel,), reservations=(reservation(d, rel),),
              results=(result(d, rel),))
    assert len(snapshot.to_payload()['related_results']) == 1
    assert snapshot.to_payload()['related_results'][0]['inspection_status'] == 'SELECT_CHILD_REQUIRED'
    for update in ({'relationships': (rel, rel)}, {'work_items': ()}, {'reservations': ()},
                   {'results': (result(d, replace(rel, reservation_id=uuid4())),)},
                   {'mission_id': uuid4()}):
        with pytest.raises(ValueError):
            replace(snapshot, **update)


def test_additive_protocol_leaves_old_consumer_contract_intact():
    _, p = modules()
    assert p.IResearchWorkPort not in p.IResearchFollowUpPort.__mro__
    assert set(name for name in p.IResearchWorkPort.__dict__ if not name.startswith('_')) == {
        'commit_research_work', 'load_research_work'}
    from typing import get_type_hints
    assert get_type_hints(p.IResearchFollowUpPort.admit_mission_follow_up)['command'] is p.FollowUpAdmissionCommand
    assert get_type_hints(p.IResearchFollowUpPort.load_mission_follow_ups)['return'] is p.FollowUpSnapshot


def test_receipt_export_never_copies_private_query_scope():
    d, p = modules()
    from datetime import datetime, timezone
    rel = relationship(d)
    receipt = p.FollowUpCommitReceipt(disposition='APPLIED', reason_code=None, revision=3,
                    receipt_id=uuid4(), recorded_at=datetime.now(timezone.utc),
                    relationship=rel, reservation=reservation(d, rel))
    assert 'bounded question' not in str(receipt.to_payload())
    assert 'queries' not in receipt.to_payload()['reservation']
