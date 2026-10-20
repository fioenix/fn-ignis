"""Borrowed owner identity and finite failure controls for recording composition."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from fastmcp import Client, Context
import pytest

from ignis.interfaces.mcp import server
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from tests.unit.test_record_mission_research_work import assignment_command


def owner(monkeypatch, repository):
    monkeypatch.setattr(server, "_COMPONENTS", None)
    monkeypatch.setattr(server, "_COMPONENTS_OWNER", None)
    monkeypatch.setattr(server, "_init_components", lambda: {"repository": repository})
    return server.get_components()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control",
    (
        "absent",
        "uninitialized",
        "unsupported",
        "replaced_repo",
        "replaced_components",
        "unknown_loop",
        "wrong_loop",
        "closed",
        "closed_memory",
        "closed_pg",
    ),
)
async def test_recording_does_not_adopt_or_initialize_unknown_owner(monkeypatch, control):
    repository = SqliteTrendRepository(":memory:")
    await repository._ensure_schema()
    components = owner(monkeypatch, repository)
    runtime = server._MissionRelayRuntime()
    if control == "absent":
        monkeypatch.setattr(server, "_COMPONENTS", None)
    elif control == "uninitialized":
        repository._initialized = False
    elif control == "unsupported":
        owner(monkeypatch, object())
    elif control == "replaced_repo":
        components["repository"] = object()
    elif control == "replaced_components":
        monkeypatch.setattr(server, "_COMPONENTS", {"repository": repository})
    elif control == "unknown_loop":
        monkeypatch.setattr(server, "_COMPONENTS_OWNER", (components, repository, None))
    elif control == "wrong_loop":
        runtime.owner_loop = object()
    elif control == "closed":
        await runtime.close()
    elif control == "closed_memory":
        await repository.close()
    elif control == "closed_pg":
        from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
        from psycopg_pool import AsyncConnectionPool

        # Real unopened pool: no connection, backend initialization or network access.
        postgres = PostgresTimescaleRepository("postgresql://invalid", pool=AsyncConnectionPool(open=False))
        owner(monkeypatch, postgres)

    def forbidden(*args, **kwargs):
        raise AssertionError("Recording bootstrapped or initialized owner storage")

    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)
    monkeypatch.setattr(repository, "_ensure_schema", forbidden)
    before = repository._mem_conn.total_changes if repository._mem_conn is not None else None
    result = await runtime.record(str(uuid4()), assignment_command())
    assert result["disposition"] == "REFUSED" and result["reason_code"] == "STORAGE_FAILURE"
    assert result["receipt_id"] is None and result["revision"] is None
    if before is not None:
        assert repository._mem_conn.total_changes == before
    await repository.close()


@pytest.mark.asyncio
async def test_owner_marker_is_exact_and_recording_wrong_loop_is_refused(monkeypatch):
    repository = SqliteTrendRepository(":memory:")
    await repository._ensure_schema()
    components = owner(monkeypatch, repository)
    assert server._COMPONENTS_OWNER == (components, repository, asyncio.get_running_loop())
    runtime = server._MissionRelayRuntime()
    result = await asyncio.to_thread(lambda: asyncio.run(runtime.record(str(uuid4()), assignment_command())))
    assert result["reason_code"] == "STORAGE_FAILURE"
    await runtime.close()
    assert repository._mem_conn is not None
    assert repository._mem_conn.execute("SELECT 1").fetchone()[0] == 1
    await repository.close()


def test_sync_component_creation_does_not_gain_loop_ownership(monkeypatch):
    components = owner(monkeypatch, object())
    assert server._COMPONENTS_OWNER[0] is components
    assert server._COMPONENTS_OWNER[2] is None


@pytest.mark.asyncio
async def test_storage_exception_is_finite_and_does_not_close_borrowed_owner(monkeypatch):
    repository = SqliteTrendRepository(":memory:")
    await repository._ensure_schema()
    owner(monkeypatch, repository)
    runtime = server._MissionRelayRuntime()

    async def failing(command):
        raise RuntimeError("private-driver-sentinel")

    monkeypatch.setattr(repository, "commit_research_work", failing)
    result = await runtime.record(str(uuid4()), assignment_command())
    assert result["reason_code"] == "STORAGE_FAILURE" and result["receipt_id"] is None
    assert "private-driver-sentinel" not in str(result)
    await runtime.close()
    assert repository._mem_conn.execute("SELECT 1").fetchone()[0] == 1
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ("bare", "fake", "foreign"))
async def test_bare_or_fabricated_context_cannot_authorize_recording(context):
    from fastmcp import FastMCP

    ctx = (
        Context(server.mcp)
        if context == "bare"
        else (Context(FastMCP("foreign")) if context == "foreign" else SimpleNamespace(transport="stdio"))
    )
    result = await server.record_mission_research_work(str(uuid4()), assignment_command(), ctx)
    assert result["reason_code"] == "UNAUTHORIZED_HOST"
    assert result["receipt_id"] is None


@pytest.mark.asyncio
async def test_recording_middleware_preserves_existing_atomic_tool(monkeypatch):
    expected = {"status": "unchanged", "request_id": "synthetic-request"}
    calls = []

    async def handle(request_id, host_task_ref, session_ref):
        calls.append((request_id, host_task_ref, session_ref))
        return expected

    monkeypatch.setattr(server, "handle_cancel_host_browser_search", handle)
    async with Client(server.mcp) as client:
        result = (
            await client.call_tool(
                "cancel_host_browser_search",
                {
                    "request_id": "synthetic-request",
                    "host_task_ref": "synthetic-host",
                    "session_ref": "synthetic-session",
                },
            )
        ).data
    assert result == expected
    assert calls == [("synthetic-request", "synthetic-host", "synthetic-session")]
