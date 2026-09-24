from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)


class MetaBrowserAuthManager:
    """
    Tier 1 (non-tech) 1-click browser session capture for Meta surfaces.

    Mirrors TikTokAuthManager: open an isolated Playwright Chromium window, let the
    user sign in with their ordinary personal account, then capture the resulting
    storageState (cookies + localStorage) and persist it through the repository,
    which encrypts the payload at rest.

    Stored under its own platform key (e.g. `threads_browser`) so a Tier 2 Graph API
    OAuth record for the same surface can coexist instead of overwriting it.
    """

    PLATFORM_NAME = "meta_browser"
    AUTH_TYPE = "session_cookies"
    LOGIN_URL = "https://www.threads.net/login"
    HOME_URL = "https://www.threads.net/"
    SESSION_COOKIE_NAMES: tuple[str, ...] = ("sessionid", "ds_user_id")
    SESSION_TTL_DAYS = 30

    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )

    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._repository = repository

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    async def is_authenticated(self) -> bool:
        return await self.get_storage_state() is not None

    async def get_storage_state(self) -> Optional[Dict[str, Any]]:
        """Return the persisted storageState, or None when no live session is stored."""
        if not self._repository:
            return None
        creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return None
        if self._is_expired(creds.get("expires_at")):
            logger.info(f"{self.PLATFORM_NAME} browser session has expired; treating as not authenticated.")
            return None
        state = creds.get("credentials_data")
        if not isinstance(state, dict) or not state.get("cookies"):
            return None
        return state

    async def get_auth_status(self) -> Dict[str, Any]:
        creds = None
        if self._repository:
            creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return {
                "platform": self.PLATFORM_NAME,
                "authenticated": False,
                "auth_type": self.AUTH_TYPE,
                "status": "NOT_CONNECTED",
                "message": f"No {self.PLATFORM_NAME} session stored. Run the browser login flow to connect.",
            }

        expires_at = creds.get("expires_at")
        expired = self._is_expired(expires_at)
        state = creds.get("credentials_data") or {}
        return {
            "platform": self.PLATFORM_NAME,
            "authenticated": not expired,
            "auth_type": self.AUTH_TYPE,
            "status": "EXPIRED" if expired else "ACTIVE",
            "cookies_count": len(state.get("cookies", []) or []) if isinstance(state, dict) else 0,
            "expires_at": expires_at,
            "encrypted_at_rest": True,
        }

    async def authenticate_interactive(
        self,
        headless: bool = False,
        timeout_seconds: int = 180,
    ) -> Dict[str, Any]:
        """
        Open a browser window for the user to sign in, then capture and persist the session.

        Deliberately defaults to a visible window: the whole point of Tier 1 is that a
        non-technical user completes a normal login (including 2FA) by hand.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed. Please install `playwright`.")

        logger.info(
            f"Starting {self.PLATFORM_NAME} browser authentication "
            f"(headless={headless}, timeout={timeout_seconds}s)..."
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ],
            )
            context = await browser.new_context(
                user_agent=self.USER_AGENT,
                viewport={"width": 1280, "height": 850},
                locale="vi-VN",
            )
            page = await context.new_page()

            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(1500)

            logged_in = await self._poll_for_session(context, page, timeout_seconds)

            if not logged_in:
                await browser.close()
                return {
                    "success": False,
                    "platform": self.PLATFORM_NAME,
                    "message": (
                        f"Login timed out after {timeout_seconds}s. "
                        "The sign-in was not completed in the browser window."
                    ),
                }

            storage_state = await context.storage_state()
            await browser.close()

        expires_at = datetime.now(timezone.utc) + timedelta(days=self.SESSION_TTL_DAYS)
        await self._persist(storage_state, expires_at)

        return {
            "success": True,
            "platform": self.PLATFORM_NAME,
            "auth_type": self.AUTH_TYPE,
            "tier": "TIER_1_BROWSER_SESSION",
            "message": (
                f"{self.PLATFORM_NAME} browser session captured and stored encrypted. "
                "Public post and hashtag ingress is now available without a Meta Developer App."
            ),
            "cookies_count": len(storage_state.get("cookies", []) or []),
            "expires_at": expires_at.isoformat(),
            "encrypted_at_rest": True,
        }

    async def _poll_for_session(self, context: Any, page: Any, timeout_seconds: int) -> bool:
        """Poll until a session cookie appears or the user runs out of time."""
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            cookies = await context.cookies()
            if self._has_session_cookie(cookies):
                return True
            await asyncio.sleep(2.0)
        return False

    @classmethod
    def _has_session_cookie(cls, cookies: List[Dict[str, Any]]) -> bool:
        for cookie in cookies or []:
            if cookie.get("name") in cls.SESSION_COOKIE_NAMES and cookie.get("value"):
                return True
        return False

    async def _persist(self, storage_state: Dict[str, Any], expires_at: datetime) -> None:
        if not self._repository:
            return
        await self._repository.save_platform_credentials(
            platform=self.PLATFORM_NAME,
            auth_type=self.AUTH_TYPE,
            credentials_data=storage_state,
            is_active=True,
            expires_at=expires_at,
        )
        try:
            await self._repository.log_event(
                component=self.__class__.__name__,
                event_type="BROWSER_SESSION_CAPTURED",
                message=f"{self.PLATFORM_NAME} browser session captured and stored encrypted.",
                level="INFO",
                details={
                    "cookies_count": len(storage_state.get("cookies", []) or []),
                    "expires_at": expires_at.isoformat(),
                },
            )
        except Exception as e:  # audit logging must never mask a successful login
            logger.warning(f"Could not write {self.PLATFORM_NAME} auth audit log: {e}")

    async def clear_auth(self) -> bool:
        if not self._repository:
            return False
        return await self._repository.delete_platform_credentials(self.PLATFORM_NAME)

    @staticmethod
    def _is_expired(raw: Any) -> bool:
        if not raw:
            return False
        try:
            parsed = datetime.fromisoformat(str(raw))
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)


class ThreadsBrowserAuthManager(MetaBrowserAuthManager):
    """1-click Threads session capture for users without a Meta Developer App."""

    PLATFORM_NAME = "threads_browser"
    LOGIN_URL = "https://www.threads.net/login"
    HOME_URL = "https://www.threads.net/"
    SESSION_COOKIE_NAMES = ("sessionid", "ds_user_id")


class InstagramBrowserAuthManager(MetaBrowserAuthManager):
    """1-click Instagram session capture backing public Reels/hashtag ingress."""

    PLATFORM_NAME = "instagram_browser"
    LOGIN_URL = "https://www.instagram.com/accounts/login/"
    HOME_URL = "https://www.instagram.com/"
    SESSION_COOKIE_NAMES = ("sessionid", "ds_user_id")
