import json
import logging
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
from urllib.parse import urlsplit
from uuid import UUID


# Ensure MCP compatibility bridge before importing FastMCP
import mcp.shared.exceptions
if not hasattr(mcp.shared.exceptions, "McpError") and hasattr(mcp.shared.exceptions, "MCPError"):
    mcp.shared.exceptions.McpError = mcp.shared.exceptions.MCPError

from fastmcp import FastMCP

from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_mission import CreateMissionUseCase
from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
from ignis.application.use_cases.ingest_trends import MAX_TOPIC_KEYWORDS, IngestTrendsUseCase
from ignis.application.use_cases.autonomous_discovery import AutonomousDiscoveryUseCase
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.entities import TopicCluster
from ignis.domain.exceptions import IgnisDomainException
from ignis.domain.research_workspace import (
    RESEARCH_ROOT_SEGMENTS,
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    MissionLineage,
    ResearchSurface,
    opportunity_index_is_allowed,
    resolve_surface,
)
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

from ignis.config import reveal_secret, settings

from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry
from ignis.domain.token_rotation import (
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
    build_expiry_alerts,
    plan_staggered_refresh,
)
from ignis.domain.value_objects import (
    IngressTrigger,
    GeoCode,
    IngressScope,
    PlatformType,
    Timeframe,
    resolve_geo,
    resolve_platform,
    resolve_timeframe,
    timeframe_to_days,
)

from ignis.infrastructure.auth.meta_browser_auth import (
    InstagramBrowserAuthManager,
    ThreadsBrowserAuthManager,
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
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.refinement_orchestrator import AutonomousRefinementOrchestrator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

logger = logging.getLogger("ignis.mcp")

HARNESS_SYSTEM_INSTRUCTIONS = """
fn-ignis is an Autonomous Social Intelligence & Market Opportunity Agent Harness.
It equips AI agents with social listening connectors, mathematical methodologies, domain knowledge, and reporting scaffolds without constraining the agent's workflow or deliverables.

Harness Capabilities:
1. Multi-Platform Connectors & Probes: Atomic operations across Threads, TikTok, YouTube, Google Trends, and Instagram (autocomplete queries, comments, video cards, trending topics, dynamic config, auth tokens).
2. Methodology & Scoring: Mathematical formulations including Opportunity Index (Demand vs. Supply), Quality Gate (Coverage, Precision, Freshness, Diversity >= 70%), and Voice of Customer pain-point clustering.
3. Domain Knowledge & Lexicons: Dynamic domain lexicon registration, negative noise filtering, and localized language heuristics.
4. Reporting Scaffolds: Data contracts and high-contrast interactive HTML Dashboard artifacts (`generate_mission_artifact`).

Operational Flexibility:
- Agents have full autonomy to select and compose tools as needed (e.g., ad-hoc social scanning, customer pain-point auditing, or end-to-end strategic dossiers).
- The 6-Step Strategic Research Framework is provided as an analytical recipe/guideline (accessible via resource `fn-ignis://sop/market-research` or prompt `market_research_pipeline`) when a comprehensive market opportunity dossier is requested.
"""

SOP_FRAMEWORK_DOC = """
# fn-ignis 6-Step Strategic Market Research Reference Framework

This framework serves as a recommended analytical recipe when agents conduct comprehensive market opportunity and white-space discovery:

1. Step 1 (Clarify Objectives & Core Hypothesis):
   Establish clear, falsifiable hypotheses. Identify vertical (Fashion, Crypto, Healthcare, Logistics) and call `register_domain_lexicon(domain="...", terms=[...])` to expand the Quality Gate's domain vocabulary dynamically before deep crawling.

2. Step 2 (Macro Scan & Real-World Keyword Expansion):
   Call `get_tiktok_creative_center_trends`, `get_tiktok_search_suggestions`, or `get_threads_trending_topics` to uncover actual slang, tool names, and sub-niches being searched by users in target geo before deep crawling.

3. Step 3 (Deep Ingress & Quality Gate):
   Call `execute_mission_ingress` for deep multi-platform ingestion. Ensure strict date windowing and noise filtering (>=70% confidence).

4. Step 4 (Single-Source 4-Lens Breakdown):
   - Google Lens: Macro search demand velocity and growth.
   - YouTube Lens: Long-form supply, case study and tutorial depth.
   - TikTok / Threads Lens: Micro short-form intent, trending hashtags, and real-time discussions.
   - Voice of Customer Lens: Real objections, pricing questions, unmet needs from comments via `extract_customer_pain_points`.

5. Step 5 (Cross-Source Synthesis & White Space Matrix):
   Correlate Demand vs. Supply, compute Opportunity Index (+100 to -100), identify HIGH_DEMAND_LOW_SUPPLY opportunities, and determine Trend Maturity Stage.

6. Step 6 (Strategic Verdict, Risks & Fast MVP Blueprint):
   Synthesize 3-5 market truths, evaluate entry risks/moats (why hasn't this been built?), formulate a 3-7 day low-cost MVP validation plan, and generate a full interactive Infographic HTML Dashboard via `generate_mission_artifact`.
"""

# Initialize FastMCP Server with Non-Prescriptive Harness Instructions
mcp = FastMCP("fn-ignis-trend-intelligence", instructions=HARNESS_SYSTEM_INSTRUCTIONS)



def _init_components():
    repository = create_repository()
    runtime_config_manager = RuntimeConfigManager(repository=repository)
    tiktok_auth_manager = TikTokAuthManager(repository=repository)
    threads_auth_manager = ThreadsAuthManager(repository=repository)
    instagram_auth_manager = InstagramAuthManager(repository=repository)
    threads_browser_auth_manager = ThreadsBrowserAuthManager(repository=repository)
    instagram_browser_auth_manager = InstagramBrowserAuthManager(repository=repository)
    creative_center_plugin = TikTokCreativeCenterPlugin(auth_manager=tiktok_auth_manager)

    google_trends_plugin = GoogleTrendsRssPlugin()
    tiktok_plugin = TikTokPlugin(auth_manager=tiktok_auth_manager)

    registry = ConnectorPluginRegistry(repository=repository)
    registry.register(google_trends_plugin)
    registry.register(tiktok_plugin)
    registry.register(creative_center_plugin)
    registry.register(
        ThreadsPlugin(
            auth_manager=threads_auth_manager,
            browser_auth_manager=threads_browser_auth_manager,
        )
    )
    registry.register(
        ReelsPlugin(
            auth_manager=instagram_auth_manager,
            browser_auth_manager=instagram_browser_auth_manager,
        )
    )

    if reveal_secret(settings.YOUTUBE_API_KEY):
        registry.register(YouTubeDataPlugin(api_key=reveal_secret(settings.YOUTUBE_API_KEY)))

    clusterer = SemanticClusterer()
    artifact_builder = HtmlArtifactBuilder()
    # One detector, shared, so its vocabulary is loaded once rather than per engine.
    language_detector = HeuristicLanguageDetector()
    quality_evaluator = QualityEvaluator(detector=language_detector)
    strategic_reasoner = StrategicMarketReasoner(detector=language_detector)

    harness_orchestrator = AutonomousRefinementOrchestrator(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        quality_evaluator=quality_evaluator,
        strategic_reasoner=strategic_reasoner,
    )

    workspace_store = WorkspaceRepository(repository=repository)

    create_mission_use_case = CreateMissionUseCase(repository=repository)
    execute_mission_use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        workspace_store=workspace_store,
    )
    create_research_workspace_use_case = CreateResearchWorkspaceUseCase(store=workspace_store)
    create_attention_mission_use_case = CreateAttentionMissionUseCase(
        repository=repository,
        store=workspace_store,
    )
    confirm_market_brief_use_case = ConfirmMarketBriefUseCase(
        repository=repository,
        store=workspace_store,
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
        "google_trends_plugin": google_trends_plugin,
        "tiktok_plugin": tiktok_plugin,
        "language_detector": language_detector,
        "tiktok_auth_manager": tiktok_auth_manager,
        "threads_auth_manager": threads_auth_manager,
        "instagram_auth_manager": instagram_auth_manager,
        "threads_browser_auth_manager": threads_browser_auth_manager,
        "instagram_browser_auth_manager": instagram_browser_auth_manager,
        "clusterer": clusterer,
        "artifact_builder": artifact_builder,
        "quality_evaluator": quality_evaluator,
        "strategic_reasoner": strategic_reasoner,
        "harness_orchestrator": harness_orchestrator,
        "workspace_store": workspace_store,
        "create_research_workspace_use_case": create_research_workspace_use_case,
        "create_attention_mission_use_case": create_attention_mission_use_case,
        "confirm_market_brief_use_case": confirm_market_brief_use_case,
        "create_mission_use_case": create_mission_use_case,
        "execute_mission_use_case": execute_mission_use_case,
        "get_mission_analysis_use_case": get_mission_analysis_use_case,
        "top_clusters_use_case": top_clusters_use_case,
        "ingest_use_case": ingest_use_case,
        "cluster_use_case": cluster_use_case,
        "autonomous_discovery_use_case": autonomous_discovery_use_case,
        "runtime_config_manager": runtime_config_manager,
    }

_COMPONENTS = None

def get_components():
    global _COMPONENTS
    if _COMPONENTS is None:
        _COMPONENTS = _init_components()
    return _COMPONENTS


# --- Data Provenance serialization helpers ---

# A mission platform can be served by credentials stored under a different key
# (Reels rides on the Instagram session, Threads has a browser + Graph tier).
_PLATFORM_CREDENTIAL_KEYS = {
    "tiktok": ("tiktok",),
    "threads": ("threads", "threads_browser"),
    "reels": ("instagram", "instagram_browser"),
}


async def _collect_channel_context(comp: Dict[str, Any]):
    """
    Gather the auth and connector-health facts the reasoner needs to explain an
    empty channel. Returns (auth_status, connector_health); either may be None
    when the underlying source is unavailable, which downgrades the audit to
    plain signal counting rather than inventing a cause.
    """
    auth_status = None
    connector_health = None

    try:
        creds = await comp["repository"].list_platform_credentials()
        active = {
            str(c.get("platform", "")).lower()
            for c in creds
            if isinstance(c, dict) and c.get("is_active")
        }
        auth_status = {
            platform: any(key in active for key in keys)
            for platform, keys in _PLATFORM_CREDENTIAL_KEYS.items()
        }
    except Exception as e:
        logger.debug(f"Channel audit could not read platform credentials: {e}")

    try:
        registry = comp.get("registry")
        if registry is not None:
            health = registry.get_health_status()
            if isinstance(health, dict):
                connector_health = health
    except Exception as e:
        logger.debug(f"Channel audit could not read connector health: {e}")

    return auth_status, connector_health


def _describe_proxy(proxy_uri: str) -> str:
    """Name the configured proxy without repeating the credentials embedded in its URI.

    The documented form of PLAYWRIGHT_PROXY_SERVER is http://user:pass@host:port, and the health
    report is tool output: it reaches the agent's transcript and any log that captures it.
    """
    if not proxy_uri:
        return "Direct (No Proxy)"
    parsed = urlsplit(proxy_uri)
    if not parsed.hostname:
        return "Configured (unparseable URI)"
    host = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
    scheme = f"{parsed.scheme}://" if parsed.scheme else ""
    return f"{scheme}{host}" if not parsed.username else f"{scheme}<redacted>@{host}"


def _serialize_citation(cit: Any) -> Dict[str, Any]:
    """`observation_id` first, because that is the citation's identity.

    The URL and the title are display payload. A reader that keys on either can merge two
    observations of one source or split one in half, so they are never the thing a conclusion is
    traced through.
    """
    platform = getattr(cit, "platform", None)
    return {
        "observation_id": getattr(cit, "observation_id", None),
        "source_id": getattr(cit, "source_id", None),
        "citation_id": getattr(cit, "citation_id", None),
        "platform": platform.value if hasattr(platform, "value") else str(platform),
        "connector_surface": getattr(cit, "connector_surface", None),
        "title_or_query": getattr(cit, "title_or_query", None),
        "metric_highlight": getattr(cit, "metric_highlight", None),
        "author_or_channel": getattr(cit, "author_or_channel", None),
        "url": getattr(cit, "url", None),
        "excerpt": getattr(cit, "excerpt", None),
    }


async def _market_brief_payload(comp: Dict[str, Any], mission: Any) -> Optional[Dict[str, Any]]:
    """The confirmed Brief a Market analysis was authorized by, or None.

    Carried into the report so a reader can see which hypothesis the evidence was collected
    against, and which conditions would disconfirm it. A Market conclusion presented without its
    falsifiers is a claim the reader has no way to argue with.
    """
    if resolve_surface(getattr(mission, "surface", None)) is not ResearchSurface.MARKET:
        return None
    revision = await comp["workspace_store"].get_brief_revision_for_mission(mission.id)
    return revision.to_payload() if revision else None


def _market_brief_blocked(
    mission: Any,
    operation: str,
    missing_fields: Optional[List[str]] = None,
    detail: Optional[str] = None,
) -> str:
    """The one refusal every Market boundary returns when no confirmed Brief authorizes it.

    Execution, analysis and export all speak the same contract on purpose. An unauthorized
    Market mission that could still be read would hand back an Opportunity Index derived from
    evidence nobody framed a question for, which is the failure the Brief gate exists to
    prevent -- and it would be a quieter failure than refusing to probe.
    """
    return json.dumps(
        {
            "status": "BLOCKED",
            "surface": ResearchSurface.MARKET.value,
            "operation": operation,
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
            "missing_fields": list(missing_fields or REQUIRED_BRIEF_FIELDS),
            "opportunity_index_applies": False,
            "error": detail
            or (
                "Market execution is not authorized until the requester confirms every required "
                "Brief field."
            ),
            "note": (
                "No probe ran, no analysis was derived and no artifact was written. Collect the "
                "missing fields with the requester, show them the complete draft, and call "
                "confirm_market_brief once they confirm it."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


async def _refuse_unauthorized_market(comp: Dict[str, Any], mission: Any, operation: str):
    """Return (brief_payload, refusal). Exactly one of the two is ever set.

    A mission on no surface, or on ATTENTION, is not a Market read and passes through with no
    Brief -- which is what keeps every pre-workspace mission working unchanged.
    """
    if resolve_surface(getattr(mission, "surface", None)) is not ResearchSurface.MARKET:
        return None, None
    brief = await _market_brief_payload(comp, mission)
    if brief is None:
        return None, _market_brief_blocked(mission, operation)
    return brief, None


def _serialize_opportunity(opp: Any, include_supporting: int = 0) -> Dict[str, Any]:
    payload = {
        "topic": opp.topic,
        "type": opp.opportunity_type,
        "demand_score": opp.search_interest_score,
        "supply_score": opp.content_supply_score,
        "opportunity_index": opp.opportunity_index,
        "recommendation": opp.strategic_recommendation,
        "citations": [_serialize_citation(c) for c in getattr(opp, "citations", []) or []],
    }
    if include_supporting:
        payload["supporting_signals"] = opp.supporting_signals[:include_supporting]
    return payload


def _surface_payload(report: Any, mission: Any) -> Dict[str, Any]:
    """What surface this analysis speaks for, and what that surface is allowed to say."""
    surface = resolve_surface(getattr(mission, "surface", None))
    payload: Dict[str, Any] = {
        "surface": surface.value if surface else None,
        "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
        "opportunity_index_applies": opportunity_index_is_allowed(surface),
    }
    if surface is ResearchSurface.ATTENTION:
        payload["note"] = (
            "ATTENTION context. Ranked topics, momentum, freshness and source coverage are "
            "reported as candidates for investigation; no Opportunity Index and no commercial "
            "verdict are derived from them."
        )
    if getattr(report, "market_brief", None):
        payload["market_brief"] = report.market_brief
    return payload


def _serialize_insights(insights: Any) -> List[Dict[str, Any]]:
    """Tolerates pre-citation missions whose insights are still plain strings."""
    out: List[Dict[str, Any]] = []
    for item in insights or []:
        if isinstance(item, str):
            out.append({"statement": item, "citations": []})
            continue
        out.append({
            "statement": getattr(item, "statement", str(item)),
            "citations": [_serialize_citation(c) for c in getattr(item, "citations", []) or []],
        })
    return out


def _serialize_channel_summaries(summaries: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for ch in summaries or []:
        platform = getattr(ch, "platform", None)
        status = getattr(ch, "status", None)
        top = getattr(ch, "top_citation", None)
        out.append({
            "platform": platform.value if hasattr(platform, "value") else str(platform),
            # The probe, not just the platform: a healthy TikTok video grid must not be able to
            # answer on behalf of a TikTok comments surface that never ran.
            "connector_surface": getattr(ch, "connector_surface", None)
            or (platform.value if hasattr(platform, "value") else str(platform)),
            "status": status.value if hasattr(status, "value") else str(status),
            "signals_count": getattr(ch, "signals_count", 0),
            "timeframe_used": getattr(ch, "timeframe_used", None),
            "top_citation": _serialize_citation(top) if top else None,
            "notes": getattr(ch, "notes", None),
        })
    return out


async def _sync_lexicons_from_db(comp: Dict[str, Any]) -> None:
    """Sync every persisted vocabulary domain from the database into the engines that use it."""
    try:
        vocabulary = await load_market_vocabulary(comp["repository"])
        pos_terms = vocabulary.positive_terms
        stop_terms = vocabulary.foreign_stopwords
        noise_terms = vocabulary.noise_blacklist

        if pos_terms:
            comp["quality_evaluator"].register_terms(pos_terms)
            comp["strategic_reasoner"].register_terms(pos_terms)
            # Terms sharing a (domain, category) bucket are treated as expansions of each other,
            # so keyword matching uses the persisted vocabulary instead of hardcoded synonyms.
            comp["strategic_reasoner"].register_synonym_groups(
                [g for g in vocabulary.by_domain_and_category.values() if len(g) > 1]
            )
        if "clusterer" in comp:
            comp["clusterer"].register_ambiguous_unigrams(vocabulary.ambiguous_unigrams)
        if "google_trends_plugin" in comp:
            comp["google_trends_plugin"].register_probe_templates(vocabulary.probe_templates)
            comp["google_trends_plugin"].register_intent_keywords(vocabulary.search_intent)
        if "language_detector" in comp:
            comp["language_detector"].register_foreign_phrases(vocabulary.foreign_phrases)
            comp["language_detector"].register_portuguese_words(vocabulary.portuguese_words)
        if "tiktok_plugin" in comp:
            comp["tiktok_plugin"].register_ui_noise(vocabulary.tiktok_ui_noise)
            comp["tiktok_plugin"].register_suggest_templates(vocabulary.tiktok_suggest_templates)
        if stop_terms:
            comp["quality_evaluator"].register_foreign_stopwords(stop_terms)
            comp["strategic_reasoner"].register_foreign_stopwords(stop_terms)
            if "clusterer" in comp and hasattr(comp["clusterer"], "register_stopwords"):
                comp["clusterer"].register_stopwords(stop_terms)
        if noise_terms:
            comp["quality_evaluator"].register_noise_blacklist(noise_terms)
            comp["strategic_reasoner"].register_noise_blacklist(noise_terms)
            if "clusterer" in comp and hasattr(comp["clusterer"], "register_stopwords"):
                comp["clusterer"].register_stopwords(noise_terms)
        if "clusterer" in comp and hasattr(comp["clusterer"], "register_taxonomies"):
            taxonomies = await comp["repository"].get_industry_taxonomies()
            if taxonomies:
                comp["clusterer"].register_taxonomies(taxonomies)
    except Exception as e:
        logger.warning(f"Could not sync dynamic lexicons from DB: {e}")

    await _sync_self_identities(comp)


async def _sync_self_identities(comp: Dict[str, Any]) -> None:
    """Bind the operator's own connected accounts so market passes can exclude their content."""
    try:
        identities = await SelfIdentityRegistry(comp["repository"]).load()
        comp["registry"].register_self_identities(identities)
        comp["self_identities"] = identities
        if identities:
            logger.info(
                "Self-content guard armed for: "
                + ", ".join(sorted({f"{i.platform}:{i.normalized_username or i.normalized_account_id}" for i in identities}))
            )
        else:
            logger.info(
                "No connected account identity is known, so self-authored content cannot be "
                "recognised. Set the 'self_accounts' runtime config to close that gap."
            )
    except Exception as e:
        logger.warning(f"Could not load self-account identities: {e}")


# --- Handlers for Agent Harness Operations ---

def _invalid_timeframe(value: object) -> str:
    """The one refusal body, so four tools cannot drift into four wordings."""
    return json.dumps(
        {
            "status": "INVALID_TIMEFRAME",
            "message": (
                f"Unknown timeframe '{value}'. Use one of: "
                + ", ".join(t.value for t in Timeframe)
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


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
    try:
        mission = await comp["create_mission_use_case"].execute(
            title=topic,
            keywords=keywords,
            agent=agent,
            session_id=session_id,
            geo=geo_val,
            timeframe=timeframe,
        )
    except ValueError:
        return _invalid_timeframe(timeframe)

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
            "channel_summaries": _serialize_channel_summaries(report.channel_summaries),
            "strategic_insights": _serialize_insights(report.strategic_insights),
            "actionable_takeaways": _serialize_insights(report.actionable_takeaways),
            "next_step": f"Call generate_mission_artifact(mission_id='{mission.id}') to render the full interactive HTML dossier."
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


    brief, refusal = await _refuse_unauthorized_market(
        comp, mission, operation="discover_market_opportunities"
    )
    if refusal:
        return refusal

    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
    
    auth_status, connector_health = await _collect_channel_context(comp)
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
        auth_status=auth_status,
        connector_health=connector_health,
        market_brief=brief,
    )

    return json.dumps(
        {
            "mission_id": str(mission.id),
            "maturity_stage": report.maturity_stage.value,
            **_surface_payload(report, mission),
            "market_opportunities": [
                _serialize_opportunity(opp) for opp in report.market_opportunities
            ],
            "channel_summaries": _serialize_channel_summaries(report.channel_summaries),
            "strategic_insights": _serialize_insights(report.strategic_insights),
            "actionables": _serialize_insights(report.actionable_takeaways),
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
        elif plat == "youtube" and not reveal_secret(settings.YOUTUBE_API_KEY):
            diagnostics["recommendations"].append("YOUTUBE_API_KEY is not configured in .env.")

    return json.dumps(diagnostics, ensure_ascii=False, indent=2)


async def handle_get_system_logs(level: Optional[str] = None, component: Optional[str] = None, limit: int = 20) -> str:
    comp = get_components()
    repo: ITrendRepository = comp["repository"]
    safe_limit = max(1, min(limit, 30))
    raw_logs = await repo.get_recent_logs(level=level, component=component, limit=safe_limit)
    
    # Sanitize log details to prevent context window bloat and PII / credential leaks
    from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, sanitize_pii_data
    sanitized_logs = []
    for log in raw_logs:
        msg = sanitize_pii_text(log.get("message", ""))
        if len(msg) > 300:
            msg = msg[:300] + "..."
        details = log.get("details", {})
        if isinstance(details, dict):
            clean_details = sanitize_pii_data(details)
            details = {k: (str(v)[:150] + "..." if len(str(v)) > 150 else v) for k, v in clean_details.items()}
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
    refresh_plan = plan_staggered_refresh(creds)
    warnings = [e for e in refresh_plan if e["status"] in (STATUS_EXPIRING_SOON, STATUS_EXPIRED)]
    return json.dumps(
        {
            "status": "SUCCESS",
            "platforms": creds,
            "count": len(creds),
            "expiry_warnings": warnings,
            "refresh_plan": refresh_plan,
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


async def _run_meta_auth(
    oauth_manager: Any,
    browser_manager: Any,
    platform_name: str,
    auth_code: Optional[str],
    client_id: Optional[str],
    client_secret: Optional[str],
    redirect_uri: Optional[str],
    browser_login: bool,
    headless: bool,
    timeout_seconds: int,
) -> Dict[str, Any]:
    """
    Dual-UX entry point: Tier 1 browser session capture, or Tier 2 Graph API OAuth.

    An absent auth_code is treated as an explicit request for the browser flow, so a
    non-technical user who just calls the tool with no arguments lands on Tier 1.
    """
    use_browser = browser_login or not (auth_code and auth_code.strip())
    try:
        if use_browser:
            if not browser_manager:
                raise RuntimeError(f"No browser auth manager is bound for {platform_name}.")
            return await browser_manager.authenticate_interactive(
                headless=headless, timeout_seconds=timeout_seconds
            )
        return await oauth_manager.exchange_code_for_token(
            auth_code=auth_code,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
    except Exception as e:
        return {
            "success": False,
            "platform": platform_name,
            "tier": "TIER_1_BROWSER_SESSION" if use_browser else "TIER_2_GRAPH_API",
            "error_type": type(e).__name__,
            "message": str(e),
        }


async def _meta_auth_status(oauth_manager: Any, browser_manager: Any) -> Dict[str, Any]:
    """Report both tiers and the active_tier so the agent can see which ingress path is live."""
    status = await oauth_manager.get_auth_status()
    browser_status = None
    if browser_manager:
        browser_status = await browser_manager.get_auth_status()
        status["browser_session"] = browser_status

    # Resolve active tier
    if status.get("authenticated"):
        status["active_tier"] = "TIER_2_GRAPH_API"
    elif browser_status and browser_status.get("authenticated"):
        status["active_tier"] = "TIER_1_BROWSER_SESSION"
    else:
        status["active_tier"] = "NONE"

    return status


async def handle_authenticate_threads(
    auth_code: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    browser_login: bool = False,
    headless: bool = False,
    timeout_seconds: int = 180,
) -> str:
    comp = get_components()
    result = await _run_meta_auth(
        oauth_manager=comp["threads_auth_manager"],
        browser_manager=comp.get("threads_browser_auth_manager"),
        platform_name=ThreadsAuthManager.PLATFORM_NAME,
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        browser_login=browser_login,
        headless=headless,
        timeout_seconds=timeout_seconds,
    )
    if isinstance(result, dict) and not browser_login:
        result["keyword_search_access"] = await _probe_threads_keyword_search(comp)
    return json.dumps(result, ensure_ascii=False, indent=2)


async def _probe_threads_keyword_search(comp: Dict[str, Any]) -> Dict[str, Any]:
    """Report whether the Threads Graph token can search public posts at all.

    The probe keyword comes from the persisted market lexicon rather than a constant, and the
    result carries its own remediation: the Tier-1 browser session needs no App Review, which is
    what a self-hosted install can realistically obtain.
    """
    # An auxiliary probe must never break the authentication it reports on.
    registry = comp.get("registry")
    plugin = registry.get_plugin(PlatformType.THREADS) if registry else None
    if plugin is None or not hasattr(plugin, "check_keyword_search_access"):
        return {"status": "UNAVAILABLE", "detail": "No Threads connector is registered."}

    try:
        ingest_use_case = comp.get("ingest_use_case")
        seeds = await ingest_use_case.load_seed_keywords() if ingest_use_case else []
        report = await plugin.check_keyword_search_access(seeds[0] if seeds else "")
    except Exception as e:
        return {"status": "INCONCLUSIVE", "detail": f"The keyword search probe failed: {e}"}

    if report.get("status") in (plugin.KEYWORD_SEARCH_SELF_ONLY, plugin.KEYWORD_SEARCH_NOT_PERMITTED):
        logger.warning(f"Threads public keyword search is unavailable: {report.get('detail')}")
        report["recommended_path"] = "authenticate_threads(browser_login=True)"
    return report


async def handle_get_threads_auth_status() -> str:
    comp = get_components()
    status = await _meta_auth_status(
        comp["threads_auth_manager"], comp.get("threads_browser_auth_manager")
    )
    return json.dumps(status, ensure_ascii=False, indent=2)


async def handle_clear_threads_auth() -> str:
    comp = get_components()
    auth_mgr: ThreadsAuthManager = comp["threads_auth_manager"]
    cleared = await auth_mgr.clear_auth()
    browser_mgr = comp.get("threads_browser_auth_manager")
    browser_cleared = await browser_mgr.clear_auth() if browser_mgr else False
    return json.dumps(
        {
            "platform": ThreadsAuthManager.PLATFORM_NAME,
            "cleared": cleared,
            "browser_session_cleared": browser_cleared,
            "message": (
                "Threads OAuth credentials deleted from local encrypted storage. This does not "
                "revoke the token at Meta -- remove the app's access in Meta account security "
                "settings if that is also required."
            )
            if cleared else "No stored Threads OAuth credentials found.",
        },
        ensure_ascii=False,
        indent=2,
    )


async def handle_authenticate_instagram(
    auth_code: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    browser_login: bool = False,
    headless: bool = False,
    timeout_seconds: int = 180,
) -> str:
    comp = get_components()
    result = await _run_meta_auth(
        oauth_manager=comp["instagram_auth_manager"],
        browser_manager=comp.get("instagram_browser_auth_manager"),
        platform_name=InstagramAuthManager.PLATFORM_NAME,
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        browser_login=browser_login,
        headless=headless,
        timeout_seconds=timeout_seconds,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_instagram_auth_status() -> str:
    comp = get_components()
    status = await _meta_auth_status(
        comp["instagram_auth_manager"], comp.get("instagram_browser_auth_manager")
    )
    return json.dumps(status, ensure_ascii=False, indent=2)


async def handle_clear_instagram_auth() -> str:
    comp = get_components()
    auth_mgr: InstagramAuthManager = comp["instagram_auth_manager"]
    cleared = await auth_mgr.clear_auth()
    browser_mgr = comp.get("instagram_browser_auth_manager")
    browser_cleared = await browser_mgr.clear_auth() if browser_mgr else False
    return json.dumps(
        {
            "platform": InstagramAuthManager.PLATFORM_NAME,
            "cleared": cleared,
            "browser_session_cleared": browser_cleared,
            "message": (
                "Instagram OAuth credentials deleted from local encrypted storage. This does not "
                "revoke the token at Meta -- remove the app's access in Meta account security "
                "settings if that is also required."
            )
            if cleared else "No stored Instagram OAuth credentials found.",
        },
        ensure_ascii=False,
        indent=2,
    )


# --- Handlers for the Dual-Surface Research Workspace ---

def _host_workspace_of(proposed_path: Path) -> Path:
    """Recover the host workspace from a proposed research path.

    The layout is fixed -- `<host>/.ignis/research/<slug>` -- so the host workspace is the path
    with those three segments removed. Recovering it rather than asking for it again keeps the
    confirmation carrying exactly the path the requester was shown.
    """
    parts = proposed_path.parts
    tail = (*RESEARCH_ROOT_SEGMENTS, proposed_path.name)
    if len(parts) <= len(tail) or parts[-len(tail):] != tail:
        raise ValueError(
            f"'{proposed_path}' is not a research workspace path. Expected a path ending in "
            f"{'/'.join(RESEARCH_ROOT_SEGMENTS)}/<research-slug>."
        )
    return Path(*parts[: -len(tail)])


def _workspace_payload(workspace: Any) -> Dict[str, Any]:
    return {
        "workspace_id": str(workspace.workspace_id),
        "slug": workspace.slug,
        "name": workspace.name,
        "root_path": str(workspace.root_path),
        "manifest_path": str(workspace.manifest_path),
        "format_version": workspace.format_version,
        "status": workspace.status.value,
        "created_at": workspace.created_at.isoformat(),
    }


async def handle_propose_research_workspace(
    host_workspace: str,
    research_name: str,
    slug: Optional[str] = None,
) -> str:
    comp = get_components()
    try:
        proposal = await comp["create_research_workspace_use_case"].propose(
            Path(host_workspace), research_name, slug=slug
        )
    except IgnisDomainException as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

    payload = proposal.to_payload()
    payload["next_step"] = (
        "Show the proposed path to the requester. Nothing has been written. Call "
        "confirm_research_workspace with confirmation=true only after they agree"
        + (", and adopt=true to reuse the folder already there." if proposal.requires_adoption
           else ".")
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def handle_confirm_research_workspace(
    proposed_path: str,
    confirmation: bool = False,
    adopt: bool = False,
    research_name: Optional[str] = None,
) -> str:
    comp = get_components()
    target = Path(proposed_path)
    try:
        host_workspace = _host_workspace_of(target)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

    use_case = comp["create_research_workspace_use_case"]
    try:
        # Re-proposed rather than carried across the call: the proposal is read-only, and
        # re-reading the folder is what makes the confirmation act on the filesystem as it is
        # now instead of as it was when the requester was first shown the path.
        proposal = await use_case.propose(
            host_workspace, research_name or target.name, slug=target.name
        )
        workspace = await use_case.confirm(proposal, confirmation=confirmation, adopt=adopt)
    except IgnisDomainException as exc:
        return json.dumps(
            {
                "status": "ADOPTION_REQUIRED" if not adopt else "REFUSED",
                "proposed_path": str(target),
                "error": str(exc),
            },
            ensure_ascii=False,
            indent=2,
        )

    if workspace is None:
        return json.dumps(
            {
                "status": "DECLINED",
                "proposed_path": str(target),
                "note": "No directory, manifest, database record or journal was created.",
            },
            ensure_ascii=False,
            indent=2,
        )

    payload = _workspace_payload(workspace)
    payload["status"] = "REUSED" if proposal.existing_workspace is not None else "CREATED"
    payload["note"] = (
        "The configured shared Ignis database is the canonical record store; this folder holds "
        "the manifest, run journals and derived artifacts. It is local-first and is not "
        "committed or published automatically."
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def handle_list_research_workspaces(limit: int = 20) -> str:
    comp = get_components()
    workspaces = await comp["workspace_store"].list_research_workspaces(limit=max(1, min(limit, 100)))
    return json.dumps(
        {
            "count": len(workspaces),
            "workspaces": [_workspace_payload(w) for w in workspaces],
            "note": (
                "Any supported Agent host connected to this Ignis database can reopen these by "
                "workspace_id, independently of the chat that created them."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


async def handle_create_attention_mission(
    workspace_id: str,
    title: str,
    geo: str = "VN",
    timeframe: str = "7d",
    seed: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    comp = get_components()
    try:
        mission = await comp["create_attention_mission_use_case"].execute(
            workspace_id=UUID(workspace_id),
            title=title,
            keywords=keywords,
            seed=seed,
            agent=agent,
            session_id=session_id,
            platforms=[resolve_platform(p) for p in platforms] if platforms else None,
            geo=resolve_geo(geo),
            timeframe=timeframe,
        )
    except ValueError:
        return _invalid_timeframe(timeframe)
    except IgnisDomainException as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

    return json.dumps(
        {
            "status": "CREATED",
            "surface": ResearchSurface.ATTENTION.value,
            "workspace_id": workspace_id,
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "title": mission.title,
            "keywords": mission.keywords,
            "geo": mission.geo_code.value,
            "timeframe": mission.timeframe,
            "requires_market_brief": False,
            "emits_opportunity_index": False,
            "note": (
                "ATTENTION describes what is gaining attention. Its ranked topics are candidates "
                "for investigation, not commercial verdicts, and it never returns an Opportunity "
                "Index."
            ),
            "next_step": f"Call execute_mission_ingress(mission_id='{mission.shortcode}').",
        },
        ensure_ascii=False,
        indent=2,
    )


async def handle_confirm_market_brief(
    workspace_id: str,
    decision: str,
    target_user: str,
    problem: str,
    geo: str,
    timeframe: str,
    hypothesis: str,
    falsifiers: Optional[List[str]] = None,
    confirmed_by: str = "",
    title: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    parent_attention_mission_id: Optional[str] = None,
    parent_cluster_id: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    comp = get_components()
    try:
        mission, revision = await comp["confirm_market_brief_use_case"].execute(
            workspace_id=UUID(workspace_id),
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=falsifiers or [],
            confirmed_by=confirmed_by,
            title=title,
            keywords=keywords,
            lineage=MissionLineage(
                parent_attention_mission_id=(
                    UUID(parent_attention_mission_id) if parent_attention_mission_id else None
                ),
                parent_cluster_id=UUID(parent_cluster_id) if parent_cluster_id else None,
            ),
            agent=agent,
            session_id=session_id,
            platforms=[resolve_platform(p) for p in platforms] if platforms else None,
        )
    except IncompleteMarketBriefError as exc:
        return json.dumps(
            {
                "status": "BLOCKED",
                "surface": ResearchSurface.MARKET.value,
                "missing_fields": exc.missing_fields,
                "error": str(exc),
                "note": (
                    "Nothing was written. Collect the missing fields with the requester, show "
                    "them the complete draft, and call this tool again once they confirm it."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    except ValueError:
        return _invalid_timeframe(timeframe)
    except IgnisDomainException as exc:
        return json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2)

    return json.dumps(
        {
            "status": "CONFIRMED",
            "surface": ResearchSurface.MARKET.value,
            "workspace_id": workspace_id,
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "brief_revision_id": str(revision.brief_revision_id),
            "revision_number": revision.revision_number,
            "confirmed_by": revision.confirmed_by,
            "confirmed_at": revision.confirmed_at.isoformat(),
            "falsifiers": list(revision.falsifiers),
            "lineage": {
                "parent_attention_mission_id": (
                    str(mission.parent_attention_mission_id)
                    if mission.parent_attention_mission_id else None
                ),
                "parent_cluster_id": (
                    str(mission.parent_cluster_id) if mission.parent_cluster_id else None
                ),
            },
            "note": (
                "This revision is immutable. Changing any required field creates a new revision "
                "and a new Market mission rather than rewriting this one. Attention lineage is "
                "context; it is not counted as support for this hypothesis."
            ),
            "next_step": f"Call execute_mission_ingress(mission_id='{mission.shortcode}').",
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


    try:
        mission = await comp["create_mission_use_case"].execute(
            title=final_title,
            keywords=final_keywords,
            agent=agent,
            session_id=session_id,
            platforms=target_platforms,
            geo=geo_val,
            timeframe=timeframe,
        )
    except ValueError:
        return _invalid_timeframe(timeframe)

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

    try:
        result = await comp["execute_mission_use_case"].execute(mission_id=mission.id)
    except IncompleteMarketBriefError as exc:
        # The use case has already set the mission BLOCKED and refused before any connector was
        # called. Re-raising past the tool boundary would have surfaced as a transport error,
        # which tells the Agent that something broke rather than that the requester still owes
        # the Brief.
        return _market_brief_blocked(
            mission,
            operation="execute_mission_ingress",
            missing_fields=exc.missing_fields,
            detail=str(exc),
        )

    result["shortcode"] = mission.shortcode
    result["display_label"] = f"[{mission.shortcode}] {mission.title}" 
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    comp = get_components()
    await _sync_lexicons_from_db(comp)
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"No research mission found with ID or shortcode: '{mission_id}'"}, ensure_ascii=False)

    brief, refusal = await _refuse_unauthorized_market(
        comp, mission, operation="get_mission_analysis"
    )
    if refusal:
        return refusal

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
    auth_status, connector_health = await _collect_channel_context(comp)
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
        auth_status=auth_status,
        connector_health=connector_health,
        market_brief=brief,
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
    analysis.update(_surface_payload(report, mission))
    analysis["market_opportunities"] = [
        _serialize_opportunity(opp, include_supporting=2) for opp in report.market_opportunities
    ]
    analysis["channel_summaries"] = _serialize_channel_summaries(report.channel_summaries)
    analysis["strategic_insights"] = _serialize_insights(report.strategic_insights)
    analysis["actionable_takeaways"] = _serialize_insights(report.actionable_takeaways)
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

    brief, refusal = await _refuse_unauthorized_market(
        comp, mission, operation="generate_mission_artifact"
    )
    if refusal:
        # Returned before the builder runs and before anything reaches disk: an exported dossier
        # is the copy that outlives the chat, so an unauthorized one is the worst place for a
        # Market conclusion to end up.
        return refusal

    signals = await comp["repository"].get_mission_signals(m_id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)

    
    auth_status, connector_health = await _collect_channel_context(comp)
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
        auth_status=auth_status,
        connector_health=connector_health,
        market_brief=brief,
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
            "channel_summaries": _serialize_channel_summaries(report.channel_summaries),
            "strategic_insights": _serialize_insights(report.strategic_insights)[:3],
            "actionable_takeaways": _serialize_insights(report.actionable_takeaways[:3]),
            "instructions_for_user": f"Interactive HTML dossier ({len(signals)} signals) exported successfully. Open file://{abs_path} directly in your browser.",
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
    # Same refusal the ingress tool gives, for the same reason: Timeframe._missing_ manufactures
    # a member for any string, so an unrecognised value reaches the reader looking valid.
    if tf_val not in tuple(Timeframe):
        return _invalid_timeframe(timeframe)

    now = datetime.now(timezone.utc)
    tf_days = timeframe_to_days(tf_val)
    window_start = now - timedelta(days=tf_days)

    safe_limit = max(1, min(limit, 30))
    clusters = await comp["top_clusters_use_case"].execute(geo=geo_val, timeframe=tf_val, limit=safe_limit)
    topics = []
    for c in clusters:
        signal_count = len(c.signals)
        plat_count = len({s.platform for s in c.signals})
        # Summary is rendered from the signals actually returned for this timeframe (BUG-07).
        dynamic_summary = c.summary_text or f"Aggregated topic from {signal_count} signals across {plat_count} platforms."
        topics.append({
            "id": str(c.id),
            "topic_name": c.topic_label,
            "summary": dynamic_summary,
            "category": c.category,
            "cross_platform_score": c.cross_platform_score,
            "momentum": c.momentum_category.value,
            "signal_count": signal_count,
        })
    envelope = {
        "status": "SUCCESS",
        "geo": geo_val.value,
        "timeframe_used": tf_val.value,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "total_topics": len(topics),
        "topics": topics,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2)


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
                # When the platform says the content was posted, where it says so at all.
                # Distinct from captured_at, which is when this harness pulled it.
                "published_at": s.published_at.isoformat() if s.published_at else None,
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
    format: str = "dashboard",
) -> str:
    comp = get_components()
    builder = comp["artifact_builder"]
    geo_val = resolve_geo(geo)
    reports_dir = _get_secure_reports_dir()

    if format.strip().lower() == "graph" and not topic_id.strip():
        await _sync_lexicons_from_db(comp)
        clusters = await comp["top_clusters_use_case"].execute(geo=geo_val, limit=150)
        html_content = builder.build_graph_artifact(clusters, geo=geo_val, clusterer=comp.get("clusterer"))
        report_file = reports_dir / f"trend_graph_{geo_val.value.lower()}.html"
        report_file.write_text(html_content, encoding="utf-8")
        abs_path = str(report_file.resolve())
        return json.dumps(
            {
                "status": "SUCCESS",
                "type": "GRAPH",
                "total_clusters": len(clusters),
                "total_signals": sum(len(c.signals) for c in clusters),
                "artifact_file": abs_path,
                "file_url": f"file://{abs_path}",
                "message": (
                    f"Interactive trend graph exported to: file://{abs_path}. "
                    "Clusters are navigable; signals are aggregated into density halos."
                ),
            },
            ensure_ascii=False,
            indent=2
        )

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
                    "topic_name": target_cluster.topic_label,
                    "artifact_file": abs_path,
                    "file_url": f"file://{abs_path}",
                    "message": f"Topic card exported to: file://{abs_path}",
                },
                ensure_ascii=False,
                indent=2
            )
        return json.dumps({"error": "Requested topic not found."}, ensure_ascii=False)


async def handle_trigger_ingress_refresh(
    geo: str = "VN",
    scope: str = "public_market",
    timeframe: str = "24h",
) -> str:
    comp = get_components()
    await _sync_lexicons_from_db(comp)
    geo_val = resolve_geo(geo)
    # The window the connectors themselves search. Without this the pass always ran at 24h no
    # matter what the caller asked for, and the timeframe only narrowed the later read.
    #
    # Timeframe._missing_ builds a member out of any string it is handed, so an unknown value
    # would reach the connectors as a live enum and then be silently mapped to a default. Check
    # it here instead, the same way an unknown scope is refused below.
    timeframe_val = resolve_timeframe(timeframe)
    if timeframe_val not in tuple(Timeframe):
        return _invalid_timeframe(timeframe)

    scope_val = IngressScope(scope)
    if scope_val is None:
        return json.dumps(
            {
                "status": "INVALID_SCOPE",
                "message": (
                    f"Unknown scope '{scope}'. Use 'public_market' (default, market listening), "
                    "'own_profile' (only the connected account's own posts) or 'both'."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    # A public pass seeds the keyword probes from the persisted lexicon, because the connectors
    # whose only feed is the operator's own account are reached that way instead.
    seeds = await comp["ingest_use_case"].load_seed_keywords() if scope_val.includes_public else []
    # REQUESTED: somebody typed this, so the pass is not script-filtered -- see IngressTrigger.
    # The keyword cap still applies: this path spends the same YouTube search quota as the worker.
    signals = await comp["registry"].fetch_from_all(
        geo=geo_val,
        timeframe=timeframe_val,
        scope=scope_val,
        seed_keywords=seeds,
        max_probe_keywords=MAX_TOPIC_KEYWORDS,
        trigger=IngressTrigger.REQUESTED,
    )
    clusters = await comp["cluster_use_case"].execute(signals)
    guard = dict(getattr(comp["registry"], "last_pass_report", {}) or {})

    return json.dumps(
        {
            "status": "success",
            "geo": geo_val.value,
            "scope": scope_val.value,
            "timeframe": timeframe_val.value,
            "total_signals_fetched": len(signals),
            "total_clusters_formed": len(clusters),
            "seed_keywords_used": len(seeds),
            "scope_guard": guard,
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


@mcp.tool(name="propose_research_workspace", description="Propose where a new research would live: `<host-workspace>/.ignis/research/<research-slug>/`. Read-only -- it creates no directory, manifest, database record or journal. Show the proposed path to the requester and call confirm_research_workspace only after they agree.")
async def propose_research_workspace(host_workspace: str, research_name: str, slug: Optional[str] = None) -> str:
    return await handle_propose_research_workspace(host_workspace, research_name, slug)


@mcp.tool(name="confirm_research_workspace", description="Create, reuse or adopt the proposed research workspace after the requester confirms it. Reuses an existing matching manifest without rewriting it; adopting a non-empty folder without a manifest needs adopt=true and never deletes or overwrites unrelated files.")
async def confirm_research_workspace(proposed_path: str, confirmation: bool = False, adopt: bool = False, research_name: Optional[str] = None) -> str:
    return await handle_confirm_research_workspace(proposed_path, confirmation, adopt, research_name)


@mcp.tool(name="list_research_workspaces", description="List the research workspaces held in the configured shared Ignis database, so a research can be reopened from any supported Agent host independently of the chat that created it.")
async def list_research_workspaces(limit: int = 20) -> str:
    return await handle_list_research_workspaces(limit)


@mcp.tool(name="create_attention_mission", description="Start an ATTENTION mission inside a confirmed research workspace: exploratory discovery of what is gaining attention. Needs no hypothesis and no Market Brief, and never returns an Opportunity Index.")
async def create_attention_mission(workspace_id: str, title: str, geo: str = "VN", timeframe: str = "7d", seed: Optional[str] = None, keywords: Optional[list[str]] = None, platforms: Optional[list[str]] = None, agent: str = "claude", session_id: Optional[str] = None) -> str:
    return await handle_create_attention_mission(workspace_id, title, geo, timeframe, seed, keywords, platforms, agent, session_id)


@mcp.tool(name="confirm_market_brief", description="Persist a requester-confirmed Market Brief and open the MARKET mission it authorizes. Run the adaptive Q&A in your own context, one question at a time, show the draft for editing, and call this only with the complete confirmed payload -- drafts and abandoned Q&A are never sent or stored. Requires decision, target_user, problem, geo, timeframe, hypothesis and at least one falsifier.")
async def confirm_market_brief(workspace_id: str, decision: str, target_user: str, problem: str, geo: str, timeframe: str, hypothesis: str, falsifiers: Optional[list[str]] = None, confirmed_by: str = "", title: Optional[str] = None, keywords: Optional[list[str]] = None, parent_attention_mission_id: Optional[str] = None, parent_cluster_id: Optional[str] = None, platforms: Optional[list[str]] = None, agent: str = "claude", session_id: Optional[str] = None) -> str:
    return await handle_confirm_market_brief(workspace_id, decision, target_user, problem, geo, timeframe, hypothesis, falsifiers, confirmed_by, title, keywords, parent_attention_mission_id, parent_cluster_id, platforms, agent, session_id)


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


@mcp.tool(name="generate_trend_artifact", description="Generate a standalone single-file HTML artifact: a trend dashboard, a single topic card (pass topic_id), or an interactive force-directed trend graph (pass format='graph').")
async def generate_trend_artifact(topic_id: str = "", geo: str = "VN", format: str = "dashboard") -> str:
    return await handle_generate_trend_artifact(topic_id=topic_id, geo=geo, format=format)


@mcp.tool(name="trigger_ingress_refresh", description="Trigger immediate multi-platform ETL trend ingestion and clustering. `timeframe` is the window the connectors search (24h, 7d, 30d, 90d, 12m), not a filter applied afterwards. Reads public market surfaces only by default; pass scope='own_profile' to read the connected account's own posts instead, or scope='both' for the union.")
async def trigger_ingress_refresh(
    geo: str = "VN",
    scope: str = "public_market",
    timeframe: str = "24h",
) -> str:
    return await handle_trigger_ingress_refresh(geo=geo, scope=scope, timeframe=timeframe)


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


@mcp.tool(name="authenticate_threads", description="Connect Meta Threads with either tier: call with no auth_code (or browser_login=true) for the 1-click browser session capture that needs no Meta Developer App, or pass auth_code to run the Graph API OAuth 2.0 flow and store a 60-day long-lived token AES-encrypted.")
async def authenticate_threads(
    auth_code: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    browser_login: bool = False,
    headless: bool = False,
    timeout_seconds: int = 180,
) -> str:
    return await handle_authenticate_threads(
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        browser_login=browser_login,
        headless=headless,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(name="get_threads_auth_status", description="Inspect the stored Meta Threads credentials across both tiers: OAuth 2.0 token state, granted scopes, key version, days remaining and refresh due, plus any captured browser session.")
async def get_threads_auth_status() -> str:
    return await handle_get_threads_auth_status()


@mcp.tool(name="clear_threads_auth", description="Delete the stored Meta Threads OAuth 2.0 credentials and browser session from local encrypted storage. Does not revoke the token at Meta.")
async def clear_threads_auth() -> str:
    return await handle_clear_threads_auth()


async def handle_get_threads_trending_topics(geo: str = "VN", limit: int = 15) -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    threads_plugin = comp["registry"].get_plugin(PlatformType.THREADS)
    if not threads_plugin or not hasattr(threads_plugin, "fetch_trending_topics"):
        return json.dumps({"status": "ERROR", "message": "Threads plugin not available or does not support trending topics."}, ensure_ascii=False)

    # Check authentication state first
    if hasattr(threads_plugin, "resolve_auth_tier") and callable(threads_plugin.resolve_auth_tier):
        try:
            auth_res = await threads_plugin.resolve_auth_tier()
            if isinstance(auth_res, tuple) and len(auth_res) == 2:
                tier, cred = auth_res
                if tier == "none":
                    return json.dumps({
                        "status": "AUTH_REQUIRED",
                        "platform": "THREADS",
                        "geo": geo_code.value,
                        "total_topics": 0,
                        "topics": [],
                        "message": "Threads is not authenticated. Run authenticate_threads(browser_login=True) to capture browser session.",
                    }, ensure_ascii=False, indent=2)
        except Exception as auth_err:
            logger.debug(f"Auth tier check error: {auth_err}")

    try:
        topics = await threads_plugin.fetch_trending_topics(geo=geo_code, limit=max(1, min(limit, 30)))
        if not topics:
            return json.dumps(
                {
                    "status": "PARSE_EMPTY",
                    "platform": "THREADS",
                    "geo": geo_code.value,
                    "total_topics": 0,
                    "topics": [],
                    "message": "Meta Threads does not currently surface 'Today's Topics' in this region or no trending topics were returned by GraphQL.",
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(
            {
                "status": "SUCCESS",
                "platform": "THREADS",
                "geo": geo_code.value,
                "total_topics": len(topics),
                "topics": topics,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching Threads trending topics: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_threads_trending_topics", description="Fetch real-time Trending Topics from Threads search surface (threads.net/search) for macro market awareness.")
async def get_threads_trending_topics(geo: str = "VN", limit: int = 15) -> str:
    return await handle_get_threads_trending_topics(geo=geo, limit=limit)


async def handle_get_threads_search_suggestions(keyword: str, geo: str = "VN", limit: int = 10) -> str:
    comp = get_components()
    geo_code = GeoCode.VN if geo.upper() == "VN" else GeoCode.GLOBAL
    threads_plugin = comp["registry"].get_plugin(PlatformType.THREADS)
    if not threads_plugin or not hasattr(threads_plugin, "fetch_search_suggestions"):
        return json.dumps({"status": "ERROR", "message": "Threads plugin not available or does not support search suggestions."}, ensure_ascii=False)

    # Check authentication state first
    if hasattr(threads_plugin, "resolve_auth_tier") and callable(threads_plugin.resolve_auth_tier):
        try:
            auth_res = await threads_plugin.resolve_auth_tier()
            if isinstance(auth_res, tuple) and len(auth_res) == 2:
                tier, cred = auth_res
                if tier == "none":
                    return json.dumps({
                        "status": "AUTH_REQUIRED",
                        "platform": "THREADS",
                        "keyword": keyword,
                        "total_suggestions": 0,
                        "suggestions": [],
                        "message": "Threads is not authenticated. Run authenticate_threads(browser_login=True) to capture browser session.",
                    }, ensure_ascii=False, indent=2)
        except Exception as auth_err:
            logger.debug(f"Auth tier check error: {auth_err}")

    try:
        suggestions = await threads_plugin.fetch_search_suggestions(keyword=keyword, geo=geo_code, limit=max(1, min(limit, 20)))
        if not suggestions:
            return json.dumps(
                {
                    "status": "PARSE_EMPTY",
                    "platform": "THREADS",
                    "keyword": keyword,
                    "total_suggestions": 0,
                    "suggestions": [],
                    "message": f"No search suggestions returned by Threads for keyword '{keyword}'.",
                },
                ensure_ascii=False,
                indent=2,
            )

        return json.dumps(
            {
                "status": "SUCCESS",
                "platform": "THREADS",
                "keyword": keyword,
                "total_suggestions": len(suggestions),
                "suggestions": suggestions,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching Threads search suggestions: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_threads_search_suggestions", description="Fetch search autocomplete suggestions and derivative queries from Threads search for keyword expansion and slang discovery.")
async def get_threads_search_suggestions(keyword: str, geo: str = "VN", limit: int = 10) -> str:
    return await handle_get_threads_search_suggestions(keyword=keyword, geo=geo, limit=limit)



@mcp.tool(name="authenticate_instagram", description="Connect Instagram with either tier: call with no auth_code (or browser_login=true) for the 1-click browser session capture that needs no Meta Developer App, or pass auth_code to run the Instagram Graph API OAuth 2.0 flow and store a 60-day long-lived token AES-encrypted.")
async def authenticate_instagram(
    auth_code: Optional[str] = None,
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    browser_login: bool = False,
    headless: bool = False,
    timeout_seconds: int = 180,
) -> str:
    return await handle_authenticate_instagram(
        auth_code=auth_code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        browser_login=browser_login,
        headless=headless,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(name="get_instagram_auth_status", description="Inspect the stored Instagram credentials across both tiers: OAuth 2.0 token state, granted scopes, days remaining and refresh due, plus any captured browser session.")
async def get_instagram_auth_status() -> str:
    return await handle_get_instagram_auth_status()


@mcp.tool(name="clear_instagram_auth", description="Delete the stored Instagram OAuth 2.0 credentials and captured browser session from local encrypted storage. Does not revoke the token at Meta.")
async def clear_instagram_auth() -> str:
    return await handle_clear_instagram_auth()


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
        
        # The caller may pass its own triggers; otherwise the persisted baseline is used. The
        # same vocabulary drives the autonomous discovery pass, so both read one lexicon domain.
        if inquiry_patterns:
            active_triggers = [t.lower() for t in inquiry_patterns]
        else:
            rows = await comp["repository"].get_domain_lexicons(domain="customer_inquiry")
            active_triggers = [
                str(row["term"]).lower() for row in (rows or []) if row.get("term")
            ]
            if not active_triggers:
                logger.warning(
                    "No customer inquiry markers registered, so no comment can be recognised as "
                    "a question. Check the customer_inquiry domain in market_lexicons."
                )

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
            if "clusterer" in comp and hasattr(comp["clusterer"], "register_stopwords"):
                comp["clusterer"].register_stopwords(terms)
        elif d_lower == "foreign_stopwords":
            if "quality_evaluator" in comp:
                comp["quality_evaluator"].register_foreign_stopwords(terms)
            if "strategic_reasoner" in comp:
                comp["strategic_reasoner"].register_foreign_stopwords(terms)
            if "clusterer" in comp and hasattr(comp["clusterer"], "register_stopwords"):
                comp["clusterer"].register_stopwords(terms)
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


async def handle_get_runtime_config(key: Optional[str] = None, category: Optional[str] = None) -> str:
    comp = get_components()
    mgr = comp["runtime_config_manager"]
    try:
        if key:
            val = await mgr.get(key)
            if val is None:
                return json.dumps(
                    {
                        "status": "NOT_FOUND",
                        "key": key,
                        "value": None,
                        "message": f"Configuration key '{key}' is not set in runtime config store.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            return json.dumps(
                {
                    "status": "SUCCESS",
                    "key": key,
                    "value": val,
                },
                ensure_ascii=False,
                indent=2,
            )
        configs = await mgr.get_all(category=category)
        if not configs:
            return json.dumps(
                {
                    "status": "WARNING",
                    "warning_type": "STORE_EMPTY",
                    "total_configs": 0,
                    "category_filter": category,
                    "configs": {},
                    "message": "Runtime config store is empty. No dynamic configurations found in database or cache.",
                },
                ensure_ascii=False,
                indent=2,
            )
        return json.dumps(
            {
                "status": "SUCCESS",
                "total_configs": len(configs),
                "category_filter": category,
                "configs": configs,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error fetching runtime config: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="get_runtime_config", description="Inspect dynamic runtime configuration parameters (e.g. threads_web_client_id, threads_graphql_endpoint, doc_ids) from persistent storage and in-memory cache.")
async def get_runtime_config(key: Optional[str] = None, category: Optional[str] = None) -> str:
    return await handle_get_runtime_config(key=key, category=category)


async def handle_update_runtime_config(
    key: str,
    value: str,
    category: str = "connector",
    description: Optional[str] = None,
) -> str:
    comp = get_components()
    mgr = comp["runtime_config_manager"]
    try:
        await mgr.set(
            key=key,
            value=value,
            category=category,
            description=description,
            updated_by="agent",
        )
        return json.dumps(
            {
                "status": "SUCCESS",
                "message": f"Successfully updated runtime config '{key}'.",
                "key": key,
                "value": value,
                "category": category,
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error updating runtime config '{key}': {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="update_runtime_config", description="Update a dynamic runtime configuration parameter (e.g. updating an outdated web client ID or GraphQL doc_id) into persistent storage and active in-memory cache.")
async def update_runtime_config(
    key: str,
    value: str,
    category: str = "connector",
    description: Optional[str] = None,
) -> str:
    return await handle_update_runtime_config(key=key, value=value, category=category, description=description)


async def handle_refresh_runtime_config_cache() -> str:
    comp = get_components()
    mgr = comp["runtime_config_manager"]
    try:
        cached = await mgr.refresh()
        return json.dumps(
            {
                "status": "SUCCESS",
                "message": "Successfully refreshed runtime configuration in-memory cache from database.",
                "total_cached_keys": len(cached),
                "cached_keys": list(cached.keys()),
            },
            ensure_ascii=False,
            indent=2,
        )
    except Exception as e:
        logger.error(f"Error refreshing runtime config cache: {e}")
        return json.dumps({"status": "ERROR", "message": str(e)}, ensure_ascii=False)


@mcp.tool(name="refresh_runtime_config_cache", description="Force invalidate and reload all dynamic runtime configurations from database into active in-memory cache.")
async def refresh_runtime_config_cache() -> str:
    return await handle_refresh_runtime_config_cache()


async def handle_verify_connectors_health() -> str:
    """
    Run active diagnostic probes across all multi-platform ingress connectors and infrastructure:
    - Database Read & Write Probe (Connection pool, active lexicons, sentinel cluster upsert)
    - YouTube Data API v3 (API Key & Quota verification)
    - Google Trends RSS (Feed responsiveness & parsing)
    - TikTok Connectors & Playwright (Browser engine & optional proxy routing)
    - Threads & Instagram Reels (Active synthetic HTTP probe & session expiry check)
    - Real-time Alert generation for consecutive failures, expiring credentials, and parse-empty probes.
    """
    comp = get_components()
    repo = comp["repository"]
    registry = comp["registry"]

    now = datetime.now(timezone.utc)
    alerts: List[Dict[str, Any]] = []

    diagnostics: Dict[str, Any] = {
        "timestamp": now.isoformat(),
        "proxy_configured": bool(reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER)),
        "proxy_server": _describe_proxy(reveal_secret(settings.PLAYWRIGHT_PROXY_SERVER)),
        "connectors": {},
        "database": {},
        "alerts": [],
        "overall_status": "HEALTHY",
    }

    # 1. Database Read Probe
    try:
        lexicons = await repo.get_domain_lexicons()
        diagnostics["database"] = {
            "status": "HEALTHY",
            "active_lexicons_count": len(lexicons),
            "storage": "PostgreSQL / TimescaleDB",
            "write_probe": "PENDING",
        }
    except Exception as e:
        diagnostics["database"] = {
            "status": "UNHEALTHY",
            "error": str(e),
            "write_probe": "SKIPPED",
        }
        diagnostics["overall_status"] = "DEGRADED"
        alerts.append({
            "level": "CRITICAL",
            "type": "DATABASE_READ_FAILURE",
            "component": "database",
            "message": f"Database read probe failed: {e}",
            "timestamp": now.isoformat(),
        })

    # 1b. Database Write Probe (Sentinel Cluster Upsert)
    try:
        sentinel_id = uuid.uuid5(uuid.NAMESPACE_DNS, "sentinel:health_write_probe")
        sentinel_cluster = TopicCluster(
            id=sentinel_id,
            canonical_name="sentinel_health_write_probe",
            summary_text="Health check write probe",
            category="health",
            cross_platform_score=0.0,
            signals=[],
            first_seen_at=now,
            last_updated_at=now,
        )
        await repo.save_clusters([sentinel_cluster])
        diagnostics["database"]["write_probe"] = "HEALTHY"
    except Exception as write_err:
        diagnostics["database"]["write_probe"] = "FAILED"
        diagnostics["database"]["write_error"] = str(write_err)
        diagnostics["database"]["status"] = "UNHEALTHY"
        diagnostics["overall_status"] = "DEGRADED"
        alerts.append({
            "level": "CRITICAL",
            "type": "DATABASE_WRITE_FAILURE",
            "component": "database",
            "message": f"Database cluster upsert probe failed: {write_err}",
            "timestamp": now.isoformat(),
        })

    # 2. Check each connector plugin
    for plugin_id, plugin in registry._plugins.items():
        platform_value = plugin.platform.value if hasattr(plugin.platform, "value") else str(plugin.platform)
        breaker = registry._breakers.get(plugin_id)

        # Check credentials & expiry
        expires_at_str = None
        days_remaining = None
        auth_mgr = getattr(plugin, "_auth_manager", None) or getattr(plugin, "_browser_auth_manager", None)
        if auth_mgr and hasattr(auth_mgr, "get_auth_status"):
            try:
                auth_info = await auth_mgr.get_auth_status()
                # Parse expires_at from browser_session or direct fields
                exp_raw = None
                if isinstance(auth_info, dict):
                    if "browser_session" in auth_info and isinstance(auth_info["browser_session"], dict):
                        exp_raw = auth_info["browser_session"].get("expires_at")
                    elif "expires_at" in auth_info:
                        exp_raw = auth_info.get("expires_at")

                if exp_raw:
                    expires_at_str = str(exp_raw)
                    try:
                        exp_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                        days_remaining = (exp_dt - now).days
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            is_ok = await plugin.is_healthy()
            if is_ok:
                # Check if synthetic probe capability exists and whether it returns empty
                probe_status = "HEALTHY"
                remediation = None

                # A connector can be healthy for one surface and blocked on another. TikTok's
                # explore grid needs no login while its keyword search does, and reporting only
                # HEALTHY hid the reason a research mission got nothing back from it.
                if hasattr(plugin, "keyword_search_blocked_reason"):
                    try:
                        blocked = await plugin.keyword_search_blocked_reason()
                    except Exception as be:
                        blocked = f"Could not determine keyword-search readiness: {be}"
                    # Only a real message counts. hasattr is true of any mock, and this report
                    # is serialised to JSON, so anything that is not a string would land in the
                    # payload and break the whole diagnostic rather than one connector's entry.
                    if not isinstance(blocked, str) or not blocked.strip():
                        blocked = None
                    if blocked:
                        remediation = blocked
                        alerts.append({
                            "level": "WARNING",
                            "type": "KEYWORD_SEARCH_BLOCKED",
                            "component": plugin.name,
                            "message": blocked,
                            "timestamp": now.isoformat(),
                        })

                if hasattr(plugin, "synthetic_probe"):
                    try:
                        probe_res = await plugin.synthetic_probe()
                        if isinstance(probe_res, list) and len(probe_res) == 0:
                            probe_status = "PARSE_EMPTY"
                            remediation = f"Probe to {plugin.name} returned 0 elements. Endpoint schema or selector may have changed."
                            diagnostics["overall_status"] = "DEGRADED"
                            alerts.append({
                                "level": "ERROR",
                                "type": "PROBE_RETURNED_EMPTY",
                                "component": plugin.name,
                                "message": remediation,
                                "timestamp": now.isoformat(),
                            })
                    except Exception as pe:
                        probe_status = "DEGRADED"
                        remediation = f"Synthetic probe error: {pe}"
                        diagnostics["overall_status"] = "DEGRADED"

                diagnostics["connectors"][plugin.name] = {
                    "plugin_id": plugin_id,
                    "platform": platform_value,
                    "status": probe_status,
                    "expires_at": expires_at_str,
                    "days_remaining": days_remaining,
                    "remediation": remediation,
                }
            else:
                # Determine reason: missing config vs expired vs unhealthy
                status_label = "UNHEALTHY"
                remediation = "Inspect connector connectivity, logs, and API status."

                if hasattr(plugin, "resolve_auth_tier"):
                    tier, cred = await plugin.resolve_auth_tier()
                    if tier == "none":
                        status_label = "NOT_CONFIGURED"
                        remediation = f"Platform is not authenticated. Run authenticate_{platform_value}(browser_login=True) or supply OAuth credentials."
                    else:
                        status_label = "CREDENTIAL_EXPIRED"
                        remediation = f"Credentials for {platform_value} appear expired or invalid. Re-authenticate using authenticate_{platform_value}()."
                elif plugin.platform == PlatformType.YOUTUBE and not getattr(plugin, "_api_key", None):
                    status_label = "NOT_CONFIGURED"
                    remediation = "YOUTUBE_API_KEY is not set in environment or config. Set YOUTUBE_API_KEY to enable YouTube Data API."

                if breaker and hasattr(breaker, "record_failure"):
                    try:
                        breaker.record_failure(RuntimeError(f"Health check failed: {status_label}"))
                        if getattr(breaker, "failure_count", 0) >= 2:
                            alerts.append({
                                "level": "CRITICAL",
                                "type": "CIRCUIT_BREAKER_OPEN",
                                "component": plugin.name,
                                "message": f"Circuit breaker for {plugin.name} tripped to OPEN after {breaker.failure_count} consecutive failures.",
                                "timestamp": now.isoformat(),
                            })
                    except Exception:
                        pass

                diagnostics["connectors"][plugin.name] = {
                    "plugin_id": plugin_id,
                    "platform": platform_value,
                    "status": status_label,
                    "expires_at": expires_at_str,
                    "days_remaining": days_remaining,
                    "remediation": remediation,
                }
                diagnostics["overall_status"] = "DEGRADED"
        except Exception as e:
            if breaker and hasattr(breaker, "record_failure"):
                try:
                    breaker.record_failure(e)
                    if getattr(breaker, "failure_count", 0) >= 2:
                        alerts.append({
                            "level": "CRITICAL",
                            "type": "CIRCUIT_BREAKER_OPEN",
                            "component": plugin.name,
                            "message": f"Circuit breaker for {plugin.name} tripped to OPEN after {breaker.failure_count} consecutive failures.",
                            "timestamp": now.isoformat(),
                        })
                except Exception:
                    pass

            diagnostics["connectors"][plugin.name] = {
                "plugin_id": plugin_id,
                "platform": platform_value,
                "status": "ERROR",
                "error": str(e),
                "expires_at": expires_at_str,
                "days_remaining": days_remaining,
                "remediation": "Check system logs or network access to diagnose connector failure.",
            }
            diagnostics["overall_status"] = "DEGRADED"

    # 3. Credential expiry & staggered refresh planning across every stored Tier-1 session
    try:
        refresh_plan = plan_staggered_refresh(await repo.list_platform_credentials(), now=now)
        diagnostics["credential_refresh_plan"] = refresh_plan
        expiry_alerts = build_expiry_alerts(refresh_plan, now=now)
        alerts.extend(expiry_alerts)
        if any(a["level"] == "CRITICAL" for a in expiry_alerts):
            diagnostics["overall_status"] = "DEGRADED"
    except Exception as e:
        logger.warning(f"Could not build credential refresh plan: {e}")

    # Persist alerts to audit log
    diagnostics["alerts"] = alerts
    for a in alerts:
        try:
            await repo.log_event(
                component=a.get("component", "system"),
                event_type=a.get("type", "ALERT"),
                message=a.get("message", ""),
                level=a.get("level", "WARNING"),
                details=a,
            )
        except Exception:
            pass

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
    """Full documentation of the fn-ignis 6-Step Market Research Reference Framework."""
    return SOP_FRAMEWORK_DOC


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


def _register_shutdown_handlers():
    """Register graceful teardown on SIGINT/SIGTERM to close connection pool."""
    import asyncio
    import signal

    def _on_signal():
        logger.info("Received termination signal, shutting down ignis MCP server...")
        global _COMPONENTS
        if _COMPONENTS and "repository" in _COMPONENTS:
            repo = _COMPONENTS["repository"]
            if hasattr(repo, "close"):
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(repo.close())
                except Exception:
                    pass

    try:
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _on_signal)
    except (NotImplementedError, RuntimeError):
        pass


def main():
    """Main CLI entry point for the fn-ignis FastMCP server.

    Startup does not look for, signal, or terminate any other process. A stdio server belongs
    to the client that spawned it and exits when that client closes the pipe, so another
    server matching the same command line is a different client's, not a leak. Startup used to
    pgrep for "ignis.interfaces.mcp.server" and SIGTERM every match, which meant opening a
    second editor killed the first one's server mid-session.
    """
    _register_shutdown_handlers()
    mcp.run()


if __name__ == "__main__":
    main()







