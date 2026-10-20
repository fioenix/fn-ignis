"""MCP snapshot read seams; actual storage acceptance stays in the integration suites."""

import inspect
from contextlib import asynccontextmanager

import pytest


def test_typed_read_handler_exists_and_requires_selected_mission():
    from ignis.interfaces.mcp import server
    handler = getattr(server, "handle_get_mission_relay_snapshot", None)
    assert callable(handler), "T026 API RED: snapshot handler is absent"
    parameter = inspect.signature(handler).parameters["mission_id"]
    assert parameter.default is inspect.Parameter.empty


def test_snapshot_handler_requires_explicit_page_size():
    from ignis.interfaces.mcp import server
    handler = getattr(server, "handle_get_mission_relay_snapshot", None)
    assert callable(handler), "T026 API RED: snapshot handler is absent"
    assert inspect.signature(handler).parameters["page_size"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_snapshot_tool_is_registered_with_required_read_inputs_and_no_viewer():
    from ignis.interfaces.mcp import server
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    assert "get_mission_relay_snapshot" in tools, "T026 registration RED: additive read tool is absent"
    assert {"mission_id", "page_size"} <= set(tools["get_mission_relay_snapshot"].parameters.get("required", []))
    assert "open_mission_relay" not in tools, "R2 retired the built-in viewer"


@pytest.fixture
def typed_projection(monkeypatch):
    import asyncio
    from datetime import datetime, timezone
    from ignis.interfaces.mcp import server
    from ignis.domain.mission_relay import MissionRelayCursor, MissionRelaySnapshot
    from ignis.domain.research_workspace import ResearchSurface
    requests = []
    runtimes = []
    class Projection:
        async def execute(self, request):
            requests.append(request)
            return MissionRelaySnapshot(mission_id=request.mission_id, run_id=request.run_id,
                high_water=MissionRelayCursor(mission_id=request.mission_id, revision=0, ordinal=0),
                read_at=datetime.now(timezone.utc), page_size=request.page_size,
                evidence=(), total_observations=0, source_count=0,
                surface=ResearchSurface.ATTENTION, evidence_offset=request.evidence_offset)
    projection = Projection()
    def use_case(runtime):
        assert runtime.owner_loop is asyncio.get_running_loop()
        assert not runtime.closed
        if runtime not in runtimes:
            runtimes.append(runtime)
        return projection
    def forbidden(*args, **kwargs):
        raise AssertionError("Read tool initialized components or writable repository")
    monkeypatch.setattr(server._MissionRelayRuntime, "_use_case", use_case)
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    return server, requests, runtimes


@asynccontextmanager
async def _unit_runtime(typed_projection, root):
    """Explicit disposable caller scope for handler units; no native transport authority claim."""
    from ignis.infrastructure.caller_storage import CallerStorageScope
    server, _, _ = typed_projection
    scope = CallerStorageScope(root)
    runtime = server._MissionRelayRuntime(server.mcp, caller_scope=scope)
    try:
        yield runtime
    finally:
        await runtime.close()


async def _unit_call(runtime, name, arguments):
    from ignis.interfaces.mcp import server
    return await getattr(server, "handle_" + name)(runtime=runtime, **arguments)


@pytest.mark.asyncio
async def test_unit_snapshot_preserves_selected_run_and_opens_no_listener(typed_projection, tmp_path):
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    mission, run = uuid4(), uuid4()
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        result = await _unit_call(runtime, "get_mission_relay_snapshot", {
            "mission_id": str(mission), "run_id": str(run), "page_size": 7,
            "after_revision": 0, "after_ordinal": 0,
        })
        payload = result.to_payload()
        assert payload["status"] == "OK"
        assert payload["mission_id"] == str(mission) and payload["run_id"] == str(run)
        assert len(requests) == 1 and requests[0].page_size == 7
        assert requests[0].after_cursor.position == (0, 0)
        assert len(runtimes) == 1 and not hasattr(runtimes[0], "listener")
    assert runtimes[0].closed


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,reason", (
    ("get_mission_relay_snapshot", {"page_size": 0}, "INVALID_PAGE_SIZE"),
    ("get_mission_relay_snapshot", {"page_size": 201}, "INVALID_PAGE_SIZE"),
    ("get_mission_relay_snapshot", {"page_size": 1, "after_revision": 1}, "INVALID_REQUEST"),
    ("get_mission_relay_snapshot", {"page_size": 1, "evidence_offset": -1}, "INVALID_REQUEST"),
))
async def test_unit_refuses_invalid_input_without_read(typed_projection, tmp_path, name, args, reason):
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        result = await _unit_call(runtime, name, {"mission_id": str(uuid4()), **args})
        assert result.to_payload() == {"schema_version": 1, "status": "REFUSED", "reason_code": reason}
        assert requests == [] and runtimes == []


@pytest.mark.asyncio
async def test_oversized_snapshot_is_a_typed_refusal_not_a_truncated_read(typed_projection, monkeypatch, tmp_path):
    from uuid import uuid4
    from ignis.infrastructure import mission_relay
    server, requests, runtimes = typed_projection
    # The empty fixture snapshot serializes to a few hundred bytes; a 64-byte limit must refuse it whole.
    monkeypatch.setattr(mission_relay, "_RESPONSE_LIMIT", 64)
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        result = await _unit_call(runtime, "get_mission_relay_snapshot", {"mission_id": str(uuid4()), "page_size": 1})
    assert result.to_payload() == {"schema_version": 1, "status": "REFUSED", "reason_code": "RESPONSE_TOO_LARGE"}
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_handler_without_owner_lifespan_is_unavailable_without_bootstrap(monkeypatch):
    from uuid import uuid4
    from ignis.interfaces.mcp import server
    result = await server.handle_get_mission_relay_snapshot(str(uuid4()), 1)
    assert result.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_UNAVAILABLE"}


@pytest.mark.asyncio
async def test_unit_handlers_share_four_process_slots_without_waiter_queue(typed_projection, monkeypatch, tmp_path):
    import asyncio
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    mission = str(uuid4())
    original = server._MissionRelayRuntime.snapshot
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0
    blocking = False
    async def blocked(runtime, request):
        nonlocal count
        if blocking:
            count += 1
            if count == 4:
                entered.set()
            await release.wait()
        return await original(runtime, request)
    monkeypatch.setattr(server._MissionRelayRuntime, "snapshot", blocked)
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        blocking = True
        pending = [asyncio.create_task(_unit_call(runtime, "get_mission_relay_snapshot", {
            "mission_id": mission, "page_size": 1,
        })) for _ in range(4)]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            fifth = await asyncio.wait_for(_unit_call(runtime, "get_mission_relay_snapshot", {
                "mission_id": mission, "page_size": 1,
            }), 1)
            assert fifth.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_BUSY"}
            assert count == 4, "Busy refusal admitted an additional repository read"
        finally:
            release.set()
            results = await asyncio.gather(*pending)
        assert all(result.to_payload()["status"] == "OK" for result in results)


@pytest.mark.asyncio
async def test_browserless_read_timeout_keeps_capacity_until_underlying_cleanup(typed_projection, monkeypatch, tmp_path):
    import asyncio
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    cancelled, cleanup = asyncio.Event(), asyncio.Event()
    count = 0
    async def blocked(runtime, request):
        nonlocal count
        count += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            await cleanup.wait()
            raise
    monkeypatch.setattr(server._MissionRelayRuntime, "snapshot", blocked)
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        pending = [asyncio.create_task(_unit_call(runtime, "get_mission_relay_snapshot", {
            "mission_id": str(uuid4()), "page_size": 1,
        })) for _ in range(4)]
        try:
            results = await asyncio.wait_for(asyncio.gather(*pending), 4)
            assert all(result.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_TIMEOUT"} for result in results)
            assert cancelled.is_set()
            fifth = await _unit_call(runtime, "get_mission_relay_snapshot", {"mission_id": str(uuid4()), "page_size": 1})
            assert fifth.to_payload()["reason_code"] == "READ_BUSY" and count == 4
        finally:
            cleanup.set()
            await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_browserless_read_revocation_discards_late_success(typed_projection, monkeypatch, tmp_path):
    import asyncio
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    entered = asyncio.Event()
    original = server._MissionRelayRuntime.snapshot
    async def late_success(runtime, request):
        recorded = await original(runtime, request)
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return recorded
    monkeypatch.setattr(server._MissionRelayRuntime, "snapshot", late_success)
    async with _unit_runtime(typed_projection, tmp_path) as runtime:
        pending = asyncio.create_task(_unit_call(runtime, "get_mission_relay_snapshot", {
            "mission_id": str(uuid4()), "page_size": 1,
        }))
        await asyncio.wait_for(entered.wait(), 1)
        await runtimes[0].close()
        result = await pending
        assert result.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_UNAVAILABLE"}
