from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.config import settings
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    ConnectorExecutionException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe, timeframe_to_days
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text
from ignis.infrastructure.auth.meta_browser_auth import InstagramBrowserAuthManager
from ignis.infrastructure.auth.meta_oauth import InstagramAuthManager
from ignis.infrastructure.cache.insights_cache import InsightsTTLCache
from ignis.infrastructure.connectors.meta_browser_ingress import (
    build_cookie_header,
    caption_text,
    coerce_int,
    collect_json_payloads,
    extract_records,
)

logger = logging.getLogger(__name__)


class ReelsPlugin(IConnectorPlugin):
    """
    Ingress plugin for Instagram Reels.

    Primary path is the official Instagram Graph API (`/{ig-user-id}/media` plus
    per-media insights), extracting play_count, like_count, comment_count, caption
    and published_at. Hashtag search backs keyword probes.

    Ingress path is resolved per call, in order:
      1. Tier 2 Graph API when a usable OAuth token is stored.
      2. Tier 1 browser session (`InstagramBrowserAuthManager`) when the user signed in
         with an ordinary personal account and no Meta Developer App exists.
      3. Legacy unauthenticated public clips endpoint when nothing is bound.
    """

    GRAPH_BASE_URL = "https://graph.instagram.com"
    LEGACY_DISCOVER_URL = "https://www.instagram.com/api/v1/clips/discover/"
    BASE_URL = LEGACY_DISCOVER_URL  # retained for backward compatibility
    BROWSER_EXPLORE_URL = "https://www.instagram.com/reels/"
    BROWSER_HASHTAG_URL = "https://www.instagram.com/explore/tags/{hashtag}/"
    BROWSER_API_MARKERS = ["/api/v1/tags/", "/api/v1/clips/", "/graphql/query", "/api/graphql"]

    MEDIA_FIELDS = "id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count,username"
    INSIGHT_METRICS = "plays,reach,total_interactions"

    REQUEST_TIMEOUT_SECONDS = 20.0
    MAX_INSIGHT_CONCURRENCY = 5

    def __init__(
        self,
        auth_manager: Optional[InstagramAuthManager] = None,
        ig_user_id: Optional[str] = None,
        browser_auth_manager: Optional[InstagramBrowserAuthManager] = None,
        insights_cache: Optional[InsightsTTLCache] = None,
    ):
        self._auth_manager = auth_manager
        self._ig_user_id = ig_user_id or settings.INSTAGRAM_USER_ID
        self._browser_auth_manager = browser_auth_manager
        self._insights_cache = insights_cache or InsightsTTLCache()

    def set_auth_manager(self, auth_manager: InstagramAuthManager) -> None:
        self._auth_manager = auth_manager

    def set_browser_auth_manager(self, browser_auth_manager: InstagramBrowserAuthManager) -> None:
        self._browser_auth_manager = browser_auth_manager

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
        """
        Active synthetic health check:
        - If OAuth2 Tier: verify access token validity.
        - If Browser Session Tier 1: send a lightweight authenticated HTTP GET to verify
          the session cookie is still valid and not redirected to login.
        """
        if not self._auth_manager and not self._browser_auth_manager:
            return True
        try:
            if self._auth_manager:
                token = await self._auth_manager.get_access_token()
                if token:
                    return True

            storage_state = await self._browser_storage_state()
            if not storage_state:
                return False

            cookie_header = build_cookie_header(storage_state)
            if not cookie_header:
                return False

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                "Cookie": cookie_header,
            }
            async with httpx.AsyncClient(timeout=6.0, follow_redirects=False) as client:
                resp = await client.get(self.BROWSER_EXPLORE_URL, headers=headers)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Reels active health probe failed: {e}")
            return False

    async def _browser_storage_state(self) -> Optional[Dict[str, Any]]:
        if not self._browser_auth_manager:
            return None
        try:
            return await self._browser_auth_manager.get_storage_state()
        except Exception as e:
            logger.warning(f"Could not load the Instagram browser session: {e}")
            return None

    async def resolve_auth_tier(self) -> Tuple[str, Optional[Any]]:
        """
        Resolve the active authentication tier.
        Returns:
            ("oauth2", access_token) if Graph API token is valid.
            ("session_cookies", storage_state) if Playwright browser session exists.
            ("none", None) if neither is configured.
        """
        if self._auth_manager:
            try:
                token = await self._auth_manager.get_access_token()
                if token:
                    return "oauth2", token
            except Exception as e:
                logger.warning(f"Instagram OAuth token lookup error: {e}")

        storage_state = await self._browser_storage_state()
        if storage_state:
            logger.info("Instagram Reels: Graph OAuth token absent, active tier is Tier 1 Browser Session.")
            return "session_cookies", storage_state

        return "none", None

    async def _has_graph_token(self) -> bool:
        """Whether the Tier 2 Graph API path is usable right now."""
        tier, _ = await self.resolve_auth_tier()
        return tier == "oauth2"

    # --- Ingress ---

    @property
    def default_feed_scope(self) -> IngressScope:
        """The Graph feed is `/{ig-user-id}/media`, the authenticated account's own media.

        The browser path reads the Reels explore surface, which is public but personalised; both
        are therefore treated as account-scoped and kept out of market passes, where the hashtag
        probe in `search_signals` is used instead.
        """
        return IngressScope.OWN_PROFILE

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        """Fetch the account's Reels published inside the requested timeframe window.

        The surfaces reachable here are account-owned or personalised, so a public-market pass
        gets nothing: the registry routes those to the hashtag probe in `search_signals`.
        """
        if not scope.includes_own:
            logger.info(
                "Reels fetch_signals skipped: its feeds are account-owned and the requested "
                f"scope is {scope.value}."
            )
            return []

        tier, credential = await self.resolve_auth_tier()
        if tier == "session_cookies" and credential:
            return await self._fetch_via_browser_session(
                url=self.BROWSER_EXPLORE_URL, storage_state=credential, geo=geo, limit=limit
            )
        if tier == "none":
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
        tier, credential = await self.resolve_auth_tier()
        if tier == "session_cookies" and credential:
            return await self._search_via_browser_session(
                keywords=keywords, storage_state=credential, geo=geo, limit=limit
            )

        token = await self._require_token()
        if not self._ig_user_id:
            raise ConnectorAuthenticationException(
                "INSTAGRAM_USER_ID is not configured; hashtag search requires an Instagram Business/Creator account ID."
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
                    raw_title=sanitize_pii_text(caption[:200]) or f"Instagram Reel #{reel_id}",
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

        # The 15-minute worker pass re-reads the same media; serving them from the TTL
        # cache is what keeps this under Meta's 200 calls/user/hour budget.
        insights, pending = self._insights_cache.partition(
            PlatformType.REELS.value, media_ids, self.INSIGHT_METRICS
        )
        if not pending:
            return insights

        semaphore = asyncio.Semaphore(self.MAX_INSIGHT_CONCURRENCY)

        async def _one(media_id: str) -> Tuple[str, Dict[str, float]]:
            async with semaphore:
                payload = await self._graph_get(
                    f"{self._api_root}/{media_id}/insights",
                    params={"metric": self.INSIGHT_METRICS, "access_token": token},
                )
                return media_id, self._parse_insights(payload)

        results = await asyncio.gather(*[_one(mid) for mid in pending], return_exceptions=True)

        for result in results:
            if isinstance(result, (ConnectorAuthenticationException, ConnectorQuotaExceededException)):
                raise result
            if isinstance(result, Exception):
                logger.warning(f"Instagram insights lookup failed for one media item: {result}")
                continue
            media_id, metrics = result
            insights[media_id] = metrics
            self._insights_cache.set(PlatformType.REELS.value, media_id, self.INSIGHT_METRICS, metrics)
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
        tier, credential = await self.resolve_auth_tier()
        if tier == "oauth2" and credential:
            return credential

        raise ConnectorAuthenticationException(
            "No valid Instagram credentials available across all auth tiers. "
            "Tier 1 (Personal / Browser): Run `authenticate_instagram(browser_login=True)`. "
            "Tier 2 (Enterprise / Developer): Run `authenticate_instagram(auth_code=...)`."
        )

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

    # --- Tier 1 browser-session ingress ---

    async def _search_via_browser_session(
        self,
        keywords: List[str],
        storage_state: Dict[str, Any],
        geo: GeoCode,
        limit: int,
    ) -> List[TrendSignal]:
        """Walk each keyword's public hashtag page using the captured browser session."""
        all_signals: List[TrendSignal] = []
        seen_ids: set[str] = set()

        for keyword in [k.strip() for k in keywords[:10] if k and k.strip()]:
            hashtag = self._to_hashtag(keyword)
            if not hashtag:
                continue
            signals = await self._fetch_via_browser_session(
                url=self.BROWSER_HASHTAG_URL.format(hashtag=hashtag),
                storage_state=storage_state,
                geo=geo,
                limit=limit,
                keyword=keyword,
            )
            for signal in signals:
                reel_id = str(signal.metadata.get("reel_id") or "")
                if reel_id and reel_id in seen_ids:
                    continue
                seen_ids.add(reel_id)
                all_signals.append(signal)

        return all_signals

    async def _fetch_via_browser_session(
        self,
        url: str,
        storage_state: Dict[str, Any],
        geo: GeoCode,
        limit: int,
        keyword: Optional[str] = None,
    ) -> List[TrendSignal]:
        payloads = await collect_json_payloads(
            url=url,
            storage_state=storage_state,
            url_markers=self.BROWSER_API_MARKERS,
            geo=geo,
        )
        records = extract_records(
            payloads,
            is_record=self._is_browser_reel,
            identity=lambda node: str(node.get("pk") or node.get("id") or ""),
            limit=min(max(limit, 1), 100),
        )
        return [self._map_browser_reel(node, geo=geo, keyword=keyword) for node in records]

    @staticmethod
    def _is_browser_reel(node: Dict[str, Any]) -> bool:
        """Match the shape of a public Reel item rather than a fixed GraphQL envelope path."""
        if not (node.get("pk") or node.get("id")):
            return False
        if not isinstance(node.get("code"), str):
            return False
        # media_type 2 is video on Instagram's private payloads; clips metadata marks Reels.
        return bool(
            node.get("video_versions")
            or node.get("clips_metadata")
            or node.get("play_count") is not None
            or coerce_int(node.get("media_type")) == 2
        )

    def _map_browser_reel(
        self,
        node: Dict[str, Any],
        geo: GeoCode,
        keyword: Optional[str],
    ) -> TrendSignal:
        reel_id = str(node.get("pk") or node.get("id") or "")
        code = str(node.get("code") or "")
        caption = caption_text(node)
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        # Author id, matched by the self-content guard when only the numeric account is known.
        author_id = str(user.get("pk") or user.get("id") or "")
        clips = node.get("clips_metadata") if isinstance(node.get("clips_metadata"), dict) else {}
        music = clips.get("music_info") if isinstance(clips.get("music_info"), dict) else {}

        play_count = coerce_int(node.get("play_count") or node.get("view_count"))
        like_count = coerce_int(node.get("like_count"))
        comment_count = coerce_int(node.get("comment_count"))

        return TrendSignal(
            platform=PlatformType.REELS,
            raw_title=sanitize_pii_text(caption[:200]) or f"Instagram Reel #{reel_id}",
            metric_value=float(play_count) if play_count > 0 else float(like_count),
            growth_velocity=0.0,
            source_url=f"https://www.instagram.com/reel/{code}/" if code else None,
            geo_code=geo,
            metadata={
                "reel_id": reel_id,
                "username": str(user.get("username") or ""),
                "user_id": author_id,
                "play_count": play_count,
                "like_count": like_count,
                "comment_count": comment_count,
                "music_title": str((music.get("music_asset_info") or {}).get("title") or "")
                if isinstance(music.get("music_asset_info"), dict) else "",
                "caption": caption,
                "published_at": self._normalize_epoch(node.get("taken_at")),
                "source": "instagram_browser_session",
                "tier": "TIER_1_BROWSER_SESSION",
                **({"matched_keyword": keyword} if keyword else {}),
            },
            captured_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _normalize_epoch(raw: Any) -> Optional[str]:
        """Instagram's private payloads carry `taken_at` as unix seconds."""
        if not raw:
            return None
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None

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
            logger.error(f"Error fetching Reels: {e}")
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
                    raw_title=sanitize_pii_text(caption[:200]) or f"Instagram Reel #{reel_id}",
                    metric_value=play_count,
                    growth_velocity=0.0,
                    source_url=url,
                    geo_code=geo,
                    metadata={
                        "reel_id": reel_id,
                        "username": username,
                        "user_id": str((item.get("user") or {}).get("pk") or (item.get("user") or {}).get("id") or ""),
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
