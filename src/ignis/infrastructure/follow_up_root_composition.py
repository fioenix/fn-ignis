"""Private root-supplied host composition; no CLI, discovery or automatic source grants.

The trusted root validates existing owner authority before supplying the explicit instruction
and Brief receipt. These functions check matching bindings; a receipt is not independent
proof of human consent. Mission content and credentials are never embedded here.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from hashlib import sha256
from uuid import UUID

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionPlan, FollowUpExecutionBoundaryError
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.follow_up_admission import SourceGrant, digest
from ignis.infrastructure.follow_up_host_activation import RootOwnerConfirmation
from ignis.infrastructure.follow_up_provider_bridge import (
    RETAIN_UNTIL_EXPLICIT_USER_DELETION, TransportBinding, _plan_value)
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.domain.research_workspace import compute_frame_fingerprint


class StartupRetentionFailure(FollowUpExecutionBoundaryError):
    """Safe failed-startup disposition; original scope survives only for explicit deletion."""

    def __init__(self, recovery):
        super().__init__('Sealed startup failed; original storage is retained pending explicit settlement.')
        self.recovery = recovery


class _ClosedStartupRetention:
    """Original root ownership, without writer, execution or fresh host capability.

    Phases that could not be observed settled stay PENDING; ``settle`` retries close-only.
    """

    def __init__(self, canonical, metadata, host, accounting, *, accounting_close='NOT_ALLOCATED',
                 host_close=None, storage_close='CLOSED', close_storage=None):
        self.confirmation = canonical.confirmation
        self.accounting_close = accounting_close
        self.host_close = _host_state(host) if host_close is None else host_close
        self.storage_close = storage_close
        self._close_storage = close_storage
        self._canonical, self._metadata = canonical, metadata
        self._host, self._accounting = host, accounting
        self._request = canonical._request()
        # Only settled storage is attested; a pending digest stays unavailable and refuses purge.
        self._database_hash = _stable_digest(canonical) if storage_close == 'CLOSED' else None
        self._accounting_identity = (accounting.path.stat().st_dev,accounting.path.stat().st_ino) if accounting else None

    def close_accounting(self):
        """Bounded close-only retry on the original run; no lease, count reset or deletion."""
        if self._accounting is None:
            return self.accounting_close
        path = self._accounting.path
        if (path.is_symlink() or path.parent.is_symlink() or not path.is_file()
                or (path.stat().st_dev,path.stat().st_ino) != self._accounting_identity):
            raise FollowUpExecutionBoundaryError()
        self.accounting_close = _close_accounting(self._accounting, self.confirmation.bounds)
        return self.accounting_close

    async def settle(self):
        """Close-only retry of pending phases; never renews authority, accounting or retention.

        The retry is owned: observer cancellation is re-raised, with this recovery, only after
        every attempted phase has recorded its observed state.
        """
        async def retry():
            if self.host_close == 'PENDING' or self.storage_close == 'PENDING':
                host, _, storage = await _settle_owned(
                    self._host, None, self.confirmation.bounds,
                    self._close_storage if self.storage_close == 'PENDING' else None)
                self.host_close = host
                if self.storage_close == 'PENDING' and storage == 'CLOSED':
                    self.storage_close = 'CLOSED'
                    self._database_hash = _stable_digest(self._canonical)
            if self.accounting_close == 'PENDING':
                self.close_accounting()
            return {'host': self.host_close, 'accounting': self.accounting_close, 'storage': self.storage_close}
        phases, cancelled = await _owned_settlement(retry)
        if cancelled:
            cancellation = asyncio.CancelledError()
            cancellation.recovery = self
            raise cancellation from None
        return phases

    async def purge(self, *, now):
        """Consume the original ownership at expiry; never reopen a writer or source lease."""
        from ignis.infrastructure.follow_up_host_activation import IsolatedCanonicalSQLite
        from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage
        metadata = self._metadata
        bounds = self.confirmation.bounds
        # Persistent retention has no expiry; deletion needs separate explicit user authority.
        if bounds.retention_until is None:
            raise FollowUpExecutionBoundaryError()
        if (now < bounds.retention_until or metadata.active_run or not metadata.closed
                or self.storage_close != 'CLOSED' or self._database_hash is None
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
            if path.exists():
                metadata._validate(path,record)
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



def _close_accounting(accounting, bounds):
    """Durably end spending authority; CLOSED only after readback, rows are never deleted."""
    if accounting is None:
        return 'NOT_ALLOCATED'
    try:
        accounting.close(bounds)
        return 'CLOSED' if accounting.is_closed(bounds) else 'PENDING'
    except FollowUpExecutionBoundaryError:
        # The private store sanitizes SQLite failures; report pending closure, never success.
        return 'PENDING'


def _stable_digest(canonical):
    """Digest closed canonical bytes; an unreadable file is unavailable, never a masking error."""
    try:
        return sha256(canonical.path.read_bytes()).hexdigest()
    except OSError:
        return None


def _host_state(host):
    """CLOSED only when revocation is published and no guarded holder or task remains."""
    if host is None:
        return 'NOT_ALLOCATED'
    with host._lock:
        return 'CLOSED' if host._revoked and not host._tokens and not host._tasks else 'PENDING'


async def _settle_owned(host, accounting, bounds, close_storage):
    """Revoke first, then attempt each later phase independently of earlier failures.

    Storage closes only once revocation is published and quiescence observed: before publication an
    original lease can still be admitted, and an unsettled holder may still use it.
    """
    if host is not None:
        try:
            await host.revoke()
        except Exception:
            pass
    host_state = _host_state(host)
    try:
        closure = _close_accounting(accounting, bounds)
    except Exception:
        closure = 'PENDING'
    storage = 'NOT_ALLOCATED'
    if close_storage is not None:
        storage = 'PENDING'
        if host_state in ('CLOSED', 'NOT_ALLOCATED'):
            try:
                await close_storage()
                storage = 'CLOSED'
            except Exception:
                pass
    return host_state, closure, storage


async def _owned_settlement(cleanup):
    """Run cleanup to completion even under repeated cancellation; report any cancellation seen."""
    settlement = asyncio.ensure_future(cleanup())
    cancelled = False
    while not settlement.done():
        try:
            await asyncio.shield(settlement)
        except asyncio.CancelledError:
            cancelled = True
    return settlement.result(), cancelled


def _raise_retained(error, recovery, failure, cancelled):
    """Preserve the original failure; cancellation first seen during cleanup is re-raised after it."""
    if recovery is not None:
        if isinstance(error, Exception) and not cancelled:
            raise failure(recovery) from None
        if isinstance(error, Exception):
            cancellation = asyncio.CancelledError()
            cancellation.recovery = recovery
            raise cancellation from None
        error.recovery = recovery
    elif cancelled and isinstance(error, Exception):
        raise asyncio.CancelledError() from None
    raise error


class CanonicalAnalysisRetentionFailure(FollowUpExecutionBoundaryError):
    """Analysis failed; the original storage is retained pending explicit settlement."""

    def __init__(self, recovery):
        super().__init__('Canonical analysis failed; original storage is retained pending explicit settlement.')
        self.recovery = recovery


async def finish_canonical_parent_analysis(result, *, assessments, candidates, judged_by):
    """Finish explicit root judgments before disposing the original single-parent storage.

    Source revocation does not dispose canonical storage or renew the existing ANALYZE
    assignment. No judgment, candidate, child, or provider request is inferred here.
    """
    from ignis.application.use_cases.submit_evidence_qualifications import SubmitEvidenceQualificationsUseCase
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from ignis.application.use_cases.get_mission_claims import GetMissionClaimsUseCase
    from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
    from ignis.domain.research_work import _admission_reason

    host, repository, canonical = result['host'], result['repository'], result['canonical']
    executor = result['executor']
    if (executor._repo is not repository or executor._registry is not host.registry
            or getattr(repository, 'enrollment', None) is not canonical
            or canonical.confirmation != host.confirmation):
        raise FollowUpExecutionBoundaryError()
    canonical.check()
    store = executor._workspace_store
    metadata = canonical.generated_metadata
    try:
        await host.revoke()
        snapshot = await store.load_mission_evidence_snapshot(host.confirmation.selected_parent_id)
        research = await repository.load_research_work(snapshot.mission.id)
        work = next((row for row in research.work_items if str(row.work_id) == result['work_id']), None)
        assignment = next((row for row in research.assignments
            if work is not None and row.assignment_id == work.assignment_id), None)
        if (snapshot.mission.status != 'COMPLETED' or work is None or assignment is None
                or work.epoch != research.current_epoch
                or _admission_reason(assignment, work, host.clock()) is not None):
            raise FollowUpExecutionBoundaryError()
        outcomes = [ExecuteMissionUseCase._probe_outcome_payload(row) for row in snapshot.outcomes]
        qualification = await SubmitEvidenceQualificationsUseCase(repository, store).execute(
            result['mission_id'], compute_frame_fingerprint(snapshot.mission, snapshot.brief), assessments)
        claim_submission = None
        if candidates:
            current = await store.load_mission_evidence_snapshot(snapshot.mission.id)
            claim_submission = await SubmitMissionClaimsUseCase(repository, store).execute(
                result['mission_id'], frame_from_snapshot(current).frame_digest,
                candidates, created_by=judged_by)
        ledger = await GetMissionClaimsUseCase(repository, store).execute(result['mission_id'])
        analysis = await GetMissionAnalysisUseCase(repository, store).execute(result['mission_id'])
    except BaseException as error:
        async def close_storage():
            try:
                await repository.close()
            finally:
                metadata.close()
        async def cleanup():
            host_state, closure, storage = await _settle_owned(
                host, result['accounting'], host.confirmation.bounds, close_storage)
            return _ClosedStartupRetention(canonical, metadata, host, result['accounting'],
                accounting_close=closure, host_close=host_state, storage_close=storage,
                close_storage=close_storage)
        recovery, cancelled = await _owned_settlement(cleanup)
        _raise_retained(error, recovery, CanonicalAnalysisRetentionFailure, cancelled)
    closure = _close_accounting(result['accounting'], host.confirmation.bounds)
    await repository.close()
    metadata.close()
    recovery = _ClosedStartupRetention(canonical, metadata, host, result['accounting'],
        accounting_close=closure)
    return {'outcomes': outcomes, 'qualification': qualification, 'claim_submission': claim_submission,
        'claim_ledger': ledger, 'analysis': analysis, 'recovery': recovery, 'accounting_close': closure}



def _validate_instruction(record):
    """Keep this private pilot's exact supported source/window/budget contract."""
    required={'reference','credential_reference','queries','geo','timeframe','source','platform',
        'tier','revision','video_limit','search_calls','other_calls','run_minutes','retention'}
    if (type(record) is not dict or set(record)!=required
            or any(type(record[key]) is not str or not record[key].strip()
                   for key in ('reference','credential_reference'))
            or type(record['queries']) is not list or len(record['queries'])!=2
            or any(type(query) is not str or not query.strip() or len(query)>512 for query in record['queries'])
            or len(set(record['queries']))!=2
            or (record['geo'],record['timeframe'],record['source'],record['platform'],record['tier'],record['revision'])
                != ('GeoCode.VN','Timeframe.LAST_30D','youtube','youtube','official_api','unversioned')
            or record['retention']!=RETAIN_UNTIL_EXPLICIT_USER_DELETION
            or any(type(record[key]) is not int or record[key]!=value for key,value in
                (('video_limit',5),('search_calls',2),('other_calls',4),('run_minutes',15)))):
        raise ValueError('OWNER_SCOPE_CONFIRMATION_REQUIRED')



def confirmation_at_approved_invocation(record, *, mission_id, run_id, started_at=None):
    """Exact reviewed root receipt, not a test boolean or persisted auto-grant."""
    _validate_instruction(record)
    from ignis.infrastructure.follow_up_provider_bridge import RunBounds
    started = started_at or datetime.now(timezone.utc)
    bounds = RunBounds(run_id=UUID(str(run_id)), started_at=started,
        deadline=started+timedelta(minutes=record['run_minutes']),
        retention_until=None,
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
    if host.confirmation.bounds.retention_until is None:
        raise FollowUpExecutionBoundaryError()
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
        scope_digest=digest(instruction),retention_until=None,create=True)
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
            analysis_policy='evidence-gated-v1', retention_policy='caller-retained-until-explicit-user-deletion',
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
        owned_host, owned_accounting = locals().get('host'), locals().get('accounting')
        owned_enrollment = locals().get('enrollment')
        owned_repository = repository
        async def close_storage():
            try:
                await owned_repository.close()
                # Claim canonical closure only after the repository actually closed.
                prepared._closed = True
                if owned_enrollment is not None:
                    owned_enrollment.closed = True
            finally:
                metadata.close()
        async def cleanup():
            host_state, closure, storage = await _settle_owned(
                owned_host, owned_accounting, confirmation.bounds if owned_accounting is not None else None,
                close_storage)
            if owned_enrollment is None:
                return None
            return _ClosedStartupRetention(owned_enrollment, metadata, owned_host, owned_accounting,
                accounting_close=closure, host_close=host_state, storage_close=storage,
                close_storage=close_storage)
        recovery, cancelled = await _owned_settlement(cleanup)
        # Preserve cancellation semantics while still returning the original retained disposition.
        _raise_retained(error, recovery, StartupRetentionFailure, cancelled)
    finally:
        metadata.active_run = False
