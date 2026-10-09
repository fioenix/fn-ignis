"""Actual typed admission for T069 child-view fixtures; no result CRUD or live providers."""

from uuid import uuid4

from ignis.application.ports.research_work_port import (
    FollowUpAdmissionCommand, FollowUpWorkCommand,
)
from ignis.domain.follow_up_admission import (
    AssignmentBudget, OperationalGap, ParentBudget, SourceGrant, WorkAuthority,
)
from ignis.domain.mission_follow_up import FollowUpExecutionRequest, FollowUpScope, FollowUpWork
from tests.integration.test_follow_up_sqlite_admission import OfflineVerifier, register
from tests.integration.test_research_work_persistence import _api, _commit


async def admit_child(repository, parent):
    domain, port, _ = _api(repository)
    state = await repository.load_research_work(parent.mission.id)
    assignment = next(a for a in state.assignments if a.assignment_id == parent.assignment.assignment_id)
    original_work = next(w for w in state.work_items if w.work_id == parent.work.work_id)
    inputs = original_work.inputs
    assert inputs == parent.finding.inputs
    assert set(inputs.observation_ids) <= set(dict(state.observation_sources))
    assert set(inputs.finding_revisions) <= set(state.current_finding_revisions)
    if hasattr(repository, '_dsn'):
        from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
        verifier = AsyncVerifier()
    else:
        verifier = OfflineVerifier()
    repository.configure_follow_up_verifier(verifier)
    proposed = domain.ResearchWorkItem(work_id=uuid4(), assignment_id=assignment.assignment_id,
        mission_id=parent.mission.id, run_id=None, question='Inspect bounded child results', expertise='Collection',
        assignee_ref='t069-offline-owner', inputs=inputs, dependencies=(), epoch=assignment.epoch,
        state='ASSIGNED', version=1, ownership_fence='t069-child-fence')
    recorded = await _commit(repository, port, parent.mission, 'ASSIGN_WORK', proposed,
                            revision=state.revision, epoch=assignment.epoch)
    assert recorded.disposition == 'APPLIED'
    scope = FollowUpScope(queries=('retail stockout',), sources=frozenset({'google', 'youtube'}))
    gap = OperationalGap(gap_id=uuid4(), parent_work_id=parent.work.work_id, inputs=inputs,
                         question=original_work.question)
    root = ParentBudget(budget_id=uuid4(), mission_id=parent.mission.id,
        manifest_digest=inputs.manifest_digest, brief_digest=inputs.brief_digest,
        quota_unit='query', cost_unit='offline_unit', quota_ceiling=2, cost_ceiling=2,
        resources=(('queries', 2), ('youtube_search_calls', 2)), confirmation_ref='synthetic-owner-confirmation')
    binding = AssignmentBudget(binding_id=uuid4(), budget_id=root.budget_id,
        assignment_id=assignment.assignment_id, epoch=assignment.epoch, assignment_version=assignment.version,
        assignment_quota=2, quota_unit='query', cost_ceiling=2, confirmation_ref=root.confirmation_ref)
    work = FollowUpWork(work_id=proposed.work_id, parent_work_id=parent.work.work_id,
        assignment_id=assignment.assignment_id, gap_id=gap.gap_id, inputs=inputs,
        research_epoch=assignment.epoch, assignment_version=assignment.version, work_version=1,
        brief_revision_id=parent.evidence.brief.brief_revision_id, approved_scope=scope, requested_scope=scope,
        authority_deadline=assignment.authority.deadline)
    sources = tuple(SourceGrant(source=s, platform=s, tier='public_http', paid=False,
        plan_digest='a' * 64, connector_revision='offline-v1', capability_id='t069-synthetic-capability',
        capability_epoch=1) for s in ('google', 'youtube'))
    authority = WorkAuthority(work=work, budget_id=root.budget_id, binding_id=binding.binding_id,
        quota_unit='query', cost_unit='offline_unit', quota=2, cost=2, quota_ceiling=2, cost_ceiling=2,
        resources=root.resources, sources=sources, confirmation_ref=root.confirmation_ref)
    for fact in (gap, root, binding, authority):
        receipt = await register(repository, parent.mission.id, fact)
        assert receipt.disposition == 'APPLIED', receipt
    receipt = await repository.record_follow_up_work(FollowUpWorkCommand(work=work,
        expected_revision=(await repository.load_research_work(parent.mission.id)).revision,
        idempotency_key=uuid4().hex, host_authorized=True))
    assert receipt.disposition == 'APPLIED'
    receipt = await repository.admit_mission_follow_up(FollowUpAdmissionCommand(
        request=FollowUpExecutionRequest(mission_id=parent.mission.id, follow_up_work_id=work.work_id,
            expected_research_epoch=assignment.epoch, idempotency_key=uuid4().hex),
        selected_parent_id=parent.mission.id,
        expected_revision=(await repository.load_research_work(parent.mission.id)).revision,
        host_authorized=True))
    assert receipt.disposition == 'APPLIED', receipt
    child = await repository.get_mission(receipt.relationship.child_mission_id)
    assert child is not None and child.workspace_id == parent.mission.workspace_id
    return child
