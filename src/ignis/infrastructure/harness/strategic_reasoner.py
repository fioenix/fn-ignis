import logging
import re
import math
from typing import List, Dict, Any, Tuple, Optional, Set

from collections import defaultdict

logger = logging.getLogger(__name__)

from ignis.config import settings
from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.harness_models import (
    ChannelDataSummary,
    ChannelHealthStatus,
    CitationEvidence,
    MarketOpportunity,
    StrategicInsight,
    TrendMaturityStage,
    HarnessResearchReport,
    QualityScorecard,
)
from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
from ignis.domain.value_objects import PlatformType, GeoCode


class StrategicMarketReasoner:
    """
    Strategic Reasoning Engine for Market Opportunity & White Space Discovery.
    Parameters and thresholds are configurable via environment variables.
    """

    FOREIGN_SCRIPTS_PATTERN = re.compile(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff]")

    # Channels that cannot ingest anything without a bound token or browser session.
    AUTH_SENSITIVE_PLATFORMS = {"tiktok", "threads", "reels"}
    VIDEO_PLATFORMS = ("youtube", "tiktok", "reels")
    RATE_LIMIT_HINTS = ("429", "quota", "rate limit", "ratelimit", "too many requests")

    def __init__(
        self,
        custom_lexicon: Optional[Set[str]] = None,
        custom_stopwords: Optional[Set[str]] = None,
        custom_noise: Optional[Set[str]] = None,
        detector: Optional[ILanguageDetector] = None,
    ):
        self._custom_lexicon: Set[str] = set(custom_lexicon or [])
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])
        self._custom_noise: Set[str] = set(custom_noise or [])
        self._detector: ILanguageDetector = detector or HeuristicLanguageDetector()

    def register_noise_blacklist(self, terms: List[str]) -> None:
        """Dynamically register mission-specific noise terms."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_noise.add(clean)

    def _is_garbage(self, title: str) -> bool:
        if not title:
            return True
        if self.FOREIGN_SCRIPTS_PATTERN.search(title):
            return True
        if self._custom_noise:
            t_low = title.lower()
            for term in self._custom_noise:
                if not term:
                    continue
                clean_term = term.lstrip("#").strip()
                if not clean_term:
                    continue
                pattern = rf"(?:\b|#){re.escape(clean_term)}\b"
                if re.search(pattern, t_low):
                    return True
        return False



    def analyze_mission(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
        scorecard: QualityScorecard,
        auth_status: Optional[Dict[str, bool]] = None,
        connector_health: Optional[Dict[str, Any]] = None,
    ) -> HarnessResearchReport:
        maturity_stage, maturity_reasons = self._assess_maturity(signals, clusters, geo=mission.geo_code)
        opportunities = self._discover_market_opportunities(signals, mission.keywords, geo=mission.geo_code)
        verified_trends = self._extract_verified_trends(signals, clusters, geo=mission.geo_code)

        # One registry per dossier: the same source keeps one CIT-xx identifier
        # wherever it is cited, so a reader never mistakes one video for two.
        citation_registry: Dict[str, CitationEvidence] = {}

        channel_summaries = self.summarize_channel_ingress(
            mission=mission,
            signals=signals,
            auth_status=auth_status,
            connector_health=connector_health,
            citation_registry=citation_registry,
        )

        insights, actionables = self._synthesize_insights(
            mission,
            signals,
            opportunities,
            maturity_stage,
            maturity_reasons,
            channel_summaries=channel_summaries,
            citation_registry=citation_registry,
        )

        return HarnessResearchReport(
            mission_id=str(mission.id),
            title=mission.title,
            scorecard=scorecard,
            maturity_stage=maturity_stage,
            channel_summaries=channel_summaries,
            verified_cross_platform_trends=verified_trends,
            market_opportunities=opportunities,
            strategic_insights=insights,
            actionable_takeaways=actionables,
        )

    # ------------------------------------------------------------------
    # Data Provenance: channel ingress audit & citation attribution
    # ------------------------------------------------------------------

    @staticmethod
    def _platform_value(platform: Any) -> str:
        return platform.value if hasattr(platform, "value") else str(platform)

    @staticmethod
    def _compact_number(value: float) -> str:
        num = float(value)
        if num >= 1_000_000:
            return f"{num / 1_000_000:.1f}M"
        if num >= 1_000:
            return f"{num / 1_000:.1f}K"
        return f"{int(num):,}"

    def _format_metric_highlight(self, signal: TrendSignal, geo: GeoCode = GeoCode.VN) -> str:
        """Render the headline metric a reader can verify against the source."""
        platform = self._platform_value(signal.platform)
        parts: List[str] = []

        if platform == "google":
            parts.append(f"search index {float(signal.metric_value):.0f}/100")
        elif platform in self.VIDEO_PLATFORMS:
            parts.append(f"{self._compact_number(signal.metric_value)} views")
        else:
            parts.append(f"{self._compact_number(signal.metric_value)} engagements")

        if signal.growth_velocity:
            parts.append(f"{float(signal.growth_velocity):+.0f}%/hr")

        comments = signal.metadata.get("comments")
        if comments:
            try:
                parts.append(f"{int(comments)} comments")
            except (TypeError, ValueError):
                pass

        return " · ".join(parts)

    def _build_citation(self, signal: TrendSignal, sequence: int, geo: GeoCode = GeoCode.VN) -> CitationEvidence:
        author = (
            signal.metadata.get("channel_title")
            or signal.metadata.get("author")
            or signal.metadata.get("username")
        )
        excerpt = signal.metadata.get("top_comment") or signal.metadata.get("excerpt")
        return CitationEvidence(
            citation_id=f"CIT-{sequence:02d}",
            platform=signal.platform,
            title_or_query=signal.metadata.get("keyword") or signal.raw_title,
            metric_highlight=self._format_metric_highlight(signal, geo=geo),
            author_or_channel=author,
            url=signal.source_url,
            excerpt=excerpt,
        )

    def _citation_key(self, signal: TrendSignal) -> str:
        return f"{self._platform_value(signal.platform)}|{signal.source_url or signal.raw_title}"

    def _mint_citation(
        self,
        signal: TrendSignal,
        registry: Dict[str, CitationEvidence],
        geo: GeoCode = GeoCode.VN,
    ) -> CitationEvidence:
        """Return the citation for a source, reusing its identifier if already cited."""
        key = self._citation_key(signal)
        existing = registry.get(key)
        if existing:
            return existing
        citation = self._build_citation(signal, len(registry) + 1, geo=geo)
        registry[key] = citation
        return citation

    @staticmethod
    def _engagement_rank(signal: TrendSignal) -> tuple:
        return (float(signal.metric_value or 0.0), float(signal.growth_velocity or 0.0))

    def _resolve_circuit_state(
        self,
        platform_value: str,
        connector_health: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return the worst-off plugin health entry serving a platform, if any."""
        if not connector_health:
            return None
        entries = [
            e for e in connector_health.values()
            if isinstance(e, dict) and self._platform_value(e.get("platform")) == platform_value
        ]
        if not entries:
            return None
        open_entries = [e for e in entries if e.get("circuit_state") == "OPEN"]
        return open_entries[0] if open_entries else entries[0]

    def _looks_rate_limited(self, health_entry: Dict[str, Any]) -> bool:
        blob = " ".join(
            str(health_entry.get(k, ""))
            for k in ("last_error_type", "last_error", "last_failure_reason", "notes")
        ).lower()
        return any(hint in blob for hint in self.RATE_LIMIT_HINTS)

    def summarize_channel_ingress(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        auth_status: Optional[Dict[str, bool]] = None,
        connector_health: Optional[Dict[str, Any]] = None,
        citation_registry: Optional[Dict[str, CitationEvidence]] = None,
    ) -> List[ChannelDataSummary]:
        """
        Audit every targeted channel so a silent ingress failure can never be
        mistaken for genuine absence of market demand.

        `auth_status` maps a platform value to whether credentials are bound;
        `connector_health` is the registry health map (plugin_id -> status dict).
        Both are optional: when omitted the audit degrades to signal counting.
        """
        geo_value = self._platform_value(mission.geo_code).upper()
        timeframe_used = f"{mission.timeframe} ({geo_value})"

        by_platform: Dict[str, List[TrendSignal]] = defaultdict(list)
        for s in signals:
            by_platform[self._platform_value(s.platform)].append(s)

        summaries: List[ChannelDataSummary] = []
        registry = citation_registry if citation_registry is not None else {}

        for platform in mission.platforms:
            p_val = self._platform_value(platform)
            channel_signals = by_platform.get(p_val, [])

            if channel_signals:
                top_signal = max(channel_signals, key=self._engagement_rank)
                summaries.append(
                    ChannelDataSummary(
                        platform=platform,
                        status=ChannelHealthStatus.HEALTHY,
                        signals_count=len(channel_signals),
                        timeframe_used=timeframe_used,
                        top_citation=self._mint_citation(top_signal, registry, geo=mission.geo_code),
                        notes=None,
                    )
                )
                continue

            health_entry = self._resolve_circuit_state(p_val, connector_health)
            needs_auth = (
                auth_status is not None
                and p_val in self.AUTH_SENSITIVE_PLATFORMS
                and auth_status.get(p_val) is False
            )

            if needs_auth:
                status = ChannelHealthStatus.AUTH_REQUIRED
                notes = "Missing token or browser session for this channel."
            elif health_entry and health_entry.get("circuit_state") == "OPEN":
                if self._looks_rate_limited(health_entry):
                    status = ChannelHealthStatus.RATE_LIMITED
                    notes = "Rate limit reached (429/quota); Circuit Breaker is OPEN."
                else:
                    status = ChannelHealthStatus.DEGRADED
                    fails = health_entry.get('consecutive_failures', 0)
                    notes = f"Circuit Breaker is OPEN after {fails} consecutive failures."
            elif connector_health is not None and health_entry is None:
                status = ChannelHealthStatus.DEGRADED
                notes = "No connector plugin registered for this channel."
            else:
                status = ChannelHealthStatus.EMPTY_NO_DATA
                notes = "No signals matched keywords in timeframe."

            summaries.append(
                ChannelDataSummary(
                    platform=platform,
                    status=status,
                    signals_count=0,
                    timeframe_used=timeframe_used,
                    top_citation=None,
                    notes=notes,
                )
            )

        return summaries

    def attribute_citations(
        self,
        statements: List[Tuple[str, List[TrendSignal]]],
        citation_registry: Optional[Dict[str, CitationEvidence]] = None,
        max_citations_per_statement: int = 3,
        geo: GeoCode = GeoCode.VN,
    ) -> List[StrategicInsight]:
        """
        Bind each statement to the concrete signals it was derived from.

        A statement with no supporting signal is still emitted, but with an empty
        citation list so downstream renderers can flag it as unverified rather
        than presenting speculation as evidence.
        """
        insights: List[StrategicInsight] = []
        registry = citation_registry if citation_registry is not None else {}

        for statement, supporting in statements:
            if not statement or not statement.strip():
                continue
            citations: List[CitationEvidence] = []
            seen: set = set()
            ranked = sorted(supporting or [], key=self._engagement_rank, reverse=True)
            for sig in ranked:
                if len(citations) >= max_citations_per_statement:
                    break
                key = self._citation_key(sig)
                if key in seen:
                    continue
                seen.add(key)
                citations.append(self._mint_citation(sig, registry, geo=geo))
            insights.append(StrategicInsight(statement=statement.strip(), citations=citations))

        return insights

    def _assess_maturity(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
        geo: GeoCode = GeoCode.VN,
    ) -> Tuple[TrendMaturityStage, List[str]]:
        reasons = []
        video_signals = [
            s for s in signals 
            if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")
        ]
        
        if not video_signals:
            reasons.append("Zero localized tutorial videos or content assets recorded.")
            return TrendMaturityStage.EMERGING, reasons

        avg_views = sum(float(s.metric_value) for s in video_signals) / float(len(video_signals))
        total_clusters = len(clusters)

        if avg_views > 20000 and total_clusters >= 3:
            reasons.append(f"High average reach ({avg_views:,.0f} views/video) across {total_clusters} topic clusters.")
            return TrendMaturityStage.HYPING, reasons
        elif avg_views > 5000:
            reasons.append(f"Moderate practitioner engagement ({avg_views:,.0f} views/video).")
            return TrendMaturityStage.EMERGING, reasons
        else:
            reasons.append("Established ecosystem with steady viewer baseline.")
            return TrendMaturityStage.MATURE, reasons

    def _extract_verified_trends(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
        geo: GeoCode = GeoCode.VN,
    ) -> List[Dict[str, Any]]:
        verified = []
        for c in clusters[:6]:
            p_counts: Dict[str, int] = defaultdict(int)
            total_views = 0.0
            for s in c.signals:
                if self._is_localized(s.raw_title, geo=geo):
                    p_counts[s.platform.value if hasattr(s.platform, "value") else str(s.platform)] += 1
                    total_views += float(s.metric_value)


            default_summary = f"Topic cluster synthesized from {len(c.signals)} signals."
            verified.append({
                "canonical_name": c.canonical_name,
                "momentum": c.momentum_category.value if hasattr(c.momentum_category, "value") else str(c.momentum_category),
                "cross_platform_score": c.cross_platform_score,
                "platform_diversity": len(p_counts),
                "total_estimated_reach": int(total_views),
                "summary": c.summary_text or default_summary,
            })
        return verified


    def register_terms(self, terms: List[str]) -> None:
        """Dynamically register new domain vocabulary terms in memory."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_lexicon.add(clean)

    def register_foreign_stopwords(self, terms: List[str]) -> None:
        """Dynamically register new foreign stop words into filter."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_stopwords.add(clean)

    def _is_vietnamese(self, title: str) -> bool:
        return self._is_localized(title, geo=GeoCode.VN)

    KEYWORD_SYNONYMS: Dict[str, Set[str]] = {
        "ai agent": {"ai", "trí tuệ nhân tạo", "agent", "trợ lý ảo", "chatbot", "bot", "tự động hóa", "tự động"},
        "ai": {"ai", "trí tuệ nhân tạo", "artificial intelligence", "agent", "bot"},
        "chatbot": {"chat bot", "chatbot", "trợ lý ảo", "bot", "ai"},
        "automation": {"tự động hóa", "tự động", "automation", "quy trình", "auto"},
        "ecommerce": {"thương mại điện tử", "e-commerce", "bán hàng online", "shop", "tiktok shop"},
        "tiktok shop": {"tiktokshop", "tiktok shop", "bán hàng tiktok", "shop"},
    }

    def _matches_topic_strictly(self, title: str, kw: str) -> bool:
        if self._is_garbage(title):
            return False

        import unicodedata
        t = unicodedata.normalize("NFC", title).lower()
        k = unicodedata.normalize("NFC", kw).lower().strip()

        # Word boundary regex for short acronyms/words (<=4 chars or single word)
        if len(k) <= 4 or " " not in k:
            pattern = rf"\b{re.escape(k)}\b"
            if re.search(pattern, t):
                return True

        # Substring match for multi-word phrases
        if k in t:
            return True

        # Check domain synonyms / expansions
        synonyms = self.KEYWORD_SYNONYMS.get(k, set())
        for syn in synonyms:
            if len(syn) <= 4 or " " not in syn:
                if re.search(rf"\b{re.escape(syn)}\b", t):
                    return True
            elif syn in t:
                return True

        # Token set match preserving 2-letter tokens like 'ai'
        kw_tokens = [w for w in k.split() if len(w) >= 2]
        if kw_tokens:
            distinctive_tokens = [w for w in kw_tokens if w in ("ai", "bot", "app", "seo", "ads", "crm", "erp")]
            if any(re.search(rf"\b{re.escape(dt)}\b", t) for dt in distinctive_tokens):
                return True
            if len(kw_tokens) >= 2 and all(w in t for w in kw_tokens):
                return True

        return False

    def _is_localized(self, title: str, geo: GeoCode = GeoCode.VN) -> bool:
        if not title:
            return False
        return self._detector.is_localized(
            text=title,
            geo=geo,
            extra_terms=self._custom_lexicon,
            extra_stopwords=self._custom_stopwords,
            extra_noise=self._custom_noise,
        )

    def _discover_market_opportunities(
        self,
        signals: List[TrendSignal],
        target_keywords: List[str],
        geo: GeoCode = GeoCode.VN,
    ) -> List[MarketOpportunity]:
        opportunities: List[MarketOpportunity] = []
        if not target_keywords:
            return opportunities

        # Extract search demand values per keyword
        demand_signals = [s for s in signals if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) == "google"]
        video_signals = [s for s in signals if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")]
        logger.info(f"Evaluating {len(target_keywords)} mission keywords against {len(signals)} candidate signals (demand: {len(demand_signals)}, video: {len(video_signals)}).")

        demand_map: Dict[str, float] = {}
        for s in demand_signals:
            kw_meta = s.metadata.get("keyword", "")
            if kw_meta:
                demand_map[kw_meta.lower().strip()] = float(s.metric_value)
            for raw_kw in target_keywords:
                kw_clean = raw_kw.lower().strip()
                if self._matches_topic_strictly(s.raw_title, kw_clean):
                    demand_map[kw_clean] = max(demand_map.get(kw_clean, 0.0), float(s.metric_value))

        for raw_kw in target_keywords:
            kw_clean = raw_kw.lower().strip()
            has_demand_signal = kw_clean in demand_map
            demand_score = demand_map.get(kw_clean, 0.0)

            # Strict topic matching across all video content platforms
            matching_videos = [
                s for s in signals
                if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")
                and self._matches_topic_strictly(s.raw_title, kw_clean)
            ]

            # Empirical market localization filter
            localized_videos = [s for s in matching_videos if self._is_localized(s.raw_title, geo=geo)]
            loc_count = len(localized_videos)
            loc_views = sum(float(s.metric_value) for s in localized_videos)

            # View-Weighted Supply Scoring Equation across all video platforms
            if loc_count == 0:
                supply_score = 0.0
            elif loc_views < 1000.0:
                base_supply = min(40.0, loc_count * 4.0)
                view_factor = min(15.0, math.log10(max(10.0, loc_views)) * 3.0) if loc_views > 0 else 0.0
                supply_score = round(base_supply + view_factor, 1)
            else:
                base_supply = min(settings.SUPPLY_BASE_MAX, loc_count * settings.SUPPLY_VIDEO_WEIGHT)
                view_factor = min(settings.SUPPLY_VIEW_MAX, math.log10(max(10.0, loc_views)) * settings.SUPPLY_VIEW_LOG_WEIGHT)
                supply_score = round(min(100.0, base_supply + view_factor), 1)

            yt_count = sum(1 for s in localized_videos if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) == "youtube")
            tt_count = sum(1 for s in localized_videos if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) == "tiktok")
            breakdown_parts = []
            if yt_count > 0:
                breakdown_parts.append(f"{yt_count} YouTube")
            if tt_count > 0:
                breakdown_parts.append(f"{tt_count} TikTok")
            plat_str = f" ({', '.join(breakdown_parts)})" if breakdown_parts else ""
            v_str = f"{loc_count} video{plat_str}"

            # Strict Opportunity Index with Inverted Sample Size Damping & Label Alignment
            if not has_demand_signal:
                if loc_count == 0:
                    opportunity_index = 0.0
                    opp_type = "NO_DATA_RECORDED"
                    rec = f"No search interest signals on Google Trends and zero local video supply recorded for '{raw_kw}' ({v_str}). Insufficient data to verify market opportunity (Opportunity Index: {opportunity_index:+0.1f})."
                else:
                    opportunity_index = round(-supply_score * 0.5, 1)
                    opp_type = "SUPPLY_DRIVEN_UNASSESSED"
                    rec = f"Local supply detected ({v_str}), but no active Google search interest signals were recorded for '{raw_kw}'. Topic may be platform-specific or emerging via social feeds rather than active search (Opportunity Index: {opportunity_index:+0.1f})."
            elif loc_count == 0:
                opportunity_index = round(demand_score * 0.15, 1)
                opp_type = "UNVERIFIED_DEMAND_GAP"
                rec = f"Search demand for '{raw_kw}' reached {demand_score:.0f}/100 with zero local video supply recorded ({v_str}). Unverified demand gap requiring VoC interviews (Effective Opportunity Index: {opportunity_index:+0.1f})."
            else:
                raw_oi = demand_score - supply_score
                if raw_oi < 0:
                    opportunity_index = round(raw_oi, 1)
                    opp_type = "SATURATED_SEGMENT"
                    rec = f"Segment '{raw_kw}' is heavily saturated ({v_str}) relative to demand (Opportunity Index: {opportunity_index:+0.1f}). Vertical differentiation required."
                else:
                    damping_map = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90}
                    damping_factor = damping_map.get(loc_count, 1.0)
                    opportunity_index = round(raw_oi * damping_factor, 1)

                    if loc_count == 1:
                        opp_type = "PROBE_OPPORTUNITY"
                        rec = f"Initial single probe detected for '{raw_kw}' ({v_str}). Early signal with thin local supply (Effective Opportunity Index: {opportunity_index:+0.1f})."
                    elif opportunity_index >= settings.WHITE_SPACE_HIGH_DEMAND_INDEX_THRESHOLD:
                        opp_type = "HIGH_DEMAND_LOW_SUPPLY"
                        rec = f"Search demand for '{raw_kw}' reached {demand_score:.0f}/100, heavily outpacing supply ({v_str}). High-conviction verified opportunity (Effective Opportunity Index: {opportunity_index:+0.1f})."
                    elif opportunity_index >= 10.0:
                        opp_type = "GROWING_OPPORTUNITY"
                        rec = f"Segment '{raw_kw}' shows positive momentum ({v_str}) with viable market runway (Effective Opportunity Index: {opportunity_index:+0.1f})."
                    else:
                        opp_type = "BALANCED_COMPETITION"
                        rec = f"Segment '{raw_kw}' is in competitive equilibrium ({v_str}); content supply matches user demand."

            if localized_videos:
                support_sigs = [f"[{s.platform.value.upper() if hasattr(s.platform, 'value') else str(s.platform).upper()}] {s.raw_title}" for s in localized_videos[:3]]
            else:
                support_sigs = ["No localized videos recorded on YouTube or TikTok within selected timeframe."]

            opportunities.append(
                MarketOpportunity(
                    topic=raw_kw,
                    opportunity_type=opp_type,
                    search_interest_score=round(demand_score, 1),
                    content_supply_score=supply_score,
                    opportunity_index=opportunity_index,
                    strategic_recommendation=rec,
                    supporting_signals=support_sigs,
                )
            )

        opportunities.sort(key=lambda o: o.opportunity_index, reverse=True)
        return opportunities


    def _synthesize_insights(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        opportunities: List[MarketOpportunity],
        maturity_stage: TrendMaturityStage,
        maturity_reasons: List[str],
        channel_summaries: Optional[List[ChannelDataSummary]] = None,
        citation_registry: Optional[Dict[str, CitationEvidence]] = None,
    ) -> Tuple[List[StrategicInsight], List[str]]:
        statements: List[Tuple[str, List[TrendSignal]]] = []
        actionables: List[str] = []

        video_signals = [
            s for s in signals
            if self._platform_value(s.platform) in self.VIDEO_PLATFORMS
        ]
        demand_signals = [s for s in signals if s.platform == PlatformType.GOOGLE_TRENDS]

        maturity_stmt = f"Market maturity stage: {maturity_stage.value} — {'; '.join(maturity_reasons)}"
        statements.append((
            maturity_stmt,
            sorted(video_signals, key=self._engagement_rank, reverse=True)[:3],
        ))

        top_gaps = [o for o in opportunities if o.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "GROWING_OPPORTUNITY"]]
        if top_gaps:
            gap_names = ", ".join([f"'{o.topic}'" for o in top_gaps[:3]])
            gap_topics = [o.topic for o in top_gaps[:3]]
            # Demand vs supply claims must cite both sides of the comparison.
            gap_evidence = [
                s for s in demand_signals
                if any(self._matches_topic_strictly(s.metadata.get("keyword", "") or s.raw_title, t) for t in gap_topics)
            ] or demand_signals[:2]
            gap_evidence = gap_evidence + [
                s for s in video_signals
                if any(self._matches_topic_strictly(s.raw_title, t) for t in gap_topics)
            ]
            gap_stmt = f"Top strategic white spaces concentrated in: {gap_names}."
            gap_action = f"Allocate resources to high-demand topics {gap_names} to capture first-mover advantage."
            statements.append((gap_stmt, gap_evidence))
            actionables.append(gap_action)

        # Identify dominant discussion topic dynamically from signal volume
        topic_counts: Dict[str, int] = {}
        topic_signals: Dict[str, List[TrendSignal]] = defaultdict(list)
        for s in signals:
            for kw in mission.keywords:
                if self._matches_topic_strictly(s.raw_title, kw):
                    topic_counts[kw] = topic_counts.get(kw, 0) + 1
                    topic_signals[kw].append(s)

        if topic_counts:
            dominant_kw, max_count = max(topic_counts.items(), key=lambda item: item[1])
            if max_count >= 3:
                dom_stmt = f"Practitioner content is concentrated around '{dominant_kw}' ({max_count} verified signals)."
                dom_action = f"Differentiate positioning to avoid direct head-to-head competition with saturated supply in '{dominant_kw}'."
                statements.append((dom_stmt, topic_signals[dominant_kw]))
                actionables.append(dom_action)

        # Voice of Customer: pain point clusters must cite the discussion carrying them.
        discussed = [s for s in signals if self._comment_count(s) > 0]
        if discussed:
            total_comments = sum(self._comment_count(s) for s in discussed)
            top_discussed = sorted(discussed, key=self._comment_count, reverse=True)
            voc_stmt = (
                f"Voice of Customer concentrated in {len(discussed)} discussion threads with {total_comments} comments captured; "
                "carefully review these comments to uncover purchase objections and unmet demands."
            )
            statements.append((voc_stmt, top_discussed))

        # Honest observability: an incomplete channel mix is itself a finding.
        if channel_summaries:
            broken = [c for c in channel_summaries if c.status != ChannelHealthStatus.HEALTHY]
            if broken:
                broken_desc = ", ".join(
                    f"{self._platform_value(c.platform).upper()} ({c.status.value})" for c in broken
                )
                broken_stmt = (
                    f"Incomplete ingress coverage: {len(broken)}/{len(channel_summaries)} channels returned zero signals — {broken_desc}. "
                    "Treat cross-platform findings as preliminary until channels are restored."
                )
                broken_action = f"Restore empty ingress channels ({broken_desc}) and re-run mission prior to capital allocation."
                statements.append((broken_stmt, []))
                actionables.append(broken_action)

        actionables.append(
            "Schedule periodic ingress surveillance to track supply shifts and search demand growth velocity."
        )

        insights = self.attribute_citations(statements, citation_registry=citation_registry, geo=mission.geo_code)
        return insights, actionables

    @staticmethod
    def _comment_count(signal: TrendSignal) -> int:
        try:
            return int(signal.metadata.get("comments") or 0)
        except (TypeError, ValueError):
            return 0
