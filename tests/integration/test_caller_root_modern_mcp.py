"""Caller-root resolution through a real in-process MCP client on both protocol eras (T097, FR-032).

The FastMCP client negotiates either the 2026-07-28 era, where roots arrive through an
InputRequiredResult round trip, or the legacy handshake, where the server asks with roots/list.
Storage is the disposable Attention relay fixture on SQLite file, SQLite memory and PostgreSQL.
"""
import json

import pytest
from fastmcp import Client

from test_mission_relay_mcp import attention_case  # noqa: F401 -- readable selected-mission fixture
from test_mission_relay_read_boundary import (
    _state,
    relay_case,  # noqa: F401 -- storage fixture behind attention_case
)

MODERN = '2026-07-28'


def _install_middleware(monkeypatch, components, expected_root):
    """Bind the server's caller middleware to the fixture store, built after the env is set.

    The middleware snapshots IGNIS_CALLER_ROOT at construction, as at server start. A fresh instance
    built after the env is set supplies that snapshot to the import-time instance for this test.
    """
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware
    from ignis.interfaces.mcp import server
    composed = []

    def compose(scope):
        composed.append(scope.root)
        if scope.root.resolve() != expected_root.resolve():
            raise AssertionError('Compose received a root other than the expected caller root')
        return components

    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            startup = CallerStorageMiddleware(compose, middleware.runtime_for_scope)
            for name in ('compose', '_configured_present', '_configured_root', '_configured_identities'):
                monkeypatch.setattr(middleware, name, getattr(startup, name))
            return server.mcp, composed
    raise AssertionError('The server has no caller-storage middleware')


async def _read_both(client, mission_id):
    snapshot = (await client.call_tool('get_mission_relay_snapshot', {
        'mission_id': str(mission_id), 'page_size': 2})).structured_content
    listed = json.loads((await client.call_tool('list_research_missions', {'limit': 5})).data)
    return snapshot, listed


def _root(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    (path / '.fnignis').mkdir()
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', (MODERN, 'legacy'))
async def test_client_roots_resolve_on_both_eras_without_a_configured_root(attention_case, monkeypatch, tmp_path, mode):  # noqa: F811
    case, missions, _runs = attention_case
    root = _root(tmp_path, 'caller')
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    before = _state(case)
    app, composed = _install_middleware(monkeypatch, {'repository': case.repository}, root)
    async with Client(app, roots=[root.as_uri()], mode=mode) as client:
        assert client.protocol_version == (MODERN if mode == MODERN else client.protocol_version)
        if mode == 'legacy':
            assert client.protocol_version != MODERN
        snapshot, listed = await _read_both(client, missions[0].id)
        # Compared before exit: the caller lifespan closes an in-memory repository on shutdown.
        assert _state(case) == before
    assert snapshot['status'] == 'OK', snapshot
    assert snapshot['mission_id'] == str(missions[0].id)
    assert {row['id'] for row in listed} >= {str(mission.id) for mission in missions}
    assert composed and all(value == root for value in composed)


@pytest.mark.asyncio
async def test_modern_configured_root_wins_over_client_roots(attention_case, monkeypatch, tmp_path):  # noqa: F811
    case, missions, _runs = attention_case
    configured = _root(tmp_path, 'configured')
    client_root = _root(tmp_path, 'client')
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(configured))
    app, composed = _install_middleware(monkeypatch, {'repository': case.repository}, configured)
    asked = []

    async def roots_handler(context):
        asked.append('roots')
        return [client_root.as_uri()]

    async with Client(app, roots=roots_handler, mode=MODERN) as client:
        snapshot, listed = await _read_both(client, missions[0].id)
    assert snapshot['status'] == 'OK'
    assert {row['id'] for row in listed} >= {str(mission.id) for mission in missions}
    assert asked == [], 'A configured root on a modern connection must not ask the client for roots'
    assert composed and all(value == configured for value in composed)


@pytest.mark.asyncio
async def test_legacy_configured_root_must_equal_client_root(attention_case, monkeypatch, tmp_path):  # noqa: F811
    case, missions, _runs = attention_case
    configured = _root(tmp_path, 'configured')
    client_root = _root(tmp_path, 'client')
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(configured))
    app, composed = _install_middleware(monkeypatch, {'repository': case.repository}, configured)
    async with Client(app, roots=[client_root.as_uri()], mode='legacy') as client:
        result = await client.call_tool('get_mission_relay_snapshot', {
            'mission_id': str(missions[0].id), 'page_size': 2}, raise_on_error=False)
    assert result.is_error
    assert 'ROOT_REQUIRED category=ROOT_SCOPE_MISMATCH roots_capability=ADVERTISED' in result.content[0].text
    assert composed == []


@pytest.mark.asyncio
async def test_modern_client_without_roots_or_configured_root_is_refused(attention_case, monkeypatch, tmp_path):  # noqa: F811
    case, missions, _runs = attention_case
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    before = _state(case)
    app, composed = _install_middleware(monkeypatch, {'repository': case.repository}, tmp_path)
    async with Client(app, mode=MODERN) as client:
        result = await client.call_tool('get_mission_relay_snapshot', {
            'mission_id': str(missions[0].id), 'page_size': 2}, raise_on_error=False)
    assert result.is_error
    assert 'ROOT_REQUIRED category=CONFIGURED_ROOT_REQUIRED roots_capability=NOT_ADVERTISED' in result.content[0].text
    assert composed == [] and _state(case) == before


@pytest.mark.asyncio
async def test_modern_client_that_cannot_answer_roots_never_reaches_storage(attention_case, monkeypatch, tmp_path):  # noqa: F811
    case, missions, _runs = attention_case
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    before = _state(case)
    app, composed = _install_middleware(monkeypatch, {'repository': case.repository}, tmp_path)

    async def declining(context):
        raise RuntimeError('client declines roots')

    async with Client(app, roots=declining, mode=MODERN) as client:
        with pytest.raises(Exception) as error:
            await client.call_tool('get_mission_relay_snapshot', {
                'mission_id': str(missions[0].id), 'page_size': 2})
    assert 'declines roots' in str(error.value)
    assert composed == [] and _state(case) == before
