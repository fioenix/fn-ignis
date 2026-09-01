import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager

logger = logging.getLogger(__name__)


class TikTokCreativeCenterPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập Top Trending Hashtags, số bài đăng, lượt xem và phân loại ngành hàng
    từ TikTok Creative Center (https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en).
    Cung cấp lớp quan sát vĩ mô (Macro Radar) cho thị trường Việt Nam.
    """

    BASE_URL = "https://ads.tiktok.com/business/creativecenter/inspiration/popular/hashtag/pc/en"

    def __init__(self, auth_manager: Optional[TikTokAuthManager] = None):
        self._auth_manager = auth_manager

    def set_auth_manager(self, auth_manager: TikTokAuthManager) -> None:
        self._auth_manager = auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    @property
    def name(self) -> str:
        return "TikTok Creative Center Macro Radar"

    async def is_healthy(self) -> bool:
        return True

    def _parse_metric_number(self, text: str) -> float:
        """Chuyển đổi chuỗi định dạng như '346.2K', '1.9B', '28M' sang số thực float."""
        if not text:
            return 0.0
        t = text.strip().upper()
        match = re.search(r"(\d+(\.\d+)?)\s*([KMB])?", t)
        if not match:
            return 0.0
        num = float(match.group(1))
        unit = match.group(3)
        if unit == "K":
            num *= 1000.0
        elif unit == "M":
            num *= 1000000.0
        elif unit == "B":
            num *= 1000000000.0
        return num

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_7D,
        limit: int = 30,
    ) -> List[TrendSignal]:
        """Thu thập danh sách Top Trending Hashtags từ TikTok Creative Center."""
        period_days = 30 if "30" in str(timeframe) else 7
        signals_data = await self.fetch_macro_trends(geo=geo, period=period_days, limit=limit)
        
        signals: List[TrendSignal] = []
        for item in signals_data:
            hashtag = item.get("hashtag", "").replace("#", "")
            raw_title = f"#{hashtag} ({item.get('category', 'General')})"
            metric_val = item.get("views_count", 0.0) or item.get("posts_count", 0.0)
            
            sig = TrendSignal(
                platform=PlatformType.TIKTOK,
                raw_title=raw_title,
                metric_value=metric_val,
                growth_velocity=0.0,
                source_url=f"https://www.tiktok.com/tag/{hashtag}",
                geo_code=geo,
                metadata={
                    "hashtag": f"#{hashtag}",
                    "rank": item.get("rank"),
                    "category": item.get("category"),
                    "posts_formatted": item.get("posts"),
                    "views_formatted": item.get("views"),
                    "source": "tiktok_creative_center",
                    "period_days": period_days,
                },
                captured_at=datetime.now(timezone.utc),
            )
            signals.append(sig)

        return signals

    async def fetch_macro_trends(
        self,
        geo: GeoCode = GeoCode.VN,
        period: int = 7,
        limit: int = 30,
        industry: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Extract detailed macro ranking trends from TikTok Creative Center with optional industry filtering."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed, skipping Creative Center scrape.")
            return []

        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        results: List[Dict[str, Any]] = []

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
                    "viewport": {"width": 1280, "height": 850},
                    "locale": "vi-VN" if geo == GeoCode.VN else "en-US",
                }
                if storage_state:
                    context_kwargs["storage_state"] = storage_state

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                country_param = "VN" if geo == GeoCode.VN else "US"
                url = f"{self.BASE_URL}?period={period}&countryCode={country_param}"
                
                logger.info(f"Navigating to TikTok Creative Center: {url} (industry filter: {industry})...")
                await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                await page.wait_for_timeout(3500)

                # Select Country
                if geo == GeoCode.VN:
                    try:
                        country_btn = await page.query_selector('text="United States of America"') or await page.query_selector('[class*="countrySelect"]')
                        if country_btn:
                            await country_btn.click()
                            await page.wait_for_timeout(1000)
                            options = await page.query_selector_all('[role="option"], [class*="option"], [class*="item"]')
                            for opt in options:
                                txt = (await opt.inner_text()).strip()
                                if txt in ["Vietnam", "Việt Nam"]:
                                    await opt.click()
                                    await page.wait_for_timeout(3000)
                                    break
                    except Exception as e:
                        logger.debug(f"Country selection handled via params: {e}")

                # Cuộn trang nhẹ để kích hoạt tải thêm
                try:
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(1500)
                except Exception:
                    pass

                text = await page.inner_text("body")
                lines = [t.strip() for t in text.split("\n") if t.strip()]

                # Bóc tách cấu trúc dòng rank & hashtag
                i = 0
                while i < len(lines) - 3:
                    if lines[i].isdigit() and lines[i + 1].startswith("#"):
                        rank = int(lines[i])
                        hashtag_raw = lines[i + 1]
                        category = lines[i + 2]
                        
                        posts_str = ""
                        views_str = ""
                        
                        # Quét tiếp các dòng liền kề để lấy posts và views
                        j = i + 3
                        while j < min(i + 8, len(lines)):
                            if lines[j].upper() == "POSTS" and j > i + 3:
                                posts_str = lines[j - 1]
                            elif lines[j].upper() == "VIEWS" and j > i + 3:
                                views_str = lines[j - 1]
                            elif lines[j].isdigit() and j + 1 < len(lines) and lines[j + 1].startswith("#"):
                                break
                            j += 1

                        # Apply industry filter if specified
                        if not industry or (industry.lower() in category.lower() or industry.lower() in hashtag_raw.lower()):
                            results.append({
                                "rank": rank,
                                "hashtag": hashtag_raw,
                                "category": category,
                                "posts": posts_str,
                                "views": views_str,
                                "posts_count": self._parse_metric_number(posts_str),
                                "views_count": self._parse_metric_number(views_str),
                            })
                        i = j
                    else:
                        i += 1

                    if len(results) >= limit:
                        break

                await browser.close()

        except Exception as e:
            logger.error(f"Error fetching TikTok Creative Center ({geo}): {e}")
            raise ConnectorExecutionException(f"Failed to fetch TikTok Creative Center trends: {e}") from e

        return results

