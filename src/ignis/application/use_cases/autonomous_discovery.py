import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ignis.application.ports.artifact_port import IArtifactBuilder
from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.harness_models import HarnessResearchReport
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.application.use_cases.ingest_trends import MAX_SEED_KEYWORDS
from ignis.infrastructure.config.vocabulary_loader import (
    MACHINERY_DOMAINS,
    TEMPLATE_PREFIXES,
)
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

logger = logging.getLogger(__name__)


class AutonomousDiscoveryUseCase:
    """
    Autonomous Trend Discovery Engine.
    Executes the end-to-end 6-step SOP on a recurring or on-demand basis:
    Macro Scan -> Keyword Expansion -> Targeted Ingress -> Voice of Customer ->
    Cross-Platform Synthesis & Opportunity Index -> Persistent Daily Digest.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        registry: ConnectorPluginRegistry,
        clusterer: IClusteringEngine,
        quality_evaluator: QualityEvaluator,
        strategic_reasoner: StrategicMarketReasoner,
        artifact_builder: IArtifactBuilder,
        reports_dir: Optional[Path] = None,
    ):
        self._repository = repository
        self._registry = registry
        self._clusterer = clusterer
        self._quality_evaluator = quality_evaluator
        self._strategic_reasoner = strategic_reasoner
        self._artifact_builder = artifact_builder
        self._reports_dir = reports_dir or (Path(__file__).resolve().parents[3] / "reports")
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    async def _load_seed_keywords(self) -> List[str]:
        """Read probe seeds from the persisted market lexicon, never from a constant in code.

        Mirrors IngestTrendsUseCase.load_seed_keywords: the machinery domains hold stopwords and
        matcher vocabulary, not topics, so they are not something to go and search for.
        """
        try:
            lexicons = await self._repository.get_domain_lexicons()
        except Exception as e:
            logger.warning(f"Could not load seed keywords from the market lexicon: {e}")
            return []

        seeds: List[str] = []
        for item in lexicons or []:
            domain = str(item.get("domain") or "").strip().lower()
            if domain in MACHINERY_DOMAINS or domain.startswith(TEMPLATE_PREFIXES):
                continue
            term = str(item.get("term") or "").strip()
            if term and term not in seeds:
                seeds.append(term)
        return seeds[:MAX_SEED_KEYWORDS]

    async def execute(
        self,
        geo: GeoCode = GeoCode.VN,
        max_macro_topics: int = 5,
        max_videos_per_topic: int = 3,
        comments_limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Execute a full autonomous discovery cycle for the target geography.
        """
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        mission_shortcode = f"DISCOVERY-{geo.value}-{today_str.replace('-', '')}"
        logger.info(f"Starting Autonomous Discovery Cycle [{mission_shortcode}] for geo={geo.value}...")

        # Step 1: Initialize or Retrieve Daily Discovery Mission
        mission_title = f"Autonomous Market Discovery Digest - {geo.value} ({today_str})"
        existing_missions = await self._repository.list_missions(limit=20)
        mission: Optional[ResearchMission] = None
        for m in existing_missions:
            if m.shortcode == mission_shortcode:
                mission = m
                break

        if not mission:
            mission = ResearchMission(
                title=mission_title,
                keywords=[],
                shortcode=mission_shortcode,
                geo_code=geo,
                timeframe=Timeframe.LAST_7D,
                summary=f"Automated daily market intelligence scan for {geo.value}.",
                created_at=datetime.now(timezone.utc),
            )
            await self._repository.save_mission(mission)

        # Step 2: Macro Scan (TikTok Creative Center & Google RSS)
        macro_trends: List[Dict[str, Any]] = []
        macro_keywords: List[str] = []

        try:
            # Dynamically load registered noise terms from database
            noise_lexicons = await self._repository.get_domain_lexicons(domain="noise_blacklist")
            noise_terms = {item["term"].lower().strip() for item in noise_lexicons}
            if noise_terms:
                self._quality_evaluator.register_noise_blacklist(list(noise_terms))
                self._strategic_reasoner.register_noise_blacklist(list(noise_terms))

            cc_plugin = None
            for _, plugin in self._registry._plugins.items():
                if isinstance(plugin, TikTokCreativeCenterPlugin):
                    cc_plugin = plugin
                    break
            if cc_plugin:
                macro_trends = await cc_plugin.fetch_macro_trends(
                    geo=geo, period=7, limit=max_macro_topics, industry="Tech & Electronics"
                )
                for item in macro_trends:
                    tag = item.get("hashtag", "").replace("#", "").strip().lower()
                    if tag and tag not in noise_terms and tag not in macro_keywords:
                        macro_keywords.append(tag)
        except Exception as e:
            logger.warning(f"Macro scan via Creative Center encountered error: {e}", exc_info=True)




        # Where the scope of this cycle came from. An empty macro scan used to be papered over
        # with five keywords compiled into this file, which quietly turned "what is the market
        # discussing" into "what is happening in AI agents and ecommerce" without saying so.
        keyword_source = "creative_center"
        if not macro_keywords:
            # The persisted lexicon is the operator's own vocabulary, not this file's opinion.
            keyword_source = "market_lexicon"
            macro_keywords = await self._load_seed_keywords()
            logger.warning(
                f"Macro scan returned no hashtags; falling back to {len(macro_keywords)} seed "
                f"terms from market_lexicons. This cycle reflects the seeded vocabulary, not "
                f"what the platform surfaced on its own."
            )
        if not macro_keywords:
            keyword_source = "none"
            logger.error(
                "Macro scan returned nothing and market_lexicons holds no seed terms, so this "
                "cycle has no scope to probe. Reporting empty rather than inventing keywords."
            )
            return {
                "status": "NO_SCOPE",
                "mission_id": str(mission.id),
                "shortcode": mission_shortcode,
                "geo_code": geo.value,
                "keyword_source": keyword_source,
                "message": (
                    "Discovery found no candidate topics. The Creative Center scan came back "
                    "empty and no seed terms are registered. Register domain vocabulary with "
                    "register_domain_lexicon, or check the TikTok session."
                ),
            }


        # Step 3: Real-World Search Suggestions & Sub-Niche Expansion
        search_suggestions: List[Dict[str, Any]] = []
        expanded_keywords: List[str] = list(macro_keywords)

        try:
            suggestions_data = await self._registry.fetch_suggestions_across_all(
                keywords=macro_keywords[:max_macro_topics],
                geo=geo,
                target_platforms=[PlatformType.TIKTOK],
            )
            search_suggestions = suggestions_data
            for entry in suggestions_data:
                for sug in entry.get("suggestions", []):
                    q = sug.get("query", "").replace("#", "").strip()
                    if q and len(q) > 2 and q not in expanded_keywords:
                        expanded_keywords.append(q)
        except Exception as e:
            logger.warning(f"Keyword expansion via search suggestions encountered error: {e}")

        # Update mission keywords with discovered scope
        mission.keywords = expanded_keywords[:15]
        await self._repository.save_mission(mission)

        # Step 4: Targeted Deep Multi-Platform Ingress
        ingested_signals: List[TrendSignal] = []
        try:
            ingested_signals = await self._registry.search_across_all(
                keywords=mission.keywords[:8],
                geo=geo,
                timeframe=Timeframe.LAST_7D,
                limit=30,
            )
            # Bind signals to mission
            for s in ingested_signals:
                s.mission_id = mission.id
            if ingested_signals:
                await self._repository.save_signals(ingested_signals)
        except Exception as e:
            logger.error(f"Targeted multi-platform ingress error: {e}")

        # Step 5: Voice of Customer & Pain Points Extraction
        customer_inquiries: List[Dict[str, Any]] = []
        try:
            tiktok_plugin = None
            for _, plugin in self._registry._plugins.items():
                if isinstance(plugin, TikTokPlugin):
                    tiktok_plugin = plugin
                    break

            inquiry_rows = await self._repository.get_domain_lexicons(domain="customer_inquiry")
            inquiry_markers = [
                str(row["term"]).lower() for row in (inquiry_rows or []) if row.get("term")
            ]
            if not inquiry_markers:
                logger.warning(
                    "No customer inquiry markers registered, so no comment can be recognised as a "
                    "question. Check the customer_inquiry domain in market_lexicons."
                )

            if tiktok_plugin and inquiry_markers:
                voc_data = await tiktok_plugin.fetch_top_comments_for_keywords(
                    keywords=mission.keywords[:3],
                    geo=geo,
                    max_videos=max_videos_per_topic,
                    limit_per_video=comments_limit,
                )
                for v in voc_data:
                    for c in v.get("comments", []):
                        txt = c.get("text", "")
                        if any(q in txt.lower() for q in inquiry_markers):
                            customer_inquiries.append({
                                "author": c.get("author"),
                                "inquiry": txt,
                                "likes": c.get("likes", 0),
                                "video_title": v.get("video_title"),
                            })
        except Exception as e:
            logger.warning(f"Voice of customer extraction encountered error: {e}")

        # Step 6: Synthesis, Semantic Clustering & Opportunity Matrix
        all_signals = await self._repository.get_mission_signals(mission.id)
        if not all_signals:
            all_signals = ingested_signals

        clusters: List[TopicCluster] = []
        if all_signals:
            clusters = await self._clusterer.cluster_signals(all_signals)
            await self._repository.save_clusters(clusters)
            # The signals were persisted before they were clustered, so membership lands as an
            # update on the observations already written. Calling save_signals again would
            # record every one of them a second time, as sightings that never happened.
            await self._repository.assign_observation_clusters(all_signals)

        # Load dynamic lexicons & foreign stopwords from database
        try:

            db_lexicons = await self._repository.get_domain_lexicons()
            pos_terms = [item["term"] for item in db_lexicons if item.get("domain") != "foreign_stopwords"]
            stop_terms = [item["term"] for item in db_lexicons if item.get("domain") == "foreign_stopwords"]
            if pos_terms:
                self._quality_evaluator.register_terms(pos_terms)
                self._strategic_reasoner.register_terms(pos_terms)
            if stop_terms:
                self._quality_evaluator.register_foreign_stopwords(stop_terms)
                self._strategic_reasoner.register_foreign_stopwords(stop_terms)
        except Exception as e:
            logger.warning(f"Could not load dynamic lexicons from DB: {e}")

        scorecard = self._quality_evaluator.evaluate_quality(all_signals, geo=geo)
        report: HarnessResearchReport = self._strategic_reasoner.analyze_mission(
            mission=mission,
            signals=all_signals,
            clusters=clusters,
            scorecard=scorecard,
        )


        # Platform breakdown
        platform_breakdown: Dict[str, int] = {}
        for s in all_signals:
            p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            platform_breakdown[p_val] = platform_breakdown.get(p_val, 0) + 1

        # Step 7: Render and Persist Daily HTML Digest Artifact
        html_content = self._artifact_builder.build_mission_report_artifact(
            mission=mission,
            signals=all_signals,
            platform_breakdown=platform_breakdown,
            report=report,
            customer_inquiries=customer_inquiries[:15],
            search_suggestions=search_suggestions,
            macro_trends=macro_trends,
        )

        report_filename = f"daily_discovery_{geo.value.lower()}_{today_str}.html"
        report_file = self._reports_dir / report_filename
        report_file.write_text(html_content, encoding="utf-8")
        abs_path = str(report_file.resolve())

        # Log audit event
        await self._repository.log_event(
            component="AutonomousDiscoveryEngine",
            event_type="DISCOVERY_COMPLETED",
            message=f"Completed autonomous discovery cycle [{mission_shortcode}] with {len(all_signals)} signals.",
            level="INFO",
            details={
                "mission_id": str(mission.id),
                "shortcode": mission_shortcode,
                "total_signals": len(all_signals),
                "total_clusters": len(clusters),
                "top_opportunities": [opp.topic for opp in report.market_opportunities[:5]],
                "artifact_file": abs_path,
            },
        )

        logger.info(f"Autonomous Discovery Cycle completed. Report saved to: {abs_path}")
        return {
            "status": "SUCCESS",
            "mission_id": str(mission.id),
            "shortcode": mission_shortcode,
            "title": mission.title,
            "geo_code": geo.value,
            "keyword_source": keyword_source,
            "total_signals": len(all_signals),
            "total_clusters": len(clusters),
            "top_opportunities": [
                {
                    "topic": opp.topic,
                    "type": opp.opportunity_type,
                    "opportunity_index": opp.opportunity_index,
                    "recommendation": opp.strategic_recommendation,
                }
                for opp in report.market_opportunities[:5]
            ],
            "total_customer_inquiries": len(customer_inquiries),
            "artifact_file": abs_path,
            "file_url": f"file://{abs_path}",
        }
