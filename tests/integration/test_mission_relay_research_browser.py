"""T055 maintained Chromium DOM over actual admitted SQLite research projection.

Removing recorded work rendering or exposing withheld result prose breaks these
controls. Loopback transport interception is scoped UI evidence, not HTTP UAT.
"""
from dataclasses import replace
from pathlib import Path

import pytest
import pytest_asyncio

from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
from tests.integration.test_mission_relay_read_boundary import _reader, _request
from tests.integration import test_mission_relay_read_boundary as physical

from tests.integration.test_research_work_persistence import _arrange, _commit
from tests.integration.test_mission_relay_browser import _viewer

relay_case = physical.relay_case

EVIDENCE = Path(__file__).resolve().parents[2] / '.handoff/spec014/us4/t055'


@pytest_asyncio.fixture
async def recorded_research(relay_case, tmp_path, request):
    mode = getattr(request, 'param', 'descriptive')
    if mode == 'schema_unavailable':
        from ignis.domain.entities import ResearchMission
        case, missions, _ = relay_case
        mission = ResearchMission(title='Canonical without research schema', keywords=['synthetic'],
            workspace_id=missions[0].workspace_id, surface='ATTENTION')
        await case.repository.save_mission(mission)
        snapshot = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))
        assert snapshot.to_payload()['research'] == {'availability': 'SCHEMA_UNAVAILABLE'}
        return snapshot, None, None
    case, mission, _, port, work, handoff, revision = await _arrange(relay_case, tmp_path)
    handoff = replace(handoff, result='<img src=x onerror="window.untrustedExecuted=true">', occurred_at=None,
                      findings=(replace(handoff.findings[0], statement='<b>Recorded descriptive finding</b>'),))
    if mode == 'pruned':
        from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
        store = WorkspaceRepository(repository=case.repository)
        run = (await store.list_run_journals(mission.id))[0]
        initial = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(replace(_request(mission, run.run_id), page_size=200))
        assert await case.repository.commit_collection_pruning(mission.id, run.run_id, []) == 6
        fresh = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(replace(_request(mission, run.run_id), page_size=200))
        assert fresh.evidence == ()
        return initial, fresh, None
    if mode == 'available_empty':
        from ignis.domain.entities import ResearchMission
        empty = ResearchMission(title='Recorded empty research', keywords=['synthetic'],
            workspace_id=mission.workspace_id, surface='ATTENTION')
        await case.repository.save_mission(empty)
        snapshot = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(empty, None))
        assert snapshot.to_payload()['research']['availability'] == 'AVAILABLE'
        return snapshot, None, None
    if mode in ('active', 'cancel_pending', 'expired', 'unknown'):
        if mode == 'cancel_pending':
            from ignis.domain.research_work import ReasonWorkPayload
            receipt = await _commit(case.repository, port, mission, 'REQUEST_CANCEL',
                ReasonWorkPayload(work_id=work.work_id, expected_version=work.version,
                    ownership_fence=work.ownership_fence, reason='Host report'), revision=revision)
            assert receipt.disposition == 'APPLIED'
        reader = _reader(case.repository)
        request_read = _request(mission, None)
        if mode in ('expired', 'unknown'):
            # Controlled read clock/missing receipt projection over actual immutable storage read.
            # These cases do not claim a natural clock wait or real host receipt absence.
            from datetime import timedelta
            from ignis.application.use_cases.get_mission_relay_snapshot import _project
            raw = await reader.load_snapshot(request_read)
            raw = replace(raw, read_at=raw.read_at + timedelta(days=301)) if mode == 'expired' else replace(raw, research_activities=())
            snapshot = _project(selected_mission_id=mission.id, selected_run_id=None,
                evidence=raw.evidence, run=raw.run, revision=raw.high_water.revision,
                read_at=raw.read_at, page_size=raw.request.page_size, coherent_read=raw)
        else:
            snapshot = await GetMissionRelaySnapshotUseCase(reader).execute(request_read)
        return snapshot, work, handoff
    if mode in ('permitted', 'withdrawn'):
        from uuid import uuid4
        from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
        from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
        from ignis.domain import research_work as domain
        from tests.unit.test_mission_claims import _observation_candidate
        from tests.integration.test_research_work_persistence import _another_work
        store = WorkspaceRepository(repository=case.repository)
        evidence = await store.load_mission_evidence_snapshot(mission.id)
        signal = next(signal for signal in evidence.signals if signal.raw_title == 'Demand evidence')
        submitted = await SubmitMissionClaimsUseCase(case.repository, store).execute(
            str(mission.id), work.inputs.frame_digest, [_observation_candidate(signal)], created_by='t055-fixture')
        assert submitted['permitted'] == 1
        claim = (await store.load_mission_evidence_snapshot(mission.id)).claims[0]
        state = await case.repository.load_research_work(mission.id)
        inputs = replace(work.inputs, observation_ids=(signal.observation_id,))
        producer, revision = await _another_work(case, mission, domain, port, work, inputs, state.revision)
        finding = replace(handoff.findings[0], finding_id=uuid4(), handoff_id=uuid4(), work_id=producer.work_id,
            inputs=inputs, result_type='STRATEGIC_CANDIDATE', claim_id=claim.claim_id,
            statement='UNLICENSED_CANDIDATE_PROSE', supporting_observation_ids=(signal.observation_id,),
            contradicting_observation_ids=(), context_observation_ids=())
        result = replace(handoff, handoff_id=finding.handoff_id, work_id=producer.work_id,
            expected_version=producer.version, inputs=inputs, result='UNLICENSED_AGGREGATE_PROSE',
            observation_sources=((signal.observation_id, signal.source_id),), claim_ids=(claim.claim_id,), findings=(finding,))
        receipt = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', result, revision=revision)
        assert receipt.disposition == 'APPLIED'
        run = (await store.list_run_journals(mission.id))[0]
        snapshot = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, run.run_id))
        assert snapshot.to_payload()['claim_gate']['state'] == 'CURRENT'
        if mode == 'withdrawn':
            from tests.integration.test_research_work_persistence import _sql
            await _sql(case, 'DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?',
                (mission.id, signal.observation_id))
            fresh = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, run.run_id))
            assert fresh.to_payload()['research']['findings'][0]['text_withheld'] is True
            return snapshot, fresh, claim
        return snapshot, producer, claim
    if mode == 'strategic':
        sentinel = 'UNPERMITTED_STRATEGIC_PROSE'
        handoff = replace(handoff, result=sentinel, limitations=(sentinel,), open_questions=(sentinel,),
            findings=(replace(handoff.findings[0], result_type='STRATEGIC_CANDIDATE', statement=sentinel,
                limitations=(sentinel,), open_questions=(sentinel,), alternative_explanation=sentinel),))
    result = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', handoff, revision=revision)
    assert result.disposition == 'APPLIED'
    ack = port.ResearchHandoffAcknowledgement(handoff_id=handoff.handoff_id,
        consumer_ref=handoff.consumer_ref, expected_version=result.work_version,
        disposition='ACCEPTED', reason_code=None, inputs=handoff.inputs)
    receipt = await _commit(case.repository, port, mission, 'ACK_HANDOFF', ack, revision=result.revision)
    assert receipt.disposition == 'APPLIED'
    if mode == 'history':
        from uuid import uuid4
        from tests.integration.test_research_work_persistence import _another_work
        from ignis.domain import research_work as domain
        inputs = replace(work.inputs, finding_revisions=((handoff.findings[0].finding_id, 1),))
        producer, revision = await _another_work(case, mission, domain, port, work, inputs, receipt.revision)
        revised = replace(handoff.findings[0], revision=2, predecessor_revision=1, inputs=inputs,
            statement='Second recorded revision', work_id=producer.work_id, handoff_id=uuid4())
        updated = replace(handoff, handoff_id=revised.handoff_id, work_id=producer.work_id,
            expected_version=producer.version, inputs=inputs, findings=(revised,))
        response = await _commit(case.repository, port, mission, 'SUBMIT_HANDOFF', updated, revision=revision)
        assert response.disposition == 'APPLIED'
    snapshot = await GetMissionRelaySnapshotUseCase(_reader(case.repository)).execute(_request(mission, None))
    assert snapshot.to_payload()['research']['availability'] == 'AVAILABLE'
    return snapshot, work, handoff


@pytest.fixture
def research_browser(recorded_research):
    # Start sync Playwright only after async storage fixtures settle.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize('relay_case', ('file', 'memory'), indirect=True)
def test_committed_research_is_inspectable_without_inventing_activity(research_browser, recorded_research):
    snapshot, work, handoff = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        output = page.get_by_role('region', name='Output', exact=True)
        # Existing Output region is present even before implementation: genuine missing-render RED.
        assert work.question in output.inner_text(), 'Recorded work question is missing from the actual inspector.'
        assert output.locator('[data-work-id]').count() == 1
        assert 'SEQUENTIAL' in output.inner_text() and 'HOST_REPORTED' in output.inner_text()
        assert 'COMPLETED' in output.inner_text() and 'ACCEPTED' in output.inner_text()
        assert 'Unknown' in output.inner_text() and 'MISSION_CURRENT' in output.inner_text()
        assert '<b>Recorded descriptive finding</b>' in output.inner_text()
        assert output.locator('img, b').count() == 0
        assert page.evaluate('window.untrustedExecuted === undefined')
        assert output.locator('[data-testid="research-observation-count"]').inner_text() == '6'
        assert output.locator('[data-testid="research-source-count"]').inner_text() == '6'
        assert output.locator('[data-testid="finding-history"] article').count() == 1
        assert not viewer.unexpected


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('width', (390, 768, 1440))
def test_research_lanes_fit_and_keyboard_details_preserve_receipts(research_browser, recorded_research, width):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.set_viewport_size({'width': width, 'height': 1000})
        page.emulate_media(reduced_motion='reduce')
        page.locator('[data-stage="Research"]').focus()
        page.keyboard.press('Enter')
        assert 'Describe recorded observations' in page.get_by_role('region', name='Output', exact=True).inner_text()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        details = page.get_by_test_id('finding-history').locator('summary').first
        details.focus()
        page.keyboard.press('Enter')
        assert details.evaluate('(element) => element.parentElement.open')
        assert page.get_by_test_id('finding-history').locator('article').count() == 1
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(EVIDENCE / f'research-{width}.png'), full_page=True)
        page.get_by_test_id('research-work-lanes').screenshot(path=str(EVIDENCE / f'work-lanes-{width}.png'))
        (EVIDENCE / f'research-{width}.dom.txt').write_text(page.get_by_test_id('stage-inspector').inner_text())


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('strategic',), indirect=True)
def test_unpermitted_candidate_never_reappears_in_handoff_or_history(research_browser, recorded_research):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        viewer.page.locator('[data-stage="Research"]').click()
        output = viewer.page.get_by_role('region', name='Output', exact=True)
        assert 'UNPERMITTED_STRATEGIC_PROSE' not in output.inner_text()
        assert 'Aggregate result withheld' in output.inner_text()
        assert 'Text withheld' in output.inner_text()
        assert 'WITHHELD' in output.inner_text()
        finding = snapshot.to_payload()['research']['findings'][0]
        assert finding['current_eligible'] is True and finding['text_withheld'] is True
        assert finding['narrative_origin'] == 'WITHHELD'
        assert 'Exact current canonical Claim Ledger narration' not in output.inner_text()
        assert 'Strategic candidate text withheld; no current Claim Ledger permission.' in output.inner_text()
        assert output.locator('[data-testid="finding-history"] article').count() == 1
        output.locator('summary').last.click()
        assert 'UNPERMITTED_STRATEGIC_PROSE' not in output.inner_text()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('history',), indirect=True)
def test_shared_input_history_keeps_exact_revisions_and_one_canonical_count(research_browser, recorded_research):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        output = page.get_by_role('region', name='Output', exact=True)
        assert output.locator('[data-work-id]').count() == 2
        assert output.locator('[data-testid="finding-history"] article').count() == 2
        assert output.get_by_test_id('research-observation-count').inner_text() == '6'
        assert output.get_by_test_id('research-source-count').inner_text() == '6'
        assert 'revision 1' in output.inner_text() and 'revision 2' in output.inner_text()
        assert 'current eligible false' in output.inner_text()
        output.locator('[data-work-id] summary').last.click()
        assert 'exact revision 1' in output.inner_text()
        assert 'Second recorded revision' in output.inner_text()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
def test_failed_refresh_withdraws_research_results_and_receipt_activity(research_browser, recorded_research):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        assert '<b>Recorded descriptive finding</b>' in page.get_by_role('region', name='Output', exact=True).inner_text()
        page.route('**/snapshot?**', lambda route: route.fulfill(status=503, json={'status': 'UNAVAILABLE'}))
        with page.expect_response(lambda response: response.status == 503):
            page.clock.run_for(2100)
        page.get_by_test_id('snapshot-state').filter(has_text='Stale').wait_for()
        output = page.get_by_role('region', name='Output', exact=True)
        assert '<b>Recorded descriptive finding</b>' not in output.inner_text()
        assert output.locator('[data-work-id]').count() == 0
        assert 'Unknown' in output.inner_text()
        viewer.counts(6, 6)


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research, state', (
    ('active', 'ACTIVE'), ('cancel_pending', 'CANCEL_PENDING'), ('expired', 'STALE'), ('unknown', 'UNKNOWN'),
), indirect=['recorded_research'])
def test_finite_receipt_unknown_expiry_and_pending_cancel_are_honest(research_browser, recorded_research, state):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        output = page.get_by_role('region', name='Output', exact=True)
        assert state in output.inner_text()
        assert 'Activity at read:' in output.inner_text()
        assert 'No ongoing execution is inferred.' in output.inner_text()
        assert output.locator('[data-work-id]').count() == 1
        assert output.locator('[data-handoff-id]').count() == 0
        assert page.evaluate("[...document.querySelectorAll('[data-testid=research-view] *')].every(element => getComputedStyle(element).animationName === 'none')")
        if state == 'CANCEL_PENDING':
            assert 'Cancellation requested · stop acknowledgement pending.' in output.inner_text()
        if state == 'STALE':
            assert 'Authority EXPIRED' in output.inner_text()
        if state == 'UNKNOWN':
            assert 'Host receipt' not in output.inner_text()
        page.get_by_role('button', name='Pause refresh', exact=True).click()
        assert 'Activity at read:' in output.inner_text()
        assert 'No ongoing execution is inferred.' in output.inner_text()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('schema_unavailable',), indirect=True)
def test_missing_schema_records_and_counts_remain_unknown(research_browser, recorded_research):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        viewer.page.locator('[data-stage="Research"]').click()
        output = viewer.page.get_by_role('region', name='Output', exact=True)
        assert 'SCHEMA_UNAVAILABLE' in output.inner_text() and 'Unknown' in output.inner_text()
        assert output.locator('[data-work-id], [data-assignment-id]').count() == 0
        assert output.locator('[data-testid="research-observation-count"], [data-testid="research-source-count"]').count() == 0


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('permitted',), indirect=True)
def test_strategic_finding_uses_exact_current_ledger_narration(research_browser, recorded_research):
    snapshot, _, claim = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        viewer.page.locator('[data-stage="Research"]').click()
        output = viewer.page.get_by_role('region', name='Output', exact=True)
        assert claim.wording in output.inner_text()
        assert 'CURRENT_CLAIM_LEDGER' in output.inner_text()
        assert 'UNLICENSED_CANDIDATE_PROSE' not in output.inner_text()
        assert 'UNLICENSED_AGGREGATE_PROSE' not in output.inner_text()
        assert 'Aggregate result withheld' in output.inner_text()
        assert output.locator('[data-testid="finding-history"] article').count() == 1


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('withdrawn',), indirect=True)
def test_successful_current_read_withdraws_old_strategic_research_text(research_browser, recorded_research):
    initial, fresh, claim = recorded_research
    with _viewer(research_browser, initial) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        assert claim.wording in page.get_by_role('region', name='Output', exact=True).inner_text()
        viewer.refresh(fresh)
        output = page.get_by_role('region', name='Output', exact=True)
        assert claim.wording not in output.inner_text()
        assert 'Text withheld' in output.inner_text()
        assert 'current eligible false' in output.inner_text()
        assert output.locator('[data-testid="finding-history"] article').count() == 1


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('available_empty',), indirect=True)
def test_available_empty_research_is_measured_zero_without_fake_specialists(research_browser, recorded_research):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        viewer.page.locator('[data-stage="Research"]').click()
        output = viewer.page.get_by_role('region', name='Output', exact=True)
        assert output.get_by_test_id('research-observation-count').inner_text() == '0'
        assert output.get_by_test_id('research-source-count').inner_text() == '0'
        assert output.locator('[data-work-id], [data-assignment-id]').count() == 0
        assert 'No recorded work items' in output.inner_text()
        assert 'No recorded finding revisions' in output.inner_text()


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('detail', ('Inputs and dependencies', 'Exact handoff inputs', 'Evidence, alternatives and limits'))
def test_successful_refresh_keeps_keyboard_focus_and_expanded_finding(research_browser, recorded_research, detail):
    snapshot, _, _ = recorded_research
    with _viewer(research_browser, snapshot) as viewer:
        page = viewer.page
        page.locator('[data-stage="Research"]').click()
        summary = page.locator('summary').filter(has_text=detail).first
        summary.focus()
        page.keyboard.press('Enter')
        assert summary.evaluate('(element) => element.parentElement.open')
        viewer.refresh(snapshot)
        summary = page.locator('summary').filter(has_text=detail).first
        assert summary.evaluate('(element) => element.parentElement.open'), 'Automatic refresh closed recorded finding details.'
        assert summary.evaluate('(element) => document.activeElement === element'), 'Automatic refresh stole summary focus.'


@pytest.mark.parametrize('relay_case', ('file',), indirect=True)
@pytest.mark.parametrize('recorded_research', ('pruned',), indirect=True)
def test_recorded_pruning_remains_inspectable_without_new_arrival_packets(research_browser, recorded_research):
    """A persisted membership removal is not evidence arriving at intake."""
    initial, fresh, _ = recorded_research
    pruned = [event for event in fresh.event_page.events if event.reason == 'MEMBERSHIP_PRUNED']
    assert len(pruned) == 1 and len(pruned[0].evidence_references) == 6
    with _viewer(research_browser, initial) as viewer:
        viewer.refresh(fresh)
        timeline = viewer.page.get_by_test_id('event-timeline').locator(f'[data-event-id="{pruned[0].event_id}"]')
        assert 'MEMBERSHIP_PRUNED' in timeline.inner_text()
        assert timeline.get_by_test_id('event-observation-count').inner_text() == '6'
        assert viewer.packets == [], 'Removed references were animated as newly arriving evidence.'
        assert not viewer.unexpected
