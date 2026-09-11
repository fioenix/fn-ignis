import asyncio
import json
import logging
import math
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.resources import sql_seed_file
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
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
                first_seen_at TEXT NOT NULL,
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
        if not signals:
            return 0
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                inserted = 0
                for s in signals:
                    plat = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
                    geo = s.geo_code.value if hasattr(s.geo_code, "value") else str(s.geo_code)
                    c_id = str(s.cluster_id) if s.cluster_id else None
                    m_id = str(s.mission_id) if s.mission_id else None
                    meta_json = json.dumps(s.metadata or {}, ensure_ascii=False)
                    cap_at = s.captured_at.isoformat() if s.captured_at else datetime.now(timezone.utc).isoformat()
                    pub_at = s.published_at.isoformat() if s.published_at else None
                    url = s.source_url.strip() if s.source_url else ""

                    existing_id = None
                    if url:
                        # Title is part of the identity: a feed-level URL is shared by every item
                        # it lists, so matching on the URL alone overwrote unrelated signals.
                        cur.execute(
                            "SELECT id FROM trend_signals WHERE platform = ? AND source_url = ? "
                            "AND raw_title = ? ORDER BY captured_at DESC LIMIT 1;",
                            (plat, url, s.raw_title),
                        )
                        found = cur.fetchone()
                        if found:
                            existing_id = found["id"] if isinstance(found, dict) or hasattr(found, "keys") else found[0]

                    if existing_id:
                        s_id = existing_id
                        cur.execute(
                            """
                            UPDATE trend_signals 
                            SET metric_value = ?, growth_velocity = ?, raw_title = ?, metadata = ?, captured_at = ?,
                                published_at = COALESCE(?, published_at), cluster_id = COALESCE(?, cluster_id)
                            WHERE id = ?;
                            """,
                            (s.metric_value, s.growth_velocity, s.raw_title, meta_json, cap_at, pub_at, c_id, s_id),
                        )
                    else:
                        s_id = str(uuid4())
                        cur.execute(
                            """
                            INSERT INTO trend_signals 
                            (id, platform, raw_title, metric_value, growth_velocity, source_url, geo_code, cluster_id, mission_id, metadata, captured_at, published_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (s_id, plat, s.raw_title, s.metric_value, s.growth_velocity, url or None, geo, c_id, m_id, meta_json, cap_at, pub_at),
                        )
                        inserted += 1

                    cur.execute(
                        """
                        INSERT INTO signal_metrics (signal_id, captured_at, metric_value, growth_velocity)
                        VALUES (?, ?, ?, ?);
                        """,
                        (s_id, cap_at, s.metric_value, s.growth_velocity),
                    )
                self._record_observations(cur, signals)

                conn.commit()
                return inserted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_save)

    async def prune_empty_clusters(self) -> int:
        """Remove clusters left holding no signals after re-clustering."""
        await self._ensure_schema()

        def _sync_prune():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM topic_clusters
                    WHERE id NOT IN (
                        SELECT DISTINCT cluster_id FROM trend_signals WHERE cluster_id IS NOT NULL
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
                    first_seen = c.first_seen_at.isoformat() if c.first_seen_at else now_str
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
                query = f"""
                    WITH ranked_clusters AS (
                        SELECT 
                            tc.id,
                            tc.canonical_name,
                            tc.topic_label,
                            tc.summary_text,
                            tc.category,
                            tc.cross_platform_score,
                            tc.first_seen_at,
                            tc.last_updated_at,
                            COUNT(ts.id) AS sig_count,
                            COUNT(DISTINCT ts.platform) AS plat_count,
                            COALESCE(SUM(ts.metric_value), 0.0) AS total_metric,
                            COALESCE(AVG(ts.growth_velocity), 0.0) AS avg_velocity
                        FROM topic_clusters tc
                        INNER JOIN trend_signals ts ON ts.cluster_id = tc.id
                        WHERE datetime(ts.captured_at) >= datetime('now', '{interval_modifier}')
                        GROUP BY tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category, tc.cross_platform_score, tc.first_seen_at, tc.last_updated_at
                        ORDER BY sig_count DESC
                        LIMIT ?
                    )
                    SELECT 
                        rc.id,
                        rc.canonical_name,
                        rc.topic_label,
                        rc.summary_text,
                        rc.category,
                        rc.cross_platform_score,
                        rc.first_seen_at,
                        rc.last_updated_at,
                        rc.sig_count,
                        rc.plat_count,
                        rc.total_metric,
                        rc.avg_velocity
                    FROM ranked_clusters rc;
                """
                cur.execute(query, (limit,))
                rows = cur.fetchall()

                clusters: List[TopicCluster] = []
                for row in rows:
                    c_id = row["id"]
                    first_seen = datetime.fromisoformat(row["first_seen_at"]) if row["first_seen_at"] else datetime.now(timezone.utc)
                    last_updated = datetime.fromisoformat(row["last_updated_at"]) if row["last_updated_at"] else datetime.now(timezone.utc)

                    # Fetch signals captured within the timeframe window for this cluster
                    sig_query = f"""
                        SELECT platform, raw_title, metric_value, growth_velocity, source_url, geo_code, metadata, captured_at, published_at
                        FROM trend_signals
                        WHERE cluster_id = ? AND datetime(captured_at) >= datetime('now', '{interval_modifier}')
                        ORDER BY captured_at DESC;
                    """
                    cur.execute(sig_query, (c_id,))
                    sig_rows = cur.fetchall()

                    signals_list: List[TrendSignal] = []
                    for sr in sig_rows:
                        meta = json.loads(sr["metadata"]) if sr["metadata"] else {}
                        cap_at = datetime.fromisoformat(sr["captured_at"]) if sr["captured_at"] else datetime.now(timezone.utc)
                        pub_at = datetime.fromisoformat(sr["published_at"]) if sr["published_at"] else None
                        signals_list.append(
                            TrendSignal(
                                platform=PlatformType(sr["platform"]),
                                raw_title=sr["raw_title"],
                                metric_value=sr["metric_value"],
                                growth_velocity=sr["growth_velocity"],
                                source_url=sr["source_url"],
                                geo_code=GeoCode(sr["geo_code"]),
                                cluster_id=UUID(c_id),
                                metadata=meta,
                                captured_at=cap_at,
                                published_at=pub_at,
                            )
                        )

                    # Calculate dynamic cross-platform score matching SemanticClusterer equation
                    plat_count = row["plat_count"]
                    total_metric = row["total_metric"]
                    avg_velocity = row["avg_velocity"]

                    platform_diversity_score = (plat_count / 5.0) * 40.0
                    metric_score = min(40.0, (math.log10(max(1.0, total_metric + 1.0)) / 8.0) * 40.0)
                    velocity_score = min(20.0, (math.log10(max(1.0, avg_velocity + 1.0)) / 4.0) * 20.0)
                    dynamic_score = round(min(100.0, platform_diversity_score + metric_score + velocity_score), 1)

                    persisted_score = row["cross_platform_score"]
                    final_score = persisted_score if (persisted_score is not None and persisted_score > 0) else dynamic_score

                    plat_cnt = len({s.platform for s in signals_list})
                    dynamic_summary = f"Aggregated topic from {len(signals_list)} signals across {plat_cnt} platforms."
                    clusters.append(
                        TopicCluster(
                            id=UUID(c_id),
                            canonical_name=row["canonical_name"],
                            _topic_label=row["topic_label"],
                            cross_platform_score=final_score,
                            summary_text=dynamic_summary,
                            category=row["category"] or "unclassified",
                            first_seen_at=first_seen,
                            last_updated_at=last_updated,
                            signals=signals_list,
                        )
                    )

                # Sort by dynamic cross platform score descending
                clusters.sort(key=lambda c: (c.cross_platform_score, len(c.signals)), reverse=True)
                return clusters
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
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
                cur.execute(
                    f"""
                    SELECT platform, raw_title, metric_value, growth_velocity, source_url, geo_code, cluster_id, mission_id, metadata, captured_at, published_at
                    FROM trend_signals
                    WHERE cluster_id = ? AND datetime(captured_at) >= datetime('now', '{interval_modifier}')
                    ORDER BY captured_at DESC
                    """,
                    (str(cluster_id),)
                )
                rows = cur.fetchall()
                signals: List[TrendSignal] = []
                seen_urls = set()
                for r in rows:
                    url = r["source_url"]
                    if url:
                        plat = r["platform"]
                        key = (plat, url)
                        if key in seen_urls:
                            continue
                        seen_urls.add(key)
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                    cap_at = datetime.fromisoformat(r["captured_at"]) if r["captured_at"] else datetime.now(timezone.utc)
                    pub_at = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
                    signals.append(
                        TrendSignal(
                            platform=PlatformType(r["platform"]),
                            raw_title=r["raw_title"],
                            metric_value=r["metric_value"],
                            growth_velocity=r["growth_velocity"],
                            source_url=r["source_url"],
                            geo_code=GeoCode(r["geo_code"]),
                            cluster_id=UUID(r["cluster_id"]) if r["cluster_id"] else None,
                            mission_id=UUID(r["mission_id"]) if r["mission_id"] else None,
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
                    " o.published_at, o.cluster_id"
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
                    cap_at = datetime.fromisoformat(r["observed_at"]) if r["observed_at"] else datetime.now(timezone.utc)
                    pub_at = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
                    signals.append(
                        TrendSignal(
                            platform=PlatformType(r["platform"]),
                            raw_title=r["observed_title"],
                            metric_value=r["metric_value"],
                            growth_velocity=r["growth_velocity"],
                            source_url=r["source_url"],
                            geo_code=GeoCode(r["geo_code"]),
                            mission_id=UUID(r["mission_id"]) if r["mission_id"] else None,
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

