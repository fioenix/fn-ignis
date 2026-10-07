"""Immutable masked research view; no raw snapshot serializer crosses this boundary."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ignis.domain.research_work import ResearchAssignment, ResearchWorkItem, ResearchActivityReceipt
from ignis.domain.research_findings import ResearchFindingRevision, ResearchHandoff


@dataclass(frozen=True, slots=True, kw_only=True)
class RelayResearchView:
    availability: str = 'SCHEMA_UNAVAILABLE'
    read_at: datetime | None = None
    mission_id: UUID | None = None
    current_run_id: UUID | None = None
    frame_digest: str | None = None
    revision: int | None = None
    current_epoch: int | None = None
    assignments: tuple[ResearchAssignment, ...] = ()
    work_items: tuple[ResearchWorkItem, ...] = ()
    handoffs: tuple[ResearchHandoff, ...] = ()
    findings: tuple[ResearchFindingRevision, ...] = ()
    acknowledgements: tuple[tuple[UUID, str, int, str, str | None], ...] = ()
    observation_sources: tuple[tuple[UUID, UUID], ...] = ()
    current_finding_revisions: tuple[tuple[UUID, int], ...] = ()
    withheld_findings: tuple[tuple[UUID, int], ...] = ()
    withheld_handoffs: tuple[UUID, ...] = ()
    activities: tuple[tuple[UUID, str, ResearchActivityReceipt | None], ...] = ()
    recorded_metadata: tuple[tuple[str, UUID, int, int, datetime, str], ...] = ()
    reasons: tuple[tuple[UUID, str | None], ...] = ()

    def __post_init__(self):
        if self.availability not in ('AVAILABLE', 'SCHEMA_UNAVAILABLE'):
            raise ValueError('Invalid research availability.')
        if self.availability == 'SCHEMA_UNAVAILABLE':
            if self.read_at is not None or self.current_run_id is not None or self.frame_digest is not None or self.mission_id is not None or self.revision is not None or self.current_epoch is not None or any(
                getattr(self, name) for name in ('assignments', 'work_items', 'handoffs', 'findings',
                'acknowledgements', 'observation_sources', 'current_finding_revisions', 'withheld_findings',
                'withheld_handoffs', 'activities', 'recorded_metadata', 'reasons')
            ):
                raise ValueError('Unavailable research must remain unknown.')
            return
        if type(self.mission_id) is not UUID or type(self.revision) is not int or self.revision < 0:
            raise ValueError('Invalid research read identity.')
        if type(self.read_at) is not datetime or self.read_at.tzinfo is None:
            raise ValueError('Invalid research read time.')
        if self.current_run_id is not None and type(self.current_run_id) is not UUID:
            raise ValueError('Invalid research run identity.')
        if type(self.current_epoch) is not int or self.current_epoch < 0:
            raise ValueError('Invalid research epoch.')
        for name, cls in (('assignments', ResearchAssignment), ('work_items', ResearchWorkItem),
                          ('handoffs', ResearchHandoff), ('findings', ResearchFindingRevision)):
            rows = getattr(self, name)
            if type(rows) is not tuple or len(rows) > 10000 or any(type(row) is not cls for row in rows):
                raise ValueError('Invalid exact research projection record.')
        if any(r.mission_id != self.mission_id for r in (*self.assignments, *self.work_items)):
            raise ValueError('Foreign research work identity.')
        if any(r.inputs.mission_id != self.mission_id for r in (*self.handoffs, *self.findings)):
            raise ValueError('Foreign research result identity.')
        for name in ('acknowledgements', 'observation_sources', 'current_finding_revisions',
                     'withheld_findings', 'withheld_handoffs', 'activities', 'recorded_metadata', 'reasons'):
            if type(getattr(self, name)) is not tuple or len(getattr(self, name)) > 10000:
                raise ValueError('Invalid bounded research projection collection.')
        work_ids = {w.work_id for w in self.work_items}
        for identity, state, receipt in self.activities:
            if identity not in work_ids or type(state) is not str or receipt is not None and type(receipt) is not ResearchActivityReceipt:
                raise ValueError('Invalid exact research activity projection.')
        required = {('ASSIGNMENT', a.assignment_id, a.version) for a in self.assignments}
        required |= {('WORK', w.work_id, w.version) for w in self.work_items}
        required |= {('HANDOFF', h.handoff_id, 1) for h in self.handoffs}
        required |= {('FINDING', f.finding_id, f.revision) for f in self.findings}
        keys = []
        for kind, identity, version, revision, recorded_at, provenance in self.recorded_metadata:
            if type(identity) is not UUID or type(version) is not int or type(revision) is not int or not 1 <= revision <= self.revision:
                raise ValueError('Invalid observed research metadata identity.')
            if type(recorded_at) is not datetime or recorded_at.tzinfo is None or provenance != 'HARNESS_OBSERVED':
                raise ValueError('Invalid observed research metadata provenance/time.')
            keys.append((kind, identity, version))
        if len(set(keys)) != len(keys) or not required <= set(keys):
            raise ValueError('Missing or duplicate research metadata.')
        if len(dict(self.observation_sources)) != len(self.observation_sources):
            raise ValueError('Duplicate research observation identity.')

    def to_payload(self):
        if self.availability != 'AVAILABLE':
            return {'availability': self.availability}
        latest = {}
        for finding in self.findings:
            latest[finding.finding_id] = max(latest.get(finding.finding_id, 0), finding.revision)
        times = {(kind, identity, version): (recorded, provenance)
                 for kind, identity, version, _, recorded, provenance in self.recorded_metadata}
        findings = []
        for finding in self.findings:
            row = finding.to_payload()
            key = (finding.finding_id, finding.revision)
            withheld = key in self.withheld_findings
            if withheld:
                row.update(statement=None, limitations=[], open_questions=[], alternative_explanation=None)
            time, provenance = times[('FINDING', *key)]
            row['submitted_recorded_at'] = row['recorded_at']
            row['narrative_origin'] = 'WITHHELD' if withheld else 'CURRENT_CLAIM_LEDGER' if finding.result_type == 'STRATEGIC_CANDIDATE' else 'SOURCE_BOUND_DESCRIPTIVE'
            row.update(latest_recorded=latest[finding.finding_id] == finding.revision,
                       current_eligible=key in self.current_finding_revisions,
                       text_withheld=withheld, recorded_at=time.isoformat(), recorded_provenance=provenance)
            findings.append(row)
        handoffs = []
        for handoff in self.handoffs:
            row = handoff.to_payload()
            withheld = handoff.handoff_id in self.withheld_handoffs
            if withheld:
                row.update(result=None, limitations=[], open_questions=[])
            row['findings'] = [f for f in findings if f['handoff_id'] == str(handoff.handoff_id)]
            row['text_withheld'] = withheld
            time, provenance = times[('HANDOFF', handoff.handoff_id, 1)]
            row['submitted_recorded_at'] = row['recorded_at']
            row.update(recorded_at=time.isoformat(), recorded_provenance=provenance)
            handoffs.append(row)
        works = []
        for work in self.work_items:
            row = work.to_payload()
            activity, receipt = next(((s, r) for i, s, r in self.activities if i == work.work_id), ('UNKNOWN', None))
            row['reason_code'] = dict(self.reasons).get(work.work_id)
            row['activity'] = {'state': activity, 'provenance': 'HOST_REPORTED' if receipt else None,
                               'receipt': receipt.to_payload() if receipt else None}
            time, provenance = times[('WORK', work.work_id, work.version)]
            row.update(recorded_at=time.isoformat(), recorded_provenance=provenance)
            works.append(row)
        assignments = []
        for assignment in self.assignments:
            row = assignment.to_payload()
            time, provenance = times[('ASSIGNMENT', assignment.assignment_id, assignment.version)]
            row.update(recorded_at=time.isoformat(), recorded_provenance=provenance,
                       capability_provenance='HOST_REPORTED' if assignment.capability else None,
                       authority_state='EXPIRED' if self.read_at >= assignment.authority.deadline else assignment.state)
            assignments.append(row)
        return {'availability': self.availability, 'mission_id': str(self.mission_id),
                'revision': self.revision, 'current_epoch': self.current_epoch,
                'scope': 'MISSION_CURRENT', 'current_run_id': str(self.current_run_id) if self.current_run_id else None,
                'frame_digest': self.frame_digest,
                'capacity': None,
                'assignments': assignments, 'work_items': works,
                'handoffs': handoffs, 'findings': findings,
                'acknowledgements': [{'handoff_id': str(i), 'consumer_ref': c, 'expected_version': v,
                                     'disposition': d, 'reason_code': r} for i, c, v, d, r in self.acknowledgements],
                'recorded_metadata': [{'record_kind': k, 'record_id': str(i), 'record_version': v,
                                       'mission_revision': rev, 'recorded_at': t.isoformat(), 'provenance': p}
                                      for k, i, v, rev, t, p in self.recorded_metadata],
                'observation_sources': [{'observation_id': str(o), 'source_id': str(s)} for o, s in self.observation_sources],
                'observation_count': len(self.observation_sources),
                'source_count': len({s for _, s in self.observation_sources}),
                'latest_finding_revisions': [{'finding_id': str(i), 'revision': r} for i, r in latest.items()],
                'current_finding_revisions': [{'finding_id': str(i), 'revision': r} for i, r in self.current_finding_revisions]}
