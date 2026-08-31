import logging
from datetime import datetime, timezone
from typing import List, Optional
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class ReelsPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập Instagram Reels & Audio Trending.
    Zero-Token Ingress.
    """

    BASE_URL = "https://www.instagram.com/api/v1/clips/discover/"

    @property
    def platform(self) -> PlatformType:
        return PlatformType.REELS

    @property
    def name(self) -> str:
        return "Instagram Reels Trending"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get(self.BASE_URL, params={"max_id": "", "page_size": min(limit, 50)})
                if resp.status_code != 200:
                    logger.warning(f"Reels response non-200: {resp.status_code}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"Lỗi khi cào Reels: {e}")
            raise ConnectorExecutionException(f"Failed to fetch Reels signals: {e}") from e

        signals: List[TrendSignal] = []
        items = data.get("items", []) or data.get("clips", [])

        for item in items:
            reel_id = item.get("id")
            code = item.get("code", "")
            caption_obj = item.get("caption", {})
            caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else str(caption_obj or "")
            user = item.get("user", {})
            username = user.get("username", "")

            play_count = float(item.get("play_count", 0))
            like_count = int(item.get("like_count", 0))
            music = item.get("music_metadata", {})
            music_title = music.get("music_title", "")

            url = f"https://www.instagram.com/reel/{code}/" if code else None

            metadata = {
                "reel_id": reel_id,
                "username": username,
                "music_title": music_title,
                "likes": like_count,
                "comments": int(item.get("comment_count", 0)),
            }

            signal = TrendSignal(
                platform=PlatformType.REELS,
                raw_title=caption[:200] or f"Instagram Reel #{reel_id}",
                metric_value=play_count,
                growth_velocity=0.0,
                source_url=url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
            )
            signals.append(signal)

        return signals
