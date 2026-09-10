"""The migration is gated on this audit, so the audit itself needs a fixture that hurts.

Every scenario below exists in the real corpus: one source polled hundreds of times, a URL that
reported two different titles, metric snapshots living beside the row they came from, rows
attached to a mission, and one identity appearing under more than one cluster. A gate that only
sees clean data would pass the day before the migration and be worthless the day after.
"""

import json
import sqlite3

import pytest

from scripts.migration_reconciliation_audit import (
    MERGE_REPEAT,
    MERGE_TITLE_CHANGED,
    MERGE_URL_VARIANT,
    RESOLUTION_METADATA,
    RESOLUTION_NORMALIZED_URL,
    RESOLUTION_UNRESOLVED,
    audit,
    main,
    normalize_url,
    open_reader,
    resolve_identity,
)

SCHEMA = """
CREATE TABLE research_missions (id TEXT PRIMARY KEY, title TEXT);
CREATE TABLE topic_clusters (id TEXT PRIMARY KEY, canonical_name TEXT);
CREATE TABLE trend_signals (
    id TEXT PRIMARY KEY, platform TEXT, raw_title TEXT, metric_value REAL,
    source_url TEXT, geo_code TEXT, cluster_id TEXT, mission_id TEXT,
    metadata TEXT, captured_at TEXT, published_at TEXT
);
CREATE TABLE signal_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id TEXT, captured_at TEXT,
    metric_value REAL, growth_velocity REAL
);
"""


def build_db(path, signals, metrics=(), missions=("m-a", "m-b"), clusters=("c-1", "c-2")):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT INTO research_missions (id, title) VALUES (?, ?)",
        [(m, f"mission {m}") for m in missions],
    )
    conn.executemany(
        "INSERT INTO topic_clusters (id, canonical_name) VALUES (?, ?)",
        [(c, f"cluster {c}") for c in clusters],
    )
    conn.executemany(
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, source_url,"
        " cluster_id, mission_id, metadata, captured_at)"
        " VALUES (:id, :platform, :raw_title, :metric_value, :source_url, :cluster_id,"
        " :mission_id, :metadata, :captured_at)",
        [{**s, "metadata": json.dumps(s.get("metadata") or {})} for s in signals],
    )
    conn.executemany(
        "INSERT INTO signal_metrics (signal_id, captured_at, metric_value, growth_velocity)"
        " VALUES (?, ?, ?, 0)",
        list(metrics),
    )
    conn.commit()
    conn.close()
    return path


def signal(sid, **overrides):
    base = {
        "id": sid,
        "platform": "youtube",
        "raw_title": "A Video",
        "metric_value": 100.0,
        "source_url": "https://www.youtube.com/watch?v=vid-1",
        "cluster_id": "c-1",
        "mission_id": None,
        "metadata": {"video_id": "vid-1"},
        "captured_at": "2026-09-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.fixture
def hostile_db(tmp_path):
    """One database carrying every shape the real corpus throws at the migration."""
    signals = [
        # Group 1: one source polled three times with three different metrics, title stable.
        signal("s1", metric_value=100.0, captured_at="2026-09-01T00:00:00+00:00"),
        signal("s2", metric_value=200.0, captured_at="2026-09-02T00:00:00+00:00"),
        signal("s3", metric_value=300.0, captured_at="2026-09-03T00:00:00+00:00"),
        # Group 2: same external id, the title it reported changed between observations. The URLs
        # normalise to one another -- www and a tracking parameter are not a different object --
        # so this must be classified on the title, not on the URL.
        signal(
            "s4",
            source_url="https://www.youtube.com/watch?v=vid-2",
            metadata={"video_id": "vid-2"},
        ),
        signal(
            "s5",
            source_url="https://youtube.com/watch?v=vid-2&utm_source=newsletter",
            metadata={"video_id": "vid-2"},
            raw_title="A Video (Remastered)",
        ),
        # Group 3: one external id reached through two URL shapes that do not normalise together,
        # a share link and a watch link. Only the connector's video_id ties them.
        signal(
            "s9",
            source_url="https://www.youtube.com/watch?v=vid-3",
            metadata={"video_id": "vid-3"},
            raw_title="Third Video",
        ),
        signal(
            "s10",
            source_url="https://youtu.be/vid-3",
            metadata={"video_id": "vid-3"},
            raw_title="Third Video",
        ),
        # A second platform, mission-attached, same identity claimed by both missions.
        signal(
            "s6",
            source_url="https://www.tiktok.com/@a/video/777",
            platform="tiktok",
            metadata={"item_id": "777"},
            mission_id="m-a",
            cluster_id="c-1",
        ),
        signal(
            "s7",
            source_url="https://www.tiktok.com/@a/video/777",
            platform="tiktok",
            metadata={"item_id": "777"},
            mission_id="m-b",
            cluster_id="c-2",  # cluster ambiguity: one identity, two clusters
        ),
        # A row with no cluster at all.
        signal(
            "s8",
            source_url="https://trends.google.com/trends/explore?q=nhuom%20toc",
            platform="google",
            metadata={"keyword": "nhuom toc"},
            cluster_id=None,
        ),
    ]
    metrics = [
        ("s1", "2026-09-01T00:00:00+00:00", 100.0),  # duplicates the row itself
        ("s1", "2026-09-05T00:00:00+00:00", 150.0),  # an observation the row does not carry
        ("s6", "2026-09-06T00:00:00+00:00", 900.0),
    ]
    return build_db(str(tmp_path / "hostile.sqlite"), signals, metrics)


def run_audit(path):
    reader = open_reader(f"sqlite:///{path}")
    try:
        return audit(reader)
    finally:
        reader.close()


# --- identity policy -------------------------------------------------------------------------


def test_title_is_not_part_of_identity():
    left, _ = resolve_identity("youtube", "https://www.youtube.com/watch?v=x1", {"video_id": "x1"})
    right, _ = resolve_identity("youtube", "https://www.youtube.com/watch?v=x1", {"video_id": "x1"})
    assert left == right


def test_connector_metadata_wins_over_the_url():
    identity, reason = resolve_identity(
        "youtube", "https://www.youtube.com/watch?v=from-url", {"video_id": "from-metadata"}
    )
    assert reason == RESOLUTION_METADATA
    assert identity.endswith("from-metadata")


def test_url_variants_collapse_to_one_identity():
    assert normalize_url("https://youtube.com/watch?v=a&utm_source=x") == normalize_url(
        "https://www.youtube.com/watch?v=a"
    )


def test_tiktok_video_and_tag_are_different_objects():
    video, _ = resolve_identity("tiktok", "https://www.tiktok.com/@a/video/777", {})
    tag, _ = resolve_identity("tiktok", "https://www.tiktok.com/tag/777", {})
    assert video != tag


def test_an_unknown_platform_falls_back_to_the_normalised_url():
    _, reason = resolve_identity("mastodon", "https://example.test/post/1", {})
    assert reason == RESOLUTION_NORMALIZED_URL


def test_a_row_with_neither_metadata_nor_url_is_unresolved():
    identity, reason = resolve_identity("youtube", None, {})
    assert reason == RESOLUTION_UNRESOLVED
    assert identity == ""


# --- the four questions ----------------------------------------------------------------------


def test_canonical_sources_are_counted_by_identity_not_by_row(hostile_db):
    report = run_audit(hostile_db)
    # Seven youtube rows are three videos; two tiktok rows are one post; google is its own.
    assert report["sources"]["canonical_sources"] == 5


def test_every_merge_carries_a_reason_code(hostile_db):
    reasons = run_audit(hostile_db)["sources"]["merge_reasons"]
    assert set(reasons) == {MERGE_REPEAT, MERGE_TITLE_CHANGED, MERGE_URL_VARIANT}
    assert run_audit(hostile_db)["sources"]["unclassified_collisions"] == []


def test_no_legacy_row_falls_outside_the_identity_breakdown(hostile_db):
    report = run_audit(hostile_db)
    src = report["sources"]
    assert src["identities_holding_one_row"] + src["rows_inside_merged_identities"] == 10
    assert sum(src["resolution_reasons"].values()) == 10
    assert src["identities_holding_one_row"] == 1  # only the google keyword stands alone


def test_observation_total_is_the_stated_formula_not_a_naive_sum(hostile_db):
    obs = run_audit(hostile_db)["observations"]
    assert obs["trend_signals_rows"] == 10
    assert obs["signal_metrics_rows"] == 3
    assert obs["triples_shared_by_both_tables"] == 1  # only s1's first point duplicates its row
    assert obs["observations"] == 10 + 3 - 1
    assert obs["naive_sum_for_contrast"] == 13
    assert obs["observations"] < obs["naive_sum_for_contrast"]


def test_mission_evidence_reports_exact_and_ambiguous_separately(hostile_db):
    mis = run_audit(hostile_db)["mission_evidence"]
    assert mis["mission_attached_rows"] == 2
    assert mis["exactly_reconstructable"] == 2
    assert mis["unresolved_identity"] == 0
    assert mis["dangling_mission_reference"] == 0
    assert mis["distinct_mission_identity_pairs"] == 2


def test_cluster_ambiguity_is_reported_rather_than_resolved(hostile_db):
    clu = run_audit(hostile_db)["cluster_membership"]
    assert clu["rows_mapping_certainly"] == 9
    assert clu["rows_without_cluster"] == 1
    # The tiktok post sits in c-1 under one mission and c-2 under the other. The audit says so
    # instead of picking one, because cluster membership belongs to the observation.
    assert clu["identities_spanning_more_than_one_cluster"] == 1


def test_a_hostile_but_intact_database_balances(hostile_db):
    report = run_audit(hostile_db)
    assert report["invariants"]["failures"] == []
    assert report["balanced"] is True


# --- the gate --------------------------------------------------------------------------------


def test_a_dangling_metric_point_fails_the_audit(tmp_path):
    path = build_db(str(tmp_path / "dangling_metric.sqlite"), [signal("s1")],
                    metrics=[("ghost", "2026-09-01T00:00:00+00:00", 1.0)])
    report = run_audit(path)
    assert report["balanced"] is False
    assert any("metric points reference a missing" in f for f in report["invariants"]["failures"])


def test_a_dangling_mission_reference_fails_the_audit(tmp_path):
    path = build_db(str(tmp_path / "dangling_mission.sqlite"),
                    [signal("s1", mission_id="m-gone")])
    report = run_audit(path)
    assert report["balanced"] is False
    assert any("mission that no longer exists" in f for f in report["invariants"]["failures"])


def test_a_dangling_cluster_reference_fails_the_audit(tmp_path):
    path = build_db(str(tmp_path / "dangling_cluster.sqlite"),
                    [signal("s1", cluster_id="c-gone")])
    report = run_audit(path)
    assert report["balanced"] is False
    assert any("cluster that no longer exists" in f for f in report["invariants"]["failures"])


def test_an_unresolvable_row_fails_the_audit(tmp_path):
    path = build_db(str(tmp_path / "unresolved.sqlite"),
                    [signal("s1", source_url=None, metadata={})])
    report = run_audit(path)
    assert report["balanced"] is False
    assert any("no resolvable external identity" in f for f in report["invariants"]["failures"])


def test_the_cli_exits_non_zero_when_the_audit_fails(tmp_path, capsys):
    path = build_db(str(tmp_path / "gate.sqlite"), [signal("s1", mission_id="m-gone")])
    assert main(["--dsn", f"sqlite:///{path}"]) == 1
    assert "NOT BALANCED" in capsys.readouterr().out


def test_the_cli_exits_zero_on_a_balanced_database(hostile_db, capsys):
    assert main(["--dsn", f"sqlite:///{hostile_db}"]) == 0
    assert "BALANCED" in capsys.readouterr().out


def test_the_cli_reports_a_missing_database_rather_than_crashing(tmp_path, capsys):
    assert main(["--dsn", f"sqlite:///{tmp_path / 'absent.sqlite'}"]) == 2
    assert "read-only" in capsys.readouterr().err


# --- read-only and determinism ---------------------------------------------------------------


def test_the_reader_cannot_write(hostile_db):
    reader = open_reader(f"sqlite:///{hostile_db}")
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader._conn.execute("DELETE FROM trend_signals")
    finally:
        reader.close()


def test_the_audit_leaves_the_database_byte_identical(hostile_db):
    before = open(hostile_db, "rb").read()
    run_audit(hostile_db)
    assert open(hostile_db, "rb").read() == before


def test_the_json_report_is_deterministic(hostile_db, tmp_path):
    first, second = tmp_path / "a.json", tmp_path / "b.json"
    main(["--dsn", f"sqlite:///{hostile_db}", "--json-out", str(first), "--quiet"])
    main(["--dsn", f"sqlite:///{hostile_db}", "--json-out", str(second), "--quiet"])
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")
    assert json.loads(first.read_text(encoding="utf-8"))["schema_version"] == 1
