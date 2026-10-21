"""T005: the sql/032 watchlist schema on SQLite, fresh and added to an existing store."""

import asyncio
import json
import sqlite3
import uuid

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

NOW = "2026-10-21T01:00:00+00:00"
TABLES = ("watchlists", "watchlist_versions", "watchlist_runs")


def _bootstrap(path):
    async def run():
        repository = SqliteTrendRepository(str(path))
        await repository._ensure_schema()
        await repository.close()

    asyncio.run(run())


def _connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _seed(conn):
    workspace, watchlist, mission = (str(uuid.uuid4()) for _ in range(3))
    conn.execute("INSERT INTO research_workspaces (id, slug, root_path, created_at) VALUES (?, 'w', '/tmp/w', ?)",
                 (workspace, NOW))
    conn.execute("INSERT INTO watchlists (id, workspace_id, name, name_key, created_at) VALUES (?, ?, 'Matcha', 'matcha', ?)",
                 (watchlist, workspace, NOW))
    conn.execute("INSERT INTO watchlist_versions (watchlist_id, version, definition, definition_digest, created_at)"
                 " VALUES (?, 1, ?, ?, ?)", (watchlist, json.dumps({"topics": []}), "a" * 64, NOW))
    conn.execute("INSERT INTO research_missions (id, title, keywords, status, created_at) VALUES (?, 'run', '[]', 'PENDING', ?)",
                 (mission, NOW))
    conn.execute("INSERT INTO watchlist_runs (mission_id, watchlist_id, version, started_at) VALUES (?, ?, 1, ?)",
                 (mission, watchlist, NOW))
    return workspace, watchlist, mission


def test_fresh_store_has_the_three_tables(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    _bootstrap(path)
    conn = _connect(path)
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(TABLES) <= names


def test_store_without_watchlists_gains_them_and_matches_a_fresh_store(tmp_path):
    fresh, older = tmp_path / "fresh.sqlite3", tmp_path / "older.sqlite3"
    _bootstrap(fresh)
    _bootstrap(older)
    conn = sqlite3.connect(older)
    conn.execute("DROP TRIGGER refuse_watchlist_version_update")
    for table in reversed(TABLES):
        conn.execute(f"DROP TABLE {table}")
    conn.commit()
    conn.close()
    assert SqliteTrendRepository.existing_core_schema_digest(str(older)) != \
        SqliteTrendRepository.existing_core_schema_digest(str(fresh))
    _bootstrap(older)
    assert SqliteTrendRepository.existing_core_schema_digest(str(older)) == \
        SqliteTrendRepository.existing_core_schema_digest(str(fresh))


def test_versions_are_immutable_but_cascade_with_their_workspace(tmp_path):
    path = tmp_path / "s.sqlite3"
    _bootstrap(path)
    conn = _connect(path)
    workspace, watchlist, mission = _seed(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE watchlist_versions SET definition_digest = ? WHERE watchlist_id = ?", ("b" * 64, watchlist))
    conn.execute("DELETE FROM research_workspaces WHERE id = ?", (workspace,))
    assert [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES] == [0, 0, 0]
    assert conn.execute("SELECT count(*) FROM research_missions WHERE id = ?", (mission,)).fetchone()[0] == 1


@pytest.mark.parametrize("statement,params", [
    ("INSERT INTO watchlists (id, workspace_id, name, name_key, created_at) VALUES (?, ?, 'MATCHA', 'matcha', ?)", "dup"),
    ("INSERT INTO watchlists (id, workspace_id, name, name_key, created_at) VALUES (?, ?, ' x', 'x', ?)", "dup"),
    ("INSERT INTO watchlist_versions (watchlist_id, version, definition, definition_digest, created_at)"
     " VALUES (?, 2, '[]', 'aaaa', ?)", "version"),
    ("INSERT INTO watchlist_versions (watchlist_id, version, definition, definition_digest, created_at)"
     " VALUES (?, 0, '{}', ?, ?)", "zero"),
    ("INSERT INTO watchlist_runs (mission_id, watchlist_id, version, started_at) VALUES (?, ?, 9, ?)", "run"),
])
def test_constraints_refuse(tmp_path, statement, params):
    path = tmp_path / "s.sqlite3"
    _bootstrap(path)
    conn = _connect(path)
    workspace, watchlist, mission = _seed(conn)
    other_mission = str(uuid.uuid4())
    conn.execute("INSERT INTO research_missions (id, title, keywords, status, created_at) VALUES (?, 'r', '[]', 'PENDING', ?)",
                 (other_mission, NOW))
    values = {
        "dup": (str(uuid.uuid4()), workspace, NOW),
        "version": (watchlist, NOW),
        "zero": (watchlist, "c" * 64, NOW),
        "run": (other_mission, watchlist, NOW),
    }[params]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(statement, values)
