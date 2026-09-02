import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional
from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)


class TikTokAuthManager:
    """
    Manages TikTok login sessions and authentication via Playwright 1-Click / QR Code.
    Captures storageState (cookies, localStorage) and persists securely to the database.
    """

    LOGIN_URL = "https://www.tiktok.com/login"
    EXPLORE_URL = "https://www.tiktok.com/explore"
    PLATFORM_NAME = "tiktok"

    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._repository = repository

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    async def is_authenticated(self) -> bool:
        """Check if the system has an active valid TikTok authentication session."""
        if not self._repository:
            return False
        creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return False
        return True

    async def get_storage_state(self) -> Optional[Dict[str, Any]]:
        """Retrieve persisted storageState from database."""
        if not self._repository:
            return None
        creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return None
        return creds.get("credentials_data")

    async def authenticate_interactive(
        self,
        headless: bool = False,
        timeout_seconds: int = 90,
    ) -> Dict[str, Any]:
        """
        Open a browser context for interactive user login via QR code or credentials.
        Automatically detects successful authentication and persists storageState to DB.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("Playwright is not installed. Please install `playwright`.")

        logger.info(f"Starting TikTok authentication session (headless={headless}, timeout={timeout_seconds}s)...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                ]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 850},
                locale="vi-VN",
            )
            page = await context.new_page()

            logger.info("Navigating to TikTok login page...")
            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)

            # Auto-click QR code button if available
            try:
                qr_btn = (
                    await page.query_selector('text=Sử dụng mã QR')
                    or await page.query_selector('text=Use QR code')
                    or await page.query_selector('a[href*="qrcode"]')
                )
                if qr_btn:
                    await qr_btn.click()
                    await page.wait_for_timeout(1000)
            except Exception as e:
                logger.debug(f"Could not auto-click QR button: {e}")

            # Polling for login session cookies
            start_time = asyncio.get_event_loop().time()
            logged_in = False

            while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
                cookies = await context.cookies()
                for c in cookies:
                    if c.get("name") in ["sessionid", "sessionid_ss", "sid_tt", "uid_tt"] and c.get("value"):
                        logged_in = True
                        break

                current_url = page.url
                if logged_in or (current_url and "/login" not in current_url and "tiktok.com" in current_url):
                    logged_in = True
                    break

                await asyncio.sleep(2.0)

            if not logged_in:
                await browser.close()
                return {
                    "success": False,
                    "message": f"Login timed out ({timeout_seconds}s). QR code was not scanned or session was cancelled.",
                }

            # Retrieve complete storageState
            storage_state = await context.storage_state()
            expires_at = datetime.now(timezone.utc) + timedelta(days=60)

            if self._repository:
                await self._repository.save_platform_credentials(
                    platform=self.PLATFORM_NAME,
                    auth_type="session_cookies",
                    credentials_data=storage_state,
                    is_active=True,
                    expires_at=expires_at,
                )
                await self._repository.log_event(
                    component="TikTokAuthManager",
                    event_type="AUTH_SUCCESS",
                    message="TikTok login successful and session state saved to database.",
                    level="INFO",
                    details={"cookies_count": len(storage_state.get("cookies", [])), "expires_at": expires_at.isoformat()}
                )

            await browser.close()
            return {
                "success": True,
                "platform": self.PLATFORM_NAME,
                "message": "TikTok authentication successful! Session securely persisted.",
                "cookies_count": len(storage_state.get("cookies", [])),
                "expires_at": expires_at.isoformat(),
            }

    async def clear_auth(self) -> bool:
        """Clear active TikTok authentication session."""
        if not self._repository:
            return False
        return await self._repository.delete_platform_credentials(self.PLATFORM_NAME)

