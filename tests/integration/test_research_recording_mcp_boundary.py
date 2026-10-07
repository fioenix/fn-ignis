"""Actual stdio transport recording; no host execution or viewer acceptance claim."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
import pytest

from tests.integration.test_mission_relay_read_boundary import relay_case as _relay_case, _state

from tests.integration.test_research_work_persistence import _arrange
from tests.integration.test_research_work_command_service import command

relay_case = _relay_case


RUNNER = """
import asyncio
import sys
import json
from pathlib import Path
from fastmcp.server.middleware import Middleware
from mcp.server.session import ServerSession
from ignis.interfaces.mcp import server
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

class TransportProof(Middleware):
    async def on_call_tool(self, context, call_next):
        if context.message.name == "record_mission_research_work":
            ctx = context.fastmcp_context
            runtime = ctx.lifespan_context["mission_relay"]
            proof = {"transport": ctx.transport, "lifespan_transport": runtime.transport,
                     "request_session": isinstance(ctx.request_context.session, ServerSession),
                     "exact_server": ctx.fastmcp is server.mcp and runtime.server is server.mcp,
                     "owner_loop": runtime.owner_loop is asyncio.get_running_loop()}
            Path(sys.argv[2]).write_text(json.dumps(proof))
        return await call_next(context)

async def main():
    repository = SqliteTrendRepository(sys.argv[1])
    server._init_components = lambda: {"repository": repository}
    server.get_components()
    server.mcp.add_middleware(TransportProof())
    # Explicit disposable fixture initialization, never recording-handler bootstrap.
    await repository._ensure_schema()
    try:
        await server.mcp.run_stdio_async(show_banner=False)
    finally:
        await repository.close()

asyncio.run(main())
"""


def stdio_client(tmp_path, case):
    runner = tmp_path / "recording_stdio.py"
    runner.write_text(RUNNER)
    env_file = tmp_path / "isolated.env"
    env_file.write_text("DATABASE_URL=sqlite:///:memory:\nYOUTUBE_API_KEY=\nIGNIS_ENCRYPTION_KEY=\n")
    root = Path(__file__).resolve().parents[2]
    transport = StdioTransport(
        command=sys.executable,
        args=[str(runner), case.repository._db_path, str(tmp_path / "transport-proof.json")],
        cwd=str(tmp_path),
        keep_alive=False,
        env={"IGNIS_ENV_FILE": str(env_file), "IGNIS_ENV_ISOLATED": "1", "PYTHONPATH": str(root / "src")},
        log_file=tmp_path / "stdio.log",
    )
    return Client(transport, timeout=15)


def public_handoff(handoff, revision):
    payload = handoff.to_payload()
    del payload["recorded_at"]
    for finding in payload["findings"]:
        del finding["recorded_at"]
    return command("SUBMIT_HANDOFF", payload, revision)


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_stdio_records_bound_handoff_and_original_retry(relay_case, tmp_path):
    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    body = public_handoff(handoff, revision)
    async with stdio_client(tmp_path, case) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        schema = tools["record_mission_research_work"].input_schema
        assert set(schema["properties"]) == {"mission_id", "command"}
        assert set(schema["required"]) == {"mission_id", "command"}
        first = (
            await client.call_tool("record_mission_research_work", {"mission_id": str(mission.id), "command": body})
        ).data
        assert first["disposition"] == "APPLIED"
        assert first["work_id"] == str(work.work_id)
        assert first["handoff_id"] == str(handoff.handoff_id)
        before = _state(case)
        retry = (
            await client.call_tool(
                "record_mission_research_work", {"mission_id": str(mission.id), "command": deepcopy(body)}
            )
        ).data
        assert retry == first
        assert _state(case) == before
    assert json.loads((tmp_path / "transport-proof.json").read_text()) == {
        "transport": "stdio",
        "lifespan_transport": "stdio",
        "request_session": True,
        "exact_server": True,
        "owner_loop": True,
    }
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,)
    assert snapshot.findings == handoff.findings


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_framework_argument_rejection_does_not_echo_private_body(relay_case, tmp_path):
    case, mission, _, _, _, handoff, revision = await _arrange(relay_case, tmp_path)
    body = public_handoff(handoff, revision)
    marker = "private-framework-sentinel"
    before = _state(case)
    async with stdio_client(tmp_path, case) as client:
        for extra in ("ctx", "host_authorized", "unknown"):
            result = await client.call_tool(
                "record_mission_research_work",
                {"mission_id": str(mission.id), "command": body, extra: marker},
                raise_on_error=False,
            )
            assert marker not in repr(result)
            assert result.data["reason_code"] == "INVALID_COMMAND"
        for arguments in (
            {"mission_id": [marker], "command": body},
            {"mission_id": str(mission.id), "command": marker},
        ):
            result = await client.call_tool("record_mission_research_work", arguments, raise_on_error=False)
            assert marker not in repr(result)
            assert result.data["reason_code"] == "INVALID_COMMAND"
    assert marker not in (tmp_path / "stdio.log").read_text()
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_stdio_nested_invalid_commands_never_reach_storage(relay_case, tmp_path):
    from tests.unit.test_record_mission_research_work import assignment_command

    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    original = public_handoff(handoff, revision)
    marker = "private-body-sentinel"
    controls = []
    for location in ("top", "payload", "finding", "bindings", "source"):
        body = deepcopy(original)
        target = {
            "top": body,
            "payload": body["payload"],
            "finding": body["payload"]["findings"][0],
            "bindings": body["payload"]["inputs"],
            "source": body["payload"]["observation_sources"][0],
        }[location]
        target["transcript"] = marker
        controls.append((body, "INVALID_COMMAND"))
    for location in ("top", "payload"):
        body = assignment_command()
        (body if location == "top" else body["payload"])["host_authorized"] = True
        controls.append((body, "INVALID_COMMAND"))
    for value in (marker * 4096, True, [marker], {"private": marker}):
        body = deepcopy(original)
        body["payload"]["result"] = value
        controls.append((body, "INVALID_COMMAND"))
    body = deepcopy(original)
    nested = marker
    for _ in range(14):
        nested = [nested]
    body["payload"]["result"] = nested
    controls.append((body, "INVALID_COMMAND"))
    controls.append(
        (
            command(
                "WAIT_WORK",
                {
                    "work_id": str(work.work_id),
                    "expected_version": work.version,
                    "ownership_fence": work.ownership_fence,
                    "reason": marker,
                },
                revision,
            ),
            "INVALID_REASON_CODE",
        )
    )
    body = deepcopy(original)
    body["operation"] = marker
    controls.append((body, "INVALID_COMMAND"))
    before = _state(case)
    async with stdio_client(tmp_path, case) as client:
        for body, reason in controls:
            result = (
                await client.call_tool("record_mission_research_work", {"mission_id": str(mission.id), "command": body})
            ).data
            assert result["disposition"] == "REFUSED" and result["reason_code"] == reason
            assert result["receipt_id"] is None and result["revision"] is None
            assert marker not in json.dumps(result)
            assert _state(case) == before
    assert marker not in (tmp_path / "stdio.log").read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_stdio_exact_scope_and_authority_rejections_retain_no_body(relay_case, tmp_path):
    from tests.unit.test_record_mission_research_work import assignment_command
    from uuid import uuid4

    case, mission, _, _, work, handoff, revision = await _arrange(relay_case, tmp_path)
    original = public_handoff(handoff, revision)
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    assignment = assignment_command()
    assignment["expected_revision"] = revision
    assignment["expected_epoch"] = 2
    assignment["payload"]["expected_manifest_digest"] = evidence.manifest.manifest_digest
    assignment["payload"]["expected_brief_revision_id"] = str(evidence.brief.brief_revision_id)
    assignment["payload"]["authority"]["actions"] = ["COLLECT"]
    controls = [(str(mission.id), assignment, "AUTHORITY_WIDENING")]
    foreign_mission = relay_case[1][1]
    foreign = await case.repository.load_mission_evidence_snapshot(foreign_mission.id)
    body = deepcopy(original)
    body["payload"]["inputs"]["mission_id"] = str(foreign_mission.id)
    controls.append((str(mission.id), body, "INVALID_COMMAND"))
    body = deepcopy(original)
    body["payload"]["observation_sources"][0]["source_id"] = str(uuid4())
    controls.append((str(mission.id), body, "INPUT_IDENTITY_MISMATCH"))
    body = deepcopy(original)
    body["payload"]["observation_sources"][0] = {
        "observation_id": str(foreign.signals[0].observation_id),
        "source_id": str(foreign.signals[0].source_id),
    }
    # Keep every nested binding consistent so the actual store must reject foreign identity.
    old_observation = body["payload"]["inputs"]["observation_ids"][0]
    new_observation = str(foreign.signals[0].observation_id)
    body["payload"]["inputs"]["observation_ids"][0] = new_observation
    for finding in body["payload"]["findings"]:
        finding["inputs"] = deepcopy(body["payload"]["inputs"])
        for role in ("supporting_observation_ids", "contradicting_observation_ids", "context_observation_ids"):
            finding[role] = [new_observation if item == old_observation else item for item in finding[role]]
    controls.append((str(mission.id), body, "INPUT_IDENTITY_MISMATCH"))
    _, other_mission, _, _, _, _, other_revision = await _arrange(relay_case, tmp_path)
    selected_foreign = deepcopy(original)
    selected_foreign["expected_revision"] = other_revision
    controls.append((str(other_mission.id), selected_foreign, "SCOPE_MISMATCH"))
    async with stdio_client(tmp_path, case) as client:
        for selected, body, reason in controls:
            body = deepcopy(body)
            body["idempotency_key"] = uuid4().hex
            if body["operation"] == "SUBMIT_HANDOFF":
                body["payload"]["result"] = "private-rejected-body-sentinel"
            from ignis.application.use_cases.record_mission_research_work import parse_recording_command

            if reason != "INVALID_COMMAND":
                parse_recording_command(selected, body, host_authorized=True)
            before = _state(case)
            result = (
                await client.call_tool("record_mission_research_work", {"mission_id": selected, "command": body})
            ).data
            assert result["disposition"] == "REFUSED" and result["reason_code"] == reason
            after = _state(case)
            assert after[0] == before[0]
            for table in before[1]:
                if table != "research_work_commands":
                    assert after[1][table] == before[1][table]
            assert "private-rejected-body-sentinel" not in repr(after)
            retry = (
                await client.call_tool(
                    "record_mission_research_work", {"mission_id": selected, "command": deepcopy(body)}
                )
            ).data
            assert retry == result and _state(case) == after


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_actual_inmemory_mcp_request_cannot_authorize_mutation(relay_case, tmp_path, monkeypatch):
    from ignis.interfaces.mcp import server

    case, mission, _, _, _, handoff, revision = await _arrange(relay_case, tmp_path)
    monkeypatch.setattr(server, "_COMPONENTS", None)
    monkeypatch.setattr(server, "_init_components", lambda: {"repository": case.repository})
    server.get_components()
    before = _state(case)
    async with Client(server.mcp) as client:
        result = (
            await client.call_tool(
                "record_mission_research_work",
                {"mission_id": str(mission.id), "command": public_handoff(handoff, revision)},
            )
        ).data
        assert result["disposition"] == "REFUSED" and result["reason_code"] == "UNAUTHORIZED_HOST"
        assert result["receipt_id"] is None
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_owner_lifetime_settles_actual_admission_despite_repeated_cancellation(relay_case, tmp_path, monkeypatch):
    from ignis.interfaces.mcp import server

    case, mission, _, _, _, handoff, revision = await _arrange(relay_case, tmp_path)
    monkeypatch.setattr(server, "_COMPONENTS", None)
    monkeypatch.setattr(server, "_init_components", lambda: {"repository": case.repository})
    server.get_components()
    runtime = server._MissionRelayRuntime()
    entered, release = asyncio.Event(), asyncio.Event()
    commit = case.repository.commit_research_work

    async def suspended(typed):
        entered.set()
        await release.wait()
        return await commit(typed)

    monkeypatch.setattr(case.repository, "commit_research_work", suspended)
    recording = asyncio.create_task(runtime.record(str(mission.id), public_handoff(handoff, revision)))
    await asyncio.wait_for(entered.wait(), 5)
    closing = asyncio.create_task(runtime.close())
    recording.cancel()
    await asyncio.sleep(0)
    recording.cancel()
    await asyncio.sleep(0)
    assert not closing.done() and not recording.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(recording, 5)
    await asyncio.wait_for(closing, 5)
    assert runtime.closed and not runtime._writes
    snapshot = await case.repository.load_research_work(mission.id)
    assert snapshot.handoffs == (handoff,)
    before = _state(case)
    assert (await runtime.record(str(mission.id), public_handoff(handoff, revision)))[
        "reason_code"
    ] == "STORAGE_FAILURE"
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_actual_stdio_six_field_assignment_original_retry_after_newer_frame(relay_case, tmp_path):
    from tests.unit.test_record_mission_research_work import assignment_command
    from tests.integration.test_research_work_persistence import _sql

    case, mission, _, _, work, _, revision = await _arrange(relay_case, tmp_path)
    evidence = await case.repository.load_mission_evidence_snapshot(mission.id)
    body = assignment_command()
    body["expected_epoch"] = 2
    body["payload"]["expected_manifest_digest"] = evidence.manifest.manifest_digest
    body["payload"]["expected_brief_revision_id"] = str(evidence.brief.brief_revision_id)
    assert set(body["payload"]) == {
        "assignment_id",
        "expected_manifest_digest",
        "expected_brief_revision_id",
        "host_task_ref",
        "authority",
        "capability",
    }
    async with stdio_client(tmp_path, case) as client:

        async def record(command_body):
            return (
                await client.call_tool(
                    "record_mission_research_work", {"mission_id": str(mission.id), "command": command_body}
                )
            ).data

        ended = await record(
            command(
                "END_RESEARCH",
                {
                    "assignment_id": str(work.assignment_id),
                    "expected_version": 2,
                    "disposition": "COMPLETED",
                    "reason": "INVALID_INPUT",
                },
                revision,
            )
        )
        assert ended["disposition"] == "APPLIED"
        body["expected_revision"] = ended["revision"]
        first = await record(body)
        assert first["disposition"] == "APPLIED"
        assert first["assignment_id"] == body["payload"]["assignment_id"]
        terminal = command(
            "END_RESEARCH",
            {
                "assignment_id": first["assignment_id"],
                "expected_version": 1,
                "disposition": "FAILED",
                "reason": "INVALID_INPUT",
            },
            first["revision"],
        )
        terminal["expected_epoch"] = 2
        assert (await record(terminal))["disposition"] == "APPLIED"
        await _sql(
            case,
            "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?",
            (str(mission.id), str(work.inputs.observation_ids[0])),
        )
        before = _state(case)
        assert await record(deepcopy(body)) == first
        assert _state(case) == before
        changed = deepcopy(body)
        changed["payload"]["host_task_ref"] = "different-safe-host"
        conflict = await record(changed)
        assert conflict["reason_code"] == "IDEMPOTENCY_CONFLICT"
        assert _state(case) == before
