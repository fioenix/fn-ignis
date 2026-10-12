"""Private caller-scope source activation supplied by a trusted embedding root.

The activation object is passed in by process-local construction. It is never derived from
configuration, environment, persisted receipts, caller roots or tool arguments, and the
production lifespan supplies none, so native follow-up execution stays refused by default.
"""
import asyncio

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError


def _bounded_executor_class():
    from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
    from ignis.domain.research_workspace import derive_collection_plan

    class BoundedSourceExecutor(ExecuteMissionUseCase):
        """Restricts plans to the mission's own keywords within the approved run queries; never widens."""

        def __init__(self, *args, approved_queries, **kwargs):
            super().__init__(*args, **kwargs)
            self._approved_queries = tuple(approved_queries)

        def _collection_plan_for_brief(self, selected, selected_manifest, requirements, selected_brief):
            if not tuple(selected.keywords) or not set(selected.keywords) <= set(self._approved_queries):
                raise ValueError('EXACT_QUERY_PLAN_REQUIRED')
            original = super()._collection_plan_for_brief(selected, selected_manifest, requirements, selected_brief)
            surface = original['probes'][0]
            actual = {key: surface[key] for key in ('authority_tier', 'connector_path', 'connector_revision', 'sampling')}
            # Analytical falsifiers stay in the Brief; no evidence role licenses an extra search phrase.
            families = {'root': tuple(selected.keywords), 'expanded': (), 'exclusions': (), 'falsification': ()}
            return derive_collection_plan(mission_id=selected.id, manifest=selected_manifest,
                keywords=selected.keywords, geo=selected.geo_code, timeframe=selected.timeframe,
                surface_requirements={'youtube': actual}, evidence_targets=('core',), expected_role='SUPPORT',
                audience=selected_brief.target_user, language='vi',
                probe_intents=tuple({'evidence_targets': ('neutral',) if role == 'CONTEXT' else ('core',),
                    'expected_role': role, 'query_families': families}
                    for role in ('SUPPORT', 'CONTRADICTION', 'CONTEXT')))

    return BoundedSourceExecutor


class CallerSourceActivation:
    """Genuine revocable host and guarded bridge borrowed onto one caller scope's storage."""

    def __init__(self, *, scope, host, bridge, plugin):
        from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
        from ignis.infrastructure.follow_up_host_activation import RootHostController
        from ignis.infrastructure.follow_up_provider_bridge import HostBoundYouTubePlugin, HostProviderBridge
        from ignis.infrastructure.follow_up_run_storage import DurableRunCallBudget, PrivateRunStorage
        components = getattr(scope, 'components', None)
        budget = getattr(bridge, 'budget', None)
        storage = getattr(budget, 'storage', None)
        if (type(host) is not RootHostController or type(bridge) is not HostProviderBridge
                or bridge._host is not host or type(plugin) is not HostBoundYouTubePlugin
                or plugin._bridge is not bridge or components is None or host._revoked
                or bridge.selected_parent_id != host.confirmation.selected_parent_id
                # The host must attest exactly the guarded plugin the private executor uses.
                or host.registry.list_plugins() != [plugin]
                or host.registry.get_plugin_by_id(plugin.plugin_id) is not plugin
                # Shared aggregate attempts come from the original durable run accounting.
                or type(budget) is not DurableRunCallBudget or budget.bounds != host.confirmation.bounds
                or type(storage) is not PrivateRunStorage
                # The ledger is the one this host authorized to register, not a same-bounds copy.
                or getattr(storage.authorize, '__self__', None) is not host
                or getattr(storage.authorize, '__func__', None) is not RootHostController.authorize_storage
                or not host._storage_registered
                # Exactly the ledger object the host attested at construction, at its original path.
                or host._storage is None or host._storage[0] is not storage
                or storage.path != host._storage[1]
                or (storage.path.stat().st_dev, storage.path.stat().st_ino) != host._storage[2]):
            raise FollowUpExecutionBoundaryError()
        storage.reopen(budget.bounds)
        base = components.get('execute_mission_use_case')
        repository, store = components.get('repository'), components.get('workspace_store')
        if (type(base) is not ExecuteMissionUseCase or base._repo is not repository
                or base._workspace_store is not store or store is None or store._repo is not repository):
            raise FollowUpExecutionBoundaryError()
        self.scope, self.host, self.bridge, self.plugin = scope, host, bridge, plugin
        self.repository, self.workspace_store = repository, store
        self.storage, self.bounds = storage, budget.bounds
        self._storage_identity = (storage.path.stat().st_dev, storage.path.stat().st_ino)
        self.owner_loop = asyncio.get_running_loop()
        self.selected_parent_id = host.confirmation.selected_parent_id
        self.accounting_close = 'NOT_CLOSED'
        self.revoked = False
        # The host's private one-source registry; the caller's shared registry stays unchanged.
        self.executor = _bounded_executor_class()(repository=repository, registry=host.registry,
            clusterer=base._clusterer, workspace_store=store, vocabulary_sync=base._vocabulary_sync,
            run_started=base._run_started, approved_queries=self.bounds.queries)
        self.attached = False

    async def run_parent(self, mission_id):
        """Execute the selected confirmed caller parent through the held guarded bridge.

        Before collection no evidence frame exists, so the binding uses the canonical
        precollection correlation of mission, manifest, Brief and checked plan.
        """
        from ignis.application.ports.follow_up_execution_port import FollowUpExecutionPlan
        from ignis.domain.follow_up_admission import SourceGrant, digest
        from ignis.domain.research_work import ResearchInputBindings
        from ignis.domain.research_workspace import compute_frame_fingerprint
        from ignis.domain.value_objects import GeoCode, Timeframe
        from ignis.infrastructure.follow_up_provider_bridge import TransportBinding, _plan_value
        confirmation = self.host.confirmation
        if mission_id != self.selected_parent_id:
            return {'status': 'REFUSED', 'reason_code': 'SCOPE_MISMATCH'}
        store, executor, plugin = self.workspace_store, self.executor, self.plugin
        canonical = await store.load_mission_evidence_snapshot(mission_id)
        mission = canonical.mission
        if mission is None or canonical.manifest is None or canonical.brief is None:
            return {'status': 'REFUSED', 'reason_code': 'CONFIRMED_CANONICAL_BRIEF_REQUIRED'}
        if mission.status in ('COMPLETED', 'CANCELLED', 'FAILED', 'INSUFFICIENT_EVIDENCE'):
            return {'status': 'REFUSED', 'reason_code': 'PARENT_ALREADY_TERMINAL'}
        if (tuple(mission.keywords) != confirmation.bounds.queries[:1]
                or tuple(str(getattr(item, 'value', item)) for item in mission.platforms) != ('youtube',)
                or _plan_value(mission.geo_code, GeoCode) != _plan_value(confirmation.geo, GeoCode)
                or _plan_value(mission.timeframe, Timeframe) != _plan_value(confirmation.timeframe, Timeframe)):
            return {'status': 'REFUSED', 'reason_code': 'CANONICAL_OWNER_SCOPE_MISMATCH'}
        requirements = await executor._require_manifest_authority(mission)
        checked_plan = await executor._build_collection_plan(mission, requirements[0], requirements[1])
        if executor._collection_queries(checked_plan) != list(confirmation.bounds.queries[:1]):
            return {'status': 'REFUSED', 'reason_code': 'CANONICAL_OWNER_SCOPE_MISMATCH'}
        metadata = self.host.registry._search_requirement(plugin, confirmation.tier, list(mission.keywords))
        plan = FollowUpExecutionPlan(queries=tuple(mission.keywords), connectors=((plugin.plugin_id,
            plugin.platform.value, confirmation.tier, plugin.connector_revision, metadata['connector_path'],
            metadata['sampling']['limit'], metadata['sampling']['ordering'], False),),
            resources=(('queries', 1), ('youtube_search_calls', 1)), geo=confirmation.geo, timeframe=confirmation.timeframe)
        brief_digest = compute_frame_fingerprint(mission, canonical.brief)
        precollection = digest(('PRECOLLECTION', mission.id, canonical.manifest.manifest_digest,
                                brief_digest, checked_plan['plan_digest']))
        inputs = ResearchInputBindings(mission_id=mission.id, manifest_digest=canonical.manifest.manifest_digest,
            brief_digest=brief_digest, frame_digest=precollection, observation_ids=(), finding_revisions=())
        source = SourceGrant(source=confirmation.source, platform=confirmation.platform, tier=confirmation.tier,
            connector_revision=plugin.connector_revision, paid=False, plan_digest=plan.digest,
            capability_id=self.host.capability_id, capability_epoch=self.host.generation)
        binding = TransportBinding(inputs=inputs, work_id=mission.id, epoch=1,
            authority_digest=digest(('INITIAL_PARENT_CORRELATION', mission.id, inputs, plan.digest)),
            plan_digest=plan.digest, geo=plan.geo, timeframe=plan.timeframe, sources=(source,),
            queries=plan.queries, confirmation_ref=confirmation.reference)
        self.host.enroll_parent(binding, plan)
        self.bridge.register(binding)
        async with self.host.hold_parent(binding) as lease:
            async with self.bridge.hold_parent_transport(binding, lease):
                result = await executor.execute(mission.id)
        after = await store.load_mission_evidence_snapshot(mission.id)
        return {'status': 'PARENT_EXECUTION_RETURNED', 'parent_mission_id': str(mission.id),
            'precollection_scope_fingerprint': precollection, 'observations': len(after.signals),
            'channel_outcomes': [row.status for row in after.outcomes],
            'executor_status': str(result.get('status', 'UNKNOWN'))}

    async def enroll_child(self, authority, *, parent_budget, assignment_budget):
        """Bind the sole optional child to a genuine gap of the terminal parent's current frame.

        Returns the authority bound to the actual guarded plan. Admission and execution still
        go through the native follow-up consumer and repository guards.
        """
        from dataclasses import replace
        from uuid import uuid4
        from ignis.application.ports.follow_up_execution_port import FollowUpExecutionContext
        from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
        from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
        from ignis.domain.follow_up_admission import AssignmentBudget, ParentBudget, WorkAuthority
        from ignis.infrastructure.follow_up_provider_bridge import TransportBinding
        from ignis.infrastructure.persistence.follow_up_admission_rules import child_records
        work = getattr(authority, 'work', None)
        if (type(authority) is not WorkAuthority or type(parent_budget) is not ParentBudget
                or type(assignment_budget) is not AssignmentBudget
                or work.inputs.mission_id != self.selected_parent_id
                or authority.budget_id != parent_budget.budget_id
                or authority.binding_id != assignment_budget.binding_id
                or tuple(work.requested_scope.queries) != self.bounds.queries[1:]
                or len(authority.sources) != 1):
            raise FollowUpExecutionBoundaryError()
        canonical = await self.workspace_store.load_mission_evidence_snapshot(self.selected_parent_id)
        if canonical.mission is None or canonical.mission.status != 'COMPLETED':
            raise FollowUpExecutionBoundaryError()
        try:
            frame = frame_from_snapshot(canonical)
        except ValueError:
            raise FollowUpExecutionBoundaryError() from None
        if work.inputs.frame_digest != frame.frame_digest:
            raise FollowUpExecutionBoundaryError()
        research = await self.repository.load_research_work(self.selected_parent_id)
        candidate = child_records(canonical, authority, 1, uuid4(), uuid4())
        context = FollowUpExecutionContext(authority, canonical, research, None, None, *candidate)
        planner = ExecuteMissionFollowUpUseCase(self.repository, self.executor,
            selected_parent_id=self.selected_parent_id, host_authorized=True)
        plan, _ = await planner._plan(context)
        source = authority.sources[0]
        if (source.source, source.platform, source.tier, source.connector_revision) != (
                self.plugin.plugin_id, self.plugin.platform.value, self.host.confirmation.tier,
                self.plugin.connector_revision) or source.paid:
            raise FollowUpExecutionBoundaryError()
        bound = replace(authority, sources=(replace(source, plan_digest=plan.digest,
            capability_id=self.host.capability_id, capability_epoch=self.host.generation),))
        binding = TransportBinding(inputs=work.inputs, work_id=work.work_id, epoch=work.research_epoch,
            authority_digest=bound.digest, plan_digest=plan.digest, geo=plan.geo, timeframe=plan.timeframe,
            sources=bound.sources, queries=tuple(work.requested_scope.queries),
            confirmation_ref=self.host.confirmation.reference)
        self.host.enroll_child(bound, binding, plan)
        self.bridge.register(binding)
        for record in (parent_budget, assignment_budget, bound):
            self.host.confirm_fact(record)
        return bound

    def check(self, scope, loop):
        components = getattr(scope, 'components', None)
        if (scope is not self.scope or loop is not self.owner_loop or components is None
                or components.get('repository') is not self.repository
                or components.get('workspace_store') is not self.workspace_store
                or self.host._revoked):
            raise FollowUpExecutionBoundaryError()

    def attach(self, scope, loop):
        """Bind admission and execution proof to the exact borrowed caller repository."""
        self.check(scope, loop)
        current = getattr(self.repository, '_follow_up_verifier', None)
        if current is not None and current is not self.bridge:
            raise FollowUpExecutionBoundaryError()
        self.repository.configure_follow_up_verifier(self.bridge)
        self.attached = True

    def _detach(self):
        # Detach only this activation's verifier; another owner's verifier is never disturbed.
        if getattr(self.repository, '_follow_up_verifier', None) is self.bridge:
            self.repository.configure_follow_up_verifier(None)
        self.attached = False

    async def close(self):
        """Revoke source authority and durably close accounting; caller data is retained."""
        try:
            if not self.revoked:
                await self.host.revoke()
                self.revoked = True
        except Exception:
            # Revocation is published before settlement; an unsettled revoke stays pending.
            pass
        finally:
            self._detach()
            self.retry_close()
        return self.disposition

    def retry_close(self):
        """Bounded close-only retry on the original run; no lease, count reset, renewal or purge."""
        from ignis.infrastructure.follow_up_root_composition import _close_accounting
        path = self.storage.path
        if (path.is_symlink() or not path.is_file()
                or (path.stat().st_dev, path.stat().st_ino) != self._storage_identity):
            self.accounting_close = 'PENDING'
        else:
            self.accounting_close = _close_accounting(self.storage, self.bounds)
        return self.disposition

    @property
    def disposition(self):
        return 'CLOSED' if self.revoked and self.accounting_close == 'CLOSED' else 'PENDING'
