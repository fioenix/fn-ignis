"""Validated existing-schema writer: no bootstrap, seed or DDL on an existing caller store."""
import asyncio
import hashlib
import sqlite3

import pytest

from ignis.domain.exceptions import RepositoryException
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

PROTECTED = ('market_lexicons', 'industry_taxonomies', 'runtime_configs', 'platform_credentials',
             'research_workspaces')


def _store(directory, *, progress=True):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'canonical.sqlite3'

    async def build():
        repository = SqliteTrendRepository(str(path))
        await repository._ensure_schema()
        if progress:
            await repository._ensure_progress_schema()
        await repository.close()
    asyncio.run(build())
    return path


def _bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _open(path, digest):
    return asyncio.run(SqliteTrendRepository.open_existing_ready(str(path), expected_core_schema_digest=digest))


@pytest.fixture
def reference(tmp_path):
    return SqliteTrendRepository.existing_core_schema_digest(str(_store(tmp_path / 'reference', progress=False)))


def test_ready_store_opens_without_running_bootstrap_or_progress_ddl(tmp_path, reference, monkeypatch):
    store = _store(tmp_path / 'caller')
    before = _bytes(store)
    entered = []
    monkeypatch.setattr(SqliteTrendRepository, '_create_tables_and_seed', lambda self: entered.append('seed'))
    monkeypatch.setattr(SqliteTrendRepository, '_create_progress_tables', lambda self: entered.append('progress'))
    repository = _open(store, reference)

    async def exercise():
        await repository._ensure_schema()
        await repository._ensure_progress_schema()
        await repository.close()
    asyncio.run(exercise())
    assert entered == [], 'The ready path re-entered general bootstrap or progress DDL'
    assert _bytes(store) == before


@pytest.mark.parametrize('drift', [
    'CREATE INDEX extra_mission_index ON research_missions (status)',
    'DROP TRIGGER mission_progress_events_validate_update',
    'DROP TABLE mission_progress_commands',
])
def test_core_or_progress_drift_refuses_with_bytes_unchanged(tmp_path, reference, drift):
    store = _store(tmp_path / 'caller')
    with sqlite3.connect(store) as connection:
        connection.execute(drift)
    before = _bytes(store)
    with pytest.raises(RepositoryException):
        _open(store, reference)
    assert _bytes(store) == before


def test_wrong_progress_definition_with_correct_names_refuses(tmp_path, reference):
    store = _store(tmp_path / 'caller', progress=False)
    with sqlite3.connect(store) as connection:
        connection.executescript(
            'CREATE TABLE mission_progress_revisions (mission_id TEXT PRIMARY KEY, revision INTEGER);'
            'CREATE TABLE mission_progress_events (id TEXT PRIMARY KEY, mission_id TEXT);'
            'CREATE TABLE mission_progress_commands (mission_id TEXT, command_key TEXT,'
            ' PRIMARY KEY (mission_id, command_key));')
    before = _bytes(store)
    with pytest.raises(RepositoryException):
        _open(store, reference)
    assert _bytes(store) == before


def test_missing_or_memory_store_refuses_without_creating_a_file(tmp_path, reference):
    missing = tmp_path / 'absent.sqlite3'
    with pytest.raises(RepositoryException):
        _open(missing, reference)
    assert not missing.exists()
    with pytest.raises(RepositoryException):
        _open(':memory:', reference)


def test_ready_connections_reject_schema_changes_and_protected_table_writes(tmp_path, reference):
    store = _store(tmp_path / 'caller')
    repository = _open(store, reference)
    with sqlite3.connect(store) as connection:
        before = {table: connection.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in PROTECTED}
        schema = connection.execute('SELECT type, name, sql FROM sqlite_master ORDER BY 1, 2').fetchall()
    forbidden = (
        'CREATE TABLE extra_table (id TEXT)',
        'CREATE TEMP TABLE extra_temp (id TEXT)',
        'CREATE INDEX extra_index ON research_missions (status)',
        'DROP TRIGGER mission_progress_events_validate_insert',
        'ALTER TABLE research_missions ADD COLUMN extra TEXT',
        "INSERT INTO runtime_configs (key, value, created_at, updated_at) VALUES ('synthetic', '1', 'x', 'x')",
        'UPDATE market_lexicons SET term = term',
        'DELETE FROM industry_taxonomies',
        'DELETE FROM platform_credentials',
        "UPDATE mission_evidence_qualifications SET status = status",
        "INSERT INTO mission_claim_evidence (claim_id) VALUES ('x')",
        'DELETE FROM system_audit_logs',
        'DELETE FROM mission_claim_evidence',
        "UPDATE mission_claims SET status = 'WITHHELD'",
        'UPDATE research_workspaces SET name = name',
        'PRAGMA foreign_keys = OFF',
        'PRAGMA writable_schema = ON',
        'PRAGMA query_only = OFF',
        'PRAGMA journal_mode = WAL',
        "ATTACH DATABASE ':memory:' AS other",
    )
    connection = repository._get_connection()
    try:
        for statement in forbidden:
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute(statement)
            connection.rollback()
        assert connection.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    finally:
        connection.close()
    with sqlite3.connect(store) as connection:
        assert {table: connection.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall() for table in PROTECTED} == before
        assert connection.execute('SELECT type, name, sql FROM sqlite_master ORDER BY 1, 2').fetchall() == schema


def test_drift_after_open_refuses_the_next_writer_operation(tmp_path, reference):
    store = _store(tmp_path / 'caller')
    repository = _open(store, reference)
    with sqlite3.connect(store) as connection:
        connection.execute('DROP TRIGGER mission_progress_events_validate_update')
    with pytest.raises(RepositoryException):
        asyncio.run(repository._ensure_progress_schema())
    with pytest.raises(RepositoryException):
        asyncio.run(repository._ensure_schema())
    with sqlite3.connect(store) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert 'mission_progress_events_validate_update' not in names, 'Ready mode recreated a dropped trigger'


def test_default_bootstrap_is_unchanged(tmp_path):
    store = _store(tmp_path / 'default', progress=False)
    with sqlite3.connect(store) as connection:
        assert connection.execute('SELECT COUNT(*) FROM market_lexicons').fetchone()[0] > 0
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'mission_progress_%'").fetchone()[0] == 0
