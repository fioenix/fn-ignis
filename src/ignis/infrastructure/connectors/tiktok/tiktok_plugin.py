import logging
from datetime import datetime, timezone
from typing import List, Optional
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class TikTokPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập TikTok Trending Hashtags & Videos.
    Zero-Token Ingress.
    """

    BASE_URL = "https://www.tiktok.com/api/explore/item_list/"

    @property
    def platform(self) -> PlatformType:
        return PlatformType.TIKTOK

    @property
    def name(self) -> str:
        return "TikTok Trending Ingress"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }
        params = {
            "count": min(limit, 50),
            "region": "VN" if geo == GeoCode.VN else "US",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(self.BASE_URL, params=params)
                if resp.status_code != 200:
                    logger.warning(f"TikTok response non-200: {resp.status_code}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"Lỗi khi cào TikTok: {e}")
            raise ConnectorExecutionException(f"Failed to fetch TikTok trends: {e}") from e

        signals: List[TrendSignal] = []
        item_list = data.get("data", {}).get("list", []) or data.get("itemList", [])

        for item in item_list:
            item_id = item.get("item_id") or item.get("id")
            title = item.get("title") or item.get("desc", "")
            stats = item.get("stats", {}) or item.get("statistics", {})
            author = item.get("author", {})

            play_count = float(stats.get("play_count") or stats.get("playCount", 0))
            author_id = author.get("unique_id") or author.get("uniqueId", "")
            hashtags = item.get("hashtags", [])

            url = f"https://www.tiktok.com/@{author_id}/video/{item_id}" if author_id and item_id else None

            metadata = {
                "item_id": item_id,
                "author": author_id,
                "author_name": author.get("nickname", ""),
                "likes": int(stats.get("digg_count") or stats.get("diggCount", 0)),
                "comments": int(stats.get("comment_count") or stats.get("commentCount", 0)),
                "shares": int(stats.get("share_count") or stats.get("shareCount", 0)),
                "hashtags": hashtags,
            }

            signal = TrendSignal(
                platform=PlatformType.TIKTOK,
                raw_title=title or f"TikTok Trend #{item_id}",
                metric_value=play_count,
                growth_velocity=0.0,
                source_url=url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
            )
            signals.append(signal)

        return signals
