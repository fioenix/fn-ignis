"""Mission ticket routing preserves the invoking caller and refuses scope substitution."""
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage
from ignis.interfaces.mcp import server
from tests.fixtures.meta_host_browser_answers import NoSocketRelay


class _Scope:
    def __init__(self, root, executor):
        self.root = root
        self.components = {"repository": _Repository(), "execute_mission_use_case": executor}

    def check(self):
        pass


class _Repository:
    async def get_mission(self, mission_id):
        return SimpleNamespace(id=mission_id)


class _Service(HostBrowserSearchService):
    """Keep real ticket/caller guards; replace only mission planning and writer entry."""
    def __init__(self):
        super().__init__()
        self.entered = []

    async def prepare_mission(self, executor, mission_id, host_task_ref, session_ref, lifetime, authorized,
                              source="tiktok"):
        return self.prepare(host_task_ref, session_ref, ["synthetic"], 20, lifetime, authorized,
                            mode="MISSION", source=source)

    async def submit_mission(self, executor, request_id, host_task_ref, session_ref):
        self.mode(request_id, host_task_ref, session_ref)
        self.entered.append(("submit", executor, current_caller_storage.get()))
        return {"status": "ACCEPTED"}

    async def cancel_mission(self, request_id, host_task_ref, session_ref):
        receipt = self.cancel(request_id, host_task_ref, session_ref)
        self.entered.append(("cancel", None, current_caller_storage.get()))
        return receipt


@pytest.fixture
def routing(tmp_path, monkeypatch):
    from ignis.application.use_cases import host_browser_search
    monkeypatch.setattr(host_browser_search, "LoopbackRelay", NoSocketRelay)
    service = _Service()
    monkeypatch.setattr(server, "_host_browser_search_service", service)
    monkeypatch.setattr(server, "_COMPONENTS", None)
    monkeypatch.setattr(server, "_init_components", lambda: pytest.fail("Reached global components"))
    monkeypatch.delenv("IGNIS_CALLER_ROOT", raising=False)
    scope = _Scope(tmp_path / "caller", "caller-executor")
    other = _Scope(tmp_path / "other", "other-executor")
    owner = SimpleNamespace(closed=False, caller_scopes={str(s.root): s for s in (scope, other)})
    middleware = CallerStorageMiddleware(lambda s: pytest.fail("Unexpected composition"), lambda *a: None,
                                         host_request_mode=service.request_mode)
    monkeypatch.setattr(middleware, "_checked_startup_root", lambda ctx: ctx.root)

    async def invoke(tool, arguments, caller=scope):
        ctx = (SimpleNamespace(root=caller.root, request_context=object(),
                               lifespan_context={"mission_relay": owner}) if caller else None)
        context = SimpleNamespace(message=SimpleNamespace(name=tool, arguments=arguments), fastmcp_context=ctx)

        async def call_next(context):
            return await getattr(server, "handle_" + tool)(**context.message.arguments)
        return await middleware.on_call_tool(context, call_next)

    yield service, scope, other, invoke
    service.close()


async def _prepare(invoke):
    request = await invoke("prepare_host_browser_search", dict(host_task_ref="task", session_ref="chrome",
        queries=[], result_limit=20, lifetime_seconds=600, authorized=True, mode="MISSION", mission_id="mission"))
    return dict(request_id=request["request_id"], host_task_ref="task", session_ref="chrome")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "cancel"])
async def test_mission_ticket_same_caller_routes_to_its_prepared_store(routing, operation):
    service, scope, _, invoke = routing
    arguments = await _prepare(invoke)
    receipt = await invoke(operation + "_host_browser_search", arguments)
    assert receipt["status"] == ("ACCEPTED" if operation == "submit" else "CANCELLED")
    assert service.entered == [(operation, "caller-executor" if operation == "submit" else None, scope)]
    assert current_caller_storage.get() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "cancel"])
@pytest.mark.parametrize("caller", ["different", "missing"])
async def test_mission_ticket_wrong_or_missing_middleware_caller_refuses_before_writer(routing, operation, caller):
    service, _, other, invoke = routing
    arguments = await _prepare(invoke)
    if caller == "missing":
        with pytest.raises(ToolError, match="ROOT_REQUIRED category=REQUEST_CONTEXT_ABSENT"):
            await invoke(operation + "_host_browser_search", arguments, None)
    else:
        receipt = await invoke(operation + "_host_browser_search", arguments, other)
        assert receipt["status"] == "BLOCKED"
    assert service.entered == []
    assert current_caller_storage.get() is None
    # A refused caller cannot consume or cancel the legitimate caller's ticket.
    assert (await invoke(operation + "_host_browser_search", arguments))["status"] != "BLOCKED"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["submit", "cancel"])
async def test_direct_mission_handler_without_pinned_caller_refuses_before_writer(routing, operation):
    service, _, _, invoke = routing
    arguments = await _prepare(invoke)
    receipt = await getattr(server, "handle_" + operation + "_host_browser_search")(**arguments)
    assert receipt["status"] == "BLOCKED"
    assert service.entered == []


def test_mission_scope_authority_has_no_write_only_server_index():
    assert not hasattr(server, "_host_mission_scopes")
