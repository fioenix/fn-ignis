"""Direct transaction contracts; no persistence or execution claims."""
import importlib
import inspect
import json
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta

import pytest

from tests.unit.test_research_findings import IDS, NOW, records


def api():
    try:
        return importlib.import_module('ignis.application.ports.research_work_port')
    except ModuleNotFoundError as exc:
        if exc.name != 'ignis.application.ports.research_work_port':
            raise
        pytest.fail('T045 port contract is absent', pytrace=False)


def command():
    p = api()
    return p.ResearchWorkCommitCommand(mission_id=IDS[0], operation='SUBMIT_HANDOFF',
        payload=records()[1], expected_revision=3, expected_epoch=1,
        idempotency_key='scope-1', host_authorized=True)


def test_exact_retry_identity_includes_expectations_and_submitted_content():
    c = command()
    assert c.payload == records()[1]
    assert c.fingerprint == replace(c).fingerprint
    for changes in ({'expected_revision': 4}, {'expected_epoch': 2},
                    {'idempotency_key': 'scope-2'}, {'host_authorized': False},
                    {'payload': replace(c.payload, result='Different')},
                    {'payload': replace(c.payload, recorded_at=NOW)}):
        assert replace(c, **changes).fingerprint != c.fingerprint
    with pytest.raises(FrozenInstanceError):
        c.expected_revision = 4


@pytest.mark.parametrize('changes', [{'operation': 'DISPATCH'}, {'payload': {}},
    {'operation': 'ASSIGN_WORK'}, {'expected_revision': True}, {'expected_epoch': 0},
    {'host_authorized': 1}, {'mission_id': 'mission'}])
def test_command_rejects_structural_substitution(changes):
    with pytest.raises(ValueError):
        replace(command(), **changes)


def test_unknown_acknowledgement_reason_is_representable_but_never_serialized():
    p = api()
    ack = p.ResearchHandoffAcknowledgement(handoff_id=IDS[6], consumer_ref='consumer-1',
        expected_version=2, disposition='REJECTED', reason_code='PRIVATE_SENTINEL', inputs=records()[0].inputs)
    assert ack.reason_code == 'PRIVATE_SENTINEL'
    assert ack.to_payload()['reason_code'] == 'INVALID_REASON_CODE'
    assert 'PRIVATE_SENTINEL' not in json.dumps(ack.to_payload())
    c = replace(command(), operation='ACK_HANDOFF', payload=ack)
    assert c.fingerprint != replace(c, payload=replace(ack, reason_code='OTHER_PRIVATE')).fingerprint
    assert 'PRIVATE_SENTINEL' not in json.dumps(c.to_payload())
    with pytest.raises(ValueError):
        replace(ack, inputs={})


def test_original_receipt_keeps_identity_time_and_events_without_payload():
    p = api()
    receipt = p.ResearchWorkCommitReceipt(disposition='APPLIED', reason_code=None,
        revision=4, work_version=3, assignment_version=None, receipt_id=IDS[8],
        event_ids=(IDS[1], IDS[2]), recorded_at=NOW)
    assert replace(receipt) == receipt
    assert receipt.to_payload()['recorded_at'] == NOW.isoformat()
    assert receipt.event_ids == (IDS[1], IDS[2])
    assert replace(receipt, recorded_at=NOW + timedelta(seconds=1)) != receipt
    with pytest.raises(ValueError):
        replace(receipt, reason_code='PRIVATE_SENTINEL')
    with pytest.raises(ValueError):
        replace(receipt, event_ids=[IDS[1]])


def snapshot():
    p = api()
    f, h = records()
    metadata = tuple(p.ResearchRecordedMetadata(record_kind=k, record_id=i,
        record_version=1, mission_revision=4, recorded_at=NOW,
        provenance='HARNESS_OBSERVED') for k, i in [('HANDOFF', h.handoff_id), ('FINDING', f.finding_id)])
    return p.ResearchWorkSnapshot(mission_id=IDS[0], revision=4, current_epoch=1,
        assignments=(), work_items=(), handoffs=(h,), findings=(f,), acknowledgements=(),
        events=(), observation_sources=h.observation_sources, current_finding_revisions=((f.finding_id, 1),),
        recorded_metadata=metadata)


def test_snapshot_retains_content_and_separate_observed_transaction_metadata():
    s = snapshot()
    assert s.handoffs == (records()[1],) and s.findings == (records()[0],)
    assert s.handoffs[0].recorded_at is None and s.findings[0].recorded_at is None
    assert all(m.recorded_at == NOW for m in s.recorded_metadata)
    assert s.observation_count == 3 and s.source_count == 1
    payload = s.to_payload()
    json.dumps(payload)
    payload['findings'][0]['limitations'].append('Changed')
    assert s.findings[0].limitations == ('Bounded sample',)


@pytest.mark.parametrize('changes', [{'events': ({},)}, {'findings': [{}]},
    {'observation_sources': ((IDS[1], IDS[7]), (IDS[1], IDS[8]))},
    {'current_finding_revisions': ((IDS[8], 1),)}, {'recorded_metadata': ({},)},
    {'recorded_metadata': ()}, {'current_epoch': True}])
def test_snapshot_rejects_untyped_or_incoherent_collections(changes):
    with pytest.raises(ValueError):
        replace(snapshot(), **changes)


def test_port_contains_no_execution_or_storage_dependencies():
    p = api()
    source = inspect.getsource(p)
    assert 'datetime.now' not in source
    for forbidden in ('ignis.infrastructure', 'subprocess', 'create_task', 'connector_port', 'import os'):
        assert forbidden not in source
    assert inspect.iscoroutinefunction(p.IResearchWorkPort.commit_research_work)
    assert inspect.iscoroutinefunction(p.IResearchWorkPort.load_research_work)


def test_handoff_ready_is_a_recorded_state_without_active_execution():
    from ignis.domain.research_work import ResearchWorkItem, project_work_activity
    inputs = records()[0].inputs
    work = ResearchWorkItem(work_id=IDS[5], assignment_id=IDS[8], mission_id=IDS[0],
        run_id=None, question='Question', expertise='Analysis', assignee_ref='worker',
        inputs=inputs, dependencies=(), epoch=1, state='HANDOFF_READY', version=2,
        ownership_fence='fence-1')
    assert project_work_activity(work=work, receipt=None, now=NOW).state == 'HANDOFF_READY'


def test_current_findings_select_exact_latest_revision_without_rewriting_history():
    s = snapshot()
    successor = replace(s.findings[0], revision=2, predecessor_revision=1)
    metadata = replace(s.recorded_metadata[1], record_version=2)
    revised = replace(s, findings=(*s.findings, successor),
        recorded_metadata=(*s.recorded_metadata, metadata),
        current_finding_revisions=((successor.finding_id, 2),))
    assert revised.current_finding_ids == (successor.finding_id,)
    assert revised.current_finding_revisions == ((successor.finding_id, 2),)
    assert revised.findings == (*s.findings, successor)
    with pytest.raises(ValueError):
        replace(revised, current_finding_revisions=((successor.finding_id, 1),))


def test_metadata_accepts_only_approved_observed_provenance():
    metadata = snapshot().recorded_metadata[0]
    assert replace(metadata, provenance='HARNESS_OBSERVED').to_payload()['provenance'] == 'HARNESS_OBSERVED'
    with pytest.raises(ValueError):
        replace(metadata, provenance='HARNESS_RECORDED')


def progress_event(event_id, ordinal):
    from ignis.domain.mission_relay import (
        MissionProgressEvent, MissionRelayCursor, MissionProgressKind, RelayProvenance)
    return MissionProgressEvent(event_id=event_id,
        cursor=MissionRelayCursor(mission_id=IDS[0], revision=4, ordinal=ordinal),
        kind=MissionProgressKind.HANDOFF_COMMITTED, provenance=RelayProvenance.HARNESS_OBSERVED,
        recorded_at=NOW, causation_key='command-1', work_id=IDS[5], handoff_id=IDS[6])


def test_snapshot_rejects_duplicate_cursor_independently_of_event_ids():
    s = snapshot()
    with pytest.raises(ValueError):
        replace(s, events=(progress_event(IDS[1], 1), progress_event(IDS[2], 1)))
    valid = replace(s, events=(progress_event(IDS[1], 1), progress_event(IDS[2], 2)))
    assert tuple(e.cursor.ordinal for e in valid.events) == (1, 2)


def test_snapshot_rejects_conflicting_overlapping_sources_without_unioning_history():
    s = snapshot()
    with pytest.raises(ValueError):
        replace(s, observation_sources=((IDS[1], IDS[8]), *s.observation_sources[1:]))
    conflicting = replace(s.handoffs[0], handoff_id=IDS[8], findings=(),
        observation_sources=((IDS[1], IDS[8]), *s.observation_sources[1:]))
    metadata = replace(s.recorded_metadata[0], record_id=IDS[8])
    with pytest.raises(ValueError):
        replace(s, observation_sources=(), handoffs=(*s.handoffs, conflicting),
            recorded_metadata=(*s.recorded_metadata, metadata))
    pruned = replace(s, observation_sources=(s.observation_sources[0],), current_finding_revisions=())
    assert pruned.handoffs == s.handoffs and pruned.findings == s.findings
    assert pruned.observation_count == 1 and pruned.current_finding_ids == ()


@pytest.mark.parametrize('kind,identity,version', [
    ('HANDOFF', IDS[8], 1), ('FINDING', IDS[8], 1),
    ('FINDING', IDS[4], 2), ('HANDOFF', IDS[6], 2),
    ('WORK', IDS[8], 1), ('ASSIGNMENT', IDS[8], 1)])
def test_snapshot_rejects_detached_persisted_metadata(kind, identity, version):
    s = snapshot()
    detached = replace(s.recorded_metadata[0], record_kind=kind,
        record_id=identity, record_version=version)
    with pytest.raises(ValueError):
        replace(s, recorded_metadata=(*s.recorded_metadata, detached))


def test_snapshot_permits_prior_known_work_and_assignment_versions_only():
    from ignis.domain.research_work import ResearchAssignment, ResearchAuthority, ResearchWorkItem
    s = snapshot()
    assignment = ResearchAssignment(assignment_id=IDS[8], mission_id=IDS[0], host_task_ref='host',
        epoch=1, authority=ResearchAuthority(actions=frozenset({'ANALYZE'}),
        sources=frozenset({'youtube'}), deadline=NOW + timedelta(days=1), quota_ceiling=0),
        capability='SEQUENTIAL', state='ACTIVE', version=2)
    work = ResearchWorkItem(work_id=IDS[5], assignment_id=IDS[8], mission_id=IDS[0],
        run_id=None, question='Question', expertise='Analysis', assignee_ref='worker',
        inputs=s.findings[0].inputs, dependencies=(), epoch=1, state='HANDOFF_READY',
        version=3, ownership_fence='fence-1')
    metadata = tuple(replace(s.recorded_metadata[0], record_kind=kind,
        record_id=identity, record_version=version) for kind, identity, version in
        [('ASSIGNMENT', IDS[8], 1), ('ASSIGNMENT', IDS[8], 2), ('WORK', IDS[5], 1), ('WORK', IDS[5], 3)])
    valid = replace(s, assignments=(assignment,), work_items=(work,),
        recorded_metadata=(*s.recorded_metadata, *metadata))
    assert valid.work_items == (work,) and valid.assignments == (assignment,)
    for kind, identity, version in [('WORK', IDS[5], 4), ('ASSIGNMENT', IDS[8], 3)]:
        future = replace(metadata[0], record_kind=kind, record_id=identity, record_version=version)
        with pytest.raises(ValueError):
            replace(valid, recorded_metadata=(*valid.recorded_metadata, future))
