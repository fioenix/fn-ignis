from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple

import httpx

from ignis.config import reveal_secret, settings
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager

logger = logging.getLogger(__name__)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def get_threads_web_client_id() -> str:
    """Retrieve dynamic Meta web client ID (X-IG-App-ID) from runtime configuration."""
    return RuntimeConfigManager.get_instance().get_sync("threads_web_client_id", "238260118697367")


def get_threads_graphql_endpoint() -> str:
    """Retrieve dynamic GraphQL endpoint from runtime configuration."""
    return RuntimeConfigManager.get_instance().get_sync("threads_graphql_endpoint", "https://www.threads.com/api/graphql")


class GraphQLDocIdCache:
    """
    In-memory cache for dynamic Meta GraphQL doc_ids and LSD tokens.
    Allows self-healing fallback: Playwright captures the latest doc_id when Meta
    rotates frontend builds, and subsequent calls use the fast httpx direct path.
    Synchronizes automatically with RuntimeConfigManager for persistence.
    """

    _cache: Dict[str, Dict[str, Optional[str]]] = {
        "trending_topics": {"doc_id": None, "lsd": None},
        "search_posts": {"doc_id": None, "lsd": None},
        "search_suggestions": {"doc_id": None, "lsd": None},
    }

    @classmethod
    def get(cls, query_type: str) -> Tuple[Optional[str], Optional[str]]:
        entry = cls._cache.get(query_type, {})
        doc_id = entry.get("doc_id")
        lsd = entry.get("lsd")
        if not doc_id:
            persisted_key = f"threads_doc_id_{query_type}"
            db_doc = RuntimeConfigManager.get_instance().get_sync(persisted_key)
            if db_doc:
                doc_id = db_doc
        return doc_id, lsd

    # Fire-and-forget persistence tasks, held so the event loop cannot collect one mid-write.
    _pending_writes: Set["asyncio.Task[None]"] = set()

    @classmethod
    def set(cls, query_type: str, doc_id: str, lsd: Optional[str] = None) -> None:
        """Record a captured doc_id, persisting it only when it is genuinely new.

        The sniffer runs inside a request interceptor, so this is called once per GraphQL
        request Threads makes -- dozens of times in a single pass. It used to queue a database
        write every time: one measured pass wrote the same three keys 97 times, 85 of them the
        same value for trending_topics. The doc_id only changes when Meta ships a new frontend
        build, which is the whole reason it is persisted, so an unchanged value is written once
        and then never again.
        """
        if query_type not in cls._cache:
            cls._cache[query_type] = {}

        # The LSD token rotates constantly and is never persisted; it belongs in memory only.
        if lsd:
            cls._cache[query_type]["lsd"] = lsd

        persisted_key = f"threads_doc_id_{query_type}"
        known = cls._cache[query_type].get("doc_id")
        if not known:
            # First sighting this process: what the database already holds counts as known, or
            # every restart would rewrite a value that never changed.
            known = RuntimeConfigManager.get_instance().get_sync(persisted_key) or None

        if known == doc_id:
            cls._cache[query_type]["doc_id"] = doc_id
            return

        cls._cache[query_type]["doc_id"] = doc_id
        logger.info(
            f"Meta rotated the '{query_type}' doc_id; persisting the newly captured one."
        )

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop: a synchronous caller. The in-memory cache still carries the new value.
            return

        task = loop.create_task(
            RuntimeConfigManager.get_instance().set(
                key=persisted_key,
                value=doc_id,
                category="threads",
                description=f"Auto-captured doc_id for {query_type}",
                updated_by="self_healing_sniffer",
            )
        )
        cls._pending_writes.add(task)
        task.add_done_callback(cls._pending_writes.discard)
        task.add_done_callback(cls._log_write_failure)

    @staticmethod
    def _log_write_failure(task: "asyncio.Task[None]") -> None:
        """A dropped write leaves the next process re-sniffing, so it must not pass unnoticed."""
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning(f"Could not persist a captured Threads doc_id: {error}")

    @classmethod
    def record_signature_from_payload(cls, doc_id: str, lsd: Optional[str], vars_raw: str) -> None:
        """Heuristically assign the captured doc_id to the right query type based on variable keys."""
        try:
            vars_dict = json.loads(vars_raw) if isinstance(vars_raw, str) else vars_raw
        except Exception:
            vars_dict = {}

        if not isinstance(vars_dict, dict):
            vars_dict = {}

        if "has_communities" in vars_dict or "has_favicons" in vars_dict:
            cls.set("search_suggestions", doc_id, lsd)
        elif "query" in vars_dict or "search_query" in vars_dict:
            cls.set("search_posts", doc_id, lsd)
        elif "prompt" in vars_dict or "keyword" in vars_dict:
            cls.set("search_suggestions", doc_id, lsd)
        else:
            cls.set("trending_topics", doc_id, lsd)


def build_cookie_header(storage_state: Dict[str, Any]) -> str:
    """Convert Playwright storage_state cookies list into a valid HTTP Cookie header string."""
    cookies = storage_state.get("cookies", []) or []
    parts = []
    for c in cookies:
        name = c.get("name")
        val = c.get("value")
        if name and val is not None:
            parts.append(f"{name}={val}")
    return "; ".join(parts)


def extract_token_from_storage(storage_state: Dict[str, Any], token_name: str) -> Optional[str]:
    """Find a specific cookie value (such as csrftoken or ds_user_id) from storage state."""
    cookies = storage_state.get("cookies", []) or []
    for c in cookies:
        if c.get("name") == token_name:
            return c.get("value")
    return None


async def fetch_graphql_direct(
    doc_id: str,
    variables: Dict[str, Any],
    storage_state: Dict[str, Any],
    lsd: Optional[str] = None,
    url: Optional[str] = None,
    geo: GeoCode = GeoCode.VN,
    timeout_seconds: float = 12.0,
) -> Optional[Dict[str, Any]]:
    """
    Fast-path: execute an authenticated GraphQL query directly via httpx without launching Playwright.
    Uses persisted doc_id and session cookies captured from storage_state.
    Returns parsed JSON dict on success, or None on error/invalidation so caller falls back to Playwright.
    """
    cookie_header = build_cookie_header(storage_state)
    if not cookie_header:
        logger.debug("No cookies in storage_state; cannot perform direct GraphQL fetch.")
        return None

    target_url = url or get_threads_graphql_endpoint()
    client_id = get_threads_web_client_id()
    csrf_token = extract_token_from_storage(storage_state, "csrftoken") or ""
    headers = {
        "User-Agent": USER_AGENT,
        "X-IG-App-ID": client_id,
        "X-FB-LSD": lsd or "AVq0",
        "X-CSRFToken": csrf_token,
        "X-ASBD-ID": "129477",
        "Cookie": cookie_header,
        "Origin": "https://www.threads.com",
        "Referer": "https://www.threads.com/search",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7" if geo == GeoCode.VN else "en-US,en;q=0.9",
    }

    form_data = {
        "lsd": lsd or "AVq0",
        "doc_id": doc_id,
        "variables": json.dumps(variables),
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = await client.post(target_url, headers=headers, data=form_data)
            if resp.status_code != 200:
                logger.debug(f"Direct GraphQL POST returned status {resp.status_code} for doc_id {doc_id}")
                return None

            payload = resp.json()
            if isinstance(payload, dict) and payload.get("errors"):
                logger.debug(f"GraphQL returned errors for doc_id {doc_id}: {payload.get('errors')}")
                return None
            return payload
    except Exception as e:
        logger.debug(f"Direct GraphQL POST encountered exception: {e}")
        return None


async def collect_json_payloads(
    url: str,
    storage_state: Dict[str, Any],
    url_markers: List[str],
    geo: GeoCode = GeoCode.VN,
    settle_ms: int = 4000,
    scrolls: int = 2,
) -> List[Dict[str, Any]]:
    """
    Drive a logged-in Playwright context over `url` and return the JSON bodies of every
    XHR whose URL contains one of `url_markers`.

    Also sniffs outgoing POST requests to capture and update doc_id and lsd signatures
    in GraphQLDocIdCache for future zero-overhead fast-path calls.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed; skipping Meta browser-session ingress.")
        return []

    payloads: List[Dict[str, Any]] = []

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )
            context_kwargs: Dict[str, Any] = {
                "user_agent": USER_AGENT,
                "viewport": {"width": 1280, "height": 900},
                "locale": "vi-VN" if geo == GeoCode.VN else "en-US",
                "storage_state": storage_state,
            }
            if reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER):
                context_kwargs["proxy"] = {"server": reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER)}

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            # Self-healing listener: capture doc_id and lsd from outgoing GraphQL queries
            async def handle_request(request: Any) -> None:
                try:
                    req_url = request.url
                    if any(marker in req_url for marker in url_markers) and request.method == "POST":
                        post_data = request.post_data
                        if post_data:
                            params = urllib.parse.parse_qs(post_data)
                            doc_ids = params.get("doc_id")
                            lsds = params.get("lsd")
                            if doc_ids:
                                captured_doc_id = doc_ids[0]
                                captured_lsd = lsds[0] if lsds else None
                                vars_raw = params.get("variables", ["{}"])[0]
                                GraphQLDocIdCache.record_signature_from_payload(
                                    captured_doc_id, captured_lsd, vars_raw
                                )
                except Exception:
                    pass

            page.on("request", handle_request)

            async def handle_response(response: Any) -> None:
                if not any(marker in response.url for marker in url_markers):
                    return
                try:
                    if "json" not in response.headers.get("content-type", ""):
                        return
                    body = await response.json()
                except Exception:
                    return
                if isinstance(body, dict):
                    payloads.append(body)

            page.on("response", handle_response)

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(settle_ms)

            for _ in range(max(scrolls, 0)):
                await page.mouse.wheel(0, 2400)
                await page.wait_for_timeout(1800)

            await browser.close()
    except Exception as e:
        logger.error(f"Meta browser-session ingress failed for {url}: {e}")
        raise ConnectorExecutionException(f"Meta browser-session ingress failed for {url}: {e}") from e

    return payloads


def walk_dicts(node: Any, max_depth: int = 14) -> Iterator[Dict[str, Any]]:
    """Depth-limited walk over every dict inside an arbitrary JSON payload."""
    if max_depth < 0:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk_dicts(value, max_depth - 1)
    elif isinstance(node, list):
        for value in node:
            yield from walk_dicts(value, max_depth - 1)


def extract_records(
    payloads: List[Dict[str, Any]],
    is_record: Callable[[Dict[str, Any]], bool],
    identity: Callable[[Dict[str, Any]], Optional[str]],
    limit: int,
) -> List[Dict[str, Any]]:
    """
    Pull de-duplicated records out of captured payloads.
    Survives the response wrapper being renamed by matching the shape of the entity.
    """
    found: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        for node in walk_dicts(payload):
            if not is_record(node):
                continue
            key = identity(node)
            if not key or key in seen:
                continue
            seen.add(key)
            found.append(node)
            if len(found) >= limit:
                return found
    return found


def extract_trending_topics(payloads: List[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    """
    Extract structured Trending Topics from Threads search GraphQL response envelopes.
    Matches various schema iterations used by Meta for today's trending topics.
    """
    topics: List[Dict[str, Any]] = []
    seen_names: set[str] = set()

    for payload in payloads:
        for node in walk_dicts(payload):
            name = None
            post_count_label = None
            topic_id = str(node.get("id") or node.get("topic_id") or "")

            if "topic" in node and isinstance(node["topic"], str):
                name = node["topic"].strip()
                post_count_label = str(node.get("post_count_label") or node.get("subtitle") or "")
            elif "topic" in node and isinstance(node["topic"], dict):
                t_obj = node["topic"]
                name = str(t_obj.get("name") or t_obj.get("title") or "").strip()
                post_count_label = str(node.get("post_count_label") or t_obj.get("subtitle") or "")
            elif "trend" in node and isinstance(node["trend"], dict):
                t_obj = node["trend"]
                name = str(t_obj.get("name") or t_obj.get("title") or "").strip()
                post_count_label = str(node.get("subtitle") or node.get("post_count_label") or "")
            elif "topic_name" in node and isinstance(node["topic_name"], str):
                name = node["topic_name"].strip()
                post_count_label = str(node.get("subtitle") or node.get("post_count_label") or "")

            if name and name not in seen_names:
                seen_names.add(name)
                numeric_posts = _parse_count_label(post_count_label)
                search_url = f"https://www.threads.net/search?q={urllib.parse.quote(name)}&serp_type=default"
                topics.append(
                    {
                        "topic": name,
                        "topic_id": topic_id,
                        "post_count": numeric_posts,
                        "post_count_label": post_count_label,
                        "search_url": search_url,
                    }
                )
                if len(topics) >= limit:
                    return topics

    return topics


def extract_search_suggestions(payloads: List[Dict[str, Any]], limit: int = 15) -> List[str]:
    """
    Extract search query suggestions/autocomplete terms from captured GraphQL payloads.
    Supports both modern Threads schema ('xdt_api__v1__text_feed__keyword_search' -> 'keywords' -> [{'name': '...'}])
    and legacy fallback keys ('keyword', 'query', 'suggestion').
    """
    suggestions: List[str] = []
    seen: set[str] = set()

    for payload in payloads:
        for node in walk_dicts(payload):
            # 1. Modern Threads keyword autocomplete schema
            if "keywords" in node and isinstance(node["keywords"], list):
                for item in node["keywords"]:
                    if isinstance(item, dict) and "name" in item and isinstance(item["name"], str):
                        kw = item["name"].strip()
                        if kw and kw not in seen and not kw.startswith("http"):
                            seen.add(kw)
                            suggestions.append(kw)
                            if len(suggestions) >= limit:
                                return suggestions

            # 2. Individual suggestion nodes
            text = None
            if "name" in node and isinstance(node["name"], str) and "tag_community_info" in node:
                text = node["name"].strip()
            elif "keyword" in node and isinstance(node["keyword"], str):
                text = node["keyword"].strip()
            elif "query" in node and isinstance(node["query"], str) and len(node["query"]) < 100:
                text = node["query"].strip()
            elif "suggestion" in node and isinstance(node["suggestion"], str):
                text = node["suggestion"].strip()

            if text and text not in seen and not text.startswith("http"):
                seen.add(text)
                suggestions.append(text)
                if len(suggestions) >= limit:
                    return suggestions

    return suggestions


def _parse_count_label(label: Optional[str]) -> int:
    """Helper to convert human-friendly post count string ('12.5K', '1.2M') into integer."""
    if not label:
        return 0
    # "BÀI VIẾT" is Instagram's own Vietnamese label for "POSTS"; it must match the rendered UI verbatim.
    clean = label.upper().replace("POSTS", "").replace("BÀI VIẾT", "").replace(",", ".").strip()
    try:
        if "M" in clean:
            num = float(clean.replace("M", "").strip())
            return int(num * 1_000_000)
        if "K" in clean:
            num = float(clean.replace("K", "").strip())
            return int(num * 1_000)
        digits = "".join(ch for ch in clean if ch.isdigit())
        return int(digits) if digits else 0
    except Exception:
        return 0


def coerce_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def caption_text(node: Dict[str, Any]) -> str:
    caption = node.get("caption")
    if isinstance(caption, dict):
        return str(caption.get("text") or "").strip()
    if isinstance(caption, str):
        return caption.strip()
    return str(node.get("text") or "").strip()


async def collect_threads_search_suggestions_via_browser(
    storage_state: Dict[str, Any],
    keyword: str,
    geo: GeoCode = GeoCode.VN,
    timeout_ms: int = 3000,
) -> List[Dict[str, Any]]:
    """
    Drive a logged-in Playwright context to www.threads.com/search, focus the search input,
    type `keyword` to trigger autocomplete, and capture incoming GraphQL response payloads.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright is not installed; skipping Meta browser-session search suggestions.")
        return []

    payloads: List[Dict[str, Any]] = []
    search_url = "https://www.threads.com/search"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )
            context_kwargs: Dict[str, Any] = {
                "user_agent": USER_AGENT,
                "viewport": {"width": 1280, "height": 900},
                "locale": "vi-VN" if geo == GeoCode.VN else "en-US",
                "storage_state": storage_state,
            }
            if reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER):
                context_kwargs["proxy"] = {"server": reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER)}

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

            async def handle_request(request: Any) -> None:
                try:
                    if "/graphql" in request.url and request.method == "POST":
                        post_data = request.post_data
                        if post_data:
                            params = urllib.parse.parse_qs(post_data)
                            doc_ids = params.get("doc_id")
                            lsds = params.get("lsd")
                            if doc_ids:
                                captured_doc_id = doc_ids[0]
                                captured_lsd = lsds[0] if lsds else None
                                vars_raw = params.get("variables", ["{}"])[0]
                                GraphQLDocIdCache.record_signature_from_payload(
                                    captured_doc_id, captured_lsd, vars_raw
                                )
                except Exception:
                    pass

            page.on("request", handle_request)

            async def handle_response(response: Any) -> None:
                if "/graphql" not in response.url:
                    return
                try:
                    if "json" not in response.headers.get("content-type", ""):
                        return
                    body = await response.json()
                    if isinstance(body, dict):
                        payloads.append(body)
                except Exception:
                    pass

            page.on("response", handle_response)

            await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
            await page.wait_for_timeout(2000)

            input_el = page.locator("input").first
            if await input_el.count() > 0:
                await input_el.fill(keyword)
                await page.wait_for_timeout(timeout_ms)

            await browser.close()
    except Exception as e:
        logger.warning(f"Failed to collect search suggestions via browser: {e}")

    return payloads

