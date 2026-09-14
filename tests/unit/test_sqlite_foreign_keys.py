"""Foreign keys are on for every SQLite connection, not only the file-backed ones.

SQLite turns foreign keys off per connection, so a pragma applied on one path and not the other
is not a smaller guarantee -- it is no guarantee at all on the path that skipped it. The
in-memory connection is built once in the constructor and handed back directly, which is exactly
the path that used to return before the pragma ran. Everything that connects to :memory: --
bootstrap, diagnostics, most of the suite -- was writing without referential integrity, and a
contract that only tested a file was green for the wrong reason.
"""

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("db_path", (":memory:", "file"))
async def test_foreign_keys_are_enforced_on_every_connection(db_path, tmp_path):
    path = ":memory:" if db_path == ":memory:" else str(tmp_path / "fk.sqlite")
    repository = SqliteTrendRepository(path)
    try:
        await repository._ensure_schema()
        conn = repository._get_connection()

        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        with pytest.raises(Exception) as failure:
            conn.execute(
                "INSERT INTO observations (id, source_id, observed_at, time_provenance,"
                " identity_source, observed_title, metric_value, geo_code)"
                " VALUES ('11111111-1111-1111-1111-111111111111',"
                " '22222222-2222-2222-2222-222222222222', '2026-09-13T00:00:00+00:00',"
                " 'exact_ingestion', 'metadata_external_id', 'dangling', 1.0, 'VN')"
            )
        assert "FOREIGN KEY" in str(failure.value).upper()
    finally:
        await repository.close()
