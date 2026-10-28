from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from ignis.application.ports.connector_port import IConnectorPlugin, SearchAttestation
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope, PlatformType, Timeframe, timeframe_to_days
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text
from ignis.infrastructure.auth.meta_browser_auth import ThreadsBrowserAuthManager
from ignis.infrastructure.auth.meta_oauth import ThreadsAuthManager
from ignis.infrastructure.cache.insights_cache import InsightsTTLCache
from ignis.infrastructure.connectors.meta_browser_ingress import caption_text, coerce_int


class ThreadsPlugin(IConnectorPlugin):
    """Compatibility port for retired internal collection; evidence comes from host tickets.

    Pure legacy mappers remain for retained-evidence conformance, with no production collector.
    """

    host_collection_required = True
    retry_failed_keywords = False
    UNAVAILABLE_REASON = "HOST_BROWSER_REQUIRED: Internal Threads collection is retired; prepare an authorized host-browser search."
    KEYWORD_SEARCH_PUBLIC = "PUBLIC_SEARCH_ENABLED"
    KEYWORD_SEARCH_SELF_ONLY = "SELF_ONLY"
    KEYWORD_SEARCH_NOT_PERMITTED = "NOT_PERMITTED"
    KEYWORD_SEARCH_INCONCLUSIVE = "INCONCLUSIVE"
    KEYWORD_SEARCH_NO_TOKEN = "NO_GRAPH_TOKEN"

    async def keyword_search_blocked_reason(self) -> str:
        return self.UNAVAILABLE_REASON

    def __init__(
        self,
        auth_manager: Optional[ThreadsAuthManager] = None,
        browser_auth_manager: Optional[ThreadsBrowserAuthManager] = None,
        insights_cache: Optional[InsightsTTLCache] = None,
    ):
        self._auth_manager = auth_manager
        self._browser_auth_manager = browser_auth_manager
        self._insights_cache = insights_cache or InsightsTTLCache()

    def set_auth_manager(self, auth_manager: ThreadsAuthManager) -> None:
        self._auth_manager = auth_manager

    def set_browser_auth_manager(self, browser_auth_manager: ThreadsBrowserAuthManager) -> None:
        self._browser_auth_manager = browser_auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.THREADS

    @property
    def name(self) -> str:
        return "Threads Trending Discussions"

    async def is_healthy(self) -> bool:
        """Stored credentials do not make the retired internal collection path healthy."""
        return False

    async def resolve_auth_tier(self) -> Tuple[str, Optional[Any]]:
        """Retained port compatibility; credentials are inspected by the auth tools only."""
        return "host_required", None

    async def resolve_ingest_runtime(self) -> IngestRuntime:
        """Host evidence requires browser authority; this plugin never opens a browser."""
        return IngestRuntime.BROWSER

    @property
    def default_feed_scope(self) -> IngressScope:
        """Retain the legacy account-scoped declaration; fetching it is unavailable."""
        return IngressScope.OWN_PROFILE

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        """Retained signature; all internal feed collection, including OWN_PROFILE, is retired."""
        raise ConnectorCapabilityUnavailableException(self.UNAVAILABLE_REASON)

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
        attestation: Optional[SearchAttestation] = None,
    ) -> List[TrendSignal]:
        """Only an explicitly authorized host ticket can collect Threads keyword evidence."""
        if attestation is not None:
            attestation.blocked(self.UNAVAILABLE_REASON)
        raise ConnectorCapabilityUnavailableException(self.UNAVAILABLE_REASON)

    async def check_keyword_search_access(self, query: str) -> Dict[str, Any]:
        """Compatibility diagnostic, without a provider call or credential access."""
        return {"status": "UNAVAILABLE", "reason_code": "HOST_BROWSER_REQUIRED", "detail": self.UNAVAILABLE_REASON, "recommended_path": "prepare_host_browser_search(source=\"threads\")"}

    async def fetch_trending_topics(
        self,
        geo: GeoCode = GeoCode.VN,
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        """Internal trending collection is unavailable; no browser, cookie HTTP or OAuth fallback."""
        raise ConnectorCapabilityUnavailableException(self.UNAVAILABLE_REASON)

    async def fetch_search_suggestions(
        self,
        keyword: str,
        geo: GeoCode = GeoCode.VN,
        limit: int = 10,
    ) -> List[str]:
        """Internal suggestions collection is unavailable; no hidden browser or API probe."""
        raise ConnectorCapabilityUnavailableException(self.UNAVAILABLE_REASON)

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
            published_at = self._normalize_timestamp(item.get("timestamp"))
            try:
                publication_time = datetime.fromisoformat(published_at) if published_at else None
            except ValueError:
                publication_time = None

            signals.append(
                TrendSignal(
                    platform=PlatformType.THREADS,
                    raw_title=sanitize_pii_text(text[:200]) or f"Threads Post #{post_id}",
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
                        "published_at": published_at,
                        "excerpt": sanitize_pii_text(text),
                        "source": "threads_graph_api",
                        **({"matched_keyword": keyword} if keyword else {}),
                    },
                    captured_at=datetime.now(timezone.utc),
                    published_at=publication_time,
                )
            )
        return signals

    async def _fetch_insights_batch(self, post_ids: List[str], token: str) -> Dict[str, Dict[str, float]]:
        """Legacy mapping is pure; retired Threads collection never fetches insights."""
        return {}

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

    @staticmethod
    def _record_matched_query(signal: TrendSignal, keyword: str) -> None:
        """Keep observed query hits without changing the first-query clustering contract."""
        queries = signal.metadata.setdefault("matched_keywords", [])
        if keyword not in queries:
            queries.append(keyword)

    @staticmethod
    def _search_records(payloads: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Only admitted roots are query results; nested quotes have no rank authority."""
        records: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for payload in payloads:
            for post in payload["posts"]:
                identity = str(post.get("pk") or post.get("id"))
                if identity not in seen:
                    seen.add(identity)
                    records.append(post)
                    if len(records) >= min(max(limit, 1), 100):
                        return records
        return records

    @classmethod
    def _public_search_results(cls, payload: Any) -> Optional[Dict[str, Any]]:
        """Project only supported public result paths; unknown or malformed envelopes fail closed."""
        if not isinstance(payload, dict) or payload.get("errors"):
            return None
        data = payload.get("data")
        result = data.get("searchResults") if isinstance(data, dict) else None
        edges = result.get("edges") if isinstance(result, dict) else None
        if not isinstance(edges, list):
            return None
        posts: List[Dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") if isinstance(edge, dict) else None
            if not isinstance(node, dict):
                return None
            if cls._is_browser_post(node):
                posts.append(node)
                continue
            thread = node.get("thread")
            items = thread.get("thread_items") if isinstance(thread, dict) else None
            if not isinstance(items, list):
                return None
            for item in items:
                post = item.get("post") if isinstance(item, dict) else None
                if not isinstance(post, dict) or not cls._is_browser_post(post):
                    return None
                posts.append(post)
        return {"posts": posts}

    @staticmethod
    def _is_browser_post(node: Dict[str, Any]) -> bool:
        """Match the shape of a Threads post rather than a fixed GraphQL envelope path."""
        if not (node.get("pk") or node.get("id")):
            return False
        if not isinstance(node.get("code"), str):
            return False
        return bool(node.get("caption") is not None or node.get("text_post_app_info"))

    def _map_browser_post(
        self,
        node: Dict[str, Any],
        geo: GeoCode,
        keyword: Optional[str],
    ) -> TrendSignal:
        post_id = str(node.get("pk") or node.get("id") or "")
        code = str(node.get("code") or "")
        text = caption_text(node)
        user = node.get("user") if isinstance(node.get("user"), dict) else {}
        username = str(user.get("username") or "")
        # The author id travels with the payload and is what the self-content guard matches on:
        # a browser session knows its own numeric account id but not always its handle.
        author_id = str(user.get("pk") or user.get("id") or "")
        app_info = node.get("text_post_app_info") if isinstance(node.get("text_post_app_info"), dict) else {}

        likes = coerce_int(node.get("like_count"))
        replies = coerce_int(app_info.get("direct_reply_count"))
        published_at = self._normalize_epoch(node.get("taken_at"))

        return TrendSignal(
            platform=PlatformType.THREADS,
            raw_title=sanitize_pii_text(text[:200]) or f"Threads Post #{post_id}",
            metric_value=float(likes),
            growth_velocity=0.0,
            source_url=f"https://www.threads.net/@{username}/post/{code}" if username and code else None,
            geo_code=geo,
            metadata={
                "post_id": post_id,
                "username": username,
                "user_id": author_id,
                "like_count": likes,
                "reply_count": replies,
                "reposts": coerce_int(app_info.get("repost_count")),
                "quotes": coerce_int(app_info.get("quote_count")),
                "published_at": published_at,
                "excerpt": sanitize_pii_text(text),
                "source": "threads_browser_session",
                "tier": "TIER_1_BROWSER_SESSION",
                **({"matched_keyword": keyword} if keyword else {}),
            },
            captured_at=datetime.now(timezone.utc),
            published_at=datetime.fromisoformat(published_at) if published_at else None,
        )

    @staticmethod
    def _normalize_epoch(raw: Any) -> Optional[str]:
        """Threads' private payloads carry `taken_at` as unix seconds."""
        if not raw:
            return None
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            return None
