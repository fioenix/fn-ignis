"""Offline middleware refusal diagnostics; no native authority or storage bootstrap claim."""
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage


@pytest.mark.asyncio
@pytest.mark.parametrize("case,category", (
    ("context", "REQUEST_CONTEXT_ABSENT"),
    ("filesystem_root", "STARTUP_ROOT_REFUSED"),
    ("home", "STARTUP_ROOT_REFUSED"),
    ("replaced", "STARTUP_ROOT_CHANGED"),
    ("owner_absent", "OWNER_LIFESPAN_UNAVAILABLE"),
    ("owner_closed", "OWNER_LIFESPAN_UNAVAILABLE"),
))
async def test_root_refusal_exposes_only_fixed_category_and_never_bypasses(case, category, tmp_path, monkeypatch):
    protected = "PRIVATE_PAYLOAD_CANARY_credential_transcript"
    calls = []
    opened = tmp_path / "repository"
    opened.mkdir()
    monkeypatch.delenv("IGNIS_CALLER_ROOT", raising=False)
    monkeypatch.setenv("HOME", str(opened if case == "home" else tmp_path / "elsewhere"))
    monkeypatch.chdir("/" if case == "filesystem_root" else opened)

    def forbidden(*_args):
        calls.append("compose")
        raise AssertionError("Refused root reached storage composition")

    async def next_call(_context):
        calls.append("dispatch")
        raise AssertionError("Refused root reached mission dispatch")

    async def roots():
        calls.append("roots_rpc")
        raise AssertionError("Client roots must never be requested")

    owner = None if case == "owner_absent" else SimpleNamespace(closed=case == "owner_closed", caller_scopes={})
    ctx = SimpleNamespace(request_context=object(), session=SimpleNamespace(list_roots=roots),
        lifespan_context={"mission_relay": owner})
    if case == "context":
        ctx = None
    context = SimpleNamespace(message=SimpleNamespace(name="get_mission_analysis",
        arguments={"mission_id": protected}), fastmcp_context=ctx)
    middleware = CallerStorageMiddleware(forbidden, forbidden)
    if case == "replaced":
        monkeypatch.chdir(tmp_path)
        opened.rename(tmp_path / "original")
        opened.mkdir()
    with pytest.raises(ToolError) as error:
        await middleware.on_call_tool(context, next_call)
    text = str(error.value)
    owner_state = "ABSENT" if case == "owner_absent" else "CLOSED" if case == "owner_closed" else "UNKNOWN"
    assert text == (f"ROOT_REQUIRED category={category} roots_capability=UNKNOWN "
                    f"rpc_error=UNKNOWN owner_state={owner_state}")
    assert protected not in text and str(tmp_path) not in text
    assert error.value.__cause__ is None
    assert calls == [] and current_caller_storage.get() is None


@pytest.mark.asyncio
async def test_independent_tactical_call_needs_no_root_diagnostic_or_composition():
    called = []
    def forbidden(*_args): raise AssertionError("Tactical call consulted root authority")
    async def dispatch(_context):
        called.append(True)
        return "unchanged"
    context = SimpleNamespace(message=SimpleNamespace(name="get_components", arguments={}),
        fastmcp_context=None)
    assert await CallerStorageMiddleware(forbidden, forbidden).on_call_tool(context, dispatch) == "unchanged"
    assert called == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize("advertised", (True, False))
async def test_diagnostic_uses_only_public_typed_capability_presence(advertised, monkeypatch):
    from mcp.types import ClientCapabilities
    monkeypatch.delenv("IGNIS_CALLER_ROOT", raising=False)
    monkeypatch.chdir("/")
    protected = "PRIVATE_CAPABILITY_CANARY"
    async def unavailable(): raise AssertionError("Client roots must never be requested")
    capabilities = ClientCapabilities(roots={} if advertised else None,
        experimental={protected: {"payload": protected}})
    ctx = SimpleNamespace(request_context=object(), session=SimpleNamespace(
        list_roots=unavailable, client_capabilities=capabilities))
    context = SimpleNamespace(message=SimpleNamespace(name="get_mission_analysis", arguments={}),
        fastmcp_context=ctx)
    def forbidden(*_args): raise AssertionError("Refusal attempted composition")
    async def next_call(_context): raise AssertionError("Refusal attempted dispatch")
    with pytest.raises(ToolError) as error:
        await CallerStorageMiddleware(forbidden, forbidden).on_call_tool(context, next_call)
    expected = "ADVERTISED" if advertised else "NOT_ADVERTISED"
    assert str(error.value) == (f"ROOT_REQUIRED category=STARTUP_ROOT_REFUSED "
        f"roots_capability={expected} rpc_error=UNKNOWN owner_state=UNKNOWN")
    assert protected not in str(error.value) and error.value.__cause__ is None
