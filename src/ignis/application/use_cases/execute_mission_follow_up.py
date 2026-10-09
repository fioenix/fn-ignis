"""Execute one recorded bounded child, without reopening its terminal parent."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from ignis.application.cancellation import await_settled
from ignis.application.ports.follow_up_execution_port import FollowUpExecutionPlan, FollowUpExecutionBoundaryError
from ignis.application.ports.research_work_port import FollowUpAdmissionCommand
from ignis.domain.follow_up_admission import CapabilityProof
from ignis.domain.mission_follow_up import FollowUpExecutionRequest, FollowUpRelationship
from ignis.domain.research_workspace import MissionTerminalStateError, MissionWriterConflictError
from ignis.domain.exceptions import RepositoryException
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.research_workspace import compute_frame_fingerprint


class FollowUpRefusal(FollowUpExecutionBoundaryError):
    def __init__(self, reason):
        super().__init__()
        self.reason = reason
        self.args = (reason,)


@dataclass(frozen=True, slots=True)
class FollowUpExecutionResponse:
    status: str
    reason_code: str | None = None
    relationship: FollowUpRelationship | None = None
    run_id: UUID | None = None
    channel_outcomes: tuple = ()

    def to_payload(self):
        link = self.relationship
        return {
            "status": self.status, "reason_code": self.reason_code,
            "child_mission_id": str(link.child_mission_id) if link else None,
            "reservation_id": str(link.reservation_id) if link else None,
            "parent_work_id": str(link.work.parent_work_id) if link else None,
            "gap_id": str(link.work.gap_id) if link else None,
            "assignment_id": str(link.work.assignment_id) if link else None,
            "follow_up_work_id": str(link.work.work_id) if link else None,
            "run_id": str(self.run_id) if self.run_id else None,
            "channel_outcomes": list(self.channel_outcomes),
        }


class ExecuteMissionFollowUpUseCase:
    def __init__(self, repository, mission_executor, *, selected_parent_id,
                 host_authorized=False, clock=None, session_initializer=None):
        self._repo = repository
        self._executor = mission_executor
        self._selected = UUID(str(selected_parent_id))
        self._host_authorized = host_authorized is True
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        # Explicit host DI for offline collectors; production has no acquisition bridge here.
        self._initializer = session_initializer

    @asynccontextmanager
    async def _execution_guard(self, provider, authority, plan):
        async with AsyncExitStack() as stack:
            try:
                lease = await stack.enter_async_context(provider(authority, plan))
                guard = getattr(lease, "async_guard", None)
                if guard is None:
                    raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
                await stack.enter_async_context(guard())
            except Exception:
                # Only acquisition failures are refusals; cancellation and execution stay outside.
                raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED") from None
            yield lease

    @staticmethod
    def _diagnostic(context):
        authority = context.authority
        reason = context.reason_code
        if authority is None:
            return reason
        work = authority.work
        if not set(work.requested_scope.queries) <= set(work.approved_scope.queries):
            return "SCOPE_MISMATCH"
        if not work.requested_scope.sources <= work.approved_scope.sources:
            return "SOURCE_MISMATCH"
        if reason == "STALE_INPUT_FRAME" and context.canonical.manifest and context.canonical.brief:
            if (work.inputs.manifest_digest == context.canonical.manifest.manifest_digest
                    and work.inputs.brief_digest == compute_frame_fingerprint(
                        context.canonical.mission, context.canonical.brief)):
                try:
                    if frame_from_snapshot(context.canonical).frame_digest != work.inputs.frame_digest:
                        return "INPUT_REVISION_MISMATCH"
                except ValueError:
                    pass
        return reason

    async def _plan(self, context):
        authority = context.authority
        mission, brief, manifest = context.child, context.brief, context.manifest
        registry = self._executor._registry
        initial = self._executor._collection_plan_for_brief(mission, manifest, {}, brief)
        queries = tuple(self._executor._collection_queries(initial))
        if queries != authority.work.requested_scope.queries:
            raise FollowUpRefusal("SCOPE_MISMATCH")
        requirements = registry._describe_execution_requirements(
            target_platforms=mission.platforms, sources=authority.sources, keywords=list(queries))
        if requirements.get("unavailable_resources") or set(requirements["resources"]) != authority.work.requested_scope.sources:
            raise FollowUpRefusal("SOURCE_MISMATCH")
        costs = dict(requirements["quota_costs"])
        costs["queries"] = len(queries)
        if any(amount > dict(authority.resources).get(unit, -1) for unit, amount in costs.items()):
            raise FollowUpRefusal("QUOTA_EXHAUSTED")
        connectors = []
        for source in authority.sources:
            plugin = registry.get_plugin_by_id(source.source)
            metadata = requirements["surface_requirements"][source.source]
            sampling = metadata["sampling"]
            if (plugin.platform.value != source.platform
                    or metadata["authority_tier"] != source.tier
                    or metadata["connector_revision"] != source.connector_revision
                    or metadata.get("requires_paid_quota", False) != source.paid):
                raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
            connectors.append((source.source, source.platform, source.tier, source.connector_revision,
                               metadata["connector_path"], sampling["limit"], sampling["ordering"],
                               metadata["requires_paid_quota"]))
        plan = FollowUpExecutionPlan(queries, tuple(sorted(connectors)), tuple(sorted(costs.items())),
                                     str(mission.geo_code), str(mission.timeframe))
        requirements["quota_costs"] = costs
        return plan, requirements

    def _current(self, lease, authority, plan):
        proof = lease.proof
        now = self._clock()
        if authority.work.authority_deadline <= now:
            raise FollowUpRefusal("AUTHORITY_EXPIRED")
        if type(proof) is not CapabilityProof or proof.envelope_digest != authority.digest:
            raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
        if proof.stop_reached:
            raise FollowUpRefusal("STOP_CONDITION_REACHED")
        if proof.cancel_requested:
            raise FollowUpRefusal("CANCEL_REQUESTED")
        if (not proof.allowed or not proof.checked_at <= now < proof.fresh_until
                or proof.sources != authority.sources or lease.is_current() is not True
                or proof.quota_unit != authority.quota_unit or proof.cost_unit != authority.cost_unit
                or proof.quota_required > authority.quota or proof.cost_required > authority.cost
                or set(dict(proof.resources)) != set(dict(authority.resources))
                or any(v > dict(authority.resources).get(k, -1) for k, v in proof.resources)
                or any(v > dict(proof.resources).get(k, -1) for k, v in plan.resources)):
            raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")

    async def _recover(self, context):
        receipt = context.receipt
        if receipt is None:
            return None
        link = receipt.relationship
        journals = await self._repo.list_run_journals(link.child_mission_id)
        claim = await self._repo.get_mission_writer_claim(link.child_mission_id)
        child = await self._repo.get_mission(link.child_mission_id)
        if child is None:
            raise FollowUpRefusal("STORAGE_FAILURE")
        if not journals and claim is None and child.status == "PENDING":
            return None
        if child.status == "COMPLETED":
            return FollowUpExecutionResponse("COMPLETED", relationship=link,
                                             run_id=journals[-1].run_id if journals else None)
        if claim is not None:
            # A persisted claim is not current execution/activity evidence. Only admission is known.
            return FollowUpExecutionResponse("ADMITTED", "EXECUTION_STATUS_UNKNOWN", link)
        return FollowUpExecutionResponse("RECONCILIATION_REQUIRED", "UNRESOLVED_EXECUTION", link,
                                         journals[-1].run_id if journals else None)

    async def execute(self, mission_id, follow_up_work_id, expected_research_epoch, idempotency_key):
        try:
            request = FollowUpExecutionRequest(mission_id=UUID(str(mission_id)),
                                               follow_up_work_id=UUID(str(follow_up_work_id)),
                                               expected_research_epoch=expected_research_epoch,
                                               idempotency_key=idempotency_key)
        except (ValueError, TypeError):
            reason = "STALE_EPOCH" if type(expected_research_epoch) is int and expected_research_epoch < 1 else "INVALID_INPUT"
            return FollowUpExecutionResponse("REFUSED", reason)
        if request.mission_id != self._selected:
            return FollowUpExecutionResponse("REFUSED", "SCOPE_MISMATCH")
        if not self._host_authorized:
            return FollowUpExecutionResponse("REFUSED", "UNAUTHORIZED_HOST")
        caller = asyncio.current_task()
        if caller.cancelling():
            raise asyncio.CancelledError
        try:
            context = await self._repo._follow_up_execution_context(
                request.mission_id, request.follow_up_work_id, request=request)
            if context.retry_reason:
                raise FollowUpRefusal(context.retry_reason)
            if context.receipt is not None:
                if request.expected_research_epoch != context.receipt.relationship.work.research_epoch:
                    raise FollowUpRefusal("STALE_EPOCH")
                recovery = await self._repo.admit_mission_follow_up(FollowUpAdmissionCommand(
                    request=request, selected_parent_id=self._selected, host_authorized=True,
                    expected_revision=context.retry_revision if context.retry_revision is not None else context.research.revision))
                if recovery.disposition == "REFUSED":
                    raise FollowUpRefusal(recovery.reason_code)
            recovered = await self._recover(context)
            if recovered:
                return recovered
            if expected_research_epoch != context.research.current_epoch:
                raise FollowUpRefusal("STALE_EPOCH")
            if self._diagnostic(context):
                raise FollowUpRefusal(self._diagnostic(context))
            authority = context.authority
            plan, requirements = await self._plan(context)
            if any(source.plan_digest != plan.digest for source in authority.sources):
                raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
            verifier = getattr(self._repo, "_follow_up_verifier", None)
            provider = getattr(verifier, "hold_execution", None)
            if provider is None:
                raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
            if caller.cancelling():
                raise asyncio.CancelledError
            async with self._execution_guard(provider, authority, plan) as lease:
                if caller.cancelling():
                    raise asyncio.CancelledError
                self._current(lease, authority, plan)
                command = FollowUpAdmissionCommand(
                    request=request, selected_parent_id=self._selected,
                    expected_revision=context.research.revision, host_authorized=True,
                )
                receipt = await self._repo.admit_mission_follow_up(command)
                if receipt.disposition == "REFUSED":
                    raise FollowUpRefusal(receipt.reason_code)
                context = await self._repo._follow_up_execution_context(request.mission_id, request.follow_up_work_id)
                recovered = await self._recover(context)
                if recovered:
                    return recovered
                self._current(lease, authority, plan)
                link = receipt.relationship
                child = await self._repo.get_mission(link.child_mission_id)
                manifest = await self._executor._workspace_store.get_mission_manifest(child.id)
                started = False

                async def before_journal(mission, run_id):
                    current = await self._repo._follow_up_execution_context(request.mission_id, request.follow_up_work_id)
                    if current.receipt is None or current.receipt.relationship != link:
                        raise FollowUpRefusal("STORAGE_FAILURE")
                    if await self._repo.list_run_journals(child.id):
                        raise FollowUpRefusal("UNRESOLVED_EXECUTION")
                    if self._diagnostic(current):
                        raise FollowUpRefusal(self._diagnostic(current))
                    if current.authority != authority:
                        raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
                    original_brief = await self._executor._workspace_store.get_brief_revision_for_mission(child.id)
                    if (original_brief is None or manifest.manifest_digest != link.child_manifest_digest
                            or compute_frame_fingerprint(mission, original_brief) != link.child_brief_digest
                            or tuple(mission.keywords) != authority.work.requested_scope.queries
                            or {p.value for p in mission.platforms} != {s.platform for s in authority.sources}):
                        raise FollowUpRefusal("SCOPE_MISMATCH")
                    actual_plan, _ = await self._plan(context.__class__(
                        authority, current.canonical, current.research, current.receipt,
                        current.reason_code, mission, original_brief, manifest))
                    if actual_plan != plan:
                        raise FollowUpRefusal("SESSION_AUTHORITY_REQUIRED")
                    self._current(lease, authority, plan)

                async def scope_guard(journal):
                    nonlocal started
                    started = True
                    self._current(lease, authority, plan)
                    if self._initializer is not None:
                        await self._initializer(authority.work.requested_scope.sources)
                    self._current(lease, authority, plan)

                async def search(**kwargs):
                    self._current(lease, authority, plan)
                    if tuple(kwargs["keywords"]) != plan.queries:
                        raise FollowUpRefusal("SCOPE_MISMATCH")
                    return await self._executor._registry._search_with_outcomes_guarded(
                        **kwargs, boundary_guard=lambda: self._current(lease, authority, plan), approved_plan=plan)

                try:
                    result = await self._executor._execute_authorized(
                        child, manifest, requirements, before_journal=before_journal,
                        scope_guard=scope_guard, search_provider=search,
                        expiry_guard=lambda: self._current(lease, authority, plan),
                    )
                except (MissionWriterConflictError, MissionTerminalStateError):
                    current = await self._repo._follow_up_execution_context(request.mission_id, request.follow_up_work_id)
                    return await self._recover(current) or FollowUpExecutionResponse(
                        "RECONCILIATION_REQUIRED", "UNRESOLVED_EXECUTION", link)
                except BaseException:
                    if started or await self._repo.list_run_journals(child.id):
                        await await_settled(self._repo._follow_up_execution_context(
                            request.mission_id, request.follow_up_work_id, unresolved=True))
                    raise
                return FollowUpExecutionResponse(
                    result["terminal_state"], relationship=link,
                    run_id=UUID(result["run"]["run_id"]),
                    channel_outcomes=tuple(result.get("channel_outcomes", ())),
                )
        except FollowUpExecutionBoundaryError as error:
            return FollowUpExecutionResponse("REFUSED", error.reason)
        except RepositoryException:
            return FollowUpExecutionResponse("REFUSED", "STORAGE_FAILURE")
