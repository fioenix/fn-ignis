"""Private explicit grants and operational facts; constructors do not confer authority."""

from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from ignis.domain.mission_follow_up import FollowUpWork
from ignis.domain.research_work import ResearchInputBindings, _digest, _integer as _domain_integer, _text, _time, _uuid


def _integer(value, minimum=0):
    _domain_integer(value, minimum)
    if value > 2**63 - 1:
        raise ValueError("Invalid finite integer amount.")


def identity(value):
    if is_dataclass(value):
        return {f.name: identity(getattr(value, f.name)) for f in fields(value)}
    if type(value) in (tuple, frozenset):
        rows = [identity(v) for v in value]
        return sorted(rows) if type(value) is frozenset else rows
    if type(value) is UUID:
        return str(value)
    if type(value) is datetime:
        return value.isoformat()
    return value


def digest(record):
    return sha256(
        json.dumps(identity(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def resources(values):
    if type(values) is not tuple or not values or len(values) > 100:
        raise ValueError("Finite explicit resource allocations required.")
    seen = set()
    for row in values:
        if type(row) is not tuple or len(row) != 2:
            raise ValueError("Invalid resource allocation.")
        _text(row[0], maximum=128)
        _integer(row[1])
        if row[0] in seen:
            raise ValueError("Duplicate resource allocation.")
        seen.add(row[0])


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationalGap:
    gap_id: UUID
    parent_work_id: UUID
    inputs: ResearchInputBindings
    question: str
    finding_id: UUID | None = None
    finding_revision: int | None = None
    question_index: int | None = None

    def __post_init__(self):
        _uuid(self.gap_id)
        _uuid(self.parent_work_id)
        _text(self.question)
        if type(self.inputs) is not ResearchInputBindings:
            raise ValueError("Exact input bindings required.")
        if self.finding_id is None:
            if self.finding_revision is not None or self.question_index is not None:
                raise ValueError("Host gap cannot borrow a finding origin.")
        else:
            _uuid(self.finding_id)
            _integer(self.finding_revision, 1)
            _integer(self.question_index)


@dataclass(frozen=True, slots=True, kw_only=True)
class ParentBudget:
    budget_id: UUID
    mission_id: UUID
    manifest_digest: str
    brief_digest: str
    quota_unit: str
    cost_unit: str
    quota_ceiling: int
    cost_ceiling: int
    resources: tuple[tuple[str, int], ...]
    confirmation_ref: str

    def __post_init__(self):
        _uuid(self.budget_id)
        _uuid(self.mission_id)
        _digest(self.manifest_digest)
        _digest(self.brief_digest)
        for v in (self.quota_unit, self.cost_unit, self.confirmation_ref):
            _text(v, maximum=128)
        _integer(self.quota_ceiling)
        _integer(self.cost_ceiling)
        resources(self.resources)


@dataclass(frozen=True, slots=True, kw_only=True)
class AssignmentBudget:
    binding_id: UUID
    budget_id: UUID
    assignment_id: UUID
    epoch: int
    assignment_version: int
    assignment_quota: int
    quota_unit: str
    cost_ceiling: int
    confirmation_ref: str

    def __post_init__(self):
        for v in (self.binding_id, self.budget_id, self.assignment_id):
            _uuid(v)
        for v in (self.epoch, self.assignment_version):
            _integer(v, 1)
        _integer(self.assignment_quota)
        _integer(self.cost_ceiling)
        _text(self.quota_unit, maximum=128)
        _text(self.confirmation_ref, maximum=128)


@dataclass(frozen=True, slots=True, kw_only=True)
class SourceGrant:
    source: str
    platform: str
    tier: str
    paid: bool
    plan_digest: str
    connector_revision: str
    capability_id: str
    capability_epoch: int

    def __post_init__(self):
        for v in (self.source, self.platform, self.connector_revision, self.capability_id):
            _text(v, maximum=128)
        if self.tier not in {"public_http", "official_api", "browser_session"} or type(self.paid) is not bool:
            raise ValueError("Invalid source authority tier.")
        _digest(self.plan_digest)
        _integer(self.capability_epoch, 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkAuthority:
    work: FollowUpWork
    budget_id: UUID
    binding_id: UUID
    quota_unit: str
    cost_unit: str
    quota: int
    cost: int
    quota_ceiling: int
    cost_ceiling: int
    resources: tuple[tuple[str, int], ...]
    sources: tuple[SourceGrant, ...]
    confirmation_ref: str

    def __post_init__(self):
        if type(self.work) is not FollowUpWork:
            raise ValueError("Exact work required.")
        _uuid(self.budget_id)
        _uuid(self.binding_id)
        for v in (self.quota_unit, self.cost_unit, self.confirmation_ref):
            _text(v, maximum=128)
        for v in (self.quota, self.cost, self.quota_ceiling, self.cost_ceiling):
            _integer(v)
        resources(self.resources)
        if type(self.sources) is not tuple or not self.sources or any(type(s) is not SourceGrant for s in self.sources):
            raise ValueError("Explicit source grant required.")
        if len({s.source for s in self.sources}) != len(self.sources):
            raise ValueError("Duplicate source grant.")

    @property
    def digest(self):
        return digest(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class CapabilityProof:
    envelope_digest: str
    process_id: str
    policy_generation: int
    operational_generation: int
    checked_at: datetime
    fresh_until: datetime
    sources: tuple[SourceGrant, ...]
    quota_unit: str
    cost_unit: str
    quota_required: int
    cost_required: int
    resources: tuple[tuple[str, int], ...]
    allowed: bool
    stop_reached: bool
    cancel_requested: bool

    def __post_init__(self):
        _digest(self.envelope_digest)
        _text(self.process_id, maximum=128)
        _integer(self.policy_generation, 1)
        _integer(self.operational_generation, 1)
        _time(self.checked_at)
        _time(self.fresh_until)
        if (
            self.fresh_until <= self.checked_at
            or type(self.allowed) is not bool
            or type(self.stop_reached) is not bool
            or type(self.cancel_requested) is not bool
        ):
            raise ValueError("Invalid capability proof.")
        for v in (self.quota_unit, self.cost_unit):
            _text(v, maximum=128)
        _integer(self.quota_required)
        _integer(self.cost_required)
        resources(self.resources)
        if type(self.sources) is not tuple or any(type(s) is not SourceGrant for s in self.sources):
            raise ValueError("Invalid verified source bindings.")
