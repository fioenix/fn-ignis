import logging
import re
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope, PlatformType, Timeframe
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager
from ignis.infrastructure.connectors.browser_support import (
    browser_launch_available,
    surface_reachable,
)
from ignis.infrastructure.connectors.meta_browser_ingress import build_cookie_header
from ignis.config import settings
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text


logger = logging.getLogger(__name__)





class TikTokPlugin(IConnectorPlugin):
    """
    Ingress Plugin for TikTok Trending & Keyword Search.
    Guarantees strict privacy: Never inspects personal inbox, notifications, or private profile data.
    Extracts only public videos with valid canonical URLs from explore and search grids.
    """

    EXPLORE_URL = "https://www.tiktok.com/explore"
    SEARCH_BASE_URL = "https://www.tiktok.com/search?q="

    VIDEO_URL_PATTERN = re.compile(r"(https://www\.tiktok\.com)?/(@[\w\.-]+)/video/(\d+)")

    def __init__(self, auth_manager: Optional[TikTokAuthManager] = None):
        self._auth_manager = auth_manager
        # TikTok's own notification, inbox and live wording, loaded from the tiktok_ui_noise
        # lexicon domain and compiled to word-boundary patterns. Held per locale in the database
        # because a hardcoded list only ever covered Vietnamese, and a Korean session then got
        # no filtering at all.
        self._ui_noise: List["re.Pattern[str]"] = []
        self._warned_about_missing_ui_noise = False
        # Commercial-intent probe phrasings, keyed by geo, from tiktok_suggest_templates_*.
        self._suggest_templates: Dict[str, List[str]] = {}

    def set_auth_manager(self, auth_manager: TikTokAuthManager) -> None:
        self._auth_manager = auth_manager

    def register_suggest_templates(self, templates: Dict[str, List[str]]) -> None:
        """Bind the per-geo intent probe phrasings used against Google Suggest."""
        cleaned = {
            str(geo).upper(): [str(p) for p in patterns if "{}" in str(p)]
            for geo, patterns in (templates or {}).items()
        }
        self._suggest_templates = {geo: p for geo, p in cleaned.items() if p}

    def _intent_probe_templates(self, geo_str: str) -> List[str]:
        """The templates for one geo, or none at all rather than another market's phrasing."""
        if not self._suggest_templates:
            return []
        return self._suggest_templates.get(
            geo_str.upper(), self._suggest_templates.get("DEFAULT", [])
        )

    def register_ui_noise(self, terms: List[str]) -> None:
        """Bind the notification and inbox wording this plugin must never ingest.

        Each term is compiled to match on word boundaries. Raw substring matching was the
        earlier behaviour and it fired inside longer words: "live " matched in "olive oil
        review", so a genuine video was dropped as a notification. A boundary does that job
        properly, which also makes the trailing space in the stored "live " term redundant
        rather than load-bearing, so terms are stripped here.

        Whitespace inside a phrase is matched loosely, because a scraped caption may carry a
        line break or a double space where the badge text has one.
        """
        self._ui_noise = []
        for term in terms or []:
            words = (term or "").strip().lower().split()
            if not words:
                continue
            pattern = r"\b" + r"\s+".join(re.escape(word) for word in words) + r"\b"
            self._ui_noise.append(re.compile(pattern, re.IGNORECASE))

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    @property
    def plugin_id(self) -> str:
        # Distinct from the Creative Center plugin, which serves the same platform.
        return "tiktok_video_grid"

    @property
    def name(self) -> str:
        return "TikTok Trending & Search Ingress"

    async def is_healthy(self) -> bool:
        """Whether an ingress pass could actually succeed right now.

        This answered `return True` unconditionally, so verify_connectors_health reported the
        connector HEALTHY on a host with no browser installed and with TikTok unreachable. The
        two things a pass genuinely needs are a launchable Chromium and an explore page that
        answers.

        A stored session is deliberately not part of the verdict. The explore grid is public,
        an unauthenticated pass still returns cards, and a bound auth manager with nothing
        stored yet is the normal state before authenticate_tiktok has been run: failing on it
        would report a working connector as broken.

        That leaves a gap this method cannot close on its own, because keyword search does need
        a session. `keyword_search_blocked_reason` reports that, and the health check passes it
        on as remediation; expiry of a session that exists belongs to get_platform_auth_status.
        """
        if not await browser_launch_available():
            return False

        cookie_header = None
        if self._auth_manager:
            try:
                storage_state = await self._auth_manager.get_storage_state()
                if storage_state:
                    cookie_header = build_cookie_header(storage_state) or None
            except Exception as e:
                logger.warning(f"Could not read the stored TikTok session for the probe: {e}")

        return await surface_reachable(self.EXPLORE_URL, cookie_header=cookie_header)

    def _is_private_or_notification(self, text: str) -> bool:
        """Reject private notification, inbox or interaction UI text.

        This guard is what backs the promise in the class docstring, so with no vocabulary
        registered it rejects everything rather than letting text through. An ingress pass that
        returns nothing is a visible failure; one that quietly starts storing the operator's own
        notifications is not.
        """
        if not text:
            return True
        if not self._ui_noise:
            # Once per instance: this runs for every card on the grid.
            if not self._warned_about_missing_ui_noise:
                self._warned_about_missing_ui_noise = True
                logger.warning(
                    "No TikTok UI noise vocabulary registered, so no card can be shown to be "
                    "public. Rejecting every card. Check the tiktok_ui_noise domain in "
                    "market_lexicons."
                )
            return True
        if any(pattern.search(text) for pattern in self._ui_noise):
            return True
        if re.match(r"^\s*\d+[\s\.\,kKmMbB]*\s*$", text):
            return True
        return False

    async def keyword_search_blocked_reason(self) -> Optional[str]:
        """Why `search_signals` would come back empty, when that is knowable in advance.

        This connector has two surfaces and they do not need the same thing. The explore grid
        is public: a pass with no stored session still returns cards, which is why is_healthy
        does not fail on a missing session. Keyword search is different -- measured 10/09/2026
        with no session stored, `search_signals` for two seeded keywords ran without error and
        returned zero cards.

        So a single boolean cannot describe this connector, and reporting HEALTHY on its own
        hid the reason a research mission got nothing from TikTok. The health report reads this
        and passes it on as remediation rather than folding it into the verdict, because the
        connector genuinely still works for the surface that does not need a login.
        """
        if not self._auth_manager:
            return (
                "No TikTok auth manager is bound, so keyword search cannot use a session. "
                "The public explore grid still works."
            )
        try:
            if await self._auth_manager.get_storage_state():
                return None
        except Exception as e:
            return f"Could not read the stored TikTok session: {e}"
        return (
            "No TikTok session is stored, so keyword search returns nothing. Run "
            "authenticate_tiktok. The public explore grid still works without one."
        )

    async def resolve_ingest_runtime(self) -> IngestRuntime:
        """TikTok exposes no official read API for this surface, so a browser is the only way in."""
        return IngestRuntime.BROWSER

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        """Fetch trending public videos from TikTok Explore."""
        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        signals = await self._fetch_via_playwright(
            url=self.EXPLORE_URL,
            storage_state=storage_state,
            geo=geo,
            limit=limit,
        )
        return signals

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
        custom_timeframe: Optional[str] = None,
    ) -> List[TrendSignal]:
        """Search public trending videos by specific keywords on TikTok."""

        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        all_signals: List[TrendSignal] = []
        seen_urls: Set[str] = set()

        import urllib.parse
        for kw in keywords[:10]:
            kw_clean = kw.strip()
            url = f"{self.SEARCH_BASE_URL}{urllib.parse.quote(kw_clean)}"
            signals = await self._fetch_via_playwright(
                url=url,
                storage_state=storage_state,
                geo=geo,
                limit=limit,
                keyword=kw_clean,
                seen_urls=seen_urls,
            )
            for s in signals:
                if s.source_url and s.source_url not in seen_urls:
                    seen_urls.add(s.source_url)
                    all_signals.append(s)

        return all_signals

    async def fetch_suggestions(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
    ) -> List[Dict[str, Any]]:
        """
        Fetch keyword search suggestions (Search Guide / Autocomplete & Related Topics) from TikTok.
        """
        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.info("Playwright not installed; activating HTTP Fallback Matrix for search suggestions.")
            return await self._fetch_suggestions_http_fallback(keywords, geo)

        results: List[Dict[str, Any]] = []
        import urllib.parse

        try:
            async with async_playwright() as p:

                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                )
                context_kwargs: Dict[str, Any] = {
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    "viewport": {"width": 1280, "height": 800},
                    "locale": "vi-VN" if geo == GeoCode.VN else "en-US",
                }
                if settings.PLAYWRIGHT_PROXY_SERVER:
                    context_kwargs["proxy"] = {"server": settings.PLAYWRIGHT_PROXY_SERVER}
                if storage_state:
                    context_kwargs["storage_state"] = storage_state


                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                for kw in keywords[:10]:
                    kw_clean = kw.strip()
                    url = f"{self.SEARCH_BASE_URL}{urllib.parse.quote(kw_clean)}"
                    
                    guide_words: List[str] = []
                    async def handle_suggest(resp):
                        if "suggest/guide" in resp.url or "search/suggest" in resp.url:
                            try:
                                if "json" in resp.headers.get("content-type", ""):
                                    body = await resp.json()
                                    items = body.get("data", [])
                                    if isinstance(items, list):
                                        for item in items:
                                            if isinstance(item, dict) and item.get("word"):
                                                guide_words.append(item["word"])
                            except Exception:
                                pass

                    page.on("response", handle_suggest)
                    await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    await page.wait_for_timeout(2000)

                    # Active In-Page API fetch fallback
                    try:
                        api_suggestions = await page.evaluate("""async (keyword) => {
                            try {
                                const resp = await fetch(`/api/search/suggest/guide/?keyword=${encodeURIComponent(keyword)}&aid=1988&app_language=vi-VN`);
                                if (resp.ok) {
                                    const json = await resp.json();
                                    return (json.data || []).map(item => item.word).filter(Boolean);
                                }
                            } catch (e) {}
                            return [];
                        }""", kw_clean)
                        if api_suggestions and isinstance(api_suggestions, list):
                            guide_words.extend(api_suggestions)
                    except Exception:
                        pass

                    # Extract DOM search guide chips/pills
                    try:
                        pill_elements = await page.query_selector_all('div[data-e2e="search-guide-item"], a[href*="/search?q="], div[class*="guide-item"]')
                        for pill in pill_elements[:8]:
                            txt = await pill.inner_text()
                            if txt and len(txt.strip()) > 2 and "\n" not in txt:
                                guide_words.append(txt.strip())
                    except Exception:
                        pass

                    # Extract hashtags and key phrases from top video cards
                    related_hashtags: List[str] = []
                    cards = await page.query_selector_all('div[data-e2e="search_top-item"], div[data-e2e="search_video-item"]')
                    for card in cards[:6]:
                        parent = await card.query_selector("xpath=..") if hasattr(card, "query_selector") else None
                        container = parent if parent else card
                        raw_text = await container.inner_text() if hasattr(container, "inner_text") else ""
                        text = raw_text if isinstance(raw_text, str) else str(raw_text or "")
                        if text:
                            for tag in re.findall(r"#\w+", text):
                                if tag.lower() not in [t.lower() for t in related_hashtags] and len(tag) > 2:
                                    related_hashtags.append(tag)

                    sug_entries = []
                    seen_sug = set()

                    for gw in guide_words:
                        clean_gw = gw.strip()
                        if clean_gw.lower() not in seen_sug and len(clean_gw) > 1:
                            seen_sug.add(clean_gw.lower())
                            sug_entries.append({"query": clean_gw, "type": "search_guide"})

                    for tag in related_hashtags[:8]:
                        if tag.lower() not in seen_sug:
                            seen_sug.add(tag.lower())
                            sug_entries.append({"query": tag, "type": "trending_hashtag"})

                    results.append({
                        "keyword": kw_clean,
                        "platform": self.platform.value,
                        "geo_code": geo.value if hasattr(geo, "value") else str(geo),
                        "suggestions_count": len(sug_entries),
                        "suggestions": sug_entries,
                    })

                await browser.close()

        except Exception as e:
            logger.warning(f"Playwright search suggestions failed ({e}), activating HTTP Fallback Matrix.")
            return await self._fetch_suggestions_http_fallback(keywords, geo)

        return results

    async def _fetch_suggestions_http_fallback(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
    ) -> List[Dict[str, Any]]:
        """
        Zero-Playwright lightweight HTTP fallback for suggestion extraction.
        Queries Google Suggestion API specialized on TikTok video intent.
        """
        results: List[Dict[str, Any]] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        }
        hl = "vi" if geo == GeoCode.VN else "en"
        gl = "vn" if geo == GeoCode.VN else "us"
        geo_value = geo.value if hasattr(geo, "value") else str(geo)

        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            for kw in keywords[:10]:
                kw_clean = kw.strip()
                sug_entries = []
                seen_sug = set()

                # Probe 1: Google Suggest for TikTok
                try:
                    resp = await client.get(
                        "https://suggestqueries.google.com/complete/search",
                        params={"client": "firefox", "q": f"{kw_clean} tiktok", "hl": hl, "gl": gl},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if len(data) > 1 and isinstance(data[1], list):
                            for q in data[1]:
                                clean_q = str(q).replace("tiktok", "").replace("TikTok", "").strip()
                                if clean_q and clean_q.lower() not in seen_sug and len(clean_q) > 2:
                                    seen_sug.add(clean_q.lower())
                                    sug_entries.append({"query": clean_q, "type": "search_guide"})
                except Exception:
                    pass

                # Probe 2: Commercial Intent Probe. Skipped when this geo has no registered
                # phrasing, because probing a market in another market's language measures
                # nothing.
                for template in self._intent_probe_templates(geo_value):
                    try:
                        resp = await client.get(
                            "https://suggestqueries.google.com/complete/search",
                            params={"client": "firefox", "q": template.format(kw_clean), "hl": hl, "gl": gl},
                        )
                        if resp.status_code == 200:
                            data = resp.json()
                            if len(data) > 1 and isinstance(data[1], list):
                                for q in data[1][:4]:
                                    clean_q = str(q).strip()
                                    if clean_q and clean_q.lower() not in seen_sug and len(clean_q) > 2:
                                        seen_sug.add(clean_q.lower())
                                        sug_entries.append({"query": clean_q, "type": "related_hashtag"})
                    except Exception:
                        pass

                results.append({
                    "keyword": kw_clean,
                    "platform": self.platform.value,
                    "geo_code": geo.value if hasattr(geo, "value") else str(geo),
                    "suggestions_count": len(sug_entries),
                    "suggestions": sug_entries,
                })

        return results


    async def fetch_video_comments(
        self,
        video_url: str,
        limit: int = 30,
    ) -> List[Dict[str, Any]]:
        """
        Fetch public comments under a specific TikTok video using in-page API with Playwright session context.
        """
        match = re.search(r"/video/(\d+)", video_url)
        if not match:
            logger.warning(f"Could not extract video ID from URL: {video_url}")
            return []
        aweme_id = match.group(1)

        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed, skipping comments scraping.")
            return []

        comments: List[Dict[str, Any]] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                )
                context_kwargs: Dict[str, Any] = {
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    "viewport": {"width": 1280, "height": 800},
                    "locale": "vi-VN",
                }
                if settings.PLAYWRIGHT_PROXY_SERVER:
                    context_kwargs["proxy"] = {"server": settings.PLAYWRIGHT_PROXY_SERVER}
                if storage_state:
                    context_kwargs["storage_state"] = storage_state


                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                await page.goto(video_url, wait_until="domcontentloaded", timeout=25000)

                safe_limit = max(5, min(limit, 50))
                js_fetch = f"""
                    async () => {{
                        try {{
                            const url = `/api/comment/list/?aid=1988&aweme_id={aweme_id}&count={safe_limit}&cursor=0`;
                            const resp = await fetch(url);
                            return await resp.json();
                        }} catch (e) {{
                            return {{ error: e.toString() }};
                        }}
                    }}
                """
                api_data = await page.evaluate(js_fetch)
                raw_comments = api_data.get("comments", []) if isinstance(api_data, dict) else []

                salt = "ignis_salt_2026"
                for c in raw_comments:
                    if isinstance(c, dict):
                        user_obj = c.get("user", {}) or {}
                        raw_name = user_obj.get("nickname") or user_obj.get("unique_id") or "user"
                        raw_id = user_obj.get("unique_id") or "anon"
                        raw_cid = str(c.get("cid", ""))
                        
                        # Salted Pseudonymization (GDPR Art. 4(5) / Law 91/2025/QH15)
                        h_name = hashlib.sha256(f"{salt}:{raw_name}".encode()).hexdigest()[:4]
                        h_id = hashlib.sha256(f"{salt}:{raw_id}".encode()).hexdigest()[:6]
                        h_cid = hashlib.sha256(f"{salt}:{raw_cid}".encode()).hexdigest()[:8]

                        pseudo_author = f"{raw_name[:2]}***_{h_name}" if len(raw_name) >= 2 else "user_anon"
                        pseudo_id = f"id_{h_id}"
                        pseudo_cid = f"cmt_{h_cid}"

                        cmt_text = c.get("text", "").strip()
                        if cmt_text:
                            # Redact phone numbers, emails, and credentials
                            redacted_text = sanitize_pii_text(cmt_text)

                            comments.append({
                                "comment_id": pseudo_cid,
                                "author": pseudo_author,
                                "author_id": pseudo_id,
                                "text": redacted_text,
                                "likes": c.get("digg_count", 0),
                                "reply_count": c.get("reply_comment_total", 0),
                                "created_at": c.get("create_time"),
                            })




                await browser.close()

        except Exception as e:
            logger.error(f"Error scraping comments for video {video_url}: {e}")
            raise ConnectorExecutionException(f"Failed to fetch TikTok comments: {e}") from e

        return comments

    async def fetch_top_comments_for_keywords(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        max_videos: int = 3,
        limit_per_video: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Search top videos for keywords and extract comments for Voice of Customer analysis.
        """
        all_results: List[Dict[str, Any]] = []

        signals = await self.search_signals(keywords=keywords, geo=geo, limit=max_videos * 2)
        valid_vids = [s for s in signals if s.source_url and "/video/" in s.source_url][:max_videos]

        for s in valid_vids:
            try:
                cmts = await self.fetch_video_comments(video_url=s.source_url, limit=limit_per_video)
                all_results.append({
                    "video_url": s.source_url,
                    "video_title": s.raw_title,
                    "author": s.metadata.get("channel", "Unknown"),
                    "views": s.metric_value,
                    "total_comments_fetched": len(cmts),
                    "comments": cmts,
                })
            except Exception as e:
                logger.warning(f"Skipping comments scraping for video {s.source_url}: {e}")

        return all_results



    async def _fetch_via_playwright(
        self,
        url: str,
        storage_state: Optional[Dict[str, Any]],
        geo: GeoCode,
        limit: int = 30,
        keyword: Optional[str] = None,
        seen_urls: Optional[Set[str]] = None,
    ) -> List[TrendSignal]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed, skipping TikTok scraping.")
            return []

        signals: List[TrendSignal] = []
        captured_items: List[Dict[str, Any]] = []
        local_seen: Set[str] = set(seen_urls or [])

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                )
                
                context_kwargs: Dict[str, Any] = {
                    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                    "viewport": {"width": 1280, "height": 800},
                    "locale": "vi-VN" if geo == GeoCode.VN else "en-US",
                }
                if settings.PLAYWRIGHT_PROXY_SERVER:
                    context_kwargs["proxy"] = {"server": settings.PLAYWRIGHT_PROXY_SERVER}
                if storage_state:
                    context_kwargs["storage_state"] = storage_state


                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                # Listen for underlying JSON API responses
                async def handle_response(response):
                    if any(k in response.url for k in ["item_list", "search/item", "search/general"]):
                        try:
                            ct = response.headers.get("content-type", "")
                            if "json" in ct or "application/json" in ct:
                                try:
                                    body = await response.json()
                                except Exception as parse_err:
                                    logger.debug(f"Failed to decode TikTok JSON response from {response.url}: {parse_err}")
                                    return
                                if not isinstance(body, dict):
                                    return
                                items = body.get("itemList") or body.get("data", {}).get("list", []) or body.get("data", [])
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, dict):
                                            captured_items.append(item)
                        except Exception as e:
                            logger.debug(f"Error reading TikTok response payload: {e}")

                page.on("response", handle_response)

                logger.info(f"TikTok Ingress navigating to {url}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3500)

                # 1. Transform from captured JSON API items if available
                for item in captured_items:
                    sig = self._parse_json_item(item, geo, keyword)
                    if sig and sig.source_url and sig.source_url not in local_seen:
                        local_seen.add(sig.source_url)
                        signals.append(sig)
                    if len(signals) >= limit:
                        break

                # 2. Fallback to DOM parsing if JSON API was not captured
                if not signals:
                    cards = await page.query_selector_all(
                        'div[data-e2e="search_top-item"], div[data-e2e="search_video-item"], div[data-e2e="search-card-item"], div[data-e2e="explore-item"]'
                    )
                    for card in cards:
                        sig = await self._parse_dom_card(card, geo, keyword)
                        if sig and sig.source_url and sig.source_url not in local_seen:
                            local_seen.add(sig.source_url)
                            signals.append(sig)
                        if len(signals) >= limit:
                            break

                await browser.close()

        except Exception as e:
            logger.error(f"Error executing TikTok Ingress ({url}): {e}")
            raise ConnectorExecutionException(f"Failed to fetch TikTok signals: {e}") from e

        return signals

    def _parse_json_item(self, item: Dict[str, Any], geo: GeoCode, keyword: Optional[str]) -> Optional[TrendSignal]:
        item_id = item.get("id") or item.get("item_id") or item.get("aweme_id")
        title = item.get("desc") or item.get("title", "")
        stats = item.get("stats") or item.get("statistics", {}) or {}
        author = item.get("author") or {}

        if not item_id or not title or self._is_private_or_notification(title):
            return None

        # Strict keyword match for short acronyms like n8n, rpa
        if keyword:
            kw_low = keyword.lower().strip()
            if len(kw_low) <= 4 and not re.search(rf"\b{re.escape(kw_low)}\b", title.lower()):
                return None

        play_count = float(stats.get("playCount") or stats.get("play_count", 0))
        author_id = author.get("uniqueId") or author.get("unique_id", "")
        if not author_id:
            return None

        url = f"https://www.tiktok.com/@{author_id}/video/{item_id}"

        metadata = {
            "item_id": str(item_id),
            "author": author_id,
            "author_name": author.get("nickname", ""),
            "likes": int(stats.get("diggCount") or stats.get("digg_count", 0)),
            "comments": int(stats.get("commentCount") or stats.get("comment_count", 0)),
            "shares": int(stats.get("shareCount") or stats.get("share_count", 0)),
            "keyword": keyword,
        }

        return TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title=sanitize_pii_text(title[:250]),
            metric_value=play_count or float(metadata["likes"]),
            growth_velocity=0.0,
            source_url=url,
            geo_code=geo,
            metadata=metadata,
            captured_at=datetime.now(timezone.utc),
        )


    async def _parse_dom_card(self, card, geo: GeoCode, keyword: Optional[str]) -> Optional[TrendSignal]:
        try:
            parent = await card.query_selector("xpath=..")
            container = parent if parent else card

            link_elem = (
                await card.query_selector('a[href*="/video/"]')
                or await container.query_selector('a[href*="/video/"]')
            )
            if not link_elem:
                return None

            raw_href = await link_elem.get_attribute("href")
            if not raw_href:
                return None

            match = self.VIDEO_URL_PATTERN.search(raw_href)
            if not match:
                return None

            author_tag = match.group(2) # @creator
            video_id = match.group(3)   # 7674847074868825362
            canonical_url = f"https://www.tiktok.com/{author_tag}/video/{video_id}"

            text = await container.inner_text()
            lines = [t.strip() for t in text.split("\n") if t.strip()]
            if not lines:
                return None

            # Skip notification / inbox noise
            combined_text = " ".join(lines)
            if self._is_private_or_notification(combined_text):
                return None

            # Parse metrics and true caption
            metric_val = 0.0
            raw_title = combined_text
            author_display = author_tag.replace("@", "")

            m_match = re.search(r"^(\d+(\.\d+)?)\s*([KkMmBb])?$", lines[0])
            if m_match:
                num = float(m_match.group(1))
                unit = (m_match.group(3) or "").upper()
                if unit == "K":
                    num *= 1000
                elif unit == "M":
                    num *= 1000000
                elif unit == "B":
                    num *= 1000000000
                metric_val = num
                if len(lines) > 1:
                    raw_title = lines[1]
                if len(lines) > 2 and lines[2] not in ["", "·"]:
                    author_display = lines[2]
            else:
                raw_title = lines[0]
                if len(lines) > 1 and lines[1] not in ["", "·"]:
                    author_display = lines[1]

            if self._is_private_or_notification(raw_title) or len(raw_title.strip()) < 3:
                return None

            # Strict keyword match
            if keyword:
                kw_low = keyword.lower().strip()
                if len(kw_low) <= 4 and not re.search(rf"\b{re.escape(kw_low)}\b", raw_title.lower()):
                    return None


            metadata = {
                "item_id": video_id,
                "author": author_display,
                "keyword": keyword,
            }

            return TrendSignal(
                platform=PlatformType.TIKTOK,
                raw_title=sanitize_pii_text(raw_title[:250]),
                metric_value=metric_val,
                growth_velocity=0.0,
                source_url=canonical_url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
            )

        except Exception:
            return None
