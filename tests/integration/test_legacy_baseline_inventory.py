"""Legacy baseline inventory is a read-only disposition proposal, not a migration."""

import hashlib
import json
import sqlite3

import pytest

from ignis.application.use_cases.inventory_legacy_baseline import InventoryLegacyBaselineUseCase
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest.mark.asyncio
async def test_inventory_targets_only_unscoped_rows_without_writing_or_promotion(tmp_path):
    database = tmp_path / "legacy.db"
    repository = SqliteTrendRepository(f"sqlite:///{database}")
    await repository._ensure_schema()
    await repository.close()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, source_url,"
            " captured_at) VALUES (?, 'youtube', 'Legacy', 1, ?, ?)",
            ("legacy-1", "https://example.test/1", "2026-09-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, mission_id,"
            " captured_at) VALUES (?, 'youtube', 'Mission', 1, ?, ?)",
            ("mission-1", "00000000-0000-4000-8000-000000000001", "2026-09-02T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO signal_metrics (signal_id, captured_at, metric_value)"
            " VALUES ('legacy-1', '2026-09-01T01:00:00+00:00', 2)"
        )
        conn.execute(
            "INSERT INTO signal_metrics (signal_id, captured_at, metric_value)"
            " VALUES ('mission-1', '2026-09-02T01:00:00+00:00', 2)"
        )
        conn.commit()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    inventory = await InventoryLegacyBaselineUseCase(
        WorkspaceRepository(SqliteTrendRepository(f"sqlite:///{database}"))
    ).execute()

    assert inventory["status"] == "INVENTORY_ONLY"
    assert inventory["deletion_candidates"] == [
        {
            "table": "trend_signals",
            "id": "legacy-1",
            "captured_at": "2026-09-01T00:00:00+00:00",
            "linked_metric_ids": [1],
        }
    ]
    assert inventory["archive_candidates"] == []
    assert inventory["excluded_mission_rows"] == 1
    assert inventory["source_url_present"] == 1
    assert inventory["recovery_required_before_deletion"] is True
    assert inventory["promoted_to_mission_evidence"] is False
    assert before == hashlib.sha256(database.read_bytes()).hexdigest()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT count(*) FROM mission_evidence").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_retention_reason_moves_target_to_archive_without_changing_database(tmp_path):
    database = tmp_path / "legacy.db"
    repository = SqliteTrendRepository(f"sqlite:///{database}")
    await repository._ensure_schema()
    await repository.close()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, captured_at)"
            " VALUES ('legacy-2', 'google', 'Old query', 1, '2026-08-01T00:00:00+00:00')"
        )
        conn.commit()
    before = database.read_bytes()

    inventory = await InventoryLegacyBaselineUseCase(
        WorkspaceRepository(SqliteTrendRepository(f"sqlite:///{database}"))
    ).execute(retention_reasons={"legacy-2": "Audit obligation"})

    assert inventory["archive_candidates"] == [
        {
            "table": "trend_signals",
            "id": "legacy-2",
            "captured_at": "2026-08-01T00:00:00+00:00",
            "linked_metric_ids": [],
            "reason": "Audit obligation",
        }
    ]
    assert inventory["deletion_candidates"] == []
    assert database.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["   ", None])
async def test_blank_retention_reason_refuses_instead_of_marking_deletion_candidate(tmp_path, reason):
    database = tmp_path / "legacy.db"
    repository = SqliteTrendRepository(f"sqlite:///{database}")
    await repository._ensure_schema()
    await repository.close()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, captured_at)"
            " VALUES ('legacy-2', 'google', 'Old query', 1, '2026-08-01')"
        )
        conn.commit()

    use_case = InventoryLegacyBaselineUseCase(
        WorkspaceRepository(SqliteTrendRepository(f"sqlite:///{database}"))
    )
    with pytest.raises(ValueError, match="Retention reason must be non-empty"):
        await use_case.execute(retention_reasons={"legacy-2": reason})


@pytest.mark.asyncio
async def test_inventory_refuses_missing_database_instead_of_initializing_it(tmp_path):
    database = tmp_path / "absent.db"
    use_case = InventoryLegacyBaselineUseCase(
        WorkspaceRepository(SqliteTrendRepository(f"sqlite:///{database}"))
    )
    with pytest.raises((FileNotFoundError, sqlite3.OperationalError)):
        await use_case.execute()
    assert not database.exists()


def test_inventory_cli_prints_json_without_modifying_existing_file(tmp_path, monkeypatch, capsys):
    from scripts.inventory_legacy_baseline import main

    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            "CREATE TABLE trend_signals (id TEXT, mission_id TEXT, captured_at TEXT,"
            " source_url TEXT, metadata TEXT);"
            "CREATE TABLE signal_metrics (id INTEGER, signal_id TEXT);"
            "CREATE TABLE mission_evidence (id TEXT);"
        )
        conn.execute(
            "INSERT INTO trend_signals VALUES ('legacy-3', NULL, '2026-07-01', NULL, NULL)"
        )
        conn.commit()
    before = database.read_bytes()
    monkeypatch.setattr(
        "sys.argv", ["inventory_legacy_baseline.py", "--dsn", f"sqlite:///{database}"]
    )

    assert main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["deletion_candidates"][0]["id"] == "legacy-3"
    assert payload["status"] == "INVENTORY_ONLY"
    assert database.read_bytes() == before


def test_inventory_cli_accepts_explicit_retention_reasons(tmp_path, monkeypatch, capsys):
    from scripts.inventory_legacy_baseline import main

    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            "CREATE TABLE trend_signals (id TEXT, mission_id TEXT, captured_at TEXT,"
            " source_url TEXT, metadata TEXT);"
            "CREATE TABLE signal_metrics (id INTEGER, signal_id TEXT);"
        )
        conn.execute(
            "INSERT INTO trend_signals VALUES ('keep-1', NULL, '2026-07-01', NULL, NULL)"
        )
        conn.commit()
    reasons = tmp_path / "reasons.json"
    reasons.write_text(json.dumps({"keep-1": "Required for audit"}), encoding="utf-8")
    before = database.read_bytes()
    monkeypatch.setattr(
        "sys.argv",
        [
            "inventory_legacy_baseline.py",
            "--dsn", f"sqlite:///{database}",
            "--retention-file", str(reasons),
        ],
    )

    assert main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["archive_candidates"][0]["reason"] == "Required for audit"
    assert payload["deletion_candidates"] == []
    assert database.read_bytes() == before


@pytest.mark.asyncio
async def test_orphan_metrics_are_quarantined_and_targets_have_stable_digest(tmp_path):
    database = tmp_path / "legacy.db"
    repository = SqliteTrendRepository(f"sqlite:///{database}")
    await repository._ensure_schema()
    await repository.close()
    with sqlite3.connect(database) as conn:
        conn.execute(
            "INSERT INTO signal_metrics (signal_id, captured_at)"
            " VALUES ('missing-parent', '2026-06-01T00:00:00+00:00')"
        )
        conn.commit()
    use_case = InventoryLegacyBaselineUseCase(
        WorkspaceRepository(SqliteTrendRepository(f"sqlite:///{database}"))
    )

    first = await use_case.execute()
    second = await use_case.execute()

    assert first["archive_candidates"] == [
        {"table": "signal_metrics", "id": 1, "reason": "MISSING_PARENT"}
    ]
    assert first["deletion_candidates"] == []
    assert first["target_digest"] == second["target_digest"]


@pytest.mark.asyncio
async def test_inventory_does_not_leave_shared_memory_connection_read_only():
    repository = SqliteTrendRepository("sqlite:///:memory:")
    try:
        await repository._ensure_schema()
        await repository.inventory_legacy_baseline()
        repository._mem_conn.execute(
            "INSERT INTO trend_signals (id, platform, raw_title, metric_value, captured_at)"
            " VALUES ('later', 'google', 'Later', 1, '2026-06-01')"
        )
        assert repository._mem_conn.execute(
            "SELECT count(*) FROM trend_signals"
        ).fetchone()[0] == 1
    finally:
        await repository.close()
