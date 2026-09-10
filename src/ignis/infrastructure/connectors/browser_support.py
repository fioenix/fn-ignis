"""What a browser-driven connector has to be able to check about itself.

A connector whose only way in is a browser is healthy when three things hold: the Playwright
module is installed, the Chromium it launches actually exists on disk, and the surface it scrapes
answers. Both TikTok connectors used to answer `return True` unconditionally, so
verify_connectors_health reported them HEALTHY on a host with no browser at all.
"""

import asyncio
import importlib.util
import logging
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# A browser install does not change while the process runs, so the answer is resolved once.
_LAUNCHABLE: Optional[bool] = None
_LAUNCHABLE_LOCK = asyncio.Lock()

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def browser_module_available() -> bool:
    """Whether the Playwright package is importable at all."""
    return importlib.util.find_spec("playwright") is not None


async def browser_launch_available() -> bool:
    """Whether a Chromium this host can actually launch is present.

    `pip install playwright` gives the module without the browsers, so importability alone says
    nothing: that check passed on a host where every browser pass would fail. Playwright is
    asked for the path it would launch rather than guessing at a cache directory, because the
    location moves with PLAYWRIGHT_BROWSERS_PATH and between platforms. Starting the driver
    costs about half a second and does not launch a browser.
    """
    global _LAUNCHABLE
    if _LAUNCHABLE is not None:
        return _LAUNCHABLE

    async with _LAUNCHABLE_LOCK:
        if _LAUNCHABLE is not None:
            return _LAUNCHABLE
        if not browser_module_available():
            _LAUNCHABLE = False
            return _LAUNCHABLE
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                executable = p.chromium.executable_path
            _LAUNCHABLE = bool(executable) and Path(executable).exists()
            if not _LAUNCHABLE:
                logger.warning(
                    "Playwright is installed but its Chromium is not: run "
                    "`playwright install chromium`. Browser-bound connectors cannot pull."
                )
        except Exception as e:
            logger.warning(f"Could not resolve a launchable browser: {e}")
            _LAUNCHABLE = False
        return _LAUNCHABLE


def reset_browser_runtime_cache() -> None:
    """Clear the resolved answer. For tests, and for a host that installs a browser mid-run."""
    global _LAUNCHABLE
    _LAUNCHABLE = None


async def surface_reachable(
    url: str,
    cookie_header: Optional[str] = None,
    timeout: float = 8.0,
) -> bool:
    """Whether the page a connector scrapes answers at all.

    Redirects are followed on purpose. The Creative Center entry URL answers 301 and lands on a
    different path, so refusing redirects the way the Threads probe does would report a working
    connector as broken.
    """
    headers = {"User-Agent": BROWSER_USER_AGENT}
    if cookie_header:
        headers["Cookie"] = cookie_header
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as client:
            response = await client.get(url)
        return response.status_code < 400
    except Exception as e:
        logger.warning(f"Health probe could not reach {url}: {e}")
        return False
