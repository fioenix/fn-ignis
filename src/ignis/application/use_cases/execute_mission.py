import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from ignis.application.ports.clustering_port import IClusteringEngine
from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import IResearchWorkspaceStore
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import VocabularySynchronizationError
from ignis.domain.research_workspace import (
    REQUIRED_BRIEF_FIELDS,
    IncompleteMarketBriefError,
    MissionProbeOutcome,
    ResearchSurface,
    WorkspaceScopeMismatchError,
    compute_query_fingerprint,
    resolve_surface,
)
from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)


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

    async def _synchronize_vocabulary(self, mission) -> None:
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
            await self._repo.update_mission(mission)
            raise

    async def execute(self, mission_id: UUID) -> Dict[str, Any]:
        mission = await self._repo.get_mission(mission_id)
        if not mission:
            raise ValueError(f"Research Mission {mission_id} does not exist.")

        await self._require_confirmed_brief(mission)

        workspace = await self._run_workspace(mission)
        if workspace is None:
            await self._synchronize_vocabulary(mission)
            return await self._execute_pass(mission)

        # The claim is taken before anything else writes, so a refused second run never touches
        # the state of the run that holds the mission -- not even to record that its own
        # vocabulary read failed. Synchronization follows the claim and still precedes RUNNING
        # and every connector call. The claim and the journal are given back by the context
        # manager, including when synchronization or the pass raises.
        async with self._workspace_store.mission_run(workspace, mission.id) as journal:
            await self._synchronize_vocabulary(mission)
            result = await self._execute_pass(mission, journal=journal)
            result["run"] = {
                "run_id": str(journal.run_id),
                "workspace_id": str(journal.workspace_id),
                "journal_path": str(journal.journal_path),
                "journal_status": "COMPLETED",
            }
            return result

    async def _record_probe_outcomes(self, mission, journal, outcomes) -> None:
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
                    query_fingerprint=compute_query_fingerprint(
                        outcome.queried_keywords, mission.geo_code, mission.timeframe
                    ),
                    completed_at=completed_at,
                )
                for outcome in outcomes
            ],
        )

    async def _execute_pass(self, mission, journal=None) -> Dict[str, Any]:
        mission_id = mission.id
        logger.info(f"Executing Research Mission '{mission.title}' [ID: {mission_id}] with keywords: {mission.keywords} (Timeframe: {mission.timeframe})...")
        mission.status = "RUNNING"
        await self._repo.update_mission(mission)

        try:
            # 1. Targeted ingress across active connector plugins, with the outcome of every
            # surface it reached: a workspace run records them, so a reopened report can tell a
            # measured zero from a probe that never measured.
            search = await self._registry.search_with_outcomes(
                keywords=mission.keywords,
                geo=mission.geo_code,
                target_platforms=mission.platforms,
                custom_timeframe=mission.timeframe,
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
            if clusters:
                await self._repo.save_clusters(clusters)
            if signals:
                await self._repo.save_signals(signals)
            if preserved:
                await self._repo.attach_mission_evidence(mission.id, preserved)
                await self._repo.assign_observation_clusters(preserved)

            signals = signals + preserved

            # 5. Now, and only now, drop the claims this pass did not renew. The retained set is
            # the observations that actually survived the writes, read back off the signals
            # rather than assumed: a sighting the writer skipped carries no observation id and
            # must not be treated as evidence this mission holds.
            retained = [s.observation_id for s in signals if s.observation_id]
            await self._repo.prune_mission_evidence(mission.id, retained)
            active_platforms = list(set(s.platform.value if hasattr(s.platform, "value") else str(s.platform) for s in signals))
            active_plat_str = ", ".join(active_platforms) if active_platforms else "none"

            if journal is not None:
                await self._record_probe_outcomes(mission, journal, search.outcomes)

            mission.status = "COMPLETED"
            mission.summary = f"Successfully collected {len(signals)} signals across {len(active_platforms)}/{len(mission.platforms)} responsive platforms ({active_plat_str}), discovered {len(clusters)} topic clusters."
            await self._repo.update_mission(mission)

            logger.info(f"Research Mission {mission_id} completed: {mission.summary}")
            return {
                "mission_id": str(mission.id),
                "title": mission.title,
                "status": mission.status,
                "total_signals": len(signals),
                "total_clusters": len(clusters),
                "summary": mission.summary,
            }
        except Exception as e:
            logger.error(f"Error executing Research Mission {mission_id}: {e}", exc_info=True)
            mission.status = "FAILED"
            mission.summary = f"Execution error: {str(e)}"
            await self._repo.update_mission(mission)
            raise e

