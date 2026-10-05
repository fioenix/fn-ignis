import asyncio
from contextlib import asynccontextmanager
import json
import logging
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid
from urllib.parse import urlsplit
from uuid import UUID


# Ensure MCP compatibility bridge before importing FastMCP
import mcp.shared.exceptions
if not hasattr(mcp.shared.exceptions, "McpError") and hasattr(mcp.shared.exceptions, "MCPError"):
    mcp.shared.exceptions.McpError = mcp.shared.exceptions.MCPError

from fastmcp import Context, FastMCP

from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_market_revision import CreateMarketRevisionUseCase
from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
from ignis.application.use_cases.get_evidence_qualification_batch import (
    DEFAULT_BATCH_LIMIT,
    GetEvidenceQualificationBatchUseCase,
)
from ignis.application.use_cases.get_mission_analysis import (
    GetMissionAnalysisUseCase,
    load_qualification_context,
)
from ignis.application.use_cases.get_mission_claims import GetMissionClaimsUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.application.use_cases.submit_evidence_qualifications import (
    SubmitEvidenceQualificationsUseCase,
)
from ignis.application.use_cases.get_top_clusters import GetTopClustersUseCase
from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.youtube_quota import YouTubeQuotaManager
from ignis.domain.entities import TopicCluster
from ignis.domain.harness_models import QualificationSummary
from ignis.domain.exceptions import IgnisDomainException, VocabularySynchronizationError
from ignis.domain.research_workspace import (
    RESEARCH_ROOT_SEGMENTS,
    REQUIRED_BRIEF_FIELDS,
    AuthorityBoundary,
    IncompleteMarketBriefError,
    InvalidMissionAuthorizationError,
    InvalidMissionManifestError,
    MissionManifest,
    MissionLineage,
    MissionTerminalStateError,
    MissionWriterConflictError,
    QualificationStatus,
    ResearchSurface,
    WorkspaceScopeMismatchError,
    opportunity_index_is_allowed,
    resolve_surface,
)
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

from ignis.config import reveal_secret, settings

from ignis.domain.token_rotation import (
    STATUS_EXPIRED,
    STATUS_EXPIRING_SOON,
    build_expiry_alerts,
    plan_staggered_refresh,
)
from ignis.domain.value_objects import (
    GeoCode,
    PlatformType,
    Timeframe,
    resolve_geo,
    resolve_platform,
    timeframe_to_days,
)
from ignis.domain.youtube_quota import YouTubeQuotaPolicy

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
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
from ignis.infrastructure.persistence import create_repository
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder

# Some official APIs authenticate in the query string. Keep HTTP client request URLs out of
# operator logs even when the host application configures the root logger at INFO.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger("ignis.mcp")

HARNESS_SYSTEM_INSTRUCTIONS = """
fn-ignis is an evidence-grounded social market research agent. Start collection or analysis only
for an explicit bounded task. Atomic source probes may answer a source question independently.
For Market analysis, confirm a mission and Brief before ingress, qualify the current evidence
frame, and render only claims permitted by the persisted Claim Ledger. Seek contrary evidence
and preserve unavailable channel states. An unsupported strategic verdict becomes a Gap Report,
not an Opportunity Index or a confident narrative. Stop work at the mission's terminal state.
Collection and analysis are separate capabilities; choose only what the requester assigned.
"""

SOP_FRAMEWORK_DOC = """
# Mission-bound social market research reference

For a source-specific request, make a bounded atomic probe and report provenance and channel
state; do not manufacture a Market conclusion. For a Market decision, confirm the mission and
Brief, including alternatives, null hypothesis, falsifiers, kill criteria, and revision rule.
Collect only the approved plan, qualify support and contradiction by the same standard, submit
current-frame claim candidates, and read the Claim Ledger before rendering. If a gate fails,
return the Gap Report and smallest next probe. An HTML report is optional and user-requested.
The mission and Claim Ledger contracts, not this recipe, decide verdict eligibility.
"""

class _MissionRelayRuntime:
    """Lazy read-only composition, owned by one FastMCP async lifespan."""

    def __init__(self):
        self.owner_loop = asyncio.get_running_loop()
        self.listener = None
        self.closed = False
        self._projection = None
        self._reads = None

    def read_service(self):
        if self.closed or asyncio.get_running_loop() is not self.owner_loop:
            raise RuntimeError("Mission viewer requires an active owning lifespan.")
        if self._reads is None:
            from ignis.infrastructure.mission_relay import MissionRelayReadService
            self._reads = MissionRelayReadService(provider=self, owner_loop=self.owner_loop)
        return self._reads

    def _use_case(self):
        if self.closed or asyncio.get_running_loop() is not self.owner_loop:
            raise RuntimeError("Mission viewer requires an active owning lifespan.")
        if self._projection is None:
            from ignis.application.use_cases.get_mission_relay_snapshot import GetMissionRelaySnapshotUseCase
            from ignis.infrastructure.persistence.mission_relay_reader import (
                PostgresMissionRelayReader, SqliteMissionRelayReader,
            )
            from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
            from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
            # Borrow initialized in-memory storage only when the owner already created it.
            repository = _COMPONENTS.get("repository") if _COMPONENTS is not None else None
            if isinstance(repository, SqliteTrendRepository):
                reader = SqliteMissionRelayReader(repository)
            elif isinstance(repository, PostgresTimescaleRepository):
                reader = PostgresMissionRelayReader(repository)
            else:
                dsn = reveal_secret(settings.DATABASE_URL)
                if dsn.startswith("sqlite:///"):
                    reader = SqliteMissionRelayReader(dsn.removeprefix("sqlite:///"))
                elif dsn.startswith(("postgresql://", "postgres://")):
                    reader = PostgresMissionRelayReader(dsn)
                else:
                    raise ValueError("Unsupported viewer storage identity.")
            self._projection = GetMissionRelaySnapshotUseCase(reader)
        return self._projection

    async def authorize_view(self, mission_id, run_id):
        from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
        from ignis.domain.mission_relay import MissionRelayReadFailure
        result = await self.snapshot(MissionRelayReadRequest(mission_id=mission_id, run_id=run_id, page_size=1))
        return result if type(result) is MissionRelayReadFailure else None

    async def snapshot(self, request):
        from ignis.domain.mission_relay import MissionRelayReadFailure, RelayReadReason, RelayReadStatus
        try:
            return await self._use_case().execute(request)
        except (ValueError, RuntimeError):
            return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE)

    async def inspect(self, request, observation_id):
        from ignis.domain.mission_relay import MissionRelayReadFailure, RelayReadReason, RelayReadStatus
        try:
            return await self._use_case().inspect(request, observation_id)
        except (ValueError, RuntimeError):
            return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE)

    async def close(self):
        self.closed = True
        resources = [resource for resource in (self.listener, self._reads) if resource is not None]
        for resource in resources:
            resource.close()
        from ignis.application.cancellation import await_settled
        async def settle():
            for resource in resources:
                if not await resource.wait_closed(timeout=None):
                    raise RuntimeError("Mission viewer reads did not settle during shutdown.")
        await await_settled(settle())


@asynccontextmanager
async def _mission_relay_lifespan(server):
    runtime = _MissionRelayRuntime()
    try:
        yield {"mission_relay": runtime}
    finally:
        await runtime.close()


# Initialize FastMCP Server with Non-Prescriptive Harness Instructions
mcp = FastMCP("fn-ignis-social-market-research", instructions=HARNESS_SYSTEM_INSTRUCTIONS,
              lifespan=_mission_relay_lifespan)

def _relay_failure(reason, unavailable=False):
    from ignis.domain.mission_relay import MissionRelayReadFailure, RelayReadStatus
    return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE if unavailable else RelayReadStatus.REFUSED,
                                   reason_code=reason)


async def handle_open_mission_relay(mission_id: str, expires_at: str, run_id: Optional[str] = None,
                                    *, runtime: Optional[_MissionRelayRuntime] = None):
    """Validate finite selected scope before any listener or component work."""
    from ignis.domain.mission_relay import MissionRelayOpenResult, RelayReadReason
    try:
        mission = UUID(mission_id)
        run = UUID(run_id) if run_id is not None else None
    except (ValueError, TypeError, AttributeError):
        return _relay_failure(RelayReadReason.SCOPE_MISMATCH)
    try:
        deadline = datetime.fromisoformat(expires_at)
        now = datetime.now(timezone.utc)
        if deadline.tzinfo is None or deadline.utcoffset() != timedelta(0) or not now < deadline <= now + timedelta(minutes=60):
            raise ValueError
    except (ValueError, TypeError):
        return _relay_failure(RelayReadReason.INVALID_EXPIRY)
    if runtime is None or runtime.closed or runtime.owner_loop is not asyncio.get_running_loop():
        return _relay_failure(RelayReadReason.READ_UNAVAILABLE, True)
    refusal = await runtime.read_service().authorize_view(mission, run, deadline)
    if refusal is not None:
        return refusal
    if runtime.closed:
        return _relay_failure(RelayReadReason.READ_UNAVAILABLE, True)
    if deadline <= datetime.now(timezone.utc):
        return _relay_failure(RelayReadReason.INVALID_EXPIRY)
    if runtime.listener is None:
        from ignis.infrastructure.mission_relay import MissionRelayHTTP
        runtime.listener = MissionRelayHTTP(provider=runtime, owner_loop=runtime.owner_loop)
    capability = await runtime.listener.open_view(mission_id=mission, run_id=run, expires_at=deadline)
    from ignis.domain.mission_relay import MissionRelayReadFailure
    if type(capability) is MissionRelayReadFailure:
        return capability
    return MissionRelayOpenResult(mission_id=mission, run_id=run, url=capability.url, expires_at=capability.expires_at)


async def handle_get_mission_relay_snapshot(mission_id: str, page_size: int, run_id: Optional[str] = None,
        after_revision: Optional[int] = None, after_ordinal: Optional[int] = None, evidence_offset: int = 0,
        *, runtime: Optional[_MissionRelayRuntime] = None):
    """Independently read a bounded selected projection without opening a browser."""
    from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
    from ignis.domain.mission_relay import MissionRelayCursor, RelayReadReason
    try:
        mission = UUID(mission_id)
        run = UUID(run_id) if run_id is not None else None
    except (ValueError, TypeError, AttributeError):
        return _relay_failure(RelayReadReason.SCOPE_MISMATCH)
    if type(page_size) is not int or not 1 <= page_size <= 200:
        return _relay_failure(RelayReadReason.INVALID_PAGE_SIZE)
    try:
        cursor = None
        if after_revision is not None or after_ordinal is not None:
            cursor = MissionRelayCursor(mission_id=mission, revision=after_revision, ordinal=after_ordinal)
        request = MissionRelayReadRequest(mission_id=mission, run_id=run, page_size=page_size,
                                         after_cursor=cursor, evidence_offset=evidence_offset)
    except ValueError:
        return _relay_failure(RelayReadReason.INVALID_REQUEST)
    if runtime is None or runtime.closed or runtime.owner_loop is not asyncio.get_running_loop():
        return _relay_failure(RelayReadReason.READ_UNAVAILABLE, True)
    return await runtime.read_service().read_snapshot(request)


@mcp.tool(name="open_mission_relay", description="Open a finite read-only local viewer for one explicitly selected mission and optional run. Requires an explicit UTC deadline; validates installed storage without bootstrap or collectors.")
async def open_mission_relay(mission_id: str, expires_at: str, ctx: Context, run_id: Optional[str] = None) -> dict:
    result = await handle_open_mission_relay(mission_id, expires_at, run_id,
                                           runtime=ctx.lifespan_context.get("mission_relay"))
    return result.to_payload()


@mcp.tool(name="get_mission_relay_snapshot", description="Read an allowlisted bounded coherent snapshot for one selected mission and optional run, without opening a viewer. Page size is explicit; cursors and evidence offsets remain selected-scope reads.")
async def get_mission_relay_snapshot(mission_id: str, page_size: int, ctx: Context,
        run_id: Optional[str] = None, after_revision: Optional[int] = None,
        after_ordinal: Optional[int] = None, evidence_offset: int = 0) -> dict:
    result = await handle_get_mission_relay_snapshot(mission_id, page_size, run_id, after_revision,
        after_ordinal, evidence_offset, runtime=ctx.lifespan_context.get("mission_relay"))
    return result.to_payload()


# This service opens no listener until an explicitly authorized finite request is prepared.
_host_browser_search_service = HostBrowserSearchService()


async def handle_prepare_host_browser_search(
    host_task_ref: str, session_ref: str, queries: List[str], result_limit: int,
    lifetime_seconds: int, authorized: bool, mode: str = "TACTICAL", mission_id: Optional[str] = None,
) -> dict:
    try:
        if mode == "MISSION":
            if not mission_id or queries or result_limit != 20 or authorized is not True:
                raise ValueError("Mission queries and limits derive from confirmed authority")
            comp = get_components()
            mission = await comp["repository"].get_mission(mission_id)
            if mission is None:
                raise ValueError("Mission not found")
            return await _host_browser_search_service.prepare_mission(
                comp["execute_mission_use_case"], mission.id, host_task_ref, session_ref,
                lifetime_seconds, authorized,
            )
        if mode != "TACTICAL" or mission_id is not None:
            raise ValueError("Invalid host search mode")
        return _host_browser_search_service.prepare(
            host_task_ref, session_ref, queries, result_limit, lifetime_seconds, authorized,
        )
    except (ValueError, InvalidMissionAuthorizationError, InvalidMissionManifestError):
        return {"status": "BLOCKED", "reason_code": "INVALID_HOST_SEARCH_SCOPE"}


@mcp.tool(name="prepare_host_browser_search")
async def prepare_host_browser_search(
    host_task_ref: str, session_ref: str, queries: List[str], result_limit: int,
    lifetime_seconds: int, authorized: bool, mode: str = "TACTICAL", mission_id: Optional[str] = None,
) -> dict:
    """Prepare one explicit finite public TikTok search batch through an authorized host browser.

    This opt-in loopback relay does not export cookies or collect in the background. TACTICAL
    creates no mission. MISSION requires an existing confirmed mission_id, queries=[] and
    result_limit=20; its full query union and limit derive from authority, including falsifiers.
    The host executes the packaged deterministic extractor and stages its JSON via
    the same-origin local form. It is not a default collector or a Market recommendation.
    """
    return await handle_prepare_host_browser_search(
        host_task_ref, session_ref, queries, result_limit, lifetime_seconds, authorized, mode, mission_id,
    )


async def handle_submit_host_browser_search(request_id: str, host_task_ref: str, session_ref: str) -> dict:
    try:
        if _host_browser_search_service.mode(request_id, host_task_ref, session_ref) == "MISSION":
            return await _host_browser_search_service.submit_mission(
                get_components()["execute_mission_use_case"], request_id, host_task_ref, session_ref,
            )
        return _host_browser_search_service.submit(request_id, host_task_ref, session_ref)
    except Exception as exc:
        if hasattr(exc, "host_search_failure"):
            return exc.host_search_failure
        return {"status": "BLOCKED", "reason_code": "HOST_SEARCH_NOT_ACCEPTABLE"}


@mcp.tool(name="submit_host_browser_search")
async def submit_host_browser_search(request_id: str, host_task_ref: str, session_ref: str) -> dict:
    """Consume a validated answer already staged through this task's local host-browser relay.

    No raw records need to be copied into model tool arguments. TACTICAL returns observations;
    MISSION revalidates scope under its existing writer and returns its canonical run/frame.
    Unknown counters/windows stay unmeasured. Failed ingestion requires journal/frame readback,
    not a retry. Accepted replay returns the cached receipt. Never returns commercial claims.
    """
    return await handle_submit_host_browser_search(request_id, host_task_ref, session_ref)


async def handle_cancel_host_browser_search(request_id: str, host_task_ref: str, session_ref: str) -> dict:
    try:
        return _host_browser_search_service.cancel(request_id, host_task_ref, session_ref)
    except ValueError:
        return {"status": "BLOCKED", "reason_code": "HOST_SEARCH_CANNOT_CANCEL"}


@mcp.tool(name="cancel_host_browser_search")
async def cancel_host_browser_search(request_id: str, host_task_ref: str, session_ref: str) -> dict:
    """Cancel a task-bound host search and close its listener, not the owner's browser or tabs."""
    return await handle_cancel_host_browser_search(request_id, host_task_ref, session_ref)



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
        registry.register(
            YouTubeDataPlugin(
                api_key=reveal_secret(settings.YOUTUBE_API_KEY),
                quota_manager=YouTubeQuotaManager(
                    repository,
                    YouTubeQuotaPolicy(
                        search_daily_limit=settings.YOUTUBE_SEARCH_DAILY_LIMIT,
                        other_daily_unit_limit=settings.YOUTUBE_OTHER_DAILY_UNIT_LIMIT,
                    ),
                ),
            )
        )

    clusterer = SemanticClusterer()
    artifact_builder = HtmlArtifactBuilder()
    # One detector, shared, so its vocabulary is loaded once rather than per engine.
    language_detector = HeuristicLanguageDetector()
    quality_evaluator = QualityEvaluator(detector=language_detector)
    strategic_reasoner = StrategicMarketReasoner(detector=language_detector)

    workspace_store = WorkspaceRepository(repository=repository)
    # One synchronizer for every entry point, so the first mission after startup registers the
    # same persisted vocabulary a process warmed by an analysis call would already hold.
    vocabulary_synchronizer = VocabularySynchronizer(
        repository,
        quality_evaluator=quality_evaluator,
        strategic_reasoner=strategic_reasoner,
        clusterer=clusterer,
        google_trends_plugin=google_trends_plugin,
        language_detector=language_detector,
        tiktok_plugin=tiktok_plugin,
        registry=registry,
    )

    execute_mission_use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=clusterer,
        workspace_store=workspace_store,
        vocabulary_sync=vocabulary_synchronizer,
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
    # Every Brief confirmation goes through the lineage-aware door, including one that names no
    # parent: a handoff that points at another research's Attention mission has to be refused
    # before a mission is written, not discovered afterwards in the lineage column.
    create_market_revision_use_case = CreateMarketRevisionUseCase(
        repository=repository,
        store=workspace_store,
        confirm_use_case=confirm_market_brief_use_case,
    )
    get_mission_analysis_use_case = GetMissionAnalysisUseCase(
        repository=repository, store=workspace_store
    )
    get_evidence_qualification_batch_use_case = GetEvidenceQualificationBatchUseCase(
        repository=repository, store=workspace_store
    )
    submit_evidence_qualifications_use_case = SubmitEvidenceQualificationsUseCase(
        repository=repository, store=workspace_store
    )
    submit_mission_claims_use_case = SubmitMissionClaimsUseCase(
        repository=repository, store=workspace_store
    )
    get_mission_claims_use_case = GetMissionClaimsUseCase(
        repository=repository, store=workspace_store
    )
    top_clusters_use_case = GetTopClustersUseCase(repository=repository)
    ingest_use_case = IngestTrendsUseCase(registry=registry, repository=repository)

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
        "workspace_store": workspace_store,
        "vocabulary_synchronizer": vocabulary_synchronizer,
        "create_research_workspace_use_case": create_research_workspace_use_case,
        "create_attention_mission_use_case": create_attention_mission_use_case,
        "confirm_market_brief_use_case": confirm_market_brief_use_case,
        "create_market_revision_use_case": create_market_revision_use_case,
        "execute_mission_use_case": execute_mission_use_case,
        "get_mission_analysis_use_case": get_mission_analysis_use_case,
        "get_evidence_qualification_batch_use_case": get_evidence_qualification_batch_use_case,
        "submit_evidence_qualifications_use_case": submit_evidence_qualifications_use_case,
        "submit_mission_claims_use_case": submit_mission_claims_use_case,
        "get_mission_claims_use_case": get_mission_claims_use_case,
        "top_clusters_use_case": top_clusters_use_case,
        "ingest_use_case": ingest_use_case,
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
        # Whether the reader is looking at evidence collected for this Brief or at the Attention
        # context the question came from. Without it the two read identically.
        "evidence_role": getattr(cit, "evidence_role", None),
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


def _missing_market_analysis_contract() -> Dict[str, Any]:
    """Fail closed when a Market boundary cannot read the persisted verdict contract."""
    return {
        "analysis_status": "INSUFFICIENT_EVIDENCE",
        "gap_report": {
            "withheld_outputs": [
                "opportunity_index",
                "demand_gap",
                "whitespace",
                "saturation",
                "commercial_recommendations",
            ],
            "failed_gates": ["PERSISTED_ANALYSIS_CONTRACT_UNAVAILABLE"],
            "missing_evidence": ["current-frame persisted sufficiency and Claim Ledger"],
            "attempted_probes": [],
            "safe_partial_conclusions": [],
            "next_best_probe": (
                "Restore the mission evidence frame and read persisted sufficiency before "
                "requesting analysis again."
            ),
            "required_authority": None,
            "estimated_cost": None,
        },
        "withheld_claim_count": 0,
        "withheld_reasons": ["PERSISTED_ANALYSIS_CONTRACT_UNAVAILABLE"],
    }


def _external_context_only_refusal(mission_id: str) -> Optional[str]:
    """Refuse file and URL inputs before they can be mistaken for a Market mission."""
    if not isinstance(mission_id, str):
        return None
    value = mission_id.strip()
    lower = value.lower()
    if not (
        value.startswith(("{", "["))
        or lower.startswith(("http://", "https://", "file://"))
        or lower.endswith((".csv", ".tsv", ".json", ".xlsx", ".parquet"))
    ):
        return None
    return json.dumps(
        {
            "status": "CONTEXT_ONLY",
            "reason_code": "MISSION_SCOPED_PROVENANCE_REQUIRED",
            "primary_market_evidence": False,
            "next_step": (
                "Use the supplied material to frame a question, then collect or verify its "
                "evidence through an authorized mission and qualify it against the current frame."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


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
    if getattr(opp, "evidence_sufficiency", None):
        payload["evidence_sufficiency"] = opp.evidence_sufficiency
        payload["qualified_demand_count"] = opp.qualified_demand_count
        payload["qualified_supply_count"] = opp.qualified_supply_count
        payload["independent_supply_sources"] = opp.independent_supply_sources
    if include_supporting:
        payload["supporting_signals"] = opp.supporting_signals[:include_supporting]
    return payload


def _surface_payload(report: Any, mission: Any) -> Dict[str, Any]:
    """What surface this analysis speaks for, and what that surface is allowed to say."""
    surface = resolve_surface(getattr(mission, "surface", None))
    qualification = getattr(report, "qualification", None)
    payload: Dict[str, Any] = {
        "surface": surface.value if surface else None,
        "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
        # A surfaced Market mission may carry an index only once its qualified evidence met the
        # minimum; a pending or insufficient assessment says so instead of printing a number.
        "opportunity_index_applies": opportunity_index_is_allowed(surface)
        and (qualification is None or qualification.status == QualificationStatus.READY.value),
    }
    payload.update(_qualification_payload(report))
    if surface is ResearchSurface.ATTENTION:
        payload["note"] = (
            "ATTENTION context. Ranked topics, momentum, freshness and source coverage are "
            "reported as candidates for investigation; no Opportunity Index and no commercial "
            "verdict are derived from them."
        )
    if getattr(report, "market_brief", None):
        payload["market_brief"] = report.market_brief
    lineage = getattr(report, "lineage", None)
    if lineage:
        payload["lineage"] = lineage
    context = getattr(report, "attention_context", None)
    if context:
        # Reported under its own key, never merged into the citation lists a conclusion is
        # traced through: a context observation beside an opportunity reads as support for it.
        payload["attention_context"] = [_serialize_citation(c) for c in context]
        payload["attention_context_note"] = (
            "Observations carried from the parent Attention mission. They record where this "
            "question came from and are not counted as support for this Brief."
        )
    return payload


def _qualification_payload(report: Any) -> Dict[str, Any]:
    """The qualification block every analysis boundary returns, in one place so they agree.

    Empty for a mission that declared no surface, which keeps its legacy payload unchanged.
    """
    qualification = getattr(report, "qualification", None)
    if qualification is None:
        return {}
    payload: Dict[str, Any] = {
        "analysis_status": qualification.status,
        "qualification": qualification.to_payload(),
    }
    # Decided by decide_qualification, the authority the batch and submit tools answer from too.
    if qualification.next_step:
        payload["next_step"] = qualification.next_step
    if getattr(report, "topic_sufficiency", None):
        payload["topic_sufficiency"] = report.topic_sufficiency
    if getattr(report, "handoff_status", None):
        payload["handoff_status"] = report.handoff_status
        payload["qualified_handoff_candidates"] = [
            {**c, "citations": [_serialize_citation(x) for x in c.get("citations", [])]}
            for c in report.qualified_handoff_candidates
        ]
        payload["cluster_qualification"] = report.cluster_qualification
    return payload


def _maturity_value(report: Any) -> Optional[str]:
    stage = getattr(report, "maturity_stage", None)
    return stage.value if stage is not None else None


async def _qualification_for(comp: Dict[str, Any], mission: Any, signals: List[Any]):
    """The persisted qualification context for a surfaced mission, or None for a legacy one."""
    store = comp.get("workspace_store")
    if store is None:
        return None
    return await load_qualification_context(store, mission, signals)


async def _attention_context_signals(comp: Dict[str, Any], mission: Any) -> List[Any]:
    """The observations of the Attention mission this one was handed off from.

    Read only when lineage names a parent, and never merged into the mission's own evidence:
    they are carried so a reader can see the origin of the question, and the analysis keeps them
    out of everything it concludes.
    """
    parent_id = getattr(mission, "parent_attention_mission_id", None)
    if not parent_id:
        return []
    return await comp["repository"].get_mission_signals(parent_id)


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


def _vocabulary_synchronizer(comp: Dict[str, Any]) -> VocabularySynchronizer:
    """The shared synchronizer, or one bound to whatever engines this component map holds."""
    synchronizer = comp.get("vocabulary_synchronizer")
    if synchronizer is not None:
        return synchronizer
    return VocabularySynchronizer(
        comp["repository"],
        quality_evaluator=comp.get("quality_evaluator"),
        strategic_reasoner=comp.get("strategic_reasoner"),
        clusterer=comp.get("clusterer"),
        google_trends_plugin=comp.get("google_trends_plugin"),
        language_detector=comp.get("language_detector"),
        tiktok_plugin=comp.get("tiktok_plugin"),
        registry=comp.get("registry"),
    )


async def _sync_lexicons_from_db(comp: Dict[str, Any]) -> None:
    """Sync every persisted vocabulary domain from the database into the engines that use it.

    Read paths stay tolerant: a failed read is logged and the handler carries on with what it has.
    Mission ingress does not go through here -- ExecuteMissionUseCase synchronizes on its own and
    refuses to run under a partial configuration.
    """
    try:
        await _vocabulary_synchronizer(comp).synchronize_vocabulary()
    except Exception as e:
        logger.warning(f"Could not sync dynamic lexicons from DB: {e}")

    await _sync_self_identities(comp)


async def _sync_self_identities(comp: Dict[str, Any]) -> None:
    """Bind the operator's own connected accounts so market passes can exclude their content."""
    try:
        comp["self_identities"] = await _vocabulary_synchronizer(comp).synchronize_self_identities()
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
    qualification = await _qualification_for(comp, mission, signals)
    extra: Dict[str, Any] = {}
    if resolve_surface(mission.surface) is ResearchSurface.MARKET:
        contract = await comp["get_mission_analysis_use_case"].execute(m_id)
        if "analysis_status" not in contract:
            contract = _missing_market_analysis_contract()
        extra = {
            "analysis_status": contract["analysis_status"],
            **({"gap_report": contract["gap_report"]} if "gap_report" in contract else {}),
            **({"qualification": contract["qualification"]} if "qualification" in contract else {}),
        }
        if qualification is not None:
            progress = qualification.progress
            status = (
                QualificationStatus.READY
                if contract["analysis_status"] == "READY"
                else qualification.decision.status
            )
            if status is QualificationStatus.READY and contract["analysis_status"] != "READY":
                status = QualificationStatus.INSUFFICIENT_RELEVANT_EVIDENCE
            comp["quality_evaluator"].apply_qualification(
                scorecard,
                QualificationSummary(
                    status=status.value,
                    total_evidence=progress.total_evidence,
                    qualified_support=progress.qualified_support,
                    context_only=progress.context_only,
                    excluded_irrelevant=progress.excluded_irrelevant,
                    unassessed=progress.unassessed,
                    question_relevance_score=progress.question_relevance_score,
                ),
            )
    elif qualification is not None:
        # Whether a conclusion is permitted decides the confidence cap, so the same analysis that
        # every other boundary runs decides it here too.
        clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
        report = comp["strategic_reasoner"].analyze_mission(
            mission=mission, signals=signals, clusters=clusters, scorecard=scorecard,
            qualification=qualification,
        )
        comp["quality_evaluator"].apply_qualification(scorecard, report.qualification)
        extra = _qualification_payload(report)

    return json.dumps(
        {
            "mission_id": str(mission.id),
            "coverage_score": scorecard.coverage_score,
            "language_precision": scorecard.language_precision,
            "data_freshness_score": scorecard.data_freshness_score,
            "creator_diversity_score": scorecard.creator_diversity_score,
            "question_relevance_score": scorecard.question_relevance_score,
            "qualification_counts": scorecard.qualification_counts,
            "overall_confidence": scorecard.overall_confidence,
            "confidence_level": scorecard.confidence_level.value,
            "flaws_detected": scorecard.flaws_detected,
            "strengths_detected": scorecard.strengths_detected,
            **extra,
        },
        ensure_ascii=False,
        indent=2
    )


async def handle_discover_market_opportunities(mission_id: str) -> str:
    external_refusal = _external_context_only_refusal(mission_id)
    if external_refusal is not None:
        return external_refusal
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
    
    analysis_contract = None
    report = None
    if resolve_surface(mission.surface) is ResearchSurface.MARKET:
        candidate = await comp["get_mission_analysis_use_case"].execute(m_id)
        analysis_contract = (
            candidate if "analysis_status" in candidate else _missing_market_analysis_contract()
        )
    if analysis_contract is None:
        auth_status, connector_health = await _collect_channel_context(comp)
        report = comp["strategic_reasoner"].analyze_mission(
            mission=mission,
            signals=signals,
            clusters=clusters,
            scorecard=scorecard,
            auth_status=auth_status,
            connector_health=connector_health,
            market_brief=brief,
            qualification=await _qualification_for(comp, mission, signals),
        )
        comp["quality_evaluator"].apply_qualification(scorecard, report.qualification)

    if analysis_contract is not None:
        return json.dumps(
            {
                "mission_id": str(mission.id),
                "shortcode": mission.shortcode,
                **analysis_contract,
            },
            ensure_ascii=False,
            indent=2,
        )

    return json.dumps(
        {
            "mission_id": str(mission.id),
            "maturity_stage": _maturity_value(report),
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


def _mission_manifest_from_payload(
    payload: Dict[str, Any], *, created_by: str, decision_context: Optional[str] = None
) -> MissionManifest:
    """Build the immutable domain contract from one host-confirmed public request."""
    authority = payload.get("authority_boundary")
    if not isinstance(authority, dict):
        raise InvalidMissionManifestError("authority_boundary must be an object of booleans.")
    resources = payload.get("allowed_resources") or payload.get("required_channels") or ()
    optional = payload.get("optional_resources") or payload.get("optional_channels") or ()
    return MissionManifest(
        outcome=payload.get("requested_outcome") or payload.get("outcome") or "",
        decision_context=payload.get("decision_context") or decision_context,
        required_channels=tuple(resources),
        optional_channels=tuple(optional),
        authority_boundary=AuthorityBoundary(
            public_http=authority.get("public_http"),
            official_api=authority.get("official_api"),
            browser_session=authority.get("browser_session"),
            paid_quota=authority.get("paid_quota"),
        ),
        quota_budget=payload.get("quota_budget") or {},
        output_type=payload.get("output_type", ""),
        stop_conditions=tuple(payload.get("stop_conditions") or ()),
        analysis_policy=payload.get("analysis_policy") or "evidence-gated-v1",
        retention_policy=payload.get("retention_policy") or "",
        created_by=created_by,
        confirmed_at=datetime.now(timezone.utc),
    )


async def handle_create_attention_mission(
    workspace_id: str,
    title: str,
    requested_outcome: str,
    allowed_resources: List[str],
    authority_boundary: Dict[str, bool],
    output_type: str,
    stop_conditions: List[str],
    retention_policy: str,
    geo: str = "VN",
    timeframe: str = "7d",
    seed: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    platforms: Optional[List[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
    quota_budget: Optional[Dict[str, int]] = None,
    analysis_policy: str = "evidence-gated-v1",
) -> str:
    comp = get_components()
    try:
        manifest = _mission_manifest_from_payload(
            {
                "requested_outcome": requested_outcome,
                "allowed_resources": allowed_resources,
                "authority_boundary": authority_boundary,
                "output_type": output_type,
                "stop_conditions": stop_conditions,
                "retention_policy": retention_policy,
                "quota_budget": quota_budget or {},
                "analysis_policy": analysis_policy,
            },
            created_by=agent,
        )
        mission = await comp["create_attention_mission_use_case"].execute(
            workspace_id=UUID(workspace_id),
            title=title,
            manifest=manifest,
            keywords=keywords,
            seed=seed,
            agent=agent,
            session_id=session_id,
            platforms=[resolve_platform(p) for p in platforms] if platforms else None,
            geo=resolve_geo(geo),
            timeframe=timeframe,
        )
        persisted_manifest = await comp["workspace_store"].get_mission_manifest(mission.id)
        if persisted_manifest is None:
            raise InvalidMissionManifestError(
                f"Mission {mission.id} was created without a readable persisted manifest."
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
            "manifest_digest": persisted_manifest.manifest_digest,
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
    mission_manifest: Dict[str, Any],
    falsifiers: Optional[List[str]] = None,
    alternative_hypotheses: Optional[List[str]] = None,
    null_hypothesis: Optional[str] = None,
    kill_criteria: Optional[List[str]] = None,
    revision_rule: Optional[str] = None,
    confirmed_by: str = "",
    title: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    parent_attention_mission_id: Optional[str] = None,
    parent_cluster_id: Optional[str] = None,
    previous_mission_id: Optional[str] = None,
    platforms: Optional[List[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    comp = get_components()
    try:
        manifest = _mission_manifest_from_payload(
            mission_manifest,
            created_by=confirmed_by or agent,
            decision_context=decision,
        )
        mission, revision = await comp["create_market_revision_use_case"].execute(
            workspace_id=UUID(workspace_id),
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=falsifiers or [],
            alternative_hypotheses=alternative_hypotheses,
            null_hypothesis=null_hypothesis,
            kill_criteria=kill_criteria,
            revision_rule=revision_rule,
            confirmed_by=confirmed_by,
            manifest=manifest,
            title=title,
            keywords=keywords,
            # None when the caller named no parent, which is not the same request as a lineage
            # saying there is none: a revision of a mission that came from a handoff inherits
            # that origin, and an empty lineage object would read as the caller clearing it.
            lineage=(
                MissionLineage(
                    parent_attention_mission_id=(
                        UUID(parent_attention_mission_id)
                        if parent_attention_mission_id else None
                    ),
                    parent_cluster_id=UUID(parent_cluster_id) if parent_cluster_id else None,
                )
                if (parent_attention_mission_id or parent_cluster_id)
                else None
            ),
            previous_mission_id=UUID(previous_mission_id) if previous_mission_id else None,
            agent=agent,
            session_id=session_id,
            platforms=[resolve_platform(p) for p in platforms] if platforms else None,
        )
        persisted_manifest = await comp["workspace_store"].get_mission_manifest(mission.id)
        if persisted_manifest is None:
            raise InvalidMissionManifestError(
                f"Mission {mission.id} was created without a readable persisted manifest."
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
            "hypothesis_register": {
                "core": revision.core_hypothesis,
                "alternatives": list(revision.alternative_hypotheses or ()),
                "null": revision.null_hypothesis,
                "kill_criteria": list(revision.kill_criteria or ()),
                "revision_rule": revision.revision_rule,
            },
            "manifest_digest": persisted_manifest.manifest_digest,
            # Read back off the stored mission, not echoed from the request: what the next
            # Agent host will find in the database is the only lineage worth reporting.
            "lineage": MissionLineage.of_mission(mission).to_payload(),
            "note": (
                "This revision is immutable. Changing any required field creates a new revision "
                "and a new Market mission rather than rewriting this one, and the new mission "
                "records this one in revises_mission_id. Attention lineage is context; it is "
                "not counted as support for this hypothesis."
            ),
            "next_step": f"Call execute_mission_ingress(mission_id='{mission.shortcode}').",
        },
        ensure_ascii=False,
        indent=2,
    )


# --- Handlers for Research Missions ---

async def _mission_writer_conflict(comp: Dict[str, Any], mission: Any, detail: str) -> str:
    """The one refusal a second writer gets, naming the run it is waiting for.

    The active run is read back rather than guessed at, because "someone else is writing" is
    not actionable on its own: the run id and the time it took the mission are what let an
    operator tell an active run from one that died holding the slot.
    """
    claim = None
    store = comp.get("workspace_store")
    if store is not None:
        claim = await store.get_mission_writer_claim(mission.id)
    return json.dumps(
        {
            "status": "CONFLICT",
            "operation": "execute_mission_ingress",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
            "active_run_id": str(claim.run_id) if claim else None,
            "active_since": claim.claimed_at.isoformat()
            if claim and hasattr(claim.claimed_at, "isoformat")
            else None,
            "error": detail,
            "note": (
                "No probe ran and nothing was written, so the active run keeps its evidence "
                "and its journal. Wait for it to finish and read the result, or -- only if "
                "that run is known to have died -- recover the mission with "
                "release_mission_writer(mission_id, run_id) using exactly the active_run_id "
                "above. Other missions in this research are unaffected."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


def _workspace_scope_blocked(mission: Any, detail: str) -> str:
    """A mission whose research the database does not hold cannot be run anywhere.

    Refused as a result rather than an exception for the same reason as the Brief gate: the
    Agent needs to read which research is missing, not that the server raised. And refused
    before anything runs -- evidence written under a workspace nothing can address again is
    evidence lost in place.
    """
    return json.dumps(
        {
            "status": "BLOCKED",
            "operation": "execute_mission_ingress",
            "mission_id": str(mission.id),
            "shortcode": mission.shortcode,
            "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
            "error": detail,
            "note": (
                "No probe ran, no writer was claimed and no journal was written. Reopen or "
                "confirm the research workspace this mission belongs to, then run it again."
            ),
        },
        ensure_ascii=False,
        indent=2,
    )


async def handle_release_mission_writer(mission_id: str, run_id: str) -> str:
    """Give a mission back after the run holding it died, by naming that exact run.

    Both identifiers are required and both must match the claim on record. There is no expiry
    and no force: a claim released without naming its holder is a claim taken from a run that
    may still be writing, which is the failure the single writer slot exists to prevent. The
    run id is the one the CONFLICT payload reported.
    """
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps(
            {"error": f"No research mission found with ID or shortcode: '{mission_id}'"},
            ensure_ascii=False,
        )

    try:
        requested_run = UUID(run_id)
    except (TypeError, ValueError):
        return json.dumps(
            {
                "status": "CONFLICT",
                "operation": "release_mission_writer",
                "mission_id": str(mission.id),
                "error": (
                    f"'{run_id}' is not a run identifier. Pass the active_run_id exactly as the "
                    "conflict result reported it."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    store = comp["workspace_store"]
    claim = await store.get_mission_writer_claim(mission.id)
    payload: Dict[str, Any] = {
        "operation": "release_mission_writer",
        "mission_id": str(mission.id),
        "shortcode": mission.shortcode,
        "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
        "run_id": run_id,
        "active_run_id": str(claim.run_id) if claim else None,
    }

    if claim is None:
        payload["status"] = "NOT_FOUND"
        payload["note"] = (
            "This mission has no active writer, so there was nothing to release and nothing "
            "was changed. It can be run again as it is."
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    if claim.run_id != requested_run:
        payload["status"] = "CONFLICT"
        payload["active_since"] = (
            claim.claimed_at.isoformat()
            if hasattr(claim.claimed_at, "isoformat") else str(claim.claimed_at)
        )
        payload["error"] = (
            f"Mission {mission.id} is held by run {claim.run_id}, not by {requested_run}. "
            "The claim was not released."
        )
        payload["note"] = (
            "A claim is only ever released by naming the run that holds it. If that run is "
            "known to have died, call this again with active_run_id."
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    await store.release_mission_writer(mission.id, requested_run)
    remaining = await store.get_mission_writer_claim(mission.id)
    if remaining is not None:
        payload["status"] = "CONFLICT"
        payload["active_run_id"] = str(remaining.run_id)
        payload["error"] = (
            f"Mission {mission.id} is still held by run {remaining.run_id} after the release. "
            "Another run claimed it in the meantime."
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    payload["status"] = "RELEASED"
    payload["active_run_id"] = None
    payload["note"] = (
        "The writer slot is free and the mission can be run again. Nothing else was touched: "
        "the released run keeps whatever journal and evidence it had already written."
    )
    logger.warning(
        "Released the writer claim of run %s on mission %s at an operator's request.",
        requested_run,
        mission.id,
    )
    return json.dumps(payload, ensure_ascii=False, indent=2)


async def handle_execute_mission_ingress(mission_id: str) -> str:
    comp = get_components()
    mission = await comp["repository"].get_mission(mission_id)
    if not mission:
        return json.dumps({"error": f"No research mission found with ID or shortcode: '{mission_id}'"}, ensure_ascii=False)

    try:
        result = await comp["execute_mission_use_case"].execute(mission_id=mission.id)
    except InvalidMissionAuthorizationError as exc:
        return json.dumps(
            {
                "status": "BLOCKED",
                "operation": "execute_mission_ingress",
                "mission_id": str(mission.id),
                "shortcode": mission.shortcode,
                "reason_code": exc.reason_code,
                "missing_authority": list(exc.missing_authority),
                "out_of_scope_resources": list(exc.out_of_scope_resources),
                "quota_overruns": exc.quota_overruns,
                "error": str(exc),
                "note": "No connector session was opened and no run journal was created.",
            },
            ensure_ascii=False,
            indent=2,
        )
    except InvalidMissionManifestError as exc:
        return json.dumps(
            {
                "status": "BLOCKED",
                "operation": "execute_mission_ingress",
                "mission_id": str(mission.id),
                "reason_code": "MANIFEST_REQUIRED_OR_INVALID",
                "error": str(exc),
                "note": "No connector session was opened and no run journal was created.",
            },
            ensure_ascii=False,
            indent=2,
        )
    except MissionTerminalStateError as exc:
        return json.dumps(
            {
                "status": "TERMINAL",
                "operation": "execute_mission_ingress",
                "mission_id": str(mission.id),
                "terminal_state": exc.status,
                "reason_code": "MISSION_ALREADY_TERMINAL",
                "error": str(exc),
                "note": "No connector session was opened and no artifact was generated.",
            },
            ensure_ascii=False,
            indent=2,
        )
    except WorkspaceScopeMismatchError as exc:
        # Raised before the writer claim and before any connector call, so there is nothing to
        # undo -- only something to tell the Agent.
        return _workspace_scope_blocked(mission, detail=str(exc))
    except MissionWriterConflictError as exc:
        # A refusal, not a breakage. The run that holds the mission is still writing, and
        # raising past the tool boundary would reach the Agent as a transport error -- which
        # reads as "the server fell over" rather than "wait for the run that is already going".
        return await _mission_writer_conflict(comp, mission, detail=str(exc))
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
    except VocabularySynchronizationError as exc:
        # Refused before the writer claim and before any connector call, so no result exists that
        # was produced under a partial configuration.
        return json.dumps(
            {
                "status": "FAILED",
                "operation": "execute_mission_ingress",
                "mission_id": str(mission.id),
                "shortcode": mission.shortcode,
                "workspace_id": str(mission.workspace_id) if mission.workspace_id else None,
                "error": str(exc),
                "note": (
                    "No connector was called and no run was started: the persisted vocabulary "
                    "this mission depends on could not be loaded. Check the configured database, "
                    "then run the mission again."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

    result["shortcode"] = mission.shortcode
    result["display_label"] = f"[{mission.shortcode}] {mission.title}" 
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    external_refusal = _external_context_only_refusal(mission_id)
    if external_refusal is not None:
        return external_refusal
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

    if resolve_surface(mission.surface) is ResearchSurface.MARKET:
        if "analysis_status" not in analysis:
            analysis.update(_missing_market_analysis_contract())
        signals = await comp["repository"].get_mission_signals(mission.id)
        qualification = await _qualification_for(comp, mission, signals)
        if qualification is not None:
            for item in analysis["top_signals"]:
                judged = qualification.judgment_of(item.get("observation_id"))
                item["qualification_relation"] = (
                    judged.relation.value if judged else "UNASSESSED"
                )
                item["qualification_reason"] = judged.reason_code.value if judged else None
                item["hypothesis_target"] = judged.hypothesis_target if judged else None
                item["analytical_role"] = (
                    judged.evidence_role.value
                    if judged and judged.evidence_role is not None
                    else None
                )
        analysis["native_artifact_guideline"] = (
            "Render only the persisted current-frame Claim Ledger. If analysis_status is "
            "INSUFFICIENT_EVIDENCE, render the Gap Report and do not invent a verdict."
        )
        return json.dumps(analysis, ensure_ascii=False, indent=2)

    # Enrich with Scorecard & White Space discovery for in-chat Native Artifact rendering
    signals = await comp["repository"].get_mission_signals(mission.id)
    clusters = await comp["top_clusters_use_case"].execute(geo=mission.geo_code, limit=20)
    tf_days = timeframe_to_days(mission.timeframe)
    scorecard = comp["quality_evaluator"].evaluate_quality(signals, geo=mission.geo_code, timeframe_days=tf_days)
    auth_status, connector_health = await _collect_channel_context(comp)
    qualification = await _qualification_for(comp, mission, signals)
    report = comp["strategic_reasoner"].analyze_mission(
        mission=mission,
        signals=signals,
        clusters=clusters,
        scorecard=scorecard,
        auth_status=auth_status,
        connector_health=connector_health,
        market_brief=brief,
        attention_context_signals=await _attention_context_signals(comp, mission),
        qualification=qualification,
    )
    comp["quality_evaluator"].apply_qualification(scorecard, report.qualification)

    if qualification is not None:
        # Every raw observation stays readable, labelled with what its judgment made of it.
        for item in analysis["top_signals"]:
            judged = qualification.judgment_of(item.get("observation_id"))
            item["qualification_relation"] = judged.relation.value if judged else "UNASSESSED"
            item["qualification_reason"] = judged.reason_code.value if judged else None

    analysis["quality_scorecard"] = {
        "overall_confidence": scorecard.overall_confidence,
        "confidence_level": scorecard.confidence_level.value,
        "coverage_score": scorecard.coverage_score,
        "language_precision": scorecard.language_precision,
        "data_freshness_score": scorecard.data_freshness_score,
        "creator_diversity_score": scorecard.creator_diversity_score,
        "question_relevance_score": scorecard.question_relevance_score,
        "qualification_counts": scorecard.qualification_counts,
        "strengths": scorecard.strengths_detected,
        "flaws": scorecard.flaws_detected,
    }
    analysis["maturity_stage"] = _maturity_value(report)
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
        source_module = Path(__file__).resolve()
        project_root = source_module.parents[4]
        # An installed wheel has no checkout root; its library directory is not user output.
        if source_module == project_root / "src/ignis/interfaces/mcp/server.py":
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
    external_refusal = _external_context_only_refusal(mission_id)
    if external_refusal is not None:
        return external_refusal
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

    
    analysis_contract = None
    report = None
    if resolve_surface(mission.surface) is ResearchSurface.MARKET:
        candidate = await comp["get_mission_analysis_use_case"].execute(m_id)
        analysis_contract = (
            candidate if "analysis_status" in candidate else _missing_market_analysis_contract()
        )
    if analysis_contract is None:
        auth_status, connector_health = await _collect_channel_context(comp)
        report = comp["strategic_reasoner"].analyze_mission(
            mission=mission,
            signals=signals,
            clusters=clusters,
            scorecard=scorecard,
            auth_status=auth_status,
            connector_health=connector_health,
            market_brief=brief,
            qualification=await _qualification_for(comp, mission, signals),
        )
        comp["quality_evaluator"].apply_qualification(scorecard, report.qualification)
    
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
        analysis_contract=analysis_contract,
        scorecard_override=scorecard,
        market_brief_override=brief,
    )

    # Securely save HTML report artifact to disk
    reports_dir = _get_secure_reports_dir()
    report_filename = f"mission_{mission.shortcode.lower()}.html"

    report_path = reports_dir / report_filename
    report_path.write_text(html_content, encoding="utf-8")
    abs_path = str(report_path.resolve())

    if analysis_contract is not None:
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
                "analysis_status": analysis_contract["analysis_status"],
                "template_revision": "mission-report/evidence-grounded-v1",
                **(
                    {"gap_report": analysis_contract["gap_report"]}
                    if analysis_contract["analysis_status"] == "INSUFFICIENT_EVIDENCE"
                    else {
                        "evidence_frame": analysis_contract["evidence_frame"],
                        "claim_ledger": analysis_contract["claim_ledger"],
                        "contradictory_evidence": analysis_contract["contradictory_evidence"],
                        "retention_policy": analysis_contract["retention_policy"],
                        "redaction_policy": analysis_contract["redaction_policy"],
                        "platform_policy": analysis_contract["platform_policy"],
                        "reuse_limit": analysis_contract["reuse_limit"],
                    }
                ),
                "note": (
                    "The artifact renders only persisted current-frame claims, or the Gap "
                    "Report when the evidence contract withholds a verdict."
                ),
            },
            ensure_ascii=False,
            indent=2,
        )

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
                "question_relevance_score": scorecard.question_relevance_score,
                "qualification_counts": scorecard.qualification_counts,
                "strengths": scorecard.strengths_detected,
                "flaws": scorecard.flaws_detected,
            },
            **_surface_payload(report, mission),
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


async def handle_get_mission_evidence_qualification_batch(
    mission_id: str, cursor: Optional[str] = None, limit: int = DEFAULT_BATCH_LIMIT
) -> str:
    comp = get_components()
    result = await comp["get_evidence_qualification_batch_use_case"].execute(
        mission_id=mission_id, cursor=cursor, limit=limit
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_submit_mission_evidence_qualifications(
    mission_id: str, frame_fingerprint: str, assessments: List[Dict[str, Any]]
) -> str:
    comp = get_components()
    result = await comp["submit_evidence_qualifications_use_case"].execute(
        mission_id=mission_id, frame_fingerprint=frame_fingerprint, assessments=assessments
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_submit_mission_claims(
    mission_id: str,
    frame_digest: str,
    candidates: List[Dict[str, Any]],
    created_by: str,
) -> str:
    comp = get_components()
    result = await comp["submit_mission_claims_use_case"].execute(
        mission_id=mission_id,
        frame_digest=frame_digest,
        candidates=candidates,
        created_by=created_by,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


async def handle_get_mission_claims(
    mission_id: str, include_superseded: bool = False
) -> str:
    comp = get_components()
    result = await comp["get_mission_claims_use_case"].execute(
        mission_id=mission_id, include_superseded=include_superseded
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


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
async def create_attention_mission(
    workspace_id: str,
    title: str,
    requested_outcome: str,
    allowed_resources: list[str],
    authority_boundary: dict,
    output_type: str,
    stop_conditions: list[str],
    retention_policy: str,
    geo: str = "VN",
    timeframe: str = "7d",
    seed: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    platforms: Optional[list[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
    quota_budget: Optional[dict[str, int]] = None,
    analysis_policy: str = "evidence-gated-v1",
) -> str:
    return await handle_create_attention_mission(
        workspace_id=workspace_id,
        title=title,
        requested_outcome=requested_outcome,
        allowed_resources=allowed_resources,
        authority_boundary=authority_boundary,
        output_type=output_type,
        stop_conditions=stop_conditions,
        retention_policy=retention_policy,
        geo=geo,
        timeframe=timeframe,
        seed=seed,
        keywords=keywords,
        platforms=platforms,
        agent=agent,
        session_id=session_id,
        quota_budget=quota_budget,
        analysis_policy=analysis_policy,
    )


@mcp.tool(name="confirm_market_brief", description="Persist a requester-confirmed Market Brief and open the MARKET mission it authorizes. Run the adaptive Q&A in your own context, show the complete draft for editing, and call this only with the confirmed decision frame: core hypothesis, two alternatives, null, falsifiers, kill criteria, and revision rule. Drafts and abandoned Q&A are never sent or stored. Pass parent_attention_mission_id (and optionally parent_cluster_id) to record the Attention result the question came from, or previous_mission_id to revise a confirmed Brief -- a revision opens a new immutable revision and mission.")
async def confirm_market_brief(
    workspace_id: str,
    decision: str,
    target_user: str,
    problem: str,
    geo: str,
    timeframe: str,
    hypothesis: str,
    mission_manifest: dict,
    falsifiers: Optional[list[str]] = None,
    alternative_hypotheses: Optional[list[str]] = None,
    null_hypothesis: Optional[str] = None,
    kill_criteria: Optional[list[str]] = None,
    revision_rule: Optional[str] = None,
    confirmed_by: str = "",
    title: Optional[str] = None,
    keywords: Optional[list[str]] = None,
    parent_attention_mission_id: Optional[str] = None,
    parent_cluster_id: Optional[str] = None,
    previous_mission_id: Optional[str] = None,
    platforms: Optional[list[str]] = None,
    agent: str = "claude",
    session_id: Optional[str] = None,
) -> str:
    return await handle_confirm_market_brief(
        workspace_id=workspace_id,
        decision=decision,
        target_user=target_user,
        problem=problem,
        geo=geo,
        timeframe=timeframe,
        hypothesis=hypothesis,
        mission_manifest=mission_manifest,
        falsifiers=falsifiers,
        alternative_hypotheses=alternative_hypotheses,
        null_hypothesis=null_hypothesis,
        kill_criteria=kill_criteria,
        revision_rule=revision_rule,
        confirmed_by=confirmed_by,
        title=title,
        keywords=keywords,
        parent_attention_mission_id=parent_attention_mission_id,
        parent_cluster_id=parent_cluster_id,
        previous_mission_id=previous_mission_id,
        platforms=platforms,
        agent=agent,
        session_id=session_id,
    )


@mcp.tool(name="execute_mission_ingress", description="Trigger deep multi-platform data collection and clustering for a research mission (idempotent replace mode).")
async def execute_mission_ingress(mission_id: str) -> str:
    return await handle_execute_mission_ingress(mission_id)


@mcp.tool(name="release_mission_writer", description="Recover a mission whose run died while holding its single writer slot. Pass the mission and exactly the active_run_id that the CONFLICT result reported: the claim is released only when both match, a wrong run_id refuses and changes nothing, and there is no expiry and no force release -- a claim taken from a run that is still writing is the failure the slot exists to prevent. Use it only when that run is known to have died; otherwise wait for it to finish.")
async def release_mission_writer(mission_id: str, run_id: str) -> str:
    return await handle_release_mission_writer(mission_id, run_id)


@mcp.tool(name="get_mission_analysis", description="Retrieve full strategic analysis payload (Scorecard, 10 White Spaces, Insights, Action Plan, Top Signals) for in-chat Native Artifact rendering.")
async def get_mission_analysis(mission_id: str, limit: int = 25, platform: Optional[str] = None) -> str:
    return await handle_get_mission_analysis(mission_id=mission_id, limit=limit, platform=platform)


@mcp.tool(name="generate_mission_artifact", description="Export a standalone Infographic Canvas HTML report to local disk (reports/ folder). Use ONLY when the user explicitly requests an exported HTML file.")
async def generate_mission_artifact(mission_id: str) -> str:
    return await handle_generate_mission_artifact(mission_id)


@mcp.tool(name="get_mission_evidence_qualification_batch", description="Read a bounded batch (default 25, max 50) of a mission's current evidence that still needs a semantic judgment, with the immutable frame it is judged against: the confirmed Market Brief revision, or the Attention title and keywords. Judge each item in your own context and send the typed result to submit_mission_evidence_qualifications with the returned frame_fingerprint. READY means every observation carries an actual assessment (unassessed: 0). When recorded judgments leave the frame unassessed the answer is terminal with no evidence: QUALIFICATION_REQUIRED with reason_code UNASSESSED_EVIDENCE, or UNAVAILABLE with reason_code EVALUATOR_UNAVAILABLE (which takes priority over pending evidence); recorded judgments are final, so reassess under a new mission or Market Brief revision instead of reading again. NOT_APPLICABLE for a mission with no research surface.")
async def get_mission_evidence_qualification_batch(mission_id: str, cursor: Optional[str] = None, limit: int = DEFAULT_BATCH_LIMIT) -> str:
    return await handle_get_mission_evidence_qualification_batch(mission_id=mission_id, cursor=cursor, limit=limit)


@mcp.tool(
    name="submit_mission_evidence_qualifications",
    description=(
        "Record 1-50 typed evidence judgments for one mission, atomically. Each assessment names "
        "an observation_id; relation (QUALIFIED_SUPPORT, QUALIFIED_CONTRADICTION, CONTEXT_ONLY, "
        "EXCLUDED_IRRELEVANT, UNASSESSED); purpose (DEMAND, SUPPLY, VOC, CONTEXT); "
        "hypothesis_target; evidence_role (SUPPORT, CONTRADICTION, CONTEXT); confidence; "
        "reason_code (DIRECT_TO_FRAME, ADJACENT_ONLY, KEYWORD_ONLY, WRONG_AUDIENCE_OR_PROBLEM, "
        "FICTION_NEWS_OR_ENTERTAINMENT, INSUFFICIENT_CONTENT, EVALUATOR_UNAVAILABLE); judged_by; "
        "and optional model identifier. Support and contradiction use the same validation rules "
        "and require a named hypothesis target. A stale frame, foreign or duplicate observation, "
        "role mismatch, or invalid assessment refuses the whole batch; identical replay is "
        "idempotent and a changed judgment is refused. The response's qualification_status, "
        "qualification_reason_code, and next_step describe the state produced by this write. "
        "Never send a prompt, transcript, or credential."
    ),
)
async def submit_mission_evidence_qualifications(mission_id: str, frame_fingerprint: str, assessments: list[dict]) -> str:
    return await handle_submit_mission_evidence_qualifications(mission_id=mission_id, frame_fingerprint=frame_fingerprint, assessments=assessments)


@mcp.tool(name="submit_mission_claims", description="Submit 1-50 candidate Market claims against the exact current evidence-frame digest. Each candidate names its type, exact wording, inference method where required, confidence, limitations, change conditions, and observation or measured-absence bindings with SUPPORT, CONTRADICTION, or CONTEXT roles. A MEASUREMENT candidate also carries its metric_denominator and metric_timeframe; omission withholds it. Ignis deterministically checks required channels, complete qualification, hypothesis coverage, evidence bindings, demand and supply minimums, and frame currency before persisting PERMITTED or WITHHELD candidates. A stale input frame or invalid binding refuses the whole batch. A frame change detected after commit returns CONFLICT/STALE_FRAME with WITHHELD rendering and the actual recorded audit count; identical replay is idempotent. Outward projections redact personal data without rewriting canonical audit wording.")
async def submit_mission_claims(mission_id: str, frame_digest: str, candidates: list[dict], created_by: str) -> str:
    return await handle_submit_mission_claims(
        mission_id=mission_id,
        frame_digest=frame_digest,
        candidates=candidates,
        created_by=created_by,
    )


@mcp.tool(name="get_mission_claims", description="Read the current Market Claim Ledger and render permission for the mission's canonical evidence frame. By default stale claims are excluded; include_superseded=true returns the immutable audit history without making old claims renderable.")
async def get_mission_claims(mission_id: str, include_superseded: bool = False) -> str:
    return await handle_get_mission_claims(
        mission_id=mission_id, include_superseded=include_superseded
    )


@mcp.tool(name="list_research_missions", description="List recent bounded research missions in the configured database.")
async def list_research_missions(limit: int = 10) -> str:
    return await handle_list_research_missions(limit)


@mcp.tool(name="diagnose_system_health", description="Inspect system health, connector circuit breaker states, and automated remediation suggestions.")
async def diagnose_system_health() -> str:
    return await handle_diagnose_system_health()


@mcp.tool(name="get_system_logs", description="Query recent system audit logs and error traces from the database for debugging.")
async def get_system_logs(level: Optional[str] = "ERROR", component: Optional[str] = None, limit: int = 20) -> str:
    return await handle_get_system_logs(level=level, component=component, limit=limit)


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
        quota_status = None
        quota_reader = getattr(plugin, "quota_status", None)

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
            if callable(quota_reader):
                try:
                    candidate = await quota_reader()
                    if isinstance(candidate, dict):
                        quota_status = candidate
                except Exception as quota_error:
                    logger.warning(
                        "Could not read quota status for %s (%s).",
                        plugin.name,
                        type(quota_error).__name__,
                    )
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
                    **({"quota": quota_status} if quota_status is not None else {}),
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
                    **({"quota": quota_status} if quota_status is not None else {}),
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
                **({"quota": quota_status} if quota_status is not None else {}),
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
    """Mission-bound social research reference without an automatic verdict."""
    return SOP_FRAMEWORK_DOC


@mcp.resource("fn-ignis://methodology/opportunity-index")
def get_opportunity_index_methodology() -> str:
    """Historical score formula; Market use still requires a permitted current-frame claim."""
    return """
# Opportunity Index Methodology
Historical formula: Search Demand Score (0-100) minus Localized Content Supply Score (0-100).
Do not compute, display, or interpret this score for a Market decision unless the current
mission frame is sufficient and a persisted Claim Ledger record explicitly permits the
corresponding measurement. Missing channels and missing denominators are not zero.
"""


@mcp.prompt(name="market_research_pipeline")
def prompt_market_research_pipeline(topic: str = "AI Agent", geo: str = "VN") -> str:
    """Draft a bounded Market assignment without starting collection or promising a verdict."""
    return f"""
The requester is considering a Market question about '{topic}' in '{geo}'. First ask for the
decision, target user, timeframe, core hypothesis, two alternatives, null hypothesis,
falsifiers, kill criteria, revision rule, allowed sources, quota, and stop condition. Show a
bounded Brief for confirmation before creating a mission or collecting. After authorization,
qualify the current evidence frame, seek contradiction, and submit claim candidates. Render
only permitted claims; otherwise return the Gap Report. Export HTML only if requested.
"""


@mcp.prompt(name="voice_of_customer_audit")
def prompt_voice_of_customer_audit(keywords: str = "Chatbot AI") -> str:
    """Frame a bounded source-specific customer-voice probe."""
    return f"""
The requester wants customer-voice evidence about '{keywords}'. Confirm the source surface,
geography, time window, sampling cap, and stop condition. Use an authorized atomic comments
or pain-point tool, report provenance and unavailable states, and distinguish observations
from inference. Do not claim market prevalence or a strategic verdict from this probe alone.
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
    try:
        mcp.run()
    finally:
        _host_browser_search_service.close()


if __name__ == "__main__":
    main()
