from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import urllib.parse
from http.cookiejar import Cookie, CookieJar, DefaultCookiePolicy
from typing import Any, Callable, Dict, Iterator, List, Optional, Set, Tuple
from urllib.request import Request

import httpx

from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager

logger = logging.getLogger(__name__)


# Project in the page so unrelated account/bootstrap JSON never leaves the browser.
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


def build_cookie_header(storage_state: Dict[str, Any], target_url: str) -> str:
    """Select only unexpired browser cookies eligible for the actual HTTP destination."""
    # Match the URL HTTPX actually sends, including dot-segment and IDNA normalization.
    try:
        target_url = str(httpx.URL(target_url))
        target = urllib.parse.urlsplit(target_url)
    except (httpx.InvalidURL, ValueError):
        return ""
    if target.scheme not in ("http", "https") or not target.hostname or target.username:
        return ""
    cookies = storage_state.get("cookies", [])
    if not isinstance(cookies, list):
        return ""
    # CookieJar's default Netscape policy otherwise permits host-only cookies on subdomains.
    jar = CookieJar(DefaultCookiePolicy(
        strict_ns_domain=DefaultCookiePolicy.DomainStrictNonDomain,
    ))
    for item in cookies:
        if not isinstance(item, dict) or item.get("partitionKey"):
            continue
        name, value = item.get("name"), item.get("value")
        domain, path = item.get("domain"), item.get("path")
        secure, expires = item.get("secure"), item.get("expires")
        if (
            not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+", name)
            or not isinstance(value, str)
            or not re.fullmatch(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*", value)
            or not isinstance(domain, str)
            or not re.fullmatch(r"\.?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*", domain)
            or not isinstance(path, str) or not path.startswith("/")
            or any(ord(c) < 32 or ord(c) == 127 for c in path)
            or not isinstance(secure, bool)
            or isinstance(expires, bool) or not isinstance(expires, (int, float))
            or not math.isfinite(expires) or (expires < 0 and expires != -1)
        ):
            continue
        jar.set_cookie(Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain.lower(), domain_specified=domain.startswith("."),
            domain_initial_dot=domain.startswith("."), path=path, path_specified=True,
            secure=secure, expires=None if expires == -1 else int(expires),
            discard=expires == -1, comment=None, comment_url=None, rest={},
        ))
    request = Request(target_url)
    jar.add_cookie_header(request)
    return request.get_header("Cookie", "")


def extract_token_from_storage(
    storage_state: Dict[str, Any], token_name: str, target_url: str,
) -> Optional[str]:
    """Choose the first eligible token, respecting CookieJar's longest-path ordering."""
    for cookie in build_cookie_header(storage_state, target_url).split("; "):
        name, separator, value = cookie.partition("=")
        if separator and name == token_name:
            return value
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
    """Retired Threads cookie-HTTP compatibility export; never sends a request."""
    raise ConnectorCapabilityUnavailableException("HOST_BROWSER_REQUIRED: Threads cookie-HTTP collection is retired.")


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
