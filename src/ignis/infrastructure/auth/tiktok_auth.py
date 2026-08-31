import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)


class TikTokAuthManager:
    """
    Quản lý phiên đăng nhập và xác thực TikTok thông qua Playwright 1-Click / QR Code.
    Bắt storageState (cookies, localStorage) và lưu trữ bền vững vào DB.
    """

    LOGIN_URL = "https://www.tiktok.com/login/phone-or-email/qrcode"
    EXPLORE_URL = "https://www.tiktok.com/explore"
    PLATFORM_NAME = "tiktok"

    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._repository = repository

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    async def is_authenticated(self) -> bool:
        """Kiểm tra xem hệ thống đã có session TikTok hợp lệ chưa."""
        if not self._repository:
            return False
        creds = await self._repository.get_platform_credentials(self.PLATFORM_NAME)
        if not creds or not creds.get("is_active"):
            return False
        return True

    async def get_storage_state(self) -> Optional[Dict[str, Any]]:
        """Lấy storageState đã lưu từ Database."""
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
        Mở cửa sổ trình duyệt để người dùng đăng nhập TikTok bằng QR Code hoặc tài khoản.
        Tự động phát hiện khi đăng nhập thành công và lưu storageState vào DB.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise RuntimeError("Playwright chưa được cài đặt. Vui lòng cài `playwright`.")

        logger.info(f"Khởi động phiên đăng nhập TikTok (headless={headless}, timeout={timeout_seconds}s)...")

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

            logger.info("Đang điều hướng đến trang QR Login của TikTok...")
            await page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

            # Polling kiểm tra cookies đăng nhập (sessionid, sid_tt, uid_tt)
            start_time = asyncio.get_event_loop().time()
            logged_in = False
            session_cookie = None

            while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
                cookies = await context.cookies()
                for c in cookies:
                    if c.get("name") in ["sessionid", "sessionid_ss", "sid_tt", "uid_tt"] and c.get("value"):
                        logged_in = True
                        session_cookie = c.get("value")
                        break

                if logged_in:
                    break
                await asyncio.sleep(2.0)

            if not logged_in:
                await browser.close()
                return {
                    "success": False,
                    "message": f"Hết thời gian chờ đăng nhập ({timeout_seconds}s). Người dùng chưa quét mã QR hoặc hủy phiên.",
                }

            # Lấy toàn bộ storageState
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
                    message="Đăng nhập TikTok thành công và lưu session vào database.",
                    level="INFO",
                    details={"cookies_count": len(storage_state.get("cookies", [])), "expires_at": expires_at.isoformat()}
                )

            await browser.close()
            return {
                "success": True,
                "platform": self.PLATFORM_NAME,
                "message": "Xác thực TikTok thành công! Session đã được lưu trữ bền vững.",
                "cookies_count": len(storage_state.get("cookies", [])),
                "expires_at": expires_at.isoformat(),
            }

    async def clear_auth(self) -> bool:
        """Xóa session đăng nhập hiện tại."""
        if not self._repository:
            return False
        return await self._repository.delete_platform_credentials(self.PLATFORM_NAME)
