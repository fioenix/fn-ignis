"""T060 browser test design; no screen-reader, WCAG certification or native UAT claim."""

import re
from urllib.parse import urlsplit

import pytest

from tests.integration import test_mission_relay_browser as browser


installed_browser = browser.installed_browser
expect = pytest.importorskip('playwright.sync_api', reason='Installed Playwright is unavailable').expect


def _tab_to(page, target):
    """Reach the actual control through sequential keyboard navigation, never focus()."""
    assert target.count() == 1, 'Essential control is absent from the keyboard-accessible page.'
    for _ in range(40):
        page.keyboard.press('Tab')
        if target.evaluate('node => node === document.activeElement'):
            return
    raise AssertionError('Essential control cannot be reached by keyboard Tab.')


def _assert_visible_focus(target):
    observed = target.evaluate("""node => {
        const style = getComputedStyle(node), rect = node.getBoundingClientRect();
        return {active: node === document.activeElement, keyboard: node.matches(':focus-visible'),
            outline: style.outlineStyle, width: parseFloat(style.outlineWidth), color: style.outlineColor,
            shadow: style.boxShadow, visible: rect.width > 0 && rect.height > 0 &&
                rect.bottom > 0 && rect.top < innerHeight && rect.right > 0 && rect.left < innerWidth};
    }""")
    assert observed['active'] and observed['keyboard'], 'Keyboard focus moved away from the selected control.'
    opaque_outline = observed['color'] != 'transparent' and not re.search(r'rgba\([^)]*,\s*0\)', observed['color'])
    outline = observed['outline'] not in ('none', 'hidden') and observed['width'] > 0 and opaque_outline
    assert observed['visible'] and (outline or observed['shadow'] != 'none'), 'Keyboard focus has no visible paint indicator.'


def _keyboard_probe(viewer):
    viewer.context.add_init_script("""window.pointerActivations = 0;
        document.addEventListener('pointerdown', () => pointerActivations++);
        document.addEventListener('mousedown', () => pointerActivations++);""")


def _assert_read_only(viewer):
    assert viewer.page.evaluate('pointerActivations') == 0, 'Inspection required a pointer action.'
    assert not viewer.unexpected, 'Keyboard viewing attempted a route outside scoped reads.'
    assert all(method == 'GET' for method, path in viewer.requests), 'Keyboard viewing invoked a mission write.'


@pytest.mark.parametrize('reduced', (False, True))
def test_keyboard_reaches_all_stages_and_essential_explanations(installed_browser, reduced):
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot((browser._observation(),)))
    viewer.page.emulate_media(reduced_motion='reduce' if reduced else 'no-preference')
    _keyboard_probe(viewer)
    try:
        viewer.open()
        for name in browser.RESPONSIBILITIES:
            button = viewer.page.get_by_role('button', name=name, exact=True)
            _tab_to(viewer.page, button)
            _assert_visible_focus(button)
            viewer.page.keyboard.press('Enter')
            inspector = viewer.page.get_by_test_id('stage-inspector')
            expect(inspector.get_by_role('heading', name=name, exact=True)).to_be_visible()
            for region in ('Input', 'Output', 'Failure reason', 'Why it matters'):
                expect(inspector.get_by_role('region', name=region, exact=True)).to_contain_text(re.compile(r'\S'))
            _assert_visible_focus(button)
        _assert_read_only(viewer)
    finally:
        viewer.close()


@pytest.mark.parametrize('reduced', (False, True))
def test_keyboard_evidence_inspection_preserves_exact_recorded_facts(installed_browser, reduced):
    row = browser._observation()
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot((row,)))
    viewer.page.emulate_media(reduced_motion='reduce' if reduced else 'no-preference')
    _keyboard_probe(viewer)
    try:
        viewer.open()
        button = viewer.page.get_by_role('button', name=row.title, exact=True)
        _tab_to(viewer.page, button)
        _assert_visible_focus(button)
        viewer.page.keyboard.press('Enter')
        inspector = viewer.page.get_by_test_id('stage-inspector')
        expect(inspector.get_by_role('heading', name='Evidence inspection', exact=True)).to_be_visible()
        for fact in (row.title, row.excerpt, str(row.observation_id), str(row.source_id), row.evidence_role.value):
            expect(inspector).to_contain_text(fact)
        expect(inspector).to_be_visible()
        assert len([path for method, path in viewer.requests if '/inspect/' in path]) == 1
        viewer.counts(1, 1)
        _assert_read_only(viewer)
    finally:
        viewer.close()


@pytest.mark.parametrize('reduced', (False, True))
def test_keyboard_controls_pause_and_resume_actual_viewer_reads(installed_browser, reduced):
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot())
    viewer.page.emulate_media(reduced_motion='reduce' if reduced else 'no-preference')
    _keyboard_probe(viewer)
    try:
        viewer.open()
        motion = viewer.page.get_by_role('button', name='Pause motion', exact=True)
        _tab_to(viewer.page, motion)
        _assert_visible_focus(motion)
        viewer.page.keyboard.press('Space')
        row = browser._observation()
        viewer.refresh(browser._snapshot((row,), (browser._event(observations=(row,)),)))
        viewer.counts(1, 1)
        assert viewer.packets == [], 'Keyboard motion pause did not suppress packet movement.'
        _assert_visible_focus(viewer.page.get_by_role('button', name='Resume motion', exact=True))
        refresh = viewer.page.get_by_role('button', name='Pause refresh', exact=True)
        _tab_to(viewer.page, refresh)
        _assert_visible_focus(refresh)
        viewer.page.keyboard.press('Space')
        before = len([path for method, path in viewer.requests if path.endswith('/snapshot')])
        viewer.page.clock.run_for(6000)
        assert len([path for method, path in viewer.requests if path.endswith('/snapshot')]) == before
        resume = viewer.page.get_by_role('button', name='Resume refresh', exact=True)
        _assert_visible_focus(resume)
        viewer.page.keyboard.press('Enter')
        viewer.refresh(browser._snapshot((row,), (browser._event(observations=(row,)),)))
        assert len([path for method, path in viewer.requests if path.endswith('/snapshot')]) == before + 1
        viewer.counts(1, 1)
        _assert_visible_focus(viewer.page.get_by_role('button', name='Pause refresh', exact=True))
        _assert_read_only(viewer)
    finally:
        viewer.close()


@pytest.mark.parametrize('target', ('stage', 'evidence'))
def test_successful_refresh_preserves_keyboard_focus_on_selected_control(installed_browser, target):
    first, second = browser._observation(), browser._observation(2)
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot((first,)))
    _keyboard_probe(viewer)
    try:
        viewer.open()
        name = 'Sources' if target == 'stage' else first.title
        selected = viewer.page.get_by_role('button', name=name, exact=True)
        _tab_to(viewer.page, selected)
        _assert_visible_focus(selected)
        fresh = browser._snapshot((first, second), (browser._event(observations=(second,)),))
        viewer.refresh(fresh)
        viewer.counts(2, 1)
        assert selected.evaluate('node => node === document.activeElement'), 'Refresh lost keyboard focus on the selected control.'
        _assert_visible_focus(selected)
        status = viewer.page.get_by_test_id('snapshot-state')
        assert status.get_attribute('role') == 'status' or status.get_attribute('aria-live') == 'polite', \
            'Routine refresh has no restrained accessible update announcement.'
        _assert_read_only(viewer)
    finally:
        viewer.close()


def _install_document_motion_probe(viewer):
    """Detect CSS/pseudo animation and script-driven transform/opacity changes."""
    viewer.context.add_init_script("""(() => {
        window.accessibilityMotion = {frames: 0, moving: 0};
        const previous = new WeakMap();
        function sample() {
            accessibilityMotion.frames++;
            let moved = false;
            for (const node of document.querySelectorAll('body, main, main *')) {
                const style = getComputedStyle(node), value = style.transform + ':' + style.opacity;
                if (previous.has(node) && previous.get(node) !== value) moved = true;
                previous.set(node, value);
            }
            if (moved) accessibilityMotion.moving++;
            requestAnimationFrame(sample);
        }
        requestAnimationFrame(sample);
    })();""")


def test_reduced_motion_preserves_facts_without_packet_pulse_or_camera_movement(installed_browser):
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot())
    _install_document_motion_probe(viewer)
    try:
        viewer.open()
        first, second = browser._observation(), browser._observation(2)
        events = (browser._event(1, (first,)), browser._event(2, (second,)))
        viewer.refresh(browser._snapshot((first,), events[:1]))
        viewer.page.wait_for_function('accessibilityMotion.moving >= 2')
        assert viewer.page.get_by_test_id('relay-packet').count() == 1, 'Ordinary-motion control did not render a fresh packet.'
        viewer.page.emulate_media(reduced_motion='reduce')
        viewer.page.wait_for_timeout(100)
        before = viewer.page.evaluate('({...accessibilityMotion})')
        viewer.refresh(browser._snapshot((first, second), events))
        viewer.page.wait_for_timeout(120)
        after = viewer.page.evaluate('({...accessibilityMotion})')
        assert after['frames'] > before['frames'], 'Reduced-motion observer stopped sampling.'
        assert after['moving'] == before['moving'], 'Reduced motion retained continuous transform/opacity movement.'
        assert viewer.page.evaluate("document.getAnimations().filter(animation => animation.playState === 'running').length") == 0, \
            'Reduced motion retained a running CSS, pseudo-element or Web Animation.'
        viewer.counts(2, 1)
        expect(browser._event_row(viewer.page, events[1])).to_be_visible()
        for row in (first, second):
            expect(viewer.page.get_by_test_id('stage-inspector').get_by_role('button', name=row.title, exact=True)).to_be_visible()
        assert not viewer.unexpected
    finally:
        viewer.close()


def test_blocked_external_resources_keep_exact_facts_and_keyboard_inspection(installed_browser):
    row = browser._observation()
    viewer = browser.FixtureViewer(installed_browser, browser._snapshot((row,)))
    blocked = []
    original = viewer._route
    def resources_unavailable(route):
        parsed = urlsplit(route.request.url)
        if parsed.scheme != 'http' or parsed.netloc != '127.0.0.1:43118':
            blocked.append((parsed.scheme, parsed.netloc))
            route.abort('failed')
        else:
            original(route)
    viewer.context.unroute('**/*')
    viewer.context.route('**/*', resources_unavailable)
    _keyboard_probe(viewer)
    try:
        viewer.open()
        assert blocked, 'The unavailable-resource control never blocked an actual resource request.'
        viewer.counts(1, 1)
        expect(viewer.page.get_by_test_id('mission-authority')).to_contain_text(str(browser.MISSION))
        button = viewer.page.get_by_role('button', name=row.title, exact=True)
        _tab_to(viewer.page, button)
        _assert_visible_focus(button)
        viewer.page.keyboard.press('Enter')
        inspector = viewer.page.get_by_test_id('stage-inspector')
        for fact in (row.title, row.excerpt, str(row.observation_id), str(row.source_id)):
            expect(inspector).to_contain_text(fact)
        expect(inspector).to_be_visible()
        viewer.counts(1, 1)
        assert len([path for method, path in viewer.requests if '/inspect/' in path]) == 1
        _assert_read_only(viewer)
    finally:
        viewer.close()
