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
