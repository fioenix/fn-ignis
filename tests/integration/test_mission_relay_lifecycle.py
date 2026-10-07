"""Loop ownership and no-bootstrap acceptance for the mission viewer lifecycle."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ignis.domain.mission_relay import MissionRelayReadFailure


def _server():
    from ignis.interfaces.mcp import server
    return server


def _lifespan(server):
    hook = getattr(server, "_mission_relay_lifespan", None)
    assert callable(hook), "T025 API RED: mission relay lifespan is absent"
    return hook(server.mcp)


@pytest.mark.asyncio
async def test_lifespan_start_and_stop_perform_no_storage_or_listener_work(monkeypatch):
    server = _server()
    calls = []
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Viewer startup performed component, storage or listener work")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    async with _lifespan(server) as state:
        runtime = state["mission_relay"]
        assert runtime.owner_loop is asyncio.get_running_loop()
        assert runtime.listener is None
    assert calls == []
    assert runtime.closed and runtime.listener is None


@pytest.mark.asyncio
async def test_missing_storage_refuses_without_component_bootstrap_or_file_creation(monkeypatch, tmp_path):
    server = _server()
    missing = tmp_path / "absent.db"
    from pydantic import SecretStr
    monkeypatch.setattr(server.settings, "DATABASE_URL", SecretStr(f"sqlite:///{missing}"))
    def forbidden():
        raise AssertionError("Viewer initialized writable components")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    monkeypatch.setattr(server, "_COMPONENTS", None)
    async with _lifespan(server) as state:
        runtime = state["mission_relay"]
        failure = await runtime.authorize_view(uuid4(), None)
        assert type(failure) is MissionRelayReadFailure
        assert failure.status.value == "UNAVAILABLE"
        assert runtime.listener is None
    assert not missing.exists()


@pytest.mark.asyncio
async def test_lifespan_cleanup_revokes_listener_before_returning(monkeypatch):
    server = _server()
    calls = []
    class Listener:
        def close(self):
            calls.append("revoke")
        async def wait_closed(self, *, timeout):
            calls.append("settle")
            return True
    async with _lifespan(server) as state:
        runtime = state["mission_relay"]
        runtime.listener = Listener()
    assert runtime.closed and calls == ["revoke", "settle"]


@pytest.mark.asyncio
async def test_unsettled_reads_cannot_be_reported_as_closed(monkeypatch):
    server = _server()
    calls = []
    class Listener:
        def close(self):
            calls.append("revoke")
        async def wait_closed(self, *, timeout):
            calls.append("settle")
            return False
    with pytest.raises(RuntimeError, match="settle"):
        async with _lifespan(server) as state:
            state["mission_relay"].listener = Listener()
    assert calls == ["revoke", "settle"]


@pytest.mark.asyncio
async def test_fastmcp_uses_registered_owner_lifespan():
    server = _server()
    async with server.mcp._lifespan_manager():
        state = server.mcp._lifespan_result
        assert "mission_relay" in state, "T025 registration RED: FastMCP does not own the viewer"
        runtime = state["mission_relay"]
        assert runtime.owner_loop is asyncio.get_running_loop()
    assert runtime.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_shutdown", (False, True))
async def test_actual_listener_shutdown_waits_for_owner_read_cleanup(cancel_shutdown):
    import http.client
    from urllib.parse import urlsplit
    from ignis.domain.mission_relay import MissionRelayCursor, MissionRelaySnapshot
    from ignis.domain.research_workspace import ResearchSurface
    from ignis.infrastructure.mission_relay import MissionRelayHTTP
    server = _server()
    entered, cancelled, cleanup = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Projection:
        block = False
        async def execute(self, request):
            assert asyncio.get_running_loop() is owner
            if self.block:
                entered.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await cleanup.wait()
                    raise
            return MissionRelaySnapshot(
                mission_id=request.mission_id, run_id=request.run_id,
                high_water=MissionRelayCursor(mission_id=request.mission_id, revision=0, ordinal=0),
                read_at=datetime.now(timezone.utc), page_size=request.page_size,
                evidence=(), total_observations=0, source_count=0, surface=ResearchSurface.ATTENTION,
            )
    owner = asyncio.get_running_loop()
    context = _lifespan(server)
    state = await context.__aenter__()
    runtime = state["mission_relay"]
    projection = Projection()
    runtime._projection = projection
    runtime.listener = MissionRelayHTTP(provider=runtime, owner_loop=owner)
    cap = await runtime.listener.open_view(mission_id=uuid4(), run_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))
    projection.block = True
    def fetch():
        destination = urlsplit(cap.url)
        connection = http.client.HTTPConnection("127.0.0.1", destination.port, timeout=5)
        try:
            connection.request("GET", destination.path + "snapshot?page_size=1")
            return connection.getresponse().status
        finally:
            connection.close()
    pending = asyncio.create_task(asyncio.to_thread(fetch))
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        closing = asyncio.create_task(context.__aexit__(None, None, None))
        await asyncio.wait_for(cancelled.wait(), 1)
        await asyncio.sleep(0.08)
        assert not closing.done(), "Lifespan returned before owner read cleanup"
        assert runtime.closed
        if cancel_shutdown:
            closing.cancel()
            await asyncio.sleep(0.08)
            assert not closing.done(), "Cancelled shutdown abandoned underlying cleanup"
    finally:
        cleanup.set()
        if closing is None:
            await context.__aexit__(None, None, None)
        elif cancel_shutdown:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(closing, 2)
        else:
            await asyncio.wait_for(closing, 2)
        assert await pending != 200
    assert await runtime.listener.wait_closed(timeout=1)
