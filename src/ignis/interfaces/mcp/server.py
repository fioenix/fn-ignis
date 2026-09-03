import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
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
from ignis.application.use_cases.autonomous_discovery import AutonomousDiscoveryUseCase
from ignis.application.ports.repository_port import ITrendRepository

from ignis.config import settings

from ignis.domain.value_objects import (
    GeoCode,
    PlatformType,
    resolve_geo,
    resolve_platform,
    resolve_timeframe,
    timeframe_to_days,
)

from ignis.infrastructure.auth.meta_oauth import InstagramAuthManager, ThreadsAuthManager
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.refinement_orchestrator import AutonomousRefinementOrchestrator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

logger = logging.getLogger("ignis.mcp")

SOP_SYSTEM_INSTRUCTIONS = """
You are the fn-ignis Trend Intelligence & Market Opportunity Agent.
When conducting any market research, niche analysis, or trend discovery task, you MUST STRICTLY FOLLOW the 6-Step Standard Operating Procedure (SOP):

1. Step 1 (Clarify Objectives & Core Hypothesis):
   Establish clear, falsifiable hypotheses. Identify vertical (Fashion, Crypto, Healthcare, Logistics) and call `register_domain_lexicon(domain="...", terms=[...])` to expand the Quality Gate's domain vocabulary dynamically before deep crawling.

2. Step 2 (Macro Scan & Real-World Keyword Expansion):
   Call `get_tiktok_creative_center_trends` and `get_tiktok_search_suggestions` to uncover actual slang, tool names, and sub-niches being searched by users in target geo before deep crawling.

3. Step 3 (Deep Ingress & Quality Gate):
   Call `execute_mission_ingress` for deep multi-platform ingestion. Ensure strict date windowing and noise filtering (>=70% confidence).

4. Step 4 (Single-Source 4-Lens Breakdown):
   - Google Lens: Macro search demand velocity and growth.
   - YouTube Lens: Long-form supply, case study and tutorial depth.
   - TikTok Search Lens: Micro short-form intent and trending hashtags.
   - Voice of Customer Lens: Real objections, pricing questions, unmet needs from comments via `extract_customer_pain_points`.

5. Step 5 (Cross-Source Synthesis & White Space Matrix):
   Correlate Demand vs. Supply, compute Opportunity Index (+100 to -100), identify HIGH_DEMAND_LOW_SUPPLY opportunities, and determine Trend Maturity Stage.

6. Step 6 (Strategic Verdict, Risks & Fast MVP Blueprint):
   Synthesize 3-5 market truths, evaluate entry risks/moats (why hasn't this been built?), formulate a 3-7 day low-cost MVP validation plan, and generate a full interactive Infographic HTML Dashboard via `generate_mission_artifact`.
"""

# Initialize FastMCP Server with System Instructions
mcp = FastMCP("fn-ignis-trend-intelligence", instructions=SOP_SYSTEM_INSTRUCTIONS)



def _init_components():
    repository = create_repository()
    tiktok_auth_manager = TikTokAuthManager(repository=repository)
    threads_auth_manager = ThreadsAuthManager(repository=repository)
    instagram_auth_manager = InstagramAuthManager(repository=repository)
    creative_center_plugin = TikTokCreativeCenterPlugin(auth_manager=tiktok_auth_manager)

    registry = ConnectorPluginRegistry(repository=repository)
    registry.register(GoogleTrendsRssPlugin())
    registry.register(TikTokPlugin(auth_manager=tiktok_auth_manager))
    registry.register(creative_center_plugin)
    registry.register(ThreadsPlugin(auth_manager=threads_auth_manager))
    registry.register(ReelsPlugin(auth_manager=instagram_auth_manager))

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
    autonomous_discovery_use_case = AutonomousDiscoveryUseCase(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        quality_evaluator=quality_evaluator,
        strategic_reasoner=strategic_reasoner,
        artifact_builder=artifact_builder,
    )

    return {
        "repository": repository,
        "registry": registry,
        "tiktok_auth_manager": tiktok_auth_manager,
        "threads_auth_manager": threads_auth_manager,
        "instagram_auth_manager": instagram_auth_manager,
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
        "autonomous_discovery_use_case": autonomous_discovery_use_case,
    }

_COMPONENTS = None

def get_components():
    global _COMPONENTS
    if _COMPONENTS is None:
        _COMPONENTS = _init_components()
    return _COMPONENTS


async def _sync_lexicons_from_db(comp: Dict[str, Any]) -> None:
    """Sync dynamic positive lexicons, foreign stopwords, and noise blacklist from DB into reasoning engines."""
    try:
        db_lexicons = await comp["repository"].get_domain_lexicons()
        pos_terms = [item["term"] for item in db_lexicons if item.get("domain") not in ("foreign_stopwords", "noise_blacklist")]
        stop_terms = [item["term"] for item in db_lexicons if item.get("domain") == "foreign_stopwords"]
        noise_terms = [item["term"] for item in db_lexicons if item.get("domain") == "noise_blacklist"]
        
        if pos_terms:
            comp["quality_evaluator"].register_terms(pos_terms)
            comp["strategic_reasoner"].register_terms(pos_terms)
        if stop_terms:
            comp["quality_evaluator"].register_foreign_stopwords(stop_terms)
            comp["strategic_reasoner"].register_foreign_stopwords(stop_terms)
        if noise_terms:
            comp["quality_evaluator"].register_noise_blacklist(noise_terms)
            comp["strategic_reasoner"].register_noise_blacklist(noise_terms)
    except Exception as e:
        logger.warning(f"Could not sync dynamic lexicons from DB: {e}")


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
    """Run end-to-end Harness: Mission initialization, refinement loop, quality evaluation, and strategic analysis."""
    comp = get_components()
    await _sync_lexicons_from_db(comp)
    geo_val = resolve_geo(geo)



    # 1. Initialize Mission
    mission = await comp["create_mission_use_case"].execute(
        title=topic,
        keywords=keywords,
        agent=agent,
        session_id=session_id,
        geo=geo_val,
        timeframe=timeframe,
    )

    # 2. Execute Harness Orchestrator
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
    await _sync_lexicons_from_db(comp)
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission with ID/shortcode '{mission_id}' not found."}, ensure_ascii=False)
    m_id = mission.id

    signals = await comp["repository"].get_mission_signals(m_id)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)

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
    await _sync_lexicons_from_db(comp)
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission with ID/shortcode '{mission_id}' not found."}, ensure_ascii=False)
    m_id = mission.id


    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
    
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
    repo: ITrendRepository = comp["repository"]

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
            diagnostics["recommendations"].append("TikTok connector throttled or challenged by bot detection. Launch Playwright authentication or refresh cookies.")
        elif plat in ["threads", "reels"] and info["circuit_state"] != "CLOSED":
            diagnostics["recommendations"].append(f"Meta ({plat}) requires authentication or GraphQL token verification. Check credentials.")
        elif plat == "youtube" and not settings.YOUTUBE_API_KEY:
            diagnostics["recommendations"].append("YOUTUBE_API_KEY is not configured in .env.")

    return json.dumps(diagnostics, ensure_ascii=False, indent=2)


async def handle_get_system_logs(level: Optional[str] = None, component: Optional[str] = None, limit: int = 20) -> str:
    comp = get_components()
    repo: ITrendRepository = comp["repository"]
    safe_limit = max(1, min(limit, 30))
    raw_logs = await repo.get_recent_logs(level=level, component=component, limit=safe_limit)
    
    # Sanitize log details to prevent context window bloat
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


# --- Handlers for Platform Authentication ---

async def handle_authenticate_tiktok(headless: bool = False, timeout_seconds: int = 90) -> str:
    comp = get_components()
    auth_mgr: TikTokAuthManager = comp["tiktok_auth_manager"]
    result = await auth_mgr.authenticate_interactive(headless=headless, timeout_seconds=timeout_seconds)
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_platform_auth_status() -> str:
    comp = get_components()
    repo: ITrendRepository = comp["repository"]
    creds = await repo.list_platform_credentials()
    return json.dumps(
        {
            "status": "SUCCESS",
            "platforms": creds,
            "count": len(creds),
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_clear_platform_auth(platform: str) -> str:
    comp = get_components()
    repo: ITrendRepository = comp["repository"]
    success = await repo.delete_platform_credentials(platform.lower())
    return json.dumps(
        {
            "platform": platform.lower(),
            "cleared": success,
            "message": f"Cleared authentication session for {platform}." if success else f"No active session found for {platform}."
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_authenticate_threads(
    auth_code: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> str:
    comp = get_components()
    auth_mgr: ThreadsAuthManager = comp["threads_auth_manager"]
    try:
        result = await auth_mgr.exchange_code_for_token(
            auth_code=auth_code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        result = {
            "success": False,
            "platform": ThreadsAuthManager.PLATFORM_NAME,
            "error_type": type(e).__name__,
            "message": str(e),
        }
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_threads_auth_status() -> str:
    comp = get_components()
    auth_mgr: ThreadsAuthManager = comp["threads_auth_manager"]
    status = await auth_mgr.get_auth_status()
    return json.dumps(status, ensure_ascii=False, indent=2)


async def handle_clear_threads_auth() -> str:
    comp = get_components()
    auth_mgr: ThreadsAuthManager = comp["threads_auth_manager"]
    cleared = await auth_mgr.clear_auth()
    return json.dumps(
        {
            "platform": ThreadsAuthManager.PLATFORM_NAME,
            "cleared": cleared,
            "message": "Threads OAuth credentials revoked."
            if cleared else "No active Threads OAuth session found.",
        },
        ensure_ascii=False,
        indent=2,
    )


# --- Handlers for Research Missions ---

async def handle_create_research_mission(
    title: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    topic: Optional[str] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    geo: str = "VN",
    timeframe: str = "7d",
) -> str:
    comp = get_components()
    geo_val = resolve_geo(geo)
    final_title = title or topic or "Untitled Mission"
    final_keywords = keywords or []
    
    target_platforms = [resolve_platform(p) for p in platforms] if platforms else None


    mission = await comp["create_mission_use_case"].execute(
        title=final_title,
        keywords=final_keywords,
        agent=agent,
        session_id=session_id,
        platforms=target_platforms,
        geo=geo_val,
        timeframe=timeframe,
    )

    return json.dumps(
        {
            "status": "CREATED",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "display_label": f"[{mission.shortcode}] {mission.title}",
            "title": mission.title,
            "keywords": mission.keywords,
            "platforms": [p.value for p in mission.platforms],
            "geo": mission.geo_code.value,
            "timeframe": mission.timeframe,
            "tip": f"You can reference shortcode '{mission.shortcode}' or ID '{str(mission.id)[:8]}' in subsequent commands.",
            "next_step": f"Call execute_mission_ingress(mission_id='{mission.shortcode}') to trigger data ingress."
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_execute_mission_ingress(mission_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"No research mission found with ID or shortcode: '{mission_id}'"}, ensure_ascii=False)

    result = await comp["execute_mission_use_case"].execute(mission_id=mission.id)
    result["shortcode"] = mission.shortcode
    result["display_label"] = f"[{mission.shortcode}] {mission.title}" 
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    comp = get_components()
    await _sync_lexicons_from_db(comp)
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"No research mission found with ID or shortcode: '{mission_id}'"}, ensure_ascii=False)

    analysis = await comp["get_mission_analysis_use_case"].execute(
        mission_id=mission.id, 
        limit=max(1, min(limit, 50)),
        platform_filter=platform
    )
    analysis["mission"]["shortcode"] = mission.shortcode
    analysis["mission"]["display_label"] = f"[{mission.shortcode}] {mission.title}" 

    # Enrich with Scorecard & White Space discovery for in-chat Native Artifact rendering
    signals = await comp["repository"].get_mission_signals(mission.id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
    )

    analysis["quality_scorecard"] = {
        "overall_confidence": scorecard.overall_confidence,
        "confidence_level": scorecard.confidence_level.value,
        "coverage_score": scorecard.coverage_score,
        "language_precision": scorecard.language_precision,
        "data_freshness_score": scorecard.data_freshness_score,
        "creator_diversity_score": scorecard.creator_diversity_score,
        "strengths": scorecard.strengths_detected,
        "flaws": scorecard.flaws_detected,
    }
    analysis["maturity_stage"] = report.maturity_stage.value
    analysis["market_opportunities"] = [
        {
            "topic": opp.topic,
            "type": opp.opportunity_type,
            "demand_score": opp.search_interest_score,
            "supply_score": opp.content_supply_score,
            "opportunity_index": opp.opportunity_index,
            "recommendation": opp.strategic_recommendation,
            "supporting_signals": opp.supporting_signals[:2],
        }
        for opp in report.market_opportunities
    ]
    analysis["strategic_insights"] = report.strategic_insights
    analysis["actionable_takeaways"] = report.actionable_takeaways
    analysis["native_artifact_guideline"] = "Render these strategic insights directly as a visual, high-contrast Claude Native Artifact in the chat window. Only export a local HTML file when the user explicitly requests it."

    return json.dumps(analysis, ensure_ascii=False, indent=2)


def _get_secure_reports_dir() -> Path:
    # 1. Try project root reports/ directory
    try:
        project_root = Path(__file__).resolve().parents[4]
        reports_dir = project_root / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        # Test write permission
        test_file = reports_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        return reports_dir
    except Exception:
        pass

    # 2. Try ~/.ignis/reports
    try:
        home_reports = Path.home() / ".ignis" / "reports"
        home_reports.mkdir(parents=True, exist_ok=True)
        return home_reports
    except Exception:
        pass

    # 3. Fallback to temporary directory
    temp_dir = Path(tempfile.gettempdir()) / "ignis_reports"
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


async def handle_generate_mission_artifact(mission_id: str) -> str:
    comp = get_components()
    await _sync_lexicons_from_db(comp)
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"Mission with ID/shortcode '{mission_id}' not found."}, ensure_ascii=False)
    m_id = mission.id

    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)

    
    report = comp["strategic_reasoner"].analyze_mission(
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

    html_content = comp["artifact_builder"].build_mission_report_artifact(
        mission=mission,
        signals=signals,
        platform_breakdown=platform_breakdown,
        report=report,
        customer_inquiries=customer_inquiries,
        search_suggestions=[],
        macro_trends=macro_trends,
    )

    # Securely save HTML report artifact to disk
    reports_dir = _get_secure_reports_dir()
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
    geo_val = resolve_geo(geo)
    tf_val = resolve_timeframe(timeframe)

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
    comp = get_components()
    builder = comp["artifact_builder"]
    geo_val = resolve_geo(geo)
    reports_dir = _get_secure_reports_dir()

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
                "message": f"Trend dashboard exported to: file://{abs_path}",
            },
            ensure_ascii=False,
            indent=2
        )
    else:
        try:
            cluster_uuid = UUID(topic_id.strip())
        except (ValueError, AttributeError):
            return json.dumps({"error": "Invalid Topic ID format."}, ensure_ascii=False)

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
                    "message": f"Topic card exported to: file://{abs_path}",
                },
                ensure_ascii=False,
                indent=2
            )
        return json.dumps({"error": "Requested topic not found."}, ensure_ascii=False)


async def handle_trigger_ingress_refresh(geo: str = "VN") -> str:
    comp = get_components()
    geo_val = resolve_geo(geo)

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


async def handle_get_current_session_mission(session_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(session_id)
    if not mission:
        return json.dumps({"status": "not_found", "message": f"No research mission found for session ID '{session_id}'"}, ensure_ascii=False)

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


# --- MCP Tools Exposure ---

@mcp.tool(name="run_autonomous_research_mission", description="Run an end-to-end autonomous research mission: create mission, execute refinement loop, evaluate quality scorecard, and discover market white spaces.")
async def run_autonomous_research_mission(
    topic: str,
    keywords: List[str],
    geo: str = "VN",
    timeframe: str = "7d",
    min_signals: int = 15,
) -> str:
    return await handle_run_autonomous_research_mission(topic, keywords, geo, timeframe, min_signals)


@mcp.tool(name="evaluate_mission_quality", description="Evaluate multi-dimensional data quality and integrity (Coverage, Freshness, Language Accuracy, Confidence Score) for a research mission.")
async def evaluate_mission_quality(mission_id: str) -> str:
    return await handle_evaluate_mission_quality(mission_id)


@mcp.tool(name="discover_market_opportunities", description="Identify high-demand, low-supply market white spaces and provide actionable strategic recommendations.")
async def discover_market_opportunities(mission_id: str) -> str:
    return await handle_discover_market_opportunities(mission_id)


@mcp.tool(name="create_research_mission", description="Create a targeted cross-platform trend research mission with specified keywords, platforms, geo, and timeframe.")
async def create_research_mission(
    topic: str,
    keywords: List[str],
    platforms: Optional[List[str]] = None,
    geo: str = "VN",
    timeframe: str = "7d",
) -> str:
    return await handle_create_research_mission(topic, keywords, platforms, geo, timeframe)


@mcp.tool(name="execute_mission_ingress", description="Trigger deep multi-platform data collection and clustering for a research mission (idempotent replace mode).")
async def execute_mission_ingress(mission_id: str) -> str:
    return await handle_execute_mission_ingress(mission_id)


@mcp.tool(name="get_mission_analysis", description="Retrieve full strategic analysis payload (Scorecard, 10 White Spaces, Insights, Action Plan, Top Signals) for in-chat Native Artifact rendering.")
async def get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    return await handle_get_mission_analysis(mission_id=mission_id, limit=limit, platform=platform)


@mcp.tool(name="generate_mission_artifact", description="Export a standalone Infographic Canvas HTML report to local disk (reports/ folder). Use ONLY when the user explicitly requests an exported HTML file.")
async def generate_mission_artifact(mission_id: str) -> str:
    return await handle_generate_mission_artifact(mission_id)


@mcp.tool(name="list_research_missions", description="List recent trend research missions and tracking campaigns.")
async def list_research_missions(limit: int = 10) -> str:
    return await handle_list_research_missions(limit)


@mcp.tool(name="diagnose_system_health", description="Inspect system health, connector circuit breaker states, and automated remediation suggestions.")
async def diagnose_system_health() -> str:
    return await handle_diagnose_system_health()


@mcp.tool(name="get_system_logs", description="Query recent system audit logs and error traces from the database for debugging.")
async def get_system_logs(level: Optional[str] = "ERROR", component: Optional[str] = None, limit: int = 20) -> str:
    return await handle_get_system_logs(level=level, component=component, limit=limit)


@mcp.tool(name="get_trending_topics", description="Fetch top cross-platform trending topic clusters ranked by momentum velocity.")
async def get_trending_topics(geo: str = "VN", timeframe: str = "24h", limit: int = 10) -> str:
    return await handle_get_trending_topics(geo=geo, timeframe=timeframe, limit=limit)


@mcp.tool(name="get_topic_detail", description="Retrieve time-series signals and engagement metrics for a specific topic cluster (token-optimized).")
async def get_topic_detail(topic_id: str, limit: int = 20) -> str:
    return await handle_get_topic_detail(topic_id=topic_id, limit=limit)


@mcp.tool(name="generate_trend_artifact", description="Generate a standalone single-file HTML dashboard or topic card artifact (Tailwind + Chart.js).")
async def generate_trend_artifact(topic_id: str = "", geo: str = "VN") -> str:
    return await handle_generate_trend_artifact(topic_id=topic_id, geo=geo)


@mcp.tool(name="trigger_ingress_refresh", description="Trigger immediate multi-platform ETL trend ingestion and clustering (zero-token background).")
async def trigger_ingress_refresh(geo: str = "VN") -> str:
    return await handle_trigger_ingress_refresh(geo=geo)


@mcp.tool(name="get_current_session_mission", description="Automatically retrieve the research mission associated with the current session ID or chat thread.")
async def get_current_session_mission(session_id: str) -> str:
    return await handle_get_current_session_mission(session_id=session_id)


@mcp.tool(name="authenticate_tiktok", description="Launch 1-Click interactive TikTok login (QR Code / Managed browser) to capture and persist session credentials.")
async def authenticate_tiktok(headless: bool = False, timeout_seconds: int = 90) -> str:
    return await handle_authenticate_tiktok(headless=headless, timeout_seconds=timeout_seconds)


@mcp.tool(name="get_platform_auth_status", description="Check connection status and active credentials across social platforms (TikTok, Threads, Reels).")
async def get_platform_auth_status() -> str:
    return await handle_get_platform_auth_status()


@mcp.tool(name="clear_platform_auth", description="Disconnect or remove stored session credentials for a specific platform.")
async def clear_platform_auth(platform: str) -> str:
    return await handle_clear_platform_auth(platform=platform)


@mcp.tool(name="authenticate_threads", description="Complete the official Meta Threads Graph API OAuth 2.0 flow: exchange an authorization code for a short-lived token, upgrade it to a 60-day long-lived user token, and persist it AES-encrypted.")
async def authenticate_threads(
    auth_code: str,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
) -> str:
    return await handle_authenticate_threads(
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )


@mcp.tool(name="get_threads_auth_status", description="Inspect the stored Meta Threads OAuth 2.0 token: active/expired state, granted scopes, key version, days remaining, and whether a refresh is due.")
async def get_threads_auth_status() -> str:
    return await handle_get_threads_auth_status()


@mcp.tool(name="clear_threads_auth", description="Revoke and delete the stored Meta Threads OAuth 2.0 credentials from local encrypted storage.")
async def clear_threads_auth() -> str:
    return await handle_clear_threads_auth()


async def handle_get_tiktok_search_suggestions(keywords: List[str], geo: str = "VN") -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    try:
        suggestions = await comp["registry"].fetch_suggestions_across_all(
            keywords=keywords,
            geo=geo_code,
            target_platforms=[PlatformType.TIKTOK],
        )
        return json.dumps(
            {
                "status": "SUCCESS",
                "total_keywords": len(keywords),
                "data": suggestions,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching TikTok search suggestions: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_tiktok_search_suggestions", description="Fetch real-time derivative search suggestions / autocomplete queries from TikTok for market demand analysis.")
async def get_tiktok_search_suggestions(keywords: list[str], geo: str = "VN") -> str:
    return await handle_get_tiktok_search_suggestions(keywords=keywords, geo=geo)


async def handle_get_tiktok_creative_center_trends(geo: str = "VN", period: int = 7, limit: int = 20, industry: Optional[str] = None) -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    safe_limit = max(1, min(limit, 50))
    safe_period = 30 if period >= 30 else 7

    # Locate TikTok Creative Center plugin
    cc_plugin = None
    for _, plugin in comp["registry"]._plugins.items():
        if isinstance(plugin, TikTokCreativeCenterPlugin):
            cc_plugin = plugin
            break

    if not cc_plugin:
        cc_plugin = TikTokCreativeCenterPlugin(auth_manager=comp.get("tiktok_auth_manager"))

    try:
        trends = await cc_plugin.fetch_macro_trends(geo=geo_code, period=safe_period, limit=safe_limit, industry=industry)
        return json.dumps(
            {
                "status": "SUCCESS",
                "geo_code": geo_code.value,
                "period_days": safe_period,
                "industry_filter": industry,
                "total_hashtags": len(trends),
                "trending_hashtags": trends,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching TikTok Creative Center trends: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_tiktok_creative_center_trends", description="Fetch top macro trending hashtags, views, and industry categories from TikTok Creative Center with optional industry filtering (e.g. 'tech', 'software', 'education', 'ecommerce').")
async def get_tiktok_creative_center_trends(geo: str = "VN", period: int = 7, limit: int = 20, industry: Optional[str] = None) -> str:
    return await handle_get_tiktok_creative_center_trends(geo=geo, period=period, limit=limit, industry=industry)


async def handle_get_tiktok_video_comments(video_url: str, limit: int = 30) -> str:
    comp = get_components()
    tiktok_plugin = None
    for _, plugin in comp["registry"]._plugins.items():
        if isinstance(plugin, TikTokPlugin):
            tiktok_plugin = plugin
            break

    if not tiktok_plugin:
        tiktok_plugin = TikTokPlugin(auth_manager=comp.get("tiktok_auth_manager"))

    try:
        comments = await tiktok_plugin.fetch_video_comments(video_url=video_url, limit=limit)
        return json.dumps(
            {
                "status": "SUCCESS",
                "video_url": video_url,
                "total_comments": len(comments),
                "comments": comments,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching TikTok video comments {video_url}: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_tiktok_video_comments", description="Fetch real-time public comments, inquiries, and discussions under a specific TikTok video URL.")
async def get_tiktok_video_comments(video_url: str, limit: int = 30) -> str:
    return await handle_get_tiktok_video_comments(video_url=video_url, limit=limit)


async def handle_extract_customer_pain_points(
    keywords: List[str],
    geo: str = "VN",
    max_videos: int = 3,
    inquiry_patterns: Optional[List[str]] = None,
) -> str:
    comp = get_components()
    geo_code = GeoCode(geo.upper())
    tiktok_plugin = None
    for _, plugin in comp["registry"]._plugins.items():
        if isinstance(plugin, TikTokPlugin):
            tiktok_plugin = plugin
            break

    if not tiktok_plugin:
        tiktok_plugin = TikTokPlugin(auth_manager=comp.get("tiktok_auth_manager"))

    try:
        data = await tiktok_plugin.fetch_top_comments_for_keywords(
            keywords=keywords,
            geo=geo_code,
            max_videos=max_videos,
            limit_per_video=20,
        )
        
        # Multi-language baseline inquiry triggers
        default_triggers = [
            "?", "how", "what", "why", "price", "cost", "where", "help", "issue", "bug", "fail", "problem", "review",
            "làm sao", "như thế nào", "giá", "bao nhiêu", "xin", "hướng dẫn", "ở đâu", "mua", "dùng được", "test", "lỗi"
        ]
        active_triggers = [t.lower() for t in (inquiry_patterns or default_triggers)]

        # Extract inquiries and top engaged comments
        all_comments = []
        inquiries = []
        for v in data:
            for c in v.get("comments", []):
                txt = c.get("text", "")
                all_comments.append(txt)
                if any(q in txt.lower() for q in active_triggers):
                    inquiries.append({
                        "video_title": v.get("video_title"),
                        "author": c.get("author"),
                        "inquiry": txt,
                        "likes": c.get("likes", 0),
                    })

        return json.dumps(
            {
                "status": "SUCCESS",
                "keywords": keywords,
                "geo": geo_code.value,
                "total_videos_analyzed": len(data),
                "total_comments_extracted": len(all_comments),
                "top_inquiries_and_pain_points": inquiries[:20],
                "videos_breakdown": data,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error extracting customer pain points from TikTok: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="extract_customer_pain_points", description="Extract voice of customer, frequent inquiries, and unmet needs across top TikTok videos for specific market keywords and target geography.")
async def extract_customer_pain_points(
    keywords: list[str],
    geo: str = "VN",
    max_videos: int = 3,
    inquiry_patterns: Optional[list[str]] = None,
) -> str:
    return await handle_extract_customer_pain_points(
        keywords=keywords,
        geo=geo,
        max_videos=max_videos,
        inquiry_patterns=inquiry_patterns,
    )



async def handle_trigger_autonomous_discovery(geo: str = "VN") -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    try:
        result = await comp["autonomous_discovery_use_case"].execute(geo=geo_code)
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error during autonomous discovery cycle: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="trigger_autonomous_discovery", description="Trigger an on-demand end-to-end autonomous discovery cycle to uncover top daily white space opportunities.")
async def trigger_autonomous_discovery(geo: str = "VN") -> str:
    return await handle_trigger_autonomous_discovery(geo=geo)


async def handle_get_latest_daily_discovery(geo: str = "VN") -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    missions = await comp["repository"].list_missions(limit=30)
    
    # Filter for discovery missions
    discovery_missions = [m for m in missions if m.shortcode and m.shortcode.startswith(f"DISCOVERY-{geo_code.value}")]
    if not discovery_missions:
        return json.dumps({"status": "INFO", "message": f"No autonomous discovery runs recorded yet for {geo_code.value}."}, ensure_ascii=False)

    latest = discovery_missions[0]
    return await handle_get_mission_analysis(str(latest.id))


@mcp.tool(name="get_latest_daily_discovery", description="Retrieve the latest daily automated market discovery digest and opportunity rankings.")
async def get_latest_daily_discovery(geo: str = "VN") -> str:
    return await handle_get_latest_daily_discovery(geo=geo)


async def handle_register_domain_lexicon(
    domain: str,
    terms: list[str],
    category: str = "vernacular",
    created_by: str = "agent",
) -> str:
    comp = get_components()
    try:
        saved_count = await comp["repository"].register_lexicon_terms(
            domain=domain,
            terms=terms,
            category=category,
            created_by=created_by,
        )
        # Update in-memory quality evaluator & strategic reasoner caches
        d_lower = domain.lower()
        if d_lower in ("noise_blacklist", "noise", "negative_keywords"):
            if "quality_evaluator" in comp:
                comp["quality_evaluator"].register_noise_blacklist(terms)
            if "strategic_reasoner" in comp:
                comp["strategic_reasoner"].register_noise_blacklist(terms)
        elif d_lower == "foreign_stopwords":
            if "quality_evaluator" in comp:
                comp["quality_evaluator"].register_foreign_stopwords(terms)
            if "strategic_reasoner" in comp:
                comp["strategic_reasoner"].register_foreign_stopwords(terms)
        else:
            if "quality_evaluator" in comp:
                comp["quality_evaluator"].register_terms(terms)
            if "strategic_reasoner" in comp:
                comp["strategic_reasoner"].register_terms(terms)

        return json.dumps(
            {
                "status": "SUCCESS",
                "domain": domain.lower(),
                "terms_registered": len(terms),
                "saved_count": saved_count,
                "message": f"Successfully registered {len(terms)} lexicon terms for domain '{domain}'.",
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error registering domain lexicon: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="register_domain_lexicon", description="Register or expand domain vocabulary, slang, brand names, and industry keywords dynamically into the persistent database so Quality Gate and Ingress engines recognize new niche vernacular.")
async def register_domain_lexicon(domain: str, terms: list[str], category: str = "vernacular") -> str:
    return await handle_register_domain_lexicon(domain=domain, terms=terms, category=category)


@mcp.tool(name="register_noise_blacklist", description="Register or expand negative keywords, generic social noise, and entertainment hashtags dynamically into the persistent database so Quality Gate filters out non-strategic signals.")
async def register_noise_blacklist(terms: list[str]) -> str:
    return await handle_register_domain_lexicon(domain="noise_blacklist", terms=terms, category="generic_noise")



async def handle_list_domain_lexicons(domain: Optional[str] = None) -> str:
    comp = get_components()
    try:
        lexicons = await comp["repository"].get_domain_lexicons(domain=domain)
        taxonomies = await comp["repository"].get_industry_taxonomies()
        return json.dumps(
            {
                "status": "SUCCESS",
                "total_lexicon_terms": len(lexicons),
                "domain_filter": domain,
                "lexicons": lexicons,
                "industry_taxonomies": taxonomies,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error listing domain lexicons: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="list_domain_lexicons", description="List active domain vocabularies, slang terms, and industry mappings currently loaded in the system.")
async def list_domain_lexicons(domain: Optional[str] = None) -> str:
    return await handle_list_domain_lexicons(domain=domain)


async def handle_verify_connectors_health() -> str:
    """
    Run active diagnostic probes across all multi-platform ingress connectors and infrastructure:
    - YouTube Data API v3 (API Key & Quota verification)
    - Google Trends RSS (Feed responsiveness & parsing)
    - TikTok Connectors & Playwright (Browser engine & optional proxy routing)
    - PostgreSQL / TimescaleDB (Connection pool & lexicon registry counts)
    """
    comp = get_components()
    repo = comp["repository"]
    registry = comp["registry"]

    diagnostics: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "proxy_configured": bool(settings.PLAYWRIGHT_PROXY_SERVER),
        "proxy_server": settings.PLAYWRIGHT_PROXY_SERVER if settings.PLAYWRIGHT_PROXY_SERVER else "Direct (No Proxy)",
        "connectors": {},
        "database": {},
        "overall_status": "HEALTHY",
    }

    # 1. Database Probe
    try:
        lexicons = await repo.get_domain_lexicons()
        diagnostics["database"] = {
            "status": "HEALTHY",
            "active_lexicons_count": len(lexicons),
            "storage": "PostgreSQL / TimescaleDB",
        }
    except Exception as e:
        diagnostics["database"] = {
            "status": "UNHEALTHY",
            "error": str(e)
        }
        diagnostics["overall_status"] = "DEGRADED"

    # 2. Check each connector plugin
    for plugin_id, plugin in registry._plugins.items():
        platform_value = plugin.platform.value if hasattr(plugin.platform, "value") else str(plugin.platform)
        try:
            is_ok = await plugin.is_healthy()
            diagnostics["connectors"][plugin.name] = {
                "plugin_id": plugin_id,
                "platform": platform_value,
                "status": "HEALTHY" if is_ok else "UNHEALTHY",
            }
            if not is_ok:
                diagnostics["overall_status"] = "DEGRADED"
        except Exception as e:
            diagnostics["connectors"][plugin.name] = {
                "plugin_id": plugin_id,
                "platform": platform_value,
                "status": "ERROR",
                "error": str(e)
            }
            diagnostics["overall_status"] = "DEGRADED"

    return json.dumps(diagnostics, ensure_ascii=False, indent=2)


@mcp.tool(name="verify_connectors_health", description="Run synthetic diagnostic health checks across all multi-platform connectors, database, and proxy.")
async def verify_connectors_health() -> str:
    """Run synthetic diagnostic health checks across all multi-platform connectors, database, and proxy."""
    return await handle_verify_connectors_health()





# ==============================================================================
# MCP RESOURCES & PROMPTS
# ==============================================================================

@mcp.resource("fn-ignis://sop/market-research")
def get_market_research_sop_resource() -> str:
    """Full documentation of the fn-ignis 6-Step Market Research Standard Operating Procedure (SOP)."""
    return SOP_SYSTEM_INSTRUCTIONS


@mcp.resource("fn-ignis://methodology/opportunity-index")
def get_opportunity_index_methodology() -> str:
    """Methodology and mathematical formulation for the Opportunity Index (Demand vs. Supply Matrix)."""
    return """
# Opportunity Index Methodology
Opportunity Index (OI) = Search Demand Score (0-100) - Localized Content Supply Score (0-100).
- Range: -100 to +100.
- OI >= +30: HIGH_DEMAND_LOW_SUPPLY (Prime White Space Opportunity).
- OI between -20 and +29: MODERATE_COMPETITION / BALANCED_MARKET.
- OI <= -30: SATURATED_SEGMENT / RED_OCEAN.
- High Enterprise Search with 0 supply: ENTERPRISE_GAP.
"""


@mcp.prompt(name="market_research_pipeline")
def prompt_market_research_pipeline(topic: str = "AI Agent", geo: str = "VN") -> str:
    """Guided prompt instructing Claude to execute the 6-Step Market Research SOP."""
    return f"""
Please execute a rigorous market intelligence and white-space discovery workflow for the topic: '{topic}' in region '{geo}'.
Strictly adhere to the 6-Step Standard Operating Procedure:
1. Clarify the business model, target audience, and establish the Core Hypothesis to validate.
2. Perform a Macro Scan using Creative Center benchmarks and real-world Autocomplete Search Suggestions to capture authentic search terms and slang.
3. Ingest deep multi-platform data (Google Trends, YouTube, TikTok) with automated noise and spam rejection (Quality Gate).
4. Conduct a Single-Source 4-Lens Breakdown (Macro Demand, Long-form Supply, Micro Intent, Voice of Customer / Pain Points).
5. Synthesize the Cross-Source Demand vs. Supply Matrix, compute the Opportunity Index, and identify HIGH_DEMAND_LOW_SUPPLY white spaces.
6. Deliver the Strategic Verdict, evaluate entry risks and competitive moats, formulate a 3-7 day fast MVP validation plan, and export the interactive Infographic HTML Dashboard Artifact.
"""


@mcp.prompt(name="voice_of_customer_audit")
def prompt_voice_of_customer_audit(keywords: str = "Chatbot AI") -> str:
    """Guided prompt to extract authentic customer voice, pain points, and objections from TikTok comments."""
    return f"""
Please extract and analyze authentic customer voice, pricing objections, technical complaints, and unmet needs for the topic '{keywords}'.
Use the `extract_customer_pain_points` tool across top market videos to synthesize the top 5 unresolved customer pain points.
"""


def main():
    """Main CLI entry point for the fn-ignis FastMCP server."""
    mcp.run()


if __name__ == "__main__":
    main()







