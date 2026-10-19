"""Caller-root resolution on MCP 2026-07-28 connections, where roots/list is forbidden (FR-032).

On a modern connection a configured startup root wins without asking the client; without one,
roots are requested through an InputRequiredResult and validated on the retry. Legacy
connections keep roots/list. See specs/014-evidence-factory/contracts/caller-root.md.
"""
from types import SimpleNamespace

import mcp_types
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.tools.base import InputRequiredToolResult
from mcp.types import ClientCapabilities

from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage

MODERN = '2026-07-28'
LEGACY = '2025-11-25'
KEY = 'ignis_caller_roots'
TOOL = 'propose_research_workspace'


def _consumer(*, protocol, capability='ADVERTISED', native_roots=(), input_responses=None,
              request_state=None, tool=TOOL):
    calls = []

    async def roots():
        calls.append('roots_rpc')
        if protocol == MODERN:
            raise RuntimeError('server-initiated requests are forbidden on modern connections')
        return SimpleNamespace(roots=[SimpleNamespace(uri=value) for value in native_roots])

    session = SimpleNamespace(list_roots=roots, protocol_version=protocol,
                              client_capabilities=None if capability == 'UNKNOWN'
                              else ClientCapabilities(roots={} if capability == 'ADVERTISED' else None))
    owner = SimpleNamespace(closed=False, caller_scopes={})
    fastmcp_context = SimpleNamespace(request_context=object(), session=session,
                                      lifespan_context={'mission_relay': owner},
                                      input_responses=input_responses, request_state=request_state)
    context = SimpleNamespace(message=SimpleNamespace(name=tool, arguments={}), fastmcp_context=fastmcp_context)

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


def _roots_answer(*uris):
    return {KEY: mcp_types.ListRootsResult(roots=[mcp_types.Root(uri=uri) for uri in uris])}


async def _ask(middleware, context, dispatch):
    result = await middleware.on_call_tool(context, dispatch)
    assert isinstance(result, InputRequiredToolResult), 'expected a roots request, not a resolved call'
    return result.input_required


def _refusal(category, capability='ADVERTISED'):
    return (f'ROOT_REQUIRED category={category} roots_capability={capability} '
            'rpc_error=UNKNOWN owner_state=UNKNOWN')


@pytest.mark.asyncio
async def test_modern_configured_root_resolves_without_asking_the_client(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(root))
    middleware, context, dispatch, calls = _consumer(protocol=MODERN)
    result = await middleware.on_call_tool(context, dispatch)
    assert result == {'selected_root': root}
    assert calls == ['compose', 'runtime', 'dispatch']
    assert current_caller_storage.get() is None


@pytest.mark.asyncio
async def test_modern_configured_root_is_not_compared_with_client_roots(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(root))
    middleware, context, dispatch, calls = _consumer(
        protocol=MODERN, input_responses=_roots_answer(foreign.as_uri()), request_state='echoed')
    assert (await middleware.on_call_tool(context, dispatch)) == {'selected_root': root}
    assert 'roots_rpc' not in calls


@pytest.mark.asyncio
@pytest.mark.parametrize('attack,category', (('invalid', 'CONFIGURED_ROOT_INVALID'),
                                             ('changed', 'CONFIGURED_ROOT_CHANGED')))
async def test_modern_broken_configured_root_refuses_without_asking(tmp_path, monkeypatch, attack, category):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', 'relative/PRIVATE_CONFIG_CANARY' if attack == 'invalid' else str(root))
    middleware, context, dispatch, calls = _consumer(protocol=MODERN)
    if attack == 'changed':
        root.rename(tmp_path / 'original')
        root.mkdir()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal(category)
    assert 'PRIVATE_' not in str(error.value)
    assert calls == []


@pytest.mark.asyncio
async def test_modern_without_configured_root_asks_for_roots_once(tmp_path, monkeypatch):
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    middleware, context, dispatch, calls = _consumer(protocol=MODERN)
    asked = await _ask(middleware, context, dispatch)
    assert set(asked.input_requests) == {KEY}
    assert isinstance(asked.input_requests[KEY], mcp_types.ListRootsRequest)
    assert asked.request_state
    assert calls == []


@pytest.mark.asyncio
async def test_modern_retry_with_valid_root_resolves_it(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    first, context, dispatch, _ = _consumer(protocol=MODERN)
    state = (await _ask(first, context, dispatch)).request_state
    middleware, context, dispatch, calls = _consumer(
        protocol=MODERN, input_responses=_roots_answer(root.as_uri()), request_state=state)
    assert (await middleware.on_call_tool(context, dispatch)) == {'selected_root': root}
    assert calls == ['compose', 'runtime', 'dispatch']


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,category', (
    ('none', 'ROOT_COUNT_INVALID'),
    ('two', 'ROOT_COUNT_INVALID'),
    ('remote_host', 'ROOT_URI_INVALID'),
    ('missing_dir', 'ROOT_PATH_INVALID'),
    ('query', 'ROOT_URI_INVALID'),
    ('fragment', 'ROOT_URI_INVALID'),
))
async def test_modern_retry_validates_returned_roots_with_the_legacy_rules(tmp_path, monkeypatch, answer, category):
    root = tmp_path / 'approved'
    root.mkdir()
    other = tmp_path / 'other'
    other.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    first, context, dispatch, _ = _consumer(protocol=MODERN)
    state = (await _ask(first, context, dispatch)).request_state
    uris = {'none': (), 'two': (root.as_uri(), other.as_uri()), 'remote_host': ('file://PRIVATE_HOST_CANARY/tmp',),
            'missing_dir': ((tmp_path / 'absent').as_uri(),), 'query': (root.as_uri() + '?PRIVATE_QUERY_CANARY',),
            'fragment': (root.as_uri() + '#PRIVATE_FRAGMENT_CANARY',)}[answer]
    middleware, context, dispatch, calls = _consumer(
        protocol=MODERN, input_responses=_roots_answer(*uris), request_state=state)
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal(category)
    assert 'PRIVATE_' not in str(error.value)
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize('responses', (None, {}, {KEY: mcp_types.ErrorData(code=-32601, message='declined')}))
async def test_modern_retry_without_roots_is_protocol_forbidden(tmp_path, monkeypatch, responses):
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    first, context, dispatch, _ = _consumer(protocol=MODERN)
    state = (await _ask(first, context, dispatch)).request_state
    middleware, context, dispatch, calls = _consumer(protocol=MODERN, input_responses=responses, request_state=state)
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('ROOTS_REQUEST_FORBIDDEN')
    assert calls == []


@pytest.mark.asyncio
async def test_modern_retry_for_another_tool_refuses_echoed_state(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    first, context, dispatch, _ = _consumer(protocol=MODERN, tool='list_research_missions')
    state = (await _ask(first, context, dispatch)).request_state
    middleware, context, dispatch, calls = _consumer(
        protocol=MODERN, input_responses=_roots_answer(root.as_uri()), request_state=state)
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('ROOTS_REQUEST_STATE_INVALID')
    assert calls == []


@pytest.mark.asyncio
async def test_modern_not_advertised_keeps_the_configured_root_path(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(root))
    middleware, context, dispatch, calls = _consumer(protocol=MODERN, capability='NOT_ADVERTISED')
    assert (await middleware.on_call_tool(context, dispatch)) == {'selected_root': root}
    assert calls == ['compose', 'runtime', 'dispatch']


@pytest.mark.asyncio
async def test_legacy_connection_keeps_roots_rpc_and_configured_equality(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(root))
    middleware, context, dispatch, calls = _consumer(protocol=LEGACY, native_roots=[foreign.as_uri()])
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('ROOT_SCOPE_MISMATCH')
    assert calls == ['roots_rpc']


@pytest.mark.asyncio
async def test_modern_unknown_capability_refuses_without_a_forbidden_roots_request(tmp_path, monkeypatch):
    root = tmp_path / 'approved'
    root.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT', str(root))
    middleware, context, dispatch, calls = _consumer(protocol=MODERN, capability='UNKNOWN')
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('ROOT_CAPABILITY_UNKNOWN', capability='UNKNOWN')
    assert calls == []


@pytest.mark.asyncio
async def test_modern_not_advertised_without_configured_root_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv('IGNIS_CALLER_ROOT', raising=False)
    middleware, context, dispatch, calls = _consumer(protocol=MODERN, capability='NOT_ADVERTISED')
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, dispatch)
    assert str(error.value) == _refusal('CONFIGURED_ROOT_REQUIRED', capability='NOT_ADVERTISED')
    assert calls == []

