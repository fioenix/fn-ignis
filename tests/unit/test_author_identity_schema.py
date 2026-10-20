"""T006/T007: the sql/031 schema on SQLite, fresh and upgraded in place from an older store."""

import asyncio
import sqlite3
import uuid

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

# The two tables exactly as a store created before sql/031 has them.
PRE_031_OBSERVATIONS = """
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    cluster_id TEXT REFERENCES topic_clusters(id) ON DELETE SET NULL,
    observed_at TEXT,
    published_at TEXT,
    time_provenance TEXT NOT NULL
        CHECK (time_provenance IN ('exact_ingestion', 'legacy_publish_only', 'unknown')),
    identity_source TEXT NOT NULL
        CHECK (identity_source IN ('metadata_external_id', 'url_external_id',
                                   'normalized_url_fallback')),
    observed_title TEXT,
    metric_value REAL DEFAULT 0.0,
    growth_velocity REAL DEFAULT 0.0,
    geo_code TEXT DEFAULT 'VN',
    source_url TEXT,
    metadata TEXT,
    CHECK (time_provenance <> 'exact_ingestion' OR observed_at IS NOT NULL)
)"""
PRE_031_MISSION_EVIDENCE = """
CREATE TABLE mission_evidence (
    id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
    observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
    recorded_at TEXT NOT NULL,
    UNIQUE (mission_id, observation_id)
)"""
NOW = "2026-10-21T01:00:00+00:00"


def _bootstrap(path):
    async def run():
        repository = SqliteTrendRepository(str(path))
        await repository._ensure_schema()
        await repository.close()

    asyncio.run(run())


def _digest(path):
    return SqliteTrendRepository.existing_core_schema_digest(str(path))


def _make_pre_031_store(path):
    """A current store taken back to the pre-031 shape, holding one mission's evidence."""
    _bootstrap(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    for trigger in ("mission_evidence_declared_account_same_mission",
                    "mission_evidence_declared_account_same_mission_update"):
        conn.execute(f"DROP TRIGGER {trigger}")
    conn.execute("DROP TABLE mission_author_keys")
    conn.execute("DROP TABLE mission_declared_accounts")
    for table, ddl in (("observations", PRE_031_OBSERVATIONS), ("mission_evidence", PRE_031_MISSION_EVIDENCE)):
        dependents = [row[0] for row in conn.execute(
            "SELECT sql FROM sqlite_master WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL",
            (table,))]
        conn.execute(f"ALTER TABLE {table} RENAME TO {table}_now")
        conn.execute(ddl)
        columns = ", ".join(row[1] for row in conn.execute(f"PRAGMA table_info({table})"))
        conn.execute(f"INSERT INTO {table} ({columns}) SELECT {columns} FROM {table}_now")
        conn.execute(f"DROP TABLE {table}_now")
        for statement in dependents:
            conn.execute(statement)
    mission, source = str(uuid.uuid4()), str(uuid.uuid4())
    conn.execute("INSERT INTO research_missions (id, title, keywords, status, created_at) VALUES (?, ?, ?, ?, ?)",
                 (mission, "pre-031", "[]", "COMPLETED", NOW))
    conn.execute("INSERT INTO sources (id, platform, external_id) VALUES (?, 'tiktok', 'video:1')", (source,))
    for index in range(3):
        observation = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source,"
            " observed_title, metadata) VALUES (?, ?, ?, 'exact_ingestion', 'metadata_external_id', ?, ?)",
            (observation, source, NOW, f"title {index}", '{"author": "legacy.handle"}'),
        )
        conn.execute("INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at) VALUES (?, ?, ?, ?)",
                     (str(uuid.uuid4()), mission, observation, NOW))
    conn.commit()
    conn.close()
    return mission, source


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        return {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("research_missions", "sources", "observations", "mission_evidence")}
    finally:
        conn.close()


def _rows(path, query):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_a_fresh_store_has_the_031_tables_and_columns(tmp_path):
    path = tmp_path / "fresh.sqlite"
    _bootstrap(path)

    tables = {row[0] for row in _rows(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = {row[1] for row in _rows(path, "PRAGMA table_info(mission_evidence)")}
    assert {"mission_author_keys", "mission_declared_accounts"} <= tables
    assert {"author_state", "author_marker", "declared_account_id"} <= columns


def test_an_older_store_is_upgraded_in_place_with_every_row_kept(tmp_path):
    path = tmp_path / "older.sqlite"
    _make_pre_031_store(path)
    before = _counts(path)
    stored_before = _rows(path, "SELECT id, metadata FROM observations ORDER BY id")

    _bootstrap(path)

    assert _counts(path) == before
    assert _rows(path, "SELECT id, metadata FROM observations ORDER BY id") == stored_before
    assert _rows(path, "SELECT DISTINCT author_state FROM mission_evidence") == [(None,)]


def test_an_upgraded_store_has_the_same_core_schema_as_a_fresh_one(tmp_path):
    fresh, older = tmp_path / "fresh.sqlite", tmp_path / "older.sqlite"
    _bootstrap(fresh)
    _make_pre_031_store(older)
    assert _digest(older) != _digest(fresh)

    _bootstrap(older)

    assert _digest(older) == _digest(fresh)


def test_upgrading_twice_changes_nothing(tmp_path):
    path = tmp_path / "older.sqlite"
    _make_pre_031_store(path)
    _bootstrap(path)
    digest, counts = _digest(path), _counts(path)

    _bootstrap(path)

    assert (_digest(path), _counts(path)) == (digest, counts)


@pytest.fixture
def upgraded(tmp_path):
    path = tmp_path / "older.sqlite"
    mission, source = _make_pre_031_store(path)
    _bootstrap(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    yield conn, mission, source
    conn.close()


def _new_observation(conn, source, identity_source="metadata_external_id"):
    observation = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source)"
        " VALUES (?, ?, ?, 'exact_ingestion', ?)",
        (observation, source, NOW, identity_source),
    )
    return observation


def test_unverifiable_content_is_an_accepted_identity_source(upgraded):
    conn, _, source = upgraded

    _new_observation(conn, source, "unverifiable_content")


def _evidence(conn, mission, observation, state, marker=None, declared=None):
    conn.execute(
        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at, author_state,"
        " author_marker, declared_account_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), mission, observation, NOW, state, marker, declared),
    )


def test_a_known_author_needs_a_marker_and_only_a_known_one_has_one(upgraded):
    conn, mission, source = upgraded

    _evidence(conn, mission, _new_observation(conn, source), "KNOWN", "0123456789abcdef")
    with pytest.raises(sqlite3.IntegrityError):
        _evidence(conn, mission, _new_observation(conn, source), "KNOWN")
    with pytest.raises(sqlite3.IntegrityError):
        _evidence(conn, mission, _new_observation(conn, source), "UNKNOWN", "0123456789abcdef")
    with pytest.raises(sqlite3.IntegrityError):
        _evidence(conn, mission, _new_observation(conn, source), "KNOWN", "not-a-marker-xyz")


def _declare(conn, mission, handle="brand.declared"):
    declared = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO mission_declared_accounts (id, mission_id, platform, account_key, declared_name,"
        " declared_at) VALUES (?, ?, 'tiktok', ?, 'Brand', ?)",
        (declared, mission, handle, NOW),
    )
    return declared


def test_a_declaration_from_another_mission_is_refused(upgraded):
    conn, mission, source = upgraded
    other = str(uuid.uuid4())
    conn.execute("INSERT INTO research_missions (id, title, keywords, status, created_at) VALUES (?, ?, ?, ?, ?)",
                 (other, "other", "[]", "COMPLETED", NOW))
    foreign = _declare(conn, other)

    with pytest.raises(sqlite3.IntegrityError):
        _evidence(conn, mission, _new_observation(conn, source), "DECLARED", declared=foreign)


def test_withdrawing_a_declaration_clears_only_the_reference(upgraded):
    conn, mission, source = upgraded
    declared = _declare(conn, mission)
    observation = _new_observation(conn, source)
    _evidence(conn, mission, observation, "DECLARED", declared=declared)

    conn.execute("DELETE FROM mission_declared_accounts WHERE id = ?", (declared,))

    assert conn.execute(
        "SELECT author_state, declared_account_id FROM mission_evidence WHERE observation_id = ?", (observation,)
    ).fetchone() == ("DECLARED", None)


def test_a_declared_account_key_must_be_normalised(upgraded):
    conn, mission, _ = upgraded

    with pytest.raises(sqlite3.IntegrityError):
        _declare(conn, mission, "@Brand.Declared")
