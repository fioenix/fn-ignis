"""Immutable follow-up contracts; storage owns admission and canonical verification."""
from dataclasses import dataclass, replace
from datetime import datetime
import re
from uuid import UUID

from ignis.domain.research_work import (
    ResearchInputBindings, _digest, _ids, _integer, _literal, _text, _time, _uuid,
)


def _exact(value, cls):
    if type(value) is not cls:
        raise ValueError('Invalid exact follow-up record type.')


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpExecutionRequest:
    """Public execution input carries IDs and a retry key, never an authority grant."""
    mission_id: UUID
    follow_up_work_id: UUID
    expected_research_epoch: int
    idempotency_key: str

    def __post_init__(self):
        _uuid(self.mission_id)
        _uuid(self.follow_up_work_id)
        _integer(self.expected_research_epoch, 1)
        _text(self.idempotency_key, maximum=256)

    def to_payload(self):
        return {'mission_id': str(self.mission_id), 'follow_up_work_id': str(self.follow_up_work_id),
                'expected_research_epoch': self.expected_research_epoch, 'idempotency_key': self.idempotency_key}


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpScope:
    queries: tuple[str, ...]
    sources: frozenset[str]

    def __post_init__(self):
        if type(self.queries) is not tuple or not 1 <= len(self.queries) <= 100:
            raise ValueError('Invalid finite query scope.')
        for query in self.queries:
            _text(query, maximum=512)
        if len(set(self.queries)) != len(self.queries):
            raise ValueError('Duplicate query scope.')
        if type(self.sources) is not frozenset or not 1 <= len(self.sources) <= 100:
            raise ValueError('Invalid finite source scope.')
        for source in self.sources:
            _text(source, maximum=128)
            if re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', source) is None:
                raise ValueError('Invalid source identifier.')

    def contains(self, requested: 'FollowUpScope') -> bool:
        _exact(requested, FollowUpScope)
        return requested.sources <= self.sources and set(requested.queries) <= set(self.queries)


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpWork:
    """Recorded proposal; presence alone does not establish admission or authority."""
    work_id: UUID
    parent_work_id: UUID
    assignment_id: UUID
    gap_id: UUID
    inputs: ResearchInputBindings
    research_epoch: int
    assignment_version: int
    work_version: int
    brief_revision_id: UUID
    approved_scope: FollowUpScope
    requested_scope: FollowUpScope
    authority_deadline: datetime

    def __post_init__(self):
        for identity in (self.work_id, self.parent_work_id, self.assignment_id, self.gap_id,
                         self.brief_revision_id):
            _uuid(identity)
        _exact(self.inputs, ResearchInputBindings)
        if self.inputs.brief_digest is None:
            raise ValueError('Confirmed parent Brief binding required.')
        for version in (self.research_epoch, self.assignment_version, self.work_version):
            _integer(version, 1)
        _exact(self.approved_scope, FollowUpScope)
        _exact(self.requested_scope, FollowUpScope)
        _time(self.authority_deadline)


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpRelationship:
    """One immutable admitted child link, without changing parent lifecycle or evidence."""
    follow_up_id: UUID
    work: FollowUpWork
    child_mission_id: UUID
    child_manifest_digest: str
    child_brief_digest: str
    reservation_id: UUID
    idempotency_key: str

    def __post_init__(self):
        for identity in (self.follow_up_id, self.child_mission_id, self.reservation_id):
            _uuid(identity)
        _exact(self.work, FollowUpWork)
        _digest(self.child_manifest_digest)
        _digest(self.child_brief_digest)
        _text(self.idempotency_key, maximum=256)
        if self.child_mission_id == self.work.inputs.mission_id:
            raise ValueError('Follow-up child must differ from parent.')
        if not self.work.approved_scope.contains(self.work.requested_scope):
            raise ValueError('Follow-up scope exceeds recorded approval.')

    def to_payload(self):
        return {'follow_up_id': str(self.follow_up_id), 'parent_mission_id': str(self.work.inputs.mission_id),
                'child_mission_id': str(self.child_mission_id), 'parent_work_id': str(self.work.parent_work_id),
                'work_id': str(self.work.work_id), 'assignment_id': str(self.work.assignment_id),
                'gap_id': str(self.work.gap_id), 'research_epoch': self.work.research_epoch,
                'reservation_id': str(self.reservation_id), 'child_manifest_digest': self.child_manifest_digest,
                'child_brief_digest': self.child_brief_digest}


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpReservation:
    """Integer quota/cost units follow the recorded budget; no inferred currency conversion."""
    relationship: FollowUpRelationship
    reserved_quota: int
    reserved_cost: int
    state: str
    measured_quota: int | None
    measured_cost: int | None
    measurement_receipt_id: UUID | None

    def __post_init__(self):
        _exact(self.relationship, FollowUpRelationship)
        for amount in (self.reserved_quota, self.reserved_cost):
            _integer(amount)
        for amount in (self.measured_quota, self.measured_cost):
            if amount is not None:
                _integer(amount)
        _uuid(self.measurement_receipt_id, True)
        if not _literal(self.state, {'RESERVED', 'UNRESOLVED', 'SETTLED'}):
            raise ValueError('Invalid reservation state.')
        if self.state == 'SETTLED':
            if None in (self.measured_quota, self.measured_cost, self.measurement_receipt_id):
                raise ValueError('Complete measurement receipt required for settlement.')
        elif self.measurement_receipt_id is not None:
            raise ValueError('Unsettled reservation cannot carry a final measurement receipt.')

    @property
    def encumbered(self) -> tuple[int, int]:
        if self.state == 'SETTLED':
            return self.measured_quota, self.measured_cost
        # Unknown or partial usage cannot release unused allocation; overspend remains visible.
        return (max(self.reserved_quota, self.measured_quota or 0),
                max(self.reserved_cost, self.measured_cost or 0))

    def to_payload(self):
        return {'relationship': self.relationship.to_payload(), 'state': self.state,
                'reserved_quota': self.reserved_quota, 'reserved_cost': self.reserved_cost,
                'measured_quota': self.measured_quota, 'measured_cost': self.measured_cost,
                'measurement_receipt_id': str(self.measurement_receipt_id) if self.measurement_receipt_id else None}

    def reconcile(self, *, measured_quota: int | None = None, measured_cost: int | None = None,
                  measurement_receipt_id: UUID | None = None) -> 'FollowUpReservation':
        """Storage must verify final receipt and closed writer before persisting settlement."""
        quota = self.measured_quota if measured_quota is None else measured_quota
        cost = self.measured_cost if measured_cost is None else measured_cost
        receipt = self.measurement_receipt_id if measurement_receipt_id is None else measurement_receipt_id
        for old, new in ((self.measured_quota, quota), (self.measured_cost, cost)):
            if new is not None:
                _integer(new)
            if old is not None and new < old:
                raise ValueError('Measured usage cannot decrease.')
        if self.state == 'SETTLED':
            if (quota, cost, receipt) != (self.measured_quota, self.measured_cost, self.measurement_receipt_id):
                raise ValueError('Cannot revise a settled reservation.')
            return self
        return replace(self, measured_quota=quota, measured_cost=cost, measurement_receipt_id=receipt,
                       state='SETTLED' if receipt is not None else 'UNRESOLVED')


def encumbered_budget(parent_mission_id: UUID,
                      reservations: tuple[FollowUpReservation, ...]) -> tuple[int, int]:
    """Sum all sibling/epoch spend and unresolved allocation; storage supplies complete history."""
    _uuid(parent_mission_id)
    if type(reservations) is not tuple:
        raise ValueError('Invalid reservation history.')
    seen = [set(), set(), set(), set()]
    quota = cost = 0
    for reservation in reservations:
        _exact(reservation, FollowUpReservation)
        relation = reservation.relationship
        if relation.work.inputs.mission_id != parent_mission_id:
            raise ValueError('Foreign parent reservation.')
        for identities, identity in zip(seen, (relation.reservation_id, relation.follow_up_id,
                                               relation.child_mission_id, relation.work.work_id)):
            if identity in identities:
                raise ValueError('Duplicate child or reservation identity.')
            identities.add(identity)
        charged_quota, charged_cost = reservation.encumbered
        quota += charged_quota
        cost += charged_cost
    return quota, cost


@dataclass(frozen=True, slots=True, kw_only=True)
class FollowUpResult:
    """Child-only references; canonical membership and permission require separate verification."""
    relationship: FollowUpRelationship
    child_run_id: UUID | None
    state: str
    inputs: ResearchInputBindings | None
    observation_sources: tuple[tuple[UUID, UUID], ...]
    outcome_ids: tuple[UUID, ...]
    claim_ids: tuple[UUID, ...]

    def __post_init__(self):
        _exact(self.relationship, FollowUpRelationship)
        _uuid(self.child_run_id, True)
        _ids(self.outcome_ids)
        _ids(self.claim_ids)
        if not _literal(self.state, {'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED', 'UNRESOLVED'}):
            raise ValueError('Invalid result state.')
        if self.inputs is not None:
            _exact(self.inputs, ResearchInputBindings)
            if (self.inputs.mission_id != self.relationship.child_mission_id
                    or self.inputs.manifest_digest != self.relationship.child_manifest_digest
                    or self.inputs.brief_digest != self.relationship.child_brief_digest):
                raise ValueError('Invalid child evidence binding.')
        if type(self.observation_sources) is not tuple:
            raise ValueError('Invalid observation source bindings.')
        observations = []
        for pair in self.observation_sources:
            if type(pair) is not tuple or len(pair) != 2:
                raise ValueError('Invalid observation source identity.')
            _uuid(pair[0])
            _uuid(pair[1])
            observations.append(pair[0])
        _ids(tuple(observations))
        if set(observations) != set(self.inputs.observation_ids if self.inputs else ()):
            raise ValueError('Child observation identity mismatch.')
        framed = self.inputs is not None and self.inputs.frame_digest is not None and self.child_run_id is not None
        if not framed and (self.state == 'COMPLETED' or self.claim_ids or self.observation_sources
                           or (self.inputs and self.inputs.finding_revisions) or self.outcome_ids):
            raise ValueError('Actual child run and frame required for result references.')

    def related_payload(self):
        return {'relation': 'FOLLOW_UP_CHILD', 'mission_id': str(self.relationship.child_mission_id),
                'run_id': str(self.child_run_id) if self.child_run_id else None,
                'frame_digest': self.inputs.frame_digest if self.inputs else None,
                'finding_references': [{'finding_id': str(i), 'revision': r}
                                       for i, r in (self.inputs.finding_revisions if self.inputs else ())],
                'inspection_status': 'SELECT_CHILD_REQUIRED'}

    def to_payload(self):
        return {**self.relationship.to_payload(), 'state': self.state,
                'child_run_id': str(self.child_run_id) if self.child_run_id else None,
                'inputs': self.inputs.to_payload() if self.inputs else None,
                'observation_sources': [{'observation_id': str(o), 'source_id': str(s)}
                                        for o, s in self.observation_sources],
                'outcome_ids': [str(i) for i in self.outcome_ids], 'claim_ids': [str(i) for i in self.claim_ids]}
