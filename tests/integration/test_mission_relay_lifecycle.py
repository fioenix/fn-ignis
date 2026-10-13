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


class _Handler:
    """A caller log handler whose removal and close are observable."""

    def __init__(self):
        import logging
        self.handler = logging.NullHandler()
        self.closed = False
        original = self.handler.close

        def close():
            self.closed = True
            original()
        self.handler.close = close


def _caller_scope(repository, *, runtime=None, handler=None):
    from types import SimpleNamespace
    return SimpleNamespace(runtime=runtime, components={"repository": repository},
                           log_handler=None if handler is None else handler.handler)


@pytest.mark.asyncio
async def test_unknown_read_settlement_retains_borrowed_storage_and_still_runs_safe_cleanup(monkeypatch):
    import logging
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    server = _server()
    settled_sources = []
    original_settle = server._MissionRelayRuntime._settle_source

    async def recording_settle(self, acquisition):
        settled_sources.append(acquisition)
        return await original_settle(self, acquisition)
    monkeypatch.setattr(server._MissionRelayRuntime, "_settle_source", recording_settle)
    repository = SqliteTrendRepository(":memory:")
    handler = _Handler()
    logging.getLogger().addHandler(handler.handler)
    class Listener:
        def close(self):
            pass
        async def wait_closed(self, *, timeout):
            return False
    try:
        with pytest.raises(RuntimeError, match="settle"):
            async with _lifespan(server) as state:
                runtime = state["mission_relay"]
                runtime.listener = Listener()
                runtime.caller_scopes["caller"] = _caller_scope(repository, handler=handler)
        assert settled_sources == [None], "Source settlement was skipped after a viewer settlement failure"
        assert handler.closed and handler.handler not in logging.getLogger().handlers
        assert repository._mem_conn is not None, "Borrowed storage was closed under unknown read settlement"
        repository._mem_conn.execute("SELECT 1")
    finally:
        logging.getLogger().removeHandler(handler.handler)
        await repository.close()


@pytest.mark.asyncio
async def test_failed_caller_runtime_close_is_reported_and_retains_its_storage():
    import logging
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    server = _server()
    repository = SqliteTrendRepository(":memory:")
    handler = _Handler()
    logging.getLogger().addHandler(handler.handler)
    class FailingCallerRuntime:
        quiescent = asyncio.Event()
        async def close(self):
            raise RuntimeError("caller viewer reads did not settle")
    try:
        with pytest.raises(RuntimeError, match="caller viewer reads did not settle"):
            async with _lifespan(server) as state:
                state["mission_relay"].caller_scopes["caller"] = _caller_scope(
                    repository, runtime=FailingCallerRuntime(), handler=handler)
        assert handler.closed and handler.handler not in logging.getLogger().handlers
        assert repository._mem_conn is not None, "Storage was closed after its caller runtime failed to settle"
    finally:
        logging.getLogger().removeHandler(handler.handler)
        await repository.close()


class _HealthyCallerRuntime:
    def __init__(self):
        self.quiescent = asyncio.Event()
        self.quiescent.set()

    async def close(self):
        return None


class _BrokenCallerRuntime:
    def __init__(self, error):
        self.quiescent = asyncio.Event()
        self.error = error

    async def close(self):
        raise self.error


@pytest.mark.asyncio
async def test_one_failed_caller_runtime_does_not_retain_a_healthy_sibling():
    import logging
    import sqlite3
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    server = _server()
    unsafe, healthy = SqliteTrendRepository(":memory:"), SqliteTrendRepository(":memory:")
    healthy_connection = healthy._mem_conn
    handler = _Handler()
    logging.getLogger().addHandler(handler.handler)
    try:
        with pytest.raises(RuntimeError, match="caller A did not settle"):
            async with _lifespan(server) as state:
                scopes = state["mission_relay"].caller_scopes
                scopes["a"] = _caller_scope(unsafe, runtime=_BrokenCallerRuntime(RuntimeError("caller A did not settle")))
                scopes["b"] = _caller_scope(healthy, runtime=_HealthyCallerRuntime(), handler=handler)
        assert unsafe._mem_conn is not None, "Storage of the unsettled caller runtime was closed"
        assert healthy._mem_conn is None, "A healthy quiescent sibling was retained because another caller failed"
        with pytest.raises(sqlite3.ProgrammingError):
            healthy_connection.execute("SELECT 1")
        assert handler.closed
    finally:
        logging.getLogger().removeHandler(handler.handler)
        await unsafe.close()


@pytest.mark.asyncio
async def test_cancelled_caller_runtime_close_still_cleans_siblings_then_propagates():
    import logging
    import sqlite3
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
    server = _server()
    cancelled, healthy = SqliteTrendRepository(":memory:"), SqliteTrendRepository(":memory:")
    healthy_connection = healthy._mem_conn
    cancelled_handler, healthy_handler = _Handler(), _Handler()
    for handler in (cancelled_handler, healthy_handler):
        logging.getLogger().addHandler(handler.handler)
    try:
        with pytest.raises(asyncio.CancelledError):
            async with _lifespan(server) as state:
                scopes = state["mission_relay"].caller_scopes
                scopes["a"] = _caller_scope(cancelled, runtime=_BrokenCallerRuntime(asyncio.CancelledError()),
                                            handler=cancelled_handler)
                scopes["b"] = _caller_scope(healthy, runtime=_HealthyCallerRuntime(), handler=healthy_handler)
        assert cancelled._mem_conn is not None, "Storage of the cancelled caller runtime was closed"
        assert cancelled_handler.closed and healthy_handler.closed, "Cancellation skipped log cleanup"
        assert healthy._mem_conn is None, "Cancellation skipped a later sibling's cleanup"
        with pytest.raises(sqlite3.ProgrammingError):
            healthy_connection.execute("SELECT 1")
    finally:
        for handler in (cancelled_handler, healthy_handler):
            logging.getLogger().removeHandler(handler.handler)
        await cancelled.close()


@pytest.mark.asyncio
async def test_repeated_shutdown_cancellation_still_waits_for_actual_cleanup():
    server = _server()
    release, entered = asyncio.Event(), asyncio.Event()
    class Listener:
        def close(self):
            pass
        async def wait_closed(self, *, timeout):
            entered.set()
            await release.wait()
            return True
    context = _lifespan(server)
    state = await context.__aenter__()
    state["mission_relay"].listener = Listener()
    closing = asyncio.create_task(context.__aexit__(None, None, None))
    await asyncio.wait_for(entered.wait(), 1)
    for _ in range(3):
        closing.cancel()
        await asyncio.sleep(0.05)
        assert not closing.done(), "A repeated cancellation abandoned the owned shutdown"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(closing, 2)
    assert state["mission_relay"]._shutdown.done() and not state["mission_relay"]._shutdown.cancelled()


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
