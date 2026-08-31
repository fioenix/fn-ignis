import json
import logging
from datetime import datetime, timezone
from typing import List, Optional, Any
from uuid import UUID

import psycopg
from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class PostgresTimescaleRepository(ITrendRepository):
    """
    Adapter lưu trữ và truy vấn xu hướng sử dụng PostgreSQL/Supabase.
    Hỗ trợ cả Research Missions theo chủ đề và Ingress chuỗi thời gian.
    """

    def __init__(
        self,
        dsn: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
        pool: Optional[AsyncConnectionPool] = None,
    ):
        self._dsn = dsn
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool = pool

    async def _get_pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            self._pool = AsyncConnectionPool(
                conninfo=self._dsn,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
                open=False,
            )
            await self._pool.open()
        return self._pool

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save_signals(self, signals: List[TrendSignal]) -> int:
        if not signals:
            return 0

        pool = await self._get_pool()
        query = """
            INSERT INTO trend_signals (
                platform,
                raw_title,
                cluster_id,
                mission_id,
                metric_value,
                growth_velocity,
                source_url,
                geo_code,
                metadata,
                captured_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
        """

        params = [
            (
                s.platform.value if hasattr(s.platform, "value") else str(s.platform),
                s.raw_title,
                s.cluster_id,
                s.mission_id,
                s.metric_value,
                s.growth_velocity,
                s.source_url,
                s.geo_code.value if hasattr(s.geo_code, "value") else str(s.geo_code),
                json.dumps(s.metadata or {}),
                s.captured_at or datetime.now(timezone.utc),
            )
            for s in signals
        ]

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(query, params)
            logger.info(f"Đã lưu thành công {len(signals)} signals vào Database.")
            return len(signals)
        except Exception as e:
            logger.error(f"Lỗi khi lưu signals vào Database: {e}", exc_info=True)
            raise RepositoryException(f"Failed to batch insert signals: {e}") from e

    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        if not clusters:
            return

        pool = await self._get_pool()
        query = """
            INSERT INTO topic_clusters (
                id,
                canonical_name,
                summary_text,
                category,
                cross_platform_score,
                first_seen_at,
                last_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                canonical_name = EXCLUDED.canonical_name,
                summary_text = EXCLUDED.summary_text,
                category = EXCLUDED.category,
                cross_platform_score = EXCLUDED.cross_platform_score,
                last_updated_at = EXCLUDED.last_updated_at;
        """

        params = [
            (
                str(c.id),
                c.canonical_name,
                c.summary_text,
                c.category,
                c.cross_platform_score,
                c.first_seen_at or datetime.now(timezone.utc),
                c.last_updated_at or datetime.now(timezone.utc),
            )
            for c in clusters
        ]

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(query, params)
            logger.info(f"Đã upsert thành công {len(clusters)} topic clusters.")
        except Exception as e:
            logger.error(f"Lỗi khi upsert topic clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to upsert topic clusters: {e}") from e

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        pool = await self._get_pool()
        query = """
            SELECT 
                id,
                canonical_name,
                summary_text,
                category,
                cross_platform_score,
                first_seen_at,
                last_updated_at
            FROM topic_clusters
            ORDER BY cross_platform_score DESC, last_updated_at DESC
            LIMIT %s;
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (limit,))
                    rows = await cur.fetchall()

            clusters = []
            for row in rows:
                c_id, name, summary, cat, score, first_seen, last_updated = row
                cluster = TopicCluster(
                    id=UUID(str(c_id)),
                    canonical_name=name,
                    summary_text=summary,
                    category=cat or "general",
                    cross_platform_score=float(score or 0.0),
                    first_seen_at=first_seen,
                    last_updated_at=last_updated,
                )
                clusters.append(cluster)
            return clusters
        except Exception as e:
            logger.error(f"Lỗi khi truy vấn top clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to query top clusters: {e}") from e

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
        pool = await self._get_pool()
        interval_map = {
            Timeframe.LAST_24H: "24 hours",
            Timeframe.LAST_7D: "7 days",
            Timeframe.LAST_30D: "30 days",
        }
        interval = interval_map.get(timeframe, "7 days")

        query = f"""
            SELECT 
                platform,
                raw_title,
                metric_value,
                growth_velocity,
                source_url,
                geo_code,
                metadata,
                captured_at,
                cluster_id,
                mission_id
            FROM trend_signals
            WHERE cluster_id = %s AND captured_at >= NOW() - INTERVAL '{interval}'
            ORDER BY captured_at ASC;
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(cluster_id),))
                    rows = await cur.fetchall()

            signals = []
            for row in rows:
                platform_str, title, metric, velocity, url, geo_str, meta_json, captured, c_id, m_id = row
                meta = meta_json if isinstance(meta_json, dict) else json.loads(meta_json or "{}")
                sig = TrendSignal(
                    platform=PlatformType(platform_str),
                    raw_title=title,
                    metric_value=float(metric or 0.0),
                    growth_velocity=float(velocity or 0.0),
                    source_url=url,
                    geo_code=GeoCode(geo_str),
                    cluster_id=UUID(str(c_id)) if c_id else None,
                    mission_id=UUID(str(m_id)) if m_id else None,
                    metadata=meta,
                    captured_at=captured,
                )
                signals.append(sig)
            return signals
        except Exception as e:
            logger.error(f"Lỗi khi lấy signals của cluster {cluster_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch cluster signals: {e}") from e

    async def create_mission(self, mission: ResearchMission) -> ResearchMission:
        pool = await self._get_pool()
        query = """
            INSERT INTO research_missions (
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        platforms_str = [p.value if hasattr(p, "value") else str(p) for p in mission.platforms]
        params = (
            str(mission.id),
            mission.title,
            mission.keywords,
            mission.shortcode,
            mission.agent,
            mission.session_id,
            platforms_str,
            mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
            mission.timeframe,
            mission.status,
            mission.summary,
            mission.created_at,
            mission.updated_at,
        )

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
            return mission
        except Exception as e:
            logger.error(f"Lỗi khi tạo research mission: {e}", exc_info=True)
            raise RepositoryException(f"Failed to create research mission: {e}") from e

    async def get_mission(self, identifier: Any) -> Optional[ResearchMission]:
        pool = await self._get_pool()
        raw_id = str(identifier).strip()
        
        query = """
            SELECT 
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                created_at,
                updated_at
            FROM research_missions
            WHERE id::text = %s 
               OR UPPER(shortcode) = UPPER(%s)
               OR session_id = %s
               OR id::text ILIKE %s
            ORDER BY created_at DESC
            LIMIT 1;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (raw_id, raw_id, raw_id, f"{raw_id}%"))
                    row = await cur.fetchone()
            if not row:
                return None

            m_id, title, kws, sc, agent_val, sess_id, plats, geo, tf, status, summary, created, updated = row
            return ResearchMission(
                id=UUID(str(m_id)),
                title=title,
                keywords=list(kws or []),
                shortcode=sc or str(m_id)[:8].upper(),
                agent=agent_val or "claude",
                session_id=sess_id,
                platforms=[PlatformType(p) for p in (plats or []) if p in PlatformType._value2member_map_],
                geo_code=GeoCode(geo) if geo in GeoCode._value2member_map_ else GeoCode.VN,
                timeframe=tf,
                status=status,
                summary=summary,
                created_at=created,
                updated_at=updated,
            )
        except Exception as e:
            logger.error(f"Lỗi khi lấy research mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to get research mission: {e}") from e

    async def update_mission(self, mission: ResearchMission) -> None:
        pool = await self._get_pool()
        query = """
            UPDATE research_missions SET
                title = %s,
                keywords = %s,
                platforms = %s,
                geo_code = %s,
                timeframe = %s,
                status = %s,
                summary = %s,
                updated_at = NOW()
            WHERE id = %s;
        """
        platforms_str = [p.value if hasattr(p, "value") else str(p) for p in mission.platforms]
        params = (
            mission.title,
            mission.keywords,
            platforms_str,
            mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
            mission.timeframe,
            mission.status,
            mission.summary,
            str(mission.id),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
        except Exception as e:
            logger.error(f"Lỗi khi cập nhật mission: {e}", exc_info=True)
            raise RepositoryException(f"Failed to update mission: {e}") from e

    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        pool = await self._get_pool()
        query = """
            SELECT 
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                created_at,
                updated_at
            FROM research_missions
            ORDER BY created_at DESC
            LIMIT %s;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (limit,))
                    rows = await cur.fetchall()

            missions = []
            for row in rows:
                m_id, title, kws, sc, agent_val, sess_id, plats, geo, tf, status, summary, created, updated = row
                mission = ResearchMission(
                    id=UUID(str(m_id)),
                    title=title,
                    keywords=list(kws or []),
                    shortcode=sc or str(m_id)[:8].upper(),
                    agent=agent_val or "claude",
                    session_id=sess_id,
                    platforms=[PlatformType(p) for p in (plats or []) if p in PlatformType._value2member_map_],
                    geo_code=GeoCode(geo) if geo in GeoCode._value2member_map_ else GeoCode.VN,
                    timeframe=tf,
                    status=status,
                    summary=summary,
                    created_at=created,
                    updated_at=updated,
                )
                missions.append(mission)
            return missions
        except Exception as e:
            logger.error(f"Lỗi khi list research missions: {e}", exc_info=True)
            raise RepositoryException(f"Failed to list research missions: {e}") from e

    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        pool = await self._get_pool()
        query = """
            SELECT 
                platform,
                raw_title,
                metric_value,
                growth_velocity,
                source_url,
                geo_code,
                metadata,
                captured_at,
                cluster_id,
                mission_id
            FROM trend_signals
            WHERE mission_id = %s
            ORDER BY metric_value DESC, captured_at DESC;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(mission_id),))
                    rows = await cur.fetchall()

            signals = []
            for row in rows:
                platform_str, title, metric, velocity, url, geo_str, meta_json, captured, c_id, m_id = row
                meta = meta_json if isinstance(meta_json, dict) else json.loads(meta_json or "{}")
                sig = TrendSignal(
                    platform=PlatformType(platform_str),
                    raw_title=title,
                    metric_value=float(metric or 0.0),
                    growth_velocity=float(velocity or 0.0),
                    source_url=url,
                    geo_code=GeoCode(geo_str),
                    cluster_id=UUID(str(c_id)) if c_id else None,
                    mission_id=UUID(str(m_id)) if m_id else None,
                    metadata=meta,
                    captured_at=captured,
                )
                signals.append(sig)
            return signals
        except Exception as e:
            logger.error(f"Lỗi khi lấy signals của mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch mission signals: {e}") from e

    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[dict] = None,
    ) -> None:
        pool = await self._get_pool()
        query = """
            INSERT INTO system_audit_logs (level, component, event_type, message, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        params = (
            level.upper(),
            component,
            event_type,
            message,
            json.dumps(details or {}),
            datetime.now(timezone.utc),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
        except Exception as e:
            logger.error(f"Lỗi khi ghi audit log ({component}): {e}")

    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        pool = await self._get_pool()
        conditions = []
        params = []

        if level:
            conditions.append("level = %s")
            params.append(level.upper())
        if component:
            conditions.append("component = %s")
            params.append(component)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"""
            SELECT id, level, component, event_type, message, details, created_at
            FROM system_audit_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s;
        """
        params.append(limit)

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, tuple(params))
                    rows = await cur.fetchall()

            logs = []
            for r in rows:
                l_id, lvl, comp, evt, msg, dtl_json, created = r
                dtl = dtl_json if isinstance(dtl_json, dict) else json.loads(dtl_json or "{}")
                logs.append({
                    "id": l_id,
                    "level": lvl,
                    "component": comp,
                    "event_type": evt,
                    "message": msg,
                    "details": dtl,
                    "created_at": created.isoformat() if created else None,
                })
            return logs
        except Exception as e:
            logger.error(f"Lỗi khi truy vấn audit logs: {e}", exc_info=True)
            return []
