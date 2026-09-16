from __future__ import annotations

import asyncio
import logging
import urllib.parse
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
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope, PlatformType, Timeframe, timeframe_to_days
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text
from ignis.infrastructure.auth.meta_browser_auth import ThreadsBrowserAuthManager
from ignis.infrastructure.auth.meta_oauth import ThreadsAuthManager
from ignis.infrastructure.cache.insights_cache import InsightsTTLCache
from ignis.infrastructure.connectors.meta_browser_ingress import (
    GraphQLDocIdCache,
    build_cookie_header,
    caption_text,
    coerce_int,
    collect_json_payloads,
    collect_threads_search_suggestions_via_browser,
    extract_records,
    extract_search_suggestions,
    extract_trending_topics,
    fetch_graphql_direct,
)

logger = logging.getLogger(__name__)


class ThreadsPlugin(IConnectorPlugin):
    """
    Ingress plugin for Meta Threads via the official Threads Graph API (OAuth 2.0).

    Text-based discussion signals: post text, views/impressions, likes and replies,
    normalized to UTC timestamps. Invalid/expired tokens (401/403) and rate limits
    (429) raise typed exceptions so the registry's circuit breaker trips instead of
    silently returning an empty, apparently-healthy result set.

    Ingress path is resolved per call, in order:
      1. Tier 2 Graph API when a usable OAuth token is stored.
      2. Tier 1 browser session (`ThreadsBrowserAuthManager`) when the user signed in
         with an ordinary personal account and no Meta Developer App exists.
      3. Legacy unauthenticated public trending endpoint when nothing is bound.
    """

    GRAPH_BASE_URL = "https://graph.threads.net"
    LEGACY_TRENDING_URL = "https://www.threads.net/api/trending"
    BROWSER_FEED_URL = "https://www.threads.com/"
    BROWSER_SEARCH_URL = "https://www.threads.com/search"
    BROWSER_API_MARKERS = ["/graphql/query", "/api/graphql", "/api/v1/text_feed"]

    THREAD_FIELDS = "id,text,permalink,timestamp,username,media_type,is_quote_post"
    INSIGHT_METRICS = "views,likes,replies,reposts,quotes"

    REQUEST_TIMEOUT_SECONDS = 20.0
    MAX_INSIGHT_CONCURRENCY = 5

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

    @property
    def _api_root(self) -> str:
        return f"{self.GRAPH_BASE_URL}/{settings.THREADS_API_VERSION}"

    async def is_healthy(self) -> bool:
        """
        Active synthetic health check:
        - If OAuth2 Tier: verify access token validity.
        - If Browser Session Tier 1: send a lightweight authenticated HTTP GET to verify
          the session cookie is still valid and not redirected to login.
        """
        if not self._auth_manager and not self._browser_auth_manager:
            # Legacy unauthenticated public mode — nothing to verify.
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
                resp = await client.get(self.BROWSER_FEED_URL, headers=headers)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"Threads active health probe failed: {e}")
            return False

    async def _browser_storage_state(self) -> Optional[Dict[str, Any]]:
        if not self._browser_auth_manager:
            return None
        try:
            return await self._browser_auth_manager.get_storage_state()
        except Exception as e:
            logger.warning(f"Could not load the Threads browser session: {e}")
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
            except Exception as e:
                logger.warning(f"Threads OAuth token lookup error: {e}")
                token = None
            if token:
                # A token without the keyword_search grant still reads its own feed, so it is not
                # useless -- but it cannot answer a market question, and the browser session can.
                # Preferring the token here is what let a public pass query an endpoint the system
                # had already established searches the operator's own posts.
                if await self._keyword_search_is_blocked():
                    storage_state = await self._browser_storage_state()
                    if storage_state:
                        logger.info(
                            "Threads: the stored Graph token cannot search public posts, so the "
                            "Tier 1 browser session takes precedence for this install."
                        )
                        return "session_cookies", storage_state
                return "oauth2", token

        storage_state = await self._browser_storage_state()
        if storage_state:
            logger.info("Threads: Graph OAuth token absent, active tier is Tier 1 Browser Session.")
            return "session_cookies", storage_state

        return "none", None

    async def _has_graph_token(self) -> bool:
        """Whether the Tier 2 Graph API path is usable right now."""
        tier, _ = await self.resolve_auth_tier()
        return tier == "oauth2"

    # --- Ingress ---

    async def resolve_ingest_runtime(self) -> IngestRuntime:
        """The Graph API tier is plain HTTP; the Tier-1 session is driven through a browser."""
        tier, _ = await self.resolve_auth_tier()
        return IngestRuntime.HTTP_API if tier == "oauth2" else IngestRuntime.BROWSER

    @property
    def default_feed_scope(self) -> IngressScope:
        """Both Threads feeds this plugin can read belong to the authenticated account.

        The Graph path is `/me/threads` (the account's own posts) and the browser path is the
        personalised home feed (the account plus whoever it follows). Neither is market evidence,
        so the registry keeps them out of public passes and uses `search_signals` instead.
        """
        return IngressScope.OWN_PROFILE

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        """Fetch top/recent threads within the requested timeframe window.

        Every surface reachable here is account-owned, so a public-market pass gets nothing:
        callers wanting market signals use `search_signals`, and the registry routes them there.
        """
        if not scope.includes_own:
            logger.info(
                "Threads fetch_signals skipped: its feeds are account-owned and the requested "
                f"scope is {scope.value}."
            )
            return []

        if not await self._has_graph_token():
            storage_state = await self._browser_storage_state()
            if storage_state:
                feed_signals = await self._fetch_via_browser_session(
                    url=self.BROWSER_FEED_URL, storage_state=storage_state, geo=geo, limit=limit
                )
                try:
                    topics = await self.fetch_trending_topics(geo=geo, limit=10)
                    for t in topics:
                        t_name = t.get("topic", "")
                        p_count = t.get("post_count", 0)
                        feed_signals.append(
                            TrendSignal(
                                platform=PlatformType.THREADS,
                                raw_title=f"[Trending Topic] {t_name}",
                                metric_value=float(p_count) if p_count > 0 else 1000.0,
                                growth_velocity=0.0,
                                source_url=t.get("search_url"),
                                geo_code=geo,
                                metadata={
                                    "topic": t_name,
                                    "topic_id": t.get("topic_id"),
                                    "post_count_label": t.get("post_count_label"),
                                    "source": "threads_trending_topics",
                                    "tier": "TIER_1_BROWSER_SESSION",
                                },
                                captured_at=datetime.now(timezone.utc),
                            )
                        )
                except Exception as e:
                    logger.warning(f"Could not augment Threads feed with trending topics: {e}")
                return feed_signals
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
        if not await self._has_graph_token():
            storage_state = await self._browser_storage_state()
            if storage_state:
                return await self._search_via_browser_session(
                    keywords=keywords, storage_state=storage_state, geo=geo, limit=limit
                )
            if not self._auth_manager:
                return await self._fetch_legacy_public(geo=geo, limit=limit)

        # Reached only when the Graph token is the sole remaining path. If it is already known to
        # search the authenticated account's own posts, the results would look exactly like market
        # evidence while being this install's own content. Missing data is recoverable; evidence
        # that is wrong and confident is not, and it reaches the Opportunity Index either way.
        if await self._keyword_search_is_blocked():
            raise ConnectorAuthenticationException(
                "The stored Threads token cannot search public posts: Meta grants "
                "threads_keyword_search only through App Review, and this token's probe found the "
                "endpoint returning the authenticated account's own posts. Refusing rather than "
                "reporting them as market evidence. Sign in with a personal account instead: "
                "authenticate_threads(browser_login=True)."
            )

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

    # Outcomes of the keyword-search access probe below.
    KEYWORD_SEARCH_PUBLIC = "PUBLIC_SEARCH_ENABLED"
    KEYWORD_SEARCH_SELF_ONLY = "SELF_ONLY"
    KEYWORD_SEARCH_NOT_PERMITTED = "NOT_PERMITTED"
    KEYWORD_SEARCH_INCONCLUSIVE = "INCONCLUSIVE"
    KEYWORD_SEARCH_NO_TOKEN = "NO_GRAPH_TOKEN"

    # Verdicts that mean this token cannot answer a public-market question. Both return HTTP 200
    # and a populated body, which is why they have to be remembered rather than re-derived from
    # whether a call succeeded.
    KEYWORD_SEARCH_BLOCKED = (KEYWORD_SEARCH_SELF_ONLY, KEYWORD_SEARCH_NOT_PERMITTED)
    # Verdicts worth storing. INCONCLUSIVE and NO_GRAPH_TOKEN say the probe learned nothing, and
    # writing them down would erase a verdict that was actually established.
    KEYWORD_SEARCH_CONCLUSIVE = (
        KEYWORD_SEARCH_PUBLIC,
        KEYWORD_SEARCH_SELF_ONLY,
        KEYWORD_SEARCH_NOT_PERMITTED,
    )

    async def check_keyword_search_access(self, query: str) -> Dict[str, Any]:
        """Probe the endpoint, then persist what was established.

        The probe costs a real API call, so its answer belongs in storage where the tier and
        search paths can read it, not only in the response of the tool that triggered it.
        """
        report = await self._probe_keyword_search_access(query)
        status = report.get("status")
        if status in self.KEYWORD_SEARCH_CONCLUSIVE and self._auth_manager is not None:
            recorder = getattr(self._auth_manager, "record_keyword_search_verdict", None)
            if recorder is not None:
                try:
                    await recorder(status)
                except Exception as e:  # Reporting the verdict must not fail the probe.
                    logger.warning(f"Could not persist the Threads keyword-search verdict: {e}")
        return report

    async def _keyword_search_is_blocked(self) -> bool:
        """Whether a stored verdict says this token cannot search public posts.

        Absence of a verdict is not a negative verdict: an install that never probed keeps the
        behaviour it had.
        """
        reader = getattr(self._auth_manager, "get_keyword_search_verdict", None)
        if reader is None:
            return False
        try:
            return await reader() in self.KEYWORD_SEARCH_BLOCKED
        except Exception as e:
            logger.warning(f"Could not read the Threads keyword-search verdict: {e}")
            return False

    async def _probe_keyword_search_access(self, query: str) -> Dict[str, Any]:
        """Establish whether this token can actually search public Threads posts.

        Meta grants `threads_keyword_search` only after App Review. Without it the endpoint still
        answers HTTP 200 — but the search runs over the authenticated account's own posts only, so
        an install that assumes otherwise ends up listening to itself and calling it market data.
        Nothing in the API reports the granted scopes (the token exchange returns only
        access_token, token_type and expires_in, and graph.threads.net exposes no debug_token), so
        this probes the behaviour instead of introspecting the grant, and reports INCONCLUSIVE
        rather than guessing when the evidence is thin.
        """
        if not query or not query.strip():
            return {
                "status": self.KEYWORD_SEARCH_INCONCLUSIVE,
                "detail": "No probe keyword was supplied, so public search access was not tested.",
            }

        if not await self._has_graph_token():
            return {
                "status": self.KEYWORD_SEARCH_NO_TOKEN,
                "detail": "No Threads Graph token is configured; the Tier-1 browser session is the active path.",
            }

        token = await self._require_token()
        try:
            own = await self._graph_get(
                f"{self._api_root}/me",
                params={"fields": "id,username", "access_token": token},
            )
        except Exception as e:
            own = {}
            logger.warning(f"Could not read the authenticated Threads account: {e}")

        own_id = str(own.get("id") or "")
        own_username = str(own.get("username") or "").lstrip("@").lower()

        try:
            payload = await self._graph_get(
                f"{self._api_root}/keyword_search",
                params={
                    "q": query.strip(),
                    "search_type": "TOP",
                    "fields": self.THREAD_FIELDS,
                    "limit": 25,
                    "access_token": token,
                },
            )
        except ConnectorAuthenticationException as e:
            return {
                "status": self.KEYWORD_SEARCH_NOT_PERMITTED,
                "detail": f"The keyword search endpoint rejected this token: {e}",
            }
        except Exception as e:
            return {
                "status": self.KEYWORD_SEARCH_INCONCLUSIVE,
                "detail": f"The keyword search probe could not complete: {e}",
            }

        items = payload.get("data") or []
        if not items:
            return {
                "status": self.KEYWORD_SEARCH_INCONCLUSIVE,
                "detail": (
                    f"The keyword search for '{query.strip()}' returned nothing, which is equally "
                    "consistent with an unapproved scope and with a term nobody posted about."
                ),
                "probe_keyword": query.strip(),
            }

        authors = {str(it.get("username") or "").lstrip("@").lower() for it in items}
        authors.discard("")
        foreign_authors = {a for a in authors if a and a != own_username}

        if foreign_authors:
            return {
                "status": self.KEYWORD_SEARCH_PUBLIC,
                "detail": (
                    f"Public search is active: {len(items)} results from "
                    f"{len(foreign_authors)} other accounts."
                ),
                "probe_keyword": query.strip(),
            }

        return {
            "status": self.KEYWORD_SEARCH_SELF_ONLY,
            "detail": (
                f"Every one of the {len(items)} results belongs to the authenticated account"
                + (f" (@{own_username})" if own_username else "")
                + (f" [id {own_id}]" if own_id and not own_username else "")
                + ". Meta grants threads_keyword_search only after App Review, so this token "
                "searches its own posts. Use the Tier-1 browser session for Threads listening "
                "instead: authenticate_threads(browser_login=True)."
            ),
            "probe_keyword": query.strip(),
        }

    async def fetch_trending_topics(
        self,
        geo: GeoCode = GeoCode.VN,
        limit: int = 15,
    ) -> List[Dict[str, Any]]:
        """
        Fetch real-time Trending Topics from Threads search surface.
        Uses Direct GraphQL fast-path if doc_id is available, falling back to Playwright.
        """
        storage_state = await self._browser_storage_state()
        if not storage_state:
            return []

        doc_id, lsd = GraphQLDocIdCache.get("trending_topics")
        if doc_id:
            direct_payload = await fetch_graphql_direct(
                doc_id=doc_id,
                variables={},
                storage_state=storage_state,
                lsd=lsd,
                geo=geo,
            )
            if direct_payload:
                topics = extract_trending_topics([direct_payload], limit=limit)
                if topics:
                    return topics

        payloads = await collect_json_payloads(
            url=self.BROWSER_SEARCH_URL,
            storage_state=storage_state,
            url_markers=self.BROWSER_API_MARKERS,
            geo=geo,
        )
        return extract_trending_topics(payloads, limit=limit)

    async def fetch_search_suggestions(
        self,
        keyword: str,
        geo: GeoCode = GeoCode.VN,
        limit: int = 10,
    ) -> List[str]:
        """
        Fetch search autocomplete suggestions / related terms from Threads search.
        Uses Direct GraphQL fast-path if doc_id is cached, falling back to Playwright input typing.
        """
        storage_state = await self._browser_storage_state()
        clean_kw = keyword.strip()
        if not storage_state or not clean_kw:
            return []

        doc_id, lsd = GraphQLDocIdCache.get("search_suggestions")
        if doc_id:
            direct_payload = await fetch_graphql_direct(
                doc_id=doc_id,
                variables={"query": clean_kw, "has_communities": True, "has_favicons": False},
                storage_state=storage_state,
                lsd=lsd,
                geo=geo,
            )
            if direct_payload:
                suggestions = extract_search_suggestions([direct_payload], limit=limit)
                if suggestions:
                    return suggestions

        payloads = await collect_threads_search_suggestions_via_browser(
            storage_state=storage_state,
            keyword=clean_kw,
            geo=geo,
        )
        return extract_search_suggestions(payloads, limit=limit)

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

        # The 15-minute worker pass re-reads the same posts; serving them from the TTL
        # cache is what keeps this under Meta's 200 calls/user/hour budget.
        insights, pending = self._insights_cache.partition(
            PlatformType.THREADS.value, post_ids, self.INSIGHT_METRICS
        )
        if not pending:
            return insights

        semaphore = asyncio.Semaphore(self.MAX_INSIGHT_CONCURRENCY)

        async def _one(post_id: str) -> Tuple[str, Dict[str, float]]:
            async with semaphore:
                payload = await self._graph_get(
                    f"{self._api_root}/{post_id}/insights",
                    params={"metric": self.INSIGHT_METRICS, "access_token": token},
                )
                return post_id, self._parse_insights(payload)

        results = await asyncio.gather(*[_one(pid) for pid in pending], return_exceptions=True)

        for result in results:
            if isinstance(result, (ConnectorAuthenticationException, ConnectorQuotaExceededException)):
                # Token rejection / soft-block must surface, not be swallowed per-post.
                raise result
            if isinstance(result, Exception):
                logger.warning(f"Threads insights lookup failed for one post: {result}")
                continue
            post_id, metrics = result
            insights[post_id] = metrics
            self._insights_cache.set(PlatformType.THREADS.value, post_id, self.INSIGHT_METRICS, metrics)
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
        tier, credential = await self.resolve_auth_tier()
        if tier == "oauth2" and credential:
            return credential

        raise ConnectorAuthenticationException(
            "No valid Threads credentials available across all auth tiers. "
            "Tier 1 (Personal / Browser): Run `authenticate_threads(browser_login=True)`. "
            "Tier 2 (Enterprise / Developer): Run `authenticate_threads(auth_code=...)`."
        )

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

    # --- Tier 1 browser-session ingress ---

    async def _search_via_browser_session(
        self,
        keywords: List[str],
        storage_state: Dict[str, Any],
        geo: GeoCode,
        limit: int,
    ) -> List[TrendSignal]:
        """Run search per keyword using Direct GraphQL fast-path, falling back to Playwright."""
        all_signals: List[TrendSignal] = []
        seen_ids: set[str] = set()
        doc_id, lsd = GraphQLDocIdCache.get("search_posts")

        for keyword in [k.strip() for k in keywords[:10] if k and k.strip()]:
            keyword_signals: List[TrendSignal] = []
            if doc_id:
                direct_payload = await fetch_graphql_direct(
                    doc_id=doc_id,
                    variables={"query": keyword, "search_type": "TOP"},
                    storage_state=storage_state,
                    lsd=lsd,
                    geo=geo,
                )
                if direct_payload:
                    records = extract_records(
                        [direct_payload],
                        is_record=self._is_browser_post,
                        identity=lambda node: str(node.get("pk") or node.get("id") or ""),
                        limit=min(max(limit, 1), 100),
                    )
                    keyword_signals = [self._map_browser_post(node, geo=geo, keyword=keyword) for node in records]

            if not keyword_signals:
                url = f"{self.BROWSER_SEARCH_URL}?{urllib.parse.urlencode({'q': keyword, 'serp_type': 'default'})}"
                keyword_signals = await self._fetch_via_browser_session(
                    url=url, storage_state=storage_state, geo=geo, limit=limit, keyword=keyword
                )

            for signal in keyword_signals:
                post_id = str(signal.metadata.get("post_id") or "")
                if post_id and post_id in seen_ids:
                    continue
                seen_ids.add(post_id)
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
            is_record=self._is_browser_post,
            identity=lambda node: str(node.get("pk") or node.get("id") or ""),
            limit=min(max(limit, 1), 100),
        )
        return [self._map_browser_post(node, geo=geo, keyword=keyword) for node in records]

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
                "published_at": self._normalize_epoch(node.get("taken_at")),
                "source": "threads_browser_session",
                "tier": "TIER_1_BROWSER_SESSION",
                **({"matched_keyword": keyword} if keyword else {}),
            },
            captured_at=datetime.now(timezone.utc),
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
            logger.error(f"Error fetching Threads: {e}")
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
            author_id = str(user.get("pk") or user.get("id") or "")

            like_count = float(item.get("like_count", 0))
            reply_count = int(item.get("reply_count", 0))

            url = f"https://www.threads.net/@{username}/post/{code}" if username and code else None

            signals.append(
                TrendSignal(
                    platform=PlatformType.THREADS,
                    raw_title=sanitize_pii_text(caption[:200]) or f"Threads Post #{post_id}",
                    metric_value=like_count,
                    growth_velocity=0.0,
                    source_url=url,
                    geo_code=geo,
                    metadata={
                        "post_id": post_id,
                        "username": username,
                        "user_id": author_id,
                        "reply_count": reply_count,
                        "like_count": int(like_count),
                        "source": "threads_public_trending",
                    },
                    captured_at=datetime.now(timezone.utc),
                )
            )

        return signals
