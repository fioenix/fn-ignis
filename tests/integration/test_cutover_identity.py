"""What the cutover orchestrator must be able to say about the database in front of it.

A resumed run is refused unless it reaches the database the earlier run measured. That gate is
only as good as the value it compares, and the first value chosen was the shape of the catalog:
the database name, its OID, and an md5 over every database in the cluster. Two independently
initialised `timescale/timescaledb-ha:pg16` clusters both answered

    postgres|5|ed7a80635ab66418335140c1261b7a11

because a default cluster holds `postgres` at OID 5 beside the two templates. The gate accepted a
journal from one deployment while connected to the other.

These run against the real server, because the question is what Postgres answers, not what the
orchestrator believes it answers.
"""

import os
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import t020_cutover  # noqa: E402


@pytest.fixture
def server():
    dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("IGNIS_TEST_POSTGRES_DSN is required to ask a real server what it answers")
    with psycopg.connect(dsn, autocommit=True) as connection:
        yield dsn, connection


def test_the_identity_probe_reports_the_cluster_identifier(server):
    """initdb writes system_identifier once, from the clock and a random value.

    It is the only value measured to differ between two fresh clusters, and it is readable
    without any grant: EXECUTE on pg_control_system() is held by PUBLIC.
    """
    _, connection = server
    # Written out here rather than taken from the module, or the assertion would only say that
    # the script's query equals itself and any other value could be substituted for it.
    expected = str(
        connection.execute("select system_identifier::text from pg_control_system()").fetchone()[0]
    )
    assert expected, "the server itself reports no cluster identifier"

    measured = str(connection.execute(t020_cutover.SYSTEM_IDENTIFIER_SQL).fetchone()[0])

    assert measured == expected, (
        "the value this gate compares is not the one initdb wrote for this cluster"
    )


def test_the_rest_of_the_identity_is_the_default_shape_every_cluster_has(server):
    """Why the database name and OID cannot carry this gate on their own.

    On a cluster nobody has added a database to, they are the same two values everywhere. The
    test states that directly: it asserts the very sameness that made the first version of this
    gate accept a journal from another deployment.
    """
    _, connection = server
    row = str(connection.execute(t020_cutover.IDENTITY_SQL).fetchone()[0])
    fields = t020_cutover.identity_fields(row, "")

    assert fields["database"] == str(
        connection.execute("select current_database()").fetchone()[0]
    )
    assert fields["database_oid"] == str(
        connection.execute(
            "select oid from pg_database where datname = current_database()"
        ).fetchone()[0]
    )
    default_databases = [
        name
        for (name,) in connection.execute("select datname from pg_database order by oid")
        if name in ("template0", "template1", "postgres")
    ]
    assert len(default_databases) == 3, (
        "these three, at these OIDs, are what every default cluster holds -- which is why"
        " agreeing on them identifies nothing"
    )
