import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin, SearchAttestation
from ignis.application.youtube_quota import YouTubeQuotaManager
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import (
    ConnectorExecutionException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, IngressScope, IngressTrigger, PlatformType, Timeframe
from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaSnapshot

import cachetools

from ignis.config import settings
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text

logger = logging.getLogger(__name__)


# Bounded LRU + TTL Cache for YouTube queries (max 2000 queries, TTL from settings)
_YOUTUBE_QUERY_CACHE: cachetools.TTLCache = cachetools.TTLCache(
    maxsize=2000,
    ttl=settings.YOUTUBE_CACHE_TTL_SECONDS
)




class YouTubeDataPlugin(IConnectorPlugin):
    """
    Ingress Plugin for YouTube Data: Most Popular Videos & Targeted Keyword Search.
    Uses 100% verified data from official YouTube Data API v3 (part=snippet,statistics).
    Enforces strict publishedAfter date filtering and garbage rejection.
    """

    BASE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
    SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"

    def __init__(
        self,
        api_key: str = "",
        quota_manager: Optional[YouTubeQuotaManager] = None,
    ):
        self._api_key = api_key
        self._quota_manager = quota_manager

    async def _reserve(
        self,
        bucket: YouTubeQuotaBucket,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
    ) -> None:
        if self._quota_manager is None:
            raise ConnectorExecutionException(
                "A shared YouTube quota manager is required before provider calls."
            )
        await self._quota_manager.reserve(bucket, trigger, cost=1)

    async def _mark_exhausted(self, bucket: YouTubeQuotaBucket) -> YouTubeQuotaSnapshot:
        if self._quota_manager is None:
            raise ConnectorExecutionException(
                "A shared YouTube quota manager is required before provider calls."
            )
        return await self._quota_manager.mark_exhausted(bucket)

    @staticmethod
    def _error_reasons(response: httpx.Response) -> List[str]:
        try:
            payload = response.json()
        except Exception:
            return []
        return [
            str(item.get("reason"))
            for item in payload.get("error", {}).get("errors", [])
            if isinstance(item, dict) and item.get("reason")
        ]

    async def _provider_exhausted(
        self,
        bucket: YouTubeQuotaBucket,
        message: str,
    ) -> ConnectorQuotaExceededException:
        snapshot = await self._mark_exhausted(bucket)
        return ConnectorQuotaExceededException(
            message,
            bucket=bucket.value,
            used=snapshot.used,
            limit=snapshot.limit,
            reset_at=snapshot.reset_at,
            exhausted=snapshot.exhausted,
        )

    async def quota_status(self) -> Optional[dict]:
        if self._quota_manager is None:
            return None
        return await self._quota_manager.status()

    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    @property
    def name(self) -> str:
        return "YouTube Data API v3"

    def _geo_to_region_code(self, geo: GeoCode) -> str:
        geo_str = geo.value if hasattr(geo, "value") else str(geo)
        if geo_str.upper() in ("", "GLOBAL"):
            return "US"
        return geo_str.upper()

    def _geo_to_relevance_language(self, geo: GeoCode) -> Optional[str]:
        geo_str = geo.value if hasattr(geo, "value") else str(geo)
        lang_map = {
            "VN": "vi",
            "US": "en",
            "GB": "en",
            "JP": "ja",
            "DE": "de",
            "FR": "fr",
            "TH": "th",
            "ID": "id",
        }
        return lang_map.get(geo_str.upper(), None)

    def _timeframe_to_published_after(self, timeframe_str: str) -> Tuple[str, datetime]:
        """Convert timeframe expression to RFC 3339 formatted UTC datetime string."""
        now = datetime.now(timezone.utc)
        tf = str(timeframe_str).lower().strip()

        if tf in ["1d", "24h", "now 1-d", "last_24h"]:
            dt = now - timedelta(days=1)
        elif tf in ["7d", "now 7-d", "last_7d"]:
            dt = now - timedelta(days=7)
        elif tf in ["30d", "1m", "today 1-m", "last_30d"]:
            dt = now - timedelta(days=30)
        elif tf in ["90d", "3m", "today 3-m"]:
            dt = now - timedelta(days=90)
        elif tf in ["12m", "1y", "today 12-m"]:
            dt = now - timedelta(days=365)
        else:
            dt = now - timedelta(days=90 if "90" in tf else 7)

        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), dt

    def _is_garbage(self, title: str) -> bool:
        if not title or len(title.strip()) < 3:
            return True
        return False

    @property
    def feed_yields_candidate_topics(self) -> bool:
        """`chart=mostPopular` ranks the region's most-watched videos, whatever they are about.

        It is one quota unit and returns fifty rows, so an untargeted pass fills the corpus with
        national entertainment that no other platform corroborates. The keyword probe consumes
        one call from the separate search allocation and returns videos about a subject the pass
        actually asked for.
        """
        return False

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            await self._reserve(YouTubeQuotaBucket.DEFAULT_UNITS)
            params = {
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": "VN",
                "maxResults": 1,
                "key": self._api_key,
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self.BASE_API_URL, params=params)
                reasons = self._error_reasons(resp)
                if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                    await self._mark_exhausted(YouTubeQuotaBucket.DEFAULT_UNITS)
                return resp.status_code == 200
        except Exception as e:
            logger.warning("YouTube Plugin health check failed (%s).", type(e).__name__)
            return False

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        if not self._api_key:
            raise ConnectorExecutionException("YouTube API Key is missing or not configured.")

        region_code = self._geo_to_region_code(geo)
        max_results = max(1, min(limit, 50))

        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max_results,
            "key": self._api_key,
        }

        try:
            await self._reserve(YouTubeQuotaBucket.DEFAULT_UNITS)
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_API_URL, params=params)

                if response.status_code == 403:
                    reasons = self._error_reasons(response)
                    
                    if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                        logger.error("YouTube API quota exceeded.")
                        raise await self._provider_exhausted(
                            YouTubeQuotaBucket.DEFAULT_UNITS,
                            "YouTube API quota limit exceeded.",
                        )

                    raise ConnectorExecutionException("YouTube API 403 Forbidden: access denied.")

                response.raise_for_status()
                data = response.json()
        except ConnectorQuotaExceededException:
            raise
        except ConnectorExecutionException:
            raise
        except Exception as e:
            logger.error("Error calling YouTube Data API (%s).", type(e).__name__)
            raise ConnectorExecutionException(
                "Failed to fetch YouTube trending videos."
            ) from None

        signals: List[TrendSignal] = []
        items = data.get("items", [])

        for item in items:
            video_id = item.get("id")
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})

            title = snippet.get("title", "").strip()
            if not title or self._is_garbage(title):
                continue

            view_count = float(statistics.get("viewCount", 0))
            like_count = int(statistics.get("likeCount", 0))
            comment_count = int(statistics.get("commentCount", 0))
            published_at_str = snippet.get("publishedAt")
            
            try:
                if published_at_str:
                    published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                else:
                    published_at = datetime.now(timezone.utc)
            except Exception:
                published_at = datetime.now(timezone.utc)

            now_utc = datetime.now(timezone.utc)
            hours_diff = max(1.0, (now_utc - published_at).total_seconds() / 3600.0)
            velocity = round(view_count / hours_diff, 2)

            source_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None

            metadata = {
                "video_id": video_id,
                "channel_id": snippet.get("channelId"),
                "channel_title": snippet.get("channelTitle"),
                "category_id": snippet.get("categoryId"),
                "tags": snippet.get("tags", []),
                "views": int(view_count),
                "likes": like_count,
                "comments": comment_count,
                "published_at": published_at_str,
            }

            signal = TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title=title,
                metric_value=view_count,
                growth_velocity=velocity,
                source_url=source_url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
                published_at=published_at,
            )
            signals.append(signal)

        return signals

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
        custom_timeframe: Optional[str] = None,
        attestation: Optional[SearchAttestation] = None,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
    ) -> List[TrendSignal]:
        """
        Search verified YouTube videos by keyword and retrieve actual engagement metrics.
        Enforces strict publishedAfter filtering and non-domain garbage rejection.

        `attestation`, when given, records each keyword whose search call answered 200; a keyword
        whose call failed and was logged below measured nothing and is recorded as a failure.
        """
        if not self._api_key:
            if attestation is not None:
                attestation.blocked("No YouTube API key is configured.")
            return []

        signals: List[TrendSignal] = []
        seen_video_ids = set()
        region_code = self._geo_to_region_code(geo)
        relevance_lang = self._geo_to_relevance_language(geo)
        
        tf_str = custom_timeframe or (timeframe.value if hasattr(timeframe, "value") else str(timeframe))
        published_after_str, published_after_dt = self._timeframe_to_published_after(tf_str)
        if attestation is not None:
            # publishedAfter is sent with every search below, so the API filters to this window.
            attestation.applied_window(tf_str)

        for raw_kw in keywords:
            cache_key = f"{raw_kw.lower().strip()}|{region_code}|{tf_str}|{limit}"
            cached_sigs = _YOUTUBE_QUERY_CACHE.get(cache_key)
            if cached_sigs is not None:

                logger.info(f"Returning {len(cached_sigs)} cached YouTube signals for '{raw_kw}' (Quota preserved).")
                if attestation is not None:
                    attestation.executed(raw_kw)
                for cs in cached_sigs:
                    v_id = cs.metadata.get("video_id")
                    if v_id and v_id not in seen_video_ids:
                        seen_video_ids.add(v_id)
                        cloned_sig = TrendSignal(
                            platform=cs.platform,
                            raw_title=cs.raw_title,
                            metric_value=cs.metric_value,
                            growth_velocity=cs.growth_velocity,
                            source_url=cs.source_url,
                            geo_code=cs.geo_code,
                            cluster_id=cs.cluster_id,
                            mission_id=cs.mission_id,
                            metadata=dict(cs.metadata or {}),
                            captured_at=cs.captured_at,
                        )
                        signals.append(cloned_sig)
                continue


            kw_signals: List[TrendSignal] = []

            search_kw = raw_kw.strip()
            search_params = {
                "part": "snippet",
                "q": search_kw,
                "type": "video",
                "regionCode": region_code,
                "relevanceLanguage": relevance_lang,
                "maxResults": min(limit, 10),
                "order": "relevance",
                "publishedAfter": published_after_str,
                "key": self._api_key,
            }


            video_ids = []
            try:
                await self._reserve(YouTubeQuotaBucket.SEARCH_LIST, trigger)
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(self.SEARCH_API_URL, params=search_params)
                    if resp.status_code in [403, 429]:
                        reasons = self._error_reasons(resp)
                        if (
                            "quotaExceeded" in reasons
                            or "dailyLimitExceeded" in reasons
                            or "rateLimitExceeded" in reasons
                            or resp.status_code == 429
                        ):
                            if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                                error = await self._provider_exhausted(
                                    YouTubeQuotaBucket.SEARCH_LIST,
                                    "YouTube API search quota limit exceeded.",
                                )
                            else:
                                error = ConnectorQuotaExceededException(
                                    "YouTube API search rate limit exceeded."
                                )
                            logger.warning("YouTube search API quota exceeded or rate limited.")
                            raise error
                        resp.raise_for_status()
                    elif resp.status_code == 200:
                        search_data = resp.json()
                        if attestation is not None:
                            attestation.executed(raw_kw)
                        for item in search_data.get("items", []):
                            v_id = item.get("id", {}).get("videoId")
                            if v_id and v_id not in seen_video_ids:
                                video_ids.append(v_id)
                                seen_video_ids.add(v_id)
                    else:
                        resp.raise_for_status()

                    if video_ids:
                        # Batch call videos.list for genuine metrics
                        video_params = {
                            "part": "snippet,statistics",
                            "id": ",".join(video_ids),
                            "key": self._api_key,
                        }
                        await self._reserve(YouTubeQuotaBucket.DEFAULT_UNITS, trigger)
                        videos_resp = await client.get(self.BASE_API_URL, params=video_params)
                        if videos_resp.status_code in [403, 429]:
                            reasons = self._error_reasons(videos_resp)
                            if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                                error = await self._provider_exhausted(
                                    YouTubeQuotaBucket.DEFAULT_UNITS,
                                    "YouTube API metrics quota limit exceeded.",
                                )
                            else:
                                error = ConnectorQuotaExceededException(
                                    "YouTube API metrics rate limit exceeded."
                                )
                            if (
                                "quotaExceeded" in reasons
                                or "dailyLimitExceeded" in reasons
                                or "rateLimitExceeded" in reasons
                                or videos_resp.status_code == 429
                            ):
                                raise error
                            videos_resp.raise_for_status()
                        elif videos_resp.status_code == 200:
                            videos_data = videos_resp.json()
                            for v_item in videos_data.get("items", []):
                                v_id = v_item.get("id")
                                v_snippet = v_item.get("snippet", {})
                                v_stats = v_item.get("statistics", {})

                                title = sanitize_pii_text(v_snippet.get("title", "").strip())
                                if not title or self._is_garbage(title):
                                    continue

                                view_count = float(v_stats.get("viewCount", 0))
                                like_count = int(v_stats.get("likeCount", 0))
                                comment_count = int(v_stats.get("commentCount", 0))
                                pub_at_str = v_snippet.get("publishedAt")

                                try:
                                    if pub_at_str:
                                        pub_at = datetime.fromisoformat(pub_at_str.replace("Z", "+00:00"))
                                    else:
                                        pub_at = datetime.now(timezone.utc)
                                except Exception:
                                    pub_at = datetime.now(timezone.utc)

                                # Strict timeframe filtering: ignore videos older than cutoff
                                if pub_at < published_after_dt:
                                    continue

                                now_utc = datetime.now(timezone.utc)
                                hours_diff = max(1.0, (now_utc - pub_at).total_seconds() / 3600.0)
                                velocity = round(view_count / hours_diff, 2)

                                meta = {
                                    "keyword": raw_kw,
                                    "video_id": v_id,
                                    "channel_title": sanitize_pii_text(v_snippet.get("channelTitle") or ""),
                                    "channel_id": v_snippet.get("channelId"),
                                    "views": int(view_count),
                                    "likes": like_count,
                                    "comments": comment_count,
                                    "published_at": pub_at_str,
                                    "timeframe_filter": tf_str,
                                }


                                sig = TrendSignal(
                                    platform=PlatformType.YOUTUBE,
                                    raw_title=title,
                                    metric_value=view_count,
                                    growth_velocity=velocity,
                                    source_url=f"https://www.youtube.com/watch?v={v_id}",
                                    geo_code=geo,
                                    metadata=meta,
                                    captured_at=datetime.now(timezone.utc),
                                    published_at=pub_at,
                                )
                                kw_signals.append(sig)
                        else:
                            videos_resp.raise_for_status()

                    if kw_signals:
                        signals.extend(kw_signals)
                        _YOUTUBE_QUERY_CACHE[cache_key] = kw_signals
            except ConnectorQuotaExceededException:
                # Quota errors MUST bubble up to trip Circuit Breaker
                raise
            except ConnectorExecutionException:
                raise
            except Exception as e:
                logger.warning(
                    "YouTube search error for keyword %r (%s).",
                    raw_kw,
                    type(e).__name__,
                )
                if attestation is not None:
                    attestation.failed(raw_kw, type(e).__name__)
                    if raw_kw in attestation.queried:
                        attestation.queried.remove(raw_kw)



        return signals
