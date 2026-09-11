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
    digest_of,
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
    growth_velocity REAL, source_url TEXT, geo_code TEXT, cluster_id TEXT,
    mission_id TEXT, metadata TEXT, captured_at TEXT, published_at TEXT
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
        "INSERT INTO trend_signals (id, platform, raw_title, metric_value, growth_velocity,"
        " source_url, geo_code, cluster_id, mission_id, metadata, captured_at, published_at)"
        " VALUES (:id, :platform, :raw_title, :metric_value, :growth_velocity, :source_url,"
        " :geo_code, :cluster_id, :mission_id, :metadata, :captured_at, :published_at)",
        [{**s, "metadata": json.dumps(s.get("metadata") or {})} for s in signals],
    )
    # metrics entries are (signal_id, captured_at, metric_value[, growth_velocity]).
    conn.executemany(
        "INSERT INTO signal_metrics (signal_id, captured_at, metric_value, growth_velocity)"
        " VALUES (?, ?, ?, ?)",
        [tuple(m) if len(m) == 4 else (*m, 1.0) for m in metrics],
    )
    conn.commit()
    conn.close()
    return path



# A real YouTube id is 11 characters, and the URL pattern needs at least 6. The fixture's default
# "vid-1" is 5, so a URL-only row carrying it resolves by the normalized-URL fallback instead of
# as a video -- these two constants exist so the route tests exercise the route they name.
YT_ID = "dQw4w9WgXcQ"
YT_URL = f"https://www.youtube.com/watch?v={YT_ID}"

def signal(sid, **overrides):
    base = {
        "id": sid,
        "platform": "youtube",
        "raw_title": "A Video",
        "metric_value": 100.0,
        "growth_velocity": 1.0,
        "source_url": "https://www.youtube.com/watch?v=vid-1",
        "geo_code": "VN",
        "cluster_id": "c-1",
        "mission_id": None,
        "metadata": {"video_id": "vid-1"},
        "captured_at": "2026-09-01T00:00:00+00:00",
        "published_at": None,
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
        # The same mission observing one source twice. This is the case the live corpus has and
        # the fixture originally lacked, which let a sort-key bug reach the real run.
        signal(
            "s11",
            source_url="https://www.tiktok.com/@a/video/777",
            platform="tiktok",
            metadata={"item_id": "777"},
            mission_id="m-a",
            cluster_id="c-1",
            metric_value=999.0,
            captured_at="2026-09-04T00:00:00+00:00",
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
        ("s1", "2026-09-01T00:00:00+00:00", 100.0, 1.0),  # the sql/008 copy of the row itself
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
    assert src["identities_holding_one_row"] + src["rows_inside_merged_identities"] == 11
    assert sum(src["resolution_reasons"].values()) == 11
    assert src["identities_holding_one_row"] == 1  # only the google keyword stands alone


def test_observation_total_is_the_stated_formula_not_a_naive_sum(hostile_db):
    obs = run_audit(hostile_db)["observations"]
    assert obs["trend_signals_rows"] == 11
    assert obs["signal_metrics_rows"] == 3
    # Only s1's first point repeats its parent row's whole payload, so only it merges.
    assert obs["lineage_merges_of_the_sql008_copy"] == 1
    assert obs["observations"] == 11 + 3 - 1
    assert obs["naive_sum_for_contrast"] == 14
    assert obs["observations"] < obs["naive_sum_for_contrast"]


def test_the_projection_declares_every_field_it_preserves(hostile_db):
    obs = run_audit(hostile_db)["observations"]
    assert set(obs["preserved_fields"]) == {
        "canonical_source_identity",
        "observed_at",
        "published_at",
        "time_provenance",
        "observed_title",
        "metric_value",
        "growth_velocity",
        "geo_code",
        "normalized_source_url",
        "canonical_metadata",
        "identity_source",
    }
    # Anything left out is a named, reasoned loss rather than an omission nobody noticed.
    assert set(obs["intentional_losses"]) == {
        "trend_signals.id",
        "signal_metrics.id",
        "trend_signals.mission_id",
        "trend_signals.cluster_id",
    }


def test_mission_evidence_reports_exact_and_ambiguous_separately(hostile_db):
    mis = run_audit(hostile_db)["mission_evidence"]
    assert mis["mission_attached_rows"] == 3
    assert mis["exactly_reconstructable"] == 3
    assert mis["unresolved_identity"] == 0
    assert mis["dangling_mission_reference"] == 0
    assert mis["distinct_mission_identity_pairs"] == 2
    # m-a saw the tiktok post twice; the audit reports that instead of dropping one.
    assert mis["missions_with_repeated_identity"] == 1


def test_cluster_ambiguity_is_reported_rather_than_resolved(hostile_db):
    clu = run_audit(hostile_db)["cluster_membership"]
    assert clu["rows_mapping_certainly"] == 10
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
    assert json.loads(first.read_text(encoding="utf-8"))["schema_version"] == 6


# --- the tracked baseline must carry evidence, not content ------------------------------------

# Values planted in the fixture that must never reach the tracked copy.
CONTENT_MARKERS = (
    "A Video",
    "A Video (Remastered)",
    "Third Video",
    "vid-1",
    "vid-2",
    "vid-3",
    "777",
    "nhuom toc",
    "youtube.com",
    "tiktok.com",
    "trends.google.com",
    "mission m-a",
)


def test_the_sanitized_report_names_no_external_content(hostile_db):
    from scripts.migration_reconciliation_audit import build_sanitized_report

    text = json.dumps(build_sanitized_report(run_audit(hostile_db)), ensure_ascii=False)
    leaked = sorted(marker for marker in CONTENT_MARKERS if marker in text)
    assert not leaked, f"the tracked baseline would publish: {leaked}"


def test_the_sanitized_report_keeps_the_evidence(hostile_db):
    from scripts.migration_reconciliation_audit import build_sanitized_report

    report = build_sanitized_report(run_audit(hostile_db))
    assert report["sanitized"] is True
    assert report["observations"]["formula"]
    assert report["sources"]["merge_reasons"]
    assert report["sources"]["unclassified_collision_count"] == 0
    assert "unclassified_collisions" not in report["sources"]
    assert report["invariants"]["checked"] == 14
    assert set(report["digests"]) >= {
        "sources",
        "observations",
        "mission_associations",
        "cluster_memberships",
    }


def test_the_unsanitized_report_does_name_identities(hostile_db):
    # The row-level copy is the one that stays out of git; it has to be useful enough to justify
    # keeping it beside a backup, which means it names what the sanitized copy hides. The first
    # version of this split failed here: both halves were identical, because nothing in the
    # report listed an identity until a detail block was added.
    detail = run_audit(hostile_db)["detail"]
    merged = {entry["identity"] for entry in detail["merged_identities"]}
    assert any("vid-1" in identity for identity in merged)
    assert any("vid-3" in identity for identity in merged)
    assert detail["identities_in_more_than_one_cluster"]
    assert any(
        "A Video (Remastered)" in entry["distinct_titles"]
        for entry in detail["merged_identities"]
    )


def test_the_detail_block_is_absent_from_the_sanitized_report(hostile_db):
    from scripts.migration_reconciliation_audit import build_sanitized_report

    assert "detail" not in build_sanitized_report(run_audit(hostile_db))


def test_digests_are_stable_across_runs(hostile_db):
    assert run_audit(hostile_db)["digests"] == run_audit(hostile_db)["digests"]


def test_digests_ignore_surrogate_row_ids(tmp_path):
    """A digest keyed on trend_signals.id would change the moment the migration rewrites rows."""
    common = dict(
        platform="youtube",
        source_url="https://www.youtube.com/watch?v=vid-9",
        metadata={"video_id": "vid-9"},
        cluster_id="c-1",
        mission_id="m-a",
    )
    left = build_db(str(tmp_path / "left.sqlite"), [signal("row-aaa", **common)])
    right = build_db(str(tmp_path / "right.sqlite"), [signal("row-zzz", **common)])
    assert run_audit(left)["digests"] == run_audit(right)["digests"]


def test_a_changed_metric_changes_the_observation_digest(tmp_path):
    base = build_db(str(tmp_path / "base.sqlite"), [signal("s1", metric_value=100.0)])
    moved = build_db(str(tmp_path / "moved.sqlite"), [signal("s1", metric_value=101.0)])
    left, right = run_audit(base)["digests"], run_audit(moved)["digests"]
    assert left["sources"] == right["sources"]  # same external object
    assert left["observations"] != right["observations"]  # different observed value


def test_the_cli_writes_a_sanitized_file_and_a_row_level_file(hostile_db, tmp_path):
    tracked, private = tmp_path / "tracked.json", tmp_path / "private.json"
    assert main(
        ["--dsn", f"sqlite:///{hostile_db}", "--json-out", str(tracked),
         "--rows-out", str(private), "--quiet"]
    ) == 0
    assert json.loads(tracked.read_text(encoding="utf-8"))["sanitized"] is True
    assert not any(m in tracked.read_text(encoding="utf-8") for m in CONTENT_MARKERS)
    assert "vid-1" in private.read_text(encoding="utf-8")


def test_a_mission_observing_one_source_twice_is_reported_not_collapsed(hostile_db):
    """UNIQUE(mission_id, observation_id), not UNIQUE(mission_id, source_id): keep both."""
    detail = run_audit(hostile_db)["detail"]
    repeats = detail["mission_identity_repeats"]
    assert len(repeats) == 1
    assert repeats[0]["mission_id"] == "m-a"
    assert repeats[0]["row_count"] == 2


def test_two_rows_with_an_identical_payload_stay_two_observations(tmp_path):
    """This is the correction. They are two collection events, not one.

    An earlier version built the member set with `set()`, counted these once, and reported the
    difference as a reduction the migration would perform. Nothing in the schema says two
    sightings must differ on source, time and metric -- in the real corpus rows that match on
    those three carry three distinct growth_velocity values. The surrogate observation id is
    what keeps them apart, so the multiplicity is data and has to be conserved.
    """
    same = dict(captured_at="2026-09-01T00:00:00+00:00", metric_value=100.0)
    path = build_db(
        str(tmp_path / "twins.sqlite"),
        [signal("s1", **same), signal("s2", **same), signal("s3", metric_value=200.0)],
    )
    obs = run_audit(path)["observations"]
    assert obs["observations"] == 3, "no observation may be dropped"
    assert obs["distinct_observation_payloads"] == 2
    assert obs["indistinguishable_observation_multiplicity"] == 1


def test_multiplicity_reaches_the_digest(tmp_path):
    """A set-based digest hashed these two identically; a multiset does not."""
    same = dict(captured_at="2026-09-01T00:00:00+00:00", metric_value=100.0)
    one = build_db(str(tmp_path / "one.sqlite"), [signal("s1", **same)])
    two = build_db(str(tmp_path / "two.sqlite"), [signal("s1", **same), signal("s2", **same)])
    assert run_audit(one)["digests"]["observations"] != run_audit(two)["digests"]["observations"]


def test_two_signal_ids_with_an_identical_payload_are_two_observations(tmp_path):
    same = dict(captured_at="2026-09-02T00:00:00+00:00", metric_value=7.0, growth_velocity=2.0)
    path = build_db(str(tmp_path / "a.sqlite"), [signal("s1", **same), signal("s2", **same)])
    assert run_audit(path)["observations"]["observations"] == 2


def test_one_signal_id_copied_into_both_tables_is_one_observation(tmp_path):
    path = build_db(
        str(tmp_path / "b.sqlite"),
        [signal("s1", captured_at="2026-09-02T00:00:00+00:00", metric_value=7.0,
                growth_velocity=2.0)],
        metrics=[("s1", "2026-09-02T00:00:00+00:00", 7.0, 2.0)],
    )
    obs = run_audit(path)["observations"]
    assert obs["observations"] == 1
    assert obs["lineage_merges_of_the_sql008_copy"] == 1


def test_the_same_time_and_metric_with_a_different_velocity_is_two_observations(tmp_path):
    path = build_db(
        str(tmp_path / "c.sqlite"),
        [signal("s1", captured_at="2026-09-02T00:00:00+00:00", metric_value=7.0,
                growth_velocity=2.0)],
        metrics=[("s1", "2026-09-02T00:00:00+00:00", 7.0, 9.0)],
    )
    obs = run_audit(path)["observations"]
    assert obs["observations"] == 2, "velocity is part of the payload, so this is a new sighting"
    assert obs["lineage_merges_of_the_sql008_copy"] == 0


def test_the_observation_digest_covers_every_observation(hostile_db):
    report = run_audit(hostile_db)
    assert (
        report["digests"]["member_counts"]["observations"]
        == report["observations"]["observations"]
    )


def test_the_cluster_digest_covers_every_membership(hostile_db):
    report = run_audit(hostile_db)
    assert (
        report["digests"]["member_counts"]["cluster_memberships"]
        == report["cluster_membership"]["memberships"]
    )


# --- decision: a historical timestamp is labelled, never re-labelled silently -----------------


def test_provenance_buckets_account_for_every_observation(hostile_db):
    obs = run_audit(hostile_db)["observations"]
    buckets = obs["time_provenance_buckets"]
    assert set(buckets) == {"exact_ingestion", "legacy_publish_only", "unknown"}
    assert sum(buckets.values()) == obs["observations"]


def test_a_youtube_row_whose_captured_at_is_its_publish_time_is_legacy(tmp_path):
    """The signature sql/015 left behind: the backfill made published_at equal captured_at."""
    stamp = "2026-08-01T00:00:00+00:00"
    path = build_db(
        str(tmp_path / "legacy.sqlite"),
        [signal("s1", captured_at=stamp, published_at=stamp)],
    )
    obs = run_audit(path)["observations"]
    assert obs["time_provenance_buckets"]["legacy_publish_only"] == 1
    assert obs["time_provenance_buckets"]["exact_ingestion"] == 0


def test_a_youtube_row_written_after_the_split_is_exact(tmp_path):
    path = build_db(
        str(tmp_path / "post.sqlite"),
        [signal("s1", captured_at="2026-09-10T00:00:00+00:00",
                published_at="2026-08-01T00:00:00+00:00")],
    )
    assert run_audit(path)["observations"]["time_provenance_buckets"]["exact_ingestion"] == 1


def test_a_youtube_row_with_no_published_at_cannot_be_placed(tmp_path):
    path = build_db(str(tmp_path / "unk.sqlite"), [signal("s1", published_at=None)])
    assert run_audit(path)["observations"]["time_provenance_buckets"]["unknown"] == 1


def test_a_google_probe_row_is_exact_while_a_google_feed_row_is_legacy(tmp_path):
    stamp = "2026-08-01T00:00:00+00:00"
    google = dict(platform="google", metadata={"keyword": "k"},
                  source_url="https://trends.google.com/trends/explore?q=k")
    path = build_db(
        str(tmp_path / "google.sqlite"),
        [
            signal("s1", raw_title="Google Search Trends: k", captured_at=stamp,
                   published_at=None, **google),
            signal("s2", raw_title="k", captured_at=stamp, published_at=stamp, **google),
        ],
    )
    buckets = run_audit(path)["observations"]["time_provenance_buckets"]
    assert buckets["exact_ingestion"] == 1
    assert buckets["legacy_publish_only"] == 1
    assert buckets["unknown"] == 0


def test_a_browser_connector_row_is_always_exact(tmp_path):
    path = build_db(
        str(tmp_path / "tiktok.sqlite"),
        [signal("s1", platform="tiktok", metadata={"item_id": "1"},
                source_url="https://www.tiktok.com/@a/video/1", published_at=None)],
    )
    assert run_audit(path)["observations"]["time_provenance_buckets"]["exact_ingestion"] == 1


def test_provenance_alone_changes_the_serialized_member(tmp_path):
    """Isolation, done properly: every other field held constant, only provenance varies.

    The first version of this test changed the platform to move a row between buckets, which also
    changed the canonical identity, the URL, the metadata and observed_at. That digest would have
    differed with time_provenance stripped out entirely, so it proved nothing about provenance.
    Calling the serializer directly is the only way to vary one field.
    """
    from ignis.infrastructure.migration.legacy_projection import (
        SignalRow,
        observation_member,
    )

    row = SignalRow(
        signal_id="s1", platform="youtube", source_url="https://www.youtube.com/watch?v=v",
        raw_title="T", metadata={"video_id": "v"}, captured_at="2026-08-01T00:00:00+00:00",
        published_at="2026-08-01T00:00:00+00:00", metric_value=1.0, growth_velocity=0.0,
        geo_code="VN", mission_id=None, cluster_id=None,
    )
    args = dict(
        identity="youtube:video:v",
        identity_source="metadata_external_id",
        row=row,
        metric_value=1.0,
        growth_velocity=0.0,
    )
    as_legacy = observation_member(observed_at=None, time_provenance="legacy_publish_only", **args)
    as_unknown = observation_member(observed_at=None, time_provenance="unknown", **args)
    assert as_legacy != as_unknown, "provenance must reach the serialized member"
    assert digest_of([as_legacy]) != digest_of([as_unknown])


def test_a_relabelled_legacy_observation_changes_the_corpus_digest(tmp_path):
    """And end to end: the same row, classified differently, gives a different digest.

    Only published_at moves, which is what decides the classification. It is also inside the
    digest, so this shows the pair changing together rather than isolating provenance -- the test
    above does the isolation.
    """
    stamp = "2026-08-01T00:00:00+00:00"
    legacy = build_db(str(tmp_path / "l.sqlite"),
                      [signal("s1", captured_at=stamp, published_at=stamp)])
    exact = build_db(str(tmp_path / "e.sqlite"),
                     [signal("s1", captured_at=stamp, published_at="2026-07-01T00:00:00+00:00")])
    left, right = run_audit(legacy), run_audit(exact)
    assert left["observations"]["time_provenance_buckets"]["legacy_publish_only"] == 1
    assert right["observations"]["time_provenance_buckets"]["exact_ingestion"] == 1
    assert left["digests"]["observations"] != right["digests"]["observations"]


def test_provenance_is_derived_per_event_not_per_row(tmp_path):
    """Mixed lineage: a parent whose current clock is proven, over a historical legacy point.

    Both repositories overwrite trend_signals.captured_at on every re-poll, while each
    signal_metrics row keeps the captured_at of the poll that wrote it. So a row can currently
    hold a proven ingestion time while its metric history still contains a point stamped with the
    publish time. Deciding provenance once per row misfiles that point.
    """
    publish = "2026-07-01T00:00:00+00:00"
    path = build_db(
        str(tmp_path / "mixed.sqlite"),
        # The parent's captured_at differs from published_at, so the current snapshot is exact.
        [signal("s1", captured_at="2026-09-01T00:00:00+00:00", published_at=publish,
                metric_value=200.0, growth_velocity=2.0)],
        # A point left over from before the split, stamped with the publish time.
        metrics=[("s1", publish, 100.0, 1.0)],
    )
    obs = run_audit(path)["observations"]
    assert obs["observations"] == 2
    assert obs["time_provenance_buckets"]["exact_ingestion"] == 1
    assert obs["time_provenance_buckets"]["legacy_publish_only"] == 1
    assert obs["time_provenance_buckets"]["unknown"] == 0


def test_a_legacy_parent_can_carry_a_later_exact_point(tmp_path):
    """The mirror case: the parent still holds a publish time, a later point does not."""
    publish = "2026-07-01T00:00:00+00:00"
    path = build_db(
        str(tmp_path / "mirror.sqlite"),
        [signal("s1", captured_at=publish, published_at=publish, growth_velocity=1.0)],
        metrics=[("s1", "2026-09-01T00:00:00+00:00", 500.0, 3.0)],
    )
    buckets = run_audit(path)["observations"]["time_provenance_buckets"]
    assert buckets["legacy_publish_only"] == 1
    assert buckets["exact_ingestion"] == 1


def test_the_digest_algorithm_label_says_multiset(hostile_db):
    assert "multiset" in run_audit(hostile_db)["digests"]["algorithm"]
    assert "sorted set" not in run_audit(hostile_db)["digests"]["algorithm"]


# --- identity_source: field 11 ----------------------------------------------------------------


def test_identity_source_alone_changes_the_serialized_member():
    """Vary the route and nothing else, at the serializer, so the field cannot ride on another.

    The same shape as the time_provenance isolation test, and for the same reason: an earlier
    version of that test moved a row between buckets by changing its platform, which changed five
    fields at once and would have passed with the field removed entirely.
    """
    from ignis.infrastructure.migration.legacy_projection import (
        SignalRow,
        observation_member,
    )

    row = SignalRow(
        signal_id="s1",
        platform="youtube",
        source_url="https://www.youtube.com/watch?v=vid-1",
        raw_title="A Video",
        metadata={"video_id": "vid-1"},
        captured_at="2026-09-01T00:00:00+00:00",
        published_at=None,
        metric_value=100.0,
        growth_velocity=1.0,
        geo_code="VN",
        mission_id=None,
        cluster_id=None,
    )
    args = dict(
        identity="youtube:video:vid-1",
        row=row,
        observed_at="2026-09-01T00:00:00+00:00",
        time_provenance="exact_ingestion",
        metric_value=100.0,
        growth_velocity=1.0,
    )
    from_metadata = observation_member(identity_source="metadata_external_id", **args)
    from_url = observation_member(identity_source="url_external_id", **args)
    from_fallback = observation_member(identity_source="normalized_url_fallback", **args)
    assert len({from_metadata, from_url, from_fallback}) == 3


def test_two_observations_of_one_source_keep_two_routes(tmp_path):
    """The corpus case: one YouTube video arrived with metadata once and URL-only once.

    Both rows resolve to one canonical source, and both routes survive into the digest. A
    source-level identity_source could only have kept one of them.
    """
    path = build_db(
        tmp_path / "routes.sqlite",
        [
            signal("s-meta", source_url=YT_URL, metadata={"video_id": YT_ID}),
            signal(
                "s-url", source_url=YT_URL, metadata={},
                captured_at="2026-09-02T00:00:00+00:00",
            ),
        ],
    )
    report = run_audit(path)
    assert report["sources"]["canonical_sources"] == 1, "one video, one canonical source"
    assert report["sources"]["resolution_reasons"] == {
        "metadata_external_id": 1,
        "url_external_id": 1,
    }
    assert report["digests"]["member_counts"]["observations"] == 2
    assert report["balanced"] is True


# There is deliberately no row-level test asserting that removing identity_source would fuse two
# observations. It cannot exist: the route is decided by whether metadata carries the identifier,
# so two rows with different routes always differ in metadata as well, and such a test would pass
# with the field deleted. The serializer-level test above is what isolates the field, and
# deleting the field from the member proves it -- exactly that test fails, plus the declaration.
