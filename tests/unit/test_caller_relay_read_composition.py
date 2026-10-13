"""Cold caller-bound relay reads use the caller's own storage identity without the full composition.

Round trips run the real FastMCP server in a subprocess admitted through IGNIS_CALLER_ROOT (in-memory
protocol client plus loopback HTTP). In-process controls exercise the same runtime read service.
Nothing here touches a real store.
"""
import asyncio
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from tests.unit import test_caller_analysis_composition as composition
from tests.unit import test_caller_youtube_pilot_cli as cli_tests

COLD = r'''
import asyncio, json, sys, urllib.request
from datetime import datetime, timedelta, timezone
import httpx
store, mission_id, run_id = sys.argv[1], sys.argv[2], sys.argv[3]
log = {'init_components': 0, 'create_repository': 0, 'constructed': [], 'network': []}
async def refused_send(self, request, **kwargs):
    log['network'].append(request.url.host)
    raise RuntimeError('network refused')
httpx.AsyncClient.send = refused_send
from ignis.interfaces.mcp import server
original_init, original_create = server._init_components, server.create_repository
def counted_init(*args, **kwargs):
    log['init_components'] += 1
    return original_init(*args, **kwargs)
def counted_create(*args, **kwargs):
    log['create_repository'] += 1
    return original_create(*args, **kwargs)
server._init_components, server.create_repository = counted_init, counted_create
for name in ('TikTokAuthManager', 'ThreadsAuthManager', 'InstagramAuthManager', 'ThreadsBrowserAuthManager',
             'InstagramBrowserAuthManager', 'GoogleTrendsRssPlugin', 'ConnectorPluginRegistry', 'RuntimeConfigManager'):
    cls = getattr(server, name)
    def recording(self, *args, _init=cls.__init__, _label=name, **kwargs):
        log['constructed'].append(_label)
        return _init(self, *args, **kwargs)
    cls.__init__ = recording
from fastmcp import Client

async def main():
    out = {}
    async with Client(server.mcp) as client:
        snapshot = {'mission_id': mission_id, 'page_size': 2}
        opened = {'mission_id': mission_id, 'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
        if run_id != '-':
            snapshot['run_id'] = opened['run_id'] = run_id
        result = await client.call_tool('get_mission_relay_snapshot', snapshot, raise_on_error=False)
        out['snapshot'] = None if result.is_error else (result.structured_content or {}).get('status')
        out['snapshot_reason'] = None if result.is_error else (result.structured_content or {}).get('reason_code')
        result = await client.call_tool('open_mission_relay', opened, raise_on_error=False)
        payload = None if result.is_error else result.structured_content
        out['open'] = None if payload is None else payload.get('status')
        if payload and payload.get('status') == 'OK':
            def fetch(url):
                with urllib.request.urlopen(url, timeout=5) as response:
                    return response.status
            out['viewer_http'] = await asyncio.to_thread(fetch, payload['url'])
    return out

result = asyncio.run(main())
print(json.dumps({'result': result, 'log': log}))
'''


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _cold(tmp_path, root, mission_id, run_id='-'):
    store = root / '.fnignis' / 'canonical.sqlite3'
    env = {**cli_tests._env(tmp_path), 'IGNIS_CALLER_ROOT': str(root)}
    result = subprocess.run([sys.executable, '-c', COLD, str(store), str(mission_id), str(run_id)],
                            capture_output=True, text=True, timeout=120, env=env, cwd=str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _run_id(store):
    with sqlite3.connect(store.as_uri() + '?mode=ro', uri=True) as connection:
        return connection.execute('SELECT id FROM mission_run_journals').fetchone()[0]


def test_cold_snapshot_and_open_read_the_caller_store_without_full_composition(tmp_path):
    root, mission_id, store = composition._prepared_completed_parent(tmp_path)
    before = _sha(store)
    trip = _cold(tmp_path, root, mission_id, _run_id(store))
    assert trip['result'] == {'snapshot': 'OK', 'snapshot_reason': None, 'open': 'OK', 'viewer_http': 200}
    assert trip['log']['init_components'] == 0, 'A cold relay read realized the full provider composition'
    assert trip['log']['create_repository'] == 0 and trip['log']['constructed'] == []
    assert trip['log']['network'] == [] and _sha(store) == before


@pytest.mark.parametrize('state', ('missing', 'old'))
def test_cold_unavailable_caller_store_refuses_read_only_without_composition(tmp_path, state):
    from uuid import uuid4
    root = tmp_path / 'caller'
    (root / '.fnignis').mkdir(parents=True)
    store = root / '.fnignis' / 'canonical.sqlite3'
    if state == 'old':
        with sqlite3.connect(store) as connection:
            connection.execute('CREATE TABLE research_missions (id TEXT PRIMARY KEY)')
    before = _sha(store)
    trip = _cold(tmp_path, root, uuid4())
    assert trip['result'] == {'snapshot': 'UNAVAILABLE', 'snapshot_reason': 'READ_UNAVAILABLE', 'open': 'UNAVAILABLE'}
    assert trip['log']['init_components'] == 0 and trip['log']['constructed'] == []
    assert _sha(store) == before and store.exists() == (before is not None)


# --- In-process controls on the runtime read service ---------------------------------------------

def _runtime(root):
    from ignis.infrastructure.caller_storage import CallerStorageScope
    from ignis.interfaces.mcp import server
    scope = CallerStorageScope(root)
    scope.components = server._compose_caller_scope(scope)
    runtime = server._MissionRelayRuntime(caller_scope=scope)
    scope.runtime = runtime
    return scope, runtime


async def _release(*scopes):
    """Close each runtime, then every repository its caller composition already owns."""
    for scope in scopes:
        try:
            await scope.runtime.close()
        finally:
            for repository in scope.components.repositories():
                await repository.close()


def _keep_global_runtime_config(monkeypatch):
    """Intentional full compositions rebind the process singleton; restore it after the test."""
    from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
    monkeypatch.setattr(RuntimeConfigManager, '_singleton', RuntimeConfigManager._singleton)


def test_root_b_relay_read_leaves_the_global_runtime_config_lookup_on_root_a(tmp_path, monkeypatch):
    from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
    _keep_global_runtime_config(monkeypatch)
    root_a, _, _ = composition._prepared_completed_parent(tmp_path / 'a')
    root_b, mission_b, store_b = composition._prepared_completed_parent(tmp_path / 'b')

    async def exercise():
        scope_a, runtime_a = _runtime(root_a)
        scope_b, runtime_b = _runtime(root_b)
        try:
            manager_a = scope_a.components['runtime_config_manager']
            assert RuntimeConfigManager.get_instance() is manager_a
            from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
            from uuid import UUID
            result = await runtime_b.snapshot(MissionRelayReadRequest(
                mission_id=mission_b, run_id=UUID(_run_id(store_b)), page_size=1))
            assert type(result).__name__ != 'MissionRelayReadFailure', result
            assert RuntimeConfigManager.get_instance() is manager_a, 'A root B relay read replaced the global lookup'
            assert scope_b.components._full is None
        finally:
            await _release(scope_a, scope_b)
    asyncio.run(exercise())


def test_cold_reader_uses_the_caller_dsn_never_the_global_one(tmp_path, monkeypatch):
    from pydantic import SecretStr
    from ignis.interfaces.mcp import server
    root, mission_id, store = composition._prepared_completed_parent(tmp_path)
    decoy = tmp_path / 'global-decoy.sqlite3'
    monkeypatch.setattr(server.settings, 'DATABASE_URL', SecretStr(f'sqlite:///{decoy}'))

    async def exercise():
        scope, runtime = _runtime(root)
        try:
            return runtime._use_case()._reader
        finally:
            await _release(scope)
    reader = asyncio.run(exercise())
    assert reader._repository is None and reader._file_uri == store.resolve().as_uri() + '?mode=ro'
    assert not decoy.exists(), 'A caller-mode read reached the global storage identity'


def test_existing_owner_repositories_are_borrowed_before_any_cold_reader(tmp_path, monkeypatch):
    _keep_global_runtime_config(monkeypatch)
    root, mission_id, store = composition._prepared_completed_parent(tmp_path)

    async def exercise():
        scope, runtime = _runtime(root)
        try:
            analysis = await scope.components.analysis()
            borrowed_analysis = runtime._use_case()._reader._repository
        finally:
            await _release(scope)
        scope_full, runtime_full = _runtime(root)
        try:
            full = scope_full.components['repository']
            borrowed_full = runtime_full._use_case()._reader._repository
        finally:
            await _release(scope_full)
        return analysis['repository'], borrowed_analysis, full, borrowed_full
    analysis, borrowed_analysis, full, borrowed_full = asyncio.run(exercise())
    assert borrowed_analysis is analysis and borrowed_full is full
