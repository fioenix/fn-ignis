import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from ignis.application.use_cases.create_mission import CreateMissionUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder
from ignis.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ignis.case_studies")

CASE_STUDIES = [
    {
        "title": "Nghiên cứu Thị trường AI Agent CSKH & Tự động hóa Doanh nghiệp",
        "keywords": ["AI Agent CSKH", "Chatbot AI", "tự động hóa n8n", "AI Agent doanh nghiệp", "Dify AI"],
        "geo": GeoCode.VN,
        "timeframe": Timeframe.LAST_30D,
        "filename": "case_study_ai_agents_vn.html",
    },

    {
        "title": "Nghiên cứu Khoảng trống Ngành Thời trang Áo Linen & Local Brand VN",
        "keywords": ["áo linen", "đầm thiết kế linen", "local brand", "thời trang công sở", "xưởng may linen"],
        "geo": GeoCode.VN,
        "timeframe": Timeframe.LAST_30D,
        "filename": "case_study_linen_fashion_vn.html",
    },
    {
        "title": "Nghiên cứu Nhu cầu Công cụ Quản lý Đơn & Livestream TikTok Shop",
        "keywords": ["phần mềm chốt đơn tiktok shop", "công cụ livestream", "affiliate tiktok shop", "quản lý đơn hàng", "tool kéo tương tác"],
        "geo": GeoCode.VN,
        "timeframe": Timeframe.LAST_30D,
        "filename": "case_study_tiktok_shop_automation_vn.html",
    },
]

async def run_all_case_studies():
    repo = create_repository()
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(GoogleTrendsRssPlugin())
    registry.register(TikTokPlugin())
    registry.register(TikTokCreativeCenterPlugin())
    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

    clusterer = SemanticClusterer()
    cluster_use_case = ClusterSignalsUseCase(clusterer=clusterer, repository=repo)
    top_clusters_use_case = GetTopClustersUseCase(repository=repo)
    quality_evaluator = QualityEvaluator()

    strategic_reasoner = StrategicMarketReasoner()
    artifact_builder = HtmlArtifactBuilder()

    create_uc = CreateMissionUseCase(repository=repo)
    execute_uc = ExecuteMissionUseCase(
        repository=repo,
        registry=registry,
        clusterer=clusterer,
    )

    reports_dir = Path(__file__).resolve().parents[1] / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    for cs in CASE_STUDIES:
        logger.info(f"==> Bắt đầu Case Study: {cs['title']}...")
        mission = await create_uc.execute(
            title=cs["title"],
            keywords=cs["keywords"],
            geo=cs["geo"],
            timeframe=cs["timeframe"],
            agent="case-study-generator",
        )

        exec_res = await execute_uc.execute(
            mission_id=mission.id,
        )


        signals = await repo.get_mission_signals(mission.id)
        clusters = await top_clusters_use_case.execute(geo=mission.geo_code, limit=20)
        scorecard = quality_evaluator.evaluate_quality(signals, geo=mission.geo_code)
        
        report = strategic_reasoner.analyze_mission(
            mission=mission,
            signals=signals,
            clusters=clusters,
            scorecard=scorecard,
        )

        platform_breakdown = {}
        macro_trends = []
        customer_inquiries = []
        for s in signals:
            p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
            platform_breakdown[p_val] = platform_breakdown.get(p_val, 0) + 1

            if s.metadata.get("source") == "tiktok_creative_center":
                macro_trends.append({
                    "rank": s.metadata.get("rank", 1),
                    "hashtag": s.metadata.get("hashtag", s.raw_title),
                    "category": s.metadata.get("category", "General"),
                    "posts": s.metadata.get("posts_formatted", "N/A"),
                    "views": s.metadata.get("views_formatted", "N/A"),
                })

        html = artifact_builder.build_mission_report_artifact(
            mission=mission,
            signals=signals,
            platform_breakdown=platform_breakdown,
            report=report,
            macro_trends=macro_trends,
            customer_inquiries=customer_inquiries,
        )


        out_file = reports_dir / cs["filename"]
        out_file.write_text(html, encoding="utf-8")
        logger.info(f"✓ Hoàn tất xuất báo cáo case study: {out_file}")

    if hasattr(repo, "close"):
        await repo.close()
    logger.info("🎉 Toàn bộ 3 Case Study đã được xuất thành công vào reports/!")

if __name__ == "__main__":
    asyncio.run(run_all_case_studies())
