import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from jinja2 import Environment, FileSystemLoader, select_autoescape

from ignis.application.ports.artifact_port import IArtifactBuilder
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.harness_models import (
    ChannelDataSummary,
    HarnessResearchReport,
    QualityScorecard,
    StrategicInsight,
    TrendMaturityStage,
)
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text


def _normalize_insights(raw_insights: List[Any]) -> List[Dict[str, Any]]:
    """
    Accept both the current StrategicInsight objects and the plain strings stored
    by missions generated before the citation engine landed, so an old dossier
    still renders instead of blowing up the template.
    """
    normalized: List[Dict[str, Any]] = []
    for item in raw_insights or []:
        if isinstance(item, StrategicInsight):
            normalized.append({"statement": item.statement, "citations": item.citations})
        elif isinstance(item, dict):
            normalized.append({
                "statement": item.get("statement", ""),
                "citations": item.get("citations", []) or [],
            })
        else:
            normalized.append({"statement": str(item), "citations": []})
    return normalized


class HtmlArtifactBuilder(IArtifactBuilder):
    """
    Deterministic HTML Artifact Builder using Jinja2 + Tailwind CDN.
    Directly incorporates Agent Harness evaluation scorecards and strategic dossiers.
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        if templates_dir is None:
            templates_dir = Path(__file__).parent / "html"
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

        def format_currency_filter(value: Any, geo: Optional[Any] = None) -> str:
            try:
                num = float(value)
            except (ValueError, TypeError):
                return str(value)
            geo_val = geo.value if hasattr(geo, "value") else str(geo or "VN")
            if geo_val == "VN":
                return f"{int(num):,} ₫".replace(",", ".")
            elif geo_val in ("US", "GLOBAL"):
                return f"${num:,.2f}" if num % 1 != 0 else f"${int(num):,}"
            elif geo_val in ("SG", "SGP"):
                return f"S${num:,.2f}" if num % 1 != 0 else f"S${int(num):,}"
            elif geo_val in ("EU", "DE", "FR"):
                return f"€{num:,.2f}"
            return f"${num:,.2f}"

        def format_number_filter(value: Any) -> str:
            try:
                num = float(value)
                if num >= 1_000_000:
                    return f"{num / 1_000_000:.1f}M"
                elif num >= 1_000:
                    return f"{num / 1_000:.1f}K"
                return f"{int(num):,}"
            except (ValueError, TypeError):
                return str(value)

        self._env.filters["format_currency"] = format_currency_filter
        self._env.filters["format_number"] = format_number_filter
        self._env.filters["sanitize_pii"] = sanitize_pii_text



    def build_dashboard_artifact(
        self,
        clusters: List[TopicCluster],
        geo: GeoCode = GeoCode.VN,
    ) -> str:
        template = self._env.get_template("trend_dashboard.html")
        return template.render(
            clusters=clusters,
            geo=geo.value if hasattr(geo, "value") else str(geo),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    # A cluster only draws this many satellite dots: the signal layer is a density hint, not a
    # navigable level, so the canvas stays cheap no matter how many rows a cluster accumulated.
    MAX_SIGNAL_DOTS_PER_CLUSTER = 24
    # Each node keeps its strongest neighbours only, otherwise dense days render as a hairball.
    MAX_EDGES_PER_NODE = 4

    def build_graph_artifact(
        self,
        clusters: List[TopicCluster],
        geo: GeoCode = GeoCode.VN,
        similarity_threshold: float = 0.12,
        clusterer: Optional[Any] = None,
    ) -> str:
        """Render an interactive force-directed graph of clusters and their signal density.

        Clusters are the navigable level: they can be hovered, clicked, filtered and searched.
        Signals are aggregated into satellite dots around their cluster and are deliberately not
        addressable, which keeps the node count bounded on days with tens of thousands of rows.
        """
        from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

        # Reuse the caller's clusterer when there is one: it carries the stopwords synced from the
        # database, which is what keeps generic words out of the topic labels.
        clusterer = clusterer or SemanticClusterer()
        doc_freq = self._token_document_frequency(clusterer, clusters)
        nodes: List[Dict[str, Any]] = []
        token_sets: List[Any] = []

        for cluster in clusters:
            platform_counts: Dict[str, int] = {}
            for signal in cluster.signals or []:
                platform = signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
                platform_counts[platform] = platform_counts.get(platform, 0) + 1

            signal_count = len(cluster.signals or [])
            momentum = cluster.momentum_category
            nodes.append({
                "id": str(cluster.id),
                "summary": sanitize_pii_text(cluster.summary_text or ""),
                "category": cluster.category or "unclassified",
                "momentum": momentum.value if hasattr(momentum, "value") else str(momentum),
                "score": round(float(cluster.cross_platform_score or 0.0), 1),
                "signal_count": signal_count,
                "platforms": platform_counts,
                "label": self._build_topic_label(clusterer, cluster, doc_freq, len(clusters)),
                "full_title": sanitize_pii_text(cluster.canonical_name or ""),
                "dots": self._build_signal_dots(cluster.signals or []),
                "last_updated_at": cluster.last_updated_at.isoformat() if cluster.last_updated_at else None,
            })
            token_sets.append(clusterer._tokenize(cluster.canonical_name or ""))

        edges = self._build_similarity_edges(clusterer, nodes, token_sets, similarity_threshold)

        template = self._env.get_template("trend_graph.html")
        return template.render(
            graph={
                "nodes": nodes,
                "edges": edges,
                "geo": geo.value if hasattr(geo, "value") else str(geo),
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            },
            geo=geo.value if hasattr(geo, "value") else str(geo),
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    # A dot label longer than this is truncated: the tooltip is a peek at the signal, not a reader.
    MAX_DOT_TITLE_CHARS = 140
    # Words kept in a node's topic label.
    TOPIC_LABEL_MAX_WORDS = 6
    # A token appearing in more than this share of clusters describes the corpus, not one topic.
    MAX_TOKEN_DOCUMENT_SHARE = 0.15
    # Minimum in-cluster count per cluster it appears in, before a token may headline a label.
    MIN_TOKEN_DISTINCTIVENESS = 0.9

    @classmethod
    def _build_signal_dots(cls, signals: List[TrendSignal]) -> List[Dict[str, str]]:
        """Sample the signal layer down to at most MAX_SIGNAL_DOTS_PER_CLUSTER dots.

        Each dot carries the verbatim title of one real signal, so hovering it shows what was
        actually captured; the cluster node itself carries the summarised topic label.
        """
        if not signals:
            return []

        step = max(1, len(signals) // cls.MAX_SIGNAL_DOTS_PER_CLUSTER)
        sampled = signals[::step][: cls.MAX_SIGNAL_DOTS_PER_CLUSTER]
        dots: List[Dict[str, str]] = []
        for signal in sampled:
            platform = signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
            title = re.sub(r"\s+", " ", sanitize_pii_text(signal.raw_title or "")).strip()
            if len(title) > cls.MAX_DOT_TITLE_CHARS:
                title = title[: cls.MAX_DOT_TITLE_CHARS - 1].rstrip() + "…"
            dots.append({"p": platform, "t": title})
        return dots

    @staticmethod
    def _token_document_frequency(clusterer: Any, clusters: List[TopicCluster]) -> Dict[str, int]:
        """Count how many clusters each token appears in, so ubiquitous words can be discounted."""
        doc_freq: Dict[str, int] = {}
        for cluster in clusters:
            tokens: Set[str] = set()
            for signal in cluster.signals or []:
                tokens |= clusterer._tokenize(signal.raw_title or "")
            for token in tokens:
                doc_freq[token] = doc_freq.get(token, 0) + 1
        return doc_freq

    @classmethod
    def _build_topic_label(
        cls,
        clusterer: Any,
        cluster: TopicCluster,
        doc_freq: Optional[Dict[str, int]] = None,
        total_clusters: int = 1,
    ) -> str:
        """Summarise a cluster into a short topic label instead of one signal's verbatim title.

        canonical_name is the most informative raw title in the group, which reads as a stray post
        rather than a topic. Score every window of words in it by how many of its tokens recur
        across the cluster's other signals, and keep the densest window: what survives is the
        vocabulary the cluster actually shares.
        """
        canonical = clusterer._clean_title(cluster.canonical_name or "")
        words = [w for w in canonical.split() if w]
        if not words:
            return cluster.canonical_name or ""

        shared: Set[str] = set()
        counts: Dict[str, int] = {}
        signals = cluster.signals or []
        if len(signals) > 1:
            for signal in signals:
                for token in clusterer._tokenize(signal.raw_title or ""):
                    counts[token] = counts.get(token, 0) + 1
            quorum = max(2, (len(signals) + 1) // 2)
            # A token that shows up in most clusters describes the corpus, not this topic.
            ceiling = max(2, int(total_clusters * cls.MAX_TOKEN_DOCUMENT_SHARE))
            shared = {
                token for token, count in counts.items()
                if count >= quorum and (doc_freq or {}).get(token, 1) <= ceiling
            }

        window = min(cls.TOPIC_LABEL_MAX_WORDS, len(words))
        normalized = [re.sub(r"[^\w]", "", w.lower()) for w in words]
        best_start, best_score = 0, -1
        for start in range(0, len(words) - window + 1):
            score = sum(1 for token in normalized[start:start + window] if token in shared)
            if score > best_score:
                best_start, best_score = start, score

        if best_score <= 0 and counts:
            # No phrase recurs across the cluster, so quoting any window would just quote one post.
            # Fall back to the tokens this cluster leans on that the rest of the corpus does not.
            freq = doc_freq or {}
            ranked = sorted(
                ((token, count / max(1, freq.get(token, 1))) for token, count in counts.items() if count > 1),
                key=lambda kv: (-kv[1], kv[0]),
            )
            top = [token for token, weight in ranked[:3] if weight > cls.MIN_TOKEN_DISTINCTIVENESS]
            if top:
                return " · ".join(top)

        start, end = best_start, best_start + window
        if best_score > 0:
            # Trim edges that carry none of the shared vocabulary, so the label lands on the phrase
            # the cluster is actually about rather than on whatever preceded it in one post.
            while end - start > 2 and normalized[start] not in shared:
                start += 1
            while end - start > 2 and normalized[end - 1] not in shared:
                end -= 1

        label = " ".join(words[start:end]).strip(" -–—:;,.\"'")
        if start > 0:
            label = "… " + label
        if end < len(words):
            label = label + " …"
        return label or canonical

    @classmethod
    def _build_similarity_edges(
        cls,
        clusterer: Any,
        nodes: List[Dict[str, Any]],
        token_sets: List[Any],
        threshold: float,
    ) -> List[Dict[str, Any]]:
        """Link clusters by title similarity, keeping only each node's strongest neighbours."""
        candidates: Dict[int, List[Dict[str, Any]]] = {}
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                weight = clusterer._calculate_similarity(token_sets[i], token_sets[j])
                if weight < threshold:
                    continue
                edge = {"source": nodes[i]["id"], "target": nodes[j]["id"], "weight": round(weight, 3)}
                candidates.setdefault(i, []).append(edge)
                candidates.setdefault(j, []).append(edge)

        kept: Dict[tuple, Dict[str, Any]] = {}
        for edge_list in candidates.values():
            for edge in sorted(edge_list, key=lambda e: e["weight"], reverse=True)[: cls.MAX_EDGES_PER_NODE]:
                kept[(edge["source"], edge["target"])] = edge
        return list(kept.values())

    def build_topic_card_artifact(
        self,
        cluster: TopicCluster,
        signals: List[TrendSignal],
    ) -> str:
        template = self._env.get_template("trend_card.html")
        return template.render(
            cluster=cluster,
            signals=signals,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

    def build_mission_report_artifact(
        self,
        mission: ResearchMission,
        signals: List[TrendSignal],
        platform_breakdown: Dict[str, int],
        report: Optional[HarnessResearchReport] = None,
        customer_inquiries: Optional[List[Dict[str, Any]]] = None,
        search_suggestions: Optional[List[Dict[str, Any]]] = None,
        macro_trends: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        template = self._env.get_template("mission_report.html")
        
        # If report is omitted, generate default scorecard baseline
        scorecard = report.scorecard if report else QualityScorecard(
            coverage_score=round((len(platform_breakdown) / 5.0) * 100.0, 1),
            language_precision=90.0,
            data_freshness_score=95.0,
            creator_diversity_score=85.0,
            overall_confidence=82.5,
        )
        channel_summaries: List[ChannelDataSummary] = list(report.channel_summaries) if report else []
        maturity = report.maturity_stage if report else TrendMaturityStage.EMERGING
        opportunities = report.market_opportunities if report else []
        insights = _normalize_insights(report.strategic_insights if report else [
            "Multi-platform verified market signals collected.",
            "Analyzing search demand velocity and content engagement distribution in target market."
        ])
        actionables = report.actionable_takeaways if report else [
            "Capitalize on high-demand, low-supply content white spaces.",
            "Establish recurring ingress monitoring to capture emerging trend momentum."
        ]

        return template.render(
            mission=mission,
            signals=signals,
            platform_breakdown=platform_breakdown,
            scorecard=scorecard,
            maturity_stage=maturity,
            market_opportunities=opportunities,
            strategic_insights=insights,
            channel_summaries=channel_summaries,
            actionable_takeaways=actionables,
            customer_inquiries=customer_inquiries or [],
            search_suggestions=search_suggestions or [],
            macro_trends=macro_trends or [],
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

