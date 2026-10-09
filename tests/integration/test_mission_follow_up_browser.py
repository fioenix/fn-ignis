"""T078 maintained-browser controls for inert historical child references."""

from dataclasses import replace
from uuid import UUID

import pytest

from ignis.domain.mission_relay import RelayRelatedResult, RelayClaimGate, RelayGateState, RelayCollectionState
from ignis.domain.research_workspace import GapReport
from tests.integration.test_mission_relay_browser import (
    _snapshot, _viewer, _render, _observation, _us3_permitted_snapshot, installed_browser,
)

CHILD = UUID(int=7801)
CHILD_RUN = UUID(int=7802)
FINDING = UUID(int=7803)
HISTORICAL_FRAME = 'b' * 64


def _related_snapshot(*, known=True):
    # Exercise the accepted six-field projection, not an invented UI/backend API.
    row = RelayRelatedResult(mission_id=CHILD, run_id=CHILD_RUN if known else None,
        frame_digest=HISTORICAL_FRAME if known else None,
        finding_references=((FINDING, 2),) if known else ())
    return _snapshot(related_results=(row,), related_results_total=1)


def test_recorded_child_scope_is_visible_without_inheriting_parent_authority(installed_browser):
    """Existing maintained DOM lacks related metadata: genuine missing-render RED."""
    with _viewer(installed_browser, _related_snapshot()) as viewer:
        page = viewer.page
        # The existing aside is already present before T078; no future seam setup.
        context = page.get_by_test_id('synthesis-context')
        assert str(CHILD) in context.inner_text(), 'Recorded admitted child reference is missing.'
        related = page.get_by_test_id('related-results')
        for exact in (str(CHILD), str(CHILD_RUN), HISTORICAL_FRAME, str(FINDING), 'revision 2'):
            assert exact in related.inner_text()
        assert 'Recorded historical scope' in related.inner_text()
        assert 'SELECT_CHILD_REQUIRED' in related.inner_text()
        assert 'independently authorized' in related.inner_text()
        assert related.locator('a, button, input, form').count() == 0
        assert 'PERMITTED' not in related.inner_text() and 'COMPLETED' not in related.inner_text()
        assert viewer.packets == []
        assert all(method == 'GET' and str(CHILD) not in path for method, path in viewer.requests)
        viewer.counts(0, 0)


def test_unknown_and_measured_empty_child_coverage_are_distinct(installed_browser):
    with _viewer(installed_browser, _related_snapshot(known=False)) as viewer:
        related = viewer.page.get_by_test_id('related-results')
        assert str(CHILD) in related.inner_text()
        assert 'Unknown' in related.inner_text()
        assert str(CHILD_RUN) not in related.inner_text() and HISTORICAL_FRAME not in related.inner_text()
        viewer.refresh(_snapshot(related_results_total=0))
        assert related.get_by_test_id('related-results-coverage').inner_text() == 'AVAILABLE · 0'
        assert str(CHILD) not in related.inner_text()
        viewer.refresh(_snapshot())
        assert 'SCHEMA_UNAVAILABLE' in related.inner_text() and 'Unknown' in related.inner_text()
        assert 'AVAILABLE · 0' not in related.inner_text()


@pytest.mark.parametrize('poison', ('mission', 'relation', 'permission', 'scope', 'coverage'))
def test_malformed_child_refresh_withdraws_reference_without_html_or_child_fetch(installed_browser, poison):
    with _viewer(installed_browser, _related_snapshot()) as viewer:
        page = viewer.page
        assert str(CHILD) in page.get_by_test_id('synthesis-context').inner_text()
        poisoned = _related_snapshot().to_payload()
        row = poisoned['related_results'][0]
        if poison == 'mission':
            row['mission_id'] = '<img src=x onerror="window.childExecuted=1">'
        elif poison == 'relation':
            row['relation'] = 'CURRENT_CHILD_RESULT'
        elif poison == 'permission':
            row['inspection_status'] = 'PERMITTED'
        elif poison == 'scope':
            row['run_id'] = None
        else:
            poisoned['related_results_coverage']['total'] = 0
        identity_fields = ('mission-identity', 'run-identity', 'frame-identity', 'manifest-identity', 'read-receipt')
        parent_identity = {field: page.get_by_test_id(field).inner_text() for field in identity_fields}
        page.route('**/snapshot?**', lambda route: route.fulfill(status=200, json=poisoned))
        with page.expect_response(lambda response: '/snapshot?' in response.url):
            page.clock.run_for(2100)
        page.get_by_test_id('snapshot-state').filter(has_text='Stale').wait_for()
        related = page.get_by_test_id('related-results')
        assert 'Unknown' in related.inner_text() and str(CHILD) not in related.inner_text()
        assert related.locator('img, a, button, form').count() == 0
        assert page.evaluate('window.childExecuted === undefined')
        assert all(method == 'GET' and str(CHILD) not in path for method, path in viewer.requests)
        assert viewer.packets == []
        assert {field: page.get_by_test_id(field).inner_text() for field in identity_fields} == parent_identity
        viewer.counts(0, 0)


def test_gap_return_keeps_terminal_parent_and_requires_own_child_inspection(installed_browser):
    parent = _us3_permitted_snapshot()
    gap = GapReport(withheld_outputs=('commercial_recommendations',), failed_gates=('qualifications_missing',),
        missing_evidence=('Recorded contradiction missing',), attempted_probes=(),
        safe_partial_conclusions=('Recorded sample only',), next_best_probe='Qualify selected evidence',
        required_authority='Separate owner confirmation', estimated_cost='Unknown')
    parent = replace(parent, collection_state=RelayCollectionState.COMPLETED,
        claim_gate=RelayClaimGate(state=RelayGateState.CURRENT, frame_digest=parent.frame_digest,
            gap_report=gap, reason_code='INSUFFICIENT_EVIDENCE'),
        related_results=_related_snapshot().related_results, related_results_total=1)
    with _viewer(installed_browser, parent) as viewer:
        page = viewer.page
        page.get_by_role('button', name='Synthesis', exact=True).click()
        assert gap.next_best_probe in page.get_by_test_id('gap-report').inner_text()
        assert page.get_by_test_id('current-claims').inner_text() == ''
        assert str(CHILD) in page.get_by_test_id('related-results').inner_text()
        assert str(parent.mission_id) in page.get_by_test_id('mission-authority').inner_text()
        assert parent.frame_digest in page.get_by_test_id('frame-identity').inner_text()
        assert 'COMPLETED' in page.get_by_test_id('mission-authority').inner_text()
        viewer.counts(1, 1)
        assert all(str(CHILD) not in path for _, path in viewer.requests)
    # Independently selected typed child scope, not a parent-reference navigation.
    observation = replace(_observation(), mission_id=CHILD)
    base = _snapshot()
    watermark = replace(base.high_water, mission_id=CHILD)
    child = replace(base, mission_id=CHILD, run_id=CHILD_RUN, high_water=watermark,
        event_page=replace(base.event_page, high_water=watermark), evidence=(observation,),
        total_observations=1, source_count=1, related_results_total=0)
    with _viewer(installed_browser, child) as viewer:
        button = viewer.page.get_by_test_id('network-observation')
        assert button.count() == 1
        assert button.get_attribute('data-network-observation-id') == str(observation.observation_id)
        assert button.get_attribute('data-network-source-id') == str(observation.source_id)
        with viewer.page.expect_response(lambda response: '/inspect/' in response.url):
            button.click()
        assert str(observation.observation_id) in viewer.page.get_by_test_id('stage-inspector').inner_text()
        assert str(CHILD) in viewer.page.get_by_test_id('mission-authority').inner_text()
        assert any(path.endswith('/inspect/' + str(observation.observation_id)) for _, path in viewer.requests)


def test_child_identity_fallback_and_narrow_reduced_motion_layout(installed_browser):
    snapshot = _related_snapshot()
    fallback = _render(snapshot).split('<noscript>', 1)[1].split('</noscript>', 1)[0]
    for value in (str(CHILD), str(CHILD_RUN), HISTORICAL_FRAME, str(FINDING), 'revision 2', 'SELECT_CHILD_REQUIRED'):
        assert value in fallback
    with _viewer(installed_browser, snapshot) as viewer:
        page = viewer.page
        page.set_viewport_size({'width': 390, 'height': 900})
        page.emulate_media(reduced_motion='reduce')
        assert str(CHILD) in page.get_by_test_id('related-results').inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.get_by_role('button', name='Inspect Synthesis details', exact=True).focus()
        page.keyboard.press('Enter')
        assert page.get_by_test_id('stage-inspector').get_by_role('heading', name='Synthesis', exact=True).is_visible()
        assert viewer.packets == []
