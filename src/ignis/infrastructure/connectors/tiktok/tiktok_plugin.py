import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager

logger = logging.getLogger(__name__)


class TikTokPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập TikTok Trending & Keyword Search.
    Hỗ trợ cả authenticated Playwright context (với storageState) và fallback HTTP client.
    Zero-Token Ingress.
    """

    EXPLORE_URL = "https://www.tiktok.com/explore"
    SEARCH_BASE_URL = "https://www.tiktok.com/search?q="

    def __init__(self, auth_manager: Optional[TikTokAuthManager] = None):
        self._auth_manager = auth_manager

    def set_auth_manager(self, auth_manager: TikTokAuthManager) -> None:
        self._auth_manager = auth_manager

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    @property
    def name(self) -> str:
        return "TikTok Trending & Search Ingress"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        """Thu thập các video thịnh hành trên TikTok Explore."""
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
    ) -> List[TrendSignal]:
        """Tìm kiếm video xu hướng theo từ khóa cụ thể trên TikTok."""
        storage_state = None
        if self._auth_manager:
            storage_state = await self._auth_manager.get_storage_state()

        all_signals: List[TrendSignal] = []
        for kw in keywords[:5]: # Giới hạn tối đa 5 keywords mỗi lượt để tối ưu thời gian
            url = f"{self.SEARCH_BASE_URL}{httpx.URL('', params={'q': kw}).query[2:]}"
            signals = await self._fetch_via_playwright(
                url=url,
                storage_state=storage_state,
                geo=geo,
                limit=limit,
                keyword=kw,
            )
            all_signals.extend(signals)

        return all_signals

    async def _fetch_via_playwright(
        self,
        url: str,
        storage_state: Optional[Dict[str, Any]],
        geo: GeoCode,
        limit: int = 30,
        keyword: Optional[str] = None,
    ) -> List[TrendSignal]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright chưa được cài đặt, bỏ qua cào TikTok.")
            return []

        signals: List[TrendSignal] = []
        captured_items: List[Dict[str, Any]] = []

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
                if storage_state:
                    context_kwargs["storage_state"] = storage_state

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                # Lắng nghe các response API JSON ngầm
                async def handle_response(response):
                    if any(k in response.url for k in ["item_list", "search/item", "search/general"]):
                        try:
                            ct = response.headers.get("content-type", "")
                            if "json" in ct:
                                body = await response.json()
                                items = body.get("itemList") or body.get("data", {}).get("list", []) or body.get("data", [])
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, dict):
                                            captured_items.append(item)
                        except Exception:
                            pass

                page.on("response", handle_response)

                logger.info(f"TikTok Ingress navigating to {url}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(3500)

                # 1. Chuyển đổi từ API JSON nếu bắt được
                for item in captured_items:
                    sig = self._parse_json_item(item, geo, keyword)
                    if sig:
                        signals.append(sig)
                    if len(signals) >= limit:
                        break

                # 2. Nếu API không bắt được, bóc tách trực tiếp từ DOM cards
                if not signals:
                    cards = await page.query_selector_all(
                        'div[data-e2e="search_top-item"], div[data-e2e="search-card-item"], div[class*="DivItemContainer"], div[data-e2e="explore-item"]'
                    )
                    for card in cards[:limit]:
                        sig = await self._parse_dom_card(card, geo, keyword)
                        if sig:
                            signals.append(sig)

                await browser.close()

        except Exception as e:
            logger.error(f"Lỗi khi thực thi TikTok Ingress ({url}): {e}")
            raise ConnectorExecutionException(f"Failed to fetch TikTok signals: {e}") from e

        return signals

    def _parse_json_item(self, item: Dict[str, Any], geo: GeoCode, keyword: Optional[str]) -> Optional[TrendSignal]:
        item_id = item.get("id") or item.get("item_id") or item.get("aweme_id")
        title = item.get("desc") or item.get("title", "")
        stats = item.get("stats") or item.get("statistics", {}) or {}
        author = item.get("author") or {}

        if not item_id and not title:
            return None

        play_count = float(stats.get("playCount") or stats.get("play_count", 0))
        author_id = author.get("uniqueId") or author.get("unique_id", "")
        url = f"https://www.tiktok.com/@{author_id}/video/{item_id}" if author_id and item_id else None

        metadata = {
            "item_id": item_id,
            "author": author_id,
            "author_name": author.get("nickname", ""),
            "likes": int(stats.get("diggCount") or stats.get("digg_count", 0)),
            "comments": int(stats.get("commentCount") or stats.get("comment_count", 0)),
            "shares": int(stats.get("shareCount") or stats.get("share_count", 0)),
            "keyword": keyword,
        }

        return TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title=title or f"TikTok Video #{item_id}",
            metric_value=play_count or float(metadata["likes"]),
            growth_velocity=0.0,
            source_url=url,
            geo_code=geo,
            metadata=metadata,
            captured_at=datetime.now(timezone.utc),
        )

    async def _parse_dom_card(self, card, geo: GeoCode, keyword: Optional[str]) -> Optional[TrendSignal]:
        try:
            link_elem = await card.query_selector('a[href*="/video/"]')
            url = await link_elem.get_attribute("href") if link_elem else None

            text = await card.inner_text()
            lines = [t.strip() for t in text.split("\n") if t.strip()]
            if not lines:
                return None

            # Dòng đầu hoặc số thường là metric (likes/views), các dòng tiếp theo là title và author
            metric_val = 0.0
            raw_title = " ".join(lines)
            
            # Cố gắng bóc tách metric từ các ký tự như "521", "1.2K", "3.4M"
            match = re.search(r"(\d+(\.\d+)?)\s*([KkMmBb])?", lines[0])
            if match:
                num = float(match.group(1))
                unit = (match.group(3) or "").upper()
                if unit == "K":
                    num *= 1000
                elif unit == "M":
                    num *= 1000000
                metric_val = num
                if len(lines) > 1:
                    raw_title = " ".join(lines[1:])

            metadata = {
                "source_text": raw_title[:300],
                "keyword": keyword,
            }

            return TrendSignal(
                platform=PlatformType.TIKTOK,
                raw_title=raw_title[:250],
                metric_value=metric_val,
                growth_velocity=0.0,
                source_url=url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
            )
        except Exception:
            return None
