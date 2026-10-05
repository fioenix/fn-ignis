import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, cast
from uuid import UUID

from ignis.application.cancellation import await_settled
from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.mission_relay_port import ICollectionRelayWriter
from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.value_objects import resolve_platform, resolve_timeframe
from ignis.domain.exceptions import VocabularySynchronizationError
from ignis.domain.research_workspace import (
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    InvalidMissionAuthorizationError,
    InvalidMissionManifestError,
    MissionTerminalStateError,
    MissionProbeOutcome,
    ResearchSurface,
    WorkspaceScopeMismatchError,
    compute_query_fingerprint,
    derive_collection_plan,
    resolve_surface,
)
from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
from ignis.infrastructure.connectors.registry import (
    ConnectorPluginRegistry,
    SurfaceProbeResult,
)
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text

logger = logging.getLogger(__name__)

TERMINAL_MISSION_STATES = frozenset(
    {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT_EVIDENCE"}
)


class ExecuteMissionUseCase:
    """
    Use Case for executing deep data ingress for a specific Research Mission,
    passing exact timeframe filters, tagging mission_id, clustering signals, and updating state.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        registry: ConnectorPluginRegistry,
        clusterer: IClusteringEngine,
        workspace_store: Optional[IResearchWorkspaceStore] = None,
        vocabulary_sync: Optional[VocabularySynchronizer] = None,
    ):
        self._repo = repository
        self._registry = registry
        self._clusterer = clusterer
        self._workspace_store = workspace_store
        self._vocabulary_sync = vocabulary_sync

    async def _require_confirmed_brief(self, mission) -> None:
        """A Market mission does not probe until the requester has confirmed its Brief.

        The gate is fail-closed: a MARKET mission whose Brief cannot be read is blocked rather
        than run, because the alternative is collecting evidence against a hypothesis nobody
        agreed to and then presenting it as an answer to a decision.

        Missions on no surface -- everything created outside a research workspace -- are not
        gated. They were never framed as hypothesis-driven investigations, so demanding a Brief
        from them would be a rule applied backwards.
        """
        if resolve_surface(mission.surface) is not ResearchSurface.MARKET:
            return

        revision = None
        if self._workspace_store is not None:
            revision = await self._workspace_store.get_brief_revision_for_mission(mission.id)

        if revision is not None:
            return

        mission.status = "BLOCKED"
        mission.summary = (
            "Blocked: Market probes are not authorized until the requester confirms a complete "
            "Market Brief."
        )
        await self._repo.update_mission(mission)
        raise IncompleteMarketBriefError(REQUIRED_BRIEF_FIELDS)

    async def _require_manifest_authority(self, mission):
        """Resolve the connector plan and refuse before a session, writer, or journal opens."""
        if resolve_surface(mission.surface) is None:
            # Legacy surface-null missions remain readable until the breaking public cutover.
            return None, {}
        if self._workspace_store is None:
            raise InvalidMissionManifestError(
                f"Mission {mission.id} is surfaced but no workspace store can read its manifest."
            )
        manifest = await self._workspace_store.get_mission_manifest(mission.id)
        if manifest is None:
            mission.status = "BLOCKED"
            mission.summary = "Blocked: surfaced missions require a confirmed Mission Manifest."
            await self._repo.update_mission(mission)
            raise InvalidMissionManifestError(mission.summary)

        resolver = getattr(self._registry, "resolve_execution_requirements", None)
        if resolver is None:
            raise InvalidMissionAuthorizationError(
                "AUTHORITY_PREFLIGHT_UNAVAILABLE",
                "The connector registry cannot prove its authority requirements, so no connector "
                "session was opened.",
            )
        # Cost the same query union the connector will execute, including counterevidence.
        # The manifest and per-mission Brief are immutable; connector metadata changes neither.
        planned_queries = self._collection_queries(
            await self._build_collection_plan(mission, manifest, {})
        )
        requirements = await resolver(
            target_platforms=mission.platforms,
            allowed_surfaces=manifest.allowed_resources,
            required_surfaces=manifest.required_channels,
            optional_surfaces=manifest.optional_channels,
            keywords=planned_queries,
        )
        requirements = self._scope_optional_execution(manifest, requirements)
        if "queries" in manifest.quota_budget:
            # A declared query budget bounds the plan, including counterevidence, not only
            # connector-specific paid/API costs. Do not silently truncate an approved plan.
            requirements["quota_costs"] = {
                **requirements.get("quota_costs", {}), "queries": len(planned_queries),
            }
        unavailable = tuple(requirements.get("unavailable_resources", ()))
        if unavailable:
            mission.status = "BLOCKED"
            mission.summary = (
                "Blocked: manifest-declared connector surfaces are unavailable: "
                + ", ".join(unavailable)
            )
            await self._repo.update_mission(mission)
            raise InvalidMissionAuthorizationError(
                "RESOURCE_UNAVAILABLE",
                mission.summary,
                missing_authority=unavailable,
            )
        try:
            manifest.require_execution_authority(
                resources=requirements.get("resources", ()),
                authority=requirements.get("authority", ()),
                quota_costs=requirements.get("quota_costs", {}),
                material_scope_change=bool(requirements.get("material_scope_change", False)),
            )
        except InvalidMissionAuthorizationError as exc:
            mission.status = "BLOCKED"
            mission.summary = f"Blocked: {exc}"
            await self._repo.update_mission(mission)
            raise
        return manifest, requirements

    @staticmethod
    def _scope_optional_execution(manifest, requirements):
        """Keep unauthorized optional probes out of the run without weakening required gates."""
        scoped = dict(requirements or {})
        selected = tuple(scoped.get("resources", ()))
        per_surface = dict(scoped.get("surface_requirements", {}))
        optional = set(manifest.optional_channels)
        authority_boundary = manifest.authority_boundary.to_payload()
        approved_resources = []
        approved_authority = []
        approved_quota: Dict[str, int] = {}
        not_requested = list(scoped.get("not_requested_resources", ()))

        # Required surfaces consume their declared authority and quota first. An overrun remains
        # a hard refusal. Optional surfaces are then admitted only while they still fit the same
        # confirmed boundary; otherwise they become explicit NOT_REQUESTED outcomes.
        ordered = tuple(surface for surface in selected if surface not in optional) + tuple(
            surface for surface in selected if surface in optional
        )
        fallback_authority = tuple(scoped.get("authority", ()))
        fallback_quota = dict(scoped.get("quota_costs", {}))
        for surface in ordered:
            surface_requirement = dict(per_surface.get(surface, {}))
            authority = surface_requirement.get("authority_tier")
            authorities = [authority] if authority else list(fallback_authority)
            if surface_requirement.get("requires_paid_quota"):
                authorities.append("paid_quota")
            surface_quota = dict(surface_requirement.get("quota_costs", {}))
            if "quota_costs" not in surface_requirement and surface not in optional:
                surface_quota = fallback_quota

            proposed_quota = dict(approved_quota)
            for name, cost in surface_quota.items():
                proposed_quota[name] = proposed_quota.get(name, 0) + int(cost)
            fits_authority = all(authority_boundary.get(name, False) for name in authorities)
            fits_quota = all(
                proposed_quota.get(name, 0) <= int(manifest.quota_budget.get(name, 0))
                for name in surface_quota
            )
            if surface in optional and (not fits_authority or not fits_quota):
                if surface not in not_requested:
                    not_requested.append(surface)
                continue

            approved_resources.append(surface)
            approved_quota = proposed_quota
            for name in authorities:
                if name not in approved_authority:
                    approved_authority.append(name)

        scoped["resources"] = tuple(approved_resources)
        scoped["authority"] = tuple(approved_authority)
        scoped["quota_costs"] = approved_quota
        scoped["not_requested_resources"] = tuple(not_requested)
        return scoped

    async def _run_workspace(self, mission):
        """The research this run writes into, or None when the mission belongs to none.

        Every mission created before the workspace feature is in that second state, so a run
        path that required a workspace would stop all of them. Those runs take no writer claim
        and write no journal, exactly as they did before.
        """
        if self._workspace_store is None or mission.workspace_id is None:
            return None
        workspace = await self._workspace_store.get_research_workspace(mission.workspace_id)
        if workspace is None:
            # The mission names a research the configured database does not hold. Running it
            # anyway would write evidence into a scope nothing can address afterwards.
            raise WorkspaceScopeMismatchError(
                f"Mission {mission.id} belongs to research workspace {mission.workspace_id}, "
                "which does not exist in the configured Ignis database."
            )
        return workspace

    async def _update_collection_state(self, mission, journal=None) -> None:
        """Run receipts use the canonical transaction; unscoped legacy writes stay unchanged."""
        if journal is None:
            await self._repo.update_mission(mission)
        else:
            await cast(ICollectionRelayWriter, self._workspace_store).commit_collection_state(
                mission, journal.run_id
            )

    async def _synchronize_vocabulary(self, mission, journal=None) -> None:
        """Load the persisted vocabulary before the mission can reach a connector.

        The first mission after a process starts used to run with none of it: only an analysis
        call had ever registered the TikTok UI noise and the probe templates, so the grid
        rejected every card and demand was measured from the bare keyword. A failure here stops
        the mission before it is marked RUNNING and before any connector is called; for a
        workspace mission it runs inside the writer claim, so only the claim holder records it.
        """
        if self._vocabulary_sync is None:
            return
        try:
            await self._vocabulary_sync.synchronize()
        except VocabularySynchronizationError as exc:
            mission.status = "FAILED"
            mission.summary = (
                "Failed before ingress: the persisted vocabulary could not be synchronized, so "
                f"no connector was called. {exc}"
            )
            await self._update_collection_state(mission, journal)
            raise

    async def _settle_collection_failure(self, mission, journal, safe_error: str) -> None:
        """Keep the complete read/write cleanup under settlement, even on repeated cancel."""
        # A terminal transaction may already have committed when cancellation is delivered.
        current = await self._repo.get_mission(mission.id) if journal is not None else None
        if current is not None and str(current.status).upper() in TERMINAL_MISSION_STATES:
            mission.status, mission.summary = current.status, current.summary
        else:
            mission.status = "FAILED"
            mission.summary = f"Execution error: {safe_error}"
            await self._update_collection_state(mission, journal)

    async def execute(self, mission_id: UUID) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

        if str(mission.status).upper() in TERMINAL_MISSION_STATES:
            raise MissionTerminalStateError(mission.id, str(mission.status).upper())

        manifest, execution_requirements = await self._require_manifest_authority(mission)
        await self._require_confirmed_brief(mission)

        return await self._execute_authorized(mission, manifest, execution_requirements)

    async def _execute_authorized(
        self, mission, manifest, execution_requirements, *, scope_guard=None, search_provider=None, expiry_guard=None
    ) -> Dict[str, Any]:
        """Reuse the canonical writer; validate a staged host scope before any ingress write."""

        workspace = await self._run_workspace(mission)
        if workspace is None:
            if scope_guard is not None:
                raise ValueError("Host mission ingestion requires a workspace writer")
            await self._synchronize_vocabulary(mission)
            result = await self._execute_pass(
                mission,
                manifest=manifest,
                execution_requirements=execution_requirements,
                search_provider=search_provider,
                expiry_guard=expiry_guard,
            )
            return result

        # The claim is taken before anything else writes, so a refused second run never touches
        # the state of the run that holds the mission -- not even to record that its own
        # vocabulary read failed. Synchronization follows the claim and still precedes RUNNING
        # and every connector call. The claim and the journal are given back by the context
        # manager, including when synchronization or the pass raises.
        async with self._workspace_store.mission_run(workspace, mission.id) as journal:
            if scope_guard is not None:
                await scope_guard(journal)
            await self._synchronize_vocabulary(mission, journal)
            result = await self._execute_pass(
                mission,
                journal=journal,
                manifest=manifest,
                execution_requirements=execution_requirements,
                search_provider=search_provider,
                expiry_guard=expiry_guard,
            )
            result["run"] = {
                "run_id": str(journal.run_id),
                "workspace_id": str(journal.workspace_id),
                "journal_path": str(journal.journal_path),
                "journal_status": "COMPLETED",
            }
            if manifest is not None:
                result["manifest_digest"] = manifest.manifest_digest
            result["terminal_state"] = mission.status
        if manifest is not None:
            outcomes = await self._workspace_store.get_latest_completed_probe_outcomes(mission.id)
            outcomes_by_surface = {item.connector_surface: item for item in outcomes}
            result["channel_outcomes"] = [
                self._probe_outcome_payload(outcomes_by_surface[surface])
                for surface in manifest.allowed_resources
            ]
            frame = await self._build_current_evidence_frame(
                mission, manifest, result["collection_plan_digest"]
            )
            result["evidence_frame"] = frame.to_payload()
            result["retention_policy"] = manifest.retention_policy
            result["redaction_policy"] = "credentials-and-personal-data-redacted"
            result["platform_policy"] = "authorized-surface-terms-apply"
            result["reuse_limit"] = (
                "Evidence is scoped to this mission. Another mission must explicitly associate "
                "and qualify it before use."
            )
        return result

    async def _build_collection_plan(self, mission, manifest, execution_requirements):
        brief = None
        if resolve_surface(mission.surface) is ResearchSurface.MARKET:
            brief = await self._workspace_store.get_brief_revision_for_mission(mission.id)
        requirements = dict((execution_requirements or {}).get("surface_requirements", {}))
        authority = tuple((execution_requirements or {}).get("authority", ()))
        default_authority = next(
            (value for value in authority if value != "paid_quota"), "public_http"
        )
        not_requested = set(
            (execution_requirements or {}).get("not_requested_resources", ())
        )
        for surface in manifest.allowed_resources:
            if surface in not_requested:
                requirements[surface] = {
                    "authority_tier": "not-requested",
                    "connector_path": "unavailable",
                    "connector_revision": "unavailable",
                    "sampling": {"limit": 0, "ordering": "not_requested"},
                }
                continue
            requirements.setdefault(
                surface,
                {
                    "authority_tier": default_authority,
                    "connector_path": f"registry.{surface}.search_signals",
                    "connector_revision": "unversioned",
                    "sampling": {"limit": 20, "ordering": "platform_default"},
                },
            )
        if brief is None:
            targets = ("attention_question",)
            expected_role = "CONTEXT"
            audience = None
            falsifiers = ()
            probe_intents = ()
        else:
            targets = ("core",)
            expected_role = "SUPPORT"
            audience = brief.target_user
            falsifiers = brief.falsifiers
            empty_families = {"root": (), "expanded": (), "exclusions": ()}
            probe_intents = (
                {
                    "evidence_targets": ("core",),
                    "expected_role": "SUPPORT",
                    "query_families": {**empty_families, "root": mission.keywords},
                },
                {
                    "evidence_targets": ("core",),
                    "expected_role": "CONTRADICTION",
                    "query_families": {**empty_families, "falsification": falsifiers},
                },
                {
                    "evidence_targets": ("neutral",),
                    "expected_role": "CONTEXT",
                    "query_families": {**empty_families, "root": mission.keywords},
                },
            )
        return derive_collection_plan(
            mission_id=mission.id,
            manifest=manifest,
            keywords=mission.keywords,
            geo=mission.geo_code,
            timeframe=mission.timeframe,
            surface_requirements=requirements,
            evidence_targets=targets,
            expected_role=expected_role,
            audience=audience,
            language=None,
            falsification_queries=falsifiers,
            probe_intents=probe_intents,
        )

    @staticmethod
    def _collection_queries(collection_plan) -> List[str]:
        queries = []
        for probe in collection_plan.get("probes", ()):
            families = probe.get("query_families", {})
            for family in ("root", "expanded", "falsification"):
                for query in families.get(family, ()):
                    if query not in queries:
                        queries.append(query)
        return queries

    @staticmethod
    def _surface_platform(surface: str) -> str:
        platform_name = "tiktok" if surface.startswith("tiktok_") else surface
        try:
            return resolve_platform(platform_name).value
        except ValueError:
            return platform_name

    def _complete_surface_outcomes(self, manifest, outcomes, execution_requirements):
        by_surface = {}
        for outcome in outcomes:
            if outcome.connector_surface in by_surface:
                raise InvalidMissionManifestError(
                    f"Connector surface '{outcome.connector_surface}' returned more than one outcome."
                )
            if outcome.connector_surface not in manifest.allowed_resources:
                raise InvalidMissionManifestError(
                    f"Connector surface '{outcome.connector_surface}' is outside the manifest."
                )
            by_surface[outcome.connector_surface] = outcome

        not_requested = set((execution_requirements or {}).get("not_requested_resources", ()))
        complete = []
        for surface in manifest.allowed_resources:
            outcome = by_surface.get(surface)
            if outcome is None:
                status = (
                    ChannelHealthStatus.NOT_REQUESTED
                    if surface in not_requested
                    else ChannelHealthStatus.FAILED
                )
                note = (
                    "The optional surface was declared but unavailable in the configured registry, "
                    "so it was not requested in this run."
                    if status is ChannelHealthStatus.NOT_REQUESTED
                    else "The declared connector surface returned no outcome for this run."
                )
                outcome = SurfaceProbeResult(
                    platform=self._surface_platform(surface),
                    connector_surface=surface,
                    status=status,
                    signals_collected=0,
                    note=note,
                )
            complete.append(outcome)
        return complete

    async def _build_current_evidence_frame(self, mission, manifest, collection_plan_digest):
        frame = await load_current_evidence_frame(
            self._repo, self._workspace_store, mission, manifest
        )
        if frame.collection_plan_digest != collection_plan_digest:
            raise InvalidMissionManifestError(
                "The completed run's persisted collection plan differs from the executed plan."
            )
        return frame

    @staticmethod
    def _probe_outcome_payload(outcome: MissionProbeOutcome) -> Dict[str, Any]:
        """Return the same complete outcome contract that was accepted by persistence."""
        return {
            "outcome_id": str(outcome.outcome_id),
            "run_id": str(outcome.run_id),
            "connector_surface": outcome.connector_surface,
            "platform": outcome.platform,
            "status": outcome.status.value,
            "signals_collected": outcome.signals_collected,
            "queried_keywords": list(outcome.queried_keywords),
            "queried_window": outcome.queried_window,
            "query_fingerprint": outcome.query_fingerprint,
            "scope_attestation": outcome.scope_attestation,
            "note": outcome.note,
            "collection_plan_digest": outcome.collection_plan_digest,
            "completed_at": outcome.completed_at.isoformat(),
        }

    async def _record_probe_outcomes(
        self, mission, journal, outcomes, *, collection_plan_digest=None
    ) -> None:
        """Write what every surface did during this run, before the mission can complete.

        A failure here propagates: a run whose outcomes are not on record would later be read as
        having measured nothing in particular, and a measured zero is only honest when the run
        that measured it is known.
        """
        completed_at = datetime.now(timezone.utc)
        await self._workspace_store.record_probe_outcomes(
            journal.run_id,
            [
                MissionProbeOutcome(
                    run_id=journal.run_id,
                    platform=outcome.platform,
                    connector_surface=outcome.connector_surface,
                    status=outcome.status,
                    signals_collected=outcome.signals_collected,
                    # Each surface's own query: the keywords it attested to running, not the
                    # mission's full list, which a connector capped at ten never saw in full.
                    queried_keywords=outcome.queried_keywords,
                    queried_window=outcome.queried_window,
                    # The window the surface attested to filtering by, not the one the mission
                    # asked for: a connector handed another window measured that one instead.
                    query_fingerprint=compute_query_fingerprint(
                        outcome.queried_keywords, mission.geo_code, outcome.queried_window
                    ),
                    completed_at=completed_at,
                    scope_attestation=(
                        outcome.scope_attestation
                        if outcome.scope_attestation is not None
                        else ({
                            "geo": mission.geo_code.value,
                            "timeframe": outcome.queried_window or mission.timeframe,
                            "keywords": list(outcome.queried_keywords),
                        }
                        if collection_plan_digest is not None
                        and outcome.status.value in ("HEALTHY", "EMPTY_NO_DATA")
                        else None)
                    ),
                    note=(
                        outcome.note
                        or (
                            "The attested scope returned no qualifying observations."
                            if outcome.status.value == "EMPTY_NO_DATA"
                            else "The connector did not produce a measurement for this declared surface."
                            if collection_plan_digest is not None
                            and outcome.status.value not in ("HEALTHY", "EMPTY_NO_DATA")
                            else None
                        )
                    ),
                    collection_plan_digest=collection_plan_digest,
                )
                for outcome in outcomes
            ],
        )

    async def _execute_pass(
        self, mission, journal=None, manifest=None, execution_requirements=None, search_provider=None, expiry_guard=None
    ) -> Dict[str, Any]:
        mission_id = mission.id
        if expiry_guard is not None:
            expiry_guard()
        logger.info(f"Executing Research Mission '{mission.title}' [ID: {mission_id}] with keywords: {mission.keywords} (Timeframe: {mission.timeframe})...")
        mission.status = "RUNNING"

        try:
            await self._update_collection_state(mission, journal)
            collection_plan_digest = None
            collection_plan = None
            if manifest is not None:
                collection_plan = await self._build_collection_plan(
                    mission, manifest, execution_requirements
                )
                collection_plan_digest = collection_plan["plan_digest"]
                if journal is not None:
                    await self._workspace_store.record_collection_plan(journal, collection_plan)
            # 1. Targeted ingress across active connector plugins, with the outcome of every
            # surface it reached: a workspace run records them, so a reopened report can tell a
            # measured zero from a probe that never measured.
            search = await (search_provider or self._registry.search_with_outcomes)(
                keywords=(
                    self._collection_queries(collection_plan)
                    if collection_plan is not None
                    else mission.keywords
                ),
                geo=mission.geo_code,
                # Both forms of the window: some connectors read only `timeframe`, and left at
                # its 24h default they searched a different window from the mission's.
                timeframe=resolve_timeframe(mission.timeframe),
                target_platforms=mission.platforms,
                target_surfaces=(
                    tuple(execution_requirements.get("resources", ()))
                    if manifest is not None
                    else None
                ),
                custom_timeframe=mission.timeframe,
            )
            surface_outcomes = search.outcomes
            if manifest is not None:
                surface_outcomes = self._complete_surface_outcomes(
                    manifest, search.outcomes, execution_requirements
                )
            signals = search.signals

            # Fail-safe: a connector can exhaust its quota mid-pass, and the mission should not
            # lose the platform it already had. What it keeps is the evidence -- the observations
            # themselves stay exactly as they were recorded. They are deliberately not merged
            # into `signals`: everything in that list goes through the writer as a new collection
            # event, so preserving a platform that way would claim the harness polled something
            # it could not reach, and would add an observation on every failed pass.
            existing_signals = await self._repo.get_mission_signals(mission.id)
            preserved: List[TrendSignal] = []
            if existing_signals:
                existing_platforms = {s.platform for s in existing_signals}
                new_platforms = {s.platform for s in signals}
                for missing_plat in existing_platforms - new_platforms:
                    kept = [s for s in existing_signals if s.platform == missing_plat]
                    logger.warning(f"Preserving {len(kept)} signals for platform {missing_plat} due to ingress quota fallback.")
                    preserved.extend(kept)

            # 2. Tag signals with mission_id
            for s in signals:
                s.mission_id = mission.id

            # 3. Semantic clustering, over what the mission will hold in total
            clusters = (
                await self._clusterer.cluster_signals(signals + preserved)
                if (signals or preserved)
                else []
            )

            # 4. Failure-safe evidence replacement: write first, prune last.
            #
            # It withdrew first before, on its own committed statement, so anything that failed
            # afterwards left the mission with no evidence at all -- neither the new nor the old.
            # It was labelled an Atomic Replace and was neither.
            #
            # This is not atomic either, and does not claim to be. What it guarantees is
            # narrower than "at every point the pass can fail": any failure before or during the
            # prune leaves the mission holding at least the evidence it started with. Once the
            # prune succeeds the replacement is complete, and a later failure -- update_mission
            # marking the mission COMPLETED, for one -- is a failure after the fact, not a loss
            # of evidence. Stale claims surviving a failure are removed by the next pass;
            # evidence deleted by a failed pass is gone.
            if expiry_guard is not None:
                expiry_guard()
            if clusters:
                await self._repo.save_clusters(clusters)
            if expiry_guard is not None:
                expiry_guard()
            if signals:
                if journal is None:
                    await self._repo.save_signals(signals)
                else:
                    await cast(ICollectionRelayWriter, self._workspace_store).commit_collection_observations(
                        mission.id, journal.run_id, signals
                    )
            if expiry_guard is not None:
                expiry_guard()
            if preserved:
                if journal is None:
                    await self._repo.attach_mission_evidence(mission.id, preserved)
                else:
                    await cast(ICollectionRelayWriter, self._workspace_store).commit_collection_membership(
                        mission.id, journal.run_id, preserved
                    )
                await self._repo.assign_observation_clusters(preserved)

            signals = signals + preserved

            # 5. Now, and only now, drop the claims this pass did not renew. The retained set is
            # the observations that actually survived the writes, read back off the signals
            # rather than assumed: a sighting the writer skipped carries no observation id and
            # must not be treated as evidence this mission holds.
            retained = [s.observation_id for s in signals if s.observation_id]
            if journal is None:
                await self._repo.prune_mission_evidence(mission.id, retained)
            else:
                await cast(ICollectionRelayWriter, self._workspace_store).commit_collection_pruning(
                    mission.id, journal.run_id, retained
                )
            active_platforms = list(set(s.platform.value if hasattr(s.platform, "value") else str(s.platform) for s in signals))
            active_plat_str = ", ".join(active_platforms) if active_platforms else "none"

            if journal is not None:
                await self._record_probe_outcomes(
                    mission,
                    journal,
                    surface_outcomes,
                    collection_plan_digest=collection_plan_digest,
                )

            mission.status = "COMPLETED"
            mission.summary = f"Successfully collected {len(signals)} signals across {len(active_platforms)}/{len(mission.platforms)} responsive platforms ({active_plat_str}), discovered {len(clusters)} topic clusters."
            await self._update_collection_state(mission, journal)

            logger.info(f"Research Mission {mission_id} completed: {mission.summary}")
            result = {
                "mission_id": str(mission.id),
                "title": mission.title,
                "status": mission.status,
                "total_signals": len(signals),
                "total_clusters": len(clusters),
                "summary": mission.summary,
            }
            if collection_plan_digest is not None:
                result["collection_plan_digest"] = collection_plan_digest
                result["collection_plan"] = collection_plan
            return result
        except (Exception, asyncio.CancelledError) as e:
            safe_error = (
                "Mission execution cancelled"
                if isinstance(e, asyncio.CancelledError)
                else sanitize_pii_text(str(e))
            )
            # Preserve the exception type for callers and tests, but replace its display payload
            # before any logger, mission summary, or upstream handler can render it.
            try:
                e.args = (safe_error,)
            except (AttributeError, TypeError):
                pass
            logger.error("Error executing Research Mission %s: %s", mission_id, safe_error)
            try:
                await await_settled(self._settle_collection_failure(mission, journal, safe_error))
            except (Exception, asyncio.CancelledError):
                # Cleanup cannot replace the original refusal or cancellation. In particular,
                # a refused terminal event leaves the earlier RUNNING fact untouched.
                logger.error("Could not settle failure state for Research Mission %s", mission_id)
            raise
