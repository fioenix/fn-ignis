from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from ignis.domain.value_objects import PlatformType, GeoCode, MomentumCategory

@dataclass
class TrendSignal:
    """Tín hiệu xu hướng đơn lẻ từ một nền tảng cụ thể tại một thời điểm."""
    platform: PlatformType
    raw_title: str
    metric_value: float = 0.0           # Views, Search index (0-100), Likes
    growth_velocity: float = 0.0        # Tốc độ tăng trưởng (% / giờ)
    source_url: Optional[str] = None
    geo_code: GeoCode = GeoCode.VN
    cluster_id: Optional[UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

@dataclass
class TopicCluster:
    """Thực thể đại diện cho một chủ đề xu hướng tổng hợp từ nhiều nền tảng."""
    canonical_name: str
    id: UUID = field(default_factory=uuid4)
    summary_text: Optional[str] = None
    category: str = "general"
    cross_platform_score: float = 0.0
    signals: List[TrendSignal] = field(default_factory=list)
    first_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def momentum_category(self) -> MomentumCategory:
        if self.cross_platform_score >= 80.0:
            return MomentumCategory.BREAKOUT
        elif self.cross_platform_score >= 50.0:
            return MomentumCategory.SURGING
        elif self.cross_platform_score >= 20.0:
            return MomentumCategory.STEADY
        return MomentumCategory.DECLINING
