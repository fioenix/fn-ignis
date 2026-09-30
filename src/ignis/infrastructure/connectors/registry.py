from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from itertools import zip_longest
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from ignis.application.ports.connector_port import IConnectorPlugin, SearchAttestation
from ignis.application.ports.language_detector_port import ILanguageDetector
from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    ConnectorQuotaExceededException,
)
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.self_content import SelfIdentity, partition_self_authored
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import (
    GeoCode,
    IngestRuntime,
    IngressScope,
    IngressTrigger,
    PlatformType,
    Timeframe,
)
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Circuit breaker protection: isolates failing plugins if consecutive errors exceed threshold."""
    def __init__(self, failure_threshold: int = 3, recovery_time_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED (normal), OPEN (tripped), HALF_OPEN (probing)
        self.last_failure_time: Optional[datetime] = None
        # Kept so an empty channel can be explained as a quota ceiling rather
        # than a generic outage in the Data Ingress audit.
        self.last_error_type: Optional[str] = None
        self.last_error_message: Optional[str] = None

    def record_success(self):
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_error_type = None
        self.last_error_message = None

    def record_failure(self, error: Optional[BaseException] = None):
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        if error is not None:
            self.last_error_type = type(error).__name__
            self.last_error_message = sanitize_pii_text(str(error))[:500]
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            logger.warning(f"Circuit Breaker TRIPPED to OPEN after {self.failure_count} consecutive failures.")

    def can_execute(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "OPEN":
            if self.last_failure_time:
                elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
                if elapsed >= self.recovery_time_seconds:
                    self.state = "HALF_OPEN"
                    return True
            return False
        return True


@dataclass(frozen=True)
class SurfaceProbeResult:
    """What one eligible connector surface did during one keyword search."""

    platform: str
    connector_surface: str
    status: ChannelHealthStatus
    signals_collected: int
    note: Optional[str] = None
    # The keywords the surface attested to having queried; a measured zero covers only these.
    queried_keywords: Tuple[str, ...] = ()
    # The window the platform attested to filtering by, or None when it applied none.
    queried_window: Optional[str] = None


@dataclass(frozen=True)
class SearchPassResult:
    """The signals of one keyword search, and the outcome of every surface it was sent to.

    Returned rather than stored on the registry, so two missions searching at once cannot read
    each other's outcomes.
    """

    signals: List[TrendSignal] = field(default_factory=list)
    outcomes: List[SurfaceProbeResult] = field(default_factory=list)


def _looks_rate_limited(text: str) -> bool:
    # One list of rate-limit hints, shared with the channel audit that explains empty surfaces.
    lowered = (text or "").lower()
    return any(hint in lowered for hint in StrategicMarketReasoner.RATE_LIMIT_HINTS)


def _failure_status(error: BaseException) -> ChannelHealthStatus:
    """A probe that raised measured nothing; say which kind of nothing."""
    if isinstance(error, ConnectorAuthenticationException):
        return ChannelHealthStatus.AUTH_REQUIRED
    if isinstance(error, ConnectorQuotaExceededException) or _looks_rate_limited(str(error)):
        return ChannelHealthStatus.RATE_LIMITED
    return ChannelHealthStatus.DEGRADED


class ConnectorPluginRegistry:
    """Manages connector plugin catalog and coordinates resilient multi-platform ingress with audit logging."""
    def __init__(self, repository: Optional[ITrendRepository] = None):
        # Keyed by plugin_id, not platform: a single platform can be served by
        # several plugins probing it differently (TikTok video grid vs Creative
        # Center). Keying by platform made the later registration silently
        # replace the earlier one.
        self._plugins: Dict[str, IConnectorPlugin] = {}
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._repository = repository
        self._self_identities: List[SelfIdentity] = []
        self._detector: Optional[ILanguageDetector] = None
        self.last_pass_report: Dict[str, Any] = {}

    def register_self_identities(self, identities: List[SelfIdentity]) -> None:
        """Bind the operator's own accounts so their content can be kept out of market passes."""
        self._self_identities = [i for i in identities if i.is_usable]

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    def register(self, plugin: IConnectorPlugin) -> None:
        plugin_id = plugin.plugin_id
        if plugin_id in self._plugins:
            logger.warning(
                f"Connector plugin id '{plugin_id}' is already registered by "
                f"[{self._plugins[plugin_id].name}]; replacing it with [{plugin.name}]. "
                "Override the `plugin_id` property if both plugins are meant to coexist."
            )
        self._plugins[plugin_id] = plugin
        self._breakers[plugin_id] = CircuitBreaker()
        logger.info(
            f"Registered Connector Plugin: [{plugin.name}] as '{plugin_id}' "
            f"for platform {plugin.platform.value}"
        )

    def get_plugin(self, platform: PlatformType) -> Optional[IConnectorPlugin]:
        """
        Return the first plugin registered for a platform.

        Kept for backward compatibility with existing call sites. Prefer
        `get_plugins()` when a platform may have several probes, or
        `get_plugin_by_id()` to address one exactly.
        """
        for plugin in self._plugins.values():
            if plugin.platform == platform:
                return plugin
        return None

    def get_plugin_by_id(self, plugin_id: str) -> Optional[IConnectorPlugin]:
        """Return exactly one plugin by its unique registry identifier."""
        return self._plugins.get(plugin_id)

    def get_plugins(self, platform: Optional[PlatformType] = None) -> List[IConnectorPlugin]:
        """Return every plugin registered for a platform, or all plugins when omitted."""
        if platform is None:
            return list(self._plugins.values())
        return [p for p in self._plugins.values() if p.platform == platform]

    def list_plugins(self) -> List[IConnectorPlugin]:
        return list(self._plugins.values())

    async def resolve_execution_requirements(
        self,
        *,
        target_platforms: List[PlatformType],
        allowed_surfaces: Tuple[str, ...],
        keywords: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Resolve policy requirements without opening a connector session or spending quota."""
        allowed = set(allowed_surfaces)
        selected = [
            plugin
            for plugin in self._plugins.values()
            if plugin.supports_search
            and plugin.platform in target_platforms
            and plugin.plugin_id in allowed
        ]
        selected_ids = {plugin.plugin_id for plugin in selected}
        unavailable = tuple(surface for surface in allowed_surfaces if surface not in selected_ids)
        authority: List[str] = []
        quota_costs: Dict[str, int] = {}
        for plugin in selected:
            runtime = await plugin.resolve_ingest_runtime()
            required = (
                "browser_session"
                if runtime is IngestRuntime.BROWSER
                else plugin.http_authority
            )
            if required not in authority:
                authority.append(required)
            if plugin.requires_paid_quota and "paid_quota" not in authority:
                authority.append("paid_quota")
            if plugin.platform is PlatformType.YOUTUBE:
                quota_costs["youtube_search_calls"] = max(1, len(keywords or []))
        return {
            "resources": tuple(plugin.plugin_id for plugin in selected),
            "authority": tuple(authority),
            "quota_costs": quota_costs,
            "unavailable_resources": unavailable,
        }

    def get_health_status(self) -> Dict[str, dict]:
        """Report health and circuit breaker state independently for every registered plugin."""
        status = {}
        for plugin_id, plugin in self._plugins.items():
            breaker = self._breakers[plugin_id]
            status[plugin_id] = {
                "plugin_id": plugin_id,
                "platform": plugin.platform.value,
                "name": plugin.name,
                "supports_search": plugin.supports_search,
                "circuit_state": breaker.state,
                "consecutive_failures": breaker.failure_count,
                "last_failure": breaker.last_failure_time.isoformat() if breaker.last_failure_time else None,
                "last_error_type": breaker.last_error_type,
                "last_error": breaker.last_error_message,
            }
        return status

    async def fetch_from_all(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
        seed_keywords: Optional[List[str]] = None,
        max_probe_keywords: Optional[int] = None,
        trigger: IngressTrigger = IngressTrigger.SCHEDULED,
    ) -> List[TrendSignal]:
        """Run one ingress pass across every healthy connector, in two stages.

        Stage 1 pulls the feeds that discover topics: what a region is searching for, which
        hashtags are climbing. Stage 2 takes those topics, adds `seed_keywords` from the market
        lexicon, and probes the remaining connectors by keyword. Staging them this way is what
        lets a cluster span several platforms: every connector in stage 2 is asked about a
        subject some other surface already showed interest in, instead of reporting its own
        national popularity chart. `max_probe_keywords` caps the fan-out, because a keyword probe
        costs far more API quota than an untargeted feed pull.

        `trigger` says who asked. A scheduled sweep is filtered down to the scripts the region
        uses, because it accumulates a corpus nobody reviews; an explicitly requested pass keeps
        whatever it found, the same way an agent's keyword probe does.

        `scope` decides which surfaces may be read. Under PUBLIC_MARKET a connector that declares
        an account-scoped feed is not asked for its feed at all; it joins stage 2 instead. Whatever
        the route, the pass ends by dropping content authored by the operator's own accounts, so a
        connector regressing to an account endpoint cannot quietly poison demand analysis.
        """
        seeds = [k.strip() for k in (seed_keywords or []) if k and k.strip()]
        discovery_plugins: List[IConnectorPlugin] = []
        probe_plugins: List[IConnectorPlugin] = []
        # Why each probe-routed plugin lost its untargeted pull, so a stage 2 that ends up with no
        # keywords can still report the accurate reason rather than a generic one.
        probe_is_account_only: Dict[str, bool] = {}
        account_scoped_skipped: List[str] = []
        no_probe_skipped: List[str] = []

        for plugin_id, plugin in self._plugins.items():
            breaker = self._breakers[plugin_id]
            if not breaker.can_execute():
                logger.warning(f"Skipping plugin [{plugin.name}] because Circuit Breaker is OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Skipping plugin {plugin.name} due to OPEN Circuit Breaker ({breaker.failure_count} consecutive errors).",
                        level="WARNING"
                    )
                continue

            feed_scope = getattr(plugin, "default_feed_scope", IngressScope.PUBLIC_MARKET)
            account_only_feed = feed_scope == IngressScope.OWN_PROFILE
            discovers_topics = getattr(plugin, "feed_yields_candidate_topics", True)

            # Two separate reasons to refuse an untargeted pull, both routed to the keyword probe:
            # the feed belongs to the operator's own account, or it is a popularity chart whose
            # contents have nothing to do with the topics this pass is about.
            if scope.includes_public and (account_only_feed or not discovers_topics):
                if plugin.supports_search:
                    probe_plugins.append(plugin)
                    probe_is_account_only[plugin.name] = account_only_feed
                    continue
                if account_only_feed:
                    account_scoped_skipped.append(plugin.name)
                    reason = (
                        f"{plugin.name} was skipped: its feed returns content owned by the "
                        f"authenticated account, which a {scope.value} pass must not ingest."
                    )
                    event = "ACCOUNT_SCOPED_FEED_SKIPPED"
                else:
                    no_probe_skipped.append(plugin.name)
                    reason = (
                        f"{plugin.name} was skipped: its untargeted feed is a popularity chart "
                        f"rather than a topic surface, and it has no keyword probe to use instead."
                    )
                    event = "UNTARGETED_FEED_SKIPPED"
                logger.info(reason)
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type=event,
                        message=reason,
                        level="INFO",
                        details={"platform": plugin.platform.value, "scope": scope.value},
                    )
                continue

            if account_only_feed and not scope.includes_public:
                # An own-profile pass wants exactly this feed.
                discovery_plugins.append(plugin)
                continue

            discovery_plugins.append(plugin)

        all_signals: List[TrendSignal] = []

        discovered = await asyncio.gather(
            *[
                self._safe_fetch(plugin, self._breakers[plugin.plugin_id], geo, timeframe, scope)
                for plugin in discovery_plugins
            ],
            return_exceptions=True,
        )
        stage_one = await self._collect_pass_results(discovery_plugins, discovered, "INGRESS")
        all_signals.extend(stage_one)

        if probe_plugins:
            keywords = self._build_probe_keywords(seeds, stage_one, max_probe_keywords)
            self._stamp_discovered_provenance(stage_one, keywords)
            if keywords:
                probed = await asyncio.gather(
                    *[
                        self._safe_search(
                            plugin,
                            self._breakers[plugin.plugin_id],
                            keywords,
                            geo,
                            timeframe,
                            trigger=trigger,
                        )
                        for plugin in probe_plugins
                    ],
                    return_exceptions=True,
                )
                all_signals.extend(await self._collect_pass_results(probe_plugins, probed, "INGRESS"))
            else:
                for plugin in probe_plugins:
                    if probe_is_account_only.get(plugin.name):
                        account_scoped_skipped.append(plugin.name)
                    else:
                        no_probe_skipped.append(plugin.name)
                logger.info(
                    "No topic keywords available for the keyword probes: neither the market "
                    "lexicon nor the discovery feeds produced one this pass."
                )

        all_signals, foreign = await self._apply_regional_script_guard(all_signals, geo, trigger)
        kept = await self._apply_scope_guard(all_signals, scope, account_scoped_skipped)
        self.last_pass_report["untargeted_feed_skipped"] = no_probe_skipped
        self.last_pass_report["foreign_script_filtered"] = foreign
        return kept

    @staticmethod
    def _stamp_discovered_provenance(
        discovered_signals: List[TrendSignal],
        keywords: List[str],
    ) -> None:
        """Record on a discovery signal the keyword it contributed, when that keyword was probed.

        Google Trends reports what a region is searching for, which is the demand half of the
        Opportunity Index, and its title *is* the keyword the other platforms were then asked
        about. Without this the demand signal and everything it retrieved cluster separately and
        the topic reads as single-platform. Signals whose keyword lost the budget cap are left
        alone: nothing corroborated them this pass.
        """
        probed = {kw.casefold() for kw in keywords}
        for signal in discovered_signals:
            title = " ".join((signal.raw_title or "").split())
            if title.casefold() in probed:
                signal.metadata = dict(signal.metadata or {})
                signal.metadata.setdefault("probe_keyword", title)

    @staticmethod
    def _build_probe_keywords(
        seeds: List[str],
        discovered_signals: List[TrendSignal],
        limit: Optional[int],
    ) -> List[str]:
        """Merge lexicon seeds with the topics stage 1 just found, capped by the quota budget.

        The two are interleaved rather than concatenated. Seeds are the domains the operator
        declared an interest in and discovered topics are what the region is asking about today;
        listing either one first lets it consume the whole budget and silently starve the other,
        which is what happened when ten lexicon seeds met a ten-keyword budget.
        """
        discovered: List[str] = []
        for signal in discovered_signals:
            term = (signal.raw_title or "").strip()
            if term and term not in discovered:
                discovered.append(term)

        keywords: List[str] = []
        for seed, topic in zip_longest(seeds, discovered):
            for term in (seed, topic):
                if term and term not in keywords:
                    keywords.append(term)

        if limit is not None and limit >= 0:
            return keywords[:limit]
        return keywords

    async def _collect_pass_results(
        self,
        plugins: List[IConnectorPlugin],
        results: List[Any],
        event_prefix: str,
    ) -> List[TrendSignal]:
        """Fold one gather's results into signals, isolating and logging each plugin's failure."""
        signals: List[TrendSignal] = []
        for plugin, result in zip(plugins, results):
            if isinstance(result, Exception):
                logger.error(f"Plugin [{plugin.name}] encountered exception during ingress: {result}")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type=f"{event_prefix}_FAILURE",
                        message=f"Error ingesting signals from {plugin.name}: {str(result)}",
                        level="ERROR",
                        details={"error": str(result), "platform": plugin.platform.value}
                    )
            elif isinstance(result, list):
                signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] collected {len(result)} signals.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type=f"{event_prefix}_SUCCESS",
                        message=f"Successfully collected {len(result)} signals from {plugin.name}.",
                        level="INFO",
                        details={"count": len(result), "platform": plugin.platform.value}
                    )
        return signals

    async def search_across_all(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        target_platforms: Optional[List[PlatformType]] = None,
        custom_timeframe: Optional[str] = None,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
        limit: int = 20,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
    ) -> List[TrendSignal]:
        """Probe every keyword-capable connector and return the signals only.

        The list-only contract ad-hoc callers rely on. A mission run needs the per-surface
        outcomes too and calls `search_with_outcomes`.
        """
        result = await self.search_with_outcomes(
            keywords=keywords,
            geo=geo,
            timeframe=timeframe,
            target_platforms=target_platforms,
            custom_timeframe=custom_timeframe,
            scope=scope,
            limit=limit,
            trigger=trigger,
        )
        return result.signals

    async def search_with_outcomes(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        target_platforms: Optional[List[PlatformType]] = None,
        target_surfaces: Optional[Tuple[str, ...]] = None,
        custom_timeframe: Optional[str] = None,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
        limit: int = 20,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
    ) -> SearchPassResult:
        """Probe every keyword-capable connector, reporting what each eligible surface did.

        A keyword search reads a public surface, but it can still surface the operator's own post
        when they happened to write about that keyword, so the same scope guard applies here.

        Every eligible surface -- one whose platform was asked for and which has a keyword probe
        -- gets exactly one outcome, including one skipped by an open circuit. An empty answer is
        EMPTY_NO_DATA only when the surface positively attests which queries it ran, through the
        `SearchAttestation` handed to it; the outcome then names exactly those keywords. A surface
        that attests nothing, says it cannot search without a session, or ran no query at all
        measured nothing, and is recorded as DEGRADED or AUTH_REQUIRED.
        """
        tasks = []
        enabled_plugins = []
        outcomes: Dict[str, SurfaceProbeResult] = {}
        blocked_reasons: Dict[str, Optional[str]] = {}
        attestations: Dict[str, Optional[SearchAttestation]] = {}

        for plugin_id, plugin in self._plugins.items():
            if target_platforms and plugin.platform not in target_platforms:
                continue
            if target_surfaces is not None and plugin_id not in target_surfaces:
                continue

            if not plugin.supports_search:
                # Falling back to fetch_signals here would inject platform-wide
                # signals unrelated to the requested keywords.
                logger.debug(f"Skipping search on [{plugin.name}]: no keyword search probe.")
                continue

            breaker = self._breakers[plugin_id]
            if not breaker.can_execute():
                logger.warning(f"Skipping plugin [{plugin.name}] because Circuit Breaker is OPEN.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="CIRCUIT_OPEN",
                        message=f"Skipping search on {plugin.name} due to OPEN Circuit Breaker.",
                        level="WARNING"
                    )
                outcomes[plugin_id] = SurfaceProbeResult(
                    platform=plugin.platform.value,
                    connector_surface=plugin_id,
                    status=(
                        ChannelHealthStatus.RATE_LIMITED
                        if _looks_rate_limited(
                            f"{breaker.last_error_type} {breaker.last_error_message}"
                        )
                        else ChannelHealthStatus.DEGRADED
                    ),
                    signals_collected=0,
                    note=f"Circuit Breaker is OPEN after {breaker.failure_count} consecutive failures.",
                )
                continue

            blocked_reasons[plugin_id] = await self._keyword_search_blocked_reason(plugin)
            attestations[plugin_id] = self._attestation_for(plugin)
            enabled_plugins.append(plugin)
            tasks.append(
                self._safe_search(
                    plugin, breaker, keywords, geo, timeframe, custom_timeframe, limit,
                    attestation=attestations[plugin_id],
                    trigger=trigger,
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_signals: List[TrendSignal] = []

        for plugin, result in zip(enabled_plugins, results):
            if isinstance(result, Exception):
                safe_error = sanitize_pii_text(str(result))
                outcomes[plugin.plugin_id] = SurfaceProbeResult(
                    platform=plugin.platform.value,
                    connector_surface=plugin.plugin_id,
                    status=_failure_status(result),
                    signals_collected=0,
                    note=safe_error[:200],
                )
                logger.error(
                    "Plugin [%s] encountered exception during search: %s",
                    plugin.name,
                    safe_error,
                )
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_FAILURE",
                        message=f"Error searching {plugin.name} with keywords {keywords}: {safe_error}",
                        level="ERROR",
                        details={"keywords": keywords, "error": safe_error}
                    )
            elif isinstance(result, list):
                outcomes[plugin.plugin_id] = self._search_outcome(
                    plugin, result, blocked_reasons.get(plugin.plugin_id),
                    attestations.get(plugin.plugin_id),
                )
                all_signals.extend(result)
                logger.info(f"Plugin [{plugin.name}] retrieved {len(result)} signals for keywords {keywords}.")
                if self._repository:
                    await self._repository.log_event(
                        component=plugin.name,
                        event_type="SEARCH_SUCCESS",
                        message=f"Successfully retrieved {len(result)} signals from {plugin.name}.",
                        level="INFO",
                        details={"keywords": keywords, "count": len(result)}
                    )

        kept = await self._apply_scope_guard(all_signals, scope, [])
        return SearchPassResult(signals=kept, outcomes=list(outcomes.values()))

    @staticmethod
    def _attestation_for(plugin: IConnectorPlugin) -> Optional[SearchAttestation]:
        """A fresh attestation for a plugin that can report what it ran, else None."""
        import inspect

        if "attestation" in inspect.signature(plugin.search_signals).parameters:
            return SearchAttestation()
        return None

    @staticmethod
    def _search_outcome(
        plugin: IConnectorPlugin,
        result: List[TrendSignal],
        blocked: Optional[str],
        attestation: Optional[SearchAttestation],
    ) -> SurfaceProbeResult:
        """Classify one surface's returned list without trusting an unattested silence."""
        queried = tuple(attestation.queried) if attestation else ()
        if result:
            status, note = ChannelHealthStatus.HEALTHY, None
        elif blocked or (attestation and attestation.blocked_reason):
            status, note = ChannelHealthStatus.AUTH_REQUIRED, blocked or attestation.blocked_reason
        elif attestation is None:
            status = ChannelHealthStatus.DEGRADED
            note = "Returned nothing without attesting that it ran the query; nothing was measured."
        elif not queried:
            status = ChannelHealthStatus.DEGRADED
            note = "; ".join(attestation.failures)[:200] or "No query was executed."
        else:
            status = ChannelHealthStatus.EMPTY_NO_DATA
            note = ("Partial: " + "; ".join(attestation.failures))[:200] if attestation.failures else None
        return SurfaceProbeResult(
            platform=plugin.platform.value,
            connector_surface=plugin.plugin_id,
            status=status,
            signals_collected=len(result),
            note=note,
            queried_keywords=queried,
            queried_window=attestation.window if attestation else None,
        )

    @staticmethod
    async def _keyword_search_blocked_reason(plugin: IConnectorPlugin) -> Optional[str]:
        """Why a surface's keyword search would come back empty, when it knows in advance.

        Optional on the plugin: only a surface that can return an empty answer without an error
        -- TikTok with no stored session -- declares it. A check that itself fails reports
        nothing, so the probe still runs and its own outcome is what gets recorded.
        """
        check = getattr(plugin, "keyword_search_blocked_reason", None)
        if check is None:
            return None
        try:
            return await check()
        except Exception as exc:
            logger.debug(f"Could not ask [{plugin.name}] whether keyword search is blocked: {exc}")
            return None

    async def _apply_regional_script_guard(
        self,
        signals: List[TrendSignal],
        geo: GeoCode,
        trigger: IngressTrigger = IngressTrigger.SCHEDULED,
    ) -> Tuple[List[TrendSignal], int]:
        """Drop signals written in a script the target region does not use.

        Applies to a scheduled sweep only. A keyword probe queries the whole platform -- `q=` is
        a search term, not a region filter -- so a Vietnam pass legitimately returns Korean,
        Cyrillic and Arabic titles, and the radar used to write them straight to the corpus it
        accumulates unattended. An explicitly requested pass keeps them: somebody is reading the
        answer and may well want it. Latin script always passes either way, so the English that
        runs through Vietnamese social content is never in question here.

        It deliberately does not judge relevance. An earlier version asked `is_localized` with
        the persisted vocabulary, which weighs language, domain terms and the noise blacklist
        together; on the live corpus that rejected 67.8% of rows, including "Khoa hoc AI cho
        nguoi moi bat dau". Worse, judging relevance against `market_lexicons` meant the radar
        could only store topics somebody had already seeded, which is the opposite of its job.
        Relevance is decided downstream by `QualityEvaluator`, which already holds that
        vocabulary and runs on the analysis path.
        """
        if not signals:
            return signals, 0
        if trigger != IngressTrigger.SCHEDULED:
            # Somebody asked for this pass, so they get what it found, in whatever language.
            # See IngressTrigger: the distinction is the requester, not the code path.
            return signals, 0
        if self._detector is None:
            from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector

            self._detector = HeuristicLanguageDetector()

        kept: List[TrendSignal] = []
        dropped: List[TrendSignal] = []
        for signal in signals:
            if self._detector.uses_regional_script(signal.raw_title or "", geo=geo):
                kept.append(signal)
            else:
                dropped.append(signal)

        if dropped:
            platforms = sorted({
                (s.platform.value if hasattr(s.platform, "value") else str(s.platform))
                for s in dropped
            })
            logger.info(
                f"Filtered {len(dropped)} signals written in a script {geo.value} does not use "
                f"({', '.join(platforms)})."
            )
            if self._repository:
                await self._repository.log_event(
                    component="ingress",
                    event_type="FOREIGN_SCRIPT_FILTERED",
                    message=(
                        f"Dropped {len(dropped)} signals written in a script {geo.value} does "
                        f"not use; a keyword probe reaches the whole platform, not one region."
                    ),
                    level="INFO",
                    details={"count": len(dropped), "platforms": platforms, "geo": geo.value},
                )
        return kept, len(dropped)

    async def _apply_scope_guard(
        self,
        signals: List[TrendSignal],
        scope: IngressScope,
        account_scoped_skipped: List[str],
    ) -> List[TrendSignal]:
        """Keep only the signals the requested scope allows, and record what was dropped."""
        collected = len(signals)
        kept: List[TrendSignal] = signals
        dropped: List[TrendSignal] = []

        if self._self_identities and scope != IngressScope.BOTH:
            public, own = partition_self_authored(signals, self._self_identities)
            if scope == IngressScope.PUBLIC_MARKET:
                kept, dropped = public, own
            else:
                kept, dropped = own, public

        platforms = sorted({
            (s.platform.value if hasattr(s.platform, "value") else str(s.platform))
            for s in dropped
        })
        self.last_pass_report = {
            "scope": scope.value,
            "collected": collected,
            "kept": len(kept),
            "filtered_out": len(dropped),
            "filtered_platforms": platforms,
            "account_scoped_skipped": account_scoped_skipped,
            "self_identities_known": len(self._self_identities),
        }

        if dropped and scope == IngressScope.PUBLIC_MARKET:
            logger.info(
                f"Filtered {len(dropped)} self-authored signals out of a {scope.value} pass "
                f"({', '.join(platforms) or 'unknown platform'})."
            )
            if self._repository:
                await self._repository.log_event(
                    component="ingress",
                    event_type="SELF_CONTENT_FILTERED",
                    message=(
                        f"Dropped {len(dropped)} signals authored by the operator's own accounts "
                        f"from a {scope.value} pass, so they cannot distort demand analysis."
                    ),
                    level="INFO",
                    details={"count": len(dropped), "platforms": platforms, "scope": scope.value},
                )
        return kept

    @staticmethod
    def _stamp_connector_surface(plugin: IConnectorPlugin, signals: List[TrendSignal]) -> List[TrendSignal]:
        """Record which connector surface returned each signal.

        A platform can be served by several probes -- the TikTok video grid and the Creative
        Center are two, and a token-less Threads browser session is a third surface on one
        platform. Health reported per platform lets a healthy grid hide a failed comment probe,
        so the surface has to travel with the signal and survive being read back out of an
        observation. `setdefault`, because a connector that knows its own sub-surface better
        than the registry does keeps what it set.
        """
        for signal in signals or []:
            if signal.metadata is None:
                signal.metadata = {}
            signal.metadata.setdefault("connector_surface", plugin.plugin_id)
        return signals or []

    async def _safe_fetch(
        self,
        plugin: IConnectorPlugin,
        breaker: CircuitBreaker,
        geo: GeoCode,
        timeframe: Timeframe,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> List[TrendSignal]:
        try:
            # `scope` is only forwarded to plugins that declare it, the same way custom_timeframe
            # is handled below: a third-party connector written against the older signature keeps
            # working, and the scope guard still covers whatever it returns.
            import inspect
            if "scope" in inspect.signature(plugin.fetch_signals).parameters:
                signals = await plugin.fetch_signals(geo=geo, timeframe=timeframe, scope=scope)
            else:
                signals = await plugin.fetch_signals(geo=geo, timeframe=timeframe)
            breaker.record_success()
            return self._stamp_connector_surface(plugin, signals)
        except Exception as e:
            breaker.record_failure(e)
            raise e

    async def _safe_search(
        self, 
        plugin: IConnectorPlugin, 
        breaker: CircuitBreaker, 
        keywords: List[str], 
        geo: GeoCode, 
        timeframe: Timeframe,
        custom_timeframe: Optional[str] = None,
        limit: Optional[int] = None,
        attestation: Optional[SearchAttestation] = None,
        trigger: IngressTrigger = IngressTrigger.REQUESTED,
    ) -> List[TrendSignal]:
        try:
            import inspect
            sig = inspect.signature(plugin.search_signals)
            kwargs = {"keywords": keywords, "geo": geo, "timeframe": timeframe}
            if "custom_timeframe" in sig.parameters:
                kwargs["custom_timeframe"] = custom_timeframe
            if limit is not None and "limit" in sig.parameters:
                kwargs["limit"] = limit
            if attestation is not None:
                kwargs["attestation"] = attestation
            if "trigger" in sig.parameters:
                kwargs["trigger"] = trigger
            signals = await plugin.search_signals(**kwargs)
            breaker.record_success()
            return self._stamp_connector_surface(plugin, signals)
        except Exception as e:
            breaker.record_failure(e)
            raise e

    async def fetch_suggestions_across_all(
        self,
        keywords: List[str],
        geo: GeoCode = GeoCode.VN,
        target_platforms: Optional[List[PlatformType]] = None,
    ) -> List[Dict[str, Any]]:
        """Collect search suggestions across all capable plugins."""
        all_suggestions: List[Dict[str, Any]] = []
        for plugin in self._plugins.values():
            if target_platforms and plugin.platform not in target_platforms:
                continue
            try:
                sugs = await plugin.fetch_suggestions(keywords=keywords, geo=geo)
                if sugs:
                    all_suggestions.extend(sugs)
            except Exception as e:
                logger.warning(
                    "Error fetching suggestions from %s: %s",
                    plugin.name,
                    sanitize_pii_text(str(e)),
                )
        return all_suggestions
