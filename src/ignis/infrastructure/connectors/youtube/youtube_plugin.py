import re
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Tuple
import httpx

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import (
    ConnectorExecutionException,
    ConnectorQuotaExceededException,
)
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

logger = logging.getLogger(__name__)


class YouTubeDataPlugin(IConnectorPlugin):
    """
    Ingress Plugin thu thập YouTube Data: Most Popular Videos & Targeted Keyword Search.
    Sử dụng dữ liệu thật 100% từ YouTube Data API v3 (part=snippet,statistics).
    Áp dụng bộ lọc ngày xuất bản (publishedAfter) nghiêm ngặt và bộ lọc rác (Garbage Rejection).
    """

    BASE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
    SEARCH_API_URL = "https://www.googleapis.com/youtube/v3/search"

    # Các pattern rác không liên quan đến công nghệ / kinh doanh
    GARBAGE_PATTERNS = [
        r"\bMŚ\b", r"\bGr [A-Z]\b", r"\bbóng đá\b", r"\bfootball\b", r"\bmonetization\b",
        r"\bchồng bắt vợ\b", r"\bthiên kim tỷ phú\b", r"\bdrama\b", r"\btiểu tam\b",
        r"\btổng tài\b", r"\bphim ngắn\b", r"\btruyện ngôn tình\b", r"\bkhát khao độc chiếm\b",
        r"\baudio chiếm hữu\b", r"\bchanh non\b", r"\btruyện audio\b", r"\bđọc truyện\b",
        r"\bbao tải\b", r"\bbốc xếp\b", r"\bcánh tay robot\b", r"\bbánh răng\b", r"\bxích tải\b",
        r"\bđồ chơi\b", r"\bmô hình cơ khí\b", r"\bur3\b", r"\brobot gắp\b",
        r"\bphonegrid\b", r"\bphone farm\b", r"\bforex\b", r"\blèm bèm\b",
        r"\boprah\b", r"\bthe dark side of ai\b", r"\btalkshow\b",
        r"\bai psychosis\b", r"\bpsychosis\b", r"\bdating an ai\b", r"\bhẹn hò.*bot\b"
    ]

    def __init__(self, api_key: str = ""):
        self._api_key = api_key

    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    @property
    def name(self) -> str:
        return "YouTube Data API v3"

    def _geo_to_region_code(self, geo: GeoCode) -> str:
        geo_map = {
            GeoCode.VN: "VN",
            GeoCode.US: "US",
            GeoCode.GLOBAL: "US",
        }
        return geo_map.get(geo, "VN")

    def _geo_to_relevance_language(self, geo: GeoCode) -> Optional[str]:
        lang_map = {
            GeoCode.VN: "vi",
            GeoCode.US: "en",
        }
        return lang_map.get(geo, None)

    def _timeframe_to_published_after(self, timeframe_str: str) -> Tuple[str, datetime]:
        """Chuyển đổi timeframe sang định dạng RFC 3339 và datetime UTC."""
        now = datetime.now(timezone.utc)
        tf = str(timeframe_str).lower().strip()

        if tf in ["1d", "24h", "now 1-d", "last_24h"]:
            dt = now - timedelta(days=1)
        elif tf in ["7d", "now 7-d", "last_7d"]:
            dt = now - timedelta(days=7)
        elif tf in ["30d", "1m", "today 1-m", "last_30d"]:
            dt = now - timedelta(days=30)
        elif tf in ["90d", "3m", "today 3-m"]:
            dt = now - timedelta(days=90)
        elif tf in ["12m", "1y", "today 12-m"]:
            dt = now - timedelta(days=365)
        else:
            dt = now - timedelta(days=90 if "90" in tf else 7)

        return dt.strftime("%Y-%m-%dT%H:%M:%SZ"), dt

    def _is_garbage(self, title: str) -> bool:
        for p in self.GARBAGE_PATTERNS:
            if re.search(p, title, re.IGNORECASE):
                return True
        return False

    def _enrich_keyword(self, kw: str, geo: GeoCode) -> str:
        """Nếu từ khóa quá ngắn (viết tắt), kết hợp context để tránh nhiễu ngữ nghĩa."""
        kw_clean = kw.strip()
        if geo == GeoCode.VN:
            if kw_clean.upper() == "RPA":
                return "RPA tự động hóa quy trình"
            elif kw_clean.upper() == "MCP AI":
                return "MCP Model Context Protocol AI"
            elif kw_clean.upper() == "AI AGENT":
                return "AI agent tự động hóa"
        return kw_clean

    async def is_healthy(self) -> bool:
        if not self._api_key:
            return False
        try:
            params = {
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": "VN",
                "maxResults": 1,
                "key": self._api_key,
            }
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self.BASE_API_URL, params=params)
                return resp.status_code == 200
        except Exception as e:
            logger.warning(f"YouTube Plugin Health Check thất bại: {e}")
            return False

    async def fetch_signals(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 50,
    ) -> List[TrendSignal]:
        if not self._api_key:
            raise ConnectorExecutionException("YouTube API Key is missing or not configured.")

        region_code = self._geo_to_region_code(geo)
        max_results = max(1, min(limit, 50))

        params = {
            "part": "snippet,statistics",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max_results,
            "key": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(self.BASE_API_URL, params=params)

                if response.status_code == 403:
                    error_json = response.json()
                    error_details = error_json.get("error", {})
                    errors_list = error_details.get("errors", [])
                    reasons = [err.get("reason") for err in errors_list if isinstance(err, dict)]
                    
                    if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                        logger.error("YouTube API quota exceeded.")
                        raise ConnectorQuotaExceededException("YouTube API quota limit exceeded.")

                    raise ConnectorExecutionException(
                        f"YouTube API 403 Forbidden: {error_details.get('message', 'Access denied')}"
                    )

                response.raise_for_status()
                data = response.json()
        except ConnectorQuotaExceededException:
            raise
        except Exception as e:
            logger.error(f"Lỗi khi gọi YouTube Data API: {e}")
            raise ConnectorExecutionException(f"Failed to fetch YouTube trending videos: {e}") from e

        signals: List[TrendSignal] = []
        items = data.get("items", [])

        for item in items:
            video_id = item.get("id")
            snippet = item.get("snippet", {})
            statistics = item.get("statistics", {})

            title = snippet.get("title", "").strip()
            if not title or self._is_garbage(title):
                continue

            view_count = float(statistics.get("viewCount", 0))
            like_count = int(statistics.get("likeCount", 0))
            comment_count = int(statistics.get("commentCount", 0))
            published_at_str = snippet.get("publishedAt")
            
            try:
                if published_at_str:
                    published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                else:
                    published_at = datetime.now(timezone.utc)
            except Exception:
                published_at = datetime.now(timezone.utc)

            now_utc = datetime.now(timezone.utc)
            hours_diff = max(1.0, (now_utc - published_at).total_seconds() / 3600.0)
            velocity = round(view_count / hours_diff, 2)

            source_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None

            metadata = {
                "video_id": video_id,
                "channel_id": snippet.get("channelId"),
                "channel_title": snippet.get("channelTitle"),
                "category_id": snippet.get("categoryId"),
                "tags": snippet.get("tags", []),
                "views": int(view_count),
                "likes": like_count,
                "comments": comment_count,
                "published_at": published_at_str,
            }

            signal = TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title=title,
                metric_value=view_count,
                growth_velocity=velocity,
                source_url=source_url,
                geo_code=geo,
                metadata=metadata,
                captured_at=published_at,
            )
            signals.append(signal)

        return signals

    async def search_signals(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 20,
        custom_timeframe: Optional[str] = None,
    ) -> List[TrendSignal]:
        """
        Tìm kiếm video YouTube thật theo từ khóa và lấy metrics thật.
        Áp dụng bộ lọc publishedAfter NGHIÊM NGẶT (không nới lỏng bỏ lọc ngày)
        và bộ lọc rác (loại bỏ video bóng đá/drama không liên quan).
        """
        if not self._api_key:
            return []

        signals: List[TrendSignal] = []
        seen_video_ids = set()
        region_code = self._geo_to_region_code(geo)
        relevance_lang = self._geo_to_relevance_language(geo)
        
        tf_str = custom_timeframe or (timeframe.value if hasattr(timeframe, "value") else str(timeframe))
        published_after_str, published_after_dt = self._timeframe_to_published_after(tf_str)

        for raw_kw in keywords:
            search_kw = self._enrich_keyword(raw_kw, geo)
            search_params = {
                "part": "snippet",
                "q": search_kw,
                "type": "video",
                "regionCode": region_code,
                "maxResults": min(limit, 10),
                "order": "relevance",
                "publishedAfter": published_after_str,
                "key": self._api_key,
            }
            if relevance_lang:
                search_params["relevanceLanguage"] = relevance_lang

            video_ids = []
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(self.SEARCH_API_URL, params=search_params)
                    if resp.status_code == 200:
                        search_data = resp.json()
                        for item in search_data.get("items", []):
                            v_id = item.get("id", {}).get("videoId")
                            if v_id and v_id not in seen_video_ids:
                                video_ids.append(v_id)
                                seen_video_ids.add(v_id)

                    if not video_ids:
                        continue

                    # Gọi videos.list batch lấy số liệu thật
                    video_params = {
                        "part": "snippet,statistics",
                        "id": ",".join(video_ids),
                        "key": self._api_key,
                    }
                    videos_resp = await client.get(self.BASE_API_URL, params=video_params)
                    if videos_resp.status_code == 200:
                        videos_data = videos_resp.json()
                        for v_item in videos_data.get("items", []):
                            v_id = v_item.get("id")
                            v_snippet = v_item.get("snippet", {})
                            v_stats = v_item.get("statistics", {})

                            title = v_snippet.get("title", "").strip()
                            if not title or self._is_garbage(title):
                                continue

                            view_count = float(v_stats.get("viewCount", 0))
                            like_count = int(v_stats.get("likeCount", 0))
                            comment_count = int(v_stats.get("commentCount", 0))
                            pub_at_str = v_snippet.get("publishedAt")

                            try:
                                if pub_at_str:
                                    pub_at = datetime.fromisoformat(pub_at_str.replace("Z", "+00:00"))
                                else:
                                    pub_at = datetime.now(timezone.utc)
                            except Exception:
                                pub_at = datetime.now(timezone.utc)

                            # Kiểm tra nghiêm ngặt: nếu video cũ hơn timeframe, BỎ QUA
                            if pub_at < published_after_dt:
                                continue

                            now_utc = datetime.now(timezone.utc)
                            hours_diff = max(1.0, (now_utc - pub_at).total_seconds() / 3600.0)
                            velocity = round(view_count / hours_diff, 2)

                            meta = {
                                "keyword": raw_kw,
                                "video_id": v_id,
                                "channel_title": v_snippet.get("channelTitle"),
                                "channel_id": v_snippet.get("channelId"),
                                "views": int(view_count),
                                "likes": like_count,
                                "comments": comment_count,
                                "published_at": pub_at_str,
                                "timeframe_filter": tf_str,
                            }

                            signals.append(
                                TrendSignal(
                                    platform=PlatformType.YOUTUBE,
                                    raw_title=title,
                                    metric_value=view_count,
                                    growth_velocity=velocity,
                                    source_url=f"https://www.youtube.com/watch?v={v_id}",
                                    geo_code=geo,
                                    metadata=meta,
                                    captured_at=pub_at,
                                )
                            )
            except Exception as e:
                logger.warning(f"YouTube search error for keyword '{raw_kw}': {e}")

        return signals
