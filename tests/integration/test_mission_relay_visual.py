"""T066 rejects the oversized header and disconnected card observatory."""

import pytest

from ignis.domain.mission_relay import MissionRelaySnapshot
from playwright.sync_api import expect

from tests.integration import test_mission_relay_browser as browser
from tests.integration import test_mission_relay_research_browser as research
from tests.integration.test_mission_relay_accessibility import _assert_visible_focus, _tab_to
from tests.integration.test_mission_relay_browser import FixtureViewer

relay_case = research.relay_case
recorded_research = research.recorded_research
research_browser = research.research_browser


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('width', (390, 768, 1440))
def test_compact_persistent_authority_leaves_network_as_primary_surface(
    research_browser, recorded_research, width,
):
    """Reject the original authority card consuming the first viewport."""
    snapshot, _, _ = recorded_research
    viewer = FixtureViewer(research_browser, snapshot)
    try:
        page = viewer.page
        page.set_viewport_size({'width': width, 'height': 1000})
        viewer.open()
        header = page.get_by_test_id('mission-authority')
        rect = header.bounding_box()
        assert rect['height'] <= (340 if width == 390 else 220), 'Authority dominates the network viewport.'
        expect(header.get_by_test_id('mission-identity')).to_have_text(str(snapshot.mission_id))
        expect(header.get_by_test_id('frame-identity')).to_be_visible()
        expect(header.get_by_test_id('read-receipt')).to_be_visible()
        page.get_by_test_id('stage-inspector').scroll_into_view_if_needed()
        assert 0 <= header.bounding_box()['y'] <= 2, 'Authority/freshness disappears during inspection.'
        viewer.counts(6, 6)
    finally:
        viewer.close()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('width', (390, 768, 1440))
def test_connected_recorded_network_and_adjacent_synthesis_have_real_identities(
    research_browser, recorded_research, width,
):
    """Reject isolated selectors and synthetic specialist/finding substitutes."""
    snapshot, _, _ = recorded_research
    viewer = FixtureViewer(research_browser, snapshot)
    try:
        page = viewer.page
        page.set_viewport_size({'width': width, 'height': 1000})
        page.emulate_media(reduced_motion='reduce')
        viewer.open()
        stages = page.get_by_role('navigation', name='Evidence responsibilities')
        assert stages.bounding_box()['height'] >= 340, 'Selectors replace the dominant research network.'
        graph = page.get_by_test_id('research-network')
        expect(graph.locator('svg')).to_be_visible()
        expect(graph.locator('path[data-link-kind="method"]')).to_have_count(4)
        work = snapshot.research.work_items[0]
        expect(graph.locator(f'[data-network-work-id="{work.work_id}"]')).to_have_count(1)
        expect(graph.get_by_test_id('network-work')).to_have_count(len(snapshot.research.work_items))
        for row in snapshot.evidence:
            expect(graph.locator(f'[data-network-observation-id="{row.observation_id}"][data-network-source-id="{row.source_id}"]')).to_have_count(1)
        # Recorded inputs are exact bindings, not an implied execution pipeline.
        for identity in work.inputs.observation_ids:
            if any(str(row.observation_id) == str(identity) for row in snapshot.evidence):
                expect(graph.locator(f'path[data-from="observation:{identity}"][data-to="work:{work.work_id}"]')).to_have_count(1)
        panel = page.get_by_test_id('synthesis-context')
        expect(panel).to_contain_text(snapshot.claim_gate.reason_code)
        finding = snapshot.research.findings[0]
        expect(panel.locator(f'[data-context-finding-id="{finding.finding_id}"]')).to_have_count(1)
        if width == 1440:
            network_rect, panel_rect = graph.bounding_box(), panel.bounding_box()
            assert panel_rect['x'] >= network_rect['x'] + network_rect['width'], 'Synthesis is stacked below the desktop network.'
            assert abs(panel_rect['y'] - network_rect['y']) < 5, 'Synthesis is detached from the research network.'
        selected = graph.get_by_test_id('network-work').first
        _tab_to(page, selected)
        _assert_visible_focus(selected)
        page.keyboard.press('Enter')
        expect(page.get_by_test_id('stage-inspector').get_by_role('heading', name='Research', exact=True)).to_be_visible()
        button = graph.get_by_test_id('network-observation').first
        button.click()
        inspector = page.get_by_test_id('stage-inspector')
        expect(inspector.get_by_role('heading', name='Evidence inspection', exact=True)).to_be_visible()
        expect(inspector).to_contain_text(str(snapshot.evidence[0].observation_id))
        expect(inspector).to_contain_text(str(snapshot.evidence[0].source_id))
        assert all(method == 'GET' for method, path in viewer.requests)
        assert not viewer.unexpected
        assert page.evaluate("document.getAnimations().filter(a => a.playState === 'running').length") == 0
    finally:
        viewer.close()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
def test_new_receipt_travels_between_visible_processing_layers(research_browser):
    """Reject a short unrelated packet strip outside the method network."""
    row = browser._observation()
    viewer = FixtureViewer(research_browser, browser._snapshot())
    try:
        page = viewer.page
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.emulate_media(reduced_motion='no-preference')
        viewer.open()
        viewer.refresh(browser._snapshot((row,), (browser._event(observations=(row,)),)))
        packet = page.get_by_test_id('relay-packet')
        expect(packet).to_have_count(1)
        geometry = packet.evaluate("""packet => {
            const rect = node => { const r = node.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
            const source = document.querySelector('[data-network-stage="Sources"]'), cleaning = document.querySelector('[data-network-stage="Cleaning"]');
            const animation = packet.getAnimations()[0], frames = animation.effect.getKeyframes();
            const last = new DOMMatrix(frames.at(-1).transform);
            const bounds = rect(packet), start = new DOMMatrix(getComputedStyle(packet).transform);
            return {source:rect(source), cleaning:rect(cleaning), bounds,
                startX:bounds.x-start.m41, startY:bounds.y-start.m42, dx:last.m41, dy:last.m42};
        }""")
        source, cleaning = geometry['source'], geometry['cleaning']
        assert packet.evaluate("""packet => {
            const r = packet.getBoundingClientRect();
            return packet.contains(document.elementFromPoint(r.x + r.width/2, r.y + r.height/2));
        }"""), 'A processing node paints over the moving receipt.'
        assert geometry['dx'] > 80, 'Receipt only moves within an unrelated arrival strip.'
        assert abs(geometry['startX'] - (source['x'] + source['width']/2)) < 4
        assert abs(geometry['startY'] - (source['y'] + source['height']/2)) < 4
        assert abs(geometry['startX'] + geometry['dx'] - (cleaning['x'] + cleaning['width']/2)) < 4
        expect(packet).to_have_attribute('data-observation-ids', '["' + str(row.observation_id) + '"]')
        page.get_by_role('button', name='Pause motion', exact=True).click()
        expect(page.get_by_test_id('relay-packet')).to_have_count(0)
        assert all(method == 'GET' for method, path in viewer.requests)
    finally:
        viewer.close()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('descriptive', 'strategic', 'withdrawn'), indirect=True)
def test_side_context_escapes_recorded_text_and_clears_currentness_on_failed_read(
    research_browser, recorded_research,
):
    """Reject executable finding markup or cached current narration after failure."""
    snapshot, fresh, _ = recorded_research
    viewer = FixtureViewer(research_browser, snapshot)
    try:
        page = viewer.page
        viewer.open()
        context = page.get_by_test_id('synthesis-context')
        expect(context.locator('img, script, b')).to_have_count(0)
        assert page.evaluate('window.untrustedExecuted !== true')
        finding = snapshot.to_payload()['research']['findings'][0]
        if not finding['text_withheld']:
            expect(context).to_contain_text(finding['statement'])
        expect(context).not_to_contain_text('UNPERMITTED_STRATEGIC_PROSE')
        expect(context).not_to_contain_text('UNLICENSED_CANDIDATE_PROSE')
        if isinstance(fresh, MissionRelaySnapshot):
            viewer.refresh(fresh)
            assert finding['statement'] is not None, 'Withdrawal control needs previously permitted text.'
            expect(context).not_to_contain_text(finding['statement'])
            expect(context).to_contain_text('Text withheld')
        viewer.context.route(browser.SNAPSHOT_URL + '?*', lambda route: route.fulfill(
            status=503, json={'status': 'UNAVAILABLE'},
        ))
        page.clock.run_for(2100)
        expect(page.get_by_test_id('context-gate')).to_contain_text('stale read')
        expect(context.locator('[data-context-finding-id]')).to_have_count(0)
        expect(context).to_contain_text('finding currentness Unknown')
    finally:
        viewer.close()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('target', ('network-observation', 'network-work'))
def test_network_refresh_preserves_exact_keyboard_identity_without_occlusion(
    research_browser, recorded_research, target,
):
    """Reject rebuilding focused nodes as new controls or hiding them behind header."""
    snapshot, _, _ = recorded_research
    viewer = FixtureViewer(research_browser, snapshot)
    try:
        page = viewer.page
        page.set_viewport_size({'width': 390, 'height': 1000})
        viewer.open()
        selected = page.get_by_test_id(target).first
        _tab_to(page, selected)
        _assert_visible_focus(selected)
        identity = selected.get_attribute('data-network-key')
        viewer.refresh(snapshot)
        selected = page.locator(f'button[data-network-key="{identity}"]')
        _assert_visible_focus(selected)
        assert selected.evaluate("""node => {
            const rect = node.getBoundingClientRect();
            return document.elementFromPoint(rect.x + rect.width/2, rect.y + rect.height/2)?.closest('button') === node;
        }"""), 'Persistent authority obscures the focused network control.'
        # A real keyboard disclosure remains inspectable without removing facts.
        summary = page.locator('.authority > details > summary')
        _tab_to(page, summary)
        page.keyboard.press('Enter')
        assert summary.evaluate('node => node.parentElement.open')
        _assert_visible_focus(summary)
        expect(page.get_by_test_id('manifest-identity')).to_be_visible()
        expect(page.get_by_test_id('last-read-attempt')).to_be_visible()
        assert all(method == 'GET' for method, path in viewer.requests)
    finally:
        viewer.close()
