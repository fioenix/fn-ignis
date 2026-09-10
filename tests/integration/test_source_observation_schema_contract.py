"""The schema contract, written before the DDL exists.

Every assertion here is one of the four decisions recorded in BACKLOG on 10/09/2026, expressed
as something a database either does or does not do. All of it is RED until the migration lands,
which is the point: the DDL is finished when this file passes on both backends, not when it
applies without error.

The contract is deliberately about behaviour rather than column lists. A migration can create
every table named here and still lose a mission's evidence, so what gets asserted is what the
tables must be unable to do -- accept a second copy of one external object, drop the second
observation a mission made of one source, or let polling frequency inflate a score.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc)


def _postgres_dsns():
    base_dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if not base_dsn:
        pytest.skip("IGNIS_TEST_POSTGRES_DSN is required for the real Postgres schema contract")
    parts = conninfo_to_dict(base_dsn)
    database_name = f"ignis_schema_{uuid4().hex}"
    return make_conninfo(**parts), make_conninfo(**{**parts, "dbname": database_name}), database_name


# Applied in this order, listed explicitly rather than globbed. Globbing sql/*.sql terminates a
# plain Postgres backend on 006_supabase_security_hardening.sql, which targets Supabase's own
# roles and linter rules. A new migration is added here deliberately, so that whoever writes it
# also decides whether it belongs in a portable schema.
SCHEMA_MIGRATIONS = (
    "001_initial_schema.sql",
    "008_deduplicate_signal_metrics.sql",
    "015_split_published_at.sql",
    "016_source_observation_model.sql",
)


@pytest_asyncio.fixture
async def postgres_schema():
    """A throwaway database carrying the portable migrations, in order."""
    from pathlib import Path

    admin_dsn, test_dsn, database_name = _postgres_dsns()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        repo_root = Path(__file__).resolve().parents[2]
        with psycopg.connect(test_dsn, autocommit=True) as conn:
            for migration in SCHEMA_MIGRATIONS:
                conn.execute((repo_root / "sql" / migration).read_text(encoding="utf-8"))
        yield test_dsn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (database_name,),
            )
            conn.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def table_exists(conn, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (name,)
        ).fetchone()
    )


def columns_of(conn, table: str) -> set:
    """Column names, having first proved the table is there.

    Without the existence check, "column X is absent from table Y" passes on a database where Y
    does not exist at all -- a test that is green for the wrong reason, which is worse than red.
    """
    assert table_exists(conn, table), f"{table} is missing"
    return {
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
        )
    }


def unique_columns(conn, table: str):
    """Every UNIQUE constraint on a table, as a set of frozensets of column names."""
    rows = conn.execute(
        """
        SELECT c.conname, array_agg(a.attname ORDER BY a.attname)
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = %s::regclass AND c.contype IN ('u', 'p')
        GROUP BY c.conname
        """,
        (table,),
    ).fetchall()
    return {frozenset(cols) for _name, cols in rows}


# --- decision: three entities exist and are separate ------------------------------------------


async def test_the_three_entities_exist(postgres_schema):
    with psycopg.connect(postgres_schema) as conn:
        for table in ("sources", "observations", "mission_evidence"):
            assert table_exists(conn, table), f"{table} is missing"


async def test_a_source_is_unique_on_platform_and_external_id(postgres_schema):
    """Database-enforced, not enforced by a SELECT-then-INSERT that two writers can race."""
    with psycopg.connect(postgres_schema) as conn:
        assert frozenset({"platform", "external_id"}) in unique_columns(conn, "sources")


async def test_a_second_copy_of_one_external_object_is_refused(postgres_schema):
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'vid-1')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'vid-1')"
            )


async def test_a_title_is_observed_not_part_of_source_identity(postgres_schema):
    """Ten URLs in the corpus reported two titles, so a title cannot live on the source."""
    with psycopg.connect(postgres_schema) as conn:
        source_columns = columns_of(conn, "sources")
        assert "raw_title" not in source_columns and "title" not in source_columns
        assert "observed_title" in columns_of(conn, "observations")


async def test_cluster_membership_is_not_on_the_source(postgres_schema):
    """172 identities sit under more than one cluster; a column here would force a choice."""
    with psycopg.connect(postgres_schema) as conn:
        assert "cluster_id" not in columns_of(conn, "sources")


# --- decision: the mission ledger is lossless -------------------------------------------------


async def test_evidence_is_unique_on_mission_and_observation_not_mission_and_source(
    postgres_schema,
):
    with psycopg.connect(postgres_schema) as conn:
        constraints = unique_columns(conn, "mission_evidence")
        assert frozenset({"mission_id", "observation_id"}) in constraints
        assert frozenset({"mission_id", "source_id"}) not in constraints, (
            "UNIQUE(mission_id, source_id) would silently drop the second observation a mission"
            " made of one source; the baseline found 2 missions in exactly that state"
        )


async def test_one_mission_keeps_two_observations_of_one_source(postgres_schema):
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('tiktok', '777') RETURNING id"
        ).fetchone()[0]
        mission_id = conn.execute(
            "INSERT INTO research_missions (title, keywords, platforms, geo_code, timeframe,"
            " status) VALUES ('m', '{}', '{}', 'VN', '7d', 'COMPLETED') RETURNING id"
        ).fetchone()[0]
        observation_ids = [
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value, time_provenance)"
                " VALUES (%s, %s, %s, 'exact_ingestion') RETURNING id",
                (source_id, NOW - timedelta(days=offset), metric),
            ).fetchone()[0]
            for offset, metric in ((2, 100.0), (1, 200.0))
        ]
        for observation_id in observation_ids:
            conn.execute(
                "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)",
                (mission_id, observation_id),
            )

        kept = conn.execute(
            "SELECT count(*) FROM mission_evidence WHERE mission_id = %s", (mission_id,)
        ).fetchone()[0]
        assert kept == 2, "the mission ledger must be lossless"


async def test_the_same_evidence_row_cannot_be_recorded_twice(postgres_schema):
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('threads', 'p1') RETURNING id"
        ).fetchone()[0]
        mission_id = conn.execute(
            "INSERT INTO research_missions (title, keywords, platforms, geo_code, timeframe,"
            " status) VALUES ('m', '{}', '{}', 'VN', '7d', 'COMPLETED') RETURNING id"
        ).fetchone()[0]
        observation_id = conn.execute(
            "INSERT INTO observations (source_id, observed_at, metric_value, time_provenance)"
            " VALUES (%s, %s, 1.0, 'exact_ingestion') RETURNING id",
            (source_id, NOW),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)",
            (mission_id, observation_id),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)",
                (mission_id, observation_id),
            )


async def test_an_observation_belongs_to_exactly_one_source(postgres_schema):
    with psycopg.connect(postgres_schema) as conn:
        assert "source_id" in columns_of(conn, "observations")
        nullable = conn.execute(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_name = 'observations' AND column_name = 'source_id'"
        ).fetchone()
        assert nullable and nullable[0] == "NO"
        foreign_keys = {
            r[0]
            for r in conn.execute(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = 'observations'::regclass AND contype = 'f'"
            )
        }
        assert foreign_keys, "observations.source_id needs a foreign key, not a convention"


# --- decision: historical timestamps are labelled, never invented -----------------------------


async def test_time_provenance_is_a_required_three_valued_column(postgres_schema):
    with psycopg.connect(postgres_schema) as conn:
        assert "time_provenance" in columns_of(conn, "observations")
        row = conn.execute(
            "SELECT is_nullable FROM information_schema.columns"
            " WHERE table_name = 'observations' AND column_name = 'time_provenance'"
        ).fetchone()
        assert row and row[0] == "NO"

    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'vid-tp') RETURNING id"
        ).fetchone()[0]
        for provenance in ("exact_ingestion", "legacy_publish_only", "unknown"):
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value, time_provenance)"
                " VALUES (%s, %s, 1.0, %s)",
                (source_id, NOW, provenance),
            )
        with pytest.raises((psycopg.errors.CheckViolation, psycopg.errors.InvalidTextRepresentation)):
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value, time_provenance)"
                " VALUES (%s, %s, 1.0, 'approximately_exact')",
                (source_id, NOW),
            )


async def test_a_legacy_publish_only_observation_has_no_invented_ingestion_time(postgres_schema):
    """The true collection time was never recorded, so observed_at stays NULL rather than lying."""
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'vid-legacy')"
            " RETURNING id"
        ).fetchone()[0]
        observation_id = conn.execute(
            "INSERT INTO observations (source_id, observed_at, published_at, metric_value,"
            " time_provenance) VALUES (%s, NULL, %s, 1.0, 'legacy_publish_only') RETURNING id",
            (source_id, NOW - timedelta(days=30)),
        ).fetchone()[0]
        row = conn.execute(
            "SELECT observed_at, published_at FROM observations WHERE id = %s", (observation_id,)
        ).fetchone()
        assert row[0] is None and row[1] is not None


async def test_an_exact_ingestion_observation_must_carry_observed_at(postgres_schema):
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('tiktok', 'vid-exact')"
            " RETURNING id"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value, time_provenance)"
                " VALUES (%s, NULL, 1.0, 'exact_ingestion')",
                (source_id,),
            )


# --- decision: multiplicity is data, so the schema must not forbid it -------------------------


async def test_two_observations_may_share_source_time_and_metric(postgres_schema):
    """The surrogate observation id is what keeps two collection events apart.

    A UNIQUE over (source_id, observed_at, metric_value) would look tidy and would delete real
    data: in the corpus, rows matching on those three carry three distinct growth_velocity
    values. The audit was corrected for asserting the opposite, and the schema must not encode
    the same mistake.
    """
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'vid-twin')"
            " RETURNING id"
        ).fetchone()[0]
        for velocity in (1.0, 2.0):
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value,"
                " growth_velocity, time_provenance)"
                " VALUES (%s, %s, 100.0, %s, 'exact_ingestion')",
                (source_id, NOW, velocity),
            )
        # And again with the velocity identical too: still two sightings.
        for _ in range(2):
            conn.execute(
                "INSERT INTO observations (source_id, observed_at, metric_value,"
                " growth_velocity, time_provenance)"
                " VALUES (%s, %s, 100.0, 5.0, 'exact_ingestion')",
                (source_id, NOW),
            )
        kept = conn.execute(
            "SELECT count(*) FROM observations WHERE source_id = %s", (source_id,)
        ).fetchone()[0]
        assert kept == 4


async def test_no_unique_constraint_forbids_a_repeated_observation_payload(postgres_schema):
    with psycopg.connect(postgres_schema) as conn:
        forbidden = (
            frozenset({"source_id", "observed_at", "metric_value"}),
            frozenset({"source_id", "observed_at"}),
            frozenset({"source_id", "metric_value"}),
        )
        constraints = unique_columns(conn, "observations")
        overlap = sorted(set(map(tuple, map(sorted, constraints & set(forbidden)))))
        assert not overlap, f"these constraints would delete real collection events: {overlap}"


async def test_an_observation_preserves_every_field_the_audit_conserves(postgres_schema):
    """The schema has to hold what the reconciliation digest promises to carry across."""
    with psycopg.connect(postgres_schema) as conn:
        columns = columns_of(conn, "observations")
        for column in (
            "source_id",
            "observed_at",
            "published_at",
            "observed_title",
            "metric_value",
            "growth_velocity",
            "geo_code",
            "source_url",
            "metadata",
            "time_provenance",
        ):
            assert column in columns, f"observations.{column} is missing"


# --- the same contract on SQLite ---------------------------------------------------------------
#
# SQLite does not read sql/, so its schema is restated in _ensure_schema and could drift from the
# migration without anything failing. These are the same behavioural assertions, not a column
# inventory: a backend that agrees on names and disagrees on constraints is the drift worth
# catching.


@pytest_asyncio.fixture
async def sqlite_schema(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(str(tmp_path / "schema_contract.sqlite"))
    await repository._ensure_schema()
    try:
        yield repository._db_path
    finally:
        await repository.close()


def _sqlite(path):
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _sqlite_columns(conn, table: str) -> set:
    rows = list(conn.execute(f"PRAGMA table_info({table})"))
    assert rows, f"{table} is missing"
    return {row[1] for row in rows}


async def test_sqlite_holds_the_three_entities_with_the_same_shape(sqlite_schema):
    import sqlite3

    with _sqlite(sqlite_schema) as conn:
        source_columns = _sqlite_columns(conn, "sources")
        assert "raw_title" not in source_columns and "title" not in source_columns
        assert "cluster_id" not in source_columns
        observation_columns = _sqlite_columns(conn, "observations")
        for column in (
            "source_id",
            "observed_at",
            "published_at",
            "observed_title",
            "metric_value",
            "growth_velocity",
            "geo_code",
            "source_url",
            "metadata",
            "time_provenance",
        ):
            assert column in observation_columns, f"observations.{column} is missing"
        _sqlite_columns(conn, "mission_evidence")

        conn.execute(
            "INSERT INTO sources (id, platform, external_id)"
            " VALUES ('s1', 'youtube', 'video:vid-1')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO sources (id, platform, external_id)"
                " VALUES ('s2', 'youtube', 'video:vid-1')"
            )


async def test_sqlite_labels_the_clock_and_refuses_an_invented_one(sqlite_schema):
    import sqlite3

    with _sqlite(sqlite_schema) as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id)"
            " VALUES ('s1', 'youtube', 'video:vid-tp')"
        )
        for index, provenance in enumerate(
            ("exact_ingestion", "legacy_publish_only", "unknown")
        ):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " time_provenance) VALUES (?, 's1', '2026-09-10T12:00:00+00:00', 1.0, ?)",
                (f"o{index}", provenance),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " time_provenance) VALUES ('o-bad', 's1', '2026-09-10T12:00:00+00:00', 1.0,"
                " 'approximately_exact')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " time_provenance) VALUES ('o-noclock', 's1', NULL, 1.0, 'exact_ingestion')"
            )
        # A legacy observation keeps a NULL observed_at rather than an invented one.
        conn.execute(
            "INSERT INTO observations (id, source_id, observed_at, published_at, metric_value,"
            " time_provenance) VALUES ('o-legacy', 's1', NULL, '2026-08-10T00:00:00+00:00', 1.0,"
            " 'legacy_publish_only')"
        )


async def test_sqlite_keeps_two_observations_of_one_source_in_one_mission(sqlite_schema):
    import sqlite3

    with _sqlite(sqlite_schema) as conn:
        conn.execute(
            "INSERT INTO sources (id, platform, external_id)"
            " VALUES ('s1', 'tiktok', 'video:777')"
        )
        conn.execute(
            "INSERT INTO research_missions (id, title, keywords, created_at)"
            " VALUES ('m1', 'm', '[]', '2026-09-10')"
        )
        for index, metric in enumerate((100.0, 200.0)):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " time_provenance) VALUES (?, 's1', ?, ?, 'exact_ingestion')",
                (f"o{index}", f"2026-09-0{index + 1}T00:00:00+00:00", metric),
            )
            conn.execute(
                "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                " VALUES (?, 'm1', ?, '2026-09-10')",
                (f"e{index}", f"o{index}"),
            )
        kept = conn.execute(
            "SELECT count(*) FROM mission_evidence WHERE mission_id = 'm1'"
        ).fetchone()[0]
        assert kept == 2, "the mission ledger must be lossless on SQLite too"

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                " VALUES ('e-dup', 'm1', 'o0', '2026-09-10')"
            )

        # Two collection events identical on every field are still two events.
        for index in range(2):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " growth_velocity, time_provenance) VALUES (?, 's1',"
                " '2026-09-10T12:00:00+00:00', 100.0, 5.0, 'exact_ingestion')",
                (f"twin{index}",),
            )
        assert (
            conn.execute("SELECT count(*) FROM observations WHERE source_id = 's1'").fetchone()[0]
            == 4
        )


async def test_a_source_carries_no_lifecycle_summary_of_its_observations(postgres_schema):
    """When a source was seen lives in observations; a pair of columns here is a second copy.

    The backfill could not fill them honestly either: 17,118 of the 18,597 observations have no
    known ingestion time, so a DEFAULT NOW() would have invented a lifecycle rather than recorded
    one.
    """
    with psycopg.connect(postgres_schema) as conn:
        columns = columns_of(conn, "sources")
        assert not columns & {"first_seen_at", "last_seen_at", "observation_count"}


async def test_an_observation_loses_its_cluster_rather_than_dangling(postgres_schema):
    with psycopg.connect(postgres_schema, autocommit=True) as conn:
        source_id = conn.execute(
            "INSERT INTO sources (platform, external_id) VALUES ('youtube', 'video:c1')"
            " RETURNING id"
        ).fetchone()[0]
        cluster_id = conn.execute(
            "INSERT INTO topic_clusters (canonical_name) VALUES ('c') RETURNING id"
        ).fetchone()[0]
        observation_id = conn.execute(
            "INSERT INTO observations (source_id, cluster_id, observed_at, metric_value,"
            " time_provenance) VALUES (%s, %s, %s, 1.0, 'exact_ingestion') RETURNING id",
            (source_id, cluster_id, NOW),
        ).fetchone()[0]
        conn.execute("DELETE FROM topic_clusters WHERE id = %s", (cluster_id,))
        row = conn.execute(
            "SELECT cluster_id FROM observations WHERE id = %s", (observation_id,)
        ).fetchone()
        assert row[0] is None, "the observation must survive its cluster, without a dangling id"


async def test_sqlite_enforces_the_same_cluster_reference(sqlite_schema):
    """A REFERENCES clause SQLite never enforces is decoration, so the behaviour is asserted.

    Both halves: the declaration is there, and the connection the repository hands out actually
    has foreign keys on -- SQLite defaults them off per connection.
    """
    import sqlite3

    with _sqlite(sqlite_schema) as conn:
        referenced = {row[2] for row in conn.execute("PRAGMA foreign_key_list(observations)")}
        assert {"sources", "topic_clusters"} <= referenced

        conn.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES ('s1', 'youtube', 'video:c1')"
        )
        conn.execute(
            "INSERT INTO topic_clusters (id, canonical_name, first_seen_at, last_updated_at)"
            " VALUES ('c1', 'c', '2026-09-10', '2026-09-10')"
        )
        conn.execute(
            "INSERT INTO observations (id, source_id, cluster_id, observed_at, metric_value,"
            " time_provenance) VALUES ('o1', 's1', 'c1', '2026-09-10T12:00:00+00:00', 1.0,"
            " 'exact_ingestion')"
        )
        conn.execute("DELETE FROM topic_clusters WHERE id = 'c1'")
        assert (
            conn.execute("SELECT cluster_id FROM observations WHERE id = 'o1'").fetchone()[0]
            is None
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, metric_value,"
                " time_provenance) VALUES ('o-dangling', 'nope',"
                " '2026-09-10T12:00:00+00:00', 1.0, 'exact_ingestion')"
            )


async def test_the_repository_connection_has_foreign_keys_on(sqlite_schema):
    """The pragma is per connection, so it is asserted on the one the repository returns."""
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repository = SqliteTrendRepository(sqlite_schema)
    try:
        conn = repository._get_connection()
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        await repository.close()
