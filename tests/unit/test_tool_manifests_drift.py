import json
import re
from pathlib import Path

import pytest
from ignis.interfaces.mcp.server import mcp


@pytest.mark.asyncio
async def test_all_tool_manifests_are_synchronized():
    """Verify that hermes_manifest.json, .hermes/tools.json, openclaw.json,
    and FastMCP server expose exactly the same set of 45 tools.
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

    assert len(server_tool_names) == 45, f"Expected 45 tools in server, got {len(server_tool_names)}"
    assert hermes_manifest_names == server_tool_names, (
        f"hermes_manifest drift: {server_tool_names ^ hermes_manifest_names}"
    )
    assert hermes_tools_names == server_tool_names, (
        f".hermes/tools.json drift: {server_tool_names ^ hermes_tools_names}"
    )
    assert openclaw.get("protocols", {}).get("tools_count") == 45


def test_wheel_smoke_uses_the_manifest_tool_count():
    """Keep the built-wheel MCP smoke gate aligned with the public tool manifest."""
    openclaw = json.loads(Path("openclaw.json").read_text(encoding="utf-8"))
    smoke_source = Path("scripts/wheel_mcp_smoke.py").read_text(encoding="utf-8")
    declared = re.search(r"^EXPECTED_TOOL_COUNT = (\d+)$", smoke_source, re.MULTILINE)

    assert declared is not None, "wheel smoke no longer declares its expected tool count"
    assert int(declared.group(1)) == openclaw["protocols"]["tools_count"]
