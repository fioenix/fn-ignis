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
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
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
                captured_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS signal_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                metric_value REAL DEFAULT 0.0,
                growth_velocity REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_signal_metrics_sig ON signal_metrics (signal_id, captured_at DESC);

            CREATE TABLE IF NOT EXISTS topic_clusters (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
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

        # Seed Initial Lexicons & Configs from SQL files if table is empty
        cur.execute("SELECT COUNT(*) FROM market_lexicons")
        count = cur.fetchone()[0]
        if count == 0:
            now_str = datetime.now(timezone.utc).isoformat()
            sql_dir = Path(__file__).resolve().parents[4] / "sql"
            if sql_dir.exists():
                for sql_filename in ("003_market_lexicons.sql", "004_global_lexicons.sql"):
                    sql_path = sql_dir / sql_filename
                    if sql_path.exists():
                        content = sql_path.read_text(encoding="utf-8")
                        matches = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", content)
                        for dom, term, cat in matches:
                            cur.execute(
                                "INSERT OR IGNORE INTO market_lexicons (id, domain, term, category, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                                (str(uuid4()), dom, term, cat, "system", now_str),
                            )

        cur.execute("SELECT COUNT(*) FROM runtime_configs")
        rc_count = cur.fetchone()[0]
        if rc_count == 0:
            sql_dir = Path(__file__).resolve().parents[4] / "sql"
            if sql_dir.exists():
                rc_path = sql_dir / "007_runtime_configs.sql"
                if rc_path.exists():
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
                    url = s.source_url.strip() if s.source_url else ""

                    existing_id = None
                    if url:
                        cur.execute(
                            "SELECT id FROM trend_signals WHERE platform = ? AND source_url = ? ORDER BY captured_at DESC LIMIT 1;",
                            (plat, url),
                        )
                        found = cur.fetchone()
                        if found:
                            existing_id = found["id"] if isinstance(found, dict) or hasattr(found, "keys") else found[0]

                    if existing_id:
                        s_id = existing_id
                        cur.execute(
                            """
                            UPDATE trend_signals 
                            SET metric_value = ?, growth_velocity = ?, raw_title = ?, metadata = ?, captured_at = ?, cluster_id = COALESCE(?, cluster_id)
                            WHERE id = ?;
                            """,
                            (s.metric_value, s.growth_velocity, s.raw_title, meta_json, cap_at, c_id, s_id),
                        )
                    else:
                        s_id = str(uuid4())
                        cur.execute(
                            """
                            INSERT INTO trend_signals 
                            (id, platform, raw_title, metric_value, growth_velocity, source_url, geo_code, cluster_id, mission_id, metadata, captured_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (s_id, plat, s.raw_title, s.metric_value, s.growth_velocity, url or None, geo, c_id, m_id, meta_json, cap_at),
                        )
                        inserted += 1

                    cur.execute(
                        """
                        INSERT INTO signal_metrics (signal_id, captured_at, metric_value, growth_velocity)
                        VALUES (?, ?, ?, ?);
                        """,
                        (s_id, cap_at, s.metric_value, s.growth_velocity),
                    )
                conn.commit()
                return inserted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_save)

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

                    cur.execute(
                        """
                        INSERT OR REPLACE INTO topic_clusters
                        (id, canonical_name, cross_platform_score, summary_text, category, first_seen_at, last_updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (c_id, c.canonical_name, c.cross_platform_score, c.summary_text, c.category, first_seen, last_updated)
                    )

                    for s in c.signals:
                        s_id = str(uuid4())
                        plat = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
                        geo = s.geo_code.value if hasattr(s.geo_code, "value") else str(s.geo_code)
                        m_id = str(s.mission_id) if s.mission_id else None
                        meta_json = json.dumps(s.metadata or {}, ensure_ascii=False)
                        cap_at = s.captured_at.isoformat() if s.captured_at else now_str

                        cur.execute(
                            """
                            INSERT OR REPLACE INTO trend_signals
                            (id, platform, raw_title, metric_value, growth_velocity, source_url, geo_code, cluster_id, mission_id, metadata, captured_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (s_id, plat, s.raw_title, s.metric_value, s.growth_velocity, s.source_url, geo, c_id, m_id, meta_json, cap_at)
                        )
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
                        GROUP BY tc.id, tc.canonical_name, tc.summary_text, tc.category, tc.cross_platform_score, tc.first_seen_at, tc.last_updated_at
                        ORDER BY sig_count DESC
                        LIMIT ?
                    )
                    SELECT 
                        rc.id,
                        rc.canonical_name,
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
                        SELECT platform, raw_title, metric_value, growth_velocity, source_url, geo_code, metadata, captured_at
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
                            )
                        )

                    # Calculate dynamic cross-platform score matching SemanticClusterer equation
                    plat_count = row["plat_count"]
                    total_metric = row["total_metric"]
                    avg_velocity = row["avg_velocity"]
                    sig_count = row["sig_count"]

                    platform_diversity_score = (plat_count / 5.0) * 35.0
                    metric_score = min(35.0, (math.log10(max(1.0, total_metric + 1.0)) / 10.0) * 35.0)
                    velocity_score = min(20.0, (math.log10(max(1.0, avg_velocity + 1.0)) / 5.0) * 20.0)
                    volume_score = min(10.0, (math.log10(max(1.0, float(sig_count) + 1.0)) / 3.0) * 10.0)
                    dynamic_score = round(min(100.0, platform_diversity_score + metric_score + velocity_score + volume_score), 1)

                    persisted_score = row["cross_platform_score"]
                    final_score = persisted_score if (persisted_score is not None and persisted_score > 0) else dynamic_score

                    plat_cnt = len({s.platform for s in signals_list})
                    dynamic_summary = f"Chủ đề tổng hợp từ {len(signals_list)} tín hiệu trên {plat_cnt} nền tảng."
                    clusters.append(
                        TopicCluster(
                            id=UUID(c_id),
                            canonical_name=row["canonical_name"],
                            cross_platform_score=final_score,
                            summary_text=dynamic_summary,
                            category=row["category"] or "general",
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
                    SELECT platform, raw_title, metric_value, growth_velocity, source_url, geo_code, cluster_id, mission_id, metadata, captured_at
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

                cur.execute(
                    """
                    INSERT OR REPLACE INTO research_missions
                    (id, title, keywords, shortcode, geo_code, timeframe, status, agent, session_id, summary, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                cur.execute(
                    "SELECT id, platform, raw_title, metric_value, growth_velocity, source_url, geo_code, mission_id, metadata, captured_at FROM trend_signals WHERE mission_id = ? ORDER BY captured_at DESC",
                    (str(mission_id),)
                )
                rows = cur.fetchall()
                signals: List[TrendSignal] = []
                for r in rows:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                    cap_at = datetime.fromisoformat(r["captured_at"]) if r["captured_at"] else datetime.now(timezone.utc)
                    signals.append(
                        TrendSignal(
                            platform=PlatformType(r["platform"]),
                            raw_title=r["raw_title"],
                            metric_value=r["metric_value"],
                            growth_velocity=r["growth_velocity"],
                            source_url=r["source_url"],
                            geo_code=GeoCode(r["geo_code"]),
                            mission_id=UUID(r["mission_id"]) if r["mission_id"] else None,
                            metadata=meta,
                            captured_at=cap_at,
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
                cur.execute("DELETE FROM trend_signals WHERE mission_id = ?", (str(mission_id),))
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

