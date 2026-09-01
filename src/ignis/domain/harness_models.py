from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any
from enum import Enum


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"                  # Độ tin cậy cao (>= 80%)
    MEDIUM = "MEDIUM"              # Độ tin cậy trung bình (60% - 79%)
    LOW = "LOW"                    # Dữ liệu còn mỏng hoặc đơn kênh (40% - 59%)
    UNRELIABLE = "UNRELIABLE"      # Dữ liệu không đáng tin cậy (< 40%)


class TrendMaturityStage(str, Enum):
    EMERGING = "EMERGING"          # Xu hướng mới nổi (Search cao, ít nội dung, velocity cao)
    HYPING = "HYPING"              # Giai đoạn bùng nổ (Views tăng vọt trên nhiều kênh)
    MATURE = "MATURE"              # Giai đoạn bão hòa / phổ cập (Nhiều nhà sáng tạo, view ổn định)
    FADING = "FADING"              # Xu hướng suy giảm


@dataclass
class QualityScorecard:
    """Bảng đánh giá chất lượng và độ tin cậy của bộ dữ liệu nghiên cứu."""
    coverage_score: float = 0.0          # % kênh thu thập thành công dữ liệu thật (0-100)
    language_precision: float = 0.0      # % tín hiệu đúng ngôn ngữ thị trường mục tiêu (0-100)
    data_freshness_score: float = 0.0    # Điểm độ tươi của dữ liệu (0-100)
    creator_diversity_score: float = 0.0 # Độ đa dạng nguồn phát tán tín hiệu (0-100)
    overall_confidence: float = 0.0      # Điểm tin cậy tổng thể (0-100)
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    flaws_detected: List[str] = field(default_factory=list)
    strengths_detected: List[str] = field(default_factory=list)


@dataclass
class MarketOpportunity:
    """Khoảng trống thị trường / Cơ hội kinh doanh phát hiện từ đối chiếu đa kênh."""
    topic: str
    opportunity_type: str                # 'HIGH_DEMAND_LOW_SUPPLY', 'EARLY_MOVER_ADVANTAGE', 'ENTERPRISE_GAP'
    search_interest_score: float         # Nhu cầu tìm kiếm từ Google Trends (0-100)
    content_supply_score: float          # Nguồn cung nội dung từ YouTube/TikTok (0-100)
    opportunity_index: float             # Điểm cơ hội = Search Interest - Content Supply
    strategic_recommendation: str
    supporting_signals: List[str] = field(default_factory=list)


@dataclass
class HarnessResearchReport:
    """Báo cáo tổng hợp từ Agent Harness với đầy đủ luận điểm chiến lược và kiểm định chất lượng."""
    mission_id: str
    title: str
    scorecard: QualityScorecard
    maturity_stage: TrendMaturityStage
    verified_cross_platform_trends: List[Dict[str, Any]] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    strategic_insights: List[str] = field(default_factory=list)
    actionable_takeaways: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
