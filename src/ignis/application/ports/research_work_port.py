"""Atomic research recording contracts, without storage or host execution.

Stores admit under one transaction and return the original receipt on exact retry.
Content remains submitted content; only explicit store metadata records commit time.
"""
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from hashlib import sha256
import json
from typing import Protocol
from uuid import UUID

from ignis.domain.mission_relay import MissionProgressEvent
from ignis.domain.research_findings import ResearchFindingRevision, ResearchHandoff
from ignis.domain.research_work import (
    ResearchAssignment, ResearchWorkItem, ResearchInputBindings, ResearchActivityReceipt,
    ReasonWorkPayload, StopWorkPayload, EndWorkPayload, EndResearchPayload,
    _uuid, _integer, _text, _time, _digest, _ids, _literal,
)


SAFE_REASONS = frozenset({
    'INPUT_REVISION_MISMATCH', 'INVALID_REASON_CODE', 'STORAGE_FAILURE',
    'IDEMPOTENCY_CONFLICT', 'STALE_REVISION', 'STALE_EPOCH', 'STALE_VERSION',
    'STALE_FENCE', 'OWNERSHIP_FENCE_MISMATCH', 'INPUT_IDENTITY_MISMATCH',
    'STALE_DEPENDENCY_REVISION', 'STALE_INPUT_FRAME', 'SCOPE_MISMATCH',
    'AUTHORITY_EXPIRED', 'AUTHORITY_WIDENING', 'ASSIGNMENT_TERMINAL',
    'CANCELLATION_PENDING', 'WORK_TERMINAL', 'ACTION_NOT_GRANTED',
    'UNKNOWN_ASSIGNEE', 'CAPABILITY_UNAVAILABLE', 'UNAUTHORIZED_HOST',
    'EXECUTION_RECEIPT_REQUIRED', 'EXECUTION_RECEIPT_NOT_CURRENT',
    'INVALID_TRANSITION', 'DEPENDENCY_NOT_READY', 'INVALID_INPUT',
    'STALE_WORK_VERSION', 'INVALID_COMMAND', 'RESULT_REQUIRED',
})


def _typed(value, cls):
    if type(value) is not cls:
        raise ValueError('Invalid exact record type.')


def _records(values, cls):
    if type(values) is not tuple or len(values) > 10000:
        raise ValueError('Invalid record collection.')
    for value in values:
        _typed(value, cls)


def _identity(value):
    """Canonical private identity includes unknown reasons, never outward projection."""
    if is_dataclass(value):
        return {f.name: _identity(getattr(value, f.name)) for f in fields(value)}
    if type(value) in (tuple, frozenset):
        rows = [_identity(v) for v in value]
        return sorted(rows) if type(value) is frozenset else rows
    if type(value) is UUID:
        return str(value)
    if type(value) is datetime:
        return value.isoformat()
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchAssignmentAdmission:
    assignment: ResearchAssignment
    expected_manifest_digest: str
    expected_brief_revision_id: UUID

    def __post_init__(self):
        _typed(self.assignment, ResearchAssignment)
        _digest(self.expected_manifest_digest)
        _uuid(self.expected_brief_revision_id)

    def to_payload(self):
        return {'assignment': self.assignment.to_payload(),
                'expected_manifest_digest': self.expected_manifest_digest,
                'expected_brief_revision_id': str(self.expected_brief_revision_id)}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkStartAdmission:
    work_id: UUID
    expected_version: int
    ownership_fence: str
    receipt: ResearchActivityReceipt

    def __post_init__(self):
        _uuid(self.work_id)
        _integer(self.expected_version)
        _text(self.ownership_fence, maximum=256)
        _typed(self.receipt, ResearchActivityReceipt)
        if self.receipt.work_id != self.work_id or self.receipt.ownership_fence != self.ownership_fence:
            raise ValueError('Invalid activity receipt binding.')

    def to_payload(self):
        return {'work_id': str(self.work_id), 'expected_version': self.expected_version,
                'ownership_fence': self.ownership_fence, 'receipt': self.receipt.to_payload()}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchHandoffAcknowledgement:
    handoff_id: UUID
    consumer_ref: str
    expected_version: int
    disposition: str
    reason_code: str | None
    inputs: ResearchInputBindings

    def __post_init__(self):
        _uuid(self.handoff_id)
        _text(self.consumer_ref, maximum=512)
        _integer(self.expected_version)
        _typed(self.inputs, ResearchInputBindings)
        _text(self.reason_code, True)
        if not _literal(self.disposition, {'ACCEPTED', 'REJECTED'}):
            raise ValueError('Invalid acknowledgement disposition.')

    def to_payload(self):
        reason = self.reason_code
        if reason is not None and reason not in SAFE_REASONS:
            reason = 'INVALID_REASON_CODE'
        return {'handoff_id': str(self.handoff_id), 'consumer_ref': self.consumer_ref,
                'expected_version': self.expected_version, 'disposition': self.disposition,
                'reason_code': reason, 'inputs': self.inputs.to_payload()}


_OPERATIONS = {'ASSIGN_RESEARCH': ResearchAssignmentAdmission, 'ASSIGN_WORK': ResearchWorkItem,
               'START_WORK': ResearchWorkStartAdmission, 'RECORD_ACTIVITY': ResearchWorkStartAdmission,
               'SUBMIT_HANDOFF': ResearchHandoff, 'ACK_HANDOFF': ResearchHandoffAcknowledgement,
               'WAIT_WORK': ReasonWorkPayload, 'RESUME_WORK': ReasonWorkPayload,
               'REQUEST_CANCEL': ReasonWorkPayload, 'ACK_STOP': StopWorkPayload,
               'END_WORK': EndWorkPayload, 'END_RESEARCH': EndResearchPayload}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkCommitCommand:
    mission_id: UUID
    operation: str
    payload: (ResearchAssignmentAdmission | ResearchWorkItem | ResearchWorkStartAdmission |
              ResearchHandoff | ResearchHandoffAcknowledgement | ReasonWorkPayload |
              StopWorkPayload | EndWorkPayload | EndResearchPayload)
    expected_revision: int
    expected_epoch: int
    idempotency_key: str
    host_authorized: bool

    def __post_init__(self):
        _uuid(self.mission_id)
        _integer(self.expected_revision)
        _integer(self.expected_epoch, 1)
        _text(self.idempotency_key, maximum=256)
        if type(self.host_authorized) is not bool:
            raise ValueError('Invalid host authority context.')
        cls = _OPERATIONS.get(self.operation) if type(self.operation) is str else None
        if cls is None:
            raise ValueError('Invalid recording operation.')
        _typed(self.payload, cls)

    @property
    def fingerprint(self):
        return sha256(json.dumps(_identity(self), sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False).encode()).hexdigest()

    def to_payload(self):
        # Rejected submitted bodies are never audit receipts or outward command copy.
        return {'mission_id': str(self.mission_id), 'operation': self.operation,
                'expected_revision': self.expected_revision, 'expected_epoch': self.expected_epoch,
                'idempotency_key': self.idempotency_key, 'host_authorized': self.host_authorized,
                'fingerprint': self.fingerprint}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkCommitReceipt:
    disposition: str
    reason_code: str | None
    revision: int
    work_version: int | None
    assignment_version: int | None
    receipt_id: UUID
    event_ids: tuple[UUID, ...]
    recorded_at: datetime

    def __post_init__(self):
        if not _literal(self.disposition, {'APPLIED', 'REFUSED'}):
            raise ValueError('Invalid receipt disposition.')
        if self.reason_code is not None and not _literal(self.reason_code, SAFE_REASONS):
            raise ValueError('Invalid safe receipt reason.')
        _integer(self.revision)
        for version in (self.work_version, self.assignment_version):
            if version is not None:
                _integer(version, 1)
        _uuid(self.receipt_id)
        _ids(self.event_ids)
        _time(self.recorded_at)
        if self.disposition == 'REFUSED' and (self.reason_code is None or self.event_ids):
            raise ValueError('Refusal requires safe reason and no committed events.')

    def to_payload(self):
        return _identity(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchRecordedMetadata:
    """Store-observed time keyed to exact immutable submitted record version."""
    record_kind: str
    record_id: UUID
    record_version: int
    mission_revision: int
    recorded_at: datetime
    provenance: str

    def __post_init__(self):
        if not _literal(self.record_kind, {'ASSIGNMENT', 'WORK', 'HANDOFF', 'FINDING'}):
            raise ValueError('Invalid metadata record kind.')
        _uuid(self.record_id)
        _integer(self.record_version, 1)
        _integer(self.mission_revision, 1)
        _time(self.recorded_at)
        if not _literal(self.provenance, {'HARNESS_OBSERVED'}):
            raise ValueError('Invalid transaction time provenance.')

    def to_payload(self):
        return _identity(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchWorkSnapshot:
    mission_id: UUID
    revision: int
    current_epoch: int
    assignments: tuple[ResearchAssignment, ...]
    work_items: tuple[ResearchWorkItem, ...]
    handoffs: tuple[ResearchHandoff, ...]
    findings: tuple[ResearchFindingRevision, ...]
    acknowledgements: tuple[ResearchHandoffAcknowledgement, ...]
    events: tuple[MissionProgressEvent, ...]
    observation_sources: tuple[tuple[UUID, UUID], ...]
    current_finding_revisions: tuple[tuple[UUID, int], ...]
    recorded_metadata: tuple[ResearchRecordedMetadata, ...]

    def __post_init__(self):
        _uuid(self.mission_id)
        _integer(self.revision)
        _integer(self.current_epoch)
        for name, cls in (('assignments', ResearchAssignment), ('work_items', ResearchWorkItem),
                          ('handoffs', ResearchHandoff), ('findings', ResearchFindingRevision),
                          ('acknowledgements', ResearchHandoffAcknowledgement),
                          ('events', MissionProgressEvent), ('recorded_metadata', ResearchRecordedMetadata)):
            _records(getattr(self, name), cls)
        if type(self.observation_sources) is not tuple:
            raise ValueError('Invalid observation source collection.')
        observations = set()
        for pair in self.observation_sources:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError('Invalid observation source identity.')
            _uuid(pair[0])
            _uuid(pair[1])
            if pair[0] in observations:
                raise ValueError('Duplicate observation identity.')
            observations.add(pair[0])
        source_bindings = dict(self.observation_sources)
        for handoff in self.handoffs:
            for observation, source in handoff.observation_sources:
                if observation in source_bindings and source_bindings[observation] != source:
                    raise ValueError('Conflicting immutable observation source identity.')
                source_bindings[observation] = source
        # Historical bindings constrain overlapping identities, never current membership.
        latest = {}
        history = set()
        for finding in self.findings:
            key = (finding.finding_id, finding.revision)
            if key in history:
                raise ValueError('Duplicate finding revision.')
            history.add(key)
            latest[finding.finding_id] = max(latest.get(finding.finding_id, 0), finding.revision)
        if type(self.current_finding_revisions) is not tuple:
            raise ValueError('Invalid current finding revisions.')
        selected = set()
        for pair in self.current_finding_revisions:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError('Invalid current finding revision.')
            _uuid(pair[0])
            _integer(pair[1], 1)
            if pair[0] in selected or latest.get(pair[0]) != pair[1]:
                raise ValueError('Unknown or superseded current finding revision.')
            selected.add(pair[0])
        for record in (*self.assignments, *self.work_items):
            if record.mission_id != self.mission_id or record.epoch > self.current_epoch:
                raise ValueError('Invalid snapshot assignment scope or epoch.')
        for record in (*self.handoffs, *self.findings, *self.acknowledgements):
            if record.inputs.mission_id != self.mission_id:
                raise ValueError('Invalid snapshot input scope.')
        if any(e.cursor.mission_id != self.mission_id or e.cursor.revision > self.revision for e in self.events):
            raise ValueError('Invalid snapshot event scope.')
        for name, identity in (('assignments', 'assignment_id'), ('work_items', 'work_id'),
                               ('handoffs', 'handoff_id'), ('acknowledgements', 'handoff_id'),
                               ('events', 'event_id')):
            identities = [getattr(r, identity) for r in getattr(self, name)]
            if len(set(identities)) != len(identities):
                raise ValueError('Duplicate snapshot record identity.')
        if any(a.reason_code is not None and a.reason_code not in SAFE_REASONS
               for a in self.acknowledgements):
            raise ValueError('Unsafe acknowledgement cannot be persisted.')
        cursors = [e.cursor for e in self.events]
        if len(set(cursors)) != len(cursors):
            raise ValueError('Duplicate snapshot event cursor.')
        required = {('ASSIGNMENT', a.assignment_id, a.version) for a in self.assignments}
        required |= {('WORK', w.work_id, w.version) for w in self.work_items}
        required |= {('HANDOFF', h.handoff_id, 1) for h in self.handoffs}
        required |= {('FINDING', f.finding_id, f.revision) for f in self.findings}
        keys = [(m.record_kind, m.record_id, m.record_version) for m in self.recorded_metadata]
        if len(set(keys)) != len(keys) or not required <= set(keys):
            raise ValueError('Missing or duplicate persisted record metadata.')
        versions = {('ASSIGNMENT', a.assignment_id): a.version for a in self.assignments}
        versions.update({('WORK', w.work_id): w.version for w in self.work_items})
        for metadata in self.recorded_metadata:
            key = (metadata.record_kind, metadata.record_id, metadata.record_version)
            if metadata.record_kind in {'HANDOFF', 'FINDING'}:
                if key not in required:
                    raise ValueError('Detached immutable record metadata.')
            elif metadata.record_version > versions.get((metadata.record_kind, metadata.record_id), 0):
                raise ValueError('Unknown or future version metadata.')
        if any(m.mission_revision > self.revision for m in self.recorded_metadata):
            raise ValueError('Metadata exceeds snapshot revision.')

    @property
    def current_finding_ids(self):
        return tuple(i for i, _ in self.current_finding_revisions)

    @property
    def observation_count(self):
        return len(self.observation_sources)

    @property
    def source_count(self):
        return len({source for _, source in self.observation_sources})

    def to_payload(self):
        return {'mission_id': str(self.mission_id), 'revision': self.revision,
                'current_epoch': self.current_epoch,
                **{name: [v.to_payload() for v in getattr(self, name)] for name in
                   ('assignments', 'work_items', 'handoffs', 'findings', 'acknowledgements', 'events', 'recorded_metadata')},
                'observation_sources': [{'observation_id': str(o), 'source_id': str(s)} for o, s in self.observation_sources],
                'observation_count': self.observation_count, 'source_count': self.source_count,
                'current_finding_ids': [str(i) for i in self.current_finding_ids],
                'current_finding_revisions': [{'finding_id': str(i), 'revision': r} for i, r in self.current_finding_revisions]}


class IResearchWorkPort(Protocol):
    """Transaction owner validates authority, CAS, scope and safe persisted content.

    Commit facts, lifecycle, findings, events and original receipt together or none.
    Initial assignment binds its requested epoch; later admission checks current
    epoch/high-water in storage. Exact retry returns the original receipt, time and
    event identities. Recording must never dispatch host agents or providers.
    """
    async def commit_research_work(self, command: ResearchWorkCommitCommand) -> ResearchWorkCommitReceipt: ...

    async def load_research_work(self, mission_id: UUID) -> ResearchWorkSnapshot:
        """Read one coherent transaction, preserving history and exact evidence IDs."""
        ...
