"""Maintained viewer renders stored permission and actual gaps, never labels as authority."""
from dataclasses import replace

from playwright.sync_api import expect
from ignis.domain.mission_relay import RelayClaimGate, RelayGateState
from ignis.domain.research_workspace import ClaimStatus, GapReport
from test_mission_relay_browser import (
    _us3_permitted_snapshot, _viewer, installed_browser,  # noqa: F401 -- pytest fixture
)


def test_current_ledger_displays_exact_bindings_and_limits(installed_browser):  # noqa: F811 -- imported fixture
    snapshot = _us3_permitted_snapshot()
    claim = replace(snapshot.claim_gate.claims[0], limitations=('Fixture sample only',),
                    change_conditions=('New contradiction changes this statement',))
    snapshot = replace(snapshot, claim_gate=replace(snapshot.claim_gate, claims=(claim,)))
    with _viewer(installed_browser, snapshot) as viewer:
        viewer.page.get_by_role('button', name='Synthesis', exact=True).click()
        assert 'Current strategic permission withheld until' not in viewer.page.locator('nav').inner_text()
        region = viewer.page.get_by_test_id('current-claims')
        for text in (claim.wording, str(claim.claim_id), claim.frame_digest,
                     str(claim.evidence_bindings[0].observation_id), 'SUPPORT',
                     'Fixture sample only', 'New contradiction changes this statement'):
            expect(region).to_contain_text(text)
        expect(viewer.page.get_by_test_id('claim-history')).not_to_contain_text(claim.wording)


def test_actual_gap_and_provisional_history_do_not_grant_permission(installed_browser):  # noqa: F811 -- imported fixture
    snapshot = _us3_permitted_snapshot()
    history = replace(snapshot.claim_gate.claims[0], status=ClaimStatus.SUPERSEDED,
                      wording='Provisional descriptive fixture wording')
    gap = GapReport(withheld_outputs=('commercial_recommendations',), failed_gates=('qualifications_missing',),
                    missing_evidence=('A recorded contradiction',), attempted_probes=(),
                    safe_partial_conclusions=('Recorded sample only',), next_best_probe='Qualify the selected contradiction',
                    required_authority='Owner-confirmed probe', estimated_cost='No new collection yet')
    snapshot = replace(snapshot, claim_gate=RelayClaimGate(state=RelayGateState.STALE,
        frame_digest=snapshot.frame_digest, history=(history,), gap_report=gap, reason_code='INSUFFICIENT_EVIDENCE'))
    with _viewer(installed_browser, snapshot) as viewer:
        viewer.page.get_by_role('button', name='Synthesis', exact=True).click()
        expect(viewer.page.get_by_test_id('current-claims')).to_be_empty()
        expect(viewer.page.get_by_test_id('claim-history')).to_contain_text(history.wording)
        region = viewer.page.get_by_test_id('gap-report')
        for text in (*gap.failed_gates, *gap.missing_evidence, gap.next_best_probe,
                     gap.required_authority, gap.estimated_cost, *gap.withheld_outputs):
            expect(region).to_contain_text(text)
        assert 'PERMITTED' not in viewer.page.get_by_test_id('current-claims').inner_text()


def test_no_script_gap_preserves_authority_cost_and_withheld_outputs():
    from test_mission_relay_browser import _render
    snapshot = _us3_permitted_snapshot()
    gap = GapReport(withheld_outputs=('commercial_recommendations',), failed_gates=('qualifications_missing',),
        missing_evidence=('A recorded contradiction',), attempted_probes=({'connector_surface': 'youtube', 'status': 'DEGRADED', 'signals_collected': 0},),
        safe_partial_conclusions=('Recorded sample only',), next_best_probe='Qualify the selected contradiction',
        required_authority='Owner-confirmed probe', estimated_cost='No new collection yet')
    snapshot = replace(snapshot, claim_gate=RelayClaimGate(state=RelayGateState.STALE,
        frame_digest=snapshot.frame_digest, gap_report=gap, reason_code='INSUFFICIENT_EVIDENCE'))
    fallback = _render(snapshot).split('<noscript>', 1)[1].split('</noscript>', 1)[0]
    for value in (*gap.withheld_outputs, *gap.failed_gates, *gap.missing_evidence,
                  *gap.safe_partial_conclusions, gap.next_best_probe, gap.required_authority,
                  gap.estimated_cost, 'youtube', 'DEGRADED'):
        assert value in fallback


def test_permitted_offline_ledger_fits_narrow_viewport(installed_browser):  # noqa: F811 -- imported fixture
    from test_mission_relay_browser import _render, DOCUMENT_URL
    snapshot = _us3_permitted_snapshot()
    # Chromium disables execution without changing the parser scripting flag.
    # Activate only the maintained fallback wrapper to measure its actual layout.
    document = _render(snapshot).replace('<noscript>', '<section>').replace('</noscript>', '</section>')
    context = installed_browser.new_context(java_script_enabled=False, viewport={'width': 390, 'height': 900})
    context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=document)
                  if route.request.url == DOCUMENT_URL else route.abort())
    try:
        page = context.new_page()
        page.goto(DOCUMENT_URL)
        expect(page.get_by_role('region', name='Recorded strategic ledger')).to_contain_text(snapshot.claim_gate.claims[0].wording)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Offline permitted facts overflow the viewport'
    finally:
        context.close()
