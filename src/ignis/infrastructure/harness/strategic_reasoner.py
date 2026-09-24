import logging
import math
import re
import unicodedata
from typing import List, Dict, Any, Tuple, Optional, Set

from collections import defaultdict

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
from ignis.domain.research_workspace import (
    EvidenceRole,
    MissionLineage,
    ResearchSurface,
    opportunity_index_is_allowed,
    resolve_surface,
)
from ignis.domain.value_objects import PlatformType, GeoCode

logger = logging.getLogger(__name__)

# Longest token still treated as an acronym that identifies a topic by itself (ai, seo, crm...)
ACRONYM_MAX_LEN = 3


def strip_context_citations(items: List[Any]) -> List[Any]:
    """Remove every Attention-context citation from things a conclusion rests on.

    Context observations never enter the analysis inputs, so in the normal path this removes
    nothing. It is applied anyway because "an Attention sighting cannot support a Market
    hypothesis" has to hold for a report assembled by any caller, not only for the one path
    that happens to keep the two lists apart today.
    """
    for item in items:
        citations = getattr(item, "citations", None)
        if not citations:
            continue
        item.citations = [
            c
            for c in citations
            if getattr(c, "evidence_role", None) != EvidenceRole.ATTENTION_CONTEXT.value
        ]
    return items


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
        self._synonym_index: Dict[str, Set[str]] = {}
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
        market_brief: Optional[Dict[str, Any]] = None,
        attention_context_signals: Optional[List[TrendSignal]] = None,
    ) -> HarnessResearchReport:
        maturity_stage, maturity_reasons = self._assess_maturity(signals, clusters, geo=mission.geo_code)
        verified_trends = self._extract_verified_trends(signals, clusters, geo=mission.geo_code)

        # One registry per dossier: the same observation keeps one CIT-xx identifier
        # wherever it is cited, so a reader never mistakes one sighting for two.
        citation_registry: Dict[str, CitationEvidence] = {}

        # ATTENTION measures what is being looked at. Running the demand-versus-supply
        # comparison for it and then hiding the number downstream would leave the reasoning
        # available to any caller that read the object directly, so it is not computed at all.
        surface = resolve_surface(mission.surface)
        opportunities = (
            self._discover_market_opportunities(
                signals,
                mission.keywords,
                geo=mission.geo_code,
                citation_registry=citation_registry,
            )
            if opportunity_index_is_allowed(surface)
            else []
        )

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

        # Everything minted so far was collected for this mission's own question, so it is
        # stamped before any carried observation reaches the registry.
        own_role = self._own_evidence_role(surface)
        for citation in citation_registry.values():
            citation.evidence_role = own_role
        attention_context = self._carry_attention_context(
            attention_context_signals, citation_registry, geo=mission.geo_code
        )
        if surface is ResearchSurface.MARKET:
            strip_context_citations(list(opportunities) + list(insights) + list(actionables))

        lineage = MissionLineage.of_mission(mission)

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
            surface=surface.value if surface else None,
            market_brief=market_brief if surface is ResearchSurface.MARKET else None,
            lineage=None if lineage.is_empty else lineage.to_payload(),
            attention_context=attention_context,
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
            observation_id=str(signal.observation_id) if signal.observation_id else None,
            source_id=str(signal.source_id) if signal.source_id else None,
            connector_surface=self._connector_surface_of(signal),
        )

    @staticmethod
    def _connector_surface_of(signal: TrendSignal) -> str:
        """Which probe returned this signal, falling back to the platform name.

        An observation written before the surface was recorded carries none. The platform value
        is what a single-probe platform's surface is called anyway, so the fallback names the
        primary probe rather than inventing a surface the signal cannot be attributed to.
        """
        recorded = (signal.metadata or {}).get("connector_surface")
        if isinstance(recorded, str) and recorded.strip():
            return recorded.strip()
        platform = signal.platform
        return platform.value if hasattr(platform, "value") else str(platform)

    def _citation_key(self, signal: TrendSignal) -> str:
        """The identity one citation is registered under.

        `observation_id` when the sighting has been stored, because that is the canonical
        evidence identity and is the only key that keeps two observations of one source apart.
        The platform-and-URL key is kept only for a signal that has not been written yet -- it
        merges two sightings of one URL, which is exactly why it cannot be the identity of
        anything a conclusion rests on.
        """
        if signal.observation_id:
            return f"observation:{signal.observation_id}"
        return f"unstored:{self._platform_value(signal.platform)}|{signal.source_url or signal.raw_title}"

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
    def _own_evidence_role(surface: Optional[ResearchSurface]) -> Optional[str]:
        """What this mission's own observations are, given the question it answers.

        A mission with no recorded surface gets no role at all: labelling a pre-workspace
        mission's evidence would claim it was collected against a Brief nobody confirmed.
        """
        if surface is ResearchSurface.MARKET:
            return EvidenceRole.MARKET_EVIDENCE.value
        if surface is ResearchSurface.ATTENTION:
            return EvidenceRole.ATTENTION_CONTEXT.value
        return None

    def _carry_attention_context(
        self,
        signals: Optional[List[TrendSignal]],
        registry: Dict[str, CitationEvidence],
        geo: GeoCode = GeoCode.VN,
    ) -> List[CitationEvidence]:
        """Cite the observations the parent Attention mission held, as context.

        Minted after the analysis, so nothing a conclusion was drawn from can be one of these.
        An observation that this mission also collected keeps the role it already earned: it is
        this mission's own evidence, and the fact that the Attention run saw it too does not
        demote it.
        """
        carried: List[CitationEvidence] = []
        for signal in signals or []:
            already_known = self._citation_key(signal) in registry
            citation = self._mint_citation(signal, registry, geo=geo)
            if not already_known:
                citation.evidence_role = EvidenceRole.ATTENTION_CONTEXT.value
                carried.append(citation)
        return carried

    @staticmethod
    def _engagement_rank(signal: TrendSignal) -> tuple:
        return (float(signal.metric_value or 0.0), float(signal.growth_velocity or 0.0))

    def _resolve_circuit_state(
        self,
        connector_surface: str,
        platform_value: str,
        connector_health: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Return the health entry for one connector surface.

        Looked up by plugin id first. Collapsing every plugin of a platform into one entry is
        what let a healthy TikTok video grid report on behalf of a failed Creative Center probe;
        the platform-wide fallback is kept only for a surface that has no registered plugin of
        its own, which is itself reported as DEGRADED below.
        """
        if not connector_health:
            return None
        entry = connector_health.get(connector_surface)
        if isinstance(entry, dict):
            return entry
        entries = [
            e for e in connector_health.values()
            if isinstance(e, dict) and self._platform_value(e.get("platform")) == platform_value
        ]
        if not entries:
            return None
        open_entries = [e for e in entries if e.get("circuit_state") == "OPEN"]
        return open_entries[0] if open_entries else entries[0]

    def _registered_surfaces_of(
        self, platform_value: str, connector_health: Optional[Dict[str, Any]]
    ) -> List[str]:
        """The plugin ids serving one platform, as the registry reports them."""
        return sorted(
            str(plugin_id)
            for plugin_id, entry in (connector_health or {}).items()
            if isinstance(entry, dict)
            and self._platform_value(entry.get("platform")) == platform_value
        )

    def _surfaces_of(
        self,
        platform_value: str,
        registered: List[str],
        seen_in_signals: Optional[List[str]] = None,
    ) -> List[str]:
        """Every connector surface that serves one platform, registered or observed.

        The union of the two matters: a plugin that is registered but returned nothing has to be
        reported -- that silent failure is what the audit exists for -- and a surface that
        appears only in the evidence has to be reported too rather than being dropped because
        the registry was unavailable at read time.
        """
        return sorted(set(registered) | set(seen_in_signals or [])) or [platform_value]

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

        # Grouped by connector surface, not by platform. One row per probe is the whole point:
        # a platform aggregate lets a healthy surface answer on behalf of a failed one, and a
        # failed probe reported as an empty platform reads downstream as an absent market.
        by_surface: Dict[str, List[TrendSignal]] = defaultdict(list)
        surfaces_seen: Dict[str, List[str]] = defaultdict(list)
        for s in signals:
            p_val = self._platform_value(s.platform)
            surface = self._connector_surface_of(s)
            by_surface[surface].append(s)
            if surface not in surfaces_seen[p_val]:
                surfaces_seen[p_val].append(surface)

        summaries: List[ChannelDataSummary] = []
        registry = citation_registry if citation_registry is not None else {}

        for platform in mission.platforms:
            p_val = self._platform_value(platform)
            registered = self._registered_surfaces_of(p_val, connector_health)

            # A signal whose surface was never recorded carries the platform name instead. When
            # exactly one probe serves that platform, the attribution is unambiguous and the
            # signals belong to it; reporting them as a second surface named after the platform
            # would invent a probe that does not exist. When several probes serve it, the
            # attribution genuinely is not known, so those signals keep their own row and say so.
            unattributed = by_surface.get(p_val)
            if unattributed and len(registered) == 1 and p_val not in registered:
                by_surface[registered[0]] = by_surface.get(registered[0], []) + unattributed
                by_surface.pop(p_val, None)
                surfaces_seen[p_val] = [s for s in surfaces_seen.get(p_val, []) if s != p_val]

            for surface in self._surfaces_of(p_val, registered, surfaces_seen.get(p_val)):
                channel_signals = by_surface.get(surface, [])
                ambiguous = surface == p_val and len(registered) > 1

                if channel_signals:
                    top_signal = max(channel_signals, key=self._engagement_rank)
                    summaries.append(
                        ChannelDataSummary(
                            platform=platform,
                            connector_surface=surface,
                            status=ChannelHealthStatus.HEALTHY,
                            signals_count=len(channel_signals),
                            timeframe_used=timeframe_used,
                            top_citation=self._mint_citation(
                                top_signal, registry, geo=mission.geo_code
                            ),
                            notes=(
                                "Recorded before the connector surface was tracked, and this "
                                "platform is served by more than one probe, so these signals "
                                "cannot be attributed to a single surface."
                                if ambiguous else None
                            ),
                        )
                    )
                    continue

                health_entry = self._resolve_circuit_state(surface, p_val, connector_health)
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
                        connector_surface=surface,
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
                "canonical_name": c.topic_label,
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

    def register_synonym_groups(self, groups: List[List[str]]) -> None:
        """Register related-term groups (one group = terms sharing a lexicon domain + category).

        Every term in a group becomes an expansion of the others, so mission keyword matching
        follows the persisted vocabulary instead of a dictionary baked into the code.
        """
        for group in groups:
            terms = {t.strip().lower() for t in group if t and t.strip()}
            if len(terms) < 2:
                continue
            for term in terms:
                self._synonym_index.setdefault(term, set()).update(terms - {term})

    def register_foreign_stopwords(self, terms: List[str]) -> None:
        """Dynamically register new foreign stop words into filter."""
        for t in terms:
            clean = t.strip().lower()
            if clean:
                self._custom_stopwords.add(clean)

    def _is_vietnamese(self, title: str) -> bool:
        return self._is_localized(title, geo=GeoCode.VN)

    def _matches_topic_strictly(self, title: str, kw: str) -> bool:
        if self._is_garbage(title):
            return False

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

        # Expansions registered from the market_lexicons table (no vocabulary is hardcoded here)
        for syn in self._synonym_index.get(k, set()):
            if len(syn) <= 4 or " " not in syn:
                if re.search(rf"\b{re.escape(syn)}\b", t):
                    return True
            elif syn in t:
                return True

        # Token set match; keeps 2-letter tokens such as 'ai' that a >2 filter used to drop
        kw_tokens = [w for w in k.split() if len(w) >= 2]
        if kw_tokens:
            # An acronym-shaped token (<= 3 ASCII alphanumerics) carries the topic on its own
            acronyms = [w for w in kw_tokens if len(w) <= ACRONYM_MAX_LEN and w.isascii() and w.isalnum()]
            if any(re.search(rf"\b{re.escape(a)}\b", t) for a in acronyms):
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
        citation_registry: Optional[Dict[str, CitationEvidence]] = None,
    ) -> List[MarketOpportunity]:
        opportunities: List[MarketOpportunity] = []
        registry = citation_registry if citation_registry is not None else {}
        if not target_keywords:
            return opportunities

        # Extract search demand values per keyword
        demand_signals = [s for s in signals if s.platform == PlatformType.GOOGLE_TRENDS]
        logger.info(
            f"Evaluating {len(target_keywords)} mission keywords against {len(signals)} candidate signals "
            f"({len(demand_signals)} of them search-demand signals)."
        )

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

            # Both sides of the comparison, so the reader can reach the observation behind the
            # index rather than a title that may belong to two different sightings. An empty
            # list stays empty: an opportunity resting on a measured absence of supply has
            # nothing on the supply side to cite, and inventing one would be the fabrication
            # the citation contract exists to prevent.
            demand_evidence = [
                s for s in demand_signals
                if self._matches_topic_strictly(
                    s.metadata.get("keyword", "") or s.raw_title, kw_clean
                )
            ]
            citations = [
                self._mint_citation(s, registry, geo=geo)
                for s in (demand_evidence[:2] + localized_videos[:3])
            ]

            opportunities.append(
                MarketOpportunity(
                    topic=raw_kw,
                    opportunity_type=opp_type,
                    search_interest_score=round(demand_score, 1),
                    content_supply_score=supply_score,
                    opportunity_index=opportunity_index,
                    strategic_recommendation=rec,
                    supporting_signals=support_sigs,
                    citations=citations,
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
    ) -> Tuple[List[StrategicInsight], List[StrategicInsight]]:
        statements: List[Tuple[str, List[TrendSignal]]] = []
        # Each takeaway travels with the signals it was derived from, for the same reason an
        # insight does: an action a reader cannot trace back to an observation is advice, and
        # the report has no way to say which of the two it is handing over.
        actions: List[Tuple[str, List[TrendSignal]]] = []

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
            actions.append((gap_action, gap_evidence))

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
                actions.append((dom_action, topic_signals[dominant_kw]))

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
                actions.append((broken_action, []))

        actions.append((
            "Schedule periodic ingress surveillance to track supply shifts and search demand growth velocity.",
            [],
        ))

        insights = self.attribute_citations(statements, citation_registry=citation_registry, geo=mission.geo_code)
        actionables = self.attribute_citations(actions, citation_registry=citation_registry, geo=mission.geo_code)
        return insights, actionables

    @staticmethod
    def _comment_count(signal: TrendSignal) -> int:
        try:
            return int(signal.metadata.get("comments") or 0)
        except (TypeError, ValueError):
            return 0
