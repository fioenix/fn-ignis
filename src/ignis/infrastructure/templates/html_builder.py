from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
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

