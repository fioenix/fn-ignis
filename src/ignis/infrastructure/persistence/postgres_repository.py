import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from uuid import UUID

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe, resolve_geo, resolve_platform

from ignis.infrastructure.auth.crypto import encrypt_credentials, decrypt_credentials

logger = logging.getLogger(__name__)


class PostgresTimescaleRepository(ITrendRepository):
    """
    Persistence adapter for PostgreSQL / Supabase storage.
    Supports both topic-based Research Missions and time-series trend ingress.
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
            logger.info(f"Successfully saved {len(signals)} signals to database.")
            return len(signals)
        except Exception as e:
            logger.error(f"Error saving signals to database: {e}", exc_info=True)
            raise RepositoryException(f"Failed to batch insert signals: {e}") from e

    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        if not clusters:
            return

        pool = await self._get_pool()
        find_query = """
            SELECT id, canonical_name
            FROM topic_clusters
            WHERE id = %s OR LOWER(canonical_name) = LOWER(%s)
            LIMIT 1;
        """
        update_query = """
            UPDATE topic_clusters SET
                canonical_name = %s,
                summary_text = %s,
                category = %s,
                cross_platform_score = %s,
                last_updated_at = %s
            WHERE id = %s;
        """
        insert_query = """
            INSERT INTO topic_clusters (
                id,
                canonical_name,
                summary_text,
                category,
                cross_platform_score,
                first_seen_at,
                last_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s);
        """

        from ignis.domain.normalization import normalize_cluster_name

        # Deduplicate clusters within the batch before saving
        deduped: Dict[str, TopicCluster] = {}
        for c in clusters:
            norm_name = normalize_cluster_name(c.canonical_name)
            if norm_name in deduped:
                target = deduped[norm_name]
                target.signals.extend(c.signals)
                target.cross_platform_score = max(target.cross_platform_score, c.cross_platform_score)
            else:
                c.canonical_name = norm_name
                deduped[norm_name] = c

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for c in deduped.values():
                        try:
                            async with conn.transaction():
                                c_first_seen = c.first_seen_at or datetime.now(timezone.utc)
                                c_last_updated = c.last_updated_at or datetime.now(timezone.utc)
                                clean_name = c.canonical_name
                                c_id_str = str(c.id)

                                await cur.execute(find_query, (c_id_str, clean_name))
                                row = await cur.fetchone()

                                if row:
                                    actual_id = row[0]
                                    await cur.execute(
                                        update_query,
                                        (
                                            clean_name,
                                            c.summary_text,
                                            c.category,
                                            c.cross_platform_score,
                                            c_last_updated,
                                            actual_id,
                                        ),
                                    )
                                else:
                                    actual_id = c.id
                                    await cur.execute(
                                        insert_query,
                                        (
                                            c_id_str,
                                            clean_name,
                                            c.summary_text,
                                            c.category,
                                            c.cross_platform_score,
                                            c_first_seen,
                                            c_last_updated,
                                        ),
                                    )

                                c.id = actual_id
                                for s in c.signals:
                                    s.cluster_id = actual_id
                        except Exception as row_err:
                            logger.warning(
                                f"Failed to upsert individual cluster '{c.canonical_name}', rolling back savepoint: {row_err}"
                            )

            logger.info(f"Successfully upserted {len(deduped)} topic clusters.")
        except Exception as e:
            logger.error(f"Error upserting topic clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to upsert topic clusters: {e}") from e

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        pool = await self._get_pool()
        interval_map = {
            Timeframe.LAST_24H: "24 hours",
            Timeframe.LAST_7D: "7 days",
            Timeframe.LAST_30D: "30 days",
        }
        interval = interval_map.get(timeframe, "24 hours")

        query = f"""
            WITH ranked_clusters AS (
                SELECT 
                    tc.id,
                    tc.canonical_name,
                    tc.summary_text,
                    tc.category,
                    tc.first_seen_at,
                    tc.last_updated_at,
                    COUNT(ts.id) AS sig_count,
                    COUNT(DISTINCT ts.platform) AS plat_count,
                    COALESCE(SUM(ts.metric_value), 0.0) AS total_metric,
                    COALESCE(AVG(ts.growth_velocity), 0.0) AS avg_velocity,
                    ROUND(LEAST(100.0, 
                        (COUNT(DISTINCT ts.platform) / 5.0 * 35.0) +
                        LEAST(35.0, (LOG(GREATEST(1.0, COALESCE(SUM(ts.metric_value), 0.0) + 1.0)) / 10.0) * 35.0) +
                        LEAST(20.0, (LOG(GREATEST(1.0, COALESCE(AVG(ts.growth_velocity), 0.0) + 1.0)) / 5.0) * 20.0) +
                        LEAST(10.0, (LOG(GREATEST(1.0, COUNT(ts.id)::numeric + 1.0)) / 3.0) * 10.0)
                    )::numeric, 1) AS dynamic_score
                FROM topic_clusters tc
                INNER JOIN trend_signals ts ON ts.cluster_id = tc.id
                WHERE ts.captured_at >= NOW() - INTERVAL '{interval}'
                GROUP BY tc.id, tc.canonical_name, tc.summary_text, tc.category, tc.first_seen_at, tc.last_updated_at
                ORDER BY dynamic_score DESC, sig_count DESC
                LIMIT %s
            )
            SELECT 
                rc.id,
                rc.canonical_name,
                rc.summary_text,
                rc.category,
                rc.dynamic_score,
                rc.first_seen_at,
                rc.last_updated_at,
                rc.sig_count,
                JSON_AGG(JSON_BUILD_OBJECT(
                    'platform', ts.platform,
                    'raw_title', ts.raw_title,
                    'metric_value', ts.metric_value,
                    'growth_velocity', ts.growth_velocity,
                    'source_url', ts.source_url,
                    'geo_code', ts.geo_code,
                    'metadata', ts.metadata,
                    'captured_at', ts.captured_at
                )) AS signals
            FROM ranked_clusters rc
            INNER JOIN trend_signals ts ON ts.cluster_id = rc.id
            WHERE ts.captured_at >= NOW() - INTERVAL '{interval}'
            GROUP BY rc.id, rc.canonical_name, rc.summary_text, rc.category, rc.dynamic_score, rc.first_seen_at, rc.last_updated_at, rc.sig_count
            ORDER BY rc.dynamic_score DESC, rc.sig_count DESC;
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (limit,))
                    rows = await cur.fetchall()

            clusters = []
            for row in rows:
                c_id, name, summary, cat, score, first_seen, last_updated = row[:7]
                _sig_count = row[7] if len(row) > 7 else 0
                sigs_raw = row[8] if len(row) > 8 else "[]"
                
                signals_list: List[TrendSignal] = []
                sigs_data = sigs_raw if isinstance(sigs_raw, list) else json.loads(sigs_raw or "[]")
                for s_dict in sigs_data:
                    c_at = s_dict.get("captured_at")
                    if isinstance(c_at, str):
                        c_at = datetime.fromisoformat(c_at)
                    sig_meta = s_dict.get("metadata") or {}
                    if isinstance(sig_meta, str):
                        try:
                            sig_meta = json.loads(sig_meta)
                        except Exception:
                            sig_meta = {}
                    signals_list.append(
                        TrendSignal(
                            platform=PlatformType(s_dict["platform"]),
                            raw_title=s_dict["raw_title"],
                            metric_value=float(s_dict.get("metric_value", 0.0)),
                            growth_velocity=float(s_dict.get("growth_velocity", 0.0)),
                            source_url=s_dict.get("source_url", ""),
                            geo_code=GeoCode(s_dict.get("geo_code", "VN")),
                            cluster_id=UUID(str(c_id)),
                            metadata=sig_meta,
                            captured_at=c_at or datetime.now(timezone.utc),
                        )
                    )

                cluster = TopicCluster(
                    id=UUID(str(c_id)),
                    canonical_name=name,
                    summary_text=summary,
                    category=cat or "general",
                    cross_platform_score=float(score or 0.0),
                    signals=signals_list,
                    first_seen_at=first_seen,
                    last_updated_at=last_updated,
                )
                clusters.append(cluster)
            return clusters
        except Exception as e:
            logger.error(f"Error querying top clusters: {e}", exc_info=True)
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
            logger.error(f"Error fetching signals for cluster {cluster_id}: {e}", exc_info=True)
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
            logger.error(f"Error creating research mission: {e}", exc_info=True)
            raise RepositoryException(f"Failed to create research mission: {e}") from e

    async def save_mission(self, mission: ResearchMission) -> ResearchMission:
        """Upsert a research mission (creates if not existing, otherwise updates)."""
        existing = await self.get_mission(mission.id)
        if existing:
            await self.update_mission(mission)
            return mission
        return await self.create_mission(mission)

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
                platforms=[resolve_platform(p) for p in (plats or [])],
                geo_code=resolve_geo(geo),
                timeframe=tf,

                status=status,
                summary=summary,
                created_at=created,
                updated_at=updated,
            )
        except Exception as e:
            logger.error(f"Error getting research mission {identifier}: {e}", exc_info=True)
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
            logger.error(f"Error updating mission: {e}", exc_info=True)
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
                    platforms=[resolve_platform(p) for p in (plats or [])],
                    geo_code=resolve_geo(geo),
                    timeframe=tf,

                    status=status,
                    summary=summary,
                    created_at=created,
                    updated_at=updated,
                )
                missions.append(mission)
            return missions
        except Exception as e:
            logger.error(f"Error listing research missions: {e}", exc_info=True)
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
            logger.error(f"Error fetching signals for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch mission signals: {e}") from e

    async def delete_mission_signals(self, mission_id: UUID) -> int:
        pool = await self._get_pool()
        query = "DELETE FROM trend_signals WHERE mission_id = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (str(mission_id),))
                    deleted_count = cur.rowcount
                    await conn.commit()
            logger.info(f"Deleted {deleted_count} prior signals for mission {mission_id} for fresh atomic replace.")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting signals for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to delete mission signals: {e}") from e

    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[dict] = None,
    ) -> None:
        from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, sanitize_pii_data
        pool = await self._get_pool()
        query = """
            INSERT INTO system_audit_logs (level, component, event_type, message, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        params = (
            level.upper(),
            component,
            event_type,
            sanitize_pii_text(message),
            json.dumps(sanitize_pii_data(details or {})),
            datetime.now(timezone.utc),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
        except Exception as e:
            logger.error(f"Error writing audit log ({component}): {e}")

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
            logger.error(f"Error querying audit logs: {e}", exc_info=True)
            return []

    async def save_platform_credentials(
        self,
        platform: str,
        auth_type: str,
        credentials_data: Dict[str, Any],
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
    ) -> None:
        pool = await self._get_pool()
        # Zero-Knowledge Encryption before persisting to database
        payload_to_store = encrypt_credentials(credentials_data)

        query = """
            INSERT INTO platform_credentials (
                platform,
                auth_type,
                credentials_data,
                is_active,
                expires_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (platform) DO UPDATE SET
                auth_type = EXCLUDED.auth_type,
                credentials_data = EXCLUDED.credentials_data,
                is_active = EXCLUDED.is_active,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW();
        """
        params = (
            platform.lower(),
            auth_type,
            json.dumps(payload_to_store),
            is_active,
            expires_at,
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
            logger.info(f"Successfully saved encrypted credentials for platform [{platform}].")
        except Exception as e:
            logger.error(f"Error saving credentials for {platform}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to save credentials for {platform}: {e}") from e

    async def get_platform_credentials(self, platform: str) -> Optional[Dict[str, Any]]:
        pool = await self._get_pool()
        query = """
            SELECT platform, auth_type, credentials_data, is_active, expires_at, updated_at
            FROM platform_credentials
            WHERE platform = %s AND is_active = TRUE
            LIMIT 1;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (platform.lower(),))
                    row = await cur.fetchone()
            if not row:
                return None

            plat, auth_type, creds_json, active, expires, updated = row
            raw_creds = creds_json if isinstance(creds_json, dict) else json.loads(creds_json or "{}")
            # Automatically decrypt ciphertext back to plaintext dictionary
            decrypted_creds = decrypt_credentials(raw_creds)
            return {
                "platform": plat,
                "auth_type": auth_type,
                "credentials_data": decrypted_creds,
                "is_active": active,
                "expires_at": expires.isoformat() if expires else None,
                "updated_at": updated.isoformat() if updated else None,
            }
        except Exception as e:
            logger.error(f"Error retrieving credentials for {platform}: {e}", exc_info=True)
            return None

    async def list_platform_credentials(self) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        query = """
            SELECT platform, auth_type, is_active, expires_at, updated_at
            FROM platform_credentials
            ORDER BY updated_at DESC;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query)
                    rows = await cur.fetchall()
            result = []
            for r in rows:
                plat, auth_type, active, expires, updated = r
                result.append({
                    "platform": plat,
                    "auth_type": auth_type,
                    "is_active": active,
                    "expires_at": expires.isoformat() if expires else None,
                    "updated_at": updated.isoformat() if updated else None,
                })
            return result
        except Exception as e:
            logger.error(f"Error listing platform credentials: {e}", exc_info=True)
            return []

    async def delete_platform_credentials(self, platform: str) -> bool:
        pool = await self._get_pool()
        query = "UPDATE platform_credentials SET is_active = FALSE, updated_at = NOW() WHERE platform = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (platform.lower(),))
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error deactivating credentials for {platform}: {e}", exc_info=True)
            return False

    async def get_domain_lexicons(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        query = """
            SELECT domain, term, category, created_by, created_at
            FROM market_lexicons
        """
        params = []
        if domain:
            query += " WHERE domain = %s"
            params.append(domain.lower())
        query += " ORDER BY domain ASC, term ASC;"

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, tuple(params) if params else None)
                    rows = await cur.fetchall()
            return [
                {
                    "domain": r[0],
                    "term": r[1],
                    "category": r[2],
                    "created_by": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching market lexicons: {e}")
            return []

    async def register_lexicon_terms(
        self,
        domain: str,
        terms: List[str],
        category: str = "vernacular",
        created_by: str = "agent",
    ) -> int:
        if not terms:
            return 0
        pool = await self._get_pool()
        clean_domain = domain.lower().strip()
        count = 0

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for t in terms:
                        clean_term = t.lower().strip()
                        if clean_term:
                            await cur.execute(
                                """
                                INSERT INTO market_lexicons (domain, term, category, created_by)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (domain, term) DO NOTHING;
                                """,
                                (clean_domain, clean_term, category, created_by)
                            )
                            count += 1
            return count
        except Exception as e:
            logger.error(f"Error registering lexicon terms: {e}", exc_info=True)
            raise RepositoryException(f"Failed to register lexicon terms: {e}") from e

    async def get_industry_taxonomies(self) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        query = "SELECT industry_code, industry_name, keywords FROM industry_taxonomies ORDER BY industry_code ASC;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query)
                    rows = await cur.fetchall()
            return [
                {
                    "industry_code": r[0],
                    "industry_name": r[1],
                    "keywords": r[2] if isinstance(r[2], list) else list(r[2] or []),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching industry taxonomies: {e}")
            return []

    async def get_runtime_config(self, key: str) -> Optional[str]:
        pool = await self._get_pool()
        query = "SELECT value FROM runtime_configs WHERE key = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (key,))
                    row = await cur.fetchone()
                    return str(row[0]) if row else None
        except Exception as e:
            logger.error(f"Error fetching runtime config for {key}: {e}")
            return None

    async def get_all_runtime_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if category:
            query = "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs WHERE category = %s ORDER BY key ASC;"
            params = (category,)
        else:
            query = "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs ORDER BY category ASC, key ASC;"
            params = ()
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
            return [
                {
                    "key": r[0],
                    "value": r[1],
                    "category": r[2],
                    "description": r[3],
                    "updated_by": r[4],
                    "created_at": str(r[5]),
                    "updated_at": str(r[6]),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching runtime configs: {e}")
            return []

    async def set_runtime_config(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        pool = await self._get_pool()
        query = """
            INSERT INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                category = COALESCE(EXCLUDED.category, runtime_configs.category),
                description = COALESCE(EXCLUDED.description, runtime_configs.description),
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW();
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (key, str(value), category, description, updated_by))
        except Exception as e:
            logger.error(f"Error setting runtime config for {key}: {e}")
            raise RepositoryException(f"Failed to set runtime config: {e}") from e

    async def delete_runtime_config(self, key: str) -> bool:
        pool = await self._get_pool()
        query = "DELETE FROM runtime_configs WHERE key = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (key,))
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting runtime config {key}: {e}")
            return False



