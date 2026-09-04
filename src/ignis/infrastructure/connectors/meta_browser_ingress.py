from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Iterator, List, Optional

from ignis.config import settings
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode

logger = logging.getLogger(__name__)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


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

    This is the Tier 1 ingress transport: it reuses the captured browser session, so it
    sees exactly the public content the signed-in user would see, with no Meta App Review.
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
            if settings.PLAYWRIGHT_PROXY_SERVER:
                context_kwargs["proxy"] = {"server": settings.PLAYWRIGHT_PROXY_SERVER}

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()

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

    Meta's private GraphQL envelopes change shape often, so match on the *shape of a post*
    rather than on a fixed path — that survives the response wrapper being renamed.
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
