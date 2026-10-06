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
