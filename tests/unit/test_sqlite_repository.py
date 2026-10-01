import sqlite3

import pytest
from ignis.domain.cross_platform_score import cross_platform_score
from datetime import datetime, timezone
from uuid import uuid4

from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.fixture
def sqlite_repo():
    # Use temporary file or in-memory sqlite for isolation
    return SqliteTrendRepository("sqlite:///:memory:")


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_field", ["required_channels", "stop_conditions"])
async def test_manifest_json_array_constraints_reject_whitespace_empty_arrays(
    sqlite_repo, empty_field
):
    mission = ResearchMission(title="Manifest constraint", keywords=["bounded"])
    await sqlite_repo.save_mission(mission)
    values = {
        "required_channels": '["youtube"]',
        "stop_conditions": '["frame complete"]',
    }
    values[empty_field] = "[ ]"

    with pytest.raises(sqlite3.IntegrityError):
        sqlite_repo._mem_conn.execute(
            "INSERT INTO mission_manifests"
            " (mission_id, outcome, required_channels, optional_channels, authority_boundary,"
            " quota_budget, output_type, stop_conditions, analysis_policy, retention_policy,"
            " created_by, confirmed_at, manifest_digest)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(mission.id),
                "Collect bounded evidence",
                values["required_channels"],
                "[]",
                '{"public_http":true,"official_api":false,"browser_session":false,'
                '"paid_quota":false}',
                "{}",
                "COLLECTION_FRAME",
                values["stop_conditions"],
                "evidence-gated-v1",
                "mission-only",
                "contract-test",
                datetime.now(timezone.utc).isoformat(),
                "d" * 64,
            ),
        )


@pytest.mark.asyncio
async def test_sqlite_signals_crud(sqlite_repo):
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Hướng dẫn làm AI Agent thực chiến",
        metric_value=25000.0,
        growth_velocity=150.0,
        source_url="https://youtube.com/watch?v=sample123",
        geo_code=GeoCode.VN,
        metadata={"channel_title": "AI Master", "likes": 500},
        captured_at=datetime.now(timezone.utc),
    )

    # 1. Save the cluster first, then the signals. That is the order the pipeline uses, and it
    # is the order the schema requires: an observation carries its cluster as a foreign key, so
    # the cluster has to exist before the observation referencing it is written.
    cluster_id = uuid4()
    cluster = TopicCluster(
        id=cluster_id,
        canonical_name="AI Agent",
        cross_platform_score=85.0,
        signals=[signal],
    )
    await sqlite_repo.save_clusters([cluster])

    # 2. Save signals
    saved_count = await sqlite_repo.save_signals([signal])
    assert saved_count == 1


    # 3. Query top clusters
    top_clusters = await sqlite_repo.get_top_clusters(geo=GeoCode.VN, limit=5)
    assert len(top_clusters) >= 1
    assert top_clusters[0].canonical_name == "AI Agent"
    # Computed from the observations in the window, not read back from the cluster row. One
    # source on one platform scores no platform diversity at all, whatever was stored.
    assert top_clusters[0].cross_platform_score == cross_platform_score(
        distinct_platforms=1, total_metric=25000.0, average_velocity=150.0
    )

    # 4. Query cluster signals
    cluster_signals = await sqlite_repo.get_cluster_signals(cluster_id)
    assert len(cluster_signals) == 1
    assert cluster_signals[0].raw_title == "Hướng dẫn làm AI Agent thực chiến"


@pytest.mark.asyncio
async def test_sqlite_mission_lifecycle(sqlite_repo):
    mission_id = uuid4()
    mission = ResearchMission(
        id=mission_id,
        title="Nghiên cứu thị trường AI Agent VN",
        keywords=["AI Agent", "n8n"],
        shortcode="VN-AI-90D",
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_30D,
        status="IN_PROGRESS",
        agent="claude-desktop",
        summary="Đánh giá khoảng trống thị trường.",
        created_at=datetime.now(timezone.utc),
    )

    # 1. Save mission
    await sqlite_repo.save_mission(mission)

    # 2. Get mission
    retrieved = await sqlite_repo.get_mission(mission_id)
    assert retrieved is not None
    assert retrieved.title == "Nghiên cứu thị trường AI Agent VN"
    assert retrieved.shortcode == "VN-AI-90D"
    assert "n8n" in retrieved.keywords

    # 3. Add mission signals
    sig1 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Video 1",
        metric_value=100.0,
        mission_id=mission_id,
        geo_code=GeoCode.VN,
        # A signal now has to say which external object it observed. Every row in the corpus
        # does; one that identifies nothing is skipped by the writer and counted, rather than
        # stored under an invented key.
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        metadata={"video_id": "dQw4w9WgXcQ"},
    )
    await sqlite_repo.save_signals([sig1])


    mission_sigs = await sqlite_repo.get_mission_signals(mission_id)
    assert len(mission_sigs) == 1
    assert mission_sigs[0].raw_title == "Video 1"

    # 4. Delete mission signals (replace mode)
    deleted = await sqlite_repo.delete_mission_signals(mission_id)
    assert deleted == 1
    after_del = await sqlite_repo.get_mission_signals(mission_id)
    assert len(after_del) == 0


@pytest.mark.asyncio
async def test_sqlite_platform_credentials(sqlite_repo):
    # Save credentials
    await sqlite_repo.save_platform_credentials(
        platform="tiktok",
        auth_type="session_cookies",
        credentials_data={"sessionid": "mock_cookie_123"},
        is_active=True,
    )

    # Get credentials
    cred = await sqlite_repo.get_platform_credentials("tiktok")
    assert cred is not None
    assert cred["platform"] == "tiktok"
    assert cred["credentials_data"]["sessionid"] == "mock_cookie_123"
    assert "credentials" not in cred, "the SQLite-only alias is not part of the public record"

    # List
    creds_list = await sqlite_repo.list_platform_credentials()
    assert len(creds_list) >= 1

    # Delete
    deleted = await sqlite_repo.delete_platform_credentials("tiktok")
    assert deleted is True
    assert await sqlite_repo.get_platform_credentials("tiktok") is None


@pytest.mark.asyncio
async def test_sqlite_dynamic_lexicons(sqlite_repo):
    # Initial seeds exist
    lexicons = await sqlite_repo.get_domain_lexicons()
    assert len(lexicons) > 0

    # Register new niche terms
    registered = await sqlite_repo.register_lexicon_terms(
        domain="fashion",
        terms=["ao dai cach tan", "set linen"],
        category="product",
        created_by="agent",
    )
    assert registered == 2

    # Query domain
    fashion_lex = await sqlite_repo.get_domain_lexicons(domain="fashion")
    terms = [lex["term"] for lex in fashion_lex]
    assert "ao dai cach tan" in terms
    assert "set linen" in terms



@pytest.mark.asyncio
async def test_an_existing_database_stops_requiring_a_cluster_first_seen_time(tmp_path):
    """CREATE TABLE IF NOT EXISTS leaves a user's file alone, so the constraint has to be relaxed.

    A database created before the backfill declares topic_clusters.first_seen_at NOT NULL. The
    backfill produces clusters built only from observations whose ingestion time was never
    recorded, and those have no first sighting to store, so an untouched file would reject them
    while a fresh one accepted them -- the two backends agreeing and the two vintages not.
    """
    import sqlite3

    from ignis.domain.entities import TopicCluster
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    db_path = tmp_path / "old_schema.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE topic_clusters (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
                topic_label TEXT,
                cross_platform_score REAL DEFAULT 0.0,
                summary_text TEXT,
                category TEXT DEFAULT 'general',
                first_seen_at TEXT NOT NULL,
                last_updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO topic_clusters (id, canonical_name, first_seen_at, last_updated_at)"
            " VALUES ('kept', 'an older cluster', '2026-08-01T00:00:00+00:00',"
            " '2026-08-01T00:00:00+00:00')"
        )
        # An observation already pointing at that cluster, written before the rebuild runs.
        # Dropping the old table with foreign keys enforced fires ON DELETE SET NULL and strips
        # the cluster off it, so the reference has to pre-date the rebuild or the test measures
        # nothing. Both tables are created here by hand for the same reason: opening the
        # repository first would rebuild before the reference existed.
        conn.execute(
            "CREATE TABLE sources (id TEXT PRIMARY KEY, platform TEXT NOT NULL,"
            " external_id TEXT NOT NULL, UNIQUE (platform, external_id))"
        )
        conn.execute(
            "CREATE TABLE observations ("
            " id TEXT PRIMARY KEY,"
            " source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,"
            " cluster_id TEXT REFERENCES topic_clusters(id) ON DELETE SET NULL,"
            " observed_at TEXT, published_at TEXT, time_provenance TEXT NOT NULL,"
            " identity_source TEXT NOT NULL, observed_title TEXT, metric_value REAL,"
            " growth_velocity REAL, geo_code TEXT, source_url TEXT, metadata TEXT)"
        )
        conn.execute(
            "INSERT INTO sources (id, platform, external_id) VALUES ('s1', 'youtube', 'video:x')"
        )
        conn.execute(
            "INSERT INTO observations (id, source_id, cluster_id, observed_at, metric_value,"
            " time_provenance, identity_source) VALUES ('o1', 's1', 'kept',"
            " '2026-09-11T00:00:00+00:00', 1.0, 'exact_ingestion', 'metadata_external_id')"
        )

    repository = SqliteTrendRepository(str(db_path))
    try:
        await repository.save_clusters([TopicCluster(canonical_name="only legacy", first_seen_at=None)])

        with sqlite3.connect(db_path) as conn:
            stored = conn.execute(
                "SELECT first_seen_at FROM topic_clusters WHERE canonical_name = 'only legacy'"
            ).fetchone()
            survived = conn.execute(
                "SELECT first_seen_at FROM topic_clusters WHERE id = 'kept'"
            ).fetchone()
            still_clustered = conn.execute(
                "SELECT cluster_id FROM observations WHERE id = 'o1'"
            ).fetchone()
            not_null_count = sum(
                1
                for row in conn.execute("PRAGMA table_info(topic_clusters)")
                if row[1] == "first_seen_at" and row[3] == 1
            )
            dangling = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert stored[0] is None
        assert survived[0] == "2026-08-01T00:00:00+00:00", "the rebuild must not lose rows"
        assert still_clustered[0] == "kept", "the rebuild must not strip the cluster off an observation"
        assert not_null_count == 0
        assert dangling == [], f"the rebuild left dangling references: {dangling}"
        # Idempotent: opening the database again must not rebuild or change anything.
        await repository.close()
        again = SqliteTrendRepository(str(db_path))
        try:
            await again._ensure_schema()
            with sqlite3.connect(db_path) as conn:
                assert (
                    conn.execute("SELECT count(*) FROM topic_clusters").fetchone()[0] == 2
                )
                assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        finally:
            await again.close()
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_an_existing_database_upgrades_evidence_contracts_without_losing_rows(tmp_path):
    """Legacy SQLite checks must be rebuilt, not merely decorated with new columns."""
    import sqlite3

    db_path = tmp_path / "legacy_evidence.sqlite"
    initial = SqliteTrendRepository(str(db_path))
    await initial._ensure_schema()
    await initial.close()

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            DROP TABLE mission_claim_evidence;
            DROP TABLE mission_claims;
            DROP TABLE mission_manifests;
            DROP TABLE mission_evidence_qualifications;
            DROP TABLE mission_probe_outcomes;
            DROP TABLE market_brief_revisions;

            CREATE TABLE market_brief_revisions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                revision_number INTEGER NOT NULL,
                decision TEXT NOT NULL,
                target_user TEXT NOT NULL,
                problem TEXT NOT NULL,
                geo TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                falsifiers TEXT NOT NULL,
                confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                UNIQUE (mission_id),
                UNIQUE (workspace_id, revision_number),
                CHECK (falsifiers <> '[]')
            );

            CREATE TABLE mission_probe_outcomes (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES mission_run_journals(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                connector_surface TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('HEALTHY', 'EMPTY_NO_DATA', 'AUTH_REQUIRED', 'RATE_LIMITED',
                               'DEGRADED')
                ),
                signals_collected INTEGER NOT NULL CHECK (signals_collected >= 0),
                queried_keywords TEXT NOT NULL DEFAULT '[]',
                queried_window TEXT,
                query_fingerprint TEXT NOT NULL,
                completed_at TEXT NOT NULL,
                UNIQUE (run_id, connector_surface)
            );

            CREATE TABLE mission_evidence_qualifications (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                brief_revision_id TEXT REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
                frame_fingerprint TEXT NOT NULL,
                relation TEXT NOT NULL CHECK (
                    relation IN ('QUALIFIED_SUPPORT', 'CONTEXT_ONLY',
                                 'EXCLUDED_IRRELEVANT', 'UNASSESSED')
                ),
                purpose TEXT NOT NULL CHECK (purpose IN ('DEMAND', 'SUPPLY', 'VOC', 'CONTEXT')),
                confidence REAL,
                reason_code TEXT NOT NULL,
                judged_by TEXT NOT NULL,
                model TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (mission_id, observation_id),
                FOREIGN KEY (mission_id, observation_id)
                    REFERENCES mission_evidence (mission_id, observation_id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "INSERT INTO research_workspaces"
            " (id, slug, root_path, status, created_at) VALUES (?, ?, ?, ?, ?)",
            ("workspace", "legacy", "/tmp/legacy", "READY", "2026-09-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO research_missions"
            " (id, title, keywords, platforms, workspace_id, surface, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "mission",
                "Legacy evidence",
                '["legacy"]',
                '["youtube"]',
                "workspace",
                "ATTENTION",
                "2026-09-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO research_missions"
            " (id, title, keywords, platforms, workspace_id, surface, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "market-mission",
                "Legacy market question",
                '["legacy"]',
                '["youtube"]',
                "workspace",
                "MARKET",
                "2026-09-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO market_brief_revisions"
            " (id, workspace_id, mission_id, revision_number, decision, target_user,"
            " problem, geo, timeframe, hypothesis, falsifiers, confirmed_by, confirmed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "brief-legacy",
                "workspace",
                "market-mission",
                1,
                "Decide whether to continue",
                "Operators",
                "Manual setup",
                "VN",
                "30d",
                "Setup friction matters",
                '["No repeated friction"]',
                "owner",
                "2026-09-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO mission_run_journals"
            " (id, workspace_id, mission_id, journal_path, sequence, status, started_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "run",
                "workspace",
                "mission",
                "/tmp/legacy/run.md",
                1,
                "COMPLETED",
                "2026-09-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO mission_probe_outcomes"
            " (id, run_id, platform, connector_surface, status, signals_collected,"
            " queried_keywords, query_fingerprint, completed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "outcome-legacy",
                "run",
                "youtube",
                "youtube.search",
                "HEALTHY",
                1,
                '["legacy"]',
                "legacy-fingerprint",
                "2026-09-01T00:01:00+00:00",
            ),
        )

    upgraded = SqliteTrendRepository(str(db_path))
    try:
        await upgraded._ensure_schema()
        with sqlite3.connect(db_path) as conn:
            legacy = conn.execute(
                "SELECT status, signals_collected, evidence_contract_version"
                " FROM mission_probe_outcomes WHERE id = 'outcome-legacy'"
            ).fetchone()
            legacy_brief = conn.execute(
                "SELECT decision, evidence_contract_version FROM market_brief_revisions"
                " WHERE id = 'brief-legacy'"
            ).fetchone()
            conn.execute(
                "INSERT INTO mission_probe_outcomes"
                " (id, run_id, platform, connector_surface, status, signals_collected,"
                " queried_keywords, query_fingerprint, note, collection_plan_digest,"
                " evidence_contract_version, completed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "outcome-failed",
                    "run",
                    "threads",
                    "threads.search",
                    "FAILED",
                    0,
                    '["legacy"]',
                    "failed-fingerprint",
                    "connector error",
                    "a" * 64,
                    2,
                    "2026-09-01T00:02:00+00:00",
                ),
            )
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(mission_probe_outcomes)")
            }
            conn.execute(
                "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)",
                ("source", "youtube", "video:legacy"),
            )
            conn.execute(
                "INSERT INTO observations"
                " (id, source_id, observed_at, time_provenance, identity_source, observed_title)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "observation",
                    "source",
                    "2026-09-01T00:03:00+00:00",
                    "exact_ingestion",
                    "metadata_external_id",
                    "Contradicting evidence",
                ),
            )
            conn.execute(
                "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                " VALUES (?, ?, ?, ?)",
                (
                    "evidence",
                    "mission",
                    "observation",
                    "2026-09-01T00:03:00+00:00",
                ),
            )
            conn.execute(
                "INSERT INTO mission_evidence_qualifications"
                " (id, mission_id, observation_id, frame_fingerprint, relation, purpose,"
                " confidence, reason_code, judged_by, hypothesis_target, evidence_role,"
                " evidence_contract_version, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "qualification",
                    "mission",
                    "observation",
                    "frame",
                    "QUALIFIED_CONTRADICTION",
                    "VOC",
                    0.8,
                    "DIRECT_TO_FRAME",
                    "contract-test",
                    "core",
                    "CONTRADICTION",
                    2,
                    "2026-09-01T00:04:00+00:00",
                ),
            )
            foreign_key_failures = conn.execute("PRAGMA foreign_key_check").fetchall()

        assert legacy == ("HEALTHY", 1, 1)
        assert legacy_brief == ("Decide whether to continue", 1)
        assert {
            "scope_attestation",
            "note",
            "collection_plan_digest",
            "evidence_contract_version",
        } <= columns
        assert foreign_key_failures == []
    finally:
        await upgraded.close()
