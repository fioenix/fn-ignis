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
from ignis.infrastructure.persistence.migration_state import (
    UNBACKFILLED_CORPUS,
    is_unbackfilled,
)
from ignis.domain.cross_platform_score import cross_platform_score
from ignis.domain.source_identity import resolve_source_identity
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
            await self._refuse_an_unbackfilled_corpus(self._pool)
        return self._pool

    async def _refuse_an_unbackfilled_corpus(self, pool) -> None:
        """Checked once, as the pool opens: the window is a deploy, not a query."""
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT"
                    " EXISTS (SELECT 1 FROM trend_signals),"
                    " EXISTS (SELECT 1 FROM observations)"
                )
            ).fetchone()
        if is_unbackfilled(*row):
            raise RepositoryException(UNBACKFILLED_CORPUS)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Record each sighting in the source/observation model. Nothing else is written.

        trend_signals and signal_metrics are read-only from here on. They stay in the schema --
        the audit reads them, the backfill reads them, and they are the only record of what the
        corpus looked like before the migration -- but a write to them now would restart the
        divergence the migration closed.
        """
        if not signals:
            return 0

        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    recorded = await self._record_observations(cur, signals)
            logger.info(f"Recorded {recorded} observations from {len(signals)} signals.")
            return recorded
        except Exception as e:
            logger.error(f"Error saving signals to database: {e}", exc_info=True)
            raise RepositoryException(f"Failed to record observations: {e}") from e

    async def _record_observations(self, cur, signals: List[TrendSignal]) -> int:
        """Write each signal as one observation of one canonical source.

        Three properties this has to hold, each of them measured on the corpus rather than
        assumed:

        - A source is upserted on (platform, external_id) in a single statement. A SELECT
          followed by an INSERT is not the same thing: two ingress passes racing on one video
          would both see nothing and both insert, which is how the legacy table came to hold
          1,927 rows for 1,924 objects.
        - Every signal becomes an observation. Nothing is deduplicated on the payload, because
          two collection events are allowed to be identical on every field and only the
          surrogate id separates them.
        - A mission's claim goes to mission_evidence, never onto the source or the observation.
          One source is observed by many missions, and the legacy mission_id column could only
          record the last one, which is why the second mission lost its evidence.
        """
        written = 0
        for signal in signals:
            platform = (
                signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
            )
            identity = resolve_source_identity(platform, signal.source_url, signal.metadata)
            if identity is None:
                # Nothing identifies this sighting. Counted by the audit rather than given an
                # invented key, and skipped here for the same reason.
                logger.warning("Signal has no resolvable external identity, skipped: %s", platform)
                continue

            await cur.execute(
                "INSERT INTO sources (platform, external_id) VALUES (%s, %s)"
                " ON CONFLICT (platform, external_id) DO UPDATE SET platform = EXCLUDED.platform"
                " RETURNING id;",
                (identity.platform, identity.external_id),
            )
            source_id = (await cur.fetchone())[0]

            # A live write knows when it collected: the clock is this process's own. Only rows
            # written before sql/015 by a connector that stamped a publish time are legacy, and
            # those arrive through the backfill, not here.
            observed_at = signal.captured_at or datetime.now(timezone.utc)
            await cur.execute(
                "INSERT INTO observations (source_id, cluster_id, observed_at, published_at,"
                " time_provenance, identity_source, observed_title, metric_value,"
                " growth_velocity, geo_code, source_url, metadata)"
                " VALUES (%s, %s, %s, %s, 'exact_ingestion', %s, %s, %s, %s, %s, %s, %s)"
                " RETURNING id;",
                (
                    source_id,
                    str(signal.cluster_id) if signal.cluster_id else None,
                    observed_at,
                    signal.published_at,
                    identity.identity_source,
                    signal.raw_title,
                    signal.metric_value,
                    signal.growth_velocity,
                    signal.geo_code.value
                    if hasattr(signal.geo_code, "value")
                    else str(signal.geo_code),
                    signal.source_url,
                    json.dumps(signal.metadata or {}),
                ),
            )
            observation_id = (await cur.fetchone())[0]
            # The caller needs this to attach a cluster later without writing a second sighting.
            signal.observation_id = UUID(str(observation_id))
            signal.identity_source = identity.identity_source
            signal.time_provenance = "exact_ingestion"
            written += 1

            if signal.mission_id:
                await cur.execute(
                    "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)"
                    " ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                    (str(signal.mission_id), str(observation_id)),
                )
        return written

    async def prune_empty_clusters(self) -> int:
        """Remove clusters holding no observation at all.

        Membership, not recency: a cluster whose only observations are legacy ones outside the
        default analysis window still describes something the corpus contains. Pruning on the
        window would delete 17,118 observations' worth of topics on the first pass after the
        backfill.
        
        Referenced by the legacy corpus counts as referenced. sql/016 creates the new tables
        empty, so between the migration and the backfill every legacy membership looks like an
        empty cluster here -- and deleting those topics cascades trend_signals.cluster_id to
        NULL, destroying the very rows the backfill was going to read. After the backfill the
        guard changes nothing, because a legacy row that was carried over has an observation.
        """
        pool = await self._get_pool()
        query = """
            DELETE FROM topic_clusters tc
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.cluster_id = tc.id)
              AND NOT EXISTS (SELECT 1 FROM trend_signals ts WHERE ts.cluster_id = tc.id);
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query)
                    return cur.rowcount or 0
        except Exception as e:
            logger.warning(f"Could not prune empty clusters: {e}")
            return 0

    @staticmethod
    def _deduplicate_clusters(clusters: List[TopicCluster]) -> Dict[str, TopicCluster]:
        """Merge clusters that normalise to the same canonical name, keyed by that name.

        A merged-away cluster is never persisted, so its signals must be re-pointed at the
        surviving cluster. Leaving them on the dropped id sent them to whatever row already
        carried it, and the surviving cluster was then stored with no signals at all — which is
        where the empty topic_clusters rows came from, roughly a dozen per ingress pass.
        """
        from ignis.domain.normalization import normalize_cluster_name

        deduped: Dict[str, TopicCluster] = {}
        for c in clusters:
            norm_name = normalize_cluster_name(c.canonical_name)
            target = deduped.get(norm_name)
            if target is None:
                c.canonical_name = norm_name
                deduped[norm_name] = c
                continue

            for signal in c.signals:
                signal.cluster_id = target.id
            target.signals.extend(c.signals)
            target.cross_platform_score = max(target.cross_platform_score, c.cross_platform_score)
        return deduped

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
                topic_label = %s,
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
                topic_label,
                summary_text,
                category,
                cross_platform_score,
                first_seen_at,
                last_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """

        deduped = self._deduplicate_clusters(clusters)

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for c in deduped.values():
                        try:
                            async with conn.transaction():
                                # Passed through, including None. Substituting now() would
                                # give a cluster of legacy observations a first sighting dated
                                # to this run.
                                c_first_seen = c.first_seen_at
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
                                            c.topic_label,
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
                                            c.topic_label,
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

    # The default analysis window admits only observations whose collection time is known.
    # published_at is not a substitute: for the 17,118 legacy observations it answers "when was
    # this posted", and a window built on it would report a two-year-old video as something seen
    # this week.
    _WINDOW_PREDICATE = (
        "o.time_provenance = 'exact_ingestion'"
        " AND o.observed_at IS NOT NULL"
        " AND o.observed_at >= NOW() - INTERVAL '{interval}'"
    )

    # Recency, then the payload, then the row id. Two observations of one source may share an
    # instant -- the schema allows it and a pass that sees one object twice in the same second
    # produces it -- and ordering on the clock alone left the winner to whatever order the rows
    # came back in. metric_value and growth_velocity come next because they are what the reader
    # returns and the score is computed from; once those tie, nothing downstream can tell the
    # two rows apart, and id only makes the choice repeatable.
    _LATEST_FIRST = (
        "o.observed_at DESC, COALESCE(o.metric_value, 0) DESC,"
        " COALESCE(o.growth_velocity, 0) DESC, o.id DESC"
    )

    # One observation per source: the most recent in the window. A source polled hourly must not
    # outweigh one polled daily, because polling frequency is a property of the harness.
    _LATEST_PER_SOURCE = """
        -- Partitioned on (cluster_id, source_id), not on source_id alone. A source observed in
        -- one cluster and later in another would otherwise keep only its latest sighting
        -- anywhere, and the earlier membership would vanish from the reader entirely -- 175
        -- identities in the corpus sit under more than one cluster, which is why cluster_id is
        -- on the observation rather than on the source.
        SELECT DISTINCT ON (o.cluster_id, o.source_id)
            o.id AS observation_id, o.source_id, o.cluster_id, o.metric_value, o.growth_velocity,
            o.observed_at, o.published_at, o.time_provenance, o.identity_source, o.observed_title,
            o.geo_code, o.source_url, o.metadata, s.platform
        FROM observations o
        JOIN sources s ON s.id = o.source_id
        WHERE o.cluster_id IS NOT NULL AND {window}
        ORDER BY o.cluster_id, o.source_id, {latest_first}
    """

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        """Rank clusters by what was observed in the window, from the new model only."""
        pool = await self._get_pool()
        interval_map = {
            Timeframe.LAST_24H: "24 hours",
            Timeframe.LAST_7D: "7 days",
            Timeframe.LAST_30D: "30 days",
        }
        interval = interval_map.get(timeframe, "24 hours")
        latest = self._LATEST_PER_SOURCE.format(
            window=self._WINDOW_PREDICATE.format(interval=interval),
            latest_first=self._LATEST_FIRST,
        )

        query = f"""
            WITH latest AS ({latest})
            SELECT
                tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                tc.first_seen_at, tc.last_updated_at,
                COUNT(*) AS source_count,
                COUNT(DISTINCT l.platform) AS platform_count,
                COALESCE(SUM(l.metric_value), 0.0) AS total_metric,
                COALESCE(AVG(l.growth_velocity), 0.0) AS avg_velocity,
                JSON_AGG(JSON_BUILD_OBJECT(
                    'platform', l.platform,
                    'raw_title', l.observed_title,
                    'metric_value', l.metric_value,
                    'growth_velocity', l.growth_velocity,
                    'source_url', l.source_url,
                    'geo_code', l.geo_code,
                    'metadata', l.metadata,
                    'observed_at', l.observed_at,
                    'published_at', l.published_at,
                    'observation_id', l.observation_id,
                    'identity_source', l.identity_source,
                    'time_provenance', l.time_provenance
                )) AS signals
            FROM latest l
            JOIN topic_clusters tc ON tc.id = l.cluster_id
            GROUP BY tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                     tc.first_seen_at, tc.last_updated_at
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query)
                    rows = await cur.fetchall()

            clusters = []
            for row in rows:
                (
                    c_id, name, label, summary, category, first_seen, last_updated,
                    source_count, platform_count, total_metric, avg_velocity, sigs_raw,
                ) = row
                # Scored here, by the same function the clusterer uses. The arithmetic used to
                # live in this query as well, and the two had already drifted apart.
                score = cross_platform_score(
                    distinct_platforms=int(platform_count or 0),
                    total_metric=float(total_metric or 0.0),
                    average_velocity=float(avg_velocity or 0.0),
                )
                sigs_data = sigs_raw if isinstance(sigs_raw, list) else json.loads(sigs_raw or "[]")
                signals_list = [
                    self._signal_from_observation(s_dict, UUID(str(c_id))) for s_dict in sigs_data
                ]
                cluster = TopicCluster(
                    id=UUID(str(c_id)),
                    canonical_name=name,
                    summary_text=summary
                    or f"{source_count} sources across {platform_count} platforms.",
                    category=category or "general",
                    cross_platform_score=score,
                    signals=signals_list,
                    first_seen_at=first_seen,
                    last_updated_at=last_updated,
                )
                cluster.topic_label = label
                clusters.append(cluster)

            clusters.sort(key=lambda c: (c.cross_platform_score, len(c.signals)), reverse=True)
            return clusters[:limit]
        except Exception as e:
            logger.error(f"Error fetching top clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch top clusters: {e}") from e

    @staticmethod
    def _signal_from_observation(data: Dict[str, Any], cluster_id: UUID) -> TrendSignal:
        observed_at = data.get("observed_at")
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at)
        published_at = data.get("published_at")
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at)
        metadata = data.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        observation_id = data.get("observation_id")
        return TrendSignal(
            platform=PlatformType(data["platform"]),
            raw_title=data.get("raw_title") or "",
            metric_value=float(data.get("metric_value") or 0.0),
            growth_velocity=float(data.get("growth_velocity") or 0.0),
            source_url=data.get("source_url"),
            geo_code=GeoCode(data.get("geo_code") or "VN"),
            cluster_id=cluster_id,
            metadata=metadata,
            captured_at=observed_at,
            published_at=published_at,
            observation_id=UUID(str(observation_id)) if observation_id else None,
            identity_source=data.get("identity_source"),
            time_provenance=data.get("time_provenance"),
        )

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
        """One signal per source, the most recent observation of it in the window.

        Deduplication is on source_id now, not on the URL. A URL is what one sighting reported,
        and the corpus holds one source seen under two URL variants -- keying on it counted that
        source twice, and a feed-level URL shared by many items counted them as one.
        """
        pool = await self._get_pool()
        interval_map = {
            Timeframe.LAST_24H: "24 hours",
            Timeframe.LAST_7D: "7 days",
            Timeframe.LAST_30D: "30 days",
        }
        interval = interval_map.get(timeframe, "7 days")
        window = self._WINDOW_PREDICATE.format(interval=interval)

        query = f"""
            SELECT DISTINCT ON (o.cluster_id, o.source_id)
                s.platform, o.observed_title, o.metric_value, o.growth_velocity, o.source_url,
                o.geo_code, o.metadata, o.observed_at, o.published_at, o.id, o.identity_source,
                o.time_provenance
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.cluster_id = %s AND {window}
            ORDER BY o.cluster_id, o.source_id, {self._LATEST_FIRST};
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(cluster_id),))
                    rows = await cur.fetchall()

            signals = [
                self._signal_from_observation(
                    {
                        "platform": row[0],
                        "raw_title": row[1],
                        "metric_value": row[2],
                        "growth_velocity": row[3],
                        "source_url": row[4],
                        "geo_code": row[5],
                        "metadata": row[6],
                        "observed_at": row[7],
                        "published_at": row[8],
                        "observation_id": row[9],
                        "identity_source": row[10],
                        "time_provenance": row[11],
                    },
                    cluster_id,
                )
                for row in rows
            ]
            signals.sort(key=lambda s: (s.captured_at is None, s.captured_at))
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
        """Read the mission's evidence through the ledger, not through a column on the source.

        mission_evidence -> observations -> sources. The legacy trend_signals.mission_id could
        hold one mission per source, so a source two missions had both observed belonged to
        whichever wrote last; this join returns exactly the observations this mission recorded.
        """
        pool = await self._get_pool()
        query = """
            SELECT
                s.platform,
                o.observed_title,
                o.metric_value,
                o.growth_velocity,
                o.source_url,
                o.geo_code,
                o.metadata,
                o.observed_at,
                o.published_at,
                o.cluster_id,
                e.mission_id,
                o.id,
                o.identity_source,
                o.time_provenance
            FROM mission_evidence e
            JOIN observations o ON o.id = e.observation_id
            JOIN sources s ON s.id = o.source_id
            WHERE e.mission_id = %s
            ORDER BY o.metric_value DESC, o.observed_at DESC;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(mission_id),))
                    rows = await cur.fetchall()

            signals = []
            for row in rows:
                (
                    platform_str, title, metric, velocity, url, geo_str, meta_json, observed,
                    published, c_id, m_id, o_id, route, provenance,
                ) = row
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
                    observation_id=UUID(str(o_id)),
                    identity_source=route,
                    time_provenance=provenance,
                    metadata=meta,
                    # Passed through exactly as stored. NULL means the collection time was never
                    # recorded, and substituting one here would turn that into "collected now".
                    captured_at=observed,
                    published_at=published,
                )
                signals.append(sig)
            return signals
        except Exception as e:
            logger.error(f"Error fetching signals for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch mission signals: {e}") from e

    async def assign_observation_clusters(self, signals: List[TrendSignal]) -> int:
        """Set the cluster on observations already written.

        Membership arrived after the sighting was stored -- the discovery pass clusters at the
        end. Putting the signals back through save_signals would record each of them a second
        time, so this is an UPDATE keyed on the observation the writer returned.
        """
        updates = [
            (str(s.cluster_id), str(s.observation_id))
            for s in signals
            if s.observation_id and s.cluster_id
        ]
        if not updates:
            return 0
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "UPDATE observations SET cluster_id = %s WHERE id = %s;", updates
                    )
            return len(updates)
        except Exception as e:
            logger.error(f"Error assigning clusters to observations: {e}", exc_info=True)
            raise RepositoryException(f"Failed to assign observation clusters: {e}") from e

    async def attach_mission_evidence(self, mission_id: UUID, signals: List[TrendSignal]) -> int:
        """Record that a mission used observations that already exist.

        The quota fallback needs this: when a connector returns nothing, the mission keeps the
        evidence it had. Re-submitting those observations through the writer would claim the
        harness polled a platform it could not reach.
        """
        rows = [
            (str(mission_id), str(s.observation_id)) for s in signals if s.observation_id
        ]
        if not rows:
            return 0
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO mission_evidence (mission_id, observation_id)"
                        " VALUES (%s, %s) ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                        rows,
                    )
            return len(rows)
        except Exception as e:
            logger.error(f"Error attaching mission evidence: {e}", exc_info=True)
            raise RepositoryException(f"Failed to attach mission evidence: {e}") from e

    async def prune_mission_evidence(self, mission_id: UUID, retained_observation_ids) -> int:
        """Drop this mission's claims on anything outside the retained set.

        The replacement writes first and prunes last, so the window where a failure can hurt is
        a window where the mission holds too much rather than nothing. Stale evidence is
        recoverable on the next pass; deleted evidence is not.
        """
        retained = [str(observation_id) for observation_id in retained_observation_ids]
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    if retained:
                        await cur.execute(
                            "DELETE FROM mission_evidence"
                            " WHERE mission_id = %s AND NOT (observation_id = ANY(%s::uuid[]))",
                            (str(mission_id), retained),
                        )
                    else:
                        await cur.execute(
                            "DELETE FROM mission_evidence WHERE mission_id = %s",
                            (str(mission_id),),
                        )
                    removed = cur.rowcount or 0
                    await conn.commit()
            return removed
        except Exception as e:
            logger.error(f"Error pruning evidence for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to prune mission evidence: {e}") from e

    async def delete_mission_signals(self, mission_id: UUID) -> int:
        """Withdraw this mission's claims, and nothing else.

        The name is from when a mission owned its signals. It does not: a source and its
        observations are shared, and 1,301 legacy associations sit across sources that other
        missions also observed. Deleting them here would delete another mission's evidence and
        the cluster history built on it, so only the association rows go.
        """
        pool = await self._get_pool()
        query = "DELETE FROM mission_evidence WHERE mission_id = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (str(mission_id),))
                    deleted_count = cur.rowcount
                    await conn.commit()
            logger.info(f"Withdrew {deleted_count} evidence rows for mission {mission_id}.")
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



