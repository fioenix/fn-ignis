"""Operator startup-root authority controls through the actual offline middleware consumer."""
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from mcp.types import ClientCapabilities
from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage


def _consumer(root, capability, *, native_roots=(), rpc_failure=False, arguments=None):
    calls = []
    async def roots():
        calls.append('roots_rpc')
        if rpc_failure: raise RuntimeError('PRIVATE_RPC_CANARY')
        return SimpleNamespace(roots=[SimpleNamespace(uri=value) for value in native_roots])
    session = SimpleNamespace(list_roots=roots)
    if capability != 'UNKNOWN': session.client_capabilities = ClientCapabilities(roots={} if capability == 'ADVERTISED' else None)
    owner = SimpleNamespace(closed=False, caller_scopes={})
    context = SimpleNamespace(message=SimpleNamespace(name='propose_research_workspace', arguments=arguments or {}),
        fastmcp_context=SimpleNamespace(request_context=object(),session=session,lifespan_context={'mission_relay':owner}))
    def compose(scope):
        calls.append('compose')
        return {'root':scope.root}
    def runtime(scope, _owner):
        calls.append('runtime')
        return object()
    async def dispatch(_context):
        calls.append('dispatch')
        scope = current_caller_storage.get()
        assert scope is not None
        return {'selected_root':scope.root,'database':scope.database}
    return CallerStorageMiddleware(compose,runtime), context, dispatch, calls


@pytest.mark.asyncio
async def test_explicit_not_advertised_uses_only_snapshotted_operator_startup_root(tmp_path, monkeypatch):
    root=tmp_path/'approved';root.mkdir()
    foreign=tmp_path/'foreign';foreign.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT',str(root))
    middleware, context, dispatch, calls=_consumer(root,'NOT_ADVERTISED',arguments={'host_workspace':str(root)})
    monkeypatch.setenv('IGNIS_CALLER_ROOT',str(foreign))
    result=await middleware.on_call_tool(context,dispatch)
    assert result=={'selected_root':root,'database':root/'.fnignis/canonical.sqlite3'}
    assert calls==['compose','runtime','dispatch']
    assert current_caller_storage.get() is None
    assert not (root/'.fnignis').exists() and not (foreign/'.fnignis').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('case',('missing','unknown','model_path'))
async def test_configured_authority_never_comes_from_missing_capability_or_model_arguments(tmp_path, monkeypatch, case):
    root=tmp_path/'approved';root.mkdir();foreign=tmp_path/'foreign';foreign.mkdir()
    if case=='missing':monkeypatch.delenv('IGNIS_CALLER_ROOT',raising=False)
    else:monkeypatch.setenv('IGNIS_CALLER_ROOT',str(root))
    middleware,context,dispatch,calls=_consumer(root,'UNKNOWN' if case=='unknown' else 'NOT_ADVERTISED',
        arguments={'host_workspace':str(foreign)})
    with pytest.raises(ToolError) as error:await middleware.on_call_tool(context,dispatch)
    expected = {
        'missing': 'ROOT_REQUIRED category=CONFIGURED_ROOT_REQUIRED roots_capability=NOT_ADVERTISED rpc_error=UNKNOWN owner_state=UNKNOWN',
        'unknown': 'ROOT_REQUIRED category=ROOT_COUNT_INVALID roots_capability=UNKNOWN rpc_error=UNKNOWN owner_state=UNKNOWN',
        'model_path': 'CALLER_STORAGE_SCOPE_REFUSED',
    }
    assert str(error.value) == expected[case]
    assert all(value not in calls for value in ('compose','runtime','dispatch'))
    assert not (root/'.fnignis').exists() and not (foreign/'.fnignis').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('case,category',(
    ('valid',None),('missing','ROOT_COUNT_INVALID'),('ambiguous','ROOT_COUNT_INVALID'),
    ('rpc','ROOTS_RPC_UNAVAILABLE'),('malformed','ROOT_URI_INVALID'),
    ('mismatch','ROOT_SCOPE_MISMATCH'),('bad_config','CONFIGURED_ROOT_INVALID'),
    ('unknown','ROOT_CAPABILITY_UNKNOWN'),
))
async def test_advertised_native_roots_remain_authoritative_without_configured_fallback(tmp_path, monkeypatch, case, category):
    root=tmp_path/'approved';root.mkdir();foreign=tmp_path/'foreign';foreign.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT','relative/PRIVATE_CONFIG_CANARY' if case=='bad_config' else str(root))
    native=[root.as_uri()]
    if case=='missing':native=[]
    if case=='ambiguous':native.append(foreign.as_uri())
    if case=='malformed':native=['https://PRIVATE_URI_CANARY/']
    if case=='mismatch':native=[foreign.as_uri()]
    middleware,context,dispatch,calls=_consumer(root,'UNKNOWN' if case=='unknown' else 'ADVERTISED',
        native_roots=native,rpc_failure=case=='rpc')
    if category is None:
        assert (await middleware.on_call_tool(context,dispatch))['selected_root']==root
        assert calls==['roots_rpc','compose','runtime','dispatch']
    else:
        with pytest.raises(ToolError) as error:await middleware.on_call_tool(context,dispatch)
        capability = 'UNKNOWN' if case == 'unknown' else 'ADVERTISED'
        assert str(error.value) == (f'ROOT_REQUIRED category={category} roots_capability={capability} '
                                   'rpc_error=UNKNOWN owner_state=UNKNOWN')
        assert 'PRIVATE_' not in str(error.value) and str(root) not in str(error.value)
        assert all(value not in calls for value in ('compose','runtime','dispatch'))
    assert not (root/'.fnignis').exists() and not (foreign/'.fnignis').exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('attack',('initial_symlink','replaced','later_symlink'))
async def test_configured_root_identity_is_pinned_before_first_request(tmp_path, monkeypatch, attack):
    root=tmp_path/'approved';foreign=tmp_path/'foreign';foreign.mkdir()
    if attack=='initial_symlink':root.symlink_to(foreign,target_is_directory=True)
    else:root.mkdir()
    monkeypatch.setenv('IGNIS_CALLER_ROOT',str(root))
    middleware,context,dispatch,calls=_consumer(root,'NOT_ADVERTISED')
    if attack!='initial_symlink':
        root.rename(tmp_path/'original')
        if attack=='replaced':root.mkdir()
        else:root.symlink_to(foreign,target_is_directory=True)
    with pytest.raises(ToolError) as error:await middleware.on_call_tool(context,dispatch)
    expected='CONFIGURED_ROOT_INVALID' if attack=='initial_symlink' else 'CONFIGURED_ROOT_CHANGED'
    assert str(error.value) == (f'ROOT_REQUIRED category={expected} roots_capability=NOT_ADVERTISED '
                               'rpc_error=UNKNOWN owner_state=UNKNOWN')
    assert calls==[] and not (foreign/'.fnignis').exists()
