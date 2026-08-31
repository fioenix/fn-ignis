import logging
from datetime import datetime, timezone
from typing import List, Optional
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class ThreadsPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập bài viết thảo luận thịnh hành trên Meta Threads.
    Zero-Token Ingress.
    """

    BASE_URL = "https://www.threads.net/api/graphql"

    @property
    def platform(self) -> PlatformType:
        return PlatformType.THREADS

    @property
    def name(self) -> str:
        return "Threads Trending Discussions"

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
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
                resp = await client.get("https://www.threads.net/api/trending", params={"limit": min(limit, 50)})
                if resp.status_code != 200:
                    logger.warning(f"Threads response non-200: {resp.status_code}")
                    return []
                data = resp.json()
        except Exception as e:
            logger.error(f"Lỗi khi cào Threads: {e}")
            raise ConnectorExecutionException(f"Failed to fetch Threads signals: {e}") from e

        signals: List[TrendSignal] = []
        media_list = data.get("data", {}).get("mediaData", []) or data.get("items", [])

        for item in media_list:
            post_id = item.get("id")
            code = item.get("code", "")
            caption_obj = item.get("caption", {})
            caption = caption_obj.get("text", "") if isinstance(caption_obj, dict) else str(caption_obj or "")
            user = item.get("user", {})
            username = user.get("username", "")

            like_count = float(item.get("like_count", 0))
            reply_count = int(item.get("reply_count", 0))

            url = f"https://www.threads.net/@{username}/post/{code}" if username and code else None

            metadata = {
                "post_id": post_id,
                "username": username,
                "reply_count": reply_count,
                "like_count": int(like_count),
            }

            signal = TrendSignal(
                platform=PlatformType.THREADS,
                raw_title=caption[:200] or f"Threads Post #{post_id}",
                metric_value=like_count,
                growth_velocity=0.0,
                source_url=url,
                geo_code=geo,
                metadata=metadata,
                captured_at=datetime.now(timezone.utc),
            )
            signals.append(signal)

        return signals
