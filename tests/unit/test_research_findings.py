"""Direct immutable result contracts, independently of future storage APIs."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
import importlib
import json
from uuid import UUID

import pytest

from ignis.domain.research_work import ResearchInputBindings


IDS = tuple(UUID(int=i) for i in range(1, 10))
NOW = datetime(2026, 10, 6, tzinfo=timezone.utc)


def models():
    try:
        return importlib.import_module('ignis.domain.research_findings')
    except ModuleNotFoundError:
        pytest.fail('T044 contract missing: research_findings constructors')


def records():
    domain = models()
    inputs = ResearchInputBindings(mission_id=IDS[0], manifest_digest='a' * 64,
        brief_digest=None, frame_digest=None, observation_ids=IDS[1:4], finding_revisions=())
    finding = domain.ResearchFindingRevision(finding_id=IDS[4], revision=1, predecessor_revision=None,
        work_id=IDS[5], handoff_id=IDS[6], inputs=inputs, result_type='DESCRIPTIVE',
        statement='Observed differences', limitations=('Bounded sample',), open_questions=('Repeat?',),
        supporting_observation_ids=(IDS[1],), contradicting_observation_ids=(IDS[2],),
        context_observation_ids=(IDS[3],), alternative_explanation='Sampling variation', claim_id=None)
    handoff = domain.ResearchHandoff(handoff_id=IDS[6], work_id=IDS[5], expected_version=2,
        ownership_fence='fence-1', consumer_ref='consumer-1', inputs=inputs,
        observation_sources=tuple((o, IDS[7]) for o in IDS[1:4]), outcome_ids=(), claim_ids=(),
        result='Observed differences', limitations=('Bounded sample',), open_questions=('Repeat?',),
        findings=(finding,), occurred_at=NOW)
    return finding, handoff


def test_pending_frame_and_counterevidence_survive_explicit_serialization():
    finding, handoff = records()
    payload = handoff.to_payload()
    assert payload['inputs']['frame_digest'] is None
    assert payload['inputs']['brief_digest'] is None
    assert payload['observation_sources'] == [
        {'observation_id': str(IDS[i]), 'source_id': str(IDS[7])} for i in (1, 2, 3)]
    assert payload['findings'][0]['supporting_observation_ids'] == [str(IDS[1])]
    assert payload['findings'][0]['contradicting_observation_ids'] == [str(IDS[2])]
    assert payload['findings'][0]['context_observation_ids'] == [str(IDS[3])]
    assert payload['findings'][0]['alternative_explanation'] == 'Sampling variation'
    assert payload['recorded_at'] is None and payload['findings'][0]['recorded_at'] is None
    assert payload['occurred_at'] == '2026-10-06T00:00:00+00:00'
    json.dumps(payload)
    payload['findings'][0]['limitations'].append('Changed')
    assert finding.limitations == ('Bounded sample',)
    with pytest.raises(FrozenInstanceError):
        handoff.result = 'Changed'


@pytest.mark.parametrize('changes', [
    {'supporting_observation_ids': (IDS[8],)},
    {'contradicting_observation_ids': (IDS[2], IDS[2])},
    {'context_observation_ids': [IDS[3]]},
    {'result_type': 'PERMITTED'}, {'revision': True},
    {'predecessor_revision': 1}, {'revision': 2, 'predecessor_revision': None},
    {'revision': 3, 'predecessor_revision': 1}, {'inputs': {}},
    {'limitations': ['Bounded sample']}, {'recorded_at': datetime(2026, 10, 6)},
])
def test_finding_rejects_malformed_bindings(changes):
    finding, _ = records()
    with pytest.raises(ValueError):
        replace(finding, **changes)


@pytest.mark.parametrize('changes', [
    {'observation_sources': ((IDS[1], IDS[7]),) },
    {'observation_sources': ((IDS[1], IDS[7]), (IDS[1], IDS[8]), (IDS[3], IDS[7]))},
    {'observation_sources': ((IDS[1], 'source'), (IDS[2], IDS[7]), (IDS[3], IDS[7]))},
    {'observation_sources': ((IDS[1], IDS[7], IDS[8]),)},
    {'observation_sources': [[IDS[1], IDS[7]]]},
    {'expected_version': True}, {'outcome_ids': (IDS[8], IDS[8])},
    {'findings': () , 'inputs': {}}, {'occurred_at': datetime(2026, 10, 6)},
])
def test_handoff_rejects_malformed_exact_bindings(changes):
    _, handoff = records()
    with pytest.raises(ValueError):
        replace(handoff, **changes)


@pytest.mark.parametrize('field,value', [('work_id', IDS[8]), ('handoff_id', IDS[8]),
    ('inputs', ResearchInputBindings(mission_id=IDS[0], manifest_digest='b' * 64,
        brief_digest=None, frame_digest=None, observation_ids=IDS[1:4], finding_revisions=()))])
def test_handoff_rejects_finding_scope_substitution(field, value):
    finding, handoff = records()
    with pytest.raises(ValueError):
        replace(handoff, findings=(replace(finding, **{field: value}),))


def test_duplicate_finding_revision_is_refused():
    finding, handoff = records()
    with pytest.raises(ValueError):
        replace(handoff, findings=(finding, finding))


def test_strategic_candidate_and_successor_do_not_grant_permission():
    finding, handoff = records()
    successor = replace(finding, revision=2, predecessor_revision=1,
        result_type='STRATEGIC_CANDIDATE', claim_id=IDS[8], recorded_at=NOW)
    payload = replace(handoff, findings=(successor,), claim_ids=(IDS[8],), recorded_at=NOW).to_payload()
    assert payload['findings'][0]['revision'] == 2
    assert payload['findings'][0]['predecessor_revision'] == 1
    assert payload['findings'][0]['result_type'] == 'STRATEGIC_CANDIDATE'
    assert payload['findings'][0]['claim_id'] == str(IDS[8])
    assert 'permission' not in payload['findings'][0]
    assert 'confidence' not in payload['findings'][0]
    assert handoff.recorded_at is None and finding.recorded_at is None


def test_arbitrary_fields_are_not_accepted():
    finding, handoff = records()
    with pytest.raises(TypeError):
        replace(finding, prompt='private')
    with pytest.raises(TypeError):
        replace(handoff, payload={})
