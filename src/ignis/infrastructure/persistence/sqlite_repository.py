import asyncio
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.resources import sql_seed_file
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.cross_platform_score import cross_platform_score
from ignis.domain.source_identity import resolve_source_identity
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe, resolve_geo, resolve_timeframe

from ignis.infrastructure.auth.crypto import decrypt_credentials, encrypt_credentials

logger = logging.getLogger(__name__)


class SqliteTrendRepository(ITrendRepository):
    """
    Lightweight, zero-dependency SQLite repository adapter for fn-ignis.
    Supports file-based SQLite databases (sqlite:///path/to/db.sqlite) and in-memory databases (sqlite:///:memory:).
    All queries run in thread pool executors to maintain 100% async non-blocking execution.
    """

    def __init__(self, db_path: str = "sqlite:///ignis.db"):
        clean_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        self._db_path = clean_path if clean_path else "ignis.db"
        self._initialized = False
        self._lock = asyncio.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row

    async def close(self) -> None:
        """Close SQLite connection if in-memory."""
        if self._mem_conn is not None:
            self._mem_conn.close()
            self._mem_conn = None

    def _get_connection(self) -> sqlite3.Connection:

        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # SQLite defaults foreign keys off per connection, which would make every REFERENCES
        # clause in the schema decoration: ON DELETE SET NULL would never fire and a dangling
        # source_id would insert cleanly. Only the three tables from sql/016 declare any.
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return
        async with self._lock:
            if not self._initialized:
                await asyncio.to_thread(self._create_tables_and_seed)
                self._initialized = True

    def _create_tables_and_seed(self) -> None:
        if self._db_path != ":memory:":
            p = Path(self._db_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS trend_signals (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                raw_title TEXT NOT NULL,
                metric_value REAL NOT NULL,
                growth_velocity REAL DEFAULT 0.0,
                source_url TEXT,
                geo_code TEXT DEFAULT 'VN',
                cluster_id TEXT,
                mission_id TEXT,
                metadata TEXT,
                captured_at TEXT NOT NULL,
                published_at TEXT
            );

            CREATE TABLE IF NOT EXISTS signal_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                metric_value REAL DEFAULT 0.0,
                growth_velocity REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_signal_metrics_sig ON signal_metrics (signal_id, captured_at DESC);

            -- The three entities sql/016_source_observation_model.sql creates on Postgres.
            -- SQLite does not read the sql/ files, so the same constraints are restated here;
            -- a backend that only agrees on column names is not the same contract.
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                -- "<kind>:<value>", so that a TikTok hashtag named "12345" and item 12345 stay
                -- two objects. See the migration header for why the namespace is inside the key.
                external_id TEXT NOT NULL,
                -- Three columns only. A URL, a resolution route and a first/last seen range
                -- are all facts about a sighting, so they live on observations; see the header
                -- of sql/016_source_observation_model.sql.
                UNIQUE (platform, external_id)
            );

            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                cluster_id TEXT REFERENCES topic_clusters(id) ON DELETE SET NULL,
                observed_at TEXT,
                published_at TEXT,
                time_provenance TEXT NOT NULL
                    CHECK (time_provenance IN ('exact_ingestion', 'legacy_publish_only', 'unknown')),
                identity_source TEXT NOT NULL
                    CHECK (identity_source IN ('metadata_external_id', 'url_external_id',
                                               'normalized_url_fallback')),
                observed_title TEXT,
                metric_value REAL DEFAULT 0.0,
                growth_velocity REAL DEFAULT 0.0,
                geo_code TEXT DEFAULT 'VN',
                source_url TEXT,
                metadata TEXT,
                CHECK (time_provenance <> 'exact_ingestion' OR observed_at IS NOT NULL)
            );
            CREATE INDEX IF NOT EXISTS idx_observations_source ON observations (source_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_cluster ON observations (cluster_id, observed_at DESC);

            CREATE TABLE IF NOT EXISTS mission_evidence (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
                recorded_at TEXT NOT NULL,
                UNIQUE (mission_id, observation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_mission_evidence_observation ON mission_evidence (observation_id);

            CREATE TABLE IF NOT EXISTS topic_clusters (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
                topic_label TEXT,
                cross_platform_score REAL DEFAULT 0.0,
                summary_text TEXT,
                category TEXT DEFAULT 'general',
                -- Nullable: a cluster built only from observations whose ingestion time was
                -- never recorded has no first sighting to store.
                first_seen_at TEXT,
                last_updated_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS research_missions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                keywords TEXT NOT NULL,
                shortcode TEXT UNIQUE,
                geo_code TEXT DEFAULT 'VN',
                timeframe TEXT DEFAULT '30d',
                status TEXT DEFAULT 'INITIALIZED',
                agent TEXT DEFAULT 'generic',
                session_id TEXT,
                summary TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS platform_credentials (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL UNIQUE,
                auth_type TEXT NOT NULL,
                encrypted_data TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS system_audit_logs (
                id TEXT PRIMARY KEY,
                component TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT DEFAULT 'INFO',
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_lexicons (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                term TEXT NOT NULL,
                category TEXT DEFAULT 'vernacular',
                created_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                UNIQUE(domain, term)
            );

            CREATE TABLE IF NOT EXISTS industry_taxonomies (
                id TEXT PRIMARY KEY,
                industry_code TEXT NOT NULL UNIQUE,
                industry_name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_configs (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'connector',
                description TEXT,
                updated_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # CREATE TABLE IF NOT EXISTS leaves an existing database untouched, so columns added
        # after a user's file was created have to be applied here.
        existing_cluster_columns = {row[1] for row in cur.execute("PRAGMA table_info(topic_clusters)")}
        if "topic_label" not in existing_cluster_columns:
            cur.execute("ALTER TABLE topic_clusters ADD COLUMN topic_label TEXT")

        # SQLite cannot drop a NOT NULL, so relaxing one means rebuilding the table. Only a
        # database created before clusters could be clock-less needs it, which is what the
        # PRAGMA check decides. Foreign keys go off for the swap: dropping the old table would
        # otherwise fire ON DELETE SET NULL and strip the cluster off every observation.
        cluster_info = list(cur.execute("PRAGMA table_info(topic_clusters)"))
        first_seen = next((row for row in cluster_info if row[1] == "first_seen_at"), None)
        if first_seen is not None and first_seen[3] == 1:
            cur.execute("PRAGMA foreign_keys = OFF")
            cur.executescript(
                """
                CREATE TABLE topic_clusters_rebuilt (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL UNIQUE,
                    topic_label TEXT,
                    cross_platform_score REAL DEFAULT 0.0,
                    summary_text TEXT,
                    category TEXT DEFAULT 'general',
                    first_seen_at TEXT,
                    last_updated_at TEXT NOT NULL
                );
                INSERT INTO topic_clusters_rebuilt
                    (id, canonical_name, topic_label, cross_platform_score, summary_text,
                     category, first_seen_at, last_updated_at)
                SELECT id, canonical_name, topic_label, cross_platform_score, summary_text,
                       category, first_seen_at, last_updated_at
                FROM topic_clusters;
                DROP TABLE topic_clusters;
                ALTER TABLE topic_clusters_rebuilt RENAME TO topic_clusters;
                """
            )
            conn.commit()
            cur.execute("PRAGMA foreign_keys = ON")

        existing_signal_columns = {row[1] for row in cur.execute("PRAGMA table_info(trend_signals)")}
        if "published_at" not in existing_signal_columns:
            # captured_at used to hold the publish time for YouTube and the Google Trends feed.
            # New rows keep the two apart; rows already written cannot have their ingestion time
            # recovered, so they are left alone rather than stamped with an invented one.
            cur.execute("ALTER TABLE trend_signals ADD COLUMN published_at TEXT")

        # Seed Initial Lexicons & Configs from SQL files if table is empty
        cur.execute("SELECT COUNT(*) FROM market_lexicons")
        count = cur.fetchone()[0]
        if count == 0:
            now_str = datetime.now(timezone.utc).isoformat()
            for sql_filename in ("003_market_lexicons.sql", "004_global_lexicons.sql"):
                sql_path = sql_seed_file(sql_filename)
                if not sql_path:
                    continue
                content = sql_path.read_text(encoding="utf-8")
                matches = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", content)
                for dom, term, cat in matches:
                    cur.execute(
                        "INSERT OR IGNORE INTO market_lexicons (id, domain, term, category, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid4()), dom, term, cat, "system", now_str),
                    )

        # Refreshed on every bootstrap rather than seeded once. Taxonomies are system-owned --
        # no tool writes them -- so there is no user edit to preserve, and INSERT OR IGNORE meant
        # a database created before a keyword set was widened kept the narrow one forever and
        # classified differently from Postgres.
        tax_path = sql_seed_file("003_market_lexicons.sql")
        if tax_path:
            now_str = datetime.now(timezone.utc).isoformat()
            content = tax_path.read_text(encoding="utf-8")
            tax_matches = re.findall(r"\('([^']+)',\s*'([^']+)',\s*ARRAY\[([^\]]+)\]\)", content)
            for code, name, kw_blob in tax_matches:
                keywords = re.findall(r"'([^']+)'", kw_blob)
                cur.execute(
                    "INSERT INTO industry_taxonomies (id, industry_code, industry_name, keywords, created_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(industry_code) DO UPDATE SET "
                    "industry_name = excluded.industry_name, keywords = excluded.keywords",
                    (str(uuid4()), code, name, json.dumps(keywords, ensure_ascii=False), now_str),
                )

        # System-owned vocabulary that replaced hardcoded Python constants. Unlike the seeds
        # above it is re-applied on every bootstrap: no MCP tool writes these domains, so there
        # is no user edit to preserve, and a database created before a list was widened would
        # otherwise keep the narrow one and behave differently from Postgres.
        now_str = datetime.now(timezone.utc).isoformat()
        for vocab_filename in (
            "012_vocabulary_from_constants.sql",
            "013_tiktok_ui_noise.sql",
            "014_language_detection_vocabulary.sql",
        ):
            vocab_path = sql_seed_file(vocab_filename)
            if not vocab_path:
                continue
            vocab_content = vocab_path.read_text(encoding="utf-8")
            for dom, term, cat in re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", vocab_content):
                cur.execute(
                    "INSERT OR IGNORE INTO market_lexicons (id, domain, term, category, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), dom, term, cat, "system", now_str),
                )

        cur.execute("SELECT COUNT(*) FROM runtime_configs")
        rc_count = cur.fetchone()[0]
        if rc_count == 0:
            rc_path = sql_seed_file("007_runtime_configs.sql")
            if rc_path:
                rc_content = rc_path.read_text(encoding="utf-8")
                rc_matches = re.findall(r"\('([^']+)',\s*'([^']*)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'\)", rc_content)
                now_str = datetime.now(timezone.utc).isoformat()
                for k, v, cat, desc, updater in rc_matches:
                    cur.execute(
                        "INSERT OR IGNORE INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (k, v, cat, desc, updater, now_str, now_str),
                    )

        conn.commit()
        if self._mem_conn is None:
            conn.close()

    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Record each sighting in the source/observation model. Nothing else is written.

        trend_signals and signal_metrics are read-only from here on. They stay in the schema --
        the audit reads them, the backfill reads them, and they are the only record of what the
        corpus looked like before the migration -- but a write to them now would restart the
        divergence the migration closed: the legacy side growing while the new model stands
        still, with nothing linking a row on one side to an observation on the other.
        """
        if not signals:
            return 0
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                recorded = self._record_observations(cur, signals)
                conn.commit()
                return recorded
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_save)

    # One observation per source, the most recent in the window, and only observations whose
    # collection time is known. published_at is not a substitute clock: for the 17,118 legacy
    # observations it says when the content was posted, and a window built on it would report a
    # two-year-old video as something seen this week.
    _LATEST_PER_SOURCE = """
        WITH latest AS (
            SELECT
                o.source_id, o.cluster_id, o.metric_value, o.growth_velocity, o.observed_at,
                o.published_at, o.observed_title, o.geo_code, o.source_url, o.metadata,
                s.platform,
                -- (cluster_id, source_id), not source_id alone: see the Postgres reader.
                ROW_NUMBER() OVER (
                    PARTITION BY o.cluster_id, o.source_id ORDER BY o.observed_at DESC
                ) AS rank
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.cluster_id IS NOT NULL
              AND o.time_provenance = 'exact_ingestion'
              AND o.observed_at IS NOT NULL
              AND o.observed_at >= datetime('now', '{modifier}')
        )
    """

    async def prune_empty_clusters(self) -> int:
        """Remove clusters holding no observation at all.

        Membership, not recency: a cluster whose only observations are legacy ones outside the
        default analysis window still describes something the corpus contains.
        """
        await self._ensure_schema()

        def _sync_prune():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM topic_clusters
                    WHERE id NOT IN (
                        SELECT DISTINCT cluster_id FROM observations WHERE cluster_id IS NOT NULL
                    );
                    """
                )
                removed = cur.rowcount or 0
                conn.commit()
                return removed
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_prune)

    def _record_observations(self, cur, signals: List[TrendSignal]) -> int:
        """Write each signal as one observation of one canonical source.

        The same three properties as the Postgres path, restated here rather than shared, because
        the two backends speak different SQL. What is shared is the part that must never diverge:
        both resolve identity through ignis.domain.source_identity.
        """
        written = 0
        for signal in signals:
            platform = (
                signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
            )
            identity = resolve_source_identity(platform, signal.source_url, signal.metadata)
            if identity is None:
                logger.warning("Signal has no resolvable external identity, skipped: %s", platform)
                continue

            # One statement, not a SELECT then an INSERT: two passes racing on one video would
            # both find nothing and both insert.
            row = cur.execute(
                "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)"
                " ON CONFLICT (platform, external_id) DO UPDATE SET platform = excluded.platform"
                " RETURNING id;",
                (str(uuid4()), identity.platform, identity.external_id),
            ).fetchone()
            source_id = row["id"] if hasattr(row, "keys") else row[0]

            # A live write knows its own collection time, so the clock is exact. Legacy rows
            # carrying a publish time arrive through the backfill, not through here.
            observed_at = (
                signal.captured_at.isoformat()
                if signal.captured_at
                else datetime.now(timezone.utc).isoformat()
            )
            observation_id = str(uuid4())
            cur.execute(
                "INSERT INTO observations (id, source_id, cluster_id, observed_at, published_at,"
                " time_provenance, identity_source, observed_title, metric_value,"
                " growth_velocity, geo_code, source_url, metadata)"
                " VALUES (?, ?, ?, ?, ?, 'exact_ingestion', ?, ?, ?, ?, ?, ?, ?);",
                (
                    observation_id,
                    source_id,
                    str(signal.cluster_id) if signal.cluster_id else None,
                    observed_at,
                    signal.published_at.isoformat() if signal.published_at else None,
                    identity.identity_source,
                    signal.raw_title,
                    signal.metric_value,
                    signal.growth_velocity,
                    signal.geo_code.value
                    if hasattr(signal.geo_code, "value")
                    else str(signal.geo_code),
                    signal.source_url,
                    json.dumps(signal.metadata or {}, ensure_ascii=False),
                ),
            )
            signal.observation_id = UUID(observation_id)
            signal.identity_source = identity.identity_source
            signal.time_provenance = "exact_ingestion"
            written += 1

            if signal.mission_id:
                cur.execute(
                    "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                    (
                        str(uuid4()),
                        str(signal.mission_id),
                        observation_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        return written

    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        if not clusters:
            return
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                for c in clusters:
                    c_id = str(c.id)
                    now_str = datetime.now(timezone.utc).isoformat()
                    first_seen = c.first_seen_at.isoformat() if c.first_seen_at else None
                    last_updated = c.last_updated_at.isoformat() if c.last_updated_at else now_str

                    # An upsert, not INSERT OR REPLACE. REPLACE is a DELETE followed by an
                    # INSERT, so with foreign keys enforced it fires ON DELETE SET NULL on every
                    # observation already pointing at this cluster -- re-saving a cluster would
                    # quietly erase the membership history it exists to accumulate.
                    cur.execute(
                        """
                        INSERT INTO topic_clusters
                        (id, canonical_name, topic_label, cross_platform_score, summary_text, category, first_seen_at, last_updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            canonical_name = excluded.canonical_name,
                            topic_label = excluded.topic_label,
                            cross_platform_score = excluded.cross_platform_score,
                            summary_text = excluded.summary_text,
                            category = excluded.category,
                            last_updated_at = excluded.last_updated_at
                        """,
                        (c_id, c.canonical_name, c.topic_label, c.cross_platform_score, c.summary_text, c.category, first_seen, last_updated)
                    )

                    # Assign the cluster in memory and stop there. This used to insert every
                    # signal under a fresh uuid4, which made save_clusters a second write path:
                    # one external source became two rows, and the contract test measured it.
                    # save_signals is the only place a signal is written, and the pipeline calls
                    # this first so the cluster exists before an observation references it.
                    for s in c.signals:
                        s.cluster_id = c.id
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await asyncio.to_thread(_sync_save)

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        """Rank clusters by what was observed in the window, from the new model only."""
        await self._ensure_schema()

        interval_map = {
            Timeframe.LAST_24H: "-24 hours",
            Timeframe.LAST_7D: "-7 days",
            Timeframe.LAST_30D: "-30 days",
        }
        interval_modifier = interval_map.get(timeframe, "-24 hours")

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute(
                    f"""
                    {self._LATEST_PER_SOURCE.format(modifier=interval_modifier)}
                    SELECT
                        tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                        tc.first_seen_at, tc.last_updated_at,
                        l.platform, l.observed_title, l.metric_value, l.growth_velocity,
                        l.source_url, l.geo_code, l.metadata, l.observed_at, l.published_at
                    FROM latest l
                    JOIN topic_clusters tc ON tc.id = l.cluster_id
                    WHERE l.rank = 1
                    """
                ).fetchall()
            finally:
                if self._mem_conn is None:
                    conn.close()

            grouped: Dict[str, List[Any]] = {}
            for row in rows:
                grouped.setdefault(row["id"], []).append(row)

            clusters: List[TopicCluster] = []
            for cluster_id, cluster_rows in grouped.items():
                head = cluster_rows[0]
                signals = [
                    self._signal_from_observation(row, UUID(cluster_id)) for row in cluster_rows
                ]
                # Scored by the same function the clusterer uses, from one observation per
                # source. The arithmetic used to be restated in this query.
                score = cross_platform_score(
                    distinct_platforms=len({s.platform for s in signals}),
                    total_metric=sum(s.metric_value for s in signals),
                    average_velocity=sum(s.growth_velocity for s in signals) / len(signals),
                )
                cluster = TopicCluster(
                    id=UUID(cluster_id),
                    canonical_name=head["canonical_name"],
                    summary_text=head["summary_text"]
                    or f"{len(signals)} sources across"
                    f" {len({s.platform for s in signals})} platforms.",
                    category=head["category"] or "general",
                    cross_platform_score=score,
                    signals=signals,
                    first_seen_at=datetime.fromisoformat(head["first_seen_at"])
                    if head["first_seen_at"]
                    else None,
                    last_updated_at=datetime.fromisoformat(head["last_updated_at"])
                    if head["last_updated_at"]
                    else datetime.now(timezone.utc),
                )
                cluster.topic_label = head["topic_label"]
                clusters.append(cluster)

            clusters.sort(key=lambda c: (c.cross_platform_score, len(c.signals)), reverse=True)
            return clusters[:limit]

        return await asyncio.to_thread(_sync_get)

    @staticmethod
    def _signal_from_observation(row, cluster_id: UUID) -> TrendSignal:
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (TypeError, ValueError):
            metadata = {}
        return TrendSignal(
            platform=PlatformType(row["platform"]),
            raw_title=row["observed_title"] or "",
            metric_value=float(row["metric_value"] or 0.0),
            growth_velocity=float(row["growth_velocity"] or 0.0),
            source_url=row["source_url"],
            geo_code=GeoCode(row["geo_code"] or "VN"),
            cluster_id=cluster_id,
            metadata=metadata,
            captured_at=datetime.fromisoformat(row["observed_at"]) if row["observed_at"] else None,
            published_at=datetime.fromisoformat(row["published_at"])
            if row["published_at"]
            else None,
        )

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
        """One signal per source, the most recent observation of it in the window.

        Deduplication is on source_id, not on the URL: the corpus holds one source seen under
        two URL variants, and a feed-level URL shared by many items.
        """
        await self._ensure_schema()

        interval_map = {
            Timeframe.LAST_24H: "-24 hours",
            Timeframe.LAST_7D: "-7 days",
            Timeframe.LAST_30D: "-30 days",
        }
        interval_modifier = interval_map.get(timeframe, "-7 days")

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute(
                    f"""
                    {self._LATEST_PER_SOURCE.format(modifier=interval_modifier)}
                    SELECT * FROM latest WHERE rank = 1 AND cluster_id = ?
                    ORDER BY observed_at ASC
                    """,
                    (str(cluster_id),),
                ).fetchall()
            finally:
                if self._mem_conn is None:
                    conn.close()
            return [self._signal_from_observation(row, cluster_id) for row in rows]

        return await asyncio.to_thread(_sync_get)

    async def create_mission(self, mission: ResearchMission) -> ResearchMission:

        return await self.save_mission(mission)

    async def save_mission(self, mission: ResearchMission) -> ResearchMission:
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                m_id = str(mission.id)
                kw_json = json.dumps(mission.keywords, ensure_ascii=False)
                geo = mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code)
                tf = mission.timeframe.value if hasattr(mission.timeframe, "value") else str(mission.timeframe)
                now_str = datetime.now(timezone.utc).isoformat()
                c_at = mission.created_at.isoformat() if mission.created_at else now_str

                # An upsert, not INSERT OR REPLACE. REPLACE deletes the row first, and
                # mission_evidence cascades on that delete: every status update would have
                # thrown away the evidence the mission had just recorded.
                cur.execute(
                    """
                    INSERT INTO research_missions
                    (id, title, keywords, shortcode, geo_code, timeframe, status, agent, session_id, summary, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        title = excluded.title,
                        keywords = excluded.keywords,
                        shortcode = excluded.shortcode,
                        geo_code = excluded.geo_code,
                        timeframe = excluded.timeframe,
                        status = excluded.status,
                        agent = excluded.agent,
                        session_id = excluded.session_id,
                        summary = excluded.summary,
                        updated_at = excluded.updated_at
                    """,
                    (m_id, mission.title, kw_json, mission.shortcode, geo, tf, mission.status, mission.agent, mission.session_id, mission.summary, c_at, now_str)
                )
                conn.commit()
                return mission
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_save)

    async def get_mission(self, mission_id: UUID) -> Optional[ResearchMission]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title, keywords, shortcode, geo_code, timeframe, status, agent, session_id, summary, created_at, updated_at FROM research_missions WHERE id = ? OR shortcode = ?",
                    (str(mission_id), str(mission_id))
                )
                r = cur.fetchone()
                if not r:
                    return None
                kws = json.loads(r["keywords"]) if r["keywords"] else []
                c_at = datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(timezone.utc)
                u_at = datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else None

                return ResearchMission(
                    id=UUID(r["id"]),
                    title=r["title"],
                    keywords=kws,
                    shortcode=r["shortcode"],
                    geo_code=resolve_geo(r["geo_code"]),
                    timeframe=resolve_timeframe(r["timeframe"]),
                    status=r["status"],
                    agent=r["agent"],
                    session_id=r["session_id"],
                    summary=r["summary"],
                    created_at=c_at,
                    updated_at=u_at,
                )
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def update_mission(self, mission: ResearchMission) -> None:
        await self.save_mission(mission)

    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title, keywords, shortcode, geo_code, timeframe, status, agent, session_id, summary, created_at, updated_at FROM research_missions ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                rows = cur.fetchall()
                missions: List[ResearchMission] = []
                for r in rows:
                    kws = json.loads(r["keywords"]) if r["keywords"] else []
                    c_at = datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(timezone.utc)
                    missions.append(
                        ResearchMission(
                            id=UUID(r["id"]),
                            title=r["title"],
                            keywords=kws,
                            shortcode=r["shortcode"],
                            geo_code=resolve_geo(r["geo_code"]),
                            timeframe=resolve_timeframe(r["timeframe"]),
                            status=r["status"],
                            agent=r["agent"],
                            session_id=r["session_id"],
                            summary=r["summary"],
                            created_at=c_at,
                        )
                    )
                return missions

            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # mission_evidence -> observations -> sources. The legacy mission_id column
                # held one mission per source, so whichever mission wrote last owned the row.
                cur.execute(
                    "SELECT s.platform, o.observed_title, o.metric_value, o.growth_velocity,"
                    " o.source_url, o.geo_code, e.mission_id, o.metadata, o.observed_at,"
                    " o.published_at, o.cluster_id, o.id AS observation_id, o.identity_source,"
                    " o.time_provenance"
                    " FROM mission_evidence e"
                    " JOIN observations o ON o.id = e.observation_id"
                    " JOIN sources s ON s.id = o.source_id"
                    " WHERE e.mission_id = ? ORDER BY o.observed_at DESC",
                    (str(mission_id),)
                )
                rows = cur.fetchall()
                signals: List[TrendSignal] = []
                for r in rows:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                    # No substitute clock. A NULL observed_at means the collection time was
                    # never recorded, and datetime.now() here would have turned every one of
                    # the 17,118 legacy observations into "collected when you ran the query".
                    cap_at = (
                        datetime.fromisoformat(r["observed_at"]) if r["observed_at"] else None
                    )
                    pub_at = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
                    signals.append(
                        TrendSignal(
                            platform=PlatformType(r["platform"]),
                            raw_title=r["observed_title"],
                            metric_value=r["metric_value"],
                            growth_velocity=r["growth_velocity"],
                            source_url=r["source_url"],
                            geo_code=GeoCode(r["geo_code"]),
                            cluster_id=UUID(r["cluster_id"]) if r["cluster_id"] else None,
                            mission_id=UUID(r["mission_id"]) if r["mission_id"] else None,
                            observation_id=UUID(r["observation_id"]),
                            identity_source=r["identity_source"],
                            time_provenance=r["time_provenance"],
                            metadata=meta,
                            captured_at=cap_at,
                            published_at=pub_at,
                        )
                    )

                return signals
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def assign_observation_clusters(self, signals: List[TrendSignal]) -> int:
        """Set the cluster on observations already written. See the Postgres docstring."""
        updates = [
            (str(s.cluster_id), str(s.observation_id))
            for s in signals
            if s.observation_id and s.cluster_id
        ]
        if not updates:
            return 0
        await self._ensure_schema()

        def _sync_assign():
            conn = self._get_connection()
            try:
                conn.executemany("UPDATE observations SET cluster_id = ? WHERE id = ?", updates)
                conn.commit()
                return len(updates)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_assign)

    async def attach_mission_evidence(self, mission_id: UUID, signals: List[TrendSignal]) -> int:
        """Record that a mission used observations that already exist. See Postgres."""
        rows = [
            (str(uuid4()), str(mission_id), str(s.observation_id),
             datetime.now(timezone.utc).isoformat())
            for s in signals
            if s.observation_id
        ]
        if not rows:
            return 0
        await self._ensure_schema()

        def _sync_attach():
            conn = self._get_connection()
            try:
                conn.executemany(
                    "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (mission_id, observation_id) DO NOTHING",
                    rows,
                )
                conn.commit()
                return len(rows)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_attach)

    async def delete_mission_signals(self, mission_id: UUID) -> int:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # Only the mission's claims. A source and its observations are shared with
                # every other mission that observed them, and the cluster history is built on
                # those observations.
                cur.execute("DELETE FROM mission_evidence WHERE mission_id = ?", (str(mission_id),))
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_del)

    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._ensure_schema()

        from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, sanitize_pii_data

        def _sync_log():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                log_id = str(uuid4())
                clean_msg = sanitize_pii_text(message)
                clean_details = sanitize_pii_data(details or {})
                details_json = json.dumps(clean_details, ensure_ascii=False)
                now_str = datetime.now(timezone.utc).isoformat()

                cur.execute(
                    "INSERT INTO system_audit_logs (id, component, event_type, message, level, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (log_id, component, event_type, clean_msg, level, details_json, now_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await asyncio.to_thread(_sync_log)

    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                query = "SELECT id, component, event_type, message, level, details, created_at FROM system_audit_logs WHERE 1=1"
                params = []
                if level:
                    query += " AND level = ?"
                    params.append(level)
                if component:
                    query += " AND component = ?"
                    params.append(component)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                logs = []
                for r in rows:
                    details = json.loads(r["details"]) if r["details"] else {}
                    logs.append({
                        "id": r["id"],
                        "component": r["component"],
                        "event_type": r["event_type"],
                        "message": r["message"],
                        "level": r["level"],
                        "details": details,
                        "created_at": r["created_at"],
                    })
                return logs
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def save_platform_credentials(
        self,
        platform: str,
        auth_type: str,
        credentials_data: Dict[str, Any],
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
    ) -> None:
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                encrypted = encrypt_credentials(credentials_data)
                encrypted_str = json.dumps(encrypted, ensure_ascii=False)
                cred_id = str(uuid4())
                now_str = datetime.now(timezone.utc).isoformat()
                exp_str = expires_at.isoformat() if expires_at else None

                cur.execute(
                    """
                    INSERT INTO platform_credentials (id, platform, auth_type, encrypted_data, is_active, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform) DO UPDATE SET
                        auth_type = excluded.auth_type,
                        encrypted_data = excluded.encrypted_data,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (cred_id, platform, auth_type, encrypted_str, 1 if is_active else 0, now_str, now_str, exp_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await asyncio.to_thread(_sync_save)

    async def get_platform_credentials(self, platform: str) -> Optional[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, platform, auth_type, encrypted_data, is_active, created_at, updated_at, expires_at FROM platform_credentials WHERE platform = ? AND is_active = 1",
                    (platform,),
                )
                r = cur.fetchone()
                if not r:
                    return None
                enc_data = json.loads(r["encrypted_data"]) if r["encrypted_data"] else {}
                decrypted = decrypt_credentials(enc_data)
                return {
                    "id": r["id"],
                    "platform": r["platform"],
                    "auth_type": r["auth_type"],
                    "credentials_data": decrypted,
                    "credentials": decrypted,
                    "is_active": bool(r["is_active"]),
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "expires_at": r["expires_at"],
                }


            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def list_platform_credentials(self) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, platform, auth_type, is_active, created_at, updated_at, expires_at FROM platform_credentials")
                rows = cur.fetchall()
                creds = []
                for r in rows:
                    creds.append({
                        "id": r["id"],
                        "platform": r["platform"],
                        "auth_type": r["auth_type"],
                        "is_active": bool(r["is_active"]),
                        "created_at": r["created_at"],
                        "updated_at": r["updated_at"],
                        "expires_at": r["expires_at"],
                    })
                return creds
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def delete_platform_credentials(self, platform: str) -> bool:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM platform_credentials WHERE platform = ?", (platform,))
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_del)

    async def get_domain_lexicons(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if domain:
                    cur.execute("SELECT domain, term, category, created_by, created_at FROM market_lexicons WHERE domain = ? ORDER BY domain, term", (domain,))
                else:
                    cur.execute("SELECT domain, term, category, created_by, created_at FROM market_lexicons ORDER BY domain, term")
                rows = cur.fetchall()
                lexicons = []
                for r in rows:
                    lexicons.append({
                        "domain": r["domain"],
                        "term": r["term"],
                        "category": r["category"],
                        "created_by": r["created_by"],
                        "created_at": r["created_at"],
                    })
                return lexicons
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def register_lexicon_terms(
        self,
        domain: str,
        terms: List[str],
        category: str = "vernacular",
        created_by: str = "agent",
    ) -> int:
        if not terms:
            return 0
        await self._ensure_schema()

        def _sync_reg():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                inserted = 0
                now_str = datetime.now(timezone.utc).isoformat()
                for term in terms:
                    clean_term = term.strip().lower()
                    if not clean_term:
                        continue
                    cur.execute(
                        """
                        INSERT INTO market_lexicons (id, domain, term, category, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(domain, term) DO UPDATE SET
                            category = excluded.category,
                            created_by = excluded.created_by
                        """,
                        (str(uuid4()), domain.strip().lower(), clean_term, category, created_by, now_str),
                    )
                    inserted += 1
                conn.commit()
                return inserted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_reg)

    async def get_industry_taxonomies(self) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT industry_code, industry_name, keywords, created_at FROM industry_taxonomies")
                rows = cur.fetchall()
                taxonomies = []
                for r in rows:
                    kws = json.loads(r["keywords"]) if r["keywords"] else []
                    taxonomies.append({
                        "industry_code": r["industry_code"],
                        "industry_name": r["industry_name"],
                        "keywords": kws,
                        "created_at": r["created_at"],
                    })
                return taxonomies
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_runtime_config(self, key: str) -> Optional[str]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT value FROM runtime_configs WHERE key = ?", (key,))
                row = cur.fetchone()
                return str(row["value"]) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_all_runtime_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get_all():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if category:
                    cur.execute(
                        "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs WHERE category = ? ORDER BY key ASC",
                        (category,),
                    )
                else:
                    cur.execute(
                        "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs ORDER BY category ASC, key ASC"
                    )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get_all)

    async def set_runtime_config(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        await self._ensure_schema()

        def _sync_set():
            conn = self._get_connection()
            try:
                now_str = datetime.now(timezone.utc).isoformat()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = COALESCE(excluded.category, runtime_configs.category),
                        description = COALESCE(excluded.description, runtime_configs.description),
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (key, str(value), category, description, updated_by, now_str, now_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await asyncio.to_thread(_sync_set)

    async def delete_runtime_config(self, key: str) -> bool:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM runtime_configs WHERE key = ?", (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_del)

