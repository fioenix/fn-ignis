"""Consumer-visible additive host-search contract without database side effects."""

import pytest

from ignis.interfaces.mcp import server


@pytest.mark.asyncio
async def test_host_search_tools_are_additive_and_require_explicit_browser_scope():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert {"prepare_host_browser_search", "submit_host_browser_search",
            "cancel_host_browser_search"} <= tools.keys()
    required = tools["prepare_host_browser_search"].parameters["required"]
    assert {"host_task_ref", "session_ref", "queries", "result_limit", "lifetime_seconds", "authorized"} <= set(required)


@pytest.mark.asyncio
async def test_tactical_preparation_and_cancel_need_no_database_component(monkeypatch):
    names = {tool.name for tool in await server.mcp.list_tools()}
    assert "prepare_host_browser_search" in names
    def forbid_database():
        pytest.fail("Tactical host search must not initialize database/auth components")
    monkeypatch.setattr(server, "_init_components", forbid_database)
    request = await server.handle_prepare_host_browser_search(
        host_task_ref="mcp-task", session_ref="authorized-host-session", queries=["túi đi làm"],
        result_limit=2, lifetime_seconds=60, authorized=True,
    )
    assert request["mode"] == "TACTICAL"
    result = await server.handle_cancel_host_browser_search(request["request_id"], "mcp-task", "authorized-host-session")
    assert result["status"] == "CANCELLED"


@pytest.mark.asyncio
async def test_mission_mode_is_explicit_in_public_preparation_schema():
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    properties = tools["prepare_host_browser_search"].parameters["properties"]
    assert "mode" in properties
    assert properties["mode"]["default"] == "TACTICAL"
    assert "mission_id" in properties


def test_server_exit_closes_all_task_listeners_even_on_failure(monkeypatch):
    from unittest.mock import Mock
    close = Mock()
    monkeypatch.setattr(server._host_browser_search_service, "close", close)
    monkeypatch.setattr(server, "_register_shutdown_handlers", lambda: None)
    def fail_run():
        raise ValueError("Fixture server failure")
    monkeypatch.setattr(server.mcp, "run", fail_run)
    with pytest.raises(ValueError):
        server.main()
    close.assert_called_once()


@pytest.mark.asyncio
async def test_preparation_without_attribution_vocabulary_names_the_gap(monkeypatch):
    monkeypatch.setattr(server._host_browser_search_service, "_attribution_templates", ())
    result = await server.handle_prepare_host_browser_search(
        host_task_ref="mcp-task", session_ref="authorized-host-session", queries=["túi đi làm"],
        result_limit=2, lifetime_seconds=60, authorized=True,
    )
    assert result == {"status": "BLOCKED", "reason_code": "AUTHOR_ATTRIBUTION_VOCABULARY_MISSING"}


@pytest.mark.asyncio
async def test_threads_prepare_is_the_only_additive_public_parameter_and_no_database(monkeypatch):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay, host_answer
    from ignis.application.use_cases import host_browser_search as module
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    service = module.HostBrowserSearchService()
    monkeypatch.setattr(server, "_host_browser_search_service", service)
    try:
        tools = {tool.name: tool for tool in await server.mcp.list_tools()}
        assert len(tools) == 53
        assert tools["prepare_host_browser_search"].parameters["properties"]["source"]["default"] == "tiktok"
        for name in ("submit_host_browser_search", "cancel_host_browser_search"):
            assert set(tools[name].parameters["properties"]) == {"request_id", "host_task_ref", "session_ref"}
        monkeypatch.setattr(server, "get_components", lambda: pytest.fail("Tactical source opened database"))
        request = await server.handle_prepare_host_browser_search("task", "session", ["synthetic"], 3, 60, True,
                                                                 source="threads")
        service.stage(request["request_id"], host_answer(request))
        receipt = await server.handle_submit_host_browser_search(request["request_id"], "task", "session")
        assert receipt["status"] == "ACCEPTED" and receipt["observations"][0]["source"] == "threads"
    finally:
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,mode", [("submit_host_browser_search", "MISSION"), ("cancel_host_browser_search", "MISSION"),
                                      ("submit_host_browser_search", "TACTICAL"), ("prepare_host_browser_search", "TACTICAL")])
async def test_middleware_routes_mission_ticket_calls_without_scoping_tactical_database(tmp_path, monkeypatch, tool, mode):
    from types import SimpleNamespace
    from ignis.infrastructure.caller_storage import CallerStorageMiddleware, current_caller_storage
    monkeypatch.delenv("IGNIS_CALLER_ROOT", raising=False)
    scope = SimpleNamespace(root=tmp_path, components={"synthetic": True}, check=lambda: None)
    owner = SimpleNamespace(closed=False, caller_scopes={str(tmp_path): scope})
    middleware = CallerStorageMiddleware(lambda scope: pytest.fail("Unexpected composition"), lambda *args: None)
    middleware.host_request_mode = lambda request_id: mode
    monkeypatch.setattr(middleware, "_checked_startup_root", lambda ctx: tmp_path)
    arguments = ({"mode": mode, "mission_id": None} if tool == "prepare_host_browser_search"
                 else {"request_id": "synthetic"})
    context = SimpleNamespace(message=SimpleNamespace(name=tool, arguments=arguments),
        fastmcp_context=SimpleNamespace(request_context=object(), lifespan_context={"mission_relay": owner}))
    async def call_next(context):
        return current_caller_storage.get()
    result = await middleware.on_call_tool(context, call_next)
    assert result is (scope if mode == "MISSION" else None)


@pytest.mark.asyncio
async def test_bound_mission_scope_is_not_rebound_for_a_different_caller(monkeypatch):
    from tests.fixtures.meta_host_browser_answers import NoSocketRelay
    from ignis.application.use_cases import host_browser_search as module
    from ignis.infrastructure.caller_storage import current_caller_storage
    monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
    service = module.HostBrowserSearchService()
    monkeypatch.setattr(server, "_host_browser_search_service", service)
    token = current_caller_storage.set(object())
    try:
        request = service.prepare("task", "session", ["synthetic"], 3, 60, True)
        current_caller_storage.set(object())
        monkeypatch.setattr(server, "get_components", lambda: pytest.fail("Caller mismatch reached components"))
        result = await server.handle_submit_host_browser_search(request["request_id"], "task", "session")
        assert result["status"] == "BLOCKED"
    finally:
        current_caller_storage.reset(token)
        service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["instagram", "threads-mcp-keyword-v1", "THREADS", ""])
async def test_unsupported_host_source_is_refused_before_transport_or_storage(monkeypatch, source):
    monkeypatch.setattr(server, "get_components", lambda: pytest.fail("Invalid source reached storage"))
    result = await server.handle_prepare_host_browser_search(
        "synthetic-task", "synthetic-session", ["synthetic"], 3, 60, True, source=source,
    )
    assert result["status"] == "BLOCKED"
