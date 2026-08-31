import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from ignis.domain.value_objects import PlatformType, GeoCode, MomentumCategory


def generate_mission_shortcode(title: str, geo: GeoCode = GeoCode.VN, timeframe: str = "7d", uid: Optional[UUID] = None) -> str:
    """Sinh shortcode thân thiện dễ nhớ cho User (ví dụ: VN-AI-AGENT-90D hoặc M-8423AA3A)."""
    clean_words = re.findall(r"[a-zA-Z0-9]+", title.upper())
    slug = "-".join(clean_words[:2]) if clean_words else "TREND"
    tf_clean = re.sub(r"[^0-9A-Z]", "", timeframe.upper())
    geo_clean = geo.value if hasattr(geo, "value") else str(geo)
    
    hex_suffix = (str(uid)[:4]).upper() if uid else "01"
    return f"{geo_clean}-{slug}-{tf_clean}-{hex_suffix}"


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
    mission_id: Optional[UUID] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TopicCluster:
    """Thực thể đại diện cho một cụm chủ đề xu hướng tổng hợp từ nhiều nền tảng."""
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


@dataclass
class ResearchMission:
    """Nhiệm vụ / Chiến dịch nghiên cứu xu hướng theo chủ đề và từ khóa cụ thể."""
    title: str
    keywords: List[str]
    id: UUID = field(default_factory=uuid4)
    shortcode: str = ""
    agent: str = "claude"                  # claude_desktop, claude_code, codex, antigravity
    session_id: Optional[str] = None       # codex://threads/..., conversation_id, session_id
    platforms: List[PlatformType] = field(default_factory=lambda: [
        PlatformType.GOOGLE_TRENDS,
        PlatformType.YOUTUBE,
        PlatformType.TIKTOK,
        PlatformType.THREADS,
        PlatformType.REELS,
    ])
    geo_code: GeoCode = GeoCode.VN
    timeframe: str = "7d"
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED
    summary: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.shortcode:
            self.shortcode = generate_mission_shortcode(self.title, self.geo_code, self.timeframe, self.id)
