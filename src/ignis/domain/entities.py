import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID, uuid4

from ignis.domain.value_objects import PlatformType, GeoCode, MomentumCategory


def generate_mission_shortcode(title: str, geo: GeoCode = GeoCode.VN, timeframe: str = "7d", uid: Optional[UUID] = None) -> str:
    """Generate human-friendly unique shortcode (e.g., VN-AI-AGENT-90D or M-8423AA3A)."""
    clean_words = re.findall(r"[a-zA-Z0-9]+", title.upper())
    slug = "-".join(clean_words[:2]) if clean_words else "TREND"
    tf_clean = re.sub(r"[^0-9A-Z]", "", timeframe.upper())
    geo_clean = geo.value if hasattr(geo, "value") else str(geo)
    
    hex_suffix = (str(uid)[:4]).upper() if uid else "01"
    return f"{geo_clean}-{slug}-{tf_clean}-{hex_suffix}"


@dataclass
class TrendSignal:
    """A discrete trend signal captured from a data source at a specific point in time."""
    platform: PlatformType
    raw_title: str
    metric_value: float = 0.0           # Views, Search index (0-100), Likes
    growth_velocity: float = 0.0        # Growth velocity (% / hour)
    source_url: Optional[str] = None
    geo_code: GeoCode = GeoCode.VN
    cluster_id: Optional[UUID] = None
    mission_id: Optional[UUID] = None
    # Set once the sighting has been stored, and on anything read back. A signal carrying one is
    # an observation that already exists; a signal without one has not been recorded yet. The
    # difference matters because re-submitting a stored observation through the writer records a
    # second collection event for a sighting that happened once.
    observation_id: Optional[UUID] = None
    # The external object this sighting is of. Display payload for a citation, never its
    # identity: two observations of one source are two pieces of evidence, and collapsing them
    # onto the source would count one sighting twice or lose the other.
    source_id: Optional[UUID] = None
    # How the source was resolved for this sighting, and which clock observed_at came from.
    # Both are written per observation, so both come back on one.
    identity_source: Optional[str] = None
    time_provenance: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    # When this harness pulled the signal. This is the clock every timeframe query runs on.
    #
    # Optional, and None means the collection time is not known -- which is the honest state of
    # 17,118 observations written before sql/015 by a connector that stamped a publish time. A
    # fresh sighting still defaults to now, because collecting one is what creates it.
    captured_at: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))
    # When the platform says the content itself was posted, where the platform reports it.
    # Kept apart from captured_at because they answer different questions: "what did we see
    # this week" is not "what was posted this week", and holding both in one column made a
    # 30-day window mean video publish dates for YouTube and scrape dates for Threads.
    published_at: Optional[datetime] = None


@dataclass
class TopicCluster:
    """A synthesized topic entity aggregating correlated cross-platform signals."""
    canonical_name: str
    id: UUID = field(default_factory=uuid4)
    # Short summary of what the cluster is about, for display. canonical_name stays the identity
    # key (cluster_id is a uuid5 of it) and is the most informative raw title in the group, which
    # reads as one member's post rather than a topic. Defaults to canonical_name so a row written
    # before this field existed still renders.
    _topic_label: Optional[str] = field(default=None, repr=False)
    summary_text: Optional[str] = None
    category: str = "unclassified"
    cross_platform_score: float = 0.0
    signals: List[TrendSignal] = field(default_factory=list)
    # The earliest exact ingestion time among the signals in the cluster. None where none of them
    # has one: a cluster built only from observations written before sql/015 has no recorded
    # first sighting, and inventing one would date the topic to whenever the query ran.
    first_seen_at: Optional[datetime] = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def topic_label(self) -> str:
        return self._topic_label or self.canonical_name

    @topic_label.setter
    def topic_label(self, value: Optional[str]) -> None:
        self._topic_label = value

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
    """A targeted strategic research mission with bound keywords, timeframe, and agent mapping."""

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
    # Which research owns this mission, and which question it is answering. Both are None for a
    # mission created outside a research workspace -- every mission written before the workspace
    # feature is in that state, and defaulting them to MARKET would claim they were
    # hypothesis-driven investigations and gate them on a Brief nobody was ever asked for.
    workspace_id: Optional[UUID] = None
    surface: Optional[str] = None          # 'ATTENTION' or 'MARKET'
    # Set only when a Market mission was opened from a selected Attention result. Context
    # lineage: it records where the question came from, never that the earlier evidence supports
    # the new hypothesis.
    parent_attention_mission_id: Optional[UUID] = None
    parent_cluster_id: Optional[UUID] = None
    # The confirmed Brief that authorizes a Market run. Null for ATTENTION by definition.
    brief_revision_id: Optional[UUID] = None
    # The Market mission whose confirmed Brief was changed to produce this one. The canonical
    # name for that relation, recorded on the newer mission: the revised mission is immutable
    # once its Brief is confirmed, so the pointer belongs to the side that came second.
    revises_mission_id: Optional[UUID] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if not self.shortcode:
            self.shortcode = generate_mission_shortcode(self.title, self.geo_code, self.timeframe, self.id)
