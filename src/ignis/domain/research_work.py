"""Pure immutable host work contracts; persistence and privacy belong downstream."""

import re
from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID


TERMINAL = frozenset({'COMPLETED', 'CANCELLED', 'FAILED', 'INSUFFICIENT_EVIDENCE', 'EXPIRED', 'INTERRUPTED'})
WORK_STATES = TERMINAL | {'ASSIGNED', 'RUNNING', 'WAITING', 'CANCEL_PENDING'}
ASSIGNMENT_STATES = TERMINAL | {'ASSIGNED', 'ACTIVE', 'CANCEL_PENDING'}
ACTIONS = frozenset({'ANALYZE', 'FOLLOW_UP'})


def _literal(value, values):
    return type(value) is str and value in values


def _integer(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Invalid integer bound.')


def _text(value, optional=False, maximum=4096):
    if optional and value is None:
        return
    if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError('Invalid bounded text.')


def _uuid(value, optional=False):
    if optional and value is None:
        return
    if type(value) is not UUID:
        raise ValueError('Invalid identity.')


def _time(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('Invalid aware time.')
    try:
        value.timestamp()
    except (ValueError, OverflowError, OSError):
        raise ValueError('Invalid finite time.') from None


def _ids(values):
    if type(values) is not tuple or len(values) > 1000 or len(set(values)) != len(values):
        raise ValueError('Invalid identity collection.')
    for value in values:
        _uuid(value)


def _digest(value, optional=False):
    if optional and value is None:
        return
    if type(value) is not str or re.fullmatch(r'[0-9a-f]{64}', value) is None:
        raise ValueError('Invalid digest.')


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchAuthority:
    actions: frozenset[str]
    sources: frozenset[str]
    deadline: datetime
    quota_ceiling: int

    def __post_init__(self):
        for values in (self.actions, self.sources):
            if type(values) is not frozenset or not values or len(values) > 100:
                raise ValueError('Invalid finite authority set.')
            for value in values:
                _text(value, maximum=128)
                if re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', value) is None:
                    raise ValueError('Invalid authority identifier.')
        _time(self.deadline)
        _integer(self.quota_ceiling)

    def to_payload(self):
        return {'actions': sorted(self.actions), 'sources': sorted(self.sources),
                'deadline': self.deadline.isoformat(), 'quota_ceiling': self.quota_ceiling}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchInputBindings:
    mission_id: UUID
    manifest_digest: str
    brief_digest: str | None
    frame_digest: str | None
    observation_ids: tuple[UUID, ...]
    finding_revisions: tuple[tuple[UUID, int], ...]

    def __post_init__(self):
        _uuid(self.mission_id)
        _digest(self.manifest_digest)
        _digest(self.brief_digest, True)
        _digest(self.frame_digest, True)
        _ids(self.observation_ids)
        if type(self.finding_revisions) is not tuple or len(self.finding_revisions) > 1000:
            raise ValueError('Invalid finding bindings.')
        identities = set()
        for row in self.finding_revisions:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError('Invalid finding binding.')
            _uuid(row[0])
            _integer(row[1], 1)
            if row[0] in identities:
                raise ValueError('Duplicate finding binding.')
            identities.add(row[0])

    def to_payload(self):
        return {'mission_id': str(self.mission_id), 'manifest_digest': self.manifest_digest,
                'brief_digest': self.brief_digest, 'frame_digest': self.frame_digest,
                'observation_ids': [str(v) for v in self.observation_ids],
                'finding_revisions': [{'finding_id': str(i), 'revision': r} for i, r in self.finding_revisions]}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchAssignment:
    assignment_id: UUID
    mission_id: UUID
    host_task_ref: str
    epoch: int
    authority: ResearchAuthority
    capability: str | None
    state: str
    version: int

    def __post_init__(self):
        _uuid(self.assignment_id)
        _uuid(self.mission_id)
        _text(self.host_task_ref, maximum=512)
        _integer(self.epoch, 1)
        _integer(self.version, 1)
        _text(self.capability, True, 128)
        if type(self.authority) is not ResearchAuthority or not _literal(self.state, ASSIGNMENT_STATES):
            raise ValueError('Invalid assignment contract.')

    def to_payload(self):
        return {'assignment_id': str(self.assignment_id), 'mission_id': str(self.mission_id),
                'host_task_ref': self.host_task_ref, 'epoch': self.epoch, 'authority': self.authority.to_payload(),
                'capability': self.capability, 'state': self.state, 'version': self.version}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkItem:
    work_id: UUID
    assignment_id: UUID
    mission_id: UUID
    run_id: UUID | None
    question: str
    expertise: str
    assignee_ref: str | None
    inputs: ResearchInputBindings
    dependencies: tuple[UUID, ...]
    epoch: int
    state: str
    version: int
    ownership_fence: str

    def __post_init__(self):
        for value in (self.work_id, self.assignment_id, self.mission_id):
            _uuid(value)
        _uuid(self.run_id, True)
        _text(self.question)
        _text(self.expertise)
        _text(self.assignee_ref, True, 512)
        _text(self.ownership_fence, maximum=256)
        _ids(self.dependencies)
        _integer(self.epoch, 1)
        _integer(self.version, 1)
        if not _literal(self.state, WORK_STATES) or type(self.inputs) is not ResearchInputBindings:
            raise ValueError('Invalid work contract.')
        if self.inputs.mission_id != self.mission_id or self.work_id in self.dependencies:
            raise ValueError('Invalid work input scope.')

    def to_payload(self):
        return {'work_id': str(self.work_id), 'assignment_id': str(self.assignment_id),
                'mission_id': str(self.mission_id), 'run_id': str(self.run_id) if self.run_id else None,
                'question': self.question, 'expertise': self.expertise, 'assignee_ref': self.assignee_ref,
                'inputs': self.inputs.to_payload(), 'dependencies': [str(v) for v in self.dependencies],
                'epoch': self.epoch, 'state': self.state, 'version': self.version, 'ownership_fence': self.ownership_fence}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchActivityReceipt:
    work_id: UUID
    epoch: int
    ownership_fence: str
    execution_ref: str
    occurred_at: datetime
    fresh_until: datetime
    provenance: str

    def __post_init__(self):
        _uuid(self.work_id)
        _integer(self.epoch, 1)
        _text(self.ownership_fence, maximum=256)
        _text(self.execution_ref, maximum=512)
        _time(self.occurred_at)
        _time(self.fresh_until)
        if self.fresh_until <= self.occurred_at or not _literal(self.provenance, {'HOST_REPORTED'}):
            raise ValueError('Invalid host activity receipt.')

    def to_payload(self):
        return {'work_id': str(self.work_id), 'epoch': self.epoch, 'ownership_fence': self.ownership_fence,
                'execution_ref': self.execution_ref, 'occurred_at': self.occurred_at.isoformat(),
                'fresh_until': self.fresh_until.isoformat(), 'provenance': self.provenance}


@dataclass(frozen=True, slots=True)
class ResearchAdmission:
    allowed: bool
    reason_code: str | None = None


def admit_research_authority(*, grant, mission_authority, now):
    _time(now)
    if grant.deadline <= now or mission_authority.deadline <= now:
        return ResearchAdmission(False, 'AUTHORITY_EXPIRED')
    if (not grant.actions <= ACTIONS or not grant.actions <= mission_authority.actions
            or not grant.sources <= mission_authority.sources or grant.deadline > mission_authority.deadline
            or grant.quota_ceiling > mission_authority.quota_ceiling):
        return ResearchAdmission(False, 'AUTHORITY_WIDENING')
    return ResearchAdmission(True)


def _identity_reason(assignment, work, now, expected_epoch, expected_version, ownership_fence):
    _time(now)
    _integer(expected_epoch, 1)
    _integer(expected_version)
    _text(ownership_fence, maximum=256)
    if assignment.mission_id != work.mission_id or assignment.assignment_id != work.assignment_id:
        return 'SCOPE_MISMATCH'
    if expected_epoch != assignment.epoch or work.epoch != assignment.epoch:
        return 'STALE_EPOCH'
    if expected_version != work.version:
        return 'STALE_VERSION'
    if ownership_fence != work.ownership_fence:
        return 'STALE_FENCE'
    return None


def _admission_reason(assignment, work, now):
    if assignment.state in TERMINAL:
        return 'ASSIGNMENT_TERMINAL'
    if assignment.state == 'CANCEL_PENDING' or work.state == 'CANCEL_PENDING':
        return 'CANCELLATION_PENDING'
    if work.state in TERMINAL:
        return 'WORK_TERMINAL'
    if assignment.authority.deadline <= now:
        return 'AUTHORITY_EXPIRED'
    if not assignment.authority.actions <= ACTIONS:
        return 'AUTHORITY_WIDENING'
    if 'ANALYZE' not in assignment.authority.actions:
        return 'ACTION_NOT_GRANTED'
    if work.assignee_ref is None:
        return 'UNKNOWN_ASSIGNEE'
    if assignment.capability not in ('SEQUENTIAL', 'CONCURRENT'):
        return 'CAPABILITY_UNAVAILABLE'
    return None


def _work_reason(assignment, work, now, expected_epoch, expected_version, ownership_fence):
    return (_identity_reason(assignment, work, now, expected_epoch, expected_version, ownership_fence)
            or _admission_reason(assignment, work, now))


def admit_work_start(*, assignment, work, receipt, now, expected_epoch, expected_version, ownership_fence, host_authorized):
    if host_authorized is not True:
        return ResearchAdmission(False, 'UNAUTHORIZED_HOST')
    reason = _work_reason(assignment, work, now, expected_epoch, expected_version, ownership_fence)
    if reason:
        return ResearchAdmission(False, reason)
    if receipt is None:
        return ResearchAdmission(False, 'EXECUTION_RECEIPT_REQUIRED')
    if receipt.work_id != work.work_id:
        return ResearchAdmission(False, 'SCOPE_MISMATCH')
    if receipt.epoch != work.epoch:
        return ResearchAdmission(False, 'STALE_EPOCH')
    if receipt.ownership_fence != work.ownership_fence:
        return ResearchAdmission(False, 'STALE_FENCE')
    if not receipt.occurred_at <= now < receipt.fresh_until:
        return ResearchAdmission(False, 'EXECUTION_RECEIPT_NOT_CURRENT')
    if work.state != 'ASSIGNED':
        return ResearchAdmission(False, 'INVALID_TRANSITION')
    return ResearchAdmission(True)


@dataclass(frozen=True, slots=True)
class ResearchActivity:
    state: str

    def to_payload(self):
        return {'state': self.state}


def project_work_activity(*, work, receipt, now):
    _time(now)
    if work.state != 'RUNNING':
        return ResearchActivity('PENDING' if work.state == 'ASSIGNED' else work.state)
    if (receipt is None or receipt.work_id != work.work_id or receipt.epoch != work.epoch
            or receipt.ownership_fence != work.ownership_fence or receipt.occurred_at > now):
        return ResearchActivity('UNKNOWN')
    return ResearchActivity('ACTIVE' if now < receipt.fresh_until else 'STALE')


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkCommandPayload:
    work_id: UUID
    expected_version: int
    ownership_fence: str

    def __post_init__(self):
        _uuid(self.work_id)
        _integer(self.expected_version)
        _text(self.ownership_fence, maximum=256)

    def to_payload(self):
        return {'work_id': str(self.work_id), 'expected_version': self.expected_version,
                'ownership_fence': self.ownership_fence}


@dataclass(frozen=True, slots=True, kw_only=True)
class StartWorkPayload(WorkCommandPayload):
    execution_ref: str
    occurred_at: datetime
    fresh_until: datetime

    def __post_init__(self):
        WorkCommandPayload.__post_init__(self)
        ResearchActivityReceipt(work_id=self.work_id, epoch=1, ownership_fence=self.ownership_fence,
            execution_ref=self.execution_ref, occurred_at=self.occurred_at, fresh_until=self.fresh_until,
            provenance='HOST_REPORTED')

    def to_payload(self):
        return {**WorkCommandPayload.to_payload(self), 'execution_ref': self.execution_ref,
                'occurred_at': self.occurred_at.isoformat(), 'fresh_until': self.fresh_until.isoformat()}


@dataclass(frozen=True, slots=True, kw_only=True)
class ReasonWorkPayload(WorkCommandPayload):
    reason: str

    def __post_init__(self):
        WorkCommandPayload.__post_init__(self)
        _text(self.reason)

    def to_payload(self):
        return {**WorkCommandPayload.to_payload(self), 'reason': self.reason}


@dataclass(frozen=True, slots=True, kw_only=True)
class StopWorkPayload(ReasonWorkPayload):
    execution_ref: str

    def __post_init__(self):
        ReasonWorkPayload.__post_init__(self)
        _text(self.execution_ref, maximum=512)

    def to_payload(self):
        return {**ReasonWorkPayload.to_payload(self), 'execution_ref': self.execution_ref}


@dataclass(frozen=True, slots=True, kw_only=True)
class EndWorkPayload(ReasonWorkPayload):
    disposition: str

    def __post_init__(self):
        ReasonWorkPayload.__post_init__(self)
        if not _literal(self.disposition, TERMINAL - {'EXPIRED'}):
            raise ValueError('Invalid terminal disposition.')

    def to_payload(self):
        return {**ReasonWorkPayload.to_payload(self), 'disposition': self.disposition}


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignResearchPayload:
    host_task_ref: str
    authority: ResearchAuthority
    capability: str | None

    def __post_init__(self):
        _text(self.host_task_ref, maximum=512)
        _text(self.capability, True, 128)
        if type(self.authority) is not ResearchAuthority:
            raise ValueError('Invalid authority contract.')

    def to_payload(self):
        return {'host_task_ref': self.host_task_ref, 'authority': self.authority.to_payload(),
                'capability': self.capability}


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignWorkPayload:
    assignment_id: UUID
    work_id: UUID
    question: str
    expertise: str
    assignee_ref: str | None
    inputs: ResearchInputBindings
    dependencies: tuple[UUID, ...]
    ownership_fence: str

    def __post_init__(self):
        _uuid(self.assignment_id)
        _uuid(self.work_id)
        _text(self.question)
        _text(self.expertise)
        _text(self.assignee_ref, True, 512)
        _text(self.ownership_fence, maximum=256)
        _ids(self.dependencies)
        if type(self.inputs) is not ResearchInputBindings or self.work_id in self.dependencies:
            raise ValueError('Invalid assigned inputs.')

    def to_payload(self):
        return {'assignment_id': str(self.assignment_id), 'work_id': str(self.work_id),
                'question': self.question, 'expertise': self.expertise, 'assignee_ref': self.assignee_ref,
                'inputs': self.inputs.to_payload(), 'dependencies': [str(v) for v in self.dependencies],
                'ownership_fence': self.ownership_fence}


@dataclass(frozen=True, slots=True, kw_only=True)
class EndResearchPayload:
    assignment_id: UUID
    expected_version: int
    disposition: str
    reason: str

    def __post_init__(self):
        _uuid(self.assignment_id)
        _integer(self.expected_version)
        _text(self.reason)
        if not _literal(self.disposition, ASSIGNMENT_STATES & TERMINAL):
            raise ValueError('Invalid assignment disposition.')

    def to_payload(self):
        return {'assignment_id': str(self.assignment_id), 'expected_version': self.expected_version,
                'disposition': self.disposition, 'reason': self.reason}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkCommand:
    operation: str
    idempotency_key: str
    expected_revision: int
    expected_epoch: int
    payload: WorkCommandPayload | AssignResearchPayload | AssignWorkPayload | EndResearchPayload

    def __post_init__(self):
        _text(self.idempotency_key, maximum=256)
        _integer(self.expected_revision)
        _integer(self.expected_epoch, 1)
        cls = _OPERATIONS.get(self.operation) if type(self.operation) is str else None
        if cls is None or type(self.payload) is not cls:
            raise ValueError('Invalid operation payload.')

    def to_payload(self):
        return {'operation': self.operation, 'idempotency_key': self.idempotency_key,
                'expected_revision': self.expected_revision, 'expected_epoch': self.expected_epoch,
                'payload': self.payload.to_payload()}


_OPERATIONS = {'ASSIGN_RESEARCH': AssignResearchPayload, 'ASSIGN_WORK': AssignWorkPayload,
               'END_RESEARCH': EndResearchPayload, 'START_WORK': StartWorkPayload, 'RECORD_ACTIVITY': StartWorkPayload,
               'WAIT_WORK': ReasonWorkPayload, 'RESUME_WORK': ReasonWorkPayload,
               'REQUEST_CANCEL': ReasonWorkPayload, 'ACK_STOP': StopWorkPayload, 'END_WORK': EndWorkPayload}


@dataclass(frozen=True, slots=True)
class ResearchCommandResult:
    disposition: str
    command: ResearchWorkCommand | None = None
    reason_code: str | None = None

    def to_payload(self):
        return {'disposition': self.disposition, 'reason_code': self.reason_code,
                'command': self.command.to_payload() if self.command else None}


def parse_research_work_command(raw):
    try:
        if type(raw) is not dict or set(raw) != {'operation', 'idempotency_key', 'expected_revision', 'expected_epoch', 'payload'}:
            raise ValueError('Invalid command.')
        if type(raw['operation']) is not str or raw['operation'] not in _OPERATIONS or type(raw['payload']) is not dict:
            raise ValueError('Invalid command.')
        cls = _OPERATIONS[raw['operation']]
        values = dict(raw['payload'])
        if set(values) != set(cls.__dataclass_fields__):
            raise ValueError('Invalid command.')
        for key in ('work_id', 'assignment_id'):
            if key in values:
                if type(values[key]) is not str:
                    raise ValueError('Invalid command.')
                values[key] = UUID(values[key])
        if cls is AssignResearchPayload:
            envelope = values['authority']
            if type(envelope) is not dict or set(envelope) != set(ResearchAuthority.__dataclass_fields__):
                raise ValueError('Invalid command.')
            if any(type(envelope[key]) is not list for key in ('actions', 'sources')):
                raise ValueError('Invalid command.')
            if any(type(v) is not str for key in ('actions', 'sources') for v in envelope[key]):
                raise ValueError('Invalid command.')
            if any(len(set(envelope[key])) != len(envelope[key]) for key in ('actions', 'sources')):
                raise ValueError('Invalid command.')
            values['authority'] = ResearchAuthority(actions=frozenset(envelope['actions']),
                sources=frozenset(envelope['sources']), deadline=datetime.fromisoformat(envelope['deadline']),
                quota_ceiling=envelope['quota_ceiling'])
        if cls is AssignWorkPayload:
            bindings = values['inputs']
            if type(bindings) is not dict or set(bindings) != set(ResearchInputBindings.__dataclass_fields__):
                raise ValueError('Invalid command.')
            if any(type(bindings[key]) is not list for key in ('observation_ids', 'finding_revisions')):
                raise ValueError('Invalid command.')
            revisions = []
            for row in bindings['finding_revisions']:
                if type(row) is not dict or set(row) != {'finding_id', 'revision'}:
                    raise ValueError('Invalid command.')
                revisions.append((UUID(row['finding_id']), row['revision']))
            values['inputs'] = ResearchInputBindings(**{**bindings, 'mission_id': UUID(bindings['mission_id']),
                'observation_ids': tuple(UUID(v) for v in bindings['observation_ids']),
                'finding_revisions': tuple(revisions)})
            if type(values['dependencies']) is not list:
                raise ValueError('Invalid command.')
            values['dependencies'] = tuple(UUID(v) for v in values['dependencies'])
        for key in ('occurred_at', 'fresh_until'):
            if key in values:
                if type(values[key]) is not str:
                    raise ValueError('Invalid command.')
                values[key] = datetime.fromisoformat(values[key])
        command = ResearchWorkCommand(**{**raw, 'payload': cls(**values)})
        return ResearchCommandResult('VALID', command)
    except (ValueError, TypeError, AttributeError, OverflowError):
        return ResearchCommandResult('REFUSED', reason_code='INVALID_COMMAND')


def check_research_work_retry(*, original, retry):
    if original == retry:
        return ResearchCommandResult('IDEMPOTENT')
    return ResearchCommandResult('REFUSED', reason_code='IDEMPOTENCY_CONFLICT')


@dataclass(frozen=True, slots=True)
class ResearchTransition:
    disposition: str
    work: ResearchWorkItem
    reason_code: str | None = None


def transition_research_work(*, work, command, assignment, now):
    payload = command.payload
    if not isinstance(payload, WorkCommandPayload):
        return ResearchTransition('REFUSED', work, 'INVALID_TRANSITION')
    if payload.work_id != work.work_id:
        return ResearchTransition('REFUSED', work, 'SCOPE_MISMATCH')
    reason = _identity_reason(assignment, work, now, command.expected_epoch,
                              payload.expected_version, payload.ownership_fence)
    if reason:
        return ResearchTransition('REFUSED', work, reason)
    operation = command.operation
    # Closing a bound execution records cessation without renewing research authority.
    closure = (operation == 'ACK_STOP' or operation == 'END_WORK'
               and payload.disposition in {'FAILED', 'INTERRUPTED', 'INSUFFICIENT_EVIDENCE'})
    reason = ('WORK_TERMINAL' if work.state in TERMINAL else None) if closure else _admission_reason(assignment, work, now)
    if reason:
        return ResearchTransition('REFUSED', work, reason)
    if operation == 'END_WORK' and payload.disposition == 'COMPLETED':
        return ResearchTransition('REFUSED', work, 'RESULT_REQUIRED')
    transitions = {'WAIT_WORK': ('RUNNING', 'WAITING'), 'RESUME_WORK': ('WAITING', 'RUNNING'),
                   'REQUEST_CANCEL': (work.state, 'CANCEL_PENDING'), 'ACK_STOP': ('CANCEL_PENDING', 'CANCELLED'),
                   'END_WORK': (work.state, payload.disposition if isinstance(payload, EndWorkPayload) else '')}
    if operation in ('START_WORK', 'RECORD_ACTIVITY'):
        receipt = ResearchActivityReceipt(work_id=work.work_id, epoch=command.expected_epoch,
            ownership_fence=payload.ownership_fence, execution_ref=payload.execution_ref,
            occurred_at=payload.occurred_at, fresh_until=payload.fresh_until, provenance='HOST_REPORTED')
        if operation == 'RECORD_ACTIVITY':
            if work.state != 'RUNNING':
                return ResearchTransition('REFUSED', work, 'INVALID_TRANSITION')
            if not receipt.occurred_at <= now < receipt.fresh_until:
                return ResearchTransition('REFUSED', work, 'EXECUTION_RECEIPT_NOT_CURRENT')
            return ResearchTransition('APPLIED', replace(work, version=work.version + 1))
        admission = admit_work_start(assignment=assignment, work=work, receipt=receipt, now=now,
            expected_epoch=command.expected_epoch, expected_version=payload.expected_version,
            ownership_fence=payload.ownership_fence, host_authorized=True)
        if not admission.allowed:
            return ResearchTransition('REFUSED', work, admission.reason_code)
        target = 'RUNNING'
    elif operation in transitions and work.state == transitions[operation][0]:
        target = transitions[operation][1]
    else:
        return ResearchTransition('REFUSED', work, 'INVALID_TRANSITION')
    return ResearchTransition('APPLIED', replace(work, state=target, version=work.version + 1))
