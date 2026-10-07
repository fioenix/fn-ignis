"""Explicit CLI bootstrap installs operational schemas without fabricating evidence."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ignis.infrastructure import persistence
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.interfaces.cli.setup_bundle import bootstrap_database
from tests.integration.test_mission_relay_read_boundary import _sqlite_state
from tests.integration.test_research_work_schema import TABLES

OPERATIONAL_TABLES = set(TABLES) | {
    "mission_progress_revisions", "mission_progress_events", "mission_progress_commands",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("storage", ("file", "memory"))
@pytest.mark.parametrize("populated", (False, True))
async def test_explicit_bootstrap_repeatedly_preserves_canonical_rows_and_empty_history(
    tmp_path, monkeypatch, storage, populated,
):
    repository = SqliteTrendRepository(":memory:" if storage == "memory" else str(tmp_path / "bootstrap.sqlite"))
    original_close = repository.close
    try:
        await repository._ensure_schema()
        if populated:
            conn = repository._get_connection()
            try:
                mission, source, observation = (str(uuid4()) for _ in range(3))
                conn.execute("INSERT INTO research_missions(id,title,keywords,created_at) VALUES (?, 'Existing mission', '[]', '2026-10-06')", (mission,))
                conn.execute("INSERT INTO sources(id,platform,external_id) VALUES (?, 'youtube', 'existing')", (source,))
                conn.execute(
                    "INSERT INTO observations(id,source_id,time_provenance,identity_source)"
                    " VALUES (?,?,'unknown','metadata_external_id')", (observation, source),
                )
                conn.execute("INSERT INTO mission_evidence(id,mission_id,observation_id,recorded_at) VALUES (?,?,?,?)", (str(uuid4()), mission, observation, "2026-10-06"))
                conn.commit()
            finally:
                if repository._mem_conn is None:
                    conn.close()
        _, before = _sqlite_state(repository)
        assert not OPERATIONAL_TABLES & before.keys()
        if storage == "file":
            # Each real CLI invocation obtains a fresh adapter over the same existing file.
            monkeypatch.setattr(persistence, "create_repository", lambda: SqliteTrendRepository(repository._db_path))
        else:
            monkeypatch.setattr(persistence, "create_repository", lambda: repository)
            # Retain the private-memory owner across calls to measure idempotence on one store.
            close = AsyncMock()
            monkeypatch.setattr(repository, "close", close)
        for _ in range(2):
            ready, _ = await bootstrap_database()
            assert ready is True
            _, current = _sqlite_state(repository)
            assert OPERATIONAL_TABLES <= current.keys()
            assert {table: current[table] for table in before} == before
            assert all(current[table] == [] for table in OPERATIONAL_TABLES)
        if storage == "memory":
            assert close.await_count == 2
    finally:
        await original_close()


@pytest.mark.asyncio
@pytest.mark.parametrize("helper", ("_ensure_progress_schema", "_ensure_research_schema"))
async def test_explicit_bootstrap_setup_failure_is_not_ready_and_closes_repository(tmp_path, monkeypatch, helper):
    repository = SqliteTrendRepository(str(tmp_path / "failure.sqlite"))
    monkeypatch.setattr(persistence, "create_repository", lambda: repository)
    failure = AsyncMock(side_effect=RuntimeError("Operational setup failed"))
    monkeypatch.setattr(repository, helper, failure)
    close = AsyncMock(wraps=repository.close)
    monkeypatch.setattr(repository, "close", close)
    ready, message = await bootstrap_database()
    assert ready is False and "Operational setup failed" in message
    failure.assert_awaited_once()
    close.assert_awaited_once()


@pytest.mark.asyncio
async def test_postgres_bootstrap_never_applies_sqlite_operational_setup(monkeypatch):
    repository = persistence.PostgresTimescaleRepository("postgresql://invalid.invalid/bootstrap-control")
    progress, research = AsyncMock(), AsyncMock()
    monkeypatch.setattr(repository, "_ensure_progress_schema", progress, raising=False)
    monkeypatch.setattr(repository, "_ensure_research_schema", research, raising=False)
    monkeypatch.setattr(repository, "get_domain_lexicons", AsyncMock(return_value=[]))
    close = AsyncMock(wraps=repository.close)
    monkeypatch.setattr(repository, "close", close)
    monkeypatch.setattr(persistence, "create_repository", lambda: repository)
    assert (await bootstrap_database())[0] is True
    progress.assert_not_awaited()
    research.assert_not_awaited()
    close.assert_awaited_once()


@pytest.mark.parametrize("helper", ("_ensure_progress_schema", "_ensure_research_schema"))
@pytest.mark.parametrize("json_output", (False, True))
def test_setup_caller_never_reports_ready_after_operational_failure(
    tmp_path, monkeypatch, capsys, helper, json_output,
):
    from ignis.interfaces.cli import setup_bundle

    repository = SqliteTrendRepository(str(tmp_path / "caller-failure.sqlite"))
    monkeypatch.setattr(persistence, "create_repository", lambda: repository)
    monkeypatch.setattr(repository, helper, AsyncMock(side_effect=RuntimeError("Operational setup failed")))
    monkeypatch.setattr(setup_bundle, "ensure_environment_file", lambda root: (False, "Fixture environment"))
    monkeypatch.setattr(setup_bundle, "setup_all_mcp_clients", lambda *args, **kwargs: [])
    monkeypatch.setattr(setup_bundle, "run_synthetic_diagnostics", AsyncMock(return_value={"database": "setup failed"}))
    report = setup_bundle.auto_provision(json_output=json_output)
    output = capsys.readouterr().out
    assert report["status"] == "warning"
    assert "Operational setup failed" in report["database"]
    assert "Ready for AI Agents" not in output
    if not json_output:
        assert "Setup incomplete" in output
