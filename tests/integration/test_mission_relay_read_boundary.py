"""Physical reader boundaries on disposable stores; absent APIs remain explicit RED.

Setup is authorized fixture work completed before observation starts. Spies delegate
to real SQLite/libpq engines, never supply snapshots, and distinguish missing reader
APIs from executed refusal/no-write behavior. T013/T014 own the implementation.
"""

import asyncio
import hashlib
import importlib
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from conftest import RepositoryCase, _apply_postgres_schema
from ignis.application.ports.mission_relay_port import (
    IMissionRelayReader,
    MissionRelayRead,
    MissionRelayReadRequest,
    ProbeOutcomeCommitCommand,
)
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.mission_relay import (
    MissionRelayCursor,
    MissionRelayReadFailure,
    RelayReadReason,
    RelayReadStatus,
)
from ignis.domain.research_workspace import MissionProbeOutcome, ResearchWorkspace
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
READER_MODULE = "ignis.infrastructure.persistence.mission_relay_reader"
WRITE_SQL = re.compile(
    r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|REPLACE|TRUNCATE|VACUUM|REINDEX|ATTACH)\b",
    re.IGNORECASE,
)
FACT_TABLES = ("research_missions", "mission_run_journals", "mission_probe_outcomes", "mission_progress_events")


def _reader(repository):
    """Controller-approved concrete names, resolved only inside behavioral tests."""
    name = "SqliteMissionRelayReader" if isinstance(repository, SqliteTrendRepository) else "PostgresMissionRelayReader"
    try:
        module = importlib.import_module(READER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != READER_MODULE:
            raise
        pytest.fail(f"Dedicated relay reader API is absent: {READER_MODULE}.{name}")
    factory = getattr(module, name, None)
    assert callable(factory), f"Dedicated relay reader API is absent: {READER_MODULE}.{name}"
    reader = factory(repository)
    assert isinstance(reader, IMissionRelayReader)
    return reader


def _request(mission, run_id, **changes):
    return MissionRelayReadRequest(mission_id=mission.id, run_id=run_id, page_size=2, **changes)


def _refused(result, reason=RelayReadReason.READ_UNAVAILABLE):
    assert type(result) is MissionRelayReadFailure, "Unavailable storage must not become a successful empty snapshot"
    assert result.status in (RelayReadStatus.REFUSED, RelayReadStatus.UNAVAILABLE)
    assert result.reason_code is reason


def _setup_traps(monkeypatch, repository):
    """Trap setup and credential entry points, while leaving actual reads/SQL real."""
    def forbidden(*args, **kwargs):
        pytest.fail("Viewing invoked setup, seed, mutation, or credential lookup")

    for name in (
        "_ensure_schema", "_ensure_progress_schema", "_create_tables_and_seed",
        "_create_progress_tables", "get_platform_credentials", "list_platform_credentials",
        "save_signals", "save_mission", "record_run_journal", "commit_probe_outcomes",
    ):
        if hasattr(type(repository), name):
            monkeypatch.setattr(type(repository), name, forbidden)


def _files(root):
    return {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in root.iterdir() if path.is_file()
    }


def _sqlite_state(repository):
    conn = repository._mem_conn
    owned = conn is None
    if owned:
        conn = sqlite3.connect(Path(repository._db_path).as_uri() + "?mode=ro", uri=True)
    try:
        schema = list(conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"))
        names = [row[1] for row in schema if row[0] == "table"]
        # All identifiers come from the disposable local engine's schema, never user input.
        rows = {name: sorted(repr(tuple(row)) for row in conn.execute('SELECT * FROM "' + name.replace('"', '""') + '"')) for name in names}
        return tuple(map(tuple, schema)), rows
    finally:
        if owned:
            conn.close()


def _postgres_state(dsn):
    with psycopg.connect(dsn) as conn:
        names = [row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        columns = conn.execute(
            "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name, ordinal_position"
        ).fetchall()
        rows = {
            name: sorted(map(repr, conn.execute(sql.SQL("SELECT * FROM public.{}").format(sql.Identifier(name))).fetchall()))
            for name in names
        }
        return columns, rows


@dataclass
class SqliteObservation:
    statements: list
    opens: list

    def assert_no_writes(self, *, file_path=None):
        assert not [statement for statement in self.statements if WRITE_SQL.search(statement)]
        if file_path is not None:
            file_opens = [item for item in self.opens if item[0] != ":memory:"]
            assert file_opens, "A successful file snapshot must actually open the selected storage"
            for database, uri in file_opens:
                assert uri and urlsplit(database).scheme == "file"
                assert parse_qs(urlsplit(database).query).get("mode") == ["ro"]
                assert Path(urlsplit(database).path).resolve() == Path(file_path).resolve()


@contextmanager
def _observe_sqlite(monkeypatch, repository=None, after_select=None):
    statements, opens = [], []
    connect = sqlite3.connect

    def observed(statement):
        statements.append(statement)

    def selected(statement):
        if after_select is not None and statement.lstrip().upper().startswith("SELECT"):
            after_select(statement)

    class Cursor(sqlite3.Cursor):
        def execute(self, statement, *args):
            result = super().execute(statement, *args)
            selected(statement)
            return result

    class Connection(sqlite3.Connection):
        def execute(self, statement, *args):
            result = super().execute(statement, *args)
            selected(statement)
            return result

        def cursor(self, *args, **kwargs):
            kwargs.setdefault("factory", Cursor)
            return super().cursor(*args, **kwargs)

    def open_observed(database, *args, **kwargs):
        opens.append((str(database), kwargs.get("uri", False)))
        kwargs.setdefault("factory", Connection)
        conn = connect(database, *args, **kwargs)
        conn.set_trace_callback(observed)
        return conn

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", open_observed)
        if repository is not None and repository._mem_conn is not None:
            def shared_trace(statement):
                observed(statement)
                # The original private connection cannot be replaced with a fresh store.
                # A serialized reader may use it directly rather than a detached backup.
                selected(statement)
            repository._mem_conn.set_trace_callback(shared_trace)
        try:
            yield SqliteObservation(statements, opens)
        finally:
            if repository is not None and repository._mem_conn is not None:
                try:
                    repository._mem_conn.set_trace_callback(None)
                except sqlite3.ProgrammingError:
                    # The explicit concurrent-close case has already closed the actual owner.
                    pass


@contextmanager
def _observe_postgres(monkeypatch, after_select=None):
    """Observe real cursor execution and the live server transaction's settings."""
    statements, reads = [], []
    execute = psycopg.AsyncCursor.execute

    async def observed(cursor, query, *args, **kwargs):
        statement = query.as_string(cursor) if isinstance(query, sql.Composable) else str(query)
        statements.append(statement)
        result = await execute(cursor, query, *args, **kwargs)
        if statement.lstrip().upper().startswith("SELECT") and any(table in statement.lower() for table in FACT_TABLES):
            probe = cursor.connection.cursor(row_factory=psycopg.rows.tuple_row)
            try:
                await execute(probe,
                    "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation'), pg_backend_pid(), pg_current_snapshot()::text"
                )
                reads.append(await probe.fetchone())
            finally:
                await probe.close()
            if after_select is not None:
                await after_select(statement)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.AsyncCursor, "execute", observed)
        yield statements, reads


def _assert_postgres_reads(observation):
    statements, reads = observation
    assert reads, "No physical canonical/progress read transaction was observed"
    assert all(row[:2] == ("on", "repeatable read") for row in reads)
    assert len({row[2:] for row in reads}) == 1, "Evidence, operational state and high-water must share one server snapshot"
    assert not [statement for statement in statements if WRITE_SQL.search(statement)]


def _assert_borrowed_pool(repository, pool):
    assert repository._pool is pool, "Viewing replaced or released the caller-owned pool"
    assert not pool.closed, "Viewing closed the caller-owned pool"


@contextmanager
def _guard_caller_close(monkeypatch, repository):
    def forbidden(*args, **kwargs):
        pytest.fail("Viewing attempted to close the caller-owned repository")

    with monkeypatch.context() as patch:
        patch.setattr(repository, "close", forbidden)
        yield


@pytest_asyncio.fixture(params=("file", "memory", "postgres"))
async def relay_case(request, tmp_path):
    if request.param == "postgres":
        dsn = request.getfixturevalue("empty_postgres_dsn")
        _apply_postgres_schema(dsn)
        repository = PostgresTimescaleRepository(dsn, min_pool_size=1, max_pool_size=2)
        case = RepositoryCase("postgres", repository, dsn)
    else:
        repository = SqliteTrendRepository(":memory:" if request.param == "memory" else str(tmp_path / "relay.sqlite"))
        await repository._ensure_schema()
        await repository._ensure_progress_schema()
        case = RepositoryCase("sqlite", repository)
    workspace = ResearchWorkspace(slug="read-boundary", root_path=tmp_path / "workspace")
    await repository.save_research_workspace(workspace)
    missions = [ResearchMission(title=title, keywords=["synthetic"], workspace_id=workspace.workspace_id) for title in ("Selected before", "Unrelated")]
    runs = []
    for mission in missions:
        await repository.save_mission(mission)
        run_id = uuid4()
        runs.append(run_id)
        await repository.record_run_journal(RunJournal(
            run_id=run_id, mission_id=mission.id, workspace_id=workspace.workspace_id,
            journal_path=tmp_path / str(run_id), sequence=1, status="COMPLETED", started_at=NOW, completed_at=NOW,
        ))
        await repository.save_signals([
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title=f"Synthetic observation {index}",
                source_url=f"https://www.youtube.com/watch?v={str(mission.id).replace('-', '')[:9]}{index:02d}",
                mission_id=mission.id, captured_at=NOW)
            for index in range(3)
        ])
        await repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
            mission_id=mission.id, run_id=run_id, outcomes=(MissionProbeOutcome(
                run_id=run_id, platform="youtube", connector_surface="youtube", status=ChannelHealthStatus.HEALTHY,
                signals_collected=3, queried_keywords=("synthetic",), query_fingerprint="a" * 64, completed_at=NOW,
            ),),
        ))
    try:
        yield case, missions, runs
    finally:
        await repository.close()


def _state(case):
    return _postgres_state(case.dsn) if case.name == "postgres" else _sqlite_state(case.repository)


@pytest.mark.asyncio
async def test_fixture_control_has_selected_and_unrelated_physical_rows(relay_case):
    """A broken fixture cannot disguise missing/empty storage as a reader failure."""
    case, missions, runs = relay_case
    _, rows = _state(case)
    assert len(rows["mission_evidence"]) == 6
    assert len(rows["sources"]) == 6
    assert len(rows["mission_probe_outcomes"]) == 2
    assert len(rows["mission_progress_events"]) == 2
    assert len(missions) == len(runs) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("memory",), indirect=True)
async def test_memory_close_control_releases_owner_and_closes_captured_connection(relay_case):
    """The accepted real owner clears its field; physical closure uses the captured connection."""
    case, missions, runs = relay_case
    connection = case.repository._mem_conn
    assert connection.execute("SELECT count(*) FROM mission_evidence").fetchone()[0] == 6
    await case.repository.close()
    assert case.repository._mem_conn is None
    with pytest.raises(sqlite3.ProgrammingError):
        connection.execute("SELECT 1")


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("memory",), indirect=True)
@pytest.mark.parametrize("serialized", (False, True))
async def test_memory_ownership_control_freezes_reader_before_real_writer_dispatch(relay_case, serialized):
    """Real existing ownership and a copied physical view expose the late-lock classification bug."""
    case, missions, runs = relay_case
    repository = case.repository
    snapshot = sqlite3.connect(":memory:", check_same_thread=False)
    repository._mem_conn.backup(snapshot)
    snapshot.execute("BEGIN")
    assert snapshot.execute("SELECT title FROM research_missions WHERE id=?", (str(missions[0].id),)).fetchone() == ("Selected before",)
    entered, release = threading.Event(), threading.Event()
    admitted = asyncio.Event()
    writing = None
    owns_lock = False

    def mutation():
        conn = repository._mem_conn
        conn.execute("UPDATE research_missions SET title='Control after' WHERE id=?", (str(missions[0].id),))
        conn.commit()
        entered.set()
        assert release.wait(5), "Control writer was not released"

    async def admitted_writer():
        admitted.set()
        await repository._run_write(mutation)

    try:
        if serialized:
            await repository._lock.acquire()
            owns_lock = True
        # This actual state belongs to the held reader/fixture, before writer acquisition.
        reader_owned = repository._lock.locked()
        writing = asyncio.create_task(admitted_writer())
        await asyncio.wait_for(admitted.wait(), 5)
        if serialized:
            assert reader_owned and not writing.done() and not entered.is_set()
            repository._lock.release()
            owns_lock = False
        assert await asyncio.to_thread(entered.wait, 5)
        assert repository._lock.locked() and not writing.done()
        assert reader_owned is serialized
        # Detached reader ownership is still false even though the actual writer now owns
        # the very same lock. The old post-dispatch lock check could not distinguish them.
        release.set()
        await asyncio.wait_for(writing, 5)
        assert snapshot.execute("SELECT title FROM research_missions WHERE id=?", (str(missions[0].id),)).fetchone() == ("Selected before",)
        assert repository._mem_conn.execute("SELECT title FROM research_missions WHERE id=?", (str(missions[0].id),)).fetchone()[0] == "Control after"
    finally:
        release.set()
        if owns_lock:
            repository._lock.release()
        if writing is not None:
            await asyncio.gather(writing, return_exceptions=True)
        snapshot.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
async def test_postgres_pool_control_rejects_closed_and_recreated_caller_pool(relay_case, monkeypatch):
    """Real owner close/reopen must not masquerade as preservation of borrowed resources."""
    case, missions, runs = relay_case
    repository = case.repository
    pool = repository._pool
    assert pool is not None
    _assert_borrowed_pool(repository, pool)
    with _guard_caller_close(monkeypatch, repository):
        with pytest.raises(pytest.fail.Exception):
            await repository.close()
    _assert_borrowed_pool(repository, pool)
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT 1")).fetchone() == (1,)
    # Explicit control setup/teardown, not a product reader or unauthorized observation.
    await repository.close()
    assert repository._pool is None and pool.closed
    recreated = await repository._get_pool()
    assert recreated is not pool and not recreated.closed
    async with recreated.connection() as conn:
        assert conn.info.transaction_status is TransactionStatus.IDLE
    with pytest.raises(AssertionError):
        _assert_borrowed_pool(repository, pool)


def test_sqlite_observation_control_catches_real_write_and_readonly_refusal(tmp_path, monkeypatch):
    database = tmp_path / "control.sqlite"
    with _observe_sqlite(monkeypatch) as observation:
        with sqlite3.connect(database) as conn:
            conn.execute("CREATE TABLE sentinel (value TEXT)")
            conn.execute("INSERT INTO sentinel VALUES ('preserved')")
    assert any("CREATE TABLE sentinel" in statement for statement in observation.statements)
    assert any("INSERT INTO sentinel" in statement for statement in observation.statements)
    before = _files(tmp_path)
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO sentinel VALUES ('forbidden')")
        assert conn.execute("SELECT value FROM sentinel").fetchall() == [("preserved",)]
    assert _files(tmp_path) == before


@pytest.mark.asyncio
async def test_postgres_observation_control_catches_live_readonly_write_refusal(empty_postgres_dsn, monkeypatch):
    with psycopg.connect(empty_postgres_dsn) as conn:
        conn.execute("CREATE TABLE research_missions (title TEXT)")
        conn.execute("INSERT INTO research_missions VALUES ('preserved')")
    before = _postgres_state(empty_postgres_dsn)
    with _observe_postgres(monkeypatch) as observation:
        async with await psycopg.AsyncConnection.connect(empty_postgres_dsn) as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                assert await (await conn.execute("SELECT title FROM research_missions")).fetchone() == ("preserved",)
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    await conn.execute("INSERT INTO research_missions VALUES ('forbidden')")
    assert any("INSERT INTO research_missions" in statement for statement in observation[0])
    assert observation[1][0][:2] == ("on", "repeatable read")
    assert _postgres_state(empty_postgres_dsn) == before


@pytest.mark.asyncio
async def test_legacy_sqlite_snapshot_control_physically_bootstraps_absent_storage(tmp_path, monkeypatch):
    """Characterize the unsuitable legacy path; this is not reader acceptance."""
    database = tmp_path / "legacy.sqlite"
    repository = SqliteTrendRepository(str(database))
    assert not database.exists()
    try:
        with _observe_sqlite(monkeypatch, repository) as observation:
            result = await repository.load_mission_evidence_snapshot(uuid4())
        assert result.mission is None
        assert database.exists()
        assert any("CREATE TABLE" in statement.upper() for statement in observation.statements)
        assert any("INSERT" in statement.upper() and "market_lexicons" in statement for statement in observation.statements)
        _, rows = _sqlite_state(repository)
        assert rows["market_lexicons"] and "research_missions" in rows
        assert "mission_progress_events" not in rows
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("storage", ("absent", "fresh", "old", "canonical_only", "incompatible_populated"))
async def test_sqlite_missing_or_old_schema_refuses_repeatedly_without_bootstrap(storage, tmp_path, monkeypatch):
    database = tmp_path / "refusal.sqlite"
    repository = SqliteTrendRepository(str(database))
    if storage in ("fresh", "old"):
        with sqlite3.connect(database) as conn:
            if storage == "old":
                conn.execute("CREATE TABLE mission_progress_events (legacy_id INTEGER)")
                conn.execute("INSERT INTO mission_progress_events VALUES (7)")
    elif storage in ("canonical_only", "incompatible_populated"):
        await repository._ensure_schema()
        with sqlite3.connect(database) as conn:
            conn.execute("CREATE TABLE unrelated_sentinel (value TEXT)")
            conn.execute("INSERT INTO unrelated_sentinel VALUES ('must survive')")
        if storage == "incompatible_populated":
            await repository._ensure_progress_schema()
            with sqlite3.connect(database) as conn:
                conn.execute("ALTER TABLE mission_progress_events RENAME COLUMN ordinal TO obsolete_ordinal")
    before_files = _files(tmp_path)
    before = _sqlite_state(repository) if database.exists() else None
    try:
        _setup_traps(monkeypatch, repository)
        with _observe_sqlite(monkeypatch, repository) as observation:
            reader = _reader(repository)
            request = MissionRelayReadRequest(mission_id=uuid4(), run_id=None, page_size=2)
            for _ in range(2):
                _refused(await reader.load_snapshot(request))
        observation.assert_no_writes()
        assert _files(tmp_path) == before_files
        assert (_sqlite_state(repository) if database.exists() else None) == before
        if storage == "absent":
            assert not database.exists()
    finally:
        await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("storage", ("missing", "old"))
async def test_postgres_missing_or_old_schema_refuses_without_initialization(storage, empty_postgres_dsn, monkeypatch):
    if storage == "old":
        _apply_postgres_schema(empty_postgres_dsn)
        with psycopg.connect(empty_postgres_dsn) as conn:
            conn.execute("ALTER TABLE mission_progress_events RENAME COLUMN ordinal TO obsolete_ordinal")
            conn.execute("CREATE TABLE unrelated_sentinel (value TEXT)")
            conn.execute("INSERT INTO unrelated_sentinel VALUES ('must survive')")
    repository = PostgresTimescaleRepository(empty_postgres_dsn, min_pool_size=1, max_pool_size=2)
    before = _postgres_state(empty_postgres_dsn)
    try:
        _setup_traps(monkeypatch, repository)
        with _observe_postgres(monkeypatch) as observation:
            reader = _reader(repository)
            request = MissionRelayReadRequest(mission_id=uuid4(), run_id=None, page_size=2)
            for _ in range(2):
                _refused(await reader.load_snapshot(request))
        assert not [statement for statement in observation[0] if WRITE_SQL.search(statement)]
        assert _postgres_state(empty_postgres_dsn) == before
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_uninitialized_private_memory_refuses_without_bootstrap(monkeypatch):
    repository = SqliteTrendRepository(":memory:")
    before = _sqlite_state(repository)
    changes = repository._mem_conn.total_changes
    try:
        _setup_traps(monkeypatch, repository)
        with _observe_sqlite(monkeypatch, repository) as observation:
            reader = _reader(repository)
            for _ in range(2):
                _refused(await reader.load_snapshot(MissionRelayReadRequest(mission_id=uuid4(), run_id=None, page_size=2)))
        observation.assert_no_writes()
        assert _sqlite_state(repository) == before
        assert repository._mem_conn.total_changes == changes
        assert not repository._mem_conn.in_transaction
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_initialized_reader_is_physical_readonly_and_preserves_unrelated_storage(relay_case, monkeypatch):
    case, missions, runs = relay_case
    before = _state(case)
    repository = case.repository
    files = _files(Path(repository._db_path).parent) if case.name == "sqlite" and repository._mem_conn is None else None
    changes = repository._mem_conn.total_changes if case.name == "sqlite" and repository._mem_conn is not None else None
    pool = repository._pool if case.name == "postgres" else None
    if case.name == "postgres":
        assert pool is not None
        _assert_borrowed_pool(repository, pool)
    _setup_traps(monkeypatch, repository)
    observer = _observe_postgres(monkeypatch) if case.name == "postgres" else _observe_sqlite(monkeypatch, repository)
    with _guard_caller_close(monkeypatch, repository), observer as observation:
        reader = _reader(repository)
        result = await reader.load_snapshot(_request(missions[0], runs[0]))
    assert type(result) is MissionRelayRead
    assert result.run.run_id == runs[0] and result.evidence.mission.id == missions[0].id
    assert result.total_observations == result.source_count == 3
    assert len(result.evidence.signals) == 2
    assert result.next_evidence_offset == 2
    assert all(signal.mission_id == missions[0].id for signal in result.evidence.signals)
    assert result.high_water.position == (1, 1)
    assert [event.run_id for event in result.events.events] == [runs[0]]
    if case.name == "postgres":
        _assert_postgres_reads(observation)
        _assert_borrowed_pool(repository, pool)
        async with pool.connection() as conn:
            assert conn.info.transaction_status is TransactionStatus.IDLE
            assert await (await conn.execute("SELECT 1")).fetchone() == (1,)
        _assert_borrowed_pool(repository, pool)
    else:
        observation.assert_no_writes(file_path=repository._db_path if files is not None else None)
        if changes is not None:
            assert repository._mem_conn.total_changes == changes
            assert not repository._mem_conn.in_transaction
        if files is not None:
            assert _files(Path(repository._db_path).parent) == files
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
@pytest.mark.parametrize("cursor_case", ("unknown", "future", "deleted", "missed"))
async def test_postgres_unknown_or_missed_cursor_resyncs_without_replay(relay_case, cursor_case, monkeypatch):
    """A retained cursor with a missing committed suffix cannot replay history."""
    case, missions, runs = relay_case
    mission_id = missions[0].id
    with psycopg.connect(case.dsn) as conn:
        for revision in (2, 3):
            conn.execute(
                "INSERT INTO mission_progress_events"
                " (id,mission_id,revision,ordinal,kind,provenance,causation_key,recorded_at)"
                " VALUES (%s,%s,%s,1,'WORK_STARTED','HOST_REPORTED',%s,%s)",
                (uuid4(), mission_id, revision, f"history:{revision}", NOW),
            )
        conn.execute("UPDATE mission_progress_revisions SET revision=3 WHERE mission_id=%s", (mission_id,))
        if cursor_case in ("deleted", "missed"):
            conn.execute("DELETE FROM mission_progress_events WHERE mission_id=%s AND revision=%s",
                (mission_id, 1 if cursor_case == "deleted" else 2))
    before = _state(case)
    revision, ordinal = {"unknown": (2, 2), "future": (4, 1), "deleted": (1, 1), "missed": (1, 1)}[cursor_case]
    cursor = MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=ordinal)
    _setup_traps(monkeypatch, case.repository)
    result = await _reader(case.repository).load_snapshot(_request(missions[0], runs[0], after_cursor=cursor))
    assert type(result) is MissionRelayRead
    assert result.high_water.position == (3, 1)
    assert result.events.resync_required
    assert result.events.events == () and result.events.after_cursor is None
    assert result.events.next_cursor is None and not result.events.has_more
    assert result.total_observations == result.source_count == 3
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
@pytest.mark.parametrize("record", ("outcome", "qualification", "manifest", "brief", "claim"))
async def test_postgres_domain_decode_failure_returns_typed_unavailable_without_repair(relay_case, record, monkeypatch):
    """SQL-accepted malformed canonical values remain typed unavailable, without repair."""
    case, missions, runs = relay_case
    mission = missions[0]
    with psycopg.connect(case.dsn) as conn:
        if record == "qualification":
            observation = conn.execute("SELECT observation_id FROM mission_evidence WHERE mission_id=%s LIMIT 1", (mission.id,)).fetchone()[0]
            conn.execute(
                "INSERT INTO mission_evidence_qualifications"
                " (mission_id,observation_id,frame_fingerprint,relation,purpose,reason_code,judged_by)"
                " VALUES (%s,%s,%s,'UNASSESSED','CONTEXT','EVALUATOR_UNAVAILABLE','reader-fixture')",
                (mission.id, observation, "a" * 64),
            )
        elif record == "manifest":
            conn.execute(
                "INSERT INTO mission_manifests"
                " (mission_id,outcome,required_channels,authority_boundary,output_type,stop_conditions,"
                " analysis_policy,retention_policy,created_by,confirmed_at,manifest_digest)"
                " VALUES (%s,'Read fixture',ARRAY['youtube'],"
                " '{\"public_http\":true,\"official_api\":false,\"browser_session\":false,\"paid_quota\":false}',"
                " 'COLLECTION_FRAME',ARRAY['completion'],'reader-fixture','retain','reader-fixture',%s,%s)",
                (mission.id, NOW, "b" * 64),
            )
        elif record == "brief":
            conn.execute(
                "INSERT INTO market_brief_revisions"
                " (id,workspace_id,mission_id,revision_number,decision,target_user,problem,geo,timeframe,"
                " hypothesis,falsifiers,confirmed_by)"
                " VALUES (%s,%s,%s,1,'Decide','Operator','Unknown demand','VN','7d',"
                " 'Demand exists',ARRAY['No demand'],'reader-fixture')",
                (uuid4(), mission.workspace_id, mission.id),
            )
        elif record == "claim":
            conn.execute(
                "INSERT INTO mission_claims"
                " (mission_id,frame_digest,client_claim_key,claim_type,wording,status,created_by)"
                " VALUES (%s,%s,'reader-fixture','OBSERVATION','Recorded fact','WITHHELD','reader-fixture')",
                (mission.id, "c" * 64),
            )
    reader = _reader(case.repository)
    request = _request(mission, runs[0])
    assert type(await reader.load_snapshot(request)) is MissionRelayRead
    statement, identity = {
        "outcome": ("UPDATE mission_probe_outcomes SET query_fingerprint='' WHERE run_id=%s", runs[0]),
        "qualification": ("UPDATE mission_evidence_qualifications SET frame_fingerprint='' WHERE mission_id=%s", mission.id),
        "manifest": ("UPDATE mission_manifests SET outcome='' WHERE mission_id=%s", mission.id),
        "brief": ("UPDATE market_brief_revisions SET decision='' WHERE mission_id=%s", mission.id),
        "claim": ("UPDATE mission_claims SET wording='' WHERE mission_id=%s", mission.id),
    }[record]
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute(statement, (identity,)).rowcount == 1
    before, pool = _state(case), case.repository._pool
    _setup_traps(monkeypatch, case.repository)
    with _guard_caller_close(monkeypatch, case.repository), _observe_postgres(monkeypatch) as observation:
        for _ in range(2):
            first_statement, first_read = len(observation[0]), len(observation[1])
            result = await reader.load_snapshot(request)
            _refused(result)
            assert result.status is RelayReadStatus.UNAVAILABLE
            _assert_postgres_reads((observation[0][first_statement:], observation[1][first_read:]))
    _assert_borrowed_pool(case.repository, pool)
    assert _state(case) == before


@contextmanager
def _observe_postgres_connections(monkeypatch, before_close=None):
    """Delegate real opens/closes and record actual invoking-loop ownership and settlement."""
    opened, closed = [], []
    connect, close = psycopg.AsyncConnection.connect, psycopg.AsyncConnection.close

    async def tracked_connect(cls, *args, **kwargs):
        conn = await connect(*args, **kwargs)
        opened.append((conn, asyncio.get_running_loop(), conn.info.backend_pid))
        return conn

    async def tracked_close(conn):
        if before_close is not None:
            await before_close()
        closed.append((conn, asyncio.get_running_loop(), conn.info.transaction_status))
        return await close(conn)

    with monkeypatch.context() as patch:
        patch.setattr(psycopg.AsyncConnection, "connect", classmethod(tracked_connect))
        patch.setattr(psycopg.AsyncConnection, "close", tracked_close)
        yield opened, closed


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
@pytest.mark.parametrize("concurrent", (False, True))
async def test_postgres_reader_owns_connections_in_each_invoking_loop(relay_case, concurrent, monkeypatch):
    """Foreign-loop loads must not use the original live caller pool or share a connection."""
    case, missions, runs = relay_case
    pool, caller_loop = case.repository._pool, asyncio.get_running_loop()
    reader = _reader(case.repository)
    _setup_traps(monkeypatch, case.repository)
    barrier, held = threading.Barrier(2), set()
    execute = psycopg.AsyncCursor.execute
    executions, receipts = [], []

    async def tracked_execute(cursor, query, *args, **kwargs):
        result = await execute(cursor, query, *args, **kwargs)
        statement = str(query)
        if statement.lstrip().upper().startswith("SELECT") and any(table in statement.lower() for table in FACT_TABLES):
            executions.append((cursor.connection, asyncio.get_running_loop()))
            async with cursor.connection.cursor(row_factory=psycopg.rows.tuple_row) as probe:
                await execute(probe,
                    "SELECT current_setting('transaction_read_only'),current_setting('transaction_isolation'),"
                    " pg_backend_pid(),pg_current_snapshot()::text")
                receipts.append((cursor.connection, await probe.fetchone()))
            if concurrent and cursor.connection not in held:
                held.add(cursor.connection)
                await asyncio.to_thread(barrier.wait, 5)
        return result

    def foreign_read():
        return asyncio.run(reader.load_snapshot(_request(missions[0], runs[0])))

    before = _state(case)
    with _guard_caller_close(monkeypatch, case.repository), _observe_postgres_connections(monkeypatch) as resources:
        monkeypatch.setattr(psycopg.AsyncCursor, "execute", tracked_execute)
        if concurrent:
            results = await asyncio.wait_for(asyncio.gather(asyncio.to_thread(foreign_read), asyncio.to_thread(foreign_read)), 10)
        else:
            results = [await asyncio.wait_for(asyncio.to_thread(foreign_read), 5) for _ in range(2)]
    assert all(type(result) is MissionRelayRead and result.high_water.position == (1, 1) for result in results)
    opened, closed = resources
    assert len(opened) == len(closed) == 2
    assert len({id(conn) for conn, _, _ in opened}) == 2
    assert len({id(loop) for _, loop, _ in opened}) == 2
    assert len({pid for _, _, pid in opened}) == 2
    assert all(loop is not caller_loop for _, loop, _ in opened)
    assert all(conn.closed for conn, _, _ in opened)
    assert all(status is TransactionStatus.IDLE for _, _, status in closed)
    assert all(any(conn is owned and loop is owner_loop for owned, owner_loop, _ in opened) for conn, loop in executions)
    assert all(any(conn is owned and loop is owner_loop for owned, owner_loop, _ in opened) for conn, loop, _ in closed)
    for owned, _, pid in opened:
        observed = [row for conn, row in receipts if conn is owned]
        assert observed and all(row[:3] == ("on", "repeatable read", pid) for row in observed)
        assert len({row[3] for row in observed}) == 1
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid=ANY(%s)", ([pid for _, _, pid in opened],)).fetchone() == (0,)
    _assert_borrowed_pool(case.repository, pool)
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT 1")).fetchone() == (1,)
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
@pytest.mark.parametrize("decode_error", (False, True))
@pytest.mark.parametrize("cancel_stage", ("read", "close"))
async def test_postgres_cancelled_reader_settles_transaction_and_owned_connection(relay_case, decode_error, cancel_stage, monkeypatch):
    """Repeated cancellation waits through real transaction exit and close, including errors."""
    case, missions, runs = relay_case
    if decode_error:
        with psycopg.connect(case.dsn) as conn:
            conn.execute("UPDATE mission_probe_outcomes SET query_fingerprint='' WHERE run_id=%s", (runs[0],))
    before, pool = _state(case), case.repository._pool
    reader = _reader(case.repository)
    entered, release = asyncio.Event(), asyncio.Event()
    held = False

    async def hold(statement):
        nonlocal held
        if not held:
            held = True
            entered.set()
            await release.wait()

    async def hold_close():
        entered.set()
        await release.wait()

    _setup_traps(monkeypatch, case.repository)
    with _guard_caller_close(monkeypatch, case.repository), _observe_postgres_connections(
        monkeypatch, hold_close if cancel_stage == "close" else None,
    ) as resources, _observe_postgres(monkeypatch, hold if cancel_stage == "read" else None) as observation:
        reading = asyncio.create_task(reader.load_snapshot(_request(missions[0], runs[0])))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            reading.cancel()
            await asyncio.sleep(0)
            reading.cancel()
            await asyncio.sleep(0)
            opened, closed = resources
            assert not reading.done() and len(opened) == 1 and closed == []
            assert not opened[0][0].closed
            _assert_borrowed_pool(case.repository, pool)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(reading, 5)
        finally:
            release.set()
            await asyncio.gather(reading, return_exceptions=True)
    _assert_postgres_reads(observation)
    assert len(opened) == len(closed) == 1
    assert closed[0][0] is opened[0][0] and closed[0][1] is opened[0][1]
    assert closed[0][2] is TransactionStatus.IDLE and opened[0][0].closed
    with psycopg.connect(case.dsn) as conn:
        assert conn.execute("SELECT count(*) FROM pg_stat_activity WHERE pid=%s", (opened[0][2],)).fetchone() == (0,)
    _assert_borrowed_pool(case.repository, pool)
    async with pool.connection() as conn:
        assert await (await conn.execute("SELECT 1")).fetchone() == (1,)
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
async def test_postgres_reader_connection_physically_refuses_evidence_write(relay_case, monkeypatch):
    """The reader's actual connection must reject an evidence UPDATE at the server."""
    case, missions, runs = relay_case
    before, execute, refused = _state(case), psycopg.AsyncCursor.execute, []

    async def attempted(cursor, query, *args, **kwargs):
        result = await execute(cursor, query, *args, **kwargs)
        if not refused and str(query).lstrip().upper().startswith("SELECT") and "research_missions" in str(query):
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                await execute(cursor.connection.cursor(), "UPDATE research_missions SET title='Forbidden'")
            refused.append(cursor.connection)
        return result

    reader = _reader(case.repository)
    monkeypatch.setattr(psycopg.AsyncCursor, "execute", attempted)
    _refused(await reader.load_snapshot(_request(missions[0], runs[0])))
    assert len(refused) == 1 and refused[0].closed
    assert _state(case) == before


@pytest.mark.asyncio
async def test_postgres_reader_borrows_identity_without_opening_or_initializing_caller(empty_postgres_dsn, monkeypatch):
    """Construction without a running loop is inert; absent schema never initializes a pool."""
    repository = PostgresTimescaleRepository(empty_postgres_dsn, min_pool_size=1, max_pool_size=2)
    before = _postgres_state(empty_postgres_dsn)
    _setup_traps(monkeypatch, repository)
    with _observe_postgres_connections(monkeypatch) as resources, _observe_postgres(monkeypatch) as observation:
        reader = await asyncio.to_thread(_reader, repository)
        assert resources == ([], []) and observation == ([], [])
        for _ in range(2):
            _refused(await reader.load_snapshot(MissionRelayReadRequest(mission_id=uuid4(), run_id=None, page_size=2)))
        assert repository._pool is None
    opened, closed = resources
    assert len(opened) == len(closed) == 2 and all(conn.closed for conn, _, _ in opened)
    assert all(status is TransactionStatus.IDLE for _, _, status in closed)
    assert not [statement for statement in observation[0] if WRITE_SQL.search(statement)]
    assert _postgres_state(empty_postgres_dsn) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
async def test_postgres_selected_journal_outcomes_do_not_use_newer_same_mission_run(relay_case, monkeypatch):
    """Native PostgreSQL run outcomes retain the exact selected run, including explicit null."""
    case, missions, runs = relay_case
    mission, newer = missions[0], uuid4()
    await case.repository.record_run_journal(RunJournal(
        run_id=newer, mission_id=mission.id, workspace_id=mission.workspace_id,
        journal_path=Path("/synthetic/newer"), sequence=2, status="COMPLETED", started_at=NOW, completed_at=NOW,
    ))
    await case.repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=mission.id, run_id=newer, outcomes=(MissionProbeOutcome(
            run_id=newer, platform="youtube", connector_surface="youtube", status=ChannelHealthStatus.EMPTY_NO_DATA,
            signals_collected=0, queried_keywords=("other",), query_fingerprint="c" * 64, completed_at=NOW,
        ),),
    ))
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    reader = _reader(case.repository)
    selected = await reader.load_snapshot(_request(mission, runs[0]))
    assert type(selected) is MissionRelayRead and selected.run.run_id == runs[0]
    assert len(selected.evidence.outcomes) == 1
    assert selected.evidence.outcomes[0].run_id == runs[0] and selected.evidence.outcomes[0].signals_collected == 3
    unspecified = await reader.load_snapshot(_request(mission, None))
    assert type(unspecified) is MissionRelayRead and unspecified.run is None
    assert unspecified.evidence.outcomes == () and unspecified.high_water.position == (2, 1)
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
async def test_postgres_native_unknown_observation_facts_remain_null(relay_case, monkeypatch):
    """Native NULL ingestion/publication/reach must not receive timestamps or zeroes."""
    case, missions, runs = relay_case
    with psycopg.connect(case.dsn) as conn:
        conn.execute(
            "UPDATE observations SET observed_at=NULL,published_at=NULL,time_provenance='unknown',"
            " metric_value=NULL,growth_velocity=NULL"
            " WHERE id IN (SELECT observation_id FROM mission_evidence WHERE mission_id=%s)", (missions[0].id,),
        )
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    result = await _reader(case.repository).load_snapshot(_request(missions[0], runs[0]))
    assert type(result) is MissionRelayRead and len(result.evidence.signals) == 2
    assert result.total_observations == result.source_count == 3
    assert all(signal.captured_at is None and signal.published_at is None
        and signal.metric_value is None and signal.growth_velocity is None and signal.time_provenance == "unknown"
        for signal in result.evidence.signals)
    assert all(signal.observation_id is not None and signal.source_id is not None for signal in result.evidence.signals)
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("postgres",), indirect=True)
async def test_postgres_event_pages_decode_native_references_and_continue_without_replay(relay_case, monkeypatch):
    """Two real committed revisions preserve typed reference identities and page continuation."""
    case, missions, runs = relay_case
    mission_id = missions[0].id
    await case.repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=mission_id, run_id=runs[0], outcomes=(MissionProbeOutcome(
            run_id=runs[0], platform="youtube", connector_surface="youtube.comments", status=ChannelHealthStatus.HEALTHY,
            signals_collected=1, queried_keywords=("synthetic",), query_fingerprint="d" * 64, completed_at=NOW,
        ),),
    ))
    with psycopg.connect(case.dsn) as conn:
        observation_id, source_id = conn.execute(
            "SELECT o.id,o.source_id FROM mission_evidence e JOIN observations o ON o.id=e.observation_id"
            " WHERE e.mission_id=%s ORDER BY o.id LIMIT 1", (mission_id,),
        ).fetchone()
        conn.execute(
            "UPDATE mission_progress_events SET evidence_references=%s WHERE mission_id=%s AND revision=1",
            (Jsonb([dict(mission_id=str(mission_id), observation_id=str(observation_id), source_id=str(source_id),
                evidence_role="ATTENTION_CONTEXT", direction=None, qualification_relation=None, qualification_frame_fingerprint=None)]), mission_id),
        )
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    reader = _reader(case.repository)
    initial = MissionRelayCursor(mission_id=mission_id, revision=0, ordinal=0)
    request = MissionRelayReadRequest(mission_id=mission_id, run_id=runs[0], page_size=1, after_cursor=initial)
    first = await reader.load_snapshot(request)
    assert type(first) is MissionRelayRead and first.high_water.position == (2, 1)
    assert first.events.after_cursor == initial and not first.events.resync_required
    assert [event.cursor.position for event in first.events.events] == [(1, 1)]
    assert first.events.has_more and first.events.next_cursor.position == (1, 1)
    reference, = first.events.events[0].evidence_references
    assert (reference.mission_id, reference.observation_id, reference.source_id) == (mission_id, observation_id, source_id)
    second = await reader.load_snapshot(replace(request, after_cursor=first.events.next_cursor))
    assert type(second) is MissionRelayRead and second.high_water == first.high_water
    assert [event.cursor.position for event in second.events.events] == [(2, 1)]
    assert not second.events.resync_required and not second.events.has_more and second.events.next_cursor is None
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", ("unknown_run", "foreign_run", "unknown_mission", "null_run"))
async def test_selected_scope_never_falls_back_to_latest_run(relay_case, selection, monkeypatch):
    case, missions, runs = relay_case
    before = _state(case)
    mission = missions[0]
    run = {"unknown_run": uuid4(), "foreign_run": runs[1], "unknown_mission": runs[0], "null_run": None}[selection]
    if selection == "unknown_mission":
        mission = replace(mission, id=uuid4())
    _setup_traps(monkeypatch, case.repository)
    reader = _reader(case.repository)
    result = await reader.load_snapshot(_request(mission, run))
    if selection == "null_run":
        assert type(result) is MissionRelayRead
        assert result.run is None and result.request.run_id is None
    else:
        _refused(result, RelayReadReason.SCOPE_MISMATCH)
    assert _state(case) == before


@pytest.mark.asyncio
async def test_selected_cursor_and_evidence_offset_remain_bounded(relay_case, monkeypatch):
    case, missions, runs = relay_case
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    reader = _reader(case.repository)
    cursor = MissionRelayCursor(mission_id=missions[0].id, revision=1, ordinal=1)
    result = await reader.load_snapshot(_request(missions[0], runs[0], after_cursor=cursor, evidence_offset=2))
    assert type(result) is MissionRelayRead
    assert result.events.after_cursor == cursor and result.events.events == ()
    assert result.high_water == cursor
    assert result.total_observations == result.source_count == 3
    assert len(result.evidence.signals) == 1 and result.next_evidence_offset is None
    assert result.evidence.signals[0].mission_id == missions[0].id
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory", "postgres"), indirect=True)
async def test_evidence_operational_state_and_highwater_share_pinned_transaction(relay_case, monkeypatch):
    """Commit a real competing publication after a reader SELECT has established its view."""
    case, missions, runs = relay_case
    reader = _reader(case.repository)
    writer = (PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=2) if case.name == "postgres"
        else case.repository if case.repository._mem_conn is not None else SqliteTrendRepository(case.repository._db_path))
    if case.name == "sqlite" and case.repository._mem_conn is None:
        with sqlite3.connect(case.repository._db_path) as conn:
            assert conn.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    entered = asyncio.Event()
    release = asyncio.Event()
    thread_release = threading.Event()
    loop = asyncio.get_running_loop()
    held = False

    async def hold_postgres(statement):
        nonlocal held
        if not held:
            held = True
            entered.set()
            await release.wait()

    def hold_sqlite(statement):
        nonlocal held
        if not held and any(table in statement.lower() for table in FACT_TABLES):
            held = True
            loop.call_soon_threadsafe(entered.set)
            assert thread_release.wait(5), "Reader scheduling hook was not released"

    observer = (_observe_postgres(monkeypatch, hold_postgres) if case.name == "postgres"
        else _observe_sqlite(monkeypatch, case.repository, hold_sqlite))
    task = writing = None
    writer_entered = asyncio.Event()
    run_write = writer._run_write if case.name == "sqlite" else None

    async def tracked_write(operation):
        writer_entered.set()
        return await run_write(operation)

    if case.name == "sqlite":
        monkeypatch.setattr(writer, "_run_write", tracked_write)

    async def mutate():
        if case.name == "postgres":
            with psycopg.connect(case.dsn) as conn:
                conn.execute("UPDATE research_missions SET title='Selected after' WHERE id=%s", (missions[0].id,))
                conn.execute("UPDATE mission_run_journals SET status='FAILED' WHERE id=%s", (runs[0],))
        else:
            def change_receipts():
                conn = writer._get_connection()
                try:
                    conn.execute("UPDATE research_missions SET title='Selected after' WHERE id=?", (str(missions[0].id),))
                    conn.execute("UPDATE mission_run_journals SET status='FAILED' WHERE id=?", (str(runs[0]),))
                    conn.commit()
                finally:
                    if writer._mem_conn is None:
                        conn.close()
            await writer._run_write(change_receipts)
        await writer.save_signals([TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Committed during read",
            source_url="https://www.youtube.com/watch?v=after000001", mission_id=missions[0].id, captured_at=NOW)])
        await writer.commit_probe_outcomes(ProbeOutcomeCommitCommand(
            mission_id=missions[0].id, run_id=runs[0], outcomes=(MissionProbeOutcome(
                run_id=runs[0], platform="youtube", connector_surface="youtube.comments", status=ChannelHealthStatus.HEALTHY,
                signals_collected=1, queried_keywords=("synthetic",), query_fingerprint="b" * 64, completed_at=NOW,
            ),),
        ))

    try:
        with observer as observation:
            task = asyncio.create_task(reader.load_snapshot(_request(missions[0], runs[0])))
            await asyncio.wait_for(entered.wait(), 5)
            reader_owned = writer is case.repository and writer._lock.locked()
            writing = asyncio.create_task(mutate())
            if writer is case.repository:
                await asyncio.wait_for(writer_entered.wait(), 5)
                if reader_owned:
                    # Actual existing ownership keeps the admitted writer pending. Allow this
                    # valid shared-connection strategy, without requiring a detached backup.
                    assert not writing.done() and not task.done()
                    thread_release.set()
                    result = await asyncio.wait_for(task, 5)
                    await asyncio.wait_for(writing, 5)
                else:
                    await asyncio.wait_for(writing, 5)
            else:
                await asyncio.wait_for(writing, 5)
            release.set()
            thread_release.set()
            result = await asyncio.wait_for(task, 5)
        assert type(result) is MissionRelayRead
        assert (result.evidence.mission.title, result.run.status, result.total_observations, result.high_water.position) == ("Selected before", "COMPLETED", 3, (1, 1))
        assert len(result.evidence.outcomes) == 1
        if case.name == "postgres":
            # Writer calls are also physically observed; only the read receipts must pin one view.
            read_receipts = [row for row in observation[1] if row[:2] == ("on", "repeatable read")]
            assert read_receipts and len({row[2:] for row in read_receipts}) == 1
        fresh = await reader.load_snapshot(_request(missions[0], runs[0]))
        assert (fresh.evidence.mission.title, fresh.run.status, fresh.total_observations, fresh.high_water.position) == ("Selected after", "FAILED", 4, (2, 1))
        assert len(fresh.evidence.outcomes) == 2
    finally:
        release.set()
        thread_release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        if writing is not None:
            await asyncio.gather(writing, return_exceptions=True)
        if writer is not case.repository:
            await writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("memory",), indirect=True)
async def test_private_memory_snapshot_survives_concurrent_owner_close(relay_case, monkeypatch):
    """A real owner close may serialize or leave a detached view; neither may tear it."""
    case, missions, runs = relay_case
    repository = case.repository
    owner_connection = repository._mem_conn
    reader = _reader(repository)
    selected, close_entered = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    held = False
    close = repository.close

    def hold(statement):
        nonlocal held
        if not held and any(table in statement.lower() for table in FACT_TABLES):
            held = True
            loop.call_soon_threadsafe(selected.set)
            assert release.wait(5), "Pinned memory read was not released"

    async def closing():
        close_entered.set()
        await close()

    tasks = []
    try:
        with _observe_sqlite(monkeypatch, repository, after_select=hold):
            reading = asyncio.create_task(reader.load_snapshot(_request(missions[0], runs[0])))
            tasks.append(reading)
            await asyncio.wait_for(selected.wait(), 5)
            closing_task = asyncio.create_task(closing())
            tasks.append(closing_task)
            await asyncio.wait_for(close_entered.wait(), 5)
            release.set()
            result = await asyncio.wait_for(reading, 5)
            await asyncio.wait_for(closing_task, 5)
        assert type(result) is MissionRelayRead
        assert (result.total_observations, result.high_water.position, result.run.status) == (3, (1, 1), "COMPLETED")
        assert all(signal.mission_id == missions[0].id for signal in result.evidence.signals)
        assert repository._mem_conn is None
        with pytest.raises(sqlite3.ProgrammingError):
            owner_connection.execute("SELECT 1")
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
@pytest.mark.parametrize("cursor_case", ("unknown", "future", "deleted", "missed"))
async def test_sqlite_unknown_or_missed_cursor_resyncs_without_replay(relay_case, cursor_case, monkeypatch):
    """Unknown positions and a retained cursor with a missing suffix cannot replay history."""
    case, missions, runs = relay_case
    repository, mission_id = case.repository, missions[0].id

    def arrange_history():
        conn = repository._get_connection()
        try:
            for revision in (2, 3):
                conn.execute(
                    "INSERT INTO mission_progress_events"
                    " (id, mission_id, revision, ordinal, kind, provenance, causation_key, recorded_at)"
                    " VALUES (?, ?, ?, 1, 'WORK_STARTED', 'HOST_REPORTED', ?, ?)",
                    (str(uuid4()), str(mission_id), revision, f"history:{revision}", NOW.isoformat()),
                )
            conn.execute("UPDATE mission_progress_revisions SET revision=3 WHERE mission_id=?", (str(mission_id),))
            if cursor_case in ("deleted", "missed"):
                removed = 1 if cursor_case == "deleted" else 2
                conn.execute("DELETE FROM mission_progress_events WHERE mission_id=? AND revision=?", (str(mission_id), removed))
            conn.commit()
        finally:
            if repository._mem_conn is None:
                conn.close()

    await repository._run_write(arrange_history)
    before = _state(case)
    position = {"unknown": (2, 2), "future": (4, 1), "deleted": (1, 1), "missed": (1, 1)}[cursor_case]
    cursor = MissionRelayCursor(mission_id=mission_id, revision=position[0], ordinal=position[1])
    _setup_traps(monkeypatch, repository)
    result = await _reader(repository).load_snapshot(_request(missions[0], runs[0], after_cursor=cursor))
    assert type(result) is MissionRelayRead
    assert result.high_water.position == (3, 1)
    assert result.events.resync_required
    assert result.events.events == () and result.events.after_cursor is None
    assert result.events.next_cursor is None and not result.events.has_more
    assert result.total_observations == result.source_count == 3
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_sqlite_reader_connection_physically_refuses_evidence_write(relay_case, monkeypatch):
    """An attempted real UPDATE on the pinned reader connection must be read-only."""
    case, missions, runs = relay_case
    before = _state(case)
    opened, attempted = [], []

    def attempt_write(statement):
        if not attempted and any(table in statement.lower() for table in FACT_TABLES):
            conn = opened[-1]
            assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
            attempted.append(True)
            with pytest.raises(sqlite3.OperationalError, match="readonly"):
                conn.execute("UPDATE research_missions SET title='Unauthorized reader write' WHERE id=?", (str(missions[0].id),))

    _setup_traps(monkeypatch, case.repository)
    with _observe_sqlite(monkeypatch, case.repository, after_select=attempt_write):
        connect = sqlite3.connect

        def capture_connection(*args, **kwargs):
            conn = connect(*args, **kwargs)
            opened.append(conn)
            return conn

        with monkeypatch.context() as patch:
            patch.setattr(sqlite3, "connect", capture_connection)
            result = await _reader(case.repository).load_snapshot(_request(missions[0], runs[0]))
    assert attempted == [True]
    assert type(result) is MissionRelayRead and result.evidence.mission.title == "Selected before"
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_sqlite_reader_includes_committed_uncheckpointed_wal(relay_case, monkeypatch):
    """A live file read must observe committed WAL facts, never an immutable main-file shortcut."""
    case, missions, runs = relay_case
    database = Path(case.repository._db_path)
    writer = sqlite3.connect(database)
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE research_missions SET title='Committed WAL fact' WHERE id=?", (str(missions[0].id),))
        writer.commit()
        assert Path(str(database) + "-wal").stat().st_size > 32
        before = _state(case)
        _setup_traps(monkeypatch, case.repository)
        with _observe_sqlite(monkeypatch, case.repository) as observation:
            result = await _reader(case.repository).load_snapshot(_request(missions[0], runs[0]))
        assert type(result) is MissionRelayRead
        assert result.evidence.mission.title == "Committed WAL fact"
        assert result.total_observations == result.source_count == 3
        observation.assert_no_writes(file_path=str(database))
        assert _state(case) == before
    finally:
        writer.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_sqlite_reader_refuses_dangling_canonical_evidence(relay_case, monkeypatch):
    """Broken canonical joins cannot be disguised as a shorter successful evidence page."""
    case, missions, runs = relay_case
    repository, mission_id = case.repository, missions[0].id

    def corrupt_lineage():
        conn = repository._get_connection()
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                "UPDATE observations SET source_id=? WHERE id IN"
                " (SELECT observation_id FROM mission_evidence WHERE mission_id=? LIMIT 1)",
                (str(uuid4()), str(mission_id)),
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=ON")
        finally:
            if repository._mem_conn is None:
                conn.close()

    await repository._run_write(corrupt_lineage)
    before = _state(case)
    _setup_traps(monkeypatch, repository)
    _refused(await _reader(repository).load_snapshot(_request(missions[0], runs[0])))
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_sqlite_event_pages_continue_without_replay_or_false_resync(relay_case, monkeypatch):
    """A real two-revision stream keeps its continuation and reaches the pinned high-water."""
    case, missions, runs = relay_case
    await case.repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=missions[0].id, run_id=runs[0], outcomes=(MissionProbeOutcome(
            run_id=runs[0], platform="youtube", connector_surface="youtube.comments",
            status=ChannelHealthStatus.HEALTHY, signals_collected=1,
            queried_keywords=("synthetic",), query_fingerprint="d" * 64, completed_at=NOW,
        ),),
    ))
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    reader = _reader(case.repository)
    initial = MissionRelayCursor(mission_id=missions[0].id, revision=0, ordinal=0)
    request = MissionRelayReadRequest(mission_id=missions[0].id, run_id=runs[0], page_size=1, after_cursor=initial)
    first = await reader.load_snapshot(request)
    assert type(first) is MissionRelayRead
    assert first.high_water.position == (2, 1)
    assert first.events.after_cursor == initial and not first.events.resync_required
    assert [event.cursor.position for event in first.events.events] == [(1, 1)]
    assert first.events.has_more and first.events.next_cursor.position == (1, 1)
    second = await reader.load_snapshot(replace(request, after_cursor=first.events.next_cursor))
    assert type(second) is MissionRelayRead
    assert second.high_water == first.high_water
    assert [event.cursor.position for event in second.events.events] == [(2, 1)]
    assert not second.events.resync_required and not second.events.has_more
    assert second.events.next_cursor is None
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("memory",), indirect=True)
async def test_sqlite_cancelled_backup_retains_ownership_and_closes_detached_connection(relay_case, monkeypatch):
    """Repeated cancellation cannot let owner close overtake an unsettled real backup."""
    case, missions, runs = relay_case
    repository = case.repository
    owner = repository._mem_conn
    reader = _reader(repository)
    copying, closing = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    copy_memory = reader._copy_memory
    detached = []

    def held_copy():
        loop.call_soon_threadsafe(copying.set)
        assert release.wait(5), "Actual memory backup dispatch was not released"
        conn = copy_memory()
        detached.append(conn)
        return conn

    async def close_owner():
        closing.set()
        await repository.close()

    monkeypatch.setattr(reader, "_copy_memory", held_copy)
    reading = asyncio.create_task(reader.load_snapshot(_request(missions[0], runs[0])))
    closing_task = None
    try:
        await asyncio.wait_for(copying.wait(), 5)
        assert repository._lock.locked()
        reading.cancel()
        await asyncio.sleep(0)
        reading.cancel()
        closing_task = asyncio.create_task(close_owner())
        await asyncio.wait_for(closing.wait(), 5)
        assert not reading.done() and not closing_task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(reading, 5)
        await asyncio.wait_for(closing_task, 5)
        assert repository._mem_conn is None and not repository._lock.locked()
        assert len(detached) == 1
        for conn in (owner, detached[0]):
            with pytest.raises(sqlite3.ProgrammingError):
                conn.execute("SELECT 1")
    finally:
        release.set()
        await asyncio.gather(reading, *([closing_task] if closing_task is not None else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
@pytest.mark.parametrize("record", ("outcome", "qualification", "manifest", "brief", "claim"))
async def test_sqlite_domain_decode_failure_returns_typed_unavailable_without_repair(relay_case, record, monkeypatch):
    """SQL-accepted malformed canonical rows must not escape the advertised typed boundary."""
    case, missions, runs = relay_case
    repository, mission = case.repository, missions[0]
    mission_id, workspace_id = str(mission.id), str(mission.workspace_id)
    owner = repository._mem_conn

    def arrange_valid_row():
        conn = repository._get_connection()
        try:
            if record == "qualification":
                observation = conn.execute("SELECT observation_id FROM mission_evidence WHERE mission_id=? LIMIT 1", (mission_id,)).fetchone()[0]
                conn.execute(
                    "INSERT INTO mission_evidence_qualifications"
                    " (id,mission_id,observation_id,frame_fingerprint,relation,purpose,reason_code,judged_by,created_at)"
                    " VALUES (?,?,?,?,'UNASSESSED','CONTEXT','EVALUATOR_UNAVAILABLE','reader-fixture',?)",
                    (str(uuid4()), mission_id, observation, "a" * 64, NOW.isoformat()),
                )
            elif record == "manifest":
                conn.execute(
                    "INSERT INTO mission_manifests"
                    " (mission_id,outcome,required_channels,authority_boundary,output_type,stop_conditions,"
                    " analysis_policy,retention_policy,created_by,confirmed_at,manifest_digest)"
                    " VALUES (?,'Read fixture','[\"youtube\"]',"
                    " '{\"public_http\":true,\"official_api\":false,\"browser_session\":false,\"paid_quota\":false}',"
                    " 'COLLECTION_FRAME','[\"completion\"]','reader-fixture','retain','reader-fixture',?,?)",
                    (mission_id, NOW.isoformat(), "b" * 64),
                )
            elif record == "brief":
                conn.execute(
                    "INSERT INTO market_brief_revisions"
                    " (id,workspace_id,mission_id,revision_number,decision,target_user,problem,geo,timeframe,"
                    " hypothesis,falsifiers,confirmed_by,confirmed_at)"
                    " VALUES (?,?,?,1,'Decide','Operator','Unknown demand','VN','7d','Demand exists',"
                    " '[\"No demand\"]','reader-fixture',?)",
                    (str(uuid4()), workspace_id, mission_id, NOW.isoformat()),
                )
            elif record == "claim":
                conn.execute(
                    "INSERT INTO mission_claims"
                    " (id,mission_id,frame_digest,client_claim_key,claim_type,wording,status,created_by,created_at)"
                    " VALUES (?,?,?,'reader-fixture','OBSERVATION','Recorded fact','WITHHELD','reader-fixture',?)",
                    (str(uuid4()), mission_id, "c" * 64, NOW.isoformat()),
                )
            conn.commit()
        finally:
            if repository._mem_conn is None:
                conn.close()

    await repository._run_write(arrange_valid_row)
    reader = _reader(repository)
    request = _request(mission, runs[0])
    assert type(await reader.load_snapshot(request)) is MissionRelayRead
    corrupt_sql = {
        "outcome": ("UPDATE mission_probe_outcomes SET query_fingerprint='' WHERE run_id=?", str(runs[0])),
        "qualification": ("UPDATE mission_evidence_qualifications SET frame_fingerprint='' WHERE mission_id=?", mission_id),
        "manifest": ("UPDATE mission_manifests SET outcome='' WHERE mission_id=?", mission_id),
        "brief": ("UPDATE market_brief_revisions SET decision='' WHERE mission_id=?", mission_id),
        "claim": ("UPDATE mission_claims SET wording='' WHERE mission_id=?", mission_id),
    }[record]

    def corrupt_record():
        conn = repository._get_connection()
        try:
            assert conn.execute(corrupt_sql[0], (corrupt_sql[1],)).rowcount == 1
            conn.commit()
        finally:
            if repository._mem_conn is None:
                conn.close()

    await repository._run_write(corrupt_record)
    before = _state(case)
    changes = owner.total_changes if owner is not None else None
    _setup_traps(monkeypatch, repository)
    with _guard_caller_close(monkeypatch, repository), _observe_sqlite(monkeypatch, repository) as observation:
        for _ in range(2):
            result = await reader.load_snapshot(request)
            _refused(result)
            assert result.status is RelayReadStatus.UNAVAILABLE
    observation.assert_no_writes(file_path=repository._db_path if owner is None else None)
    assert _state(case) == before
    assert repository._mem_conn is owner
    if owner is not None:
        assert owner.total_changes == changes and not owner.in_transaction
        assert owner.execute("SELECT 1").fetchone()[0] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_sqlite_selected_journal_outcomes_do_not_use_newer_same_mission_run(relay_case, monkeypatch):
    """A later completed run cannot replace the explicitly requested run's facts."""
    case, missions, runs = relay_case
    repository, mission = case.repository, missions[0]
    newer_run = uuid4()
    later = datetime(2030, 1, 1, tzinfo=timezone.utc)
    await repository.record_run_journal(RunJournal(
        run_id=newer_run, mission_id=mission.id, workspace_id=mission.workspace_id,
        journal_path=Path(repository._db_path).parent / str(newer_run), sequence=2,
        status="COMPLETED", started_at=later, completed_at=later,
    ))
    await repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=mission.id, run_id=newer_run, outcomes=(MissionProbeOutcome(
            run_id=newer_run, platform="youtube", connector_surface="youtube",
            status=ChannelHealthStatus.EMPTY_NO_DATA, signals_collected=0,
            queried_keywords=("other",), query_fingerprint="c" * 64, completed_at=later,
        ),),
    ))
    before = _state(case)
    _setup_traps(monkeypatch, repository)
    result = await _reader(repository).load_snapshot(_request(mission, runs[0]))
    assert type(result) is MissionRelayRead
    assert result.run.run_id == runs[0]
    assert len(result.evidence.outcomes) == 1
    assert result.evidence.outcomes[0].run_id == runs[0]
    assert result.evidence.outcomes[0].signals_collected == 3
    assert result.high_water.position == (2, 1)
    assert _state(case) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "memory"), indirect=True)
async def test_sqlite_reader_preserves_unknown_observation_times_and_measurements(relay_case, monkeypatch):
    """Unknown persisted times/reach remain unknown in the bounded typed evidence page."""
    case, missions, runs = relay_case
    repository, mission_id = case.repository, missions[0].id

    def arrange_unknown_facts():
        conn = repository._get_connection()
        try:
            conn.execute(
                "UPDATE observations SET observed_at=NULL, published_at=NULL,"
                " time_provenance='unknown', metric_value=NULL, growth_velocity=NULL"
                " WHERE id IN (SELECT observation_id FROM mission_evidence WHERE mission_id=?)",
                (str(mission_id),),
            )
            conn.commit()
        finally:
            if repository._mem_conn is None:
                conn.close()

    await repository._run_write(arrange_unknown_facts)
    before = _state(case)
    _setup_traps(monkeypatch, repository)
    result = await _reader(repository).load_snapshot(_request(missions[0], runs[0]))
    assert type(result) is MissionRelayRead
    assert len(result.evidence.signals) == 2
    assert result.total_observations == result.source_count == 3
    assert all(
        signal.captured_at is None and signal.published_at is None
        and signal.metric_value is None and signal.growth_velocity is None
        and signal.time_provenance == "unknown"
        for signal in result.evidence.signals
    )
    assert all(signal.source_id is not None and signal.observation_id is not None for signal in result.evidence.signals)
    assert _state(case) == before


async def _publish_additional_run(repository, mission, journal_path):
    run_id = uuid4()
    await repository.record_run_journal(RunJournal(
        run_id=run_id, mission_id=mission.id, workspace_id=mission.workspace_id,
        journal_path=journal_path, sequence=2, status="COMPLETED", started_at=NOW, completed_at=NOW,
    ))
    await repository.commit_probe_outcomes(ProbeOutcomeCommitCommand(
        mission_id=mission.id, run_id=run_id, outcomes=(MissionProbeOutcome(
            run_id=run_id, platform="youtube", connector_surface="youtube.search",
            status=ChannelHealthStatus.EMPTY_NO_DATA, signals_collected=0,
            queried_keywords=("synthetic",), query_fingerprint="e" * 64, completed_at=NOW,
        ),),
    ))
    return run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("ownership", ("mission", "workspace"))
@pytest.mark.parametrize("selection", ("omitted", "different_valid_run"))
@pytest.mark.parametrize("cursor", ("omitted", "consumed_corrupt_event", "future_resync"))
async def test_event_journal_scope_mutation_refuses_entire_pinned_read(
    relay_case, tmp_path, monkeypatch, ownership, selection, cursor
):
    """Later owner SQL must not hide foreign canonical event lineage behind run/page selection."""
    case, missions, runs = relay_case
    repository, mission = case.repository, missions[0]
    selected_run = await _publish_additional_run(repository, mission, tmp_path / "additional-run")
    other_workspace = ResearchWorkspace(slug="other-event-owner", root_path=tmp_path / "other-workspace")
    await repository.save_research_workspace(other_workspace)
    column, value = ("mission_id", missions[1].id) if ownership == "mission" else ("workspace_id", other_workspace.workspace_id)
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as conn:
            assert conn.execute(f"UPDATE mission_run_journals SET {column}=%s WHERE id=%s", (value, runs[0])).rowcount == 1
    else:
        def mutate():
            conn = repository._get_connection()
            try:
                assert conn.execute(f"UPDATE mission_run_journals SET {column}=? WHERE id=?", (str(value), str(runs[0]))).rowcount == 1
                conn.commit()
            finally:
                if repository._mem_conn is None:
                    conn.close()
        await repository._run_write(mutate)
    after = None if cursor == "omitted" else MissionRelayCursor(
        mission_id=mission.id, revision=1 if cursor == "consumed_corrupt_event" else 99, ordinal=1,
    )
    request = _request(mission, None if selection == "omitted" else selected_run, after_cursor=after)
    before = _state(case)
    pool = repository._pool if case.name == "postgres" else None
    reader = _reader(repository)
    _setup_traps(monkeypatch, repository)
    observer = _observe_postgres(monkeypatch) if case.name == "postgres" else _observe_sqlite(monkeypatch, repository)
    with _guard_caller_close(monkeypatch, repository), observer as observation:
        result = await reader.load_snapshot(request)
        _refused(result)
        assert result.status is RelayReadStatus.UNAVAILABLE
    if case.name == "postgres":
        _assert_postgres_reads(observation)
        _assert_borrowed_pool(repository, pool)
    else:
        observation.assert_no_writes(file_path=repository._db_path if repository._mem_conn is None else None)
    assert _state(case) == before


@pytest.mark.asyncio
async def test_selected_outcome_run_preserves_full_same_mission_event_stream(relay_case, tmp_path, monkeypatch):
    """Protecting lineage must not silently filter mission events to the requested outcome run."""
    case, missions, runs = relay_case
    repository, mission = case.repository, missions[0]
    later_run = await _publish_additional_run(repository, mission, tmp_path / "additional-run")
    before = _state(case)
    reader = _reader(repository)
    _setup_traps(monkeypatch, repository)
    for selected, expected_outcome_runs in ((None, ()), (runs[0], (runs[0],)), (later_run, (later_run,))):
        result = await reader.load_snapshot(_request(mission, selected))
        assert type(result) is MissionRelayRead
        assert result.high_water.position == (2, 1)
        assert tuple(event.run_id for event in result.events.events) == (runs[0], later_run)
        assert tuple(outcome.run_id for outcome in result.evidence.outcomes) == expected_outcome_runs
        assert result.total_observations == 3 and result.source_count == 3
    assert _state(case) == before
