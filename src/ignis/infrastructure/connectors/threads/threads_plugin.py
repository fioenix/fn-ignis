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
from ignis.infrastructure.auth.meta_oauth import ThreadsAuthManager

logger = logging.getLogger(__name__)


class ThreadsPlugin(IConnectorPlugin):
    """
    Ingress plugin for Meta Threads via the official Threads Graph API (OAuth 2.0).

    Text-based discussion signals: post text, views/impressions, likes and replies,
    normalized to UTC timestamps. Invalid/expired tokens (401/403) and rate limits
    (429) raise typed exceptions so the registry's circuit breaker trips instead of
    silently returning an empty, apparently-healthy result set.

    When no auth manager is bound, the plugin falls back to the legacy unauthenticated
    public trending endpoint (best-effort, no insights).
    """

    GRAPH_BASE_URL = "https://graph.threads.net"
    LEGACY_TRENDING_URL = "https://www.threads.net/api/trending"

    THREAD_FIELDS = "id,text,permalink,timestamp,username,media_type,is_quote_post"
    INSIGHT_METRICS = "views,likes,replies,reposts,quotes"

    REQUEST_TIMEOUT_SECONDS = 20.0
    MAX_INSIGHT_CONCURRENCY = 5

    def __init__(self, auth_manager: Optional[ThreadsAuthManager] = None):
        self._auth_manager = auth_manager

    def set_auth_manager(self, auth_manager: ThreadsAuthManager) -> None:
        self._auth_manager = auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.THREADS

    @property
    def name(self) -> str:
        return "Threads Trending Discussions"

    @property
    def _api_root(self) -> str:
        return f"{self.GRAPH_BASE_URL}/{settings.THREADS_API_VERSION}"

    async def is_healthy(self) -> bool:
        """
        Report health honestly: an OAuth-backed connector without a usable token is
        NOT healthy, because every ingress call would fail authentication.
        """
        if not self._auth_manager:
            # Legacy unauthenticated public mode — nothing to verify.
            return True
        try:
            return (await self._auth_manager.get_access_token()) is not None
        except Exception as e:
            logger.warning(f"Threads health check failed: {e}")
            return False

    # --- Ingress ---

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        """Fetch top/recent threads within the requested timeframe window."""
        if not self._auth_manager:
            return await self._fetch_legacy_public(geo=geo, limit=limit)

        token = await self._require_token()
        since, until = self._resolve_window(timeframe)

        payload = await self._graph_get(
            f"{self._api_root}/me/threads",
            params={
                "fields": self.THREAD_FIELDS,
                "since": since,
                "until": until,
                "limit": min(max(limit, 1), 100),
                "access_token": token,
            },
        )

        items = payload.get("data") or []
        return await self._map_items(items, token=token, geo=geo)

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
    ) -> List[TrendSignal]:
        """Probe the Threads keyword search endpoint for each research keyword."""
        if not self._auth_manager:
            return await self._fetch_legacy_public(geo=geo, limit=limit)

        token = await self._require_token()
        since, until = self._resolve_window(timeframe)

        all_signals: List[TrendSignal] = []
        seen_ids: set[str] = set()

        for keyword in [k.strip() for k in keywords[:10] if k and k.strip()]:
            payload = await self._graph_get(
                f"{self._api_root}/keyword_search",
                params={
                    "q": keyword,
                    "search_type": "TOP",
                    "fields": self.THREAD_FIELDS,
                    "since": since,
                    "until": until,
                    "limit": min(max(limit, 1), 100),
                    "access_token": token,
                },
            )
            items = [it for it in (payload.get("data") or []) if str(it.get("id")) not in seen_ids]
            for it in items:
                seen_ids.add(str(it.get("id")))

            signals = await self._map_items(items, token=token, geo=geo, keyword=keyword)
            all_signals.extend(signals)

        return all_signals

    # --- Mapping ---

    async def _map_items(
        self,
        items: List[Dict[str, Any]],
        token: str,
        geo: GeoCode,
        keyword: Optional[str] = None,
    ) -> List[TrendSignal]:
        insights = await self._fetch_insights_batch([str(it.get("id")) for it in items if it.get("id")], token)

        signals: List[TrendSignal] = []
        for item in items:
            post_id = str(item.get("id") or "")
            text = (item.get("text") or "").strip()
            username = item.get("username") or ""
            metrics = insights.get(post_id, {})

            views = float(metrics.get("views", 0) or 0)
            likes = int(metrics.get("likes", 0) or 0)
            replies = int(metrics.get("replies", 0) or 0)

            # Views/impressions is the primary demand metric; fall back to likes when
            # the insights scope is not granted for this token.
            metric_value = views if views > 0 else float(likes)

            signals.append(
                TrendSignal(
                    platform=PlatformType.THREADS,
                    raw_title=text[:200] or f"Threads Post #{post_id}",
                    metric_value=metric_value,
                    growth_velocity=0.0,
                    source_url=item.get("permalink"),
                    geo_code=geo,
                    metadata={
                        "post_id": post_id,
                        "username": username,
                        "views": int(views),
                        "like_count": likes,
                        "reply_count": replies,
                        "reposts": int(metrics.get("reposts", 0) or 0),
                        "quotes": int(metrics.get("quotes", 0) or 0),
                        "media_type": item.get("media_type"),
                        "published_at": self._normalize_timestamp(item.get("timestamp")),
                        "source": "threads_graph_api",
                        **({"matched_keyword": keyword} if keyword else {}),
                    },
                    captured_at=datetime.now(timezone.utc),
                )
            )
        return signals

    async def _fetch_insights_batch(self, post_ids: List[str], token: str) -> Dict[str, Dict[str, float]]:
        """Fetch per-post insight metrics with bounded concurrency; degrade gracefully on failure."""
        if not post_ids:
            return {}

        semaphore = asyncio.Semaphore(self.MAX_INSIGHT_CONCURRENCY)

        async def _one(post_id: str) -> tuple[str, Dict[str, float]]:
            async with semaphore:
                payload = await self._graph_get(
                    f"{self._api_root}/{post_id}/insights",
                    params={"metric": self.INSIGHT_METRICS, "access_token": token},
                )
                return post_id, self._parse_insights(payload)

        results = await asyncio.gather(*[_one(pid) for pid in post_ids], return_exceptions=True)

        insights: Dict[str, Dict[str, float]] = {}
        for result in results:
            if isinstance(result, (ConnectorAuthenticationException, ConnectorQuotaExceededException)):
                # Token rejection / soft-block must surface, not be swallowed per-post.
                raise result
            if isinstance(result, Exception):
                logger.warning(f"Threads insights lookup failed for one post: {result}")
                continue
            post_id, metrics = result
            insights[post_id] = metrics
        return insights

    @staticmethod
    def _parse_insights(payload: Dict[str, Any]) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        for entry in payload.get("data") or []:
            name = entry.get("name")
            if not name:
                continue
            if "total_value" in entry and isinstance(entry["total_value"], dict):
                metrics[name] = float(entry["total_value"].get("value", 0) or 0)
                continue
            values = entry.get("values") or []
            if values and isinstance(values[0], dict):
                metrics[name] = float(values[0].get("value", 0) or 0)
        return metrics

    @staticmethod
    def _normalize_timestamp(raw: Any) -> Optional[str]:
        """Normalize a Graph API ISO-8601 timestamp to UTC ISO format."""
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
        """Convert the domain timeframe into the Graph API's since/until unix seconds."""
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=timeframe_to_days(timeframe))
        return str(int(since.timestamp())), str(int(now.timestamp()))

    # --- HTTP + error classification ---

    async def _require_token(self) -> str:
        token = await self._auth_manager.get_access_token()
        if not token:
            raise ConnectorAuthenticationException(
                "No valid Threads OAuth token available. Run the `authenticate_threads` MCP tool "
                "to complete the Graph API OAuth 2.0 flow."
            )
        return token

    async def _graph_get(self, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.REQUEST_TIMEOUT_SECONDS) as client:
                resp = await client.get(url, params=params)
        except httpx.HTTPError as e:
            raise ConnectorExecutionException(f"Threads Graph API transport error for {url}: {e}") from e

        status = resp.status_code
        if status == 200:
            try:
                return resp.json()
            except Exception as e:
                raise ConnectorExecutionException(f"Threads Graph API returned malformed JSON: {e}") from e

        detail = self._extract_error_detail(resp)
        await self._record_failure(status, detail, url)

        if status in (401, 403):
            raise ConnectorAuthenticationException(
                f"Threads Graph API rejected the credentials (HTTP {status}): {detail}. "
                "The token is invalid, expired, or lacks the required scope."
            )
        if status == 429:
            raise ConnectorQuotaExceededException(
                f"Threads Graph API rate limit reached (HTTP 429): {detail}"
            )
        raise ConnectorExecutionException(f"Threads Graph API request failed (HTTP {status}): {detail}")

    async def _record_failure(self, status: int, detail: str, url: str) -> None:
        if not self._auth_manager:
            return
        try:
            await self._auth_manager.record_api_failure(status, detail, endpoint=url)
        except Exception as e:
            logger.warning(f"Could not record Threads API failure to audit log: {e}")

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
        """Best-effort public trending scrape used only when no OAuth manager is bound."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(self.LEGACY_TRENDING_URL, params={"limit": min(limit, 50)})
                if resp.status_code != 200:
                    logger.warning(f"Threads response non-200: {resp.status_code}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"Lỗi khi cào Threads: {e}")
            raise ConnectorExecutionException(f"Failed to fetch Threads signals: {e}") from e

        signals: List[TrendSignal] = []
        media_list = data.get("data", {}).get("mediaData", []) or data.get("items", [])

        for item in media_list:
            post_id = item.get("id")
            code = item.get("code", "")
            caption_obj = item.get("caption", {})
            caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else str(caption_obj or "")
            user = item.get("user", {})
            username = user.get("username", "")

            like_count = float(item.get("like_count", 0))
            reply_count = int(item.get("reply_count", 0))

            url = f"https://www.threads.net/@{username}/post/{code}" if username and code else None

            signals.append(
                TrendSignal(
                    platform=PlatformType.THREADS,
                    raw_title=caption[:200] or f"Threads Post #{post_id}",
                    metric_value=like_count,
                    growth_velocity=0.0,
                    source_url=url,
                    geo_code=geo,
                    metadata={
                        "post_id": post_id,
                        "username": username,
                        "reply_count": reply_count,
                        "like_count": int(like_count),
                        "source": "threads_public_trending",
                    },
                    captured_at=datetime.now(timezone.utc),
                )
            )

        return signals
