from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from enum import Enum

from ignis.domain.value_objects import PlatformType


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"                  # High statistical confidence (>= 80%)
    MEDIUM = "MEDIUM"              # Medium statistical confidence (60% - 79%)
    LOW = "LOW"                    # Low confidence or single-source data (40% - 59%)
    UNRELIABLE = "UNRELIABLE"      # Insufficient or unreliable sample (< 40%)


class TrendMaturityStage(str, Enum):
    EMERGING = "EMERGING"          # Early emerging trend (High search velocity, low content supply)
    HYPING = "HYPING"              # Rapid acceleration phase (Surging views across platforms)
    MATURE = "MATURE"              # Mature / mainstream phase (High supply, steady viewership)
    FADING = "FADING"              # Declining interest / decaying velocity


class ChannelHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"              # Ingress succeeded with at least one signal
    EMPTY_NO_DATA = "EMPTY_NO_DATA"  # Channel ran fine but returned no keyword match
    AUTH_REQUIRED = "AUTH_REQUIRED"  # No token / browser session bound to the channel
    RATE_LIMITED = "RATE_LIMITED"    # Quota or HTTP 429 ceiling reached
    DEGRADED = "DEGRADED"            # Network error / soft-block (Circuit Breaker OPEN)


@dataclass
class CitationEvidence:
    """Concrete source evidence backing a strategic statement."""
    citation_id: str                     # 'CIT-01', 'CIT-02', ...
    platform: PlatformType
    title_or_query: str                  # Article / video title or search keyword
    metric_highlight: str                # '120K views', '+180% velocity', '45 comments'
    author_or_channel: Optional[str] = None
    url: Optional[str] = None
    excerpt: Optional[str] = None        # Representative comment / argument snippet


@dataclass
class ChannelDataSummary:
    """Per-channel ingress audit record."""
    platform: PlatformType
    status: ChannelHealthStatus
    signals_count: int
    timeframe_used: str                  # e.g. '30d (VN)'
    top_citation: Optional[CitationEvidence] = None
    notes: Optional[str] = None          # Warning note when empty / failing


@dataclass
class StrategicInsight:
    """Strategic statement bound to its supporting evidence."""
    statement: str
    citations: List[CitationEvidence] = field(default_factory=list)


@dataclass
class QualityScorecard:
    """Quality scorecard assessing data integrity, language accuracy, and sample validity."""
    coverage_score: float = 0.0          # % of target platforms with verified data (0-100)
    language_precision: float = 0.0      # % of signals accurately localized to target market (0-100)
    data_freshness_score: float = 0.0    # Timeframe freshness score (0-100)
    creator_diversity_score: float = 0.0 # Independent creator / channel entropy (0-100)
    overall_confidence: float = 0.0      # Composite confidence score (0-100)
    confidence_level: ConfidenceLevel = ConfidenceLevel.LOW
    flaws_detected: List[str] = field(default_factory=list)
    strengths_detected: List[str] = field(default_factory=list)


@dataclass
class MarketOpportunity:
    """Market opportunity and white space identified through cross-platform correlation."""
    topic: str
    opportunity_type: str                # 'HIGH_DEMAND_LOW_SUPPLY', 'EARLY_MOVER_ADVANTAGE', 'ENTERPRISE_GAP'
    search_interest_score: float         # Search demand from Google Trends (0-100)
    content_supply_score: float          # Content supply volume from YouTube/TikTok (0-100)
    opportunity_index: float             # Opportunity Index = (Search - Supply) * Sample Damping
    strategic_recommendation: str
    supporting_signals: List[str] = field(default_factory=list)


@dataclass
class HarnessResearchReport:
    """Synthesized strategic dossier produced by the Autonomous Agent Harness."""
    mission_id: str
    title: str
    scorecard: QualityScorecard
    maturity_stage: TrendMaturityStage
    channel_summaries: List[ChannelDataSummary] = field(default_factory=list)
    verified_cross_platform_trends: List[Dict[str, Any]] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    strategic_insights: List[StrategicInsight] = field(default_factory=list)
    actionable_takeaways: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

