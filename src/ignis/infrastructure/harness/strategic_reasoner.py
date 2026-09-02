import re
import math
from typing import List, Dict, Any, Tuple, Optional, Set

from collections import defaultdict

from ignis.config import settings
from ignis.domain.entities import TrendSignal, TopicCluster, ResearchMission
from ignis.domain.harness_models import (
    MarketOpportunity,
    TrendMaturityStage,
    HarnessResearchReport,
    QualityScorecard,
)
from ignis.domain.value_objects import PlatformType, GeoCode



class StrategicMarketReasoner:
    """
    Strategic Reasoning Engine for Market Opportunity & White Space Discovery.
    Parameters and thresholds are configurable via environment variables.
    """

    VIETNAMESE_CHARS_PATTERN = re.compile(
        r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]",
        re.IGNORECASE
    )

    TECH_LOAN_WORDS = {
        "ai", "bot", "chat", "agent", "app", "tool", "pro", "plus", "hub", "lab",
        "tech", "online", "code", "dev", "web", "net", "top", "mini", "shop", "store"
    }

    VI_CORE_WORDS = {
        "va", "cua", "la", "trong", "cho", "voi", "ve", "tu", "dong", "hoa",
        "huong", "dan", "cach", "lam", "chu", "doanh", "nghiep", "ung", "dung",
        "giai", "phap", "phan", "mem", "tri", "tue", "nhan", "tao", "tro", "ly",
        "kiem", "tien", "nguoi", "viet", "nam", "danh", "bai", "hoc", "khoa",
        "thuc", "chien", "tong", "quan", "chi", "tiet", "zalo", "acc", "clone",
        "shop", "gia", "ban", "mua", "setup", "chot", "don", "kho", "hang",
        "sao", "gi", "tai", "bao", "nhieu", "cskh", "dai", "phi", "khong",
        "duoc", "nay", "moi", "tot", "nhat", "hay", "chia", "se", "kinh",
        "nghiem", "tai", "lieu", "phan", "tich", "xay", "dung", "tu", "van",
        "khach", "hang", "dich", "vu", "cong", "nghe", "nen", "tang"
    }

    # Characters strictly unique to Vietnamese
    VI_EXCLUSIVE_CHARS_PATTERN = re.compile(
        r"[ơớờởỡợưứừửữựđĐắằẳẵặấầẩẫậếềểễệốồổỗộớờởỡợứừửữựỳỹỷỵảẻỉỏủẽĩạẹịọụ]",
        re.IGNORECASE
    )


    FOREIGN_SCRIPTS_PATTERN = re.compile(r"[\uac00-\ud7af\u4e00-\u9fff\u3040-\u30ff\u0e00-\u0e7f\u0400-\u04ff]")

    FOREIGN_STOPWORDS = {
        "formation", "complete", "complète", "avec", "cours", "pour", "dans", "tuto", "debutant", "débutant",
        "como", "funcionam", "chegou", "novos", "veja", "agentes", "autonomos", "autônomos",
        "para", "com", "por", "sobre", "este", "esta", "todos", "agora", "fazer", "curso",
        "gratis", "completo", "você", "voce", "seus", "suas", "criar", "criando",
        "ferramenta", "passo", "inteligencia", "artificial", "automatizar",
        "cara", "yang", "untuk", "bisa"
    }


    def __init__(
        self,
        custom_lexicon: Optional[Set[str]] = None,
        custom_stopwords: Optional[Set[str]] = None,
        custom_noise: Optional[Set[str]] = None,
    ):
        self._custom_lexicon: Set[str] = set(custom_lexicon or [])
        self._custom_stopwords: Set[str] = set(custom_stopwords or [])
        self._custom_noise: Set[str] = set(custom_noise or [])

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
    ) -> HarnessResearchReport:
        maturity_stage, maturity_reasons = self._assess_maturity(signals, clusters)
        opportunities = self._discover_market_opportunities(signals, mission.keywords, geo=mission.geo_code)
        verified_trends = self._extract_verified_trends(signals, clusters, geo=mission.geo_code)

        insights, actionables = self._synthesize_insights(
            mission, signals, opportunities, maturity_stage, maturity_reasons
        )

        return HarnessResearchReport(
            mission_id=str(mission.id),
            title=mission.title,
            scorecard=scorecard,
            maturity_stage=maturity_stage,
            verified_cross_platform_trends=verified_trends,
            market_opportunities=opportunities,
            strategic_insights=insights,
            actionable_takeaways=actionables,
        )

    def _assess_maturity(
        self,
        signals: List[TrendSignal],
        clusters: List[TopicCluster],
    ) -> Tuple[TrendMaturityStage, List[str]]:
        reasons = []
        video_signals = [
            s for s in signals 
            if (s.platform.value if hasattr(s.platform, "value") else str(s.platform)) in ("youtube", "tiktok", "reels")
        ]
        
        if not video_signals:
            reasons.append("Zero localized video tutorials or production assets detected.")
            return TrendMaturityStage.EMERGING, reasons

        avg_views = sum(float(s.metric_value) for s in video_signals) / float(len(video_signals))
        total_clusters = len(clusters)

        if avg_views > 20000 and total_clusters >= 3:
            reasons.append(f"High average view velocity ({avg_views:,.0f} views/video) across {total_clusters} clusters.")
            return TrendMaturityStage.HYPING, reasons
        elif avg_views > 5000:
            reasons.append(f"Moderate practitioner engagement ({avg_views:,.0f} views/video).")
            return TrendMaturityStage.EMERGING, reasons
        else:
            reasons.append("Established ecosystem with stable viewership.")
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


            verified.append({
                "canonical_name": c.canonical_name,
                "momentum": c.momentum_category.value if hasattr(c.momentum_category, "value") else str(c.momentum_category),
                "cross_platform_score": c.cross_platform_score,
                "platform_diversity": len(p_counts),
                "total_estimated_reach": int(total_views),
                "summary": c.summary_text or f"Aggregated cluster with {len(c.signals)} signals.",
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
        if not title:
            return False

        if self.FOREIGN_SCRIPTS_PATTERN.search(title):
            return False

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
                    return False

        title_lower = title.lower()
        words = set(re.findall(r"\b[a-zA-ZàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđĐ]+\b", title_lower))
        
        # Layer 1: Reject foreign stopwords (Static + Dynamic DB)
        all_stopwords = self.FOREIGN_STOPWORDS | self._custom_stopwords
        if any(fw in words for fw in all_stopwords):
            return False

        # Layer 2: Exclusive Vietnamese characters with diacritics
        if self.VI_EXCLUSIVE_CHARS_PATTERN.search(title):
            return True

        # Layer 3: Unaccented text verification
        # Exclude international tech loan words from proof of Vietnamese localization
        pure_words = words - self.TECH_LOAN_WORDS
        active_core = self.VI_CORE_WORDS | self._custom_lexicon
        vi_core_count = sum(1 for w in pure_words if w in active_core)
        
        # Requires at least 2 genuine core Vietnamese words for unaccented titles
        return vi_core_count >= 2

    def _matches_topic_strictly(self, title: str, kw: str) -> bool:
        if self._is_garbage(title):
            return False

        t = title.lower()
        k = kw.lower().strip()

        # Word boundary regex for short acronyms/words (<=4 chars or single word)
        if len(k) <= 4 or " " not in k:
            pattern = rf"\b{re.escape(k)}\b"
            if re.search(pattern, t):
                return True
        
        # Substring match for multi-word phrases
        if k in t:
            return True

        # Token set match: all key content tokens exist in title
        kw_tokens = [w for w in k.split() if len(w) > 2]
        if len(kw_tokens) >= 2:
            return all(w in t for w in kw_tokens)

        return False

    def _is_localized(self, title: str, geo: GeoCode = GeoCode.VN) -> bool:
        if not title:
            return False
        geo_val = geo.value if hasattr(geo, "value") else str(geo)
        if geo_val.upper() == "VN":
            return self._is_vietnamese(title)

        # Generalized international localization: reject noise and empty signals
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
                    return False
        return len(title.strip()) >= 3



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
        demand_signals = [s for s in signals if s.platform == PlatformType.GOOGLE_TRENDS]
        demand_map: Dict[str, float] = {}
        for s in demand_signals:
            kw_meta = s.metadata.get("keyword", "")
            if kw_meta:
                demand_map[kw_meta.lower().strip()] = float(s.metric_value)
            for raw_kw in target_keywords:
                if raw_kw.lower() in s.raw_title.lower():
                    demand_map[raw_kw.lower().strip()] = max(demand_map.get(raw_kw.lower().strip(), 0.0), float(s.metric_value))

        for raw_kw in target_keywords:
            kw_clean = raw_kw.lower().strip()
            demand_score = demand_map.get(kw_clean, 50.0)

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
            v_str = f"{loc_count} video{plat_str}" if loc_count == 1 else f"{loc_count} videos{plat_str}"

            # Strict Opportunity Index with Inverted Sample Size Damping & Label Alignment
            if loc_count == 0:
                opportunity_index = round(demand_score * 0.15, 1)
                opp_type = "UNVERIFIED_DEMAND_GAP"
                rec = f"Search demand for '{raw_kw}' reaches {demand_score:.0f}/100 with zero localized supply recorded ({v_str}). Speculative gap requiring preliminary customer interviews (Effective OI: {opportunity_index:+0.1f})."
            else:
                raw_oi = demand_score - supply_score
                if raw_oi < 0:
                    opportunity_index = round(raw_oi, 1)
                    opp_type = "SATURATED_SEGMENT"
                    rec = f"Segment '{raw_kw}' is heavily saturated ({v_str}) relative to demand (OI: {opportunity_index:+0.1f}). Requires verticalized differentiation."
                else:
                    damping_map = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90}
                    damping_factor = damping_map.get(loc_count, 1.0)
                    opportunity_index = round(raw_oi * damping_factor, 1)

                    if loc_count == 1:
                        opp_type = "PROBE_OPPORTUNITY"
                        rec = f"Initial probe detected for '{raw_kw}' ({v_str}). Early signal with thin localized supply (Effective OI: {opportunity_index:+0.1f})."
                    elif opportunity_index >= settings.WHITE_SPACE_HIGH_DEMAND_INDEX_THRESHOLD:
                        opp_type = "HIGH_DEMAND_LOW_SUPPLY"
                        rec = f"Search demand for '{raw_kw}' reaches {demand_score:.0f}/100 outstripping available supply ({v_str}). High-confidence verified opportunity (Effective OI: {opportunity_index:+0.1f})."
                    elif opportunity_index >= 10.0:
                        opp_type = "GROWING_OPPORTUNITY"
                        rec = f"Segment '{raw_kw}' shows positive momentum ({v_str}) with addressable market headroom (Effective OI: {opportunity_index:+0.1f})."
                    else:
                        opp_type = "BALANCED_COMPETITION"
                        rec = f"Segment '{raw_kw}' is in market equilibrium ({v_str}) where content supply balances consumer demand."

            if localized_videos:
                support_sigs = [f"[{s.platform.value.upper() if hasattr(s.platform, 'value') else str(s.platform).upper()}] {s.raw_title}" for s in localized_videos[:3]]
            else:
                support_sigs = ["No localized videos recorded across YouTube or TikTok in the requested timeframe."]

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
    ) -> Tuple[List[str], List[str]]:
        insights = []
        actionables = []

        insights.append(f"Market Maturity: {maturity_stage.value} — {'; '.join(maturity_reasons)}")

        top_gaps = [o for o in opportunities if o.opportunity_type in ["HIGH_DEMAND_LOW_SUPPLY", "GROWING_OPPORTUNITY"]]
        if top_gaps:
            gap_names = ", ".join([f"'{o.topic}'" for o in top_gaps[:3]])
            insights.append(f"Largest strategic white space opportunities concentrate in: {gap_names}.")
            actionables.append(f"Focus resources on high-demand topics {gap_names} to capture early-mover category advantage.")

        # Identify dominant discussion topic dynamically from signal volume
        topic_counts: Dict[str, int] = {}
        for s in signals:
            for kw in mission.keywords:
                if self._matches_topic_strictly(s.raw_title, kw):
                    topic_counts[kw] = topic_counts.get(kw, 0) + 1

        if topic_counts:
            dominant_kw, max_count = max(topic_counts.items(), key=lambda item: item[1])
            if max_count >= 3:
                insights.append(f"Practitioner content is heavily concentrated around '{dominant_kw}' ({max_count} verified signals).")
                actionables.append(f"Differentiate positioning against existing supply density in '{dominant_kw}'.")

        actionables.append("Schedule periodic ingress cycles to monitor supply churn and search demand acceleration.")

        return insights, actionables

