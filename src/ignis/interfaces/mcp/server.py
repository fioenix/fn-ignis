import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

# Ensure MCP compatibility bridge before importing FastMCP
import mcp.shared.exceptions
if not hasattr(mcp.shared.exceptions, "McpError") and hasattr(mcp.shared.exceptions, "MCPError"):
    mcp.shared.exceptions.McpError = mcp.shared.exceptions.MCPError

from fastmcp import FastMCP

from ignis.application.use_cases.create_mission import CreateMissionUseCase
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.config import settings
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.refinement_orchestrator import AutonomousRefinementOrchestrator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

logger = logging.getLogger("ignis.mcp")

# Khởi tạo FastMCP Server
mcp = FastMCP("fn-ignis-trend-intelligence")

def _init_components():
    repository = PostgresTimescaleRepository(
        dsn=settings.DATABASE_URL,
        min_pool_size=settings.DB_MIN_POOL_SIZE,
        max_pool_size=settings.DB_MAX_POOL_SIZE,
    )
    registry = ConnectorPluginRegistry(repository=repository)
    registry.register(GoogleTrendsRssPlugin())
    registry.register(TikTokPlugin())
    registry.register(ThreadsPlugin())
    registry.register(ReelsPlugin())

    if settings.YOUTUBE_API_KEY:
        registry.register(YouTubeDataPlugin(api_key=settings.YOUTUBE_API_KEY))

    clusterer = SemanticClusterer()
    artifact_builder = HtmlArtifactBuilder()
    quality_evaluator = QualityEvaluator()
    strategic_reasoner = StrategicMarketReasoner()

    harness_orchestrator = AutonomousRefinementOrchestrator(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        quality_evaluator=quality_evaluator,
        strategic_reasoner=strategic_reasoner,
    )

    create_mission_use_case = CreateMissionUseCase(repository=repository)
    execute_mission_use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
    )
    get_mission_analysis_use_case = GetMissionAnalysisUseCase(repository=repository)
    top_clusters_use_case = GetTopClustersUseCase(repository=repository)
    ingest_use_case = IngestTrendsUseCase(registry=registry, repository=repository)
    cluster_use_case = ClusterSignalsUseCase(clusterer=clusterer, repository=repository)

    return {
        "repository": repository,
        "registry": registry,
        "clusterer": clusterer,
        "artifact_builder": artifact_builder,
        "quality_evaluator": quality_evaluator,
        "strategic_reasoner": strategic_reasoner,
        "harness_orchestrator": harness_orchestrator,
        "create_mission_use_case": create_mission_use_case,
        "execute_mission_use_case": execute_mission_use_case,
        "get_mission_analysis_use_case": get_mission_analysis_use_case,
        "top_clusters_use_case": top_clusters_use_case,
        "ingest_use_case": ingest_use_case,
        "cluster_use_case": cluster_use_case,
    }

_COMPONENTS = None

def get_components():
    global _COMPONENTS
    if _COMPONENTS is None:
        _COMPONENTS = _init_components()
    return _COMPONENTS


# --- Handlers for Agent Harness Operations ---

async def handle_run_autonomous_research_mission(
    topic: str,
    keywords: List[str],
    geo: str = "VN",
    timeframe: str = "7d",
    min_signals: int = 15,
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    """Chạy toàn diện Harness: Tự động khởi tạo, Refinement Loop, Đánh giá chất lượng và Bóc tách chiến lược."""
    comp = get_components()
    geo_val = GeoCode(geo.upper()) if geo.upper() in GeoCode._value2member_map_ else GeoCode.VN

    # 1. Tạo Mission
    mission = await comp["create_mission_use_case"].execute(
        title=topic,
        keywords=keywords,
        agent=agent,
        session_id=session_id,
        geo=geo_val,
        timeframe=timeframe,
    )

    # 2. Chạy Harness Orchestrator
    report = await comp["harness_orchestrator"].run_mission_harness(
        mission_id=mission.id,
        min_signals=min_signals,
    )

    return json.dumps(
        {
            "status": "COMPLETED",
            "mission_id": str(mission.id),
            "title": mission.title,
            "scorecard": {
                "coverage_score": report.scorecard.coverage_score,
                "language_precision": report.scorecard.language_precision,
                "data_freshness_score": report.scorecard.data_freshness_score,
                "creator_diversity_score": report.scorecard.creator_diversity_score,
                "overall_confidence": report.scorecard.overall_confidence,
                "confidence_level": report.scorecard.confidence_level.value,
                "flaws": report.scorecard.flaws_detected,
                "strengths": report.scorecard.strengths_detected,
            },
            "maturity_stage": report.maturity_stage.value,
            "market_opportunities": [
                {
                    "topic": opp.topic,
                    "type": opp.opportunity_type,
                    "demand_score": opp.search_interest_score,
                    "supply_score": opp.content_supply_score,
                    "opportunity_index": opp.opportunity_index,
                    "recommendation": opp.strategic_recommendation,
                }
                for opp in report.market_opportunities
            ],
            "strategic_insights": report.strategic_insights,
            "actionable_takeaways": report.actionable_takeaways,
            "next_step": f"Gọi generate_mission_artifact(mission_id='{mission.id}') để xem báo cáo HTML đầy đủ."
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_evaluate_mission_quality(mission_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Không tìm thấy mission với mã: '{mission_id}'"}, ensure_ascii=False)
    m_id = mission.id
    if not mission:
        return json.dumps({"error": "Mission not found"}, ensure_ascii=False)

    signals = await comp["repository"].get_mission_signals(m_id)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code)

    return json.dumps(
        {
            "mission_id": str(mission.id),
            "coverage_score": scorecard.coverage_score,
            "language_precision": scorecard.language_precision,
            "data_freshness_score": scorecard.data_freshness_score,
            "creator_diversity_score": scorecard.creator_diversity_score,
            "overall_confidence": scorecard.overall_confidence,
            "confidence_level": scorecard.confidence_level.value,
            "flaws_detected": scorecard.flaws_detected,
            "strengths_detected": scorecard.strengths_detected,
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_discover_market_opportunities(mission_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Không tìm thấy mission với mã: '{mission_id}'"}, ensure_ascii=False)
    m_id = mission.id
    if not mission:
        return json.dumps({"error": "Mission not found"}, ensure_ascii=False)

    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code)
    
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
    )

    return json.dumps(
        {
            "mission_id": str(mission.id),
            "maturity_stage": report.maturity_stage.value,
            "market_opportunities": [
                {
                    "topic": opp.topic,
                    "type": opp.opportunity_type,
                    "demand_score": opp.search_interest_score,
                    "supply_score": opp.content_supply_score,
                    "opportunity_index": opp.opportunity_index,
                    "recommendation": opp.strategic_recommendation,
                }
                for opp in report.market_opportunities
            ],
            "strategic_insights": report.strategic_insights,
            "actionables": report.actionable_takeaways,
        },
        ensure_ascii=False,
        indent=2
    )


# --- Handlers for System Diagnostics & Logs ---

async def handle_diagnose_system_health() -> str:
    comp = get_components()
    registry: ConnectorPluginRegistry = comp["registry"]
    repo: PostgresTimescaleRepository = comp["repository"]

    health_status = registry.get_health_status()
    recent_errors = await repo.get_recent_logs(level="ERROR", limit=5)

    diagnostics = {
        "status": "HEALTHY" if all(v["circuit_state"] == "CLOSED" for v in health_status.values()) else "DEGRADED",
        "connectors": health_status,
        "recent_errors": recent_errors,
        "recommendations": []
    }

    for plat, info in health_status.items():
        if plat == "tiktok" and info["circuit_state"] != "CLOSED":
            diagnostics["recommendations"].append("TikTok bị chặn bởi bot detection / WAF. Cần bật Playwright headless browser hoặc cập nhật session cookie.")
        elif plat in ["threads", "reels"] and info["circuit_state"] != "CLOSED":
            diagnostics["recommendations"].append(f"Meta ({plat}) yêu cầu xác thực hoặc GraphQL token. Cần kiểm tra sessionid.")
        elif plat == "youtube" and not settings.YOUTUBE_API_KEY:
            diagnostics["recommendations"].append("YouTube API key chưa được cấu hình trong .env.")

    return json.dumps(diagnostics, ensure_ascii=False, indent=2)


async def handle_get_system_logs(level: Optional[str] = None, component: Optional[str] = None, limit: int = 20) -> str:
    comp = get_components()
    repo: PostgresTimescaleRepository = comp["repository"]
    safe_limit = max(1, min(limit, 30))
    raw_logs = await repo.get_recent_logs(level=level, component=component, limit=safe_limit)
    
    # Rút gọn nội dung chi tiết để không làm phình to token
    sanitized_logs = []
    for log in raw_logs:
        msg = log.get("message", "")
        if len(msg) > 300:
            msg = msg[:300] + "..."
        details = log.get("details", {})
        if isinstance(details, dict):
            details = {k: (str(v)[:150] + "..." if len(str(v)) > 150 else v) for k, v in details.items()}
        sanitized_logs.append({
            "id": log.get("id"),
            "level": log.get("level"),
            "component": log.get("component"),
            "event_type": log.get("event_type"),
            "message": msg,
            "details": details,
            "created_at": log.get("created_at"),
        })
    return json.dumps(sanitized_logs, ensure_ascii=False, indent=2)


# --- Handlers for Research Missions ---

async def handle_create_research_mission(
    topic: str,
    keywords: List[str],
    platforms: Optional[List[str]] = None,
    geo: str = "VN",
    timeframe: str = "7d",
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    comp = get_components()
    geo_val = GeoCode(geo.upper()) if geo.upper() in GeoCode._value2member_map_ else GeoCode.VN
    
    target_platforms = None
    if platforms:
        target_platforms = [PlatformType(p.lower()) for p in platforms if p.lower() in PlatformType._value2member_map_]

    mission = await comp["create_mission_use_case"].execute(
        title=topic,
        keywords=keywords,
        agent=agent,
        session_id=session_id,
        platforms=target_platforms,
        geo=geo_val,
        timeframe=timeframe,
    )
    return json.dumps(
        {
            "status": "created",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "display_label": f"[{mission.shortcode}] {mission.title}",
            "title": mission.title,
            "keywords": mission.keywords,
            "platforms": [p.value for p in mission.platforms],
            "geo": mission.geo_code.value,
            "timeframe": mission.timeframe,
            "tip": f"Bạn có thể dùng mã ngắn '{mission.shortcode}' hoặc '{str(mission.id)[:8]}' trong các câu lệnh tiếp theo.",
            "next_step": f"Gọi execute_mission_ingress(mission_id='{mission.shortcode}') để kích hoạt cào dữ liệu."
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_execute_mission_ingress(mission_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Không tìm thấy mission với mã: '{mission_id}'"}, ensure_ascii=False)

    result = await comp["execute_mission_use_case"].execute(mission_id=mission.id)
    result["shortcode"] = mission.shortcode
    result["display_label"] = f"[{mission.shortcode}] {mission.title}" 
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Không tìm thấy mission với mã: '{mission_id}'"}, ensure_ascii=False)

    analysis = await comp["get_mission_analysis_use_case"].execute(
        mission_id=mission.id, 
        limit=max(1, min(limit, 50)),
        platform_filter=platform
    )
    analysis["mission"]["shortcode"] = mission.shortcode
    analysis["mission"]["display_label"] = f"[{mission.shortcode}] {mission.title}" 
    return json.dumps(analysis, ensure_ascii=False, indent=2)


async def handle_generate_mission_artifact(mission_id: str) -> str:
    from pathlib import Path
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Không tìm thấy mission với mã: '{mission_id}'"}, ensure_ascii=False)
    m_id = mission.id

    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code)
    
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
    )
    
    platform_breakdown = {}
    for s in signals:
        p_val = s.platform.value if hasattr(s.platform, "value") else str(s.platform)
        platform_breakdown[p_val] = platform_breakdown.get(p_val, 0) + 1

    html_content = comp["artifact_builder"].build_mission_report_artifact(
        mission=mission,
        signals=signals,
        platform_breakdown=platform_breakdown,
        report=report,
    )

    # Lưu file HTML vào thư mục reports/ của dự án để tránh tràn token buffer
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_filename = f"mission_{mission.shortcode.lower()}.html"
    report_path = reports_dir / report_filename
    report_path.write_text(html_content, encoding="utf-8")
    abs_path = str(report_path.resolve())

    return json.dumps(
        {
            "status": "SUCCESS",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "display_label": f"[{mission.shortcode}] {mission.title}",
            "title": mission.title,
            "total_signals": len(signals),
            "artifact_file": abs_path,
            "file_url": f"file://{abs_path}",
            "quality_scorecard": {
                "overall_confidence": scorecard.overall_confidence,
                "confidence_level": scorecard.confidence_level.value,
                "coverage_score": scorecard.coverage_score,
                "data_freshness_score": scorecard.data_freshness_score,
                "language_precision": scorecard.language_precision,
                "strengths": scorecard.strengths_detected,
                "flaws": scorecard.flaws_detected,
            },
            "top_market_opportunities": [
                {
                    "topic": opp.topic,
                    "type": opp.opportunity_type,
                    "demand_score": opp.search_interest_score,
                    "supply_score": opp.content_supply_score,
                    "opportunity_index": opp.opportunity_index,
                    "recommendation": opp.strategic_recommendation,
                }
                for opp in report.market_opportunities[:5]
            ],
            "strategic_insights": report.strategic_insights[:3],
            "actionable_takeaways": report.actionable_takeaways[:3],
            "instructions_for_user": f"Báo cáo HTML đầy đủ ({len(signals)} signals) đã được xuất thành công. Bạn có thể mở trực tiếp đường dẫn file://{abs_path} trên trình duyệt.",
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_list_research_missions(limit: int = 10) -> str:
    comp = get_components()
    safe_limit = max(1, min(limit, 30))
    missions = await comp["repository"].list_missions(limit=safe_limit)
    result = [
        {
            "id": str(m.id),
            "shortcode": m.shortcode,
            "display_label": f"[{m.shortcode}] {m.title}",
            "title": m.title,
            "keywords": m.keywords,
            "status": m.status,
            "summary": (m.summary[:200] + "...") if m.summary and len(m.summary) > 200 else m.summary,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in missions
    ]
    return json.dumps(result, ensure_ascii=False, indent=2)


# --- Legacy Handlers ---

async def handle_get_trending_topics(
    geo: str = "VN",
    timeframe: str = "24h",
    limit: int = 10,
) -> str:
    comp = get_components()
    geo_val = GeoCode(geo.upper()) if geo.upper() in GeoCode._value2member_map_ else GeoCode.VN
    tf_val = Timeframe(timeframe) if timeframe in Timeframe._value2member_map_ else Timeframe.LAST_24H

    safe_limit = max(1, min(limit, 30))
    clusters = await comp["top_clusters_use_case"].execute(geo=geo_val, timeframe=tf_val, limit=safe_limit)
    result = [
        {
            "id": str(c.id),
            "topic_name": c.canonical_name,
            "summary": c.summary_text,
            "category": c.category,
            "cross_platform_score": c.cross_platform_score,
            "momentum": c.momentum_category.value,
            "signal_count": len(c.signals),
        }
        for c in clusters
    ]
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_topic_detail(topic_id: str, limit: int = 20) -> str:
    comp = get_components()
    try:
        cluster_uuid = UUID(topic_id.strip())
    except (ValueError, AttributeError):
        return json.dumps({"error": f"Invalid UUID: {topic_id}"}, ensure_ascii=False)

    all_signals = await comp["repository"].get_cluster_signals(cluster_id=cluster_uuid)
    safe_limit = max(1, min(limit, 50))
    top_signals = all_signals[:safe_limit]

    result = {
        "topic_id": str(cluster_uuid),
        "total_signals": len(all_signals),
        "returned_signals": len(top_signals),
        "signals": [
            {
                "platform": s.platform.value if hasattr(s.platform, "value") else str(s.platform),
                "title": s.raw_title,
                "metric_value": s.metric_value,
                "growth_velocity": s.growth_velocity,
                "source_url": s.source_url,
                "captured_at": s.captured_at.isoformat() if s.captured_at else None,
                "metadata": {
                    k: v for k, v in s.metadata.items() if k in ["channel_title", "channel", "views", "likes", "published_at"]
                },
            }
            for s in top_signals
        ]
    }
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_generate_trend_artifact(
    topic_id: str = "",
    geo: str = "VN",
) -> str:
    from pathlib import Path
    comp = get_components()
    builder = comp["artifact_builder"]
    geo_val = GeoCode(geo.upper()) if geo.upper() in GeoCode._value2member_map_ else GeoCode.VN
    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    if not topic_id.strip():
        clusters = await comp["top_clusters_use_case"].execute(geo=geo_val, limit=10)
        html_content = builder.build_dashboard_artifact(clusters, geo=geo_val)
        report_file = reports_dir / f"trend_dashboard_{geo_val.value.lower()}.html"
        report_file.write_text(html_content, encoding="utf-8")
        abs_path = str(report_file.resolve())
        return json.dumps(
            {
                "status": "SUCCESS",
                "type": "DASHBOARD",
                "total_clusters": len(clusters),
                "artifact_file": abs_path,
                "file_url": f"file://{abs_path}",
                "message": f"Dashboard xu hướng đã được xuất ra: file://{abs_path}",
            },
            ensure_ascii=False,
            indent=2
        )
    else:
        try:
            cluster_uuid = UUID(topic_id.strip())
        except (ValueError, AttributeError):
            return json.dumps({"error": "Định dạng Topic ID không hợp lệ."}, ensure_ascii=False)

        signals = await comp["repository"].get_cluster_signals(cluster_id=cluster_uuid)
        cluster_info = await comp["top_clusters_use_case"].execute(geo=geo_val, limit=50)
        target_cluster = next((c for c in cluster_info if c.id == cluster_uuid), None)
        if not target_cluster and signals:
            formed = await comp["clusterer"].cluster_signals(signals)
            target_cluster = formed[0] if formed else None

        if target_cluster:
            html_content = builder.build_topic_card_artifact(target_cluster, signals)
            report_file = reports_dir / f"topic_{str(cluster_uuid)[:8]}.html"
            report_file.write_text(html_content, encoding="utf-8")
            abs_path = str(report_file.resolve())
            return json.dumps(
                {
                    "status": "SUCCESS",
                    "type": "TOPIC_CARD",
                    "topic_name": target_cluster.canonical_name,
                    "artifact_file": abs_path,
                    "file_url": f"file://{abs_path}",
                    "message": f"Topic Card đã được xuất ra: file://{abs_path}",
                },
                ensure_ascii=False,
                indent=2
            )
        return json.dumps({"error": "Không tìm thấy chủ đề yêu cầu."}, ensure_ascii=False)


async def handle_trigger_ingress_refresh(geo: str = "VN") -> str:
    comp = get_components()
    geo_val = GeoCode(geo.upper()) if geo.upper() in GeoCode._value2member_map_ else GeoCode.VN

    signals = await comp["registry"].fetch_from_all(geo=geo_val)
    clusters = await comp["cluster_use_case"].execute(signals)

    return json.dumps(
        {
            "status": "success",
            "geo": geo_val.value,
            "total_signals_fetched": len(signals),
            "total_clusters_formed": len(clusters),
        },
        ensure_ascii=False,
        indent=2,
    )


# --- MCP Tools Exposure ---

@mcp.tool(name="run_autonomous_research_mission", description="Chạy trọn gói Agent Harness: Tự động khởi tạo mission, chạy Refinement Loop tối ưu dữ liệu, chấm điểm Scorecard và bóc tách cơ hội thị trường (White Spaces).")
async def run_autonomous_research_mission(
    topic: str,
    keywords: List[str],
    geo: str = "VN",
    timeframe: str = "7d",
    min_signals: int = 15,
) -> str:
    return await handle_run_autonomous_research_mission(topic, keywords, geo, timeframe, min_signals)


@mcp.tool(name="evaluate_mission_quality", description="Chấm điểm chất lượng dữ liệu (Coverage, Freshness, Language Accuracy, Confidence Score) cho một Research Mission.")
async def evaluate_mission_quality(mission_id: str) -> str:
    return await handle_evaluate_mission_quality(mission_id)


@mcp.tool(name="discover_market_opportunities", description="Bóc tách khoảng trống thị trường (White Spaces: Nhu cầu tìm kiếm cao nhưng nguồn cung nội dung thấp) và gợi ý chiến lược.")
async def discover_market_opportunities(mission_id: str) -> str:
    return await handle_discover_market_opportunities(mission_id)


@mcp.tool(name="create_research_mission", description="Tạo một bài toán nghiên cứu xu hướng đa kênh theo chủ đề và từ khóa cụ thể.")
async def create_research_mission(
    topic: str,
    keywords: List[str],
    platforms: Optional[List[str]] = None,
    geo: str = "VN",
    timeframe: str = "7d",
) -> str:
    return await handle_create_research_mission(topic, keywords, platforms, geo, timeframe)


@mcp.tool(name="execute_mission_ingress", description="Kích hoạt cào sâu dữ liệu đa kênh cho một Research Mission.")
async def execute_mission_ingress(mission_id: str) -> str:
    return await handle_execute_mission_ingress(mission_id)


@mcp.tool(name="get_mission_analysis", description="Lấy dữ liệu phân tích tóm tắt & Top tín hiệu nổi bật của một Research Mission (Tối ưu token, không làm tràn context).")
async def get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    return await handle_get_mission_analysis(mission_id=mission_id, limit=limit, platform=platform)


@mcp.tool(name="generate_mission_artifact", description="Sinh báo cáo HTML Infographic Canvas hoàn chỉnh cho một Mission (Lưu ra thư mục reports/, trả về đường dẫn file và tóm tắt JSON siêu nhẹ an toàn token 100%).")
async def generate_mission_artifact(mission_id: str) -> str:
    return await handle_generate_mission_artifact(mission_id)


@mcp.tool(name="list_research_missions", description="Liệt kê danh sách các chiến dịch / bài toán nghiên cứu xu hướng đã thực hiện.")
async def list_research_missions(limit: int = 10) -> str:
    return await handle_list_research_missions(limit)


@mcp.tool(name="diagnose_system_health", description="Chẩn đoán sức khỏe hệ thống, trạng thái Circuit Breaker 5 kênh và gợi ý cách fix lỗi tự động.")
async def diagnose_system_health() -> str:
    return await handle_diagnose_system_health()


@mcp.tool(name="get_system_logs", description="Truy vấn danh sách Audit Logs và vết lỗi gần nhất trong Database để phân tích và debug.")
async def get_system_logs(level: Optional[str] = "ERROR", component: Optional[str] = None, limit: int = 20) -> str:
    return await handle_get_system_logs(level=level, component=component, limit=limit)


@mcp.tool(name="get_trending_topics", description="Truy vấn danh sách các chủ đề xu hướng nóng nhất đa nền tảng.")
async def get_trending_topics(geo: str = "VN", timeframe: str = "24h", limit: int = 10) -> str:
    return await handle_get_trending_topics(geo=geo, timeframe=timeframe, limit=limit)


@mcp.tool(name="get_topic_detail", description="Lấy lịch sử tín hiệu đa kênh và metrics của một chủ đề xu hướng (Tối ưu token, limit 20).")
async def get_topic_detail(topic_id: str, limit: int = 20) -> str:
    return await handle_get_topic_detail(topic_id=topic_id, limit=limit)


@mcp.tool(name="generate_trend_artifact", description="Sinh Single-File HTML Artifact (Tailwind + Chart.js) pixel-perfect 100%.")
async def generate_trend_artifact(topic_id: str = "", geo: str = "VN") -> str:
    return await handle_generate_trend_artifact(topic_id=topic_id, geo=geo)


@mcp.tool(name="trigger_ingress_refresh", description="Kích hoạt tiến trình cào dữ liệu Ingress ETL và gom cụm tức thì (Zero-Token).")
async def trigger_ingress_refresh(geo: str = "VN") -> str:
    return await handle_trigger_ingress_refresh(geo=geo)


if __name__ == "__main__":
    mcp.run()


async def handle_get_current_session_mission(session_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(session_id)
    if not mission:
        return json.dumps({"status": "not_found", "message": f"Không tìm thấy mission nào gắn với SessionID '{session_id}'"}, ensure_ascii=False)

    return json.dumps(
        {
            "status": "found",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "display_label": f"[{mission.shortcode}] {mission.title}",
            "title": mission.title,
            "keywords": mission.keywords,
            "agent": mission.agent,
            "session_id": mission.session_id,
            "created_at": mission.created_at.isoformat() if mission.created_at else None,
        },
        ensure_ascii=False,
        indent=2
    )

@mcp.tool(name="get_current_session_mission", description="Tự động khôi phục và lấy thông tin Mission gắn liền với phiên chat / SessionID hiện tại.")
async def get_current_session_mission(session_id: str) -> str:
    return await handle_get_current_session_mission(session_id=session_id)
