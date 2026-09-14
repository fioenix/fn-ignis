"""The verifier has to fail on a database that has not been backfilled.

The reconciliation audit cannot do this job: it reads trend_signals and signal_metrics, which
the migration leaves untouched, so it reports BALANCED whatever the new tables contain --
including nothing at all. These tests pin the difference.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.post_migration_verification import main, open_stored_reader, verify

NEW_MODEL_SCHEMA = """
CREATE TABLE sources (
    id TEXT PRIMARY KEY, platform TEXT NOT NULL, external_id TEXT NOT NULL,
    UNIQUE (platform, external_id)
);
CREATE TABLE observations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES sources(id),
    cluster_id TEXT, observed_at TEXT, published_at TEXT,
    time_provenance TEXT NOT NULL, identity_source TEXT NOT NULL,
    observed_title TEXT, metric_value REAL, growth_velocity REAL,
    geo_code TEXT, source_url TEXT, metadata TEXT
);
CREATE TABLE mission_evidence (
    id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, observation_id TEXT NOT NULL,
    recorded_at TEXT
);
"""

BASELINE = {
    "schema_version": 7,
    "digests": {
        "sources": "a" * 64,
        "observations": "b" * 64,
        "mission_associations": "c" * 64,
        "cluster_memberships": "d" * 64,
        "member_counts": {
            "sources": 1924,
            "observations": 18597,
            "mission_associations": 1301,
            "cluster_memberships": 15754,
        },
    },
    "observations": {
        "time_provenance_buckets": {
            "exact_ingestion": 1479,
            "legacy_publish_only": 17118,
            "unknown": 0,
        }
    },
}


def _database(tmp_path, rows=()) -> str:
    path = tmp_path / "migrated.sqlite"
    with sqlite3.connect(path) as conn:
        conn.executescript(NEW_MODEL_SCHEMA)
        for statement, params in rows:
            conn.execute(statement, params)
    return str(path)


def _verify(path) -> dict:
    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        return verify(reader, BASELINE)
    finally:
        reader.close()


def test_an_unmigrated_database_does_not_verify(tmp_path):
    """The tables exist and are empty, which is exactly when the audit would say BALANCED."""
    report = _verify(_database(tmp_path))

    assert report["verified"] is False
    assert all(not c["matches"] for c in report["comparisons"])
    assert [c["actual_members"] for c in report["comparisons"]] == [0, 0, 0, 0]


def test_every_set_is_compared_on_both_digest_and_count(tmp_path):
    report = _verify(_database(tmp_path))

    assert [c["set"] for c in report["comparisons"]] == [
        "sources",
        "observations",
        "mission_associations",
        "cluster_memberships",
    ]
    for comparison in report["comparisons"]:
        assert comparison["expected_digest"] and comparison["actual_digest"]
        assert comparison["expected_members"] > 0


def test_the_verifier_serializes_what_was_stored_rather_than_deriving_it(tmp_path):
    """A migration that wrote the wrong provenance must not be repaired on the way out.

    The row below is a YouTube observation whose stored provenance says exact_ingestion while
    its observed_at equals its published_at -- the shape the legacy derivation would call
    legacy_publish_only. The verifier has to report what is there.
    """
    path = _database(
        tmp_path,
        rows=[
            (
                "INSERT INTO sources (id, platform, external_id)"
                " VALUES ('s1', 'youtube', 'video:dQw4w9WgXcQ')",
                (),
            ),
            (
                "INSERT INTO observations (id, source_id, observed_at, published_at,"
                " time_provenance, identity_source, observed_title, metric_value,"
                " growth_velocity, geo_code, source_url, metadata)"
                " VALUES ('o1', 's1', '2026-07-01T08:30:00+00:00', '2026-07-01T08:30:00+00:00',"
                " 'exact_ingestion', 'metadata_external_id', 'A video', 1.0, 0.0, 'VN',"
                " 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', '{}')",
                (),
            ),
        ],
    )

    report = _verify(path)

    assert report["time_provenance"]["actual"] == {"exact_ingestion": 1}
    assert report["time_provenance"]["matches"] is False


def test_evidence_pointing_at_no_observation_is_counted_not_ignored(tmp_path):
    path = _database(
        tmp_path,
        rows=[
            (
                "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                " VALUES ('e1', 'm1', 'missing', '2026-09-11')",
                (),
            )
        ],
    )

    report = _verify(path)

    assert report["dangling_evidence"] == 1
    assert report["verified"] is False


def test_the_exit_code_says_mismatch(tmp_path, capsys):
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(BASELINE), encoding="utf-8")
    path = _database(tmp_path)

    code = main(["--dsn", f"sqlite:///{path}", "--baseline", str(baseline_path)])

    assert code == 1
    assert "MISMATCH" in capsys.readouterr().out


def test_the_verifier_reads_the_new_tables_not_the_legacy_ones(tmp_path):
    """A database holding only the legacy tables cannot be verified at all."""
    path = tmp_path / "legacy_only.sqlite"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE trend_signals (id TEXT PRIMARY KEY)")

    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        with pytest.raises(sqlite3.OperationalError):
            list(reader.sources())
    finally:
        reader.close()


def test_the_baseline_must_be_named_and_is_never_defaulted(tmp_path):
    """A baseline describes one snapshot, so using one implicitly compares two databases.

    The tracked file is this repository's corpus on 10/09/2026. Another self-hosted install
    running the verifier without saying which baseline it means would be checking its own
    database against those numbers.
    """
    import pytest as _pytest

    from scripts.post_migration_verification import REFERENCE_BASELINE

    path = _database(tmp_path)
    with _pytest.raises(SystemExit):
        main(["--dsn", f"sqlite:///{path}"])

    assert REFERENCE_BASELINE.exists(), "the reference baseline is still tracked"
    baseline = json.loads(Path(REFERENCE_BASELINE).read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 7
    assert baseline["digests"]["member_counts"] == {
        "sources": 1924,
        "observations": 18597,
        "mission_associations": 1301,
        "cluster_memberships": 15754,
    }


# --- rows that must not disappear between the table and the comparison -------------------------


def _matching_baseline(path) -> dict:
    """A baseline that the database at `path` satisfies exactly.

    Built from the database itself, so the tests below start from a genuinely green run. A
    "still green" assertion means nothing unless something was green to begin with.
    """
    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        observations = list(reader.observations())
        from scripts.post_migration_verification import digest_of

        sources = list(reader.sources())
        members = [o.member for o in observations]
        clusters = [f"{o.cluster_id}\x1f{o.member}" for o in observations if o.cluster_id]
        member_of = {o.observation_id: o.member for o in observations}
        evidence = [
            f"{mission_id}\x1f{member_of[observation_id]}"
            for mission_id, observation_id in reader.evidence()
            if observation_id in member_of
        ]
    finally:
        reader.close()

    provenance: dict = {}
    for observation in observations:
        provenance[observation.time_provenance or "missing"] = (
            provenance.get(observation.time_provenance or "missing", 0) + 1
        )
    return {
        "schema_version": 7,
        "digests": {
            "sources": digest_of(sources),
            "observations": digest_of(members),
            "mission_associations": digest_of(evidence),
            "cluster_memberships": digest_of(clusters),
            "member_counts": {
                "sources": len(sources),
                "observations": len(members),
                "mission_associations": len(evidence),
                "cluster_memberships": len(clusters),
            },
        },
        "observations": {"time_provenance_buckets": provenance},
    }


def _one_good_observation(tmp_path):
    return _database(
        tmp_path,
        rows=[
            (
                "INSERT INTO sources (id, platform, external_id)"
                " VALUES ('s1', 'youtube', 'video:dQw4w9WgXcQ')",
                (),
            ),
            (
                "INSERT INTO observations (id, source_id, observed_at, time_provenance,"
                " identity_source, observed_title, metric_value, growth_velocity, geo_code,"
                " source_url, metadata)"
                " VALUES ('o1', 's1', '2026-09-11T01:00:00+00:00', 'exact_ingestion',"
                " 'metadata_external_id', 'A video', 1.0, 0.0, 'VN',"
                " 'https://www.youtube.com/watch?v=dQw4w9WgXcQ', '{}')",
                (),
            ),
        ],
    )


def test_the_baseline_built_from_a_database_verifies_it(tmp_path):
    """The control. Every test below starts from this and breaks one thing."""
    path = _one_good_observation(tmp_path)
    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        report = verify(reader, _matching_baseline(path))
    finally:
        reader.close()
    assert report["verified"] is True


def test_an_observation_pointing_at_no_source_cannot_verify(tmp_path):
    """An inner join drops it, and a dropped row is a row the gate never sees.

    This is the migration failure the verifier exists for: the table holds two observations and
    the comparison saw one, so every digest matched and the database was broken.
    """
    path = _one_good_observation(tmp_path)
    baseline = _matching_baseline(path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "INSERT INTO observations (id, source_id, observed_at, time_provenance,"
            " identity_source, metric_value, metadata)"
            " VALUES ('orphan', 'no-such-source', '2026-09-11T02:00:00+00:00',"
            " 'exact_ingestion', 'metadata_external_id', 2.0, '{}')"
        )

    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        report = verify(reader, baseline)
    finally:
        reader.close()

    assert report["dangling_source_references"] == 1
    assert report["observation_rows"] == 2
    assert report["verified"] is False


def test_stored_metadata_that_is_not_json_cannot_verify(tmp_path):
    """Reading it as {} repairs the corruption and lets a broken row match a healthy baseline."""
    path = _one_good_observation(tmp_path)
    baseline = _matching_baseline(path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE observations SET metadata = 'not-json' WHERE id = 'o1'")

    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        report = verify(reader, baseline)
    finally:
        reader.close()

    assert report["invalid_metadata"] == 1
    assert report["verified"] is False


def test_every_observation_row_is_accounted_for(tmp_path):
    """The projected count and the raw row count are compared, so no row leaves quietly."""
    path = _one_good_observation(tmp_path)
    reader = open_stored_reader(f"sqlite:///{path}")
    try:
        report = verify(reader, _matching_baseline(path))
    finally:
        reader.close()

    assert report["observation_rows"] == 1
    assert report["comparisons"][1]["actual_members"] == 1
