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
    """Concrete source evidence backing a strategic statement.

    `observation_id` is the identity. A URL or a title is what one sighting reported and is
    display payload only: the corpus already contains URLs reporting two different titles, so a
    citation keyed on either can merge two pieces of evidence or split one in half. A citation
    without an observation_id is evidence that has not been stored yet, and a Market conclusion
    may not rest on one.
    """
    citation_id: str                     # 'CIT-01', 'CIT-02', ...
    platform: PlatformType
    title_or_query: str                  # Article / video title or search keyword
    metric_highlight: str                # '120K views', '+180% velocity', '45 comments'
    author_or_channel: Optional[str] = None
    url: Optional[str] = None
    excerpt: Optional[str] = None        # Representative comment / argument snippet
    observation_id: Optional[str] = None  # Canonical evidence identity
    source_id: Optional[str] = None       # The external object, for display
    connector_surface: Optional[str] = None  # Which probe returned it (e.g. 'tiktok_creative_center')


@dataclass
class ChannelDataSummary:
    """Per-connector-surface ingress audit record.

    Keyed by surface, not by platform. One platform can be served by several probes, and a
    platform-level aggregate lets a healthy TikTok video grid hide a failed TikTok comments
    probe -- which reads, downstream, as a market with no customer voice rather than as a probe
    that did not run.
    """
    platform: PlatformType
    status: ChannelHealthStatus
    signals_count: int
    timeframe_used: str                  # e.g. '30d (VN)'
    top_citation: Optional[CitationEvidence] = None
    notes: Optional[str] = None          # Warning note when empty / failing
    # Defaults to the platform value, which is what a single-probe platform's surface is called.
    connector_surface: Optional[str] = None


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
    # The observations this opportunity actually stands on. Empty is a real answer and means
    # the opportunity rests on a measured absence of supply rather than on a sighting.
    citations: List[CitationEvidence] = field(default_factory=list)


@dataclass
class HarnessResearchReport:
    """Synthesized strategic dossier produced by the Autonomous Agent Harness.

    `surface` says which question the mission was answering, and it decides what the report is
    allowed to contain: an `ATTENTION` report carries ranked topics and their evidence but no
    market opportunities and no Opportunity Index, because attention is not demand.
    """
    mission_id: str
    title: str
    scorecard: QualityScorecard
    maturity_stage: TrendMaturityStage
    channel_summaries: List[ChannelDataSummary] = field(default_factory=list)
    verified_cross_platform_trends: List[Dict[str, Any]] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    strategic_insights: List[StrategicInsight] = field(default_factory=list)
    actionable_takeaways: List[StrategicInsight] = field(default_factory=list)
    # None for a mission created outside a research workspace, which declared no surface.
    surface: Optional[str] = None
    # The confirmed Brief revision that authorized a MARKET mission, as display payload.
    market_brief: Optional[Dict[str, Any]] = None
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

