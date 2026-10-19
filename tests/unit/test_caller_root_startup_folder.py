"""The caller root is the folder the agent was opened in (FR-032, revised 2026-10-19).

The middleware snapshots the server's working directory at startup; IGNIS_CALLER_ROOT is an
optional override. Client roots and the negotiated protocol era are never consulted. See
specs/014-evidence-factory/contracts/caller-root.md.
"""
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from mcp.types import ClientCapabilities

from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage

MODERN = '2026-07-28'
LEGACY = '2025-11-25'


def _consumer(*, protocol=MODERN, capability='ADVERTISED', client_roots=()):
    """Build the middleware where the server starts, as the agent host launches it."""
    calls = []

    async def roots():
        calls.append('roots_rpc')
        return SimpleNamespace(roots=[SimpleNamespace(uri=uri) for uri in client_roots])

    session = SimpleNamespace(list_roots=roots, protocol_version=protocol,
                              client_capabilities=None if capability == 'UNKNOWN'
                              else ClientCapabilities(roots={} if capability == 'ADVERTISED' else None))
    owner = SimpleNamespace(closed=False, caller_scopes={})
    fastmcp_context = SimpleNamespace(request_context=object(), session=session,
                                      lifespan_context={'mission_relay': owner},
                                      input_responses=None, request_state=None)
    context = SimpleNamespace(message=SimpleNamespace(name='list_research_missions', arguments={}),
                              fastmcp_context=fastmcp_context)

    def compose(scope):
        calls.append('compose')
        return {'root': scope.root}

    def runtime(scope, _owner):
        calls.append('runtime')
        return object()

    async def dispatch(_context):
        calls.append('dispatch')
        scope = current_caller_storage.get()
        assert scope is not None
        return {'selected_root': scope.root}

    return CallerStorageMiddleware(compose, runtime), context, dispatch, calls


def _refusal(category, capability='ADVERTISED'):
    return (f'ROOT_REQUIRED category={category} roots_capability={capability} '
            'rpc_error=UNKNOWN owner_state=UNKNOWN')


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', (MODERN, LEGACY))
@pytest.mark.parametrize('roots', ('none', 'one_foreign', 'several'))
@pytest.mark.parametrize('capability', ('ADVERTISED', 'NOT_ADVERTISED', 'UNKNOWN'))
async def test_startup_folder_is_the_root_whatever_the_client_sends(tmp_path, monkeypatch, protocol, roots, capability):
    opened = tmp_path / 'repository'
    opened.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(opened)
    client_roots = {'none': (), 'one_foreign': (other.as_uri(),), 'several': (opened.as_uri(), other.as_uri())}[roots]
    middleware, context, dispatch, calls = _consumer(protocol=protocol, capability=capability, client_roots=client_roots)
    result = await middleware.on_call_tool(context, dispatch)
    assert result == {'selected_root': opened}
    assert calls == ['compose', 'runtime', 'dispatch'], 'Client roots must never be requested'
    assert current_caller_storage.get() is None


@pytest.mark.asyncio
async def test_override_wins_over_the_startup_folder(tmp_path, monkeypatch):
    opened = tmp_path / 'repository'
    opened.mkdir()
    override = tmp_path / 'override'
    override.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(override))
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    assert (await middleware.on_call_tool(context, dispatch)) == {'selected_root': override}
    assert 'roots_rpc' not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize('place', ('home', 'filesystem_root'))
async def test_home_or_filesystem_root_startup_folder_refuses(tmp_path, monkeypatch, place):
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(home if place == 'home' else '/')
    middleware, context, dispatch, calls = _consumer()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('STARTUP_ROOT_REFUSED')
    assert calls == []
    assert not (home / '.fnignis').exists()


@pytest.mark.asyncio
async def test_replaced_startup_folder_refuses(tmp_path, monkeypatch):
    opened = tmp_path / 'repository'
    opened.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    monkeypatch.chdir(tmp_path)
    opened.rename(tmp_path / 'original')
    opened.mkdir()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('STARTUP_ROOT_CHANGED')
    assert calls == []


@pytest.mark.asyncio
async def test_invalid_override_refuses_without_falling_back_to_the_startup_folder(tmp_path, monkeypatch):
    opened = tmp_path / 'repository'
    opened.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', 'relative/PRIVATE_CONFIG_CANARY')
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('CONFIGURED_ROOT_INVALID')
    assert 'PRIVATE_' not in str(error.value)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('place', ('home_via_symlink', 'parent_of_home', 'world_writable', 'sticky', 'foreign_owner'))
async def test_unsuitable_startup_folders_refuse(tmp_path, monkeypatch, place):
    opened = tmp_path / 'repository'
    opened.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.setenv('HOME', str(tmp_path / 'elsewhere'))
    if place == 'home_via_symlink':
        alias = tmp_path / 'home-alias'
        alias.symlink_to(opened, target_is_directory=True)
        monkeypatch.setenv('HOME', str(alias))
    elif place == 'parent_of_home':
        (opened / 'user').mkdir()
        monkeypatch.setenv('HOME', str(opened / 'user'))
    elif place == 'world_writable':
        opened.chmod(0o777)
    elif place == 'sticky':
        opened.chmod(0o1755)
    else:
        import os
        real_uid = os.getuid()
        monkeypatch.setattr(os, 'getuid', lambda: real_uid + 1)
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('STARTUP_ROOT_REFUSED')
    assert calls == []
    assert not (opened / '.fnignis').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('attack', ('folder_becomes_symlink', 'parent_renamed'))
async def test_startup_folder_swaps_refuse(tmp_path, monkeypatch, attack):
    parent = tmp_path / 'projects'
    parent.mkdir()
    opened = parent / 'repository'
    opened.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    monkeypatch.chdir(tmp_path)
    if attack == 'folder_becomes_symlink':
        opened.rename(parent / 'original')
        opened.symlink_to(foreign, target_is_directory=True)
    else:
        parent.rename(tmp_path / 'original-projects')
        parent.mkdir()
        opened.mkdir()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('STARTUP_ROOT_CHANGED')
    assert calls == [] and list(foreign.iterdir()) == []


@pytest.mark.asyncio
async def test_host_workspace_may_name_the_opened_folder_through_a_symlinked_path(tmp_path, monkeypatch):
    real = tmp_path / 'real-projects'
    real.mkdir()
    opened = real / 'repository'
    opened.mkdir()
    alias = tmp_path / 'Projects'
    alias.symlink_to(real, target_is_directory=True)
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    context.message.arguments = {'host_workspace': str(alias / 'repository')}
    assert (await middleware.on_call_tool(context, dispatch)) == {'selected_root': opened.resolve()}
    assert context.message.arguments['host_workspace'] == str(opened.resolve()), \
        'The tool must receive the pinned root, not the symlinked spelling'


@pytest.mark.asyncio
@pytest.mark.parametrize('named', ('sibling', 'relative'))
async def test_host_workspace_naming_another_folder_refuses(tmp_path, monkeypatch, named):
    opened = tmp_path / 'repository'
    opened.mkdir()
    (tmp_path / 'sibling').mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    monkeypatch.chdir(opened)
    middleware, context, dispatch, calls = _consumer()
    context.message.arguments = {'host_workspace': str(tmp_path / 'sibling') if named == 'sibling' else '.'}
    with pytest.raises(ToolError, match='^CALLER_STORAGE_SCOPE_REFUSED$'):
        await middleware.on_call_tool(context, dispatch)
    assert 'dispatch' not in calls
