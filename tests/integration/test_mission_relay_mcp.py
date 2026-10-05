"""Actual MCP/HTTP read chain over disposable canonical storage."""

import asyncio
import http.client
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest
import pytest_asyncio
from fastmcp import Client
from pathlib import Path
from uuid import uuid4

from ignis.application.ports.mission_relay_port import ProbeOutcomeCommitCommand
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import MissionProbeOutcome
from ignis.domain.value_objects import PlatformType

from test_mission_relay_read_boundary import (
    _assert_postgres_reads,
    _observe_postgres,
    _observe_sqlite,
    _setup_traps,
    _state,
    relay_case,  # noqa: F401 -- expose the actual disposable storage fixture
)


def _http(url):
    target = urlsplit(url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        connection.request('GET', target.path + ('?' + target.query if target.query else ''))
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest_asyncio.fixture
async def attention_case(relay_case):  # noqa: F811 -- imported pytest fixture
    case, missions, runs = relay_case
    now = datetime.now(timezone.utc)
    selected = ResearchMission(title='Selected Attention view', keywords=['synthetic'],
        surface='ATTENTION', workspace_id=missions[0].workspace_id)
    run = uuid4()
    await case.repository.save_mission(selected)
    await case.repository.record_run_journal(RunJournal(run_id=run, mission_id=selected.id,
        workspace_id=selected.workspace_id, journal_path=Path('private/test-view-journal'),
        sequence=1, status='COMPLETED', started_at=now, completed_at=now))
    await case.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title=f'Public synthetic observation {number}',
        source_url=f'https://example.invalid/{selected.id}/{number}',
        mission_id=selected.id, captured_at=now) for number in range(3)])
    await case.repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=selected.id, run_id=run, outcomes=(MissionProbeOutcome(run_id=run,
            platform='youtube', connector_surface='youtube', status=ChannelHealthStatus.HEALTHY,
            signals_collected=3, queried_keywords=('synthetic',), query_fingerprint='a' * 64,
            completed_at=now),)))
    return case, [selected, missions[1]], [run, runs[1]]


@contextmanager
def _observe_chain(case, monkeypatch):
    if case.name != 'postgres':
        with _observe_sqlite(monkeypatch, case.repository) as observed:
            yield observed
        return
    from ignis.infrastructure.persistence.mission_relay_reader import PostgresMissionRelayReader
    original = PostgresMissionRelayReader.load_snapshot
    calls = []
    async def physical_read(reader, request):
        # Pin and verify each real read separately; the HTTP/MCP chain contains
        # several deliberately independent transactions, not one global read.
        with _observe_postgres(monkeypatch) as observation:
            result = await original(reader, request)
        _assert_postgres_reads(observation)
        calls.append(observation)
        return result
    class ChainObservation:
        def assert_no_writes(self):
            assert calls, 'No physical PostgreSQL read was executed'
    with monkeypatch.context() as patch:
        patch.setattr(PostgresMissionRelayReader, 'load_snapshot', physical_read)
        yield ChainObservation()


@pytest.mark.asyncio
async def test_actual_mcp_http_selected_view_and_inspector_preserve_physical_storage(attention_case, monkeypatch):
    from ignis.interfaces.mcp import server
    case, missions, runs = attention_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    monkeypatch.setattr(server, '_COMPONENTS', {'repository': case.repository})
    def forbidden(*args, **kwargs):
        raise AssertionError('Read chain initialized writable components or credentials')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    observer = _observe_chain(case, monkeypatch)
    with observer as observed:
        async with Client(server.mcp) as client:
            snapshot = (await client.call_tool('get_mission_relay_snapshot', {
                'mission_id': str(missions[0].id), 'run_id': str(runs[0]), 'page_size': 2,
            })).structured_content
            assert snapshot['status'] == 'OK'
            assert snapshot['counts'] == {'observations': 3, 'sources': 3}
            assert len(snapshot['evidence']) == 2 and snapshot['next_evidence_offset'] == 2
            cap = (await client.call_tool('open_mission_relay', {
                'mission_id': str(missions[0].id), 'run_id': str(runs[0]),
                'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            })).structured_content
            assert cap['status'] == 'OK'
            status, headers, html = await asyncio.to_thread(_http, cap['url'])
            assert status == 200 and headers['Cache-Control'] == 'no-store'
            assert b'data-testid="mission-authority"' in html, 'Real HTTP root still serves the temporary shell'
            assert str(missions[0].id).encode() in html and str(runs[0]).encode() in html
            assert str(missions[1].id).encode() not in html and str(runs[1]).encode() not in html
            assert urlsplit(cap['url']).path.strip('/').split('/')[-1].encode() not in html
            status, _, body = await asyncio.to_thread(_http, cap['url'] + 'snapshot?page_size=2')
            projected = json.loads(body)
            assert status == 200 and projected['high_water'] == snapshot['high_water']
            assert projected['counts'] == snapshot['counts']
            row = projected['evidence'][0]
            status, _, body = await asyncio.to_thread(_http, cap['url'] + 'inspect/' + row['observation_id'] + '?page_size=2')
            inspected = json.loads(body)
            assert status == 200 and inspected['observation'] == row
            assert inspected['mission_id'] == snapshot['mission_id'] and inspected['run_id'] == snapshot['run_id']
            status, _, body = await asyncio.to_thread(_http, cap['url'] + 'snapshot?page_size=2&evidence_offset=2')
            last = json.loads(body)
            assert status == 200 and len(last['evidence']) == 1 and last['next_evidence_offset'] is None
            assert last['counts'] == snapshot['counts']
        observed.assert_no_writes()
    assert _state(case) == before


@pytest.mark.asyncio
async def test_actual_mcp_http_browser_reads_and_inspects_without_writes(attention_case, monkeypatch, tmp_path):
    from ignis.interfaces.mcp import server
    from playwright.async_api import async_playwright, expect
    case, missions, runs = attention_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    monkeypatch.setattr(server, '_COMPONENTS', {'repository': case.repository})
    def forbidden(*args, **kwargs):
        raise AssertionError('Browser viewer initialized writable components or credentials')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    observer = _observe_chain(case, monkeypatch)
    errors, requests, external = [], [], []
    with observer as observed:
        async with Client(server.mcp) as client:
            initial = (await client.call_tool('get_mission_relay_snapshot', {
                'mission_id': str(missions[0].id), 'run_id': str(runs[0]), 'page_size': 100,
            })).structured_content
            assert initial['status'] == 'OK'
            cap = (await client.call_tool('open_mission_relay', {
                'mission_id': str(missions[0].id), 'run_id': str(runs[0]),
                'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            })).structured_content
            assert cap['status'] == 'OK'
            target = urlsplit(cap['url'])
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    context = await browser.new_context(service_workers='block')
                    async def route_read(route):
                        request = route.request
                        url = urlsplit(request.url)
                        if url.hostname in ('fonts.googleapis.com', 'fonts.gstatic.com'):
                            await route.abort()
                        elif request.method == 'GET' and url.scheme == 'http' and url.netloc == target.netloc:
                            requests.append(url.path)
                            await route.continue_()
                        else:
                            external.append((request.method, url.hostname))
                            await route.abort()
                    await context.route('**/*', route_read)
                    page = await context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.clock.install(time=datetime.now(timezone.utc))
                    response = await page.goto(cap['url'])
                    assert response.status == 200
                    await expect(page.get_by_test_id('mission-authority')).to_contain_text(str(missions[0].id))
                    await expect(page.get_by_test_id('observation-count')).to_have_text('3')
                    await expect(page.get_by_test_id('source-count')).to_have_text('3')
                    for _ in range(2):
                        async with page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
                            await page.clock.run_for(2100)
                        await expect(page.get_by_test_id('snapshot-state')).to_contain_text('particle motion encodes receipts')
                    await expect(page.get_by_test_id('relay-packet')).to_have_count(0)
                    row = initial['evidence'][0]
                    async with page.expect_response(lambda response: '/inspect/' in urlsplit(response.url).path):
                        await page.get_by_test_id('stage-inspector').get_by_role('button', name=row['title'], exact=True).click()
                    inspector = page.get_by_test_id('stage-inspector')
                    for value in (row['observation_id'], row['source_id'], row['title'], 'ATTENTION_CONTEXT'):
                        await expect(inspector).to_contain_text(value)
                    await page.get_by_role('button', name='Research', exact=True).click()
                    await expect(inspector).to_contain_text('Unavailable')
                    await page.get_by_role('button', name='Synthesis', exact=True).click()
                    await expect(inspector).to_contain_text('Withheld')
                    await page.screenshot(path=str(tmp_path / 'actual-viewer.png'), full_page=True)
                    assert not errors and not external
                    assert len([path for path in requests if path.endswith('/snapshot')]) == 2
                    assert any('/inspect/' in path for path in requests)
                    await context.close()
                finally:
                    await browser.close()
        observed.assert_no_writes()
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('storage', ('missing', 'old', 'denied'))
async def test_actual_mcp_missing_schema_or_access_refuses_before_bootstrap(storage, monkeypatch, tmp_path):
    import sqlite3
    from pydantic import SecretStr
    from ignis.interfaces.mcp import server
    path = tmp_path / 'unavailable.db'
    if storage == 'old':
        with sqlite3.connect(path) as connection:
            connection.execute('CREATE TABLE research_missions (id TEXT PRIMARY KEY)')
    before = path.read_bytes() if path.exists() else None
    monkeypatch.setattr(server.settings, 'DATABASE_URL', SecretStr(f'sqlite:///{path}'))
    monkeypatch.setattr(server, '_COMPONENTS', None)
    def forbidden(*args, **kwargs):
        raise AssertionError('Unavailable viewer invoked bootstrap or credential initialization')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    if storage == 'denied':
        def denied(*args, **kwargs):
            raise sqlite3.OperationalError('inert access denied')
        monkeypatch.setattr(sqlite3, 'connect', denied)
    async with Client(server.mcp) as client:
        for tool, args in (
            ('get_mission_relay_snapshot', {'page_size': 2}),
            ('open_mission_relay', {'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()}),
        ):
            result = (await client.call_tool(tool, {'mission_id': str(uuid4()), **args})).structured_content
            assert result == {'schema_version': 1, 'status': 'UNAVAILABLE', 'reason_code': 'READ_UNAVAILABLE'}
    assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.asyncio
@pytest.mark.parametrize('state,label', (('PENDING', 'Idle'), ('RUNNING', 'RUNNING'), ('LEGACY_UNRECOGNIZED', 'Unknown')))
async def test_actual_idle_is_canonical_not_inferred_from_unselected_run(attention_case, monkeypatch, state, label):
    from ignis.interfaces.mcp import server
    from playwright.async_api import async_playwright, expect
    case, missions, _ = attention_case
    mission = ResearchMission(title='Canonical collection state', keywords=['synthetic'],
        surface='ATTENTION', status=state, workspace_id=missions[0].workspace_id)
    await case.repository.save_mission(mission)
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    monkeypatch.setattr(server, '_COMPONENTS', {'repository': case.repository})
    def forbidden(*args, **kwargs):
        raise AssertionError('Idle viewer started collection or component bootstrap')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    with _observe_chain(case, monkeypatch) as observed:
        async with Client(server.mcp) as client:
            snapshot = (await client.call_tool('get_mission_relay_snapshot', {
                'mission_id': str(mission.id), 'page_size': 100,
            })).structured_content
            assert snapshot['run_id'] is None
            assert snapshot['collection_state'] == (state if state != 'LEGACY_UNRECOGNIZED' else None)
            cap = (await client.call_tool('open_mission_relay', {
                'mission_id': str(mission.id),
                'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
            })).structured_content
            async with async_playwright() as runtime:
                browser = await runtime.chromium.launch(headless=True)
                try:
                    page = await browser.new_page()
                    await page.route('https://fonts.googleapis.com/**', lambda route: route.abort())
                    await page.route('https://fonts.gstatic.com/**', lambda route: route.abort())
                    assert (await page.goto(cap['url'])).status == 200
                    await expect(page.get_by_test_id('collection-state')).to_contain_text(label)
                    if state != 'PENDING':
                        await expect(page.get_by_test_id('collection-state')).not_to_contain_text('Idle')
                    await expect(page.get_by_test_id('relay-packet')).to_have_count(0)
                    await expect(page.get_by_test_id('observation-count')).to_have_text('0')
                finally:
                    await browser.close()
        observed.assert_no_writes()
    assert _state(case) == before


@contextmanager
def _view_only(case, monkeypatch):
    before = _state(case)
    with monkeypatch.context() as patch:
        _setup_traps(patch, case.repository)
        with _observe_chain(case, patch) as observed:
            yield
            observed.assert_no_writes()
    assert _state(case) == before


@pytest.mark.asyncio
async def test_committed_changes_reach_actual_http_browser_once(attention_case, monkeypatch):
    from ignis.interfaces.mcp import server
    from ignis.domain.research_workspace import (
        EvidenceDirection, EvidencePurpose, EvidenceQualification, QualificationReason,
        QualificationRelation, compute_frame_fingerprint,
    )
    from playwright.async_api import async_playwright, expect
    case, missions, runs = attention_case
    mission, run = missions[0], runs[0]
    monkeypatch.setattr(server, '_COMPONENTS', {'repository': case.repository})
    def forbidden(*args, **kwargs):
        raise AssertionError('Viewer started component bootstrap or credential initialization')
    monkeypatch.setattr(server, 'get_components', forbidden)
    monkeypatch.setattr(server, 'create_repository', forbidden)
    async with Client(server.mcp) as client, async_playwright() as runtime:
        browser = await runtime.chromium.launch(headless=True)
        try:
            context = await browser.new_context(service_workers='block')
            await context.add_init_script('''(() => {
                window.receipts = [];
                new MutationObserver(changes => {
                    for (const change of changes) for (const node of change.addedNodes) {
                        if (node instanceof Element && node.matches('[data-testid="relay-packet"]')) {
                            receipts.push({event:node.dataset.eventId, role:node.dataset.evidenceRole,
                                direction:node.dataset.direction || null,
                                observations:JSON.parse(node.dataset.observationIds),
                                provenance:node.dataset.provenance});
                        }
                    }
                }).observe(document, {childList:true, subtree:true});
            })();''')
            await context.route('https://fonts.googleapis.com/**', lambda route: route.abort())
            await context.route('https://fonts.gstatic.com/**', lambda route: route.abort())
            page = await context.new_page()
            clock_time = datetime.now(timezone.utc)
            await page.clock.install(time=clock_time)
            await page.clock.pause_at(clock_time + timedelta(seconds=1))
            with _view_only(case, monkeypatch):
                cap = (await client.call_tool('open_mission_relay', {
                    'mission_id': str(mission.id), 'run_id': str(run),
                    'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                })).structured_content
                assert cap['status'] == 'OK'
                assert (await page.goto(cap['url'])).status == 200
                await expect(page.get_by_test_id('observation-count')).to_have_text('3')
                assert await page.evaluate('receipts') == []
            # Deliberate control-plane fixture writes occur outside the guarded
            # viewer phases. Only these authorized commits may change storage.
            signals = [TrendSignal(platform=PlatformType.YOUTUBE,
                raw_title=f'New committed observation {number}',
                source_url=f'https://example.invalid/new/{mission.id}/{number}',
                mission_id=mission.id, captured_at=datetime.now(timezone.utc)) for number in range(2)]
            assert await case.repository.commit_collection_observations(mission.id, run, signals) == 2
            assert all(signal.observation_id is not None for signal in signals)
            with _view_only(case, monkeypatch):
                async with page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
                    await page.clock.run_for(2100)
                await expect(page.get_by_test_id('observation-count')).to_have_text('5')
                await expect(page.get_by_test_id('source-count')).to_have_text('5')
                arrivals = await page.evaluate('receipts')
                assert len(arrivals) == 1 and set(arrivals[0]['observations']) == {str(signal.observation_id) for signal in signals}
                assert arrivals[0]['role'] == 'ATTENTION_CONTEXT' and arrivals[0]['provenance'] == 'HARNESS_OBSERVED'
                async with page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
                    await page.clock.run_for(2100)
                assert await page.evaluate('receipts') == arrivals
            directions = (EvidenceDirection.SUPPORT, EvidenceDirection.CONTRADICTION)
            relations = (QualificationRelation.QUALIFIED_SUPPORT, QualificationRelation.QUALIFIED_CONTRADICTION)
            qualifications = [EvidenceQualification(mission_id=mission.id,
                observation_id=signal.observation_id, frame_fingerprint=compute_frame_fingerprint(mission, None),
                relation=relation, purpose=EvidencePurpose.VOC, confidence=0.9,
                reason_code=QualificationReason.DIRECT_TO_FRAME, judged_by='fixture',
                evidence_role=direction, evidence_contract_version=2,
                hypothesis_target='synthetic observation check', created_at=datetime.now(timezone.utc))
                for signal, direction, relation in zip(signals, directions, relations)]
            assert await case.repository.commit_evidence_qualifications(mission.id, qualifications) == 2
            with _view_only(case, monkeypatch):
                async with page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
                    await page.clock.run_for(2100)
                await expect(page.get_by_test_id('snapshot-state')).to_contain_text('particle motion encodes receipts')
                packets = await page.evaluate('receipts')
                assert len(packets) == 3 and packets[:1] == arrivals
                assert {packet['direction'] for packet in packets[1:]} == {'SUPPORT', 'CONTRADICTION'}
                assert len({packet['event'] for packet in packets[1:]}) == 1
                assert packets[1]['event'] != arrivals[0]['event']
                for signal, relation in zip(signals, relations):
                    async with page.expect_response(lambda response: '/inspect/' in urlsplit(response.url).path):
                        await page.get_by_test_id('stage-inspector').get_by_role('button', name=signal.raw_title, exact=True).click()
                    await expect(page.get_by_test_id('stage-inspector')).to_contain_text(relation.value)
                    await page.get_by_role('button', name='Sources', exact=True).click()
                async with page.expect_response(lambda response: urlsplit(response.url).path.endswith('/snapshot')):
                    await page.clock.run_for(2100)
                assert await page.evaluate('receipts') == packets
                await expect(page.get_by_test_id('observation-count')).to_have_text('5')
                await page.reload()
                assert await page.evaluate('receipts') == []
                await expect(page.get_by_test_id('observation-count')).to_have_text('5')
                await context.close()
        finally:
            await browser.close()
