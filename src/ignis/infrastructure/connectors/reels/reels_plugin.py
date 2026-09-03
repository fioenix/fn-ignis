from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.config import settings
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    ConnectorExecutionException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe, timeframe_to_days
from ignis.infrastructure.auth.meta_oauth import InstagramAuthManager

logger = logging.getLogger(__name__)


class ReelsPlugin(IConnectorPlugin):
    """
    Ingress plugin for Instagram Reels.

    Primary path is the official Instagram Graph API (`/{ig-user-id}/media` plus
    per-media insights), extracting play_count, like_count, comment_count, caption
    and published_at. Hashtag search backs keyword probes. Falls back to the legacy
    public clips endpoint only when no OAuth manager is bound.
    """

    GRAPH_BASE_URL = "https://graph.instagram.com"
    LEGACY_DISCOVER_URL = "https://www.instagram.com/api/v1/clips/discover/"
    BASE_URL = LEGACY_DISCOVER_URL  # retained for backward compatibility

    MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,username"
    INSIGHT_METRICS = "plays,reach,total_interactions"

    REQUEST_TIMEOUT_SECONDS = 20.0
    MAX_INSIGHT_CONCURRENCY = 5

    def __init__(
        self,
        auth_manager: Optional[InstagramAuthManager] = None,
        ig_user_id: Optional[str] = None,
    ):
        self._auth_manager = auth_manager
        self._ig_user_id = ig_user_id or settings.INSTAGRAM_USER_ID

    def set_auth_manager(self, auth_manager: InstagramAuthManager) -> None:
        self._auth_manager = auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.REELS

    @property
    def name(self) -> str:
        return "Instagram Reels Trending"

    @property
    def _api_root(self) -> str:
        return f"{self.GRAPH_BASE_URL}/{settings.INSTAGRAM_API_VERSION}"

    async def is_healthy(self) -> bool:
        """An OAuth-backed connector without a usable token is not healthy."""
        if not self._auth_manager:
            return True
        try:
            return (await self._auth_manager.get_access_token()) is not None
        except Exception as e:
            logger.warning(f"Reels health check failed: {e}")
            return False

    # --- Ingress ---

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        """Fetch the account's Reels published inside the requested timeframe window."""
        if not self._auth_manager:
            return await self._fetch_legacy_public(geo=geo, limit=limit)

        token = await self._require_token()
        if not self._ig_user_id:
            raise ConnectorAuthenticationException(
                "INSTAGRAM_USER_ID is not configured; the Reels Graph API ingress needs an "
                "Instagram Business/Creator account ID."
            )

        since, until = self._resolve_window(timeframe)
        payload = await self._graph_get(
            f"{self._api_root}/{self._ig_user_id}/media",
            params={
                "fields": self.MEDIA_FIELDS,
                "since": since,
                "until": until,
                "limit": min(max(limit, 1), 100),
                "access_token": token,
            },
        )

        items = [it for it in (payload.get("data") or []) if self._is_reel(it)]
        return await self._map_items(items, token=token, geo=geo)

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
    ) -> List[TrendSignal]:
        """Probe top Reels per keyword through the Instagram hashtag search endpoints."""
        if not self._auth_manager:
            return await self._fetch_legacy_public(geo=geo, limit=limit)

        token = await self._require_token()
        if not self._ig_user_id:
            raise ConnectorAuthenticationException(
                "INSTAGRAM_USER_ID is not configured; hashtag search requires a bound Instagram account ID."
            )

        all_signals: List[TrendSignal] = []
        seen_ids: set[str] = set()

        for keyword in [k.strip() for k in keywords[:10] if k and k.strip()]:
            hashtag = self._to_hashtag(keyword)
            hashtag_id = await self._resolve_hashtag_id(hashtag, token)
            if not hashtag_id:
                continue

            payload = await self._graph_get(
                f"{self._api_root}/{hashtag_id}/top_media",
                params={
                    "user_id": self._ig_user_id,
                    "fields": self.MEDIA_FIELDS,
                    "limit": min(max(limit, 1), 50),
                    "access_token": token,
                },
            )
            items = [
                it for it in (payload.get("data") or [])
                if self._is_reel(it) and str(it.get("id")) not in seen_ids
            ]
            for it in items:
                seen_ids.add(str(it.get("id")))

            all_signals.extend(await self._map_items(items, token=token, geo=geo, keyword=keyword))

        return all_signals

    async def _resolve_hashtag_id(self, hashtag: str, token: str) -> Optional[str]:
        payload = await self._graph_get(
            f"{self._api_root}/ig_hashtag_search",
            params={"user_id": self._ig_user_id, "q": hashtag, "access_token": token},
        )
        data = payload.get("data") or []
        if not data:
            logger.info(f"Instagram returned no hashtag id for '{hashtag}'.")
            return None
        return str(data[0].get("id")) or None

    @staticmethod
    def _to_hashtag(keyword: str) -> str:
        """Instagram hashtag search accepts a single alphanumeric token without '#'."""
        return "".join(ch for ch in keyword if ch.isalnum()).lower()

    @staticmethod
    def _is_reel(item: Dict[str, Any]) -> bool:
        product_type = (item.get("media_product_type") or "").upper()
        if product_type:
            return product_type == "REELS"
        # top_media does not always expose media_product_type; keep any video.
        return (item.get("media_type") or "").upper() in ("VIDEO", "")

    # --- Mapping ---

    async def _map_items(
        self,
        items: List[Dict[str, Any]],
        token: str,
        geo: GeoCode,
        keyword: Optional[str] = None,
    ) -> List[TrendSignal]:
        insights = await self._fetch_insights_batch(
            [str(it.get("id")) for it in items if it.get("id")], token
        )

        signals: List[TrendSignal] = []
        for item in items:
            reel_id = str(item.get("id") or "")
            caption = (item.get("caption") or "").strip()
            like_count = int(item.get("like_count", 0) or 0)
            comment_count = int(item.get("comments_count", 0) or 0)
            metrics = insights.get(reel_id, {})
            play_count = int(metrics.get("plays", 0) or 0)

            # Plays is the demand signal; without the insights scope fall back to likes.
            metric_value = float(play_count) if play_count > 0 else float(like_count)

            signals.append(
                TrendSignal(
                    platform=PlatformType.REELS,
                    raw_title=caption[:200] or f"Instagram Reel #{reel_id}",
                    metric_value=metric_value,
                    growth_velocity=0.0,
                    source_url=item.get("permalink"),
                    geo_code=geo,
                    metadata={
                        "reel_id": reel_id,
                        "username": item.get("username", ""),
                        "play_count": play_count,
                        "like_count": like_count,
                        "comment_count": comment_count,
                        "reach": int(metrics.get("reach", 0) or 0),
                        "total_interactions": int(metrics.get("total_interactions", 0) or 0),
                        "caption": caption,
                        "published_at": self._normalize_timestamp(item.get("timestamp")),
                        "source": "instagram_graph_api",
                        **({"matched_keyword": keyword} if keyword else {}),
                    },
                    captured_at=datetime.now(timezone.utc),
                )
            )
        return signals

    async def _fetch_insights_batch(self, media_ids: List[str], token: str) -> Dict[str, Dict[str, float]]:
        if not media_ids:
            return {}

        semaphore = asyncio.Semaphore(self.MAX_INSIGHT_CONCURRENCY)

        async def _one(media_id: str) -> tuple[str, Dict[str, float]]:
            async with semaphore:
                payload = await self._graph_get(
                    f"{self._api_root}/{media_id}/insights",
                    params={"metric": self.INSIGHT_METRICS, "access_token": token},
                )
                return media_id, self._parse_insights(payload)

        results = await asyncio.gather(*[_one(mid) for mid in media_ids], return_exceptions=True)

        insights: Dict[str, Dict[str, float]] = {}
        for result in results:
            if isinstance(result, (ConnectorAuthenticationException, ConnectorQuotaExceededException)):
                raise result
            if isinstance(result, Exception):
                logger.warning(f"Instagram insights lookup failed for one media item: {result}")
                continue
            media_id, metrics = result
            insights[media_id] = metrics
        return insights

    @staticmethod
    def _parse_insights(payload: Dict[str, Any]) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        for entry in payload.get("data") or []:
            name = entry.get("name")
            if not name:
                continue
            if isinstance(entry.get("total_value"), dict):
                metrics[name] = float(entry["total_value"].get("value", 0) or 0)
                continue
            values = entry.get("values") or []
            if values and isinstance(values[0], dict):
                metrics[name] = float(values[0].get("value", 0) or 0)
        return metrics

    @staticmethod
    def _normalize_timestamp(raw: Any) -> Optional[str]:
        if not raw:
            return None
        text = str(raw).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return str(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _resolve_window(timeframe: Timeframe) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=timeframe_to_days(timeframe))
        return str(int(since.timestamp())), str(int(now.timestamp()))

    # --- HTTP + error classification ---

    async def _require_token(self) -> str:
        token = await self._auth_manager.get_access_token()
        if not token:
            raise ConnectorAuthenticationException(
                "No valid Instagram OAuth token available for the Reels connector."
            )
        return token

    async def _graph_get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ConnectorExecutionException(f"Instagram Graph API transport error for {url}: {e}") from e

        status = resp.status_code
        if status == 200:
            try:
                return resp.json()
            except Exception as e:
                raise ConnectorExecutionException(f"Instagram Graph API returned malformed JSON: {e}") from e

        detail = self._extract_error_detail(resp)
        await self._record_failure(status, detail, url)

        if status in (401, 403):
            raise ConnectorAuthenticationException(
                f"Instagram Graph API rejected the credentials (HTTP {status}): {detail}. "
                "The token is invalid, expired, or lacks the required scope."
            )
        if status == 429:
            raise ConnectorQuotaExceededException(
                f"Instagram Graph API rate limit reached (HTTP 429): {detail}"
            )
        raise ConnectorExecutionException(f"Instagram Graph API request failed (HTTP {status}): {detail}")

    async def _record_failure(self, status: int, detail: str, url: str) -> None:
        if not self._auth_manager:
            return
        try:
            await self._auth_manager.record_api_failure(status, detail, endpoint=url)
        except Exception as e:
            logger.warning(f"Could not record Instagram API failure to audit log: {e}")

    @staticmethod
    def _extract_error_detail(resp: httpx.Response) -> str:
        try:
            body = resp.json()
        except Exception:
            return (resp.text or "")[:300]
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return str(err.get("message") or err)
            if err:
                return str(err)
        return str(body)[:300]

    # --- Legacy unauthenticated fallback ---

    async def _fetch_legacy_public(self, geo: GeoCode, limit: int) -> List[TrendSignal]:
        """Best-effort public clips discovery used only when no OAuth manager is bound."""
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(self.LEGACY_DISCOVER_URL, params={"max_id": "", "page_size": min(limit, 50)})
                if resp.status_code != 200:
                    logger.warning(f"Reels response non-200: {resp.status_code}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"Lỗi khi cào Reels: {e}")
            raise ConnectorExecutionException(f"Failed to fetch Reels signals: {e}") from e

        signals: List[TrendSignal] = []
        items = data.get("items", []) or data.get("clips", [])

        for item in items:
            reel_id = item.get("id")
            code = item.get("code", "")
            caption_obj = item.get("caption", {})
            caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else str(caption_obj or "")
            user = item.get("user", {})
            username = user.get("username", "")

            play_count = float(item.get("play_count", 0))
            like_count = int(item.get("like_count", 0))
            music = item.get("music_metadata", {})
            music_title = music.get("music_title", "")

            url = f"https://www.instagram.com/reel/{code}/" if code else None

            signals.append(
                TrendSignal(
                    platform=PlatformType.REELS,
                    raw_title=caption[:200] or f"Instagram Reel #{reel_id}",
                    metric_value=play_count,
                    growth_velocity=0.0,
                    source_url=url,
                    geo_code=geo,
                    metadata={
                        "reel_id": reel_id,
                        "username": username,
                        "music_title": music_title,
                        "play_count": int(play_count),
                        "like_count": like_count,
                        "likes": like_count,
                        "comment_count": int(item.get("comment_count", 0)),
                        "comments": int(item.get("comment_count", 0)),
                        "caption": caption,
                        "source": "instagram_public_clips",
                    },
                    captured_at=datetime.now(timezone.utc),
                )
            )

        return signals
