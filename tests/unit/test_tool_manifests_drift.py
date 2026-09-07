import asyncio
import json
import pytest
from ignis.interfaces.mcp.server import mcp


@pytest.mark.asyncio
async def test_all_tool_manifests_are_synchronized():
    """Verify that hermes_manifest.json, .hermes/tools.json, openclaw.json,
    and FastMCP server expose exactly the same set of 39 tools.
    """
    tools = await mcp.list_tools()
    server_tool_names = {t.name for t in tools}

    with open("hermes_manifest.json", "r", encoding="utf-8") as f:
        hermes_manifest = json.load(f)

    with open(".hermes/tools.json", "r", encoding="utf-8") as f:
        hermes_tools = json.load(f)

    with open("openclaw.json", "r", encoding="utf-8") as f:
        openclaw = json.load(f)

    hermes_manifest_names = {t["function"]["name"] for t in hermes_manifest}
    hermes_tools_names = {t["function"]["name"] for t in hermes_tools}

    assert len(server_tool_names) == 39, f"Expected 39 tools in server, got {len(server_tool_names)}"
    assert hermes_manifest_names == server_tool_names, (
        f"hermes_manifest drift: {server_tool_names ^ hermes_manifest_names}"
    )
    assert hermes_tools_names == server_tool_names, (
        f".hermes/tools.json drift: {server_tool_names ^ hermes_tools_names}"
    )
    assert openclaw.get("protocols", {}).get("tools_count") == 39
