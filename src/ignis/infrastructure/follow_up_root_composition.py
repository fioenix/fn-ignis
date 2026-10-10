"""Private root-supplied host composition; no CLI, discovery or automatic source grants.

The trusted root validates existing owner authority before supplying the explicit instruction
and Brief receipt. These functions check matching bindings; a receipt is not independent
proof of human consent. Mission content and credentials are never embedded here.
"""
from datetime import datetime, timedelta, timezone
import os
from hashlib import sha256
from uuid import UUID

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionPlan, FollowUpExecutionBoundaryError
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.follow_up_admission import SourceGrant, digest
from ignis.infrastructure.follow_up_host_activation import RootOwnerConfirmation
from ignis.infrastructure.follow_up_provider_bridge import TransportBinding, _plan_value
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.domain.research_workspace import compute_frame_fingerprint


class StartupRetentionFailure(FollowUpExecutionBoundaryError):
    """Safe failed-startup disposition; original scope survives only for explicit deletion."""

    def __init__(self, recovery):
        super().__init__('Sealed startup failed; original storage remains closed for expiry recovery.')
        self.recovery = recovery


class _ClosedStartupRetention:
    """Original settled root ownership, without writer, execution or fresh host capability."""

    def __init__(self, canonical, metadata, host, accounting):
        self.confirmation = canonical.confirmation
        self._canonical, self._metadata = canonical, metadata
        self._host, self._accounting = host, accounting
        self._request = canonical._request()
        self._database_hash = sha256(canonical.path.read_bytes()).hexdigest()
        self._accounting_identity = (accounting.path.stat().st_dev,accounting.path.stat().st_ino) if accounting else None

    async def purge(self, *, now):
        """Consume the original ownership at expiry; never reopen a writer or source lease."""
        from ignis.infrastructure.follow_up_host_activation import IsolatedCanonicalSQLite
        from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage
        metadata = self._metadata
        bounds = self.confirmation.bounds
        if (now < bounds.retention_until or metadata.active_run or not metadata.closed
                or not self._canonical.closed
                or (self._host is not None and (not self._host._revoked or self._host._tokens or self._host._tasks))):
            raise FollowUpExecutionBoundaryError()
        state = metadata._load()
        # Refuse changed registered payloads/directories before any canonical deletion.
        for key,identity in state['directories'].items():
            path = metadata.root/key
            metadata._relative(path)
            if path.exists() and [path.stat().st_dev,path.stat().st_ino] != identity:
                raise FollowUpExecutionBoundaryError()
        for key,record in state['files'].items():
            path = metadata.root/key
            metadata._relative(path)
            if path.exists():metadata._validate(path,record)
        canonical = (self._canonical if self._canonical._deletion_only else
            IsolatedCanonicalSQLite.reopen_for_deletion(self._canonical.root,self.confirmation))
        if canonical._request() != self._request:
            raise FollowUpExecutionBoundaryError()
        if canonical.path.exists() and sha256(canonical.path.read_bytes()).hexdigest() != self._database_hash:
            raise FollowUpExecutionBoundaryError()
        self._canonical = canonical
        private_audit = None
        if self._accounting is not None:
            path = self._accounting.path
            if (path.is_symlink() or path.parent.is_symlink()
                    or (path.stat().st_dev,path.stat().st_ino) != self._accounting_identity):
                raise FollowUpExecutionBoundaryError()
            def deletion_only(operation,run_id,bounds_digest):
                return (operation=='purge' and run_id==bounds.run_id and bounds_digest==digest(bounds))
            private = PrivateRunStorage(path.parent,authorize=deletion_only)
            private_audit = private.purge(bounds,now=now)
        canonical_audit = canonical._purge_closed(now=now)
        metadata_audit = metadata.purge(now=now)
        return {'private_audit':private_audit,'canonical_audit':canonical_audit,'metadata_audit':metadata_audit}



def _validate_instruction(record):
    """Keep this private pilot's exact supported source/window/budget contract."""
    required={'reference','credential_reference','queries','geo','timeframe','source','platform',
        'tier','revision','video_limit','search_calls','other_calls','run_minutes','retention_days'}
    if (type(record) is not dict or set(record)!=required
            or any(type(record[key]) is not str or not record[key].strip()
                   for key in ('reference','credential_reference'))
            or type(record['queries']) is not list or len(record['queries'])!=2
            or any(type(query) is not str or not query.strip() or len(query)>512 for query in record['queries'])
            or len(set(record['queries']))!=2
            or (record['geo'],record['timeframe'],record['source'],record['platform'],record['tier'],record['revision'])
                != ('GeoCode.VN','Timeframe.LAST_30D','youtube','youtube','official_api','unversioned')
            or any(type(record[key]) is not int or record[key]!=value for key,value in
                (('video_limit',5),('search_calls',2),('other_calls',4),('run_minutes',15),('retention_days',7)))):
        raise ValueError('OWNER_SCOPE_CONFIRMATION_REQUIRED')



def confirmation_at_approved_invocation(record, *, mission_id, run_id, started_at=None):
    """Exact reviewed root receipt, not a test boolean or persisted auto-grant."""
    _validate_instruction(record)
    from ignis.infrastructure.follow_up_provider_bridge import RunBounds
    started = started_at or datetime.now(timezone.utc)
    bounds = RunBounds(run_id=UUID(str(run_id)), started_at=started,
        deadline=started+timedelta(minutes=record['run_minutes']),
        retention_until=started+timedelta(days=record['retention_days']),
        queries=tuple(record['queries']), video_limit=record['video_limit'],
        search_calls=record['search_calls'], other_calls=record['other_calls'])
    return RootOwnerConfirmation(reference=record['reference'], credential_reference=record['credential_reference'],
        bounds=bounds, selected_parent_id=UUID(str(mission_id)), source=record['source'],
        platform=record['platform'], tier=record['tier'], revision=record['revision'],
        geo=record['geo'], timeframe=record['timeframe'])


def deferred_injected_key():
    """Called only by private guarded transport after proof and persisted attempt charge."""
    value = os.environ.get('YOUTUBE_API_KEY')
    if not value:
        raise ValueError('CREDENTIAL_INJECTION_UNAVAILABLE')
    return value


async def run_canonical_parent(*, host, bridge, executor, parent_work_id):
    """Actual production parent execution, refusing absent approved canonical inputs first.

    Host/controller/plugin/registry/budget are explicitly constructed by the root. This
    function does not invent a Market Brief, work assignment, gap, child or analysis verdict.
    """
    if type(executor) is not ExecuteMissionUseCase or executor._registry is not host.registry:
        return {'status': 'REFUSED', 'reason_code': 'OWNED_EXECUTOR_REQUIRED'}
    repository = executor._repo
    enrollment = getattr(repository, 'enrollment', None)
    if enrollment is None or enrollment.confirmation != host.confirmation:
        return {'status': 'REFUSED', 'reason_code': 'CANONICAL_RETENTION_ENROLLMENT_REQUIRED'}
    canonical = await executor._workspace_store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
    if canonical.mission is None or canonical.manifest is None or canonical.brief is None:
        return {'status': 'REFUSED', 'reason_code': 'CONFIRMED_CANONICAL_BRIEF_REQUIRED'}
    research = await repository.load_research_work(canonical.mission.id)
    work = next((row for row in research.work_items if row.work_id == UUID(str(parent_work_id))), None)
    if work is None or work.epoch != research.current_epoch:
        return {'status': 'REFUSED', 'reason_code': 'CURRENT_CANONICAL_PARENT_WORK_REQUIRED'}
    try:
        frame = frame_from_snapshot(canonical)
    except ValueError:
        return {'status': 'REFUSED', 'reason_code': 'CURRENT_CANONICAL_PARENT_FRAME_REQUIRED'}
    if (work.inputs.frame_digest != frame.frame_digest or work.inputs.mission_id != canonical.mission.id
            or work.inputs.manifest_digest != canonical.manifest.manifest_digest):
        return {'status': 'REFUSED', 'reason_code': 'CURRENT_CANONICAL_PARENT_FRAME_REQUIRED'}
    if canonical.mission.status in ('COMPLETED', 'CANCELLED', 'FAILED', 'INSUFFICIENT_EVIDENCE'):
        return {'status': 'REFUSED', 'reason_code': 'PARENT_ALREADY_TERMINAL'}
    confirmation = host.confirmation
    if (tuple(canonical.mission.keywords) != confirmation.bounds.queries[:1]
            or tuple(str(getattr(item,'value',item)) for item in canonical.mission.platforms) != ('youtube',)
            or _plan_value(canonical.mission.geo_code,GeoCode) != _plan_value(confirmation.geo,GeoCode)
            or _plan_value(canonical.mission.timeframe,Timeframe) != _plan_value(confirmation.timeframe,Timeframe)
            or work.inputs.brief_digest != compute_frame_fingerprint(canonical.mission,canonical.brief)
            or [item.plugin_id for item in host.registry.list_plugins()] != [confirmation.source]):
        return {'status':'REFUSED','reason_code':'CANONICAL_OWNER_SCOPE_MISMATCH'}
    plugin = host.registry.get_plugin_by_id(confirmation.source)
    if plugin is None:
        return {'status': 'REFUSED', 'reason_code': 'SOURCE_CAPABILITY_UNAVAILABLE'}
    queries = confirmation.bounds.queries[:1]
    metadata = host.registry._search_requirement(plugin, confirmation.tier, list(queries))
    plan = FollowUpExecutionPlan(queries=queries,
        connectors=((plugin.plugin_id, plugin.platform.value, confirmation.tier, plugin.connector_revision,
            metadata['connector_path'], metadata['sampling']['limit'], metadata['sampling']['ordering'],
            metadata['requires_paid_quota']),),
        resources=(('queries',1),('youtube_search_calls',1)), geo=confirmation.geo, timeframe=confirmation.timeframe)
    source = SourceGrant(source=confirmation.source, platform=confirmation.platform, tier=confirmation.tier,
        connector_revision=confirmation.revision, paid=False, plan_digest=plan.digest,
        capability_id=host.capability_id, capability_epoch=host.generation)
    binding = TransportBinding(inputs=work.inputs, work_id=work.work_id, epoch=work.epoch,
        authority_digest=digest(('parent',work.work_id,work.inputs,plan.digest)), plan_digest=plan.digest,
        geo=plan.geo,timeframe=plan.timeframe,sources=(source,),queries=queries,confirmation_ref=confirmation.reference)
    host.enroll_parent(binding,plan)
    bridge.register(binding)
    async with host.hold_parent(binding) as lease:
        async with bridge.hold_parent_transport(binding,lease):
            result = await executor.execute(canonical.mission.id)
    after = await executor._workspace_store.load_mission_evidence_snapshot(canonical.mission.id)
    return {'status':'PARENT_EXECUTION_RETURNED','parent_mission_id':str(canonical.mission.id),
        'parent_work_id':str(work.work_id),'input_frame_digest':frame.frame_digest,
        'observations':len(after.signals),'channel_outcomes':[row.status for row in after.outcomes],
        'child_status':'NOT_ADMITTED','analysis_status':'QUALIFICATION_AND_CANONICAL_GAP_REQUIRED',
        'executor_status':str(result.get('status','UNKNOWN'))}


async def expire_owned_storage(host, canonical, repository, accounting):
    """Explicit root lifecycle, with durable phase readback and deletion-only retry."""
    metadata = canonical.generated_metadata
    if metadata.active_run:
        raise ValueError('OWNED_EXECUTION_NOT_QUIESCENT')
    phase = metadata._load().get('private_audit')
    if phase is None:
        phase = accounting.purge(host.confirmation.bounds, now=host.clock())
        metadata.record_phase('private_audit',phase)
    canonical_audit = await canonical.purge(host, repository)
    metadata.close()
    metadata_audit = metadata.purge(now=host.clock())
    return {'private_audit':phase,'canonical_audit':canonical_audit,'metadata_audit':metadata_audit}



def validate_brief_confirmation(brief, receipt, instruction):
    """The trusted root supplies this specific receipt; proposed content is not authority."""
    _validate_instruction(instruction)
    required = {'decision', 'target_user', 'problem', 'geo', 'timeframe', 'hypothesis',
        'falsifiers', 'alternative_hypotheses', 'null_hypothesis', 'kill_criteria', 'revision_rule'}
    if (type(brief) is not dict or set(brief) != required
            or type(receipt) is not dict or set(receipt) != {'status', 'reference', 'owner_reference',
                'payload_digest', 'collection_scope_digest', 'confirmed_by'}
            or receipt['status'] != 'CONFIRMED'
            or not isinstance(receipt['reference'], str) or not receipt['reference'].strip()
            or not isinstance(receipt['confirmed_by'], str) or not receipt['confirmed_by'].strip()
            or receipt['owner_reference'] != instruction['reference']
            or receipt['payload_digest'] != digest(brief)
            or receipt['collection_scope_digest'] != digest(instruction)
            or brief['geo'] != 'VN' or brief['timeframe'] != '30d'):
        raise ValueError('EXPLICIT_COMPATIBLE_BRIEF_CONFIRMATION_REQUIRED')


async def bootstrap_confirmed_parent(*, root, brief, receipt, instruction, resolve_credential,
                                     transport, quota_manager, clusterer):
    """Offline-reviewable host bootstrap; no helper, child, qualification or verdict is inferred."""
    validate_brief_confirmation(brief, receipt, instruction)
    from pathlib import Path
    from uuid import uuid4
    from types import MethodType
    from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
    from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
    from ignis.infrastructure.follow_up_host_activation import (
        PreparedCanonicalSQLite, RootHostController, open_owned_canonical_repository)
    from ignis.infrastructure.follow_up_provider_bridge import HostProviderBridge, HostBoundYouTubePlugin
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
    from ignis.domain.research_workspace import (
        MissionManifest, AuthorityBoundary, MissionOutputType, derive_collection_plan)
    from ignis.domain.research_work import (
        ResearchInputBindings, ResearchAuthority, ResearchAssignment, ResearchWorkItem)
    from ignis.application.ports.research_work_port import ResearchWorkCommitCommand, ResearchAssignmentAdmission
    from ignis.infrastructure.follow_up_workspace_retention import GeneratedWorkspaceRetention, RetainedWorkspaceRepository
    root = Path(root)
    invocation_started = datetime.now(timezone.utc)
    metadata = GeneratedWorkspaceRetention(root,owner_reference=instruction['reference'],
        scope_digest=digest(instruction),retention_until=invocation_started+timedelta(days=instruction['retention_days']),
        create=True)
    prepared = PreparedCanonicalSQLite(root/'canonical', owner_reference=instruction['reference'],
                                       collection_scope_digest=digest(instruction))
    metadata.bind_bootstrap(prepared)
    repository = prepared.repository
    metadata.active_run = True
    try:
        await repository._ensure_schema()
        store = RetainedWorkspaceRepository(repository,metadata)
        creator = CreateResearchWorkspaceUseCase(store)
        workspace = await store.create_owned_workspace(await creator.propose(root, 'Bounded confirmed source research'))
        manifest = MissionManifest(outcome=brief['decision'], decision_context=brief['decision'],
            required_channels=('youtube',), optional_channels=(),
            authority_boundary=AuthorityBoundary(public_http=False, official_api=True,
                browser_session=False, paid_quota=False),
            quota_budget={'queries':2, 'youtube_search_calls':2},
            output_type=MissionOutputType.MARKET_ANALYSIS,
            stop_conditions=('deadline or aggregate budget or missing authority',),
            analysis_policy='evidence-gated-v1', retention_policy='exclusive-owned-seven-day-host-disposition',
            created_by=receipt['confirmed_by'], confirmed_at=datetime.now(timezone.utc))
        mission, revision = await ConfirmMarketBriefUseCase(repository, store).execute(
            workspace_id=workspace.workspace_id, manifest=manifest,
            confirmed_by=receipt['confirmed_by'], keywords=instruction['queries'][:1], **brief)
        confirmation = confirmation_at_approved_invocation(instruction, mission_id=mission.id, run_id=uuid4(), started_at=invocation_started)
        enrollment = await prepared.seal(confirmation, repository)
        metadata.seal_bootstrap(prepared)
        enrollment.generated_metadata = metadata
        repository = open_owned_canonical_repository(enrollment)
        store = RetainedWorkspaceRepository(repository,metadata)
        registry = ConnectorPluginRegistry()
        host = RootHostController(confirmation, registry, scope_path=root/'root-scope.json', create=True,
                                  clock=lambda: datetime.now(timezone.utc))
        accounting = PrivateRunStorage(root/'accounting', authorize=host.authorize_storage, create=True)
        budget = DurableRunCallBudget(confirmation.bounds, storage=accounting, register=True, clock=host.clock)
        bridge = HostProviderBridge(host, budget, selected_parent_id=mission.id)
        plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=resolve_credential,
                                       transport=transport, quota_manager=quota_manager)
        registry.register(plugin)
        executor = ExecuteMissionUseCase(repository, registry, clusterer, workspace_store=store)
        original_policy = executor._collection_plan_for_brief
        def bounded_policy(self, selected, selected_manifest, requirements, selected_brief):
            if (selected.id != mission.id or selected_manifest.manifest_digest != manifest_for_run.manifest_digest
                    or selected_brief != revision or tuple(selected.keywords) != tuple(instruction['queries'][:1])):
                raise ValueError('EXACT_QUERY_PLAN_REQUIRED')
            original = original_policy(selected, selected_manifest, requirements, selected_brief)
            # Analytical falsifiers remain in the Brief. All three evidence roles inspect the
            # same explicitly approved provider query; none licenses an additional search phrase.
            surface = original['probes'][0]
            actual = {key:surface[key] for key in ('authority_tier','connector_path','connector_revision','sampling')}
            families = {'root':tuple(selected.keywords), 'expanded':(), 'exclusions':(), 'falsification':()}
            return derive_collection_plan(mission_id=selected.id, manifest=selected_manifest,
                keywords=selected.keywords, geo=selected.geo_code, timeframe=selected.timeframe,
                surface_requirements={'youtube':actual}, evidence_targets=('core',), expected_role='SUPPORT',
                audience=selected_brief.target_user, language='vi',
                probe_intents=tuple({'evidence_targets':('neutral',) if role=='CONTEXT' else ('core',),
                    'expected_role':role,'query_families':families} for role in ('SUPPORT','CONTRADICTION','CONTEXT')))
        manifest_for_run = await store.get_mission_manifest(mission.id)
        executor._collection_plan_for_brief = MethodType(bounded_policy, executor)
        requirements = await executor._require_manifest_authority(mission)
        checked_plan = await executor._build_collection_plan(mission, requirements[0], requirements[1])
        if executor._collection_queries(checked_plan) != instruction['queries'][:1]:
            raise ValueError('EXACT_QUERY_PLAN_REQUIRED')
        connector_metadata = registry._search_requirement(plugin, confirmation.tier, list(mission.keywords))
        plan = FollowUpExecutionPlan(queries=tuple(mission.keywords), connectors=((plugin.plugin_id,
            plugin.platform.value, confirmation.tier, plugin.connector_revision, connector_metadata['connector_path'],
            connector_metadata['sampling']['limit'],connector_metadata['sampling']['ordering'],False),),
            resources=(('queries',1),('youtube_search_calls',1)),geo=confirmation.geo,timeframe=confirmation.timeframe)
        precollection = digest(('PRECOLLECTION',mission.id,manifest_for_run.manifest_digest,
                               compute_frame_fingerprint(mission,revision),checked_plan['plan_digest']))
        inputs = ResearchInputBindings(mission_id=mission.id, manifest_digest=manifest_for_run.manifest_digest,
            brief_digest=compute_frame_fingerprint(mission,revision),frame_digest=precollection,
            observation_ids=(),finding_revisions=())
        source = SourceGrant(source='youtube',platform='youtube',tier=confirmation.tier,
            connector_revision=plugin.connector_revision,paid=False,plan_digest=plan.digest,
            capability_id=host.capability_id,capability_epoch=host.generation)
        binding = TransportBinding(inputs=inputs,work_id=mission.id,epoch=1,
            authority_digest=digest(('INITIAL_PARENT_CORRELATION',mission.id,inputs,plan.digest)),
            plan_digest=plan.digest,geo=plan.geo,timeframe=plan.timeframe,sources=(source,),
            queries=plan.queries,confirmation_ref=confirmation.reference)
        host.enroll_parent(binding,plan)
        bridge.register(binding)
        async with host.hold_parent(binding) as lease:
            async with bridge.hold_parent_transport(binding,lease):
                result = await executor.execute(mission.id)
        snapshot = await store.load_mission_evidence_snapshot(mission.id)
        frame = frame_from_snapshot(snapshot)
        research = await repository.load_research_work(mission.id)
        epoch = research.current_epoch+1
        assignment = ResearchAssignment(assignment_id=uuid4(),mission_id=mission.id,
            host_task_ref=receipt['reference'],epoch=epoch,
            authority=ResearchAuthority(actions=frozenset({'ANALYZE','FOLLOW_UP'}),sources=frozenset({'youtube'}),
                deadline=confirmation.bounds.deadline,quota_ceiling=2),capability='SEQUENTIAL',state='ASSIGNED',version=1)
        assigned = await repository.commit_research_work(ResearchWorkCommitCommand(mission_id=mission.id,
            operation='ASSIGN_RESEARCH',payload=ResearchAssignmentAdmission(assignment=assignment,
                expected_manifest_digest=manifest_for_run.manifest_digest,expected_brief_revision_id=revision.brief_revision_id),
            expected_revision=research.revision,expected_epoch=epoch,idempotency_key=uuid4().hex,host_authorized=True))
        if assigned.disposition != 'APPLIED':
            raise ValueError('CANONICAL_ASSIGNMENT_REFUSED:'+assigned.reason_code)
        after_inputs = ResearchInputBindings(mission_id=mission.id,manifest_digest=manifest_for_run.manifest_digest,
            brief_digest=compute_frame_fingerprint(mission,revision),frame_digest=frame.frame_digest,
            observation_ids=tuple(sorted((s.observation_id for s in snapshot.signals),key=str)),finding_revisions=())
        work = ResearchWorkItem(work_id=uuid4(),assignment_id=assignment.assignment_id,mission_id=mission.id,
            run_id=snapshot.outcomes[0].run_id,question=brief['decision'],expertise='Descriptive synthesis',
            assignee_ref=receipt['confirmed_by'],inputs=after_inputs,dependencies=(),epoch=epoch,state='ASSIGNED',
            version=1,ownership_fence=uuid4().hex)
        worked = await repository.commit_research_work(ResearchWorkCommitCommand(mission_id=mission.id,
            operation='ASSIGN_WORK',payload=work,expected_revision=assigned.revision,expected_epoch=epoch,
            idempotency_key=uuid4().hex,host_authorized=True))
        if worked.disposition != 'APPLIED':
            raise ValueError('CANONICAL_WORK_REFUSED:'+worked.reason_code)
        return {'status':'PARENT_EXECUTED_ANALYSIS_ASSIGNED','workspace_id':str(workspace.workspace_id),
            'mission_id':str(mission.id),'brief_revision_id':str(revision.brief_revision_id),
            'assignment_id':str(assignment.assignment_id),'work_id':str(work.work_id),
            'execution_run_id':str(work.run_id),'accounting_run_id':str(confirmation.bounds.run_id),
            'frame_digest':frame.frame_digest,'precollection_scope_fingerprint':precollection,
            'precollection_identity_kind':'CANONICAL_MISSION_CORRELATION_NOT_RESEARCH_WORK',
            'research_revision':worked.revision,'observations':len(snapshot.signals),
            'child_status':'NOT_ADMITTED','analysis_status':'QUALIFICATION_AND_GENUINE_CANONICAL_GAP_REQUIRED',
            'executor_status':result.get('status','UNKNOWN'),'canonical':enrollment,'repository':repository,
            'host':host,'accounting':accounting,'executor':executor,'bridge':bridge}
    except BaseException as error:
        if 'host' in locals():
            await host.revoke()
        await repository.close()
        prepared._closed = True
        metadata.close()
        if 'enrollment' in locals():
            enrollment.closed = True
            recovery = _ClosedStartupRetention(enrollment,metadata,locals().get('host'),locals().get('accounting'))
            if isinstance(error,Exception):
                raise StartupRetentionFailure(recovery) from None
            # Preserve cancellation semantics while still returning the original closed disposition.
            error.recovery = recovery
        raise
    finally:
        metadata.active_run = False
