"""Actual coherent read-to-display timing, isolated from real-mission UAT."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastmcp import Client
from playwright.async_api import async_playwright, expect
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from tests.unit.test_mission_claims import _eligible_mission, _observation_candidate, _signal_named
from test_mission_relay_read_boundary import relay_case  # noqa: F401 -- fixture
from test_mission_relay_mcp import _view_only


@pytest.mark.asyncio
async def test_us3_actual_read_to_display_latency_and_permission_readback(relay_case, tmp_path, monkeypatch):  # noqa: F811 -- fixture
    from ignis.interfaces.mcp import server
    case, _, _ = relay_case
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path, repository=case.repository)
    use_case = SubmitMissionClaimsUseCase(repository, store)
    candidate = _observation_candidate(_signal_named(signals, 'Demand evidence'))
    result = await use_case.execute(str(mission.id), frame.frame_digest, [candidate], created_by='readback-control')
    assert result.get('permitted') == 1
    run = (await store.list_run_journals(mission.id))[0]
    monkeypatch.setattr(server, '_COMPONENTS', {'repository': repository})
    def forbidden(*args, **kwargs):
        raise AssertionError('Readback initialized components or credentials')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    async with Client(server.mcp) as client:
        cap = (await client.call_tool('open_mission_relay', {'mission_id': str(mission.id),
            'run_id': str(run.run_id), 'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()})).structured_content
        async with async_playwright() as runtime:
            browser = await runtime.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                await page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                with _view_only(case, monkeypatch):
                    assert (await page.goto(cap['url'])).status == 200
                    await page.get_by_role('button', name='Synthesis', exact=True).click()
                    await expect(page.get_by_test_id('current-claims')).to_contain_text(candidate['wording'])
                    await expect(page.get_by_test_id('frame-identity')).to_have_text(frame.frame_digest)
                    await expect(page.get_by_test_id('gate-state')).to_have_text('CURRENT')
                wording = 'A newly persisted fixture statement with exact observation support.'
                await page.evaluate('''wording => {
                    window.t040Boundary = null; window.t040Latency = null;
                    const original = window.fetch;
                    window.fetch = async (...args) => {
                        const response = await original(...args);
                        const json = response.json.bind(response);
                        response.json = async () => {
                            const data = await json();
                            if (data.claim_gate?.claims.some(claim => claim.wording === wording))
                                window.t040Boundary = performance.now();
                            return data;
                        };
                        return response;
                    };
                    new MutationObserver(() => {
                        const region = document.querySelector('[data-testid="current-claims"]');
                        if (window.t040Latency === null && window.t040Boundary !== null && region?.textContent.includes(wording))
                            window.t040Latency = performance.now() - window.t040Boundary;
                    }).observe(document.querySelector('[data-testid="stage-inspector"]'), {childList: true, subtree: true});
                }''', wording)
                candidate = {**candidate, 'client_claim_key': 'timed-current-fixture', 'wording': wording}
                result = await use_case.execute(str(mission.id), frame.frame_digest, [candidate], created_by='readback-control')
                assert result.get('permitted') == 1
                with _view_only(case, monkeypatch):
                    await expect(page.get_by_test_id('current-claims')).to_contain_text(wording, timeout=6000)
                    latency = await page.evaluate('t040Latency')
                    assert latency is not None and 0 <= latency < 5000
                    await expect(page.get_by_test_id('claim-history')).not_to_contain_text(wording)
                    await expect(page.get_by_test_id('current-claims')).to_contain_text(str(_signal_named(signals, 'Demand evidence').observation_id))
                    receipt = await page.get_by_test_id('read-receipt').inner_text()
                name = 'postgres' if case.name == 'postgres' else ('memory' if repository._db_path == ':memory:' else 'sqlite-file')
                output = Path('.handoff/spec014/t040') / f'latency-{name}.json'
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps({'storage': name, 'successful_read_to_display_ms': latency,
                    'read_at': receipt, 'frame_digest': frame.frame_digest, 'real_mission_uat': False}))
            finally:
                await browser.close()
