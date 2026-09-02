from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Any
from enum import Enum


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
    verified_cross_platform_trends: List[Dict[str, Any]] = field(default_factory=list)
    market_opportunities: List[MarketOpportunity] = field(default_factory=list)
    strategic_insights: List[str] = field(default_factory=list)
    actionable_takeaways: List[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

