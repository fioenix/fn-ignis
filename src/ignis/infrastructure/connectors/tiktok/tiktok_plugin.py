import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.author_identity import assign_author
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorCapabilityUnavailableException, ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, IngestRuntime, IngressScope, PlatformType, Timeframe
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager
from ignis.config import reveal_secret, settings
from ignis.infrastructure.security.pii_sanitizer import (
    mask_author_identity_text,
    sanitize_pii_text,
    tokenise_mentions,
)


logger = logging.getLogger(__name__)


class TikTokPlugin(IConnectorPlugin):
    """
    TikTok public video comments for get_tiktok_video_comments.
    Explore and built-in keyword search are retired; TikTok search runs through the host browser.
    """

    def __init__(self, auth_manager: Optional[TikTokAuthManager] = None):
        self._auth_manager = auth_manager

    def set_auth_manager(self, auth_manager: TikTokAuthManager) -> None:
        self._auth_manager = auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    @property
    def plugin_id(self) -> str:
        # Distinct from the retired Creative Center plugin, which served the same platform.
        return "tiktok_video_grid"

    @property
    def name(self) -> str:
        return "TikTok Trending & Search Ingress"

    async def is_healthy(self) -> bool:
        """The retired Explore and search collection cannot be healthy."""
        return False

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
        """Retained signature; built-in Explore collection is retired."""
        raise ConnectorCapabilityUnavailableException(
            "HOST_BROWSER_REQUIRED: Built-in TikTok collection is retired; prepare an authorized host-browser search."
        )

    @staticmethod
    def canonical_comment_video_url(video_url: str) -> str:
        """Accept www TikTok HTTPS video forms only; discard tracking and author identity."""
        try:
            if not isinstance(video_url, str) or any(ord(char) <= 32 for char in video_url):
                raise ValueError
            parsed = urlsplit(video_url)
            match = re.fullmatch(r"/(?:@[\w.-]*/video|video|share/video)/([0-9]+)/?", parsed.path)
            if parsed.scheme != "https" or parsed.netloc != "www.tiktok.com" or not match:
                raise ValueError
        except ValueError:
            raise ValueError("Invalid TikTok video URL") from None
        return "https://www.tiktok.com/share/video/" + match.group(1)

    async def fetch_video_comments(
        self,
        video_url: str,
        limit: int = 30,
        author_key: Optional[bytes] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch public comments under a specific TikTok video using in-page API with Playwright session context.

        With `author_key`, each comment carries an `author_assignment`: a marker under that key,
        so a caller can count distinct commenters in one response. The key is the caller's and
        is never stored; without it no author fact is produced at all (Spec 015).
        """
        canonical_url = self.canonical_comment_video_url(video_url)
        aweme_id = canonical_url.rsplit("/", 1)[1]

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
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                    ]
                )
                try:
                    context_kwargs: Dict[str, Any] = {
                        "viewport": {"width": 1280, "height": 800},
                        "locale": "vi-VN",
                    }
                    if reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER):
                        context_kwargs["proxy"] = {"server": reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER)}
                    if storage_state:
                        context_kwargs["storage_state"] = storage_state


                    context = await browser.new_context(**context_kwargs)
                    page = await context.new_page()

                    async def contain_navigation(route):
                        request = route.request
                        if request.is_navigation_request():
                            try:
                                allowed = self.canonical_comment_video_url(request.url) == canonical_url
                            except ValueError:
                                allowed = False
                            if not allowed:
                                await route.abort()
                                return
                        await route.continue_()

                    await context.route("**/*", contain_navigation)
                    await page.goto(canonical_url, wait_until="domcontentloaded", timeout=25000)
                    if self.canonical_comment_video_url(page.url) != canonical_url:
                        raise ValueError("TikTok comment navigation left the requested video")

                    safe_limit = max(5, min(limit, 50))
                    js_fetch = f"""
                        async () => {{
                            try {{
                                if (location.origin !== 'https://www.tiktok.com') throw new Error('Invalid comment origin');
                                const url = `https://www.tiktok.com/api/comment/list/?aid=1988&aweme_id={aweme_id}&count={safe_limit}&cursor=0`;
                                const resp = await fetch(url, {{redirect: 'error'}});
                                return await resp.json();
                            }} catch (e) {{
                                return {{ error: e.toString() }};
                            }}
                        }}
                    """
                    api_data = await page.evaluate(js_fetch)
                    if not isinstance(api_data, dict) or "error" in api_data:
                        raise ValueError("TikTok comment API request failed")
                    raw_comments = api_data.get("comments", [])

                    # No commenter identity leaves this loop, not even a pseudonym: a fixed-salt hash
                    # links one commenter across every mission and leaks a prefix of the name
                    # (Spec 015, research R3). The comment id is the comment's own content reference.
                    for c in raw_comments:
                        if isinstance(c, dict):
                            cmt_text = c.get("text", "").strip()
                            if cmt_text:
                                # Redact phone numbers, emails, and credentials
                                redacted_text = tokenise_mentions(sanitize_pii_text(cmt_text), {})

                                comment = {
                                    "comment_id": str(c.get("cid") or "") or None,
                                    "text": redacted_text,
                                    "likes": c.get("digg_count", 0),
                                    "reply_count": c.get("reply_comment_total", 0),
                                    "created_at": c.get("create_time"),
                                }
                                if author_key is not None:
                                    user = c.get("user") or {}
                                    comment["author_assignment"] = assign_author(
                                        PlatformType.TIKTOK,
                                        {"user_id": user.get("uid"), "unique_id": user.get("unique_id")},
                                        None,
                                        author_key,
                                    )
                                comments.append(comment)




                finally:
                    await browser.close()

        except Exception as e:
            logger.error(
                "Error scraping comments for video %s: %s",
                canonical_url,
                mask_author_identity_text(str(e)),
            )
            raise ConnectorExecutionException(
                f"Failed to fetch TikTok comments: {mask_author_identity_text(str(e))}"
            ) from e

        return comments
