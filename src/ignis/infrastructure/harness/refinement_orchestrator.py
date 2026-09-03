import logging
from typing import List
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import HarnessResearchReport
from ignis.domain.value_objects import timeframe_to_days
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

logger = logging.getLogger(__name__)


class AutonomousRefinementOrchestrator:
    """
    Agent Harness Orchestrator: Coordinates autonomous research cycles,
    runs iterative refinement loops to expand keywords, evaluates data quality gates, and synthesizes strategic dossiers.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        registry: ConnectorPluginRegistry,
        clusterer: IClusteringEngine,
        quality_evaluator: QualityEvaluator,
        strategic_reasoner: StrategicMarketReasoner,
    ):
        self._repo = repository
        self._registry = registry
        self._clusterer = clusterer
        self._evaluator = quality_evaluator
        self._reasoner = strategic_reasoner

    async def run_mission_harness(
        self,
        mission_id: UUID,
        min_signals: int = 15,
        target_confidence: float = 65.0,
    ) -> HarnessResearchReport:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research mission {mission_id} does not exist.")

        logger.info(f"[Harness] Starting autonomous ingress loop for mission '{mission.title}' (ID: {mission_id})...")
        mission.status = "RUNNING"
        await self._repo.update_mission(mission)

        # 0. Load Dynamic Lexicons, Foreign Stopwords & Noise Blacklist from Database
        try:
            db_lexicons = await self._repo.get_domain_lexicons()
            pos_terms = [item["term"] for item in db_lexicons if item.get("domain") not in ("foreign_stopwords", "noise_blacklist")]
            stop_terms = [item["term"] for item in db_lexicons if item.get("domain") == "foreign_stopwords"]
            noise_terms = [item["term"] for item in db_lexicons if item.get("domain") == "noise_blacklist"]
            if pos_terms:
                self._evaluator.register_terms(pos_terms)
                self._reasoner.register_terms(pos_terms)
            if stop_terms:
                self._evaluator.register_foreign_stopwords(stop_terms)
                self._reasoner.register_foreign_stopwords(stop_terms)
            if noise_terms:
                self._evaluator.register_noise_blacklist(noise_terms)
                self._reasoner.register_noise_blacklist(noise_terms)
        except Exception as e:
            logger.warning(f"[Harness] Failed to load dynamic lexicons from DB: {e}")


        # Pass 1: Primary keyword search across target platforms
        signals: List[TrendSignal] = await self._registry.search_across_all(
            keywords=mission.keywords,
            geo=mission.geo_code,
            target_platforms=mission.platforms,
        )

        for s in signals:
            s.mission_id = mission.id

        tf_days = timeframe_to_days(mission.timeframe)
        scorecard = self._evaluator.evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
        logger.info(f"[Harness] Pass 1 complete: {len(signals)} signals, Quality Confidence: {scorecard.overall_confidence}% ({scorecard.confidence_level.value}).")

        # Pass 2: Refinement Loop if sample size or confidence score is below threshold
        if len(signals) < min_signals or scorecard.overall_confidence < target_confidence:
            logger.info("[Harness] Triggering Pass 2 (Refinement Loop) to expand auxiliary sub-queries...")
            
            # Extract related queries discovered in Pass 1
            sub_queries = []
            for s in signals:
                for rq in s.metadata.get("related_queries", []):
                    if rq not in mission.keywords and rq not in sub_queries:
                        sub_queries.append(rq)
            
            if sub_queries:
                extra_keywords = sub_queries[:4]
                logger.info(f"[Harness] Ingesting auxiliary sub-queries: {extra_keywords}")
                extra_signals = await self._registry.search_across_all(
                    keywords=extra_keywords,
                    geo=mission.geo_code,
                    target_platforms=mission.platforms,
                )
                for es in extra_signals:
                    es.mission_id = mission.id
                signals.extend(extra_signals)

                # Re-evaluate quality scorecard after refinement
                scorecard = self._evaluator.evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
                logger.info(f"[Harness] Post Pass 2: Total {len(signals)} signals, Quality Confidence: {scorecard.overall_confidence}%.")

        # Semantic Clustering
        clusters = await self._clusterer.cluster_signals(signals) if signals else []

        # Persist signals and clusters
        if clusters:
            await self._repo.save_clusters(clusters)
        if signals:
            await self._repo.save_signals(signals)

        # Synthesize strategic insights via StrategicMarketReasoner
        report = self._reasoner.analyze_mission(
            mission=mission,
            signals=signals,
            clusters=clusters,
            scorecard=scorecard,
        )

        mission.status = "COMPLETED"
        mission.summary = f"Confidence: {scorecard.overall_confidence}% ({scorecard.confidence_level.value}) | Ingested {len(signals)} signals | Discovered {len(report.market_opportunities)} market opportunities."
        await self._repo.update_mission(mission)

        return report

