"""The rehearsal is evidence, so the thing producing it has to be unable to lie or to overreach.

Two properties matter more than any single check the rehearsal reports. It must not be able to
write anywhere an operator names, because a rehearsal that can reach a configured database is a
migration tool wearing a rehearsal's label. And it must fail when the schema is wrong, because a
run that passes either way measures nothing.
"""

import json
import os
import sqlite3

import pytest

from scripts import t037_schema_rehearsal as rehearsal


def _sqlite_target(tmp_path):
    """A database with legacy rows and no workspace schema: a target that predates 017."""
    path = tmp_path / "existing.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trend_signals (id INTEGER PRIMARY KEY, platform TEXT,"
                     " source_url TEXT, raw_title TEXT, metadata TEXT, captured_at TEXT,"
                     " metric_value REAL, mission_id TEXT, cluster_id TEXT,"
                     " growth_velocity REAL, geo_code TEXT, published_at TEXT)")
        conn.execute("CREATE TABLE research_missions (id TEXT PRIMARY KEY, title TEXT)")
        conn.execute("CREATE TABLE topic_clusters (id TEXT PRIMARY KEY)")
    return path


# --- The safety property ----------------------------------------------------

def test_the_default_mode_writes_nothing_to_the_target(tmp_path):
    """inspect is the mode that may meet a real database, so it must only ever read."""
    path = _sqlite_target(tmp_path)
    before = (path.stat().st_size, sorted(_table_names(path)))

    record = rehearsal.inspect(f"sqlite:///{path}")

    assert (path.stat().st_size, sorted(_table_names(path))) == before
    assert record.schema["migration_applied"] is False
    assert record.schema["tables_present"] == []
    assert record.disposition["schema_applied_to_this_target"] is False
    assert not record.failed


def test_write_mode_refuses_a_target_an_operator_names(tmp_path):
    """There is no argument that points the writing mode at a configured database."""
    path = _sqlite_target(tmp_path)
    assert rehearsal.main(
        ["--mode", "rehearse", "--confirm-scratch", "--dsn", f"sqlite:///{path}"]
    ) == 2
    # And nothing happened to it.
    assert rehearsal.TABLES_INTRODUCED[0] not in _table_names(path)


def test_write_mode_requires_an_explicit_opt_in():
    assert rehearsal.main(["--mode", "rehearse"]) == 2


def test_a_database_that_is_not_scratch_is_not_a_drop_target():
    """The name is matched in full: a prefix test would accept ignis_rehearsal_production."""
    assert rehearsal.is_scratch_name("ignis_rehearsal_" + "0" * 32)
    assert not rehearsal.is_scratch_name("ignis_rehearsal_production")
    assert not rehearsal.is_scratch_name("postgres")
    assert not rehearsal.is_scratch_name("")


# --- The evidence -----------------------------------------------------------

@pytest.fixture(scope="module")
def sqlite_record():
    return rehearsal.run_rehearsal("sqlite")


def test_the_sqlite_rehearsal_passes_every_check(sqlite_record):
    assert [c.name for c in sqlite_record.failed] == []
    assert sqlite_record.payload()["result"] == "PASSED"


def test_the_record_carries_counts_and_digests_for_every_canonical_set(sqlite_record):
    corpus = sqlite_record.corpus
    for moment in ("before", "after"):
        assert set(corpus[moment]["digests"]) == set(rehearsal.CANONICAL_SETS)
        assert set(corpus[moment]["member_counts"]) == set(rehearsal.CANONICAL_SETS)
        for name in rehearsal.CANONICAL_SETS:
            assert corpus[moment]["member_counts"][name] > 0, (
                f"{name} is empty, so 'unchanged' would prove nothing"
            )
            assert len(corpus[moment]["digests"][name]) == 64
    assert corpus["drift"] == []
    counts = corpus["untouched_table_counts"]
    assert counts["before"] == counts["after"]
    assert all(counts["before"][table] > 0 for table in rehearsal.UNTOUCHED_TABLES)


def test_the_record_names_the_migration_by_its_own_digest(sqlite_record):
    under = [m for m in sqlite_record.migrations if m["under_rehearsal"]]
    assert [m["file"] for m in under] == [rehearsal.MIGRATION_UNDER_REHEARSAL]
    assert len(under[0]["sha256"]) == 64
    on_disk = rehearsal.sha256_of(rehearsal.SQL_DIR / rehearsal.MIGRATION_UNDER_REHEARSAL)
    assert under[0]["sha256"] == on_disk


def test_the_record_exposes_no_dsn(sqlite_record):
    serialized = json.dumps(sqlite_record.payload())
    assert "://" not in serialized
    assert "password" not in serialized.lower()
    configured = os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip()
    if configured:
        assert configured not in serialized


def test_the_record_states_that_nothing_production_was_migrated(sqlite_record):
    assert sqlite_record.disposition["rehearsal_only"] is True
    assert sqlite_record.disposition["production_apply_performed"] is False
    assert sqlite_record.target["scratch"] is True


def test_the_rehearsal_applies_the_repository_schema_contract_order():
    """One order, or the rehearsal is measuring a schema the integration suite never builds."""
    import re
    from pathlib import Path

    conftest = (Path(__file__).resolve().parents[1] / "integration" / "conftest.py").read_text()
    block = re.search(r"SCHEMA_MIGRATIONS = \((.*?)\)", conftest, re.DOTALL).group(1)
    contract = tuple(re.findall(r'"([^"]+\.sql)"', block))
    assert rehearsal.SCHEMA_MIGRATIONS == contract
    assert rehearsal.SCHEMA_MIGRATIONS[-1] == rehearsal.MIGRATION_UNDER_REHEARSAL


def test_the_rehearsal_is_deterministic_and_leaves_nothing_behind(sqlite_record):
    """Two runs of one migration must hash one corpus, and neither may leave a database."""
    again = rehearsal.run_rehearsal("sqlite")
    assert again.corpus["after"]["digests"] == sqlite_record.corpus["after"]["digests"]
    assert [c.name for c in again.checks] == [c.name for c in sqlite_record.checks]
    assert [c.name for c in again.failed] == []
    for record in (sqlite_record, again):
        assert record.cleanup["scratch_root_removed"] is True
        assert record.cleanup["scratch_databases_remaining"] == []


def test_reapplying_the_migration_adds_no_object(sqlite_record):
    by_name = {c.name: c for c in sqlite_record.checks}
    assert by_name["017.reapplying_creates_nothing_new"].passed


# --- The rehearsal has to be able to fail -----------------------------------

def test_a_corpus_that_moved_is_reported_as_drift():
    before = {"digests": {n: "a" * 64 for n in rehearsal.CANONICAL_SETS},
              "member_counts": {n: 3 for n in rehearsal.CANONICAL_SETS}}
    after = json.loads(json.dumps(before))
    after["digests"]["observations"] = "b" * 64
    after["member_counts"]["sources"] = 4
    drift = rehearsal.corpus_drift(before, after)
    assert any("sources: 3 members became 4" in d for d in drift)
    assert any("observations: 3 members both times, different digest" in d for d in drift)


def test_a_missing_invariant_fails_the_run(monkeypatch):
    """An expectation the database does not satisfy has to come back as a failed run, not a log."""
    monkeypatch.setitem(
        rehearsal.FOREIGN_KEYS,
        ("mission_writer_claims", "run_id"),
        ("research_workspaces", "CASCADE"),
    )
    record = rehearsal.run_rehearsal("sqlite")
    failed = [c.name for c in record.failed]
    assert "017.foreign_keys_and_on_delete" in failed
    assert record.payload()["result"] == "FAILED"


def test_a_corpus_that_changed_under_the_migration_fails_the_run(monkeypatch):
    calls = {"n": 0}
    real = rehearsal.legacy_corpus

    def drifting(*args, **kwargs):
        calls["n"] += 1
        measured = real(*args, **kwargs)
        if calls["n"] > 1:
            measured["member_counts"]["sources"] += 1
        return measured

    monkeypatch.setattr(rehearsal, "legacy_corpus", drifting)
    record = rehearsal.run_rehearsal("sqlite")
    assert "corpus.unchanged_by_017" in [c.name for c in record.failed]


# --- PostgreSQL -------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("IGNIS_TEST_POSTGRES_DSN", "").strip(),
    reason="IGNIS_TEST_POSTGRES_DSN is required to rehearse sql/017 as a file on PostgreSQL",
)
def test_the_postgres_rehearsal_executes_the_migration_and_drops_its_scratch_database():
    record = rehearsal.run_rehearsal("postgres")
    assert [c.name for c in record.failed] == []
    assert record.disposition["migration_file_executed"] is True
    assert rehearsal.is_scratch_name(record.target["database"])
    assert record.cleanup["scratch_databases_remaining"] == []
    assert "://" not in json.dumps(record.payload())


def _table_names(path):
    with sqlite3.connect(path) as conn:
        return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
