import logging
from typing import List
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import HarnessResearchReport
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner

logger = logging.getLogger(__name__)


class AutonomousRefinementOrchestrator:
    """
    Agent Harness Orchestrator: Tự động điều phối quá trình nghiên cứu,
    chạy Refinement Loop để tối ưu dữ liệu, chấm điểm chất lượng và tổng hợp báo cáo chiến lược.
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
            raise ValueError(f"Research Mission {mission_id} không tồn tại.")

        logger.info(f"[Harness] Bắt đầu Autonomous Ingress Loop cho Mission '{mission.title}' (ID: {mission_id})...")
        mission.status = "RUNNING"
        await self._repo.update_mission(mission)

        # 0. Nạp Dynamic Lexicons & Foreign Stopwords từ PostgreSQL DB
        try:
            db_lexicons = await self._repo.get_domain_lexicons()
            pos_terms = [item["term"] for item in db_lexicons if item.get("domain") != "foreign_stopwords"]
            stop_terms = [item["term"] for item in db_lexicons if item.get("domain") == "foreign_stopwords"]
            if pos_terms:
                self._evaluator.register_terms(pos_terms)
                self._reasoner.register_terms(pos_terms)
            if stop_terms:
                self._evaluator.register_foreign_stopwords(stop_terms)
                self._reasoner.register_foreign_stopwords(stop_terms)
        except Exception as e:
            logger.warning(f"[Harness] Không thể tải dynamic lexicons từ DB: {e}")

        # Pass 1: Cào theo từ khóa chính
        signals: List[TrendSignal] = await self._registry.search_across_all(
            keywords=mission.keywords,
            geo=mission.geo_code,
            target_platforms=mission.platforms,
        )

        for s in signals:
            s.mission_id = mission.id


        scorecard = self._evaluator.evaluate_quality(signals, geo=mission.geo_code)
        logger.info(f"[Harness] Pass 1 hoàn tất: {len(signals)} signals, Quality Confidence: {scorecard.overall_confidence}% ({scorecard.confidence_level.value}).")

        # Pass 2: Refinement Loop nếu chưa đủ tín hiệu hoặc điểm tin cậy thấp
        if len(signals) < min_signals or scorecard.overall_confidence < target_confidence:
            logger.info("[Harness] Kích hoạt Pass 2 (Refinement Loop) để mở rộng từ khóa phụ...")
            
            # Trích xuất các related queries từ Pass 1
            sub_queries = []
            for s in signals:
                for rq in s.metadata.get("related_queries", []):
                    if rq not in mission.keywords and rq not in sub_queries:
                        sub_queries.append(rq)
            
            if sub_queries:
                extra_keywords = sub_queries[:4]
                logger.info(f"[Harness] Cào bổ sung theo sub-queries: {extra_keywords}")
                extra_signals = await self._registry.search_across_all(
                    keywords=extra_keywords,
                    geo=mission.geo_code,
                    target_platforms=mission.platforms,
                )
                for es in extra_signals:
                    es.mission_id = mission.id
                signals.extend(extra_signals)

                # Đánh giá lại chất lượng sau khi bổ sung
                scorecard = self._evaluator.evaluate_quality(signals, geo=mission.geo_code)
                logger.info(f"[Harness] Sau Pass 2: Tổng cộng {len(signals)} signals, Confidence: {scorecard.overall_confidence}%.")

        # Gom cụm Semantic Clustering
        clusters = await self._clusterer.cluster_signals(signals) if signals else []

        # Lưu dữ liệu vào Supabase
        if clusters:
            await self._repo.save_clusters(clusters)
        if signals:
            await self._repo.save_signals(signals)

        # Phân tích chiến lược qua StrategicMarketReasoner
        report = self._reasoner.analyze_mission(
            mission=mission,
            signals=signals,
            clusters=clusters,
            scorecard=scorecard,
        )

        mission.status = "COMPLETED"
        mission.summary = f"Confidence: {scorecard.overall_confidence}% ({scorecard.confidence_level.value}) | Thu thập {len(signals)} signals | Phát hiện {len(report.market_opportunities)} cơ hội thị trường."
        await self._repo.update_mission(mission)

        return report
