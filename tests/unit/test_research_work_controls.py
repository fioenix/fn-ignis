"""Bounded controls for parser variants and receipt-based activity updates."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import pytest
from ignis.domain.research_work import parse_research_work_command, transition_research_work
from ignis.domain.research_work import ResearchAuthority, ResearchAssignment, ResearchInputBindings, ResearchWorkItem

NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def envelope(operation, payload):
    return dict(operation=operation, payload=payload, idempotency_key='control-1', expected_epoch=1, expected_revision=0)


@pytest.mark.parametrize('operation,payload', [
    ('ASSIGN_RESEARCH', dict(host_task_ref='host/1', capability=None, authority=dict(actions=['ANALYZE'],
        sources=['youtube'], deadline=(NOW + timedelta(hours=1)).isoformat(), quota_ceiling=0))),
    ('ASSIGN_WORK', dict(assignment_id=str(UUID(int=1)), work_id=str(UUID(int=2)), question='Compare evidence',
        expertise='Analysis', assignee_ref=None, ownership_fence='fence', dependencies=[],
        inputs=dict(mission_id=str(UUID(int=3)), manifest_digest='a'*64, brief_digest=None,
            frame_digest=None, observation_ids=[], finding_revisions=[]))),
    ('END_RESEARCH', dict(assignment_id=str(UUID(int=1)), expected_version=1, disposition='CANCELLED', reason='Owner stopped assignment')),
])
def test_assignment_command_roundtrip_and_unknown_fields(operation, payload):
    result = parse_research_work_command(envelope(operation, payload))
    assert result.disposition == 'VALID'
    assert parse_research_work_command(result.command.to_payload()).command == result.command
    payload['secret'] = 'sentinel'
    refused = parse_research_work_command(envelope(operation, payload))
    assert refused.disposition == 'REFUSED'
    assert 'sentinel' not in str(refused.to_payload())


def test_record_activity_requires_current_receipt():
    authority = ResearchAuthority(actions=frozenset({'ANALYZE'}), sources=frozenset({'youtube'}),
        deadline=NOW + timedelta(hours=1), quota_ceiling=1)
    assignment = ResearchAssignment(assignment_id=UUID(int=1), mission_id=UUID(int=3), host_task_ref='host/1',
        authority=authority, capability='SEQUENTIAL', epoch=1, version=1, state='ACTIVE')
    inputs = ResearchInputBindings(mission_id=UUID(int=3), manifest_digest='a'*64, brief_digest=None,
        frame_digest=None, observation_ids=(), finding_revisions=())
    work = ResearchWorkItem(work_id=UUID(int=2), assignment_id=UUID(int=1), mission_id=UUID(int=3),
        run_id=None, question='Compare evidence', expertise='Analysis', assignee_ref='host/worker', inputs=inputs,
        dependencies=(), epoch=1, state='RUNNING', version=1, ownership_fence='fence')
    payload = dict(work_id=str(work.work_id), expected_version=1, ownership_fence='fence', execution_ref='host/execution',
        occurred_at=NOW.isoformat(), fresh_until=(NOW+timedelta(minutes=1)).isoformat())
    parsed = parse_research_work_command(envelope('RECORD_ACTIVITY', payload))
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command, now=NOW)
    assert result.disposition == 'APPLIED'
    assert result.work.state == 'RUNNING'
    assert result.work.version == 2
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command,
        now=NOW+timedelta(minutes=1))
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'EXECUTION_RECEIPT_NOT_CURRENT'
    assert result.work == work


def bound_records(state='RUNNING', assignment_state='ACTIVE'):
    authority = ResearchAuthority(actions=frozenset({'ANALYZE'}), sources=frozenset({'youtube'}),
        deadline=NOW + timedelta(hours=1), quota_ceiling=1)
    assignment = ResearchAssignment(assignment_id=UUID(int=1), mission_id=UUID(int=3), host_task_ref='host/1',
        authority=authority, capability='SEQUENTIAL', epoch=1, version=1, state=assignment_state)
    inputs = ResearchInputBindings(mission_id=UUID(int=3), manifest_digest='a'*64, brief_digest=None,
        frame_digest=None, observation_ids=(), finding_revisions=())
    work = ResearchWorkItem(work_id=UUID(int=2), assignment_id=UUID(int=1), mission_id=UUID(int=3),
        run_id=None, question='Compare evidence', expertise='Analysis', assignee_ref='host/worker', inputs=inputs,
        dependencies=(), epoch=1, state=state, version=1, ownership_fence='fence')
    return assignment, work


@pytest.mark.parametrize('container', ['assignment', 'assign_payload', 'work', 'work_payload'])
def test_nested_serializer_subclasses_are_refused(container):
    from dataclasses import replace
    from ignis.domain.research_work import AssignResearchPayload, AssignWorkPayload
    assignment, work = bound_records()
    class ExtraAuthority(ResearchAuthority):
        def to_payload(self):
            return {**super().to_payload(), 'unapproved': 'sentinel'}
    class ExtraInputs(ResearchInputBindings):
        def to_payload(self):
            return {**super().to_payload(), 'unapproved': 'sentinel'}
    authority = ExtraAuthority(**{name: getattr(assignment.authority, name)
                                for name in ResearchAuthority.__dataclass_fields__})
    inputs = ExtraInputs(**{name: getattr(work.inputs, name) for name in ResearchInputBindings.__dataclass_fields__})
    with pytest.raises(ValueError):
        if container == 'assignment':
            replace(assignment, authority=authority)
        elif container == 'assign_payload':
            AssignResearchPayload(host_task_ref='host/1', capability=None, authority=authority)
        elif container == 'work':
            replace(work, inputs=inputs)
        else:
            AssignWorkPayload(assignment_id=assignment.assignment_id, work_id=work.work_id, question=work.question,
                expertise=work.expertise, assignee_ref=None, inputs=inputs, dependencies=(), ownership_fence='fence')


@pytest.mark.parametrize('assignment_state', ['CANCELLED', 'EXPIRED', 'COMPLETED'])
def test_actual_stop_closes_bound_work_after_assignment_termination(assignment_state):
    assignment, work = bound_records('CANCEL_PENDING', assignment_state)
    parsed = parse_research_work_command(envelope('ACK_STOP', dict(work_id=str(work.work_id),
        expected_version=1, ownership_fence='fence', execution_ref='host/stopped', reason='Actual stop acknowledged')))
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command, now=NOW)
    assert result.disposition == 'APPLIED'
    assert result.work.state == 'CANCELLED'
    assert result.work.version == 2
    assert work.state == 'CANCEL_PENDING'
    assert assignment.state == assignment_state


@pytest.mark.parametrize('disposition', ['FAILED', 'INTERRUPTED', 'INSUFFICIENT_EVIDENCE'])
def test_closure_after_deadline_does_not_revive_authority(disposition):
    assignment, work = bound_records()
    parsed = parse_research_work_command(envelope('END_WORK', dict(work_id=str(work.work_id),
        expected_version=1, ownership_fence='fence', disposition=disposition, reason='Host execution ended')))
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command,
        now=NOW+timedelta(hours=1))
    assert result.disposition == 'APPLIED'
    assert result.work.state == disposition
    assert result.work.version == 2
    assert work.state == 'RUNNING'
    assert assignment.state == 'ACTIVE'


@pytest.mark.parametrize('field,value,reason', [('expected_epoch', 2, 'STALE_EPOCH'),
    ('expected_version', 0, 'STALE_VERSION'), ('ownership_fence', 'obsolete', 'STALE_FENCE'),
    ('work_id', str(UUID(int=8)), 'SCOPE_MISMATCH')])
def test_terminal_assignment_stop_keeps_exact_identity_guards(field, value, reason):
    assignment, work = bound_records('CANCEL_PENDING', 'CANCELLED')
    raw = envelope('ACK_STOP', dict(work_id=str(work.work_id), expected_version=1,
        ownership_fence='fence', execution_ref='host/stopped', reason='Actual stop acknowledged'))
    if field == 'expected_epoch':
        raw[field] = value
    else:
        raw['payload'][field] = value
    parsed = parse_research_work_command(raw)
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command, now=NOW)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == reason
    assert result.work == work


@pytest.mark.parametrize('operation', ['START_WORK', 'RESUME_WORK', 'RECORD_ACTIVITY'])
@pytest.mark.parametrize('boundary', ['terminal', 'expired', 'cancel'])
def test_new_execution_remains_fenced_after_closure_boundary(operation, boundary):
    assignment, work = bound_records('WAITING' if operation == 'RESUME_WORK' else 'RUNNING',
        'CANCELLED' if boundary == 'terminal' else ('CANCEL_PENDING' if boundary == 'cancel' else 'ACTIVE'))
    payload = dict(work_id=str(work.work_id), expected_version=1, ownership_fence='fence')
    if operation == 'RESUME_WORK':
        payload['reason'] = 'Resume requested'
    else:
        payload.update(execution_ref='host/execution', occurred_at=NOW.isoformat(),
            fresh_until=(NOW+timedelta(hours=2)).isoformat())
    parsed = parse_research_work_command(envelope(operation, payload))
    result = transition_research_work(work=work, assignment=assignment, command=parsed.command,
        now=NOW+timedelta(hours=1) if boundary == 'expired' else NOW)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == {'terminal': 'ASSIGNMENT_TERMINAL', 'expired': 'AUTHORITY_EXPIRED',
                                 'cancel': 'CANCELLATION_PENDING'}[boundary]
    assert result.work == work
