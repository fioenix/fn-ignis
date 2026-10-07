"""T065 measured layout over recorded research plus synthetic long-content stress."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from tests.integration import test_mission_relay_research_browser as research
from tests.integration.test_mission_relay_accessibility import _assert_visible_focus, _tab_to
from tests.integration.test_mission_relay_browser import FixtureViewer, RESPONSIBILITIES

relay_case = research.relay_case
recorded_research = research.recorded_research
research_browser = research.research_browser
EVIDENCE = Path(__file__).resolve().parents[2] / '.handoff/spec014/t065'
LONG_TOKEN = 'RecordedIdentity' * 24
LONG_TEXT = ('Recorded fixture detail with explicit limitations. ' * 12) + LONG_TOKEN


def _assert_layout(page):
    from playwright.sync_api import expect
    for name in ('Pause refresh', 'Pause motion', 'First evidence page', 'Next evidence page'):
        expect(page.get_by_role('button', name=name, exact=True)).to_be_visible()
    measured = page.evaluate("""() => {
        const visible = node => node.getClientRects().length > 0;
        const nodes = [...document.querySelectorAll('button, summary, .inspector p, .inspector h4, .identity, .timeline p')].filter(visible);
        const clippedByAncestor = node => {
            const rect = node.getBoundingClientRect();
            for (let parent = node.parentElement; parent; parent = parent.parentElement) {
                const style = getComputedStyle(parent), bounds = parent.getBoundingClientRect();
                if (['hidden', 'clip'].includes(style.overflowY) && (rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1)) return true;
                if (['hidden', 'clip'].includes(style.overflowX) && (rect.left < bounds.left - 1 || rect.right > bounds.right + 1)) return true;
            }
            return false;
        };
        const clipped = nodes.filter(node => {
            const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
            return rect.left < -1 || rect.right > innerWidth + 1 ||
                node.scrollWidth > node.clientWidth + 1 || node.scrollHeight > node.clientHeight + 1 ||
                style.textOverflow === 'ellipsis' || clippedByAncestor(node);
        }).map(node => node.tagName + ':' + node.textContent.slice(0, 80));
        return {width: innerWidth, document: document.documentElement.scrollWidth,
            controls: nodes.filter(node => ['BUTTON', 'SUMMARY'].includes(node.tagName)).length, clipped};
    }""")
    assert measured['document'] <= measured['width'], 'Responsive document overflows horizontally.'
    assert measured['controls'] >= 10, 'Responsive layout lost essential controls.'
    assert measured['clipped'] == [], f"Responsive essential content is clipped: {measured['clipped']}"
    return measured


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('width', (390, 768, 1440))
def test_recorded_research_and_long_evidence_retain_keyboard_controls_without_clipping(
    research_browser, recorded_research, width,
):
    """Projection stress is synthetic; identities/counts originate from actual SQLite."""
    from playwright.sync_api import expect
    snapshot, _, _ = recorded_research
    first = replace(snapshot.evidence[0], title=LONG_TOKEN, excerpt=LONG_TEXT)
    findings = tuple(replace(row, statement=LONG_TEXT, alternative_explanation=LONG_TOKEN,
                             limitations=(LONG_TEXT,)) for row in snapshot.research.findings)
    handoffs = tuple(replace(row, result=LONG_TEXT, limitations=(LONG_TEXT,)) for row in snapshot.research.handoffs)
    work = tuple(replace(row, question=LONG_TEXT) for row in snapshot.research.work_items)
    stressed = replace(snapshot, evidence=(first, *snapshot.evidence[1:]),
                       research=replace(snapshot.research, findings=findings, handoffs=handoffs, work_items=work))
    assert findings and handoffs and work, 'Responsive research fixture has no recorded work/results.'
    viewer = FixtureViewer(research_browser, stressed)
    try:
        page = viewer.page
        page.set_viewport_size({'width': width, 'height': 1000})
        page.emulate_media(reduced_motion='reduce')
        viewer.open()
        for name in RESPONSIBILITIES:
            button = page.get_by_role('button', name=name, exact=True)
            _tab_to(page, button)
            _assert_visible_focus(button)
            page.keyboard.press('Enter')
            expect(page.get_by_test_id('stage-inspector').get_by_role('heading', name=name, exact=True)).to_be_visible()
            _assert_layout(page)
        _tab_to(page, page.get_by_role('button', name='Sources', exact=True))
        page.keyboard.press('Enter')
        selected = page.get_by_test_id('stage-inspector').get_by_role('button', name=LONG_TOKEN, exact=True)
        _tab_to(page, selected)
        _assert_visible_focus(selected)
        page.keyboard.press('Enter')
        inspector = page.get_by_test_id('stage-inspector')
        expect(inspector.get_by_role('heading', name='Evidence inspection', exact=True)).to_be_visible()
        for fact in (LONG_TOKEN, LONG_TEXT, str(first.observation_id), str(first.source_id)):
            expect(inspector).to_contain_text(fact)
        _assert_layout(page)
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(EVIDENCE / f'evidence-{width}.png'), full_page=True)
        _tab_to(page, page.get_by_role('button', name='Research', exact=True))
        page.keyboard.press('Enter')
        for summary in inspector.locator('summary').all():
            _tab_to(page, summary)
            _assert_visible_focus(summary)
            page.keyboard.press('Enter')
            assert summary.evaluate('node => node.parentElement.open'), 'Keyboard inspection did not expand recorded details.'
        expect(inspector.get_by_test_id('research-observation-count')).to_have_text(str(len({observation for observation, source in snapshot.research.observation_sources})))
        expect(inspector.get_by_test_id('research-source-count')).to_have_text(str(len({source for observation, source in snapshot.research.observation_sources})))
        expect(inspector).to_contain_text(LONG_TEXT)
        for assignment in stressed.research.assignments:
            expect(inspector.locator(f'[data-assignment-id="{assignment.assignment_id}"]')).to_be_visible()
        for row in work:
            expect(inspector.locator(f'[data-work-id="{row.work_id}"]')).to_be_visible()
        for row in handoffs:
            record = inspector.locator(f'[data-handoff-id="{row.handoff_id}"]')
            expect(record).to_be_visible()
            expect(record).to_contain_text(LONG_TEXT)
        for row in findings:
            record = inspector.locator(f'[data-finding-id="{row.finding_id}"]')
            expect(record).to_be_visible()
            expect(record).to_contain_text(LONG_TEXT)
        measured = _assert_layout(page)
        page.screenshot(path=str(EVIDENCE / f'research-{width}.png'), full_page=True)
        (EVIDENCE / f'layout-{width}.json').write_text(json.dumps(measured, indent=2) + '\n')
        assert not viewer.unexpected, 'Responsive inspection attempted an out-of-scope route.'
        assert all(method == 'GET' for method, path in viewer.requests), 'Responsive viewing invoked a mission write.'
    finally:
        viewer.close()
