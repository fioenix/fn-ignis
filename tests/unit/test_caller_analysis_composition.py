"""Caller-bound Market analysis tools on a prepared existing store.

Round trips run the real FastMCP server in a subprocess bound to a synthetic caller root through
IGNIS_CALLER_ROOT; a MockTransport parent supplies the evidence. In-process controls exercise the
same composition objects directly. Nothing here touches a real store.
"""
import asyncio
import json
import sqlite3
import subprocess
import sys

import pytest

from tests.unit import test_caller_youtube_pilot_cli as cli_tests

ROUND_TRIP = r'''
import asyncio, json, sys
from pathlib import Path
import httpx
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
store, mission_id, mode = str(Path(sys.argv[1]).absolute()), sys.argv[2], sys.argv[3]
entered, constructed = [], []
for name in ('_create_tables_and_seed', '_create_progress_tables', '_ensure_research_schema'):
    def traced(self, *args, _original=getattr(SqliteTrendRepository, name), _name=name):
        if str(Path(self._db_path).absolute()) == store:
            entered.append(_name)
        return _original(self, *args)
    setattr(SqliteTrendRepository, name, traced)
from ignis.interfaces.mcp import server
providers = [httpx.AsyncClient, httpx.Client]
for name in ('TikTokAuthManager', 'ThreadsAuthManager', 'InstagramAuthManager', 'ThreadsBrowserAuthManager',
             'InstagramBrowserAuthManager', 'TikTokCreativeCenterPlugin', 'GoogleTrendsRssPlugin', 'TikTokPlugin',
             'ThreadsPlugin', 'ReelsPlugin', 'YouTubeDataPlugin', 'ConnectorPluginRegistry', 'RuntimeConfigManager'):
    providers.append(getattr(server, name))
for provider in providers:
    def recording(self, *args, _init=provider.__init__, _label=provider.__name__, **kwargs):
        constructed.append(_label)
        return _init(self, *args, **kwargs)
    provider.__init__ = recording
from fastmcp import Client

def data(result):
    # The analysis tools return JSON text; FastMCP may also wrap it as {"result": "<json>"}.
    return json.loads(result.content[0].text)

async def main():
    out = {}
    async with Client(server.mcp) as client:
        if mode == 'other':
            result = await client.call_tool('list_research_missions', {}, raise_on_error=False)
            out['other'] = not result.is_error
            return out
        if mode == 'analysis-only':
            result = await client.call_tool('get_mission_analysis', {'mission_id': mission_id}, raise_on_error=False)
            out['refused'] = result.content[0].text if result.is_error else None
            out['analysis_status'] = None if result.is_error else data(result).get('analysis_status')
            return out
        batch = await client.call_tool('get_mission_evidence_qualification_batch', {'mission_id': mission_id},
                                       raise_on_error=False)
        if batch.is_error:
            out['refused'] = batch.content[0].text
            return out
        batch = data(batch)
        out['batch'] = {'status': batch['status'], 'evidence': [item['observation_id'] for item in batch['evidence']]}
        assessments = [{'observation_id': item, 'relation': 'QUALIFIED_SUPPORT', 'purpose': 'SUPPLY',
                        'confidence': 0.9, 'reason_code': 'DIRECT_TO_FRAME', 'judged_by': 'claude-code',
                        'model': 'claude-opus-5-5', 'hypothesis_target': 'core', 'evidence_role': 'SUPPORT'}
                       for item in out['batch']['evidence']]
        submitted = data(await client.call_tool('submit_mission_evidence_qualifications', {
            'mission_id': mission_id, 'frame_fingerprint': batch['frame_fingerprint'], 'assessments': assessments}))
        out['qualifications'] = {'status': submitted.get('status'), 'recorded': submitted.get('recorded')}
        frame = data(await client.call_tool('get_mission_claims', {'mission_id': mission_id}))['frame_digest']
        candidate = {'client_claim_key': 'observed-material', 'claim_type': 'OBSERVATION',
                     'wording': 'One recent public item describes n8n instructional material.', 'confidence': 0.6,
                     'evidence_bindings': [{'observation_id': out['batch']['evidence'][0], 'probe_outcome_id': None,
                                            'role': 'SUPPORT', 'hypothesis_target': 'core'}]}
        claims = data(await client.call_tool('submit_mission_claims', {
            'mission_id': mission_id, 'frame_digest': frame, 'candidates': [candidate], 'created_by': 'claude-code'}))
        out['claims'] = {key: claims.get(key) for key in ('status', 'recorded', 'permitted', 'withheld', 'analysis_status')}
        out['claims']['frame_matches'] = claims.get('frame_digest') == frame
        ledger = data(await client.call_tool('get_mission_claims', {'mission_id': mission_id}))
        out['ledger'] = {'status': ledger.get('status'), 'claims': [
            {'key': claim['client_claim_key'], 'status': claim['status'], 'withheld_reasons': claim['withheld_reasons'],
             'bindings': [[b['observation_id'], b['role'], b['hypothesis_target']] for b in claim['evidence_bindings']]}
            for claim in ledger['claims']]}
        analysis = data(await client.call_tool('get_mission_analysis', {'mission_id': mission_id}))
        out['analysis'] = {'analysis_status': analysis.get('analysis_status'),
                           'failed_gates': (analysis.get('gap_report') or {}).get('failed_gates')}
    return out

result = asyncio.run(main())
print(json.dumps({'result': result, 'entered': entered, 'constructed': sorted(set(constructed))}, default=str))
'''

PRESERVED = ('market_lexicons', 'industry_taxonomies', 'runtime_configs', 'platform_credentials', 'research_workspaces')
GATES = ['MISSING_HYPOTHESIS_COVERAGE:alternative:1', 'MISSING_HYPOTHESIS_COVERAGE:alternative:2',
         'MISSING_HYPOTHESIS_COVERAGE:null', 'MISSING_CONTRADICTION_COVERAGE', 'MISSING_DEMAND_EVIDENCE',
         'MISSING_SUPPLY_EVIDENCE']


def _prepared_completed_parent(tmp_path, *, progress=True):
    root, mission_id = cli_tests._caller_store(tmp_path, progress=progress)
    if progress:
        packet, confirmation = cli_tests._packet(tmp_path)
        run = cli_tests._run(cli_tests._args(root, mission_id, packet, confirmation), tmp_path)
        assert run.returncode == 0, run.stdout + run.stderr
    return root, mission_id, root / '.fnignis' / 'canonical.sqlite3'


def _round_trip(tmp_path, root, store, mission_id, mode='analysis'):
    env = {**cli_tests._env(tmp_path), 'IGNIS_CALLER_ROOT': str(root)}
    result = subprocess.run([sys.executable, '-c', ROUND_TRIP, str(store), str(mission_id), mode], capture_output=True,
                            text=True, timeout=120, env=env, cwd=str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _state(store):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return (connection.execute('SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY 1, 2').fetchall(),
                {t: connection.execute(f'SELECT * FROM "{t}" ORDER BY 1').fetchall() for t in PRESERVED},
                connection.execute('PRAGMA schema_version').fetchone()[0])


def _count(store, table):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return connection.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def _observation(store):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return connection.execute('SELECT observation_id FROM mission_evidence').fetchone()[0]


def test_market_analysis_tools_record_and_read_without_bootstrap_or_providers(tmp_path):
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    before, observation = _state(store), _observation(store)
    trip = _round_trip(tmp_path, root, store, mission_id)
    result = trip['result']
    assert result['batch'] == {'status': 'QUALIFICATION_REQUIRED', 'evidence': [observation]}
    assert result['qualifications'] == {'status': 'RECORDED', 'recorded': 1}
    assert result['claims'] == {'status': 'RECORDED', 'recorded': 1, 'permitted': 0, 'withheld': 1,
                                'analysis_status': 'INSUFFICIENT_EVIDENCE', 'frame_matches': True}
    assert result['ledger'] == {'status': 'READY', 'claims': [{
        'key': 'observed-material', 'status': 'WITHHELD', 'withheld_reasons': GATES,
        'bindings': [[observation, 'SUPPORT', 'core']]}]}
    assert result['analysis'] == {'analysis_status': 'INSUFFICIENT_EVIDENCE', 'failed_gates': GATES}
    assert trip['entered'] == [], 'A prepared caller store re-entered bootstrap, seed or DDL'
    assert trip['constructed'] == [], f"Analysis tools constructed auth/provider/client objects: {trip['constructed']}"
    after = _state(store)
    assert after[0] == before[0] and after[1] == before[1], 'Schema or preserved vocabulary/config/workspace rows changed'
    assert after[2] == before[2], 'Schema cookie changed: DDL ran on the prepared store'
    assert [_count(store, t) for t in ('mission_evidence_qualifications', 'mission_claims', 'mission_claim_evidence')] == [1, 1, 1]


@pytest.mark.parametrize('drift', [
    'DROP TRIGGER mission_progress_events_validate_update',
    'CREATE INDEX extra_mission_index ON research_missions (status)',
])
def test_drifted_prepared_store_refuses_before_any_read_or_write(tmp_path, drift):
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    with sqlite3.connect(store) as connection:
        connection.execute(drift)
    before = store.read_bytes()
    trip = _round_trip(tmp_path, root, store, mission_id)
    assert 'CALLER_SCHEMA_UNSUPPORTED' in trip['result']['refused'], trip
    assert trip['entered'] == [] and trip['constructed'] == []
    assert store.read_bytes() == before, 'A drifted prepared store was modified instead of refused'


def test_other_caller_tools_keep_the_full_composition(tmp_path):
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    trip = _round_trip(tmp_path, root, store, mission_id, mode='other')
    assert trip['result'] == {'other': True}
    assert 'ConnectorPluginRegistry' in trip['constructed'], 'Non-analysis tools must keep their existing composition'


def test_attention_analysis_reads_its_surface_before_the_market_readiness_gate(tmp_path):
    from ignis.domain.entities import ResearchMission
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    root, _, store = _prepared_completed_parent(tmp_path)
    attention = ResearchMission(title='Explore n8n attention', keywords=['n8n'], surface='ATTENTION')

    async def create():
        repository = SqliteTrendRepository(str(store))
        await repository.create_mission(attention)
        await repository.close()
    asyncio.run(create())
    with sqlite3.connect(store) as connection:
        connection.execute('CREATE INDEX extra_mission_index ON research_missions (status)')
    trip = _round_trip(tmp_path, root, store, attention.id, mode='analysis-only')
    assert trip['result']['refused'] is None, 'An Attention mission was refused by the Market readiness gate'
    assert 'ConnectorPluginRegistry' in trip['constructed'], 'Attention analysis keeps its full composition'


# --- In-process controls on the same composition objects ---------------------------------------------

def _caller_components(root):
    from ignis.infrastructure.caller_storage import CallerStorageScope
    from ignis.interfaces.mcp import server
    scope = CallerStorageScope(root)
    components = server._compose_caller_scope(scope)
    scope.components = components
    return scope, components


def test_analysis_grant_refuses_collection_mission_and_protected_writes(tmp_path):
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    before = _state(store)
    scope, components = _caller_components(root)

    async def exercise():
        analysis = await components.analysis()
        connection = analysis['repository']._get_connection()
        refused = []
        try:
            for statement in (
                "INSERT INTO observations (id) VALUES ('synthetic')",
                "UPDATE research_missions SET status = 'PENDING'",
                "DELETE FROM mission_evidence",
                "INSERT INTO runtime_configs (key, value, created_at, updated_at) VALUES ('k', 'v', 'x', 'x')",
                'DELETE FROM market_lexicons',
                'UPDATE research_workspaces SET name = name',
                'DELETE FROM platform_credentials',
                'CREATE TABLE extra_table (id TEXT)',
            ):
                try:
                    connection.execute(statement)
                except sqlite3.DatabaseError as error:
                    refused.append('not authorized' in str(error))
                connection.rollback()
        finally:
            connection.close()
            await analysis['repository'].close()
        return refused
    assert asyncio.run(exercise()) == [True] * 8
    assert _state(store) == before


def test_finite_parent_grant_still_refuses_analysis_writes(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    root, mission_id, store = _prepared_completed_parent(tmp_path)

    async def exercise():
        digest = await SqliteTrendRepository.supported_core_schema_digest()
        repository = await SqliteTrendRepository.open_existing_ready(str(store), expected_core_schema_digest=digest)
        connection = repository._get_connection()
        try:
            with pytest.raises(sqlite3.DatabaseError, match='not authorized'):
                connection.execute("INSERT INTO mission_claims (id) VALUES ('synthetic')")
        finally:
            connection.close()
    asyncio.run(exercise())


def test_guarded_snapshot_readers_use_only_their_borrowed_connection(tmp_path, monkeypatch):
    from ignis.infrastructure.persistence import evidence_snapshot
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    scope, components = _caller_components(root)
    readers, original = [], evidence_snapshot.read_evidence_snapshot

    async def capture(reader, target):
        readers.append((reader._get_connection() is reader._mem_conn, reader._mem_conn))
        return await original(reader, target)
    monkeypatch.setattr(evidence_snapshot, 'read_evidence_snapshot', capture)

    async def exercise():
        analysis = await components.analysis()
        await analysis['workspace_store'].load_mission_evidence_snapshot(mission_id)
        await analysis['repository'].close()
    asyncio.run(exercise())
    assert readers and all(identity for identity, _ in readers), 'A guarded reader used a fresh connection'
    with pytest.raises(sqlite3.ProgrammingError):
        readers[0][1].execute('SELECT 1')


def test_unprepared_store_is_reevaluated_and_only_prepared_composition_is_cached(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    root, mission_id, store = _prepared_completed_parent(tmp_path, progress=False)
    scope, components = _caller_components(root)

    async def exercise():
        first = await components.analysis()
        prepare = SqliteTrendRepository(str(store))
        await prepare._ensure_progress_schema()
        await prepare.close()
        second = await components.analysis()
        third = await components.analysis()
        with sqlite3.connect(store) as connection:
            connection.execute('DROP TRIGGER mission_progress_events_validate_update')
        from ignis.domain.exceptions import RepositoryException
        refused = False
        try:
            await (await components.analysis())['repository'].get_mission(mission_id)
        except RepositoryException:
            refused = True
        await second['repository'].close()
        return first, second, third, refused
    first, second, third, refused = asyncio.run(exercise())
    assert first is components, 'An unprepared store keeps the existing composition'
    assert second is not components and second['repository']._existing_ready is not None
    assert third is second, 'The validated prepared composition is reused'
    assert refused, 'Drift after preparation must refuse on the next read'
    assert components._full is None, 'Analysis composition must not build the full provider composition'


def test_lifecycle_owns_only_realized_repositories_and_roots_never_share(tmp_path):
    root_a, mission_a, _ = _prepared_completed_parent(tmp_path / 'a')
    root_b, mission_b, _ = _prepared_completed_parent(tmp_path / 'b')
    _, components_a = _caller_components(root_a)
    _, components_b = _caller_components(root_b)

    async def exercise():
        assert components_a.repositories() == []
        analysis_a, analysis_b = await components_a.analysis(), await components_b.analysis()
        owned = components_a.repositories()
        assert owned == [analysis_a['repository']] and components_a._full is None
        assert analysis_a['repository'] is not analysis_b['repository']
        assert str(root_a) in analysis_a['repository']._db_path and str(root_b) in analysis_b['repository']._db_path
        assert await analysis_a['repository'].get_mission(mission_b) is None
        assert await analysis_b['repository'].get_mission(mission_a) is None
        for repository in owned + components_b.repositories():
            await repository.close()
    asyncio.run(exercise())


def test_borrowed_snapshot_readers_keep_caller_scope_checks_on_both_paths(tmp_path, monkeypatch):
    from fastmcp.exceptions import ToolError
    from ignis.infrastructure.persistence import evidence_snapshot
    root, mission_id, store = _prepared_completed_parent(tmp_path)
    scope, components = _caller_components(root)
    observed, original = [], evidence_snapshot.read_evidence_snapshot
    invalidate = {'now': False}

    async def capture(reader, target):
        if invalidate['now']:
            (root / '.fnignis' / '.env').write_text('# changed after admission\n')
        try:
            observed.append(reader._get_connection() is reader._mem_conn)
        except ToolError as error:
            observed.append(str(error))
            raise
        return await original(reader, target)
    monkeypatch.setattr(evidence_snapshot, 'read_evidence_snapshot', capture)
    analysis = asyncio.run(components.analysis())
    repository = analysis['repository']

    # load_mission_evidence_snapshot: borrowed identity, then refusal once the scope is invalidated.
    asyncio.run(analysis['workspace_store'].load_mission_evidence_snapshot(mission_id))
    # _commit_snapshot on a held write transaction: same identity, same refusal.
    connection = repository._get_connection()
    connection.execute('BEGIN IMMEDIATE')
    try:
        repository._commit_snapshot(connection, mission_id)
        invalidate['now'] = True
        with pytest.raises(ToolError):
            repository._commit_snapshot(connection, mission_id)
    finally:
        connection.rollback()
        connection.close()
    (root / '.fnignis' / '.env').unlink()
    scope_two, components_two = _caller_components(root)
    analysis_two = asyncio.run(components_two.analysis())
    invalidate['now'] = True
    with pytest.raises(ToolError):
        asyncio.run(analysis_two['workspace_store'].load_mission_evidence_snapshot(mission_id))
    assert observed[:2] == [True, True], observed
    # A config file appearing after admission is refused by the scope check (mode 0644 is never accepted).
    assert observed[2:] == ['CALLER_CONFIG_REFUSED', 'CALLER_CONFIG_REFUSED'], observed
