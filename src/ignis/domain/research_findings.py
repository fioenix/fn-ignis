"""Immutable result bindings; admission and safe text projection belong downstream."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ignis.domain.research_work import ResearchInputBindings, _ids, _integer, _literal, _text, _time, _uuid


def _texts(values):
    if type(values) is not tuple or len(values) > 100:
        raise ValueError('Invalid text collection.')
    for value in values:
        _text(value)


def _optional_time(value):
    if value is not None:
        _time(value)


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchFindingRevision:
    finding_id: UUID
    revision: int
    predecessor_revision: int | None
    work_id: UUID
    handoff_id: UUID
    inputs: ResearchInputBindings
    result_type: str
    statement: str
    limitations: tuple[str, ...]
    open_questions: tuple[str, ...]
    supporting_observation_ids: tuple[UUID, ...]
    contradicting_observation_ids: tuple[UUID, ...]
    context_observation_ids: tuple[UUID, ...]
    alternative_explanation: str | None
    claim_id: UUID | None
    # The owning transaction supplies recorded time; construction never invents it.
    recorded_at: datetime | None = None

    def __post_init__(self):
        for value in (self.finding_id, self.work_id, self.handoff_id):
            _uuid(value)
        _uuid(self.claim_id, True)
        _integer(self.revision, 1)
        if self.revision == 1:
            if self.predecessor_revision is not None:
                raise ValueError('First finding revision has no predecessor.')
        else:
            _integer(self.predecessor_revision, 1)
            if self.predecessor_revision != self.revision - 1:
                raise ValueError('Invalid predecessor revision.')
        if type(self.inputs) is not ResearchInputBindings:
            raise ValueError('Invalid finding inputs.')
        if not _literal(self.result_type, {'DESCRIPTIVE', 'STRATEGIC_CANDIDATE'}):
            raise ValueError('Invalid finding result type.')
        _text(self.statement)
        _text(self.alternative_explanation, True)
        _texts(self.limitations)
        _texts(self.open_questions)
        _optional_time(self.recorded_at)
        for values in (self.supporting_observation_ids, self.contradicting_observation_ids,
                       self.context_observation_ids):
            _ids(values)
            if not set(values) <= set(self.inputs.observation_ids):
                raise ValueError('Finding observations exceed bound inputs.')

    def to_payload(self):
        return {'finding_id': str(self.finding_id), 'revision': self.revision,
                'predecessor_revision': self.predecessor_revision, 'work_id': str(self.work_id),
                'handoff_id': str(self.handoff_id), 'inputs': self.inputs.to_payload(),
                'result_type': self.result_type, 'statement': self.statement,
                'limitations': list(self.limitations), 'open_questions': list(self.open_questions),
                'supporting_observation_ids': [str(v) for v in self.supporting_observation_ids],
                'contradicting_observation_ids': [str(v) for v in self.contradicting_observation_ids],
                'context_observation_ids': [str(v) for v in self.context_observation_ids],
                'alternative_explanation': self.alternative_explanation,
                'claim_id': str(self.claim_id) if self.claim_id else None,
                'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None}


@dataclass(frozen=True, slots=True, kw_only=True)
class ResearchHandoff:
    handoff_id: UUID
    work_id: UUID
    expected_version: int
    ownership_fence: str
    consumer_ref: str
    inputs: ResearchInputBindings
    observation_sources: tuple[tuple[UUID, UUID], ...]
    outcome_ids: tuple[UUID, ...]
    claim_ids: tuple[UUID, ...]
    result: str
    limitations: tuple[str, ...]
    open_questions: tuple[str, ...]
    findings: tuple[ResearchFindingRevision, ...]
    occurred_at: datetime | None = None
    # This is transaction metadata, distinct from host-reported occurrence time.
    recorded_at: datetime | None = None

    def __post_init__(self):
        _uuid(self.handoff_id)
        _uuid(self.work_id)
        _integer(self.expected_version)
        _text(self.ownership_fence, maximum=256)
        _text(self.consumer_ref, maximum=512)
        _text(self.result)
        _texts(self.limitations)
        _texts(self.open_questions)
        _ids(self.outcome_ids)
        _ids(self.claim_ids)
        _optional_time(self.occurred_at)
        _optional_time(self.recorded_at)
        if type(self.inputs) is not ResearchInputBindings:
            raise ValueError('Invalid handoff inputs.')
        if type(self.observation_sources) is not tuple or len(self.observation_sources) > 1000:
            raise ValueError('Invalid observation source bindings.')
        observations = set()
        for row in self.observation_sources:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError('Invalid observation source binding.')
            _uuid(row[0])
            _uuid(row[1])
            if row[0] in observations:
                raise ValueError('Duplicate observation source binding.')
            observations.add(row[0])
        if observations != set(self.inputs.observation_ids):
            raise ValueError('Observation sources must match exact inputs.')
        if type(self.findings) is not tuple or len(self.findings) > 1000:
            raise ValueError('Invalid finding collection.')
        identities = set()
        for finding in self.findings:
            if type(finding) is not ResearchFindingRevision:
                raise ValueError('Invalid finding revision contract.')
            if (finding.work_id != self.work_id or finding.handoff_id != self.handoff_id
                    or finding.inputs != self.inputs):
                raise ValueError('Finding scope must match handoff.')
            if finding.finding_id in identities:
                raise ValueError('Duplicate finding identity.')
            identities.add(finding.finding_id)

    def to_payload(self):
        return {'handoff_id': str(self.handoff_id), 'work_id': str(self.work_id),
                'expected_version': self.expected_version, 'ownership_fence': self.ownership_fence,
                'consumer_ref': self.consumer_ref, 'inputs': self.inputs.to_payload(),
                'observation_sources': [{'observation_id': str(o), 'source_id': str(s)}
                                        for o, s in self.observation_sources],
                'outcome_ids': [str(v) for v in self.outcome_ids], 'claim_ids': [str(v) for v in self.claim_ids],
                'result': self.result, 'limitations': list(self.limitations),
                'open_questions': list(self.open_questions), 'findings': [v.to_payload() for v in self.findings],
                'occurred_at': self.occurred_at.isoformat() if self.occurred_at else None,
                'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None}
