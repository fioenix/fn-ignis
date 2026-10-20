import json
import re
from pathlib import Path

import pytest
from ignis.interfaces.mcp.server import mcp


@pytest.mark.asyncio
async def test_all_tool_manifests_are_synchronized():
    """Verify that hermes_manifest.json, .hermes/tools.json, openclaw.json,
    and FastMCP server expose exactly the same set of 47 tools.
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

    assert len(server_tool_names) == 47, f"Expected 47 tools in server, got {len(server_tool_names)}"
    assert hermes_manifest_names == server_tool_names, (
        f"hermes_manifest drift: {server_tool_names ^ hermes_manifest_names}"
    )
    assert hermes_tools_names == server_tool_names, (
        f".hermes/tools.json drift: {server_tool_names ^ hermes_tools_names}"
    )
    assert openclaw.get("protocols", {}).get("tools_count") == 47
    for manifest in (hermes_manifest, hermes_tools):
        assert len(manifest) == 47
        for entry in manifest:
            function = entry["function"]
            tool = next(tool for tool in tools if tool.name == function["name"])
            assert function["parameters"] == tool.parameters, function["name"]
            assert function["description"] == tool.description, function["name"]


def test_wheel_smoke_uses_the_manifest_tool_count():
    """Keep the built-wheel MCP smoke gate aligned with the public tool manifest."""
    openclaw = json.loads(Path("openclaw.json").read_text(encoding="utf-8"))
    smoke_source = Path("scripts/wheel_mcp_smoke.py").read_text(encoding="utf-8")
    declared = re.search(r"^EXPECTED_TOOL_COUNT = (\d+)$", smoke_source, re.MULTILINE)

    assert declared is not None, "wheel smoke no longer declares its expected tool count"
    assert int(declared.group(1)) == openclaw["protocols"]["tools_count"]


def _manifest_function(path: str, name: str) -> dict:
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    return next(e["function"] for e in entries if e["function"]["name"] == name)


@pytest.mark.asyncio
async def test_the_two_qualification_tools_carry_their_typed_contract_everywhere():
    """The host Agent can only submit a typed judgment it can read the shape of."""
    from ignis.domain.research_workspace import (
        EvidencePurpose,
        QualificationReason,
        QualificationRelation,
    )

    tools = {t.name: t for t in await mcp.list_tools()}
    expected_required = {
        "get_mission_evidence_qualification_batch": ["mission_id"],
        "submit_mission_evidence_qualifications": ["mission_id", "frame_fingerprint", "assessments"],
    }
    for name, required in expected_required.items():
        schema = tools[name].parameters
        assert schema["required"] == required, name
        for manifest in ("hermes_manifest.json", ".hermes/tools.json"):
            function = _manifest_function(manifest, name)
            assert function["parameters"] == schema, f"{manifest} drifted from the server for {name}"
            assert function["description"] == tools[name].description, f"{manifest}: {name}"

    batch = tools["get_mission_evidence_qualification_batch"].parameters["properties"]
    assert batch["limit"] == {"default": 25, "type": "integer"}
    assessments = tools["submit_mission_evidence_qualifications"].parameters["properties"]["assessments"]
    assert assessments["type"] == "array" and assessments["items"]["type"] == "object"
    description = tools["submit_mission_evidence_qualifications"].description
    for enum in (QualificationRelation, EvidencePurpose, QualificationReason):
        missing = [member.value for member in enum if member.value not in description]
        assert not missing, f"the submit tool does not tell the Agent about {missing}"


@pytest.mark.asyncio
async def test_the_batch_tool_does_not_promise_ready_whenever_nothing_is_pending():
    """The description is an instruction an Agent reads, so it must name the terminal non-ready states."""
    tools = {t.name: t for t in await mcp.list_tools()}
    description = tools["get_mission_evidence_qualification_batch"].description

    assert "Returns READY when nothing is pending" not in description
    for required in ("QUALIFICATION_REQUIRED", "UNAVAILABLE", "unassessed"):
        assert required in description, required


@pytest.mark.asyncio
async def test_the_submit_tool_says_its_next_step_follows_the_state_it_produced():
    """After a write that made the frame terminal, another batch read is not the next step."""
    tools = {t.name: t for t in await mcp.list_tools()}
    description = tools["submit_mission_evidence_qualifications"].description

    for required in ("qualification_status", "qualification_reason_code", "next_step"):
        assert required in description, required


@pytest.mark.asyncio
async def test_claim_ledger_tools_match_both_manifest_schemas():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    expected_required = {
        "submit_mission_claims": ["mission_id", "frame_digest", "candidates", "created_by"],
        "get_mission_claims": ["mission_id"],
    }
    for name, required in expected_required.items():
        assert tools[name].parameters["required"] == required
        for manifest in ("hermes_manifest.json", ".hermes/tools.json"):
            function = _manifest_function(manifest, name)
            assert function["parameters"] == tools[name].parameters
            assert function["description"] == tools[name].description
