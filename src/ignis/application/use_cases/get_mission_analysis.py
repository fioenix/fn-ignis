import logging
from typing import Dict, Any, Optional
from uuid import UUID
from collections import defaultdict

from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)


class GetMissionAnalysisUseCase:
    """
    Use Case lấy dữ liệu phân tích của Mission tối ưu hóa Token (Token-Efficient).
    Tóm lược dữ liệu, trích xuất top signals và loại bỏ metadata rác để không làm tràn context của AI Agent.
    """

    def __init__(self, repository: ITrendRepository):
        self._repo = repository

    async def execute(
        self,
        mission_id: UUID,
        limit: int = 25,
        platform_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} không tồn tại.")

        signals = await self._repo.get_mission_signals(mission_id)

        # Lọc theo platform nếu có
        if platform_filter:
            signals = [
                s for s in signals 
                if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)).lower() == platform_filter.lower()
            ]

        # Thống kê phân bố nền tảng và kênh phát sóng
        platform_breakdown = defaultdict(int)
        channel_counts = defaultdict(int)
        total_views = 0.0

        for s in signals:
            p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            platform_breakdown[p_val] += 1
            
            ch = s.metadata.get("channel_title")
            if ch:
                channel_counts[ch] += 1
            if p_val == "youtube":
                total_views += s.metric_value

        # Sắp xếp signals theo độ nổi bật (views/metric giảm dần)
        sorted_signals = sorted(signals, key=lambda x: (x.metric_value, x.growth_velocity), reverse=True)
        top_signals = sorted_signals[:limit]

        # Tinh gọn metadata để tiết kiệm token
        compact_signals = []
        for s in top_signals:
            p_str = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            
            clean_meta = {}
            if "channel_title" in s.metadata:
                clean_meta["channel"] = s.metadata["channel_title"]
            if "likes" in s.metadata:
                clean_meta["likes"] = s.metadata["likes"]
            if "comments" in s.metadata:
                clean_meta["comments"] = s.metadata["comments"]
            if "related_queries" in s.metadata:
                clean_meta["related_queries"] = s.metadata["related_queries"][:5]
            if "keyword" in s.metadata:
                clean_meta["keyword"] = s.metadata["keyword"]

            compact_signals.append({
                "platform": p_str,
                "title": s.raw_title,
                "metric_value": s.metric_value,
                "velocity_per_hour": s.growth_velocity,
                "url": s.source_url,
                "metadata": clean_meta,
            })

        # Top 5 kênh hoạt động mạnh nhất
        top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        return {
            "mission": {
                "id": str(mission.id),
                "title": mission.title,
                "keywords": mission.keywords,
                "geo": mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
                "timeframe": mission.timeframe,
                "status": mission.status,
                "summary": mission.summary,
            },
            "stats": {
                "total_signals_collected": len(signals),
                "platform_breakdown": dict(platform_breakdown),
                "total_youtube_views": int(total_views),
                "top_creators": [{"channel": ch, "video_count": cnt} for ch, cnt in top_channels],
                "signals_returned": len(compact_signals),
                "note": f"Hiển thị Top {len(compact_signals)} tín hiệu có tương tác cao nhất. Sử dụng generate_mission_artifact để xem toàn bộ danh sách trong HTML."
            },
            "top_signals": compact_signals,
        }
