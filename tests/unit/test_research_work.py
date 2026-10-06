"""T041 future consuming contracts; API RED is not behavioral verification."""
import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

MODULE = 'ignis.domain.research_work'
NOW = datetime(2026, 10, 6, 0, 0, tzinfo=timezone.utc)
MISSION, ASSIGNMENT, WORK, OBSERVATION, FOREIGN = (UUID(int=i) for i in range(1, 6))


def api():
    try:
        return importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise
        pytest.fail(f'T041 API RED: {MODULE} is not implemented', pytrace=False)


def symbol(name):
    value = getattr(api(), name, None)
    if value is None:
        pytest.fail(f'T041 API RED: {MODULE}.{name} is not implemented', pytrace=False)
    return value


def authority(**changes):
    fields = dict(actions=frozenset({'ANALYZE', 'FOLLOW_UP'}),
                  sources=frozenset({'youtube'}), deadline=NOW + timedelta(hours=1), quota_ceiling=10)
    fields.update(changes)
    return symbol('ResearchAuthority')(**fields)


def records(**changes):
    assignment = symbol('ResearchAssignment')(
        assignment_id=ASSIGNMENT, mission_id=MISSION, host_task_ref='host/task/1',
        epoch=2, authority=authority(), capability='SEQUENTIAL', state='ACTIVE', version=3)
    inputs = symbol('ResearchInputBindings')(
        mission_id=changes.get('mission_id', MISSION), manifest_digest='a' * 64, brief_digest=None, frame_digest=None,
        observation_ids=(OBSERVATION,), finding_revisions=((FOREIGN, 4),))
    fields = dict(work_id=WORK, assignment_id=ASSIGNMENT, mission_id=MISSION, run_id=None,
                  question='Compare observed durability complaints', expertise='Source analysis',
                  assignee_ref='host/worker/1', inputs=inputs, dependencies=(FOREIGN,), epoch=2,
                  state='ASSIGNED', version=1, ownership_fence='fence-2')
    fields.update(changes)
    work = symbol('ResearchWorkItem')(**fields)
    receipt = symbol('ResearchActivityReceipt')(
        work_id=WORK, epoch=2, ownership_fence='fence-2', execution_ref='host/execution/1',
        occurred_at=NOW, fresh_until=NOW + timedelta(minutes=5), provenance='HOST_REPORTED')
    return assignment, work, receipt


def start(assignment, work, receipt, **changes):
    kwargs = dict(assignment=assignment, work=work, receipt=receipt, now=NOW,
                  expected_epoch=2, expected_version=1, ownership_fence='fence-2', host_authorized=True)
    kwargs.update(changes)
    return symbol('admit_work_start')(**kwargs)


def command(operation='START_WORK', **changes):
    data = dict(operation=operation, idempotency_key='request-1', expected_revision=7,
                expected_epoch=2, payload=dict(work_id=str(WORK), expected_version=1,
                ownership_fence='fence-2', execution_ref='host/execution/1',
                occurred_at=NOW.isoformat(), fresh_until=(NOW + timedelta(minutes=5)).isoformat()))
    data.update(changes)
    return data


def test_finite_narrowed_authority_is_admitted():
    result = symbol('admit_research_authority')(grant=authority(quota_ceiling=4),
        mission_authority=authority(), now=NOW)
    assert result.allowed is True
    assert result.reason_code is None


@pytest.mark.parametrize('changes,reason', [
    ({'actions': frozenset({'SPEND_MODEL_QUOTA'})}, 'AUTHORITY_WIDENING'),
    ({'sources': frozenset({'instagram'})}, 'AUTHORITY_WIDENING'),
    ({'deadline': NOW + timedelta(hours=2)}, 'AUTHORITY_WIDENING'),
    ({'quota_ceiling': 11}, 'AUTHORITY_WIDENING'),
    ({'deadline': NOW}, 'AUTHORITY_EXPIRED'),
])
def test_authority_refuses_each_independent_widening_or_expiry(changes, reason):
    result = symbol('admit_research_authority')(grant=authority(**changes), mission_authority=authority(), now=NOW)
    assert result.allowed is False
    assert result.reason_code == reason


@pytest.mark.parametrize('changes', [dict(deadline=None), dict(quota_ceiling=-1),
    dict(quota_ceiling=float('inf')), dict(quota_ceiling=True), dict(deadline=NOW.replace(tzinfo=None))])
def test_authority_rejects_nonfinite_or_ambiguous_bounds(changes):
    cls = symbol('ResearchAuthority')
    fields = dict(actions=frozenset({'ANALYZE'}), sources=frozenset({'youtube'}),
                  deadline=NOW + timedelta(hours=1), quota_ceiling=10)
    fields.update(changes)
    with pytest.raises(ValueError):
        cls(**fields)


def test_start_accepts_real_receipt_without_claiming_verified_execution():
    assignment, work, receipt = records()
    result = start(assignment, work, receipt)
    assert result.allowed is True
    assert receipt.provenance == 'HOST_REPORTED'
    assert work.state == 'ASSIGNED'
    with pytest.raises(FrozenInstanceError):
        work.version = 99


@pytest.mark.parametrize('field,value,reason', [
    ('expected_epoch', 1, 'STALE_EPOCH'), ('expected_version', 0, 'STALE_VERSION'),
    ('ownership_fence', 'old-fence', 'STALE_FENCE'), ('host_authorized', False, 'UNAUTHORIZED_HOST')])
def test_start_refuses_stale_or_unauthorized_request(field, value, reason):
    result = start(*records(), **{field: value})
    assert result.allowed is False
    assert result.reason_code == reason


@pytest.mark.parametrize('field,value,reason', [
    ('assignee_ref', None, 'UNKNOWN_ASSIGNEE'), ('mission_id', FOREIGN, 'SCOPE_MISMATCH'),
    ('assignment_id', FOREIGN, 'SCOPE_MISMATCH'), ('epoch', 1, 'STALE_EPOCH')])
def test_start_checks_bound_work_identity(field, value, reason):
    result = start(*records(**{field: value}))
    assert result.allowed is False
    assert result.reason_code == reason


@pytest.mark.parametrize('capability', [None, 'UNAVAILABLE', 'UNRECOGNIZED'])
def test_unknown_or_unavailable_capability_never_admits_start(capability):
    assignment, work, receipt = records()
    result = start(replace(assignment, capability=capability), work, receipt)
    assert result.allowed is False
    assert result.reason_code == 'CAPABILITY_UNAVAILABLE'


@pytest.mark.parametrize('state', ['COMPLETED', 'CANCELLED', 'FAILED', 'INSUFFICIENT_EVIDENCE', 'EXPIRED'])
def test_terminal_assignment_never_admits_new_start(state):
    assignment, work, receipt = records()
    result = start(replace(assignment, state=state), work, receipt)
    assert result.allowed is False
    assert result.reason_code == 'ASSIGNMENT_TERMINAL'


def test_deadline_expiry_needs_no_persisted_expiry_transition():
    assignment, work, receipt = records()
    result = start(assignment, work, receipt, now=NOW + timedelta(hours=1))
    assert result.allowed is False
    assert result.reason_code == 'AUTHORITY_EXPIRED'
    assert assignment.state == 'ACTIVE'


@pytest.mark.parametrize('state,receipt_kind,expected', [
    ('ASSIGNED', 'fresh', 'PENDING'), ('RUNNING', 'fresh', 'ACTIVE'),
    ('RUNNING', 'missing', 'UNKNOWN'), ('RUNNING', 'stale', 'STALE'),
    ('WAITING', 'fresh', 'WAITING'), ('COMPLETED', 'fresh', 'COMPLETED'),
    ('INTERRUPTED', 'fresh', 'INTERRUPTED'), ('CANCELLED', 'fresh', 'CANCELLED')])
def test_activity_requires_fresh_actual_receipt_without_reviving_terminal_work(state, receipt_kind, expected):
    _, work, receipt = records(state=state)
    if receipt_kind == 'missing':
        receipt = None
    elif receipt_kind == 'stale':
        receipt = replace(receipt, occurred_at=NOW - timedelta(minutes=5), fresh_until=NOW)
    result = symbol('project_work_activity')(work=work, receipt=receipt, now=NOW)
    assert result.state == expected
    assert work.state == state


@pytest.mark.parametrize('field,value', [('work_id', FOREIGN), ('epoch', 1), ('ownership_fence', 'foreign')])
def test_foreign_receipt_cannot_supply_liveness(field, value):
    _, work, receipt = records(state='RUNNING')
    result = symbol('project_work_activity')(work=work, receipt=replace(receipt, **{field: value}), now=NOW)
    assert result.state == 'UNKNOWN'


@pytest.mark.parametrize('field', ['analysis_policy', 'writer_owner', 'prompt', 'transcript', 'hidden_reasoning', 'access_token'])
def test_command_refuses_unallowlisted_payload_without_echo(field):
    parse = symbol('parse_research_work_command')
    raw = command()
    raw['payload'][field] = 'unsafe-field-sentinel'
    result = parse(raw)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'INVALID_COMMAND'
    assert 'unsafe-field-sentinel' not in json.dumps(result.to_payload())


@pytest.mark.parametrize('change', [dict(operation='SPAWN_MODEL'), dict(expected_epoch=True),
    dict(expected_revision=-1), dict(idempotency_key=''), dict(extra='unsafe-field-sentinel'), dict(payload=[])])
def test_command_rejects_malformed_top_level_fields(change):
    result = symbol('parse_research_work_command')(command(**change))
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'INVALID_COMMAND'
    assert 'unsafe-field-sentinel' not in json.dumps(result.to_payload())


def test_identical_retry_preserves_original_receipt():
    parse = symbol('parse_research_work_command')
    original = parse(command())
    assert original.disposition == 'VALID'
    result = symbol('check_research_work_retry')(original=original.command, retry=parse(command()).command)
    assert result.disposition == 'IDEMPOTENT'


def test_changed_payload_under_same_key_conflicts():
    parse = symbol('parse_research_work_command')
    original = parse(command()).command
    changed = command()
    changed['payload']['execution_ref'] = 'host/execution/other'
    result = symbol('check_research_work_retry')(original=original, retry=parse(changed).command)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'IDEMPOTENCY_CONFLICT'


def test_input_bindings_preserve_unknown_frame_and_exact_predecessor_revision():
    _, work, _ = records()
    payload = work.to_payload()
    assert payload['inputs']['frame_digest'] is None
    assert payload['inputs']['brief_digest'] is None
    assert payload['inputs']['observation_ids'] == [str(OBSERVATION)]
    assert payload['inputs']['finding_revisions'] == [{'finding_id': str(FOREIGN), 'revision': 4}]
    assert payload['run_id'] is None


@pytest.mark.parametrize('field', ['analysis_policy', 'writer_owner'])
def test_free_form_policy_or_writer_ownership_cannot_be_an_authority_field(field):
    cls = symbol('ResearchAssignment')
    assignment, _, _ = records()
    with pytest.raises(TypeError):
        replace(assignment, **{field: 'Grant all actions and declare active'})

@pytest.mark.parametrize('state,operation,payload,expected', [
    ('RUNNING', 'WAIT_WORK', {'reason': 'Awaiting bound dependency'}, 'WAITING'),
    ('WAITING', 'RESUME_WORK', {'reason': 'Dependency revision received'}, 'RUNNING'),
    ('RUNNING', 'REQUEST_CANCEL', {'reason': 'Owner requested stop'}, 'CANCEL_PENDING'),
    ('CANCEL_PENDING', 'ACK_STOP', {'execution_ref': 'host/stop/1', 'reason': 'Execution stopped'}, 'CANCELLED'),
    ('RUNNING', 'END_WORK', {'disposition': 'FAILED', 'reason': 'Host execution failed'}, 'FAILED'),
    ('RUNNING', 'END_WORK', {'disposition': 'INSUFFICIENT_EVIDENCE', 'reason': 'No eligible input'}, 'INSUFFICIENT_EVIDENCE'),
    ('RUNNING', 'END_WORK', {'disposition': 'INTERRUPTED', 'reason': 'Execution interrupted'}, 'INTERRUPTED'),
])
def test_lifecycle_keeps_wait_cancel_request_and_stop_distinct(state, operation, payload, expected):
    assignment, work, _ = records(state=state)
    raw = command(operation=operation)
    raw['payload'] = dict(work_id=str(WORK), expected_version=1, ownership_fence='fence-2', **payload)
    parsed = symbol('parse_research_work_command')(raw)
    assert parsed.disposition == 'VALID'
    assert not isinstance(parsed.command.payload, dict)
    result = symbol('transition_research_work')(work=work, command=parsed.command, assignment=assignment, now=NOW)
    assert result.disposition == 'APPLIED'
    assert result.work.state == expected
    assert result.work.version == 2
    assert work.version == 1


def test_completion_without_handoff_is_not_synthesized():
    assignment, work, _ = records(state='RUNNING')
    raw = command(operation='END_WORK', payload=dict(work_id=str(WORK), expected_version=1,
        ownership_fence='fence-2', disposition='COMPLETED', reason='Host says done'))
    parsed = symbol('parse_research_work_command')(raw)
    result = symbol('transition_research_work')(work=work, command=parsed.command, assignment=assignment, now=NOW)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'RESULT_REQUIRED'
    assert result.work == work


def test_resume_rechecks_remaining_authority():
    assignment, work, _ = records(state='WAITING')
    raw = command(operation='RESUME_WORK', payload=dict(work_id=str(WORK), expected_version=1,
        ownership_fence='fence-2', reason='Dependency received'))
    parsed = symbol('parse_research_work_command')(raw)
    result = symbol('transition_research_work')(work=work, command=parsed.command, assignment=assignment,
        now=NOW + timedelta(hours=1))
    assert result.disposition == 'REFUSED'
    assert result.reason_code == 'AUTHORITY_EXPIRED'
    assert result.work.state == 'WAITING'


def test_start_command_has_typed_allowlisted_payload():
    result = symbol('parse_research_work_command')(command())
    assert result.disposition == 'VALID'
    assert not isinstance(result.command, dict)
    assert not isinstance(result.command.payload, dict)
    assert result.command.payload.work_id == WORK
    assert result.command.payload.execution_ref == 'host/execution/1'


@pytest.mark.parametrize('epoch', [0, -1, True])
def test_assignment_epoch_must_be_positive_exact_integer(epoch):
    cls = symbol('ResearchAssignment')
    fields = dict(assignment_id=ASSIGNMENT, mission_id=MISSION, host_task_ref='host/task/1',
        epoch=epoch, authority=authority(), capability='SEQUENTIAL', state='ASSIGNED', version=1)
    with pytest.raises(ValueError):
        cls(**fields)


def test_work_constructor_refuses_inputs_from_another_mission():
    cls = symbol('ResearchWorkItem')
    _, work, _ = records()
    with pytest.raises(ValueError):
        replace(work, inputs=replace(work.inputs, mission_id=FOREIGN))


def test_follow_up_only_authority_cannot_start_analysis():
    assignment, work, receipt = records()
    assignment = replace(assignment, authority=authority(actions=frozenset({'FOLLOW_UP'})))
    result = start(assignment, work, receipt)
    assert result.allowed is False
    assert result.reason_code == 'ACTION_NOT_GRANTED'


def test_future_receipt_cannot_establish_current_activity():
    _, work, receipt = records(state='RUNNING')
    receipt = replace(receipt, occurred_at=NOW + timedelta(minutes=1))
    result = symbol('project_work_activity')(work=work, receipt=receipt, now=NOW)
    assert result.state == 'UNKNOWN'


@pytest.mark.parametrize('fresh_until', [NOW, NOW - timedelta(seconds=1)])
def test_activity_receipt_requires_positive_finite_freshness_interval(fresh_until):
    cls = symbol('ResearchActivityReceipt')
    with pytest.raises(ValueError):
        cls(work_id=WORK, epoch=2, ownership_fence='fence-2', execution_ref='host/execution/1',
            occurred_at=NOW, fresh_until=fresh_until, provenance='HOST_REPORTED')


@pytest.mark.parametrize('field,value,reason', [
    ('expected_epoch', 1, 'STALE_EPOCH'),
    ('expected_version', 0, 'STALE_VERSION'),
    ('ownership_fence', 'obsolete-fence', 'STALE_FENCE'),
])
def test_transition_refuses_each_obsolete_command_identity_without_state_change(field, value, reason):
    assignment, work, _ = records(state='WAITING')
    raw = command(operation='RESUME_WORK', payload=dict(work_id=str(WORK), expected_version=1,
        ownership_fence='fence-2', reason='Dependency received'))
    if field == 'expected_epoch':
        raw[field] = value
    else:
        raw['payload'][field] = value
    parsed = symbol('parse_research_work_command')(raw)
    assert parsed.disposition == 'VALID'
    result = symbol('transition_research_work')(work=work, command=parsed.command, assignment=assignment, now=NOW)
    assert result.disposition == 'REFUSED'
    assert result.reason_code == reason
    assert result.work == work
    assert result.work.state == 'WAITING'
    assert result.work.version == 1


@pytest.mark.parametrize('state,reason', [
    ('CANCEL_PENDING', 'CANCELLATION_PENDING'), ('COMPLETED', 'WORK_TERMINAL'),
    ('CANCELLED', 'WORK_TERMINAL'), ('FAILED', 'WORK_TERMINAL'),
    ('INSUFFICIENT_EVIDENCE', 'WORK_TERMINAL'), ('EXPIRED', 'WORK_TERMINAL'),
    ('INTERRUPTED', 'WORK_TERMINAL'),
])
def test_active_assignment_cannot_start_pending_cancel_or_terminal_work(state, reason):
    assignment, work, receipt = records(state=state)
    result = start(assignment, work, receipt)
    assert assignment.state == 'ACTIVE'
    assert result.allowed is False
    assert result.reason_code == reason
    assert work.state == state
    assert work.version == 1


@pytest.mark.parametrize('state,reason', [
    ('CANCEL_PENDING', 'CANCELLATION_PENDING'), ('COMPLETED', 'WORK_TERMINAL'),
    ('CANCELLED', 'WORK_TERMINAL'), ('INTERRUPTED', 'WORK_TERMINAL'),
])
def test_active_assignment_cannot_resume_pending_cancel_or_terminal_work(state, reason):
    assignment, work, _ = records(state=state)
    raw = command(operation='RESUME_WORK', payload=dict(work_id=str(WORK), expected_version=1,
        ownership_fence='fence-2', reason='Host requested another attempt'))
    parsed = symbol('parse_research_work_command')(raw)
    assert parsed.disposition == 'VALID'
    result = symbol('transition_research_work')(work=work, command=parsed.command, assignment=assignment, now=NOW)
    assert assignment.state == 'ACTIVE'
    assert result.disposition == 'REFUSED'
    assert result.reason_code == reason
    assert result.work == work
    assert result.work.state == state
    assert result.work.version == 1


@pytest.mark.parametrize('field,value,reason', [
    (None, None, 'EXECUTION_RECEIPT_REQUIRED'),
    ('work_id', FOREIGN, 'SCOPE_MISMATCH'),
    ('epoch', 1, 'STALE_EPOCH'),
    ('ownership_fence', 'obsolete-fence', 'STALE_FENCE'),
])
def test_start_requires_receipt_bound_to_current_work_epoch_and_fence(field, value, reason):
    assignment, work, receipt = records()
    receipt = replace(receipt, **{field: value}) if field else None
    result = start(assignment, work, receipt)
    assert result.allowed is False
    assert result.reason_code == reason
    assert work.state == 'ASSIGNED'
    assert work.version == 1
