"""The caller root through a real in-process MCP client on both protocol eras (FR-032, SC-018).

The root is the folder the agent was opened in. Whatever roots the client sends, and whether it
negotiates 2026-07-28 or the legacy handshake, mission tools read the opened folder's store.
Storage is the disposable Attention relay fixture on SQLite file, SQLite memory and PostgreSQL.
"""
import json

import pytest
from fastmcp import Client

from tests.caller_roots import bind_caller_root
from test_mission_relay_mcp import attention_case  # noqa: F401 -- readable selected-mission fixture
from test_mission_relay_read_boundary import (
    _state,
    relay_case,  # noqa: F401 -- storage fixture behind attention_case
)

MODERN = '2026-07-28'


def _bind(monkeypatch, components, opened):
    """Open the agent in ``opened`` and serve the fixture store as that folder's components."""
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware
    from ignis.interfaces.mcp import server
    composed = []

    def compose(scope):
        composed.append(scope.root)
        if scope.root.resolve() != opened.resolve():
            raise AssertionError('Compose received a root other than the opened folder')
        return components

    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            monkeypatch.setattr(middleware, 'compose', compose)
    bind_caller_root(monkeypatch, opened)
    return server.mcp, composed


def _folder(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    (path / '.fnignis').mkdir()
    return path


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', (MODERN, 'legacy'))
@pytest.mark.parametrize('roots', ('none', 'several'))
async def test_opened_folder_is_the_root_whatever_roots_the_client_sends(attention_case, monkeypatch, tmp_path, mode, roots):  # noqa: F811
    case, missions, _runs = attention_case
    opened = _folder(tmp_path, 'repository')
    extra = _folder(tmp_path, 'extra-working-directory')
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    before = _state(case)
    app, composed = _bind(monkeypatch, {'repository': case.repository}, opened)
    asked = []

    async def client_roots(context):
        asked.append('roots')
        return [extra.as_uri(), opened.as_uri()]

    async with Client(app, roots=client_roots if roots == 'several' else None, mode=mode) as client:
        if mode == MODERN:
            assert client.protocol_version == MODERN
        snapshot = (await client.call_tool('get_mission_relay_snapshot', {
            'mission_id': str(missions[0].id), 'page_size': 2})).structured_content
        listed = json.loads((await client.call_tool('list_research_missions', {'limit': 5})).data)
        # Compared before exit: the caller lifespan closes an in-memory repository on shutdown.
        assert _state(case) == before
    assert snapshot['status'] == 'OK', snapshot
    assert snapshot['mission_id'] == str(missions[0].id)
    assert {row['id'] for row in listed} >= {str(mission.id) for mission in missions}
    assert composed and all(value == opened for value in composed)
    assert asked == [], 'Client roots must never be requested'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', (MODERN, 'legacy'))
async def test_refused_startup_folder_never_reaches_storage(attention_case, monkeypatch, tmp_path, mode):  # noqa: F811
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware
    from ignis.interfaces.mcp import server
    case, missions, _runs = attention_case
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    before = _state(case)
    app, composed = _bind(monkeypatch, {'repository': case.repository}, _folder(tmp_path, 'repository'))
    for middleware in server.mcp.middleware:
        if isinstance(middleware, CallerStorageMiddleware):
            # As if the agent host had started the server in the home directory.
            monkeypatch.setattr(middleware, '_startup_refused', True)
    async with Client(app, mode=mode) as client:
        result = await client.call_tool('get_mission_relay_snapshot', {
            'mission_id': str(missions[0].id), 'page_size': 2}, raise_on_error=False)
    assert result.is_error
    assert 'ROOT_REQUIRED category=STARTUP_ROOT_REFUSED' in result.content[0].text
    assert composed == [] and _state(case) == before
