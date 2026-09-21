"""The interval in which the legacy corpus is not allowed to move, asked of a real server.

Two things were measured wrong before this existed. The audit's reader opened a transaction at
READ COMMITTED, so its four digests could describe a corpus that never existed at one instant:
a probe read count 0, another connection inserted, and the next read in the same transaction
returned 1. And the last measurement before the write closed its connection before the backfill
was spawned, leaving a gap in which a writer could land with nothing watching.

Neither is visible from a stubbed test. Both are properties of the server.
"""

import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from tests.integration.conftest import _drop_test_database

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import migration_reconciliation_audit as audit_module  # noqa: E402
import t020_cutover  # noqa: E402


@pytest.fixture
def legacy_tables():
    """A scratch database holding the four tables the projection reads, and nothing else."""
    admin_dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if not admin_dsn:
        pytest.skip("IGNIS_TEST_POSTGRES_DSN is required to ask a real server what it does")
    # A fresh name per run, never a fixed one. The fixed name meant the fixture opened by
    # dropping a database it had not created -- the only place in the suite that could destroy
    # something pre-existing, and a name collision away from destroying the wrong thing. A uuid
    # name cannot collide, so there is nothing to drop before creating.
    name = f"ignis_standstill_{uuid4().hex}"
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = t020_cutover.make_conninfo(
        **dict(t020_cutover.dsn_fields(admin_dsn), dbname=name)
    )
    with psycopg.connect(dsn, autocommit=True) as setup:
        for table in t020_cutover.LEGACY_TABLES:
            setup.execute(f"CREATE TABLE {table} (id bigserial primary key)")
    try:
        yield dsn
    finally:
        # Shared with conftest: a plain drop races a connection pooler, which reopens a server
        # session between the terminate and the DROP and leaves the scratch database behind.
        _drop_test_database(admin_dsn, name)


def test_the_audit_reader_reads_one_instant(legacy_tables):
    """A digest built from several statements has to describe one state of the corpus.

    At READ COMMITTED each statement saw whatever had committed by the time it ran, so a writer
    landing mid-read produced four digests of a corpus that was never simultaneously true.
    """
    reader = audit_module.PostgresReader(legacy_tables)
    try:
        assert (
            reader.connection.execute("show transaction_isolation").fetchone()[0]
            == "repeatable read"
        )
        first = reader.connection.execute("select count(*) from trend_signals").fetchone()[0]

        with psycopg.connect(legacy_tables, autocommit=True) as writer:
            writer.execute("INSERT INTO trend_signals DEFAULT VALUES")

        second = reader.connection.execute("select count(*) from trend_signals").fetchone()[0]
        assert first == second, "the reader's own transaction saw the corpus change under it"
    finally:
        reader.close()


def test_a_writer_cannot_land_while_the_guard_is_held(legacy_tables):
    """The measurement and the write have to be one interval, not two adjacent moments.

    The mutation here is attempted after the guard is open -- which is the case a stubbed
    measurement returning a different digest can never reach.
    """
    with t020_cutover.standstill_guard(legacy_tables):
        with psycopg.connect(legacy_tables, autocommit=True) as writer:
            writer.execute("SET lock_timeout = '1s'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                writer.execute("INSERT INTO trend_signals DEFAULT VALUES")


def test_the_same_write_succeeds_once_the_guard_is_gone(legacy_tables):
    """Negative control: the guard is what refuses the write, not the scratch schema."""
    with t020_cutover.standstill_guard(legacy_tables):
        pass

    with psycopg.connect(legacy_tables, autocommit=True) as writer:
        writer.execute("SET lock_timeout = '1s'")
        writer.execute("INSERT INTO trend_signals DEFAULT VALUES")
        assert writer.execute("select count(*) from trend_signals").fetchone()[0] == 1


def test_the_guard_still_lets_the_backfill_read(legacy_tables):
    """SHARE blocks writers and admits readers; the backfill reads every legacy row it migrates."""
    with t020_cutover.standstill_guard(legacy_tables):
        with psycopg.connect(legacy_tables, autocommit=True) as child:
            child.execute("SET lock_timeout = '1s'")
            assert child.execute("select count(*) from trend_signals").fetchone()[0] == 0
