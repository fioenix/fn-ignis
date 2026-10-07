"""Additive MCP read seams; actual storage and browser acceptance stay in T030."""

import inspect

import pytest


@pytest.mark.parametrize("name", ("handle_open_mission_relay", "handle_get_mission_relay_snapshot"))
def test_typed_read_handler_exists_and_requires_selected_mission(name):
    from ignis.interfaces.mcp import server
    handler = getattr(server, name, None)
    assert callable(handler), "T026 API RED: additive viewer handler is absent"
    parameter = inspect.signature(handler).parameters["mission_id"]
    assert parameter.default is inspect.Parameter.empty


def test_open_handler_requires_explicit_deadline():
    from ignis.interfaces.mcp import server
    handler = getattr(server, "handle_open_mission_relay", None)
    assert callable(handler), "T026 API RED: open handler is absent"
    assert inspect.signature(handler).parameters["expires_at"].default is inspect.Parameter.empty


def test_snapshot_handler_requires_explicit_page_size():
    from ignis.interfaces.mcp import server
    handler = getattr(server, "handle_get_mission_relay_snapshot", None)
    assert callable(handler), "T026 API RED: snapshot handler is absent"
    assert inspect.signature(handler).parameters["page_size"].default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_two_additive_tools_are_registered_with_required_read_inputs():
    from ignis.interfaces.mcp import server
    tools = {tool.name: tool for tool in await server.mcp.list_tools()}
    for name, required in (("open_mission_relay", {"mission_id", "expires_at"}),
                           ("get_mission_relay_snapshot", {"mission_id", "page_size"})):
        assert name in tools, "T026 registration RED: additive read tool is absent"
        assert required <= set(tools[name].parameters.get("required", []))


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


@pytest.mark.asyncio
async def test_actual_mcp_snapshot_preserves_selected_run_and_opens_no_listener(typed_projection):
    from fastmcp import Client
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    mission, run = uuid4(), uuid4()
    async with Client(server.mcp) as client:
        result = await client.call_tool("get_mission_relay_snapshot", {
            "mission_id": str(mission), "run_id": str(run), "page_size": 7,
            "after_revision": 0, "after_ordinal": 0,
        })
        payload = result.structured_content
        assert payload["status"] == "OK"
        assert payload["mission_id"] == str(mission) and payload["run_id"] == str(run)
        assert len(requests) == 1 and requests[0].page_size == 7
        assert requests[0].after_cursor.position == (0, 0)
        assert len(runtimes) == 1 and runtimes[0].listener is None
    assert runtimes[0].closed


@pytest.mark.asyncio
async def test_actual_mcp_open_preserves_expiry_and_returns_explicit_read_authority(typed_projection):
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urlsplit
    from uuid import uuid4
    from fastmcp import Client
    server, requests, runtimes = typed_projection
    mission, run = uuid4(), uuid4()
    deadline = datetime.now(timezone.utc) + timedelta(minutes=15)
    async with Client(server.mcp) as client:
        result = await client.call_tool("open_mission_relay", {
            "mission_id": str(mission), "run_id": str(run), "expires_at": deadline.isoformat(),
        })
        payload = result.structured_content
        assert set(payload) == {"schema_version", "status", "mission_id", "run_id", "url", "expires_at", "read_only", "inspection_supported"}
        assert payload["status"] == "OK" and payload["read_only"] is True
        assert payload["inspection_supported"] is True
        assert payload["mission_id"] == str(mission) and payload["run_id"] == str(run)
        assert payload["expires_at"] == deadline.isoformat()
        assert urlsplit(payload["url"]).hostname == "127.0.0.1"
        assert all(r.mission_id == mission and r.run_id == run for r in requests)
    assert runtimes[0].closed
    assert await runtimes[0].listener.wait_closed(timeout=1)


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args,reason", (
    ("get_mission_relay_snapshot", {"page_size": 0}, "INVALID_PAGE_SIZE"),
    ("get_mission_relay_snapshot", {"page_size": 201}, "INVALID_PAGE_SIZE"),
    ("get_mission_relay_snapshot", {"page_size": 1, "after_revision": 1}, "INVALID_REQUEST"),
    ("get_mission_relay_snapshot", {"page_size": 1, "evidence_offset": -1}, "INVALID_REQUEST"),
    ("open_mission_relay", {"expires_at": "2026-01-01T00:00:00"}, "INVALID_EXPIRY"),
    ("open_mission_relay", {"expires_at": "2026-01-01T00:00:00Z"}, "INVALID_EXPIRY"),
))
async def test_actual_mcp_refuses_invalid_input_without_read_or_listener(typed_projection, name, args, reason):
    from fastmcp import Client
    from uuid import uuid4
    server, requests, runtimes = typed_projection
    async with Client(server.mcp) as client:
        result = await client.call_tool(name, {"mission_id": str(uuid4()), **args})
        assert result.structured_content == {"schema_version": 1, "status": "REFUSED", "reason_code": reason}
        assert requests == [] and runtimes == []


@pytest.mark.asyncio
async def test_handler_without_owner_lifespan_is_unavailable_without_bootstrap(monkeypatch):
    from uuid import uuid4
    from ignis.interfaces.mcp import server
    result = await server.handle_get_mission_relay_snapshot(str(uuid4()), 1)
    assert result.to_payload() == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_UNAVAILABLE"}


@pytest.mark.asyncio
async def test_mcp_and_http_share_four_process_slots_without_waiter_queue(typed_projection, monkeypatch):
    import asyncio
    import http.client
    import json
    from datetime import datetime, timedelta, timezone
    from urllib.parse import urlsplit
    from uuid import uuid4
    from fastmcp import Client
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
    async with Client(server.mcp) as client:
        cap = (await client.call_tool("open_mission_relay", {
            "mission_id": mission, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
        })).structured_content
        assert cap["status"] == "OK"
        blocking = True
        pending = [asyncio.create_task(client.call_tool("get_mission_relay_snapshot", {
            "mission_id": mission, "page_size": 1,
        })) for _ in range(4)]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            fifth = await asyncio.wait_for(client.call_tool("get_mission_relay_snapshot", {
                "mission_id": mission, "page_size": 1,
            }), 1)
            assert fifth.structured_content == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_BUSY"}
            def http_read():
                url = urlsplit(cap["url"])
                connection = http.client.HTTPConnection("127.0.0.1", url.port, timeout=1)
                try:
                    connection.request("GET", url.path + "snapshot?page_size=1")
                    response = connection.getresponse()
                    return response.status, json.loads(response.read())
                finally:
                    connection.close()
            status, body = await asyncio.to_thread(http_read)
            assert status == 503 and body == fifth.structured_content
            assert count == 4, "Busy refusal admitted an additional repository read"
        finally:
            release.set()
            results = await asyncio.gather(*pending)
        assert all(result.structured_content["status"] == "OK" for result in results)


@pytest.mark.asyncio
async def test_browserless_read_timeout_keeps_capacity_until_underlying_cleanup(typed_projection, monkeypatch):
    import asyncio
    from uuid import uuid4
    from fastmcp import Client
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
    async with Client(server.mcp) as client:
        pending = [asyncio.create_task(client.call_tool("get_mission_relay_snapshot", {
            "mission_id": str(uuid4()), "page_size": 1,
        })) for _ in range(4)]
        try:
            results = await asyncio.wait_for(asyncio.gather(*pending), 4)
            assert all(result.structured_content == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_TIMEOUT"} for result in results)
            assert cancelled.is_set()
            fifth = await client.call_tool("get_mission_relay_snapshot", {"mission_id": str(uuid4()), "page_size": 1})
            assert fifth.structured_content["reason_code"] == "READ_BUSY" and count == 4
        finally:
            cleanup.set()
            await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_browserless_read_revocation_discards_late_success(typed_projection, monkeypatch):
    import asyncio
    from uuid import uuid4
    from fastmcp import Client
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
    async with Client(server.mcp) as client:
        pending = asyncio.create_task(client.call_tool("get_mission_relay_snapshot", {
            "mission_id": str(uuid4()), "page_size": 1,
        }))
        await asyncio.wait_for(entered.wait(), 1)
        await runtimes[0].close()
        result = await pending
        assert result.structured_content == {"schema_version": 1, "status": "UNAVAILABLE", "reason_code": "READ_UNAVAILABLE"}
