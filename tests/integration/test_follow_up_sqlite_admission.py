"""T072 physical SQLite controls; verification providers are explicitly offline doubles."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
import sqlite3
from uuid import uuid4

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from tests.unit.test_mission_claims import _eligible_mission


class OfflineVerifier:
    """No actual credential/session proof; deterministic synthetic capability authority."""

    def __init__(self):
        self.lock = threading.RLock()
        self.generation = 1
        self.operational_generation = 1
        self.allowed = True
        self.confirmed = True
        self.calls = 0
        self.revoke_on_check = False

    def verify_owner(self, reference, digest):
        return self.confirmed and reference == "synthetic-owner-confirmation"

    @asynccontextmanager
    async def hold_current(self, request):
        from ignis.domain.follow_up_admission import CapabilityProof

        self.calls += 1
        verifier = self
        generation = self.generation
        operational = self.operational_generation

        class Lease:
            proof = CapabilityProof(
                envelope_digest=request.digest,
                process_id="offline-process",
                policy_generation=generation,
                operational_generation=operational,
                checked_at=datetime.now(timezone.utc),
                fresh_until=datetime.now(timezone.utc) + timedelta(minutes=2),
                sources=request.sources,
                quota_unit=request.quota_unit,
                cost_unit=request.cost_unit,
                quota_required=request.quota,
                cost_required=request.cost,
                resources=request.resources,
                allowed=verifier.allowed,
                stop_reached=False,
                cancel_requested=False,
            )

            @contextmanager
            def guard(self):
                with verifier.lock:
                    yield self

            def is_current(self):
                if verifier.revoke_on_check:
                    verifier.generation += 1
                return verifier.generation == generation and verifier.operational_generation == operational

        yield Lease()


async def register(repository, mission_id, record, key=None):
    from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand

    return await repository.record_follow_up_fact(
        FollowUpFactCommand(
            mission_id=mission_id,
            record=record,
            expected_revision=(await repository.load_research_work(mission_id)).revision,
            idempotency_key=key or uuid4().hex,
            host_authorized=True,
        )
    )


async def ready(tmp_path, *, budget=4, resource_budget=20, source_id="youtube", source_platform="youtube"):
    from ignis.domain.follow_up_admission import (
        OperationalGap,
        ParentBudget,
        AssignmentBudget,
        SourceGrant,
        WorkAuthority,
    )
    from ignis.domain.research_work import (
        ResearchAssignment,
        ResearchAuthority,
        ResearchInputBindings,
        ResearchWorkItem,
    )
    from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope
    from ignis.application.ports.research_work_port import (
        ResearchWorkCommitCommand,
        ResearchAssignmentAdmission,
        FollowUpWorkCommand,
    )
    from ignis.domain.research_workspace import compute_frame_fingerprint

    repository = SqliteTrendRepository(str(tmp_path / "admission.db"))
    await repository._ensure_schema()
    from unittest.mock import patch
    from tests.unit.test_mission_claims import _manifest

    original_outcomes = repository.record_probe_outcomes

    async def record_outcomes(run_id, outcomes):
        if source_id != "youtube":
            outcomes = [
                *outcomes,
                replace(
                    outcomes[0],
                    connector_surface=source_id,
                    platform="tiktok",
                    status="EMPTY_NO_DATA",
                    note="Synthetic offline empty query",
                    outcome_id=uuid4(),
                    signals_collected=0,
                ),
            ]
        return await original_outcomes(run_id, outcomes)

    with (
        patch(
            "tests.unit.test_mission_claims._manifest",
            return_value=replace(
                _manifest(),
                required_channels=tuple(sorted({"google", "youtube", source_id})),
                quota_budget={"queries": 20},
            ),
        ),
        patch.object(repository, "record_probe_outcomes", record_outcomes),
    ):
        _, store, mission, _, frame = await _eligible_mission(tmp_path, repository=repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    inputs = ResearchInputBindings(
        mission_id=mission.id,
        manifest_digest=evidence.manifest.manifest_digest,
        brief_digest=compute_frame_fingerprint(mission, evidence.brief),
        frame_digest=frame.frame_digest,
        observation_ids=tuple(sorted((s.observation_id for s in evidence.signals), key=str)),
        finding_revisions=(),
    )
    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    assignment = ResearchAssignment(
        assignment_id=uuid4(),
        mission_id=mission.id,
        host_task_ref="offline",
        epoch=1,
        authority=ResearchAuthority(
            actions=frozenset({"ANALYZE", "FOLLOW_UP"}),
            sources=frozenset({source_id}),
            deadline=deadline,
            quota_ceiling=budget,
        ),
        capability="SEQUENTIAL",
        state="ASSIGNED",
        version=1,
    )
    revision = (await repository.load_research_work(mission.id)).revision

    async def commit(operation, payload):
        nonlocal revision
        r = await repository.commit_research_work(
            ResearchWorkCommitCommand(
                mission_id=mission.id,
                operation=operation,
                payload=payload,
                expected_revision=revision,
                expected_epoch=1,
                idempotency_key=uuid4().hex,
                host_authorized=True,
            )
        )
        assert r.disposition == "APPLIED", r
        revision = r.revision

    await commit(
        "ASSIGN_RESEARCH",
        ResearchAssignmentAdmission(
            assignment=assignment,
            expected_manifest_digest=inputs.manifest_digest,
            expected_brief_revision_id=evidence.brief.brief_revision_id,
        ),
    )
    parent = ResearchWorkItem(
        work_id=uuid4(),
        assignment_id=assignment.assignment_id,
        mission_id=mission.id,
        run_id=None,
        question="Bounded operational gap",
        expertise="Synthesis",
        assignee_ref="offline",
        inputs=inputs,
        dependencies=(),
        epoch=1,
        state="ASSIGNED",
        version=1,
        ownership_fence="offline",
    )
    await commit("ASSIGN_WORK", parent)
    child = replace(parent, work_id=uuid4())
    await commit("ASSIGN_WORK", child)
    mission.status = "COMPLETED"
    await repository.update_mission(mission)
    verifier = OfflineVerifier()
    repository.configure_follow_up_verifier(verifier)
    gap = OperationalGap(gap_id=uuid4(), parent_work_id=parent.work_id, inputs=inputs, question=parent.question)
    root = ParentBudget(
        budget_id=uuid4(),
        mission_id=mission.id,
        manifest_digest=inputs.manifest_digest,
        brief_digest=inputs.brief_digest,
        quota_unit="query",
        cost_unit="offline_unit",
        quota_ceiling=budget,
        cost_ceiling=budget,
        resources=(("queries", resource_budget),),
        confirmation_ref="synthetic-owner-confirmation",
    )
    binding = AssignmentBudget(
        binding_id=uuid4(),
        budget_id=root.budget_id,
        assignment_id=assignment.assignment_id,
        epoch=1,
        assignment_version=1,
        assignment_quota=budget,
        quota_unit=root.quota_unit,
        cost_ceiling=budget,
        confirmation_ref=root.confirmation_ref,
    )
    scope = FollowUpScope(queries=("retail stockout", *evidence.brief.falsifiers), sources=frozenset({source_id}))
    follow = FollowUpWork(
        work_id=child.work_id,
        parent_work_id=parent.work_id,
        assignment_id=assignment.assignment_id,
        gap_id=gap.gap_id,
        inputs=inputs,
        research_epoch=1,
        assignment_version=1,
        work_version=1,
        brief_revision_id=evidence.brief.brief_revision_id,
        approved_scope=scope,
        requested_scope=scope,
        authority_deadline=deadline,
    )
    source = SourceGrant(
        source=source_id,
        platform=source_platform,
        tier="public_http",
        paid=False,
        plan_digest="a" * 64,
        connector_revision="offline-v1",
        capability_id="offline-public",
        capability_epoch=1,
    )
    authority = WorkAuthority(
        work=follow,
        budget_id=root.budget_id,
        binding_id=binding.binding_id,
        quota_unit=root.quota_unit,
        cost_unit=root.cost_unit,
        quota=2,
        cost=2,
        quota_ceiling=budget,
        cost_ceiling=budget,
        resources=(("queries", 2),),
        sources=(source,),
        confirmation_ref=root.confirmation_ref,
    )
    for record in (gap, root, binding, authority):
        await register(repository, mission.id, record)
    revision = (await repository.load_research_work(mission.id)).revision
    receipt = await repository.record_follow_up_work(
        FollowUpWorkCommand(work=follow, expected_revision=revision, idempotency_key="record", host_authorized=True)
    )
    assert receipt.disposition == "APPLIED"
    return repository, mission, follow, authority, verifier


def command(mission, follow, revision, key="admit"):
    from ignis.domain.mission_follow_up import FollowUpExecutionRequest
    from ignis.application.ports.research_work_port import FollowUpAdmissionCommand

    return FollowUpAdmissionCommand(
        request=FollowUpExecutionRequest(
            mission_id=mission.id,
            follow_up_work_id=follow.work_id,
            expected_research_epoch=follow.research_epoch,
            idempotency_key=key,
        ),
        selected_parent_id=mission.id,
        expected_revision=revision,
        host_authorized=True,
    )


@pytest.mark.asyncio
async def test_real_race_reopen_original_receipt_and_parent_isolation(tmp_path):
    repository, mission, follow, _, verifier = await ready(tmp_path)
    before = await repository.load_mission_evidence_snapshot(mission.id)
    cmd = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    contender = SqliteTrendRepository(repository._db_path)
    contender._initialized = True
    contender.configure_follow_up_verifier(verifier)
    receipts = await asyncio.gather(repository.admit_mission_follow_up(cmd), contender.admit_mission_follow_up(cmd))
    assert receipts[0] == receipts[1] and receipts[0].disposition == "APPLIED"
    snapshot = await repository.load_mission_follow_ups(mission.id)
    assert len(snapshot.relationships) == len(snapshot.reservations) == 1
    assert (await repository.get_mission(mission.id)).status == "COMPLETED"
    after = await repository.load_mission_evidence_snapshot(mission.id)
    assert after.signals == before.signals and after.claims == before.claims
    connection = repository._get_connection()
    connection.execute("UPDATE mission_follow_up_reservations SET state='UNRESOLVED',measured_quota=1,version=2")
    connection.commit()
    connection.close()
    contender.configure_follow_up_verifier(None)
    assert await contender.admit_mission_follow_up(cmd) == receipts[0]
    assert (await contender.load_mission_follow_ups(mission.id)).reservations[0].state == "UNRESOLVED"
    conflict = await contender.admit_mission_follow_up(replace(cmd, expected_revision=cmd.expected_revision + 1))
    assert conflict.reason_code == "IDEMPOTENCY_CONFLICT"
    await contender.close()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control,reason",
    [
        ("missing", "SESSION_AUTHORITY_REQUIRED"),
        ("false", "SESSION_AUTHORITY_REQUIRED"),
        ("revoked", "SESSION_AUTHORITY_REQUIRED"),
        ("host", "UNAUTHORIZED_HOST"),
        ("epoch", "STALE_EPOCH"),
        ("revision", "STALE_REVISION"),
    ],
)
async def test_current_proof_and_binding_refusal_before_child(tmp_path, control, reason):
    repository, mission, follow, _, verifier = await ready(tmp_path)
    cmd = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    if control == "missing":
        repository.configure_follow_up_verifier(None)
    if control == "false":
        verifier.allowed = False
    if control == "revoked":
        verifier.revoke_on_check = True
    if control == "host":
        cmd = replace(cmd, host_authorized=False)
    if control == "epoch":
        cmd = replace(cmd, request=replace(cmd.request, expected_research_epoch=2))
    if control == "revision":
        cmd = replace(cmd, expected_revision=0)
    result = await repository.admit_mission_follow_up(cmd)
    assert result.disposition == "REFUSED" and result.reason_code == reason
    snapshot = await repository.load_mission_follow_ups(mission.id)
    assert snapshot.relationships == snapshot.reservations == ()
    await repository.close()


@pytest.mark.asyncio
async def test_late_failure_rolls_back_child_and_reservation(tmp_path):
    repository, mission, follow, _, _ = await ready(tmp_path)
    connection = repository._get_connection()
    initial = connection.execute("SELECT count(*) FROM research_missions").fetchone()[0]
    connection.execute(
        "CREATE TRIGGER t072_fault BEFORE INSERT ON mission_follow_up_commands WHEN NEW.operation='ADMIT' BEGIN SELECT RAISE(ABORT,'offline fault'); END"
    )
    connection.commit()
    connection.close()
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert result.reason_code == "STORAGE_FAILURE"
    connection = repository._get_connection()
    assert connection.execute("SELECT count(*) FROM research_missions").fetchone()[0] == initial
    assert connection.execute("SELECT count(*) FROM mission_follow_ups").fetchone()[0] == 0
    connection.close()
    await repository.close()


async def sibling(repository, mission, follow, authority, *, new_epoch=False, quota_ceiling=None):
    from ignis.domain.follow_up_admission import AssignmentBudget
    from ignis.domain.research_work import EndResearchPayload
    from ignis.application.ports.research_work_port import (
        ResearchWorkCommitCommand,
        ResearchAssignmentAdmission,
        FollowUpWorkCommand,
    )

    state = await repository.load_research_work(mission.id)
    assignment = next(a for a in state.assignments if a.assignment_id == follow.assignment_id)

    async def commit(operation, payload, epoch):
        revision = (await repository.load_research_work(mission.id)).revision
        receipt = await repository.commit_research_work(
            ResearchWorkCommitCommand(
                mission_id=mission.id,
                operation=operation,
                payload=payload,
                expected_revision=revision,
                expected_epoch=epoch,
                idempotency_key=uuid4().hex,
                host_authorized=True,
            )
        )
        assert receipt.disposition == "APPLIED", receipt
        return receipt

    binding_id = authority.binding_id
    if new_epoch:
        await commit(
            "END_RESEARCH",
            EndResearchPayload(
                assignment_id=assignment.assignment_id,
                expected_version=assignment.version,
                disposition="COMPLETED",
                reason="Synthetic epoch boundary",
            ),
            assignment.epoch,
        )
        assignment = replace(
            assignment,
            assignment_id=uuid4(),
            epoch=assignment.epoch + 1,
            state="ASSIGNED",
            version=1,
            authority=replace(
                assignment.authority,
                quota_ceiling=quota_ceiling if quota_ceiling is not None else assignment.authority.quota_ceiling,
            ),
        )
        await commit(
            "ASSIGN_RESEARCH",
            ResearchAssignmentAdmission(
                assignment=assignment,
                expected_manifest_digest=follow.inputs.manifest_digest,
                expected_brief_revision_id=follow.brief_revision_id,
            ),
            assignment.epoch,
        )
        binding = AssignmentBudget(
            binding_id=uuid4(),
            budget_id=authority.budget_id,
            assignment_id=assignment.assignment_id,
            epoch=assignment.epoch,
            assignment_version=assignment.version,
            assignment_quota=assignment.authority.quota_ceiling,
            quota_unit=authority.quota_unit,
            cost_ceiling=authority.cost_ceiling,
            confirmation_ref=authority.confirmation_ref,
        )
        await register(repository, mission.id, binding)
        binding_id = binding.binding_id
    source_work = next(w for w in state.work_items if w.work_id == follow.work_id)
    source_work = replace(
        source_work,
        work_id=uuid4(),
        assignment_id=assignment.assignment_id,
        epoch=assignment.epoch,
        state="ASSIGNED",
        version=1,
    )
    await commit("ASSIGN_WORK", source_work, assignment.epoch)
    following = replace(
        follow,
        work_id=source_work.work_id,
        assignment_id=assignment.assignment_id,
        research_epoch=assignment.epoch,
        assignment_version=assignment.version,
        work_version=1,
    )
    grant = replace(
        authority,
        work=following,
        binding_id=binding_id,
        quota_ceiling=min(authority.quota_ceiling, assignment.authority.quota_ceiling),
    )
    await register(repository, mission.id, grant)
    revision = (await repository.load_research_work(mission.id)).revision
    receipt = await repository.record_follow_up_work(
        FollowUpWorkCommand(
            work=following, expected_revision=revision, idempotency_key=uuid4().hex, host_authorized=True
        )
    )
    assert receipt.disposition == "APPLIED"
    return following, grant


@pytest.mark.asyncio
async def test_all_epoch_unknown_and_partial_allocations_cannot_reset(tmp_path):
    repository, mission, follow, authority, _ = await ready(tmp_path)
    first = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert first.disposition == "APPLIED"
    connection = repository._get_connection()
    connection.execute(
        "UPDATE mission_follow_up_reservations SET state='UNRESOLVED',measured_quota=1,measured_cost=1,version=2"
    )
    connection.commit()
    connection.close()
    following, grant = await sibling(repository, mission, follow, authority, new_epoch=True)
    second = await repository.admit_mission_follow_up(
        command(mission, following, (await repository.load_research_work(mission.id)).revision, key="second")
    )
    assert second.disposition == "APPLIED"
    third, _ = await sibling(repository, mission, following, grant)
    result = await repository.admit_mission_follow_up(
        command(mission, third, (await repository.load_research_work(mission.id)).revision, key="third")
    )
    assert result.reason_code == "QUOTA_EXHAUSTED"
    snapshot = await repository.load_mission_follow_ups(mission.id)
    assert len(snapshot.relationships) == 2
    assert sum(r.encumbered[0] for r in snapshot.reservations) == 4
    assert {r.relationship.work.research_epoch for r in snapshot.reservations} == {1, 2}
    await repository.close()


@pytest.mark.asyncio
async def test_resource_allocations_survive_scalar_settlement(tmp_path):
    repository, mission, follow, authority, _ = await ready(tmp_path, budget=4, resource_budget=2)
    first = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert first.disposition == "APPLIED"
    connection = repository._get_connection()
    connection.execute(
        "UPDATE mission_follow_up_reservations SET state='SETTLED',measured_quota=0,measured_cost=0,measurement_receipt_id=?,version=2",
        (str(uuid4()),),
    )
    connection.commit()
    connection.close()
    following, _ = await sibling(repository, mission, follow, authority)
    result = await repository.admit_mission_follow_up(
        command(mission, following, (await repository.load_research_work(mission.id)).revision, key="resource")
    )
    assert result.reason_code == "QUOTA_EXHAUSTED"
    connection = repository._get_connection()
    assert connection.execute("SELECT sum(allocated) FROM mission_follow_up_reservation_resources").fetchone()[0] == 2
    assert connection.execute("SELECT count(*) FROM mission_follow_ups").fetchone()[0] == 1
    connection.close()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control", ["unit", "owner", "unknown_gap", "changed_gap_input", "root_expansion", "assignment_interpretation"]
)
async def test_registration_cannot_fabricate_authority_or_gap(tmp_path, control):
    from ignis.domain.follow_up_admission import OperationalGap

    repository, mission, follow, authority, verifier = await ready(tmp_path)
    if control == "unit":
        candidate = replace(authority, quota_unit="unrelated_unit")
    elif control == "owner":
        verifier.confirmed = False
        candidate = replace(authority, confirmation_ref="synthetic-owner-confirmation")
    elif control == "unknown_gap":
        candidate = replace(authority, work=replace(follow, gap_id=uuid4()))
    elif control == "changed_gap_input":
        candidate = OperationalGap(
            gap_id=uuid4(),
            parent_work_id=follow.parent_work_id,
            inputs=replace(follow.inputs, frame_digest="b" * 64),
            question="Bounded operational gap",
        )
    elif control == "root_expansion":
        from ignis.infrastructure.persistence.sqlite_follow_up_admission import decode

        connection = repository._get_connection()
        candidate = replace(
            decode(connection.execute("SELECT payload FROM mission_follow_up_parent_budgets").fetchone()[0]),
            budget_id=uuid4(),
            quota_ceiling=99,
        )
        connection.close()
    else:
        from ignis.infrastructure.persistence.sqlite_follow_up_admission import decode

        connection = repository._get_connection()
        candidate = replace(
            decode(connection.execute("SELECT payload FROM mission_follow_up_assignment_budgets").fetchone()[0]),
            binding_id=uuid4(),
            assignment_quota=99,
        )
        connection.close()
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        await register(repository, mission.id, candidate)
    snapshot = await repository.load_mission_follow_ups(mission.id)
    assert snapshot.relationships == snapshot.reservations == ()
    await repository.close()


@pytest.mark.asyncio
async def test_no_legacy_activity_or_work_state_change_on_admission(tmp_path):
    repository, mission, follow, _, _ = await ready(tmp_path)
    before = await repository.load_research_work(mission.id)
    admitted = await repository.admit_mission_follow_up(command(mission, follow, before.revision))
    after = await repository.load_research_work(mission.id)
    assert admitted.disposition == "APPLIED" and after.revision == before.revision + 1
    assert after.work_items == before.work_items
    connection = repository._get_connection()
    assert (
        connection.execute(
            "SELECT count(*) FROM research_activity_receipts WHERE work_id=?", (str(follow.work_id),)
        ).fetchone()[0]
        == 0
    )
    connection.close()
    assert after.events == before.events
    await repository.close()


@pytest.mark.asyncio
async def test_expiring_proof_rolls_back_before_commit(tmp_path):
    import time

    repository, mission, follow, _, verifier = await ready(tmp_path)
    original = verifier.hold_current

    @asynccontextmanager
    async def expiring(request):
        async with original(request) as lease:
            lease.proof = replace(lease.proof, fresh_until=datetime.now(timezone.utc) + timedelta(milliseconds=40))
            yield lease

    verifier.hold_current = expiring
    write = repository._write_brief_revision_row

    def delayed(cursor, brief):
        time.sleep(0.08)
        return write(cursor, brief)

    repository._write_brief_revision_row = delayed
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert (await repository.load_mission_follow_ups(mission.id)).relationships == ()
    await repository.close()


@pytest.mark.asyncio
async def test_new_retry_key_is_durably_bound_without_verifier(tmp_path):
    repository, mission, follow, _, _ = await ready(tmp_path)
    cmd = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    original = await repository.admit_mission_follow_up(cmd)
    repository.configure_follow_up_verifier(None)
    alias = replace(cmd, request=replace(cmd.request, idempotency_key="alias"))
    recovered = await repository.admit_mission_follow_up(alias)
    assert recovered.disposition == "EXISTING" and recovered.relationship == original.relationship
    assert await repository.admit_mission_follow_up(alias) == recovered
    assert (
        await repository.admit_mission_follow_up(replace(alias, expected_revision=0))
    ).reason_code == "IDEMPOTENCY_CONFLICT"
    connection = repository._get_connection()
    assert (
        connection.execute("SELECT count(*) FROM mission_follow_up_commands WHERE operation='ADMIT'").fetchone()[0] == 2
    )
    connection.close()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "control,reason",
    [
        ("stop", "STOP_CONDITION_REACHED"),
        ("cancel", "CANCEL_REQUESTED"),
        ("tier", "SESSION_AUTHORITY_REQUIRED"),
        ("capability", "SESSION_AUTHORITY_REQUIRED"),
        ("platform", "SESSION_AUTHORITY_REQUIRED"),
    ],
)
async def test_verified_current_operational_stop_and_source_generation(tmp_path, control, reason):
    repository, mission, follow, _, verifier = await ready(tmp_path)
    original = verifier.hold_current

    @asynccontextmanager
    async def controlled(request):
        async with original(request) as lease:
            if control == "stop":
                lease.proof = replace(lease.proof, stop_reached=True)
            elif control == "cancel":
                lease.proof = replace(lease.proof, cancel_requested=True)
            elif control == "tier":
                lease.proof = replace(lease.proof, sources=(replace(lease.proof.sources[0], tier="official_api"),))
            elif control == "platform":
                lease.proof = replace(lease.proof, sources=(replace(lease.proof.sources[0], platform="tiktok"),))
            else:
                lease.proof = replace(lease.proof, sources=(replace(lease.proof.sources[0], capability_epoch=2),))
            yield lease

    verifier.hold_current = controlled
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert result.reason_code == reason
    assert (await repository.load_mission_follow_ups(mission.id)).relationships == ()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["partial", "mismatch", "legacy"])
async def test_historical_resource_metadata_must_be_complete_and_exact(tmp_path, control):
    repository, mission, follow, authority, _ = await ready(tmp_path)
    first = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert first.disposition == "APPLIED"
    following, _ = await sibling(repository, mission, follow, authority)
    connection = repository._get_connection()
    if control == "partial":
        connection.execute("DROP TRIGGER mission_follow_up_reservation_resources_delete_immutable")
        connection.execute("DELETE FROM mission_follow_up_reservation_resources")
    elif control == "mismatch":
        connection.execute("DROP TRIGGER mission_follow_up_reservation_resources_update_immutable")
        connection.execute("UPDATE mission_follow_up_reservation_resources SET allocated=1")
    else:
        connection.execute("DROP TRIGGER mission_follow_up_authorities_delete_immutable")
        connection.execute("DELETE FROM mission_follow_up_authorities WHERE work_id=?", (str(follow.work_id),))
    connection.commit()
    connection.close()
    result = await repository.admit_mission_follow_up(
        command(mission, following, (await repository.load_research_work(mission.id)).revision, key="next")
    )
    assert result.reason_code == "RECONCILIATION_REQUIRED"
    assert len((await repository.load_mission_follow_ups(mission.id)).relationships) == 1
    await repository.close()


@pytest.mark.asyncio
async def test_child_uses_only_selected_authority_and_fresh_lifecycle(tmp_path):
    repository, mission, follow, _, _ = await ready(tmp_path)
    before = await repository.load_research_work(mission.id)
    result = await repository.admit_mission_follow_up(command(mission, follow, before.revision))
    child = await repository.load_mission_evidence_snapshot(result.relationship.child_mission_id)
    assert child.mission.status == "PENDING" and child.mission.workspace_id == mission.workspace_id
    assert (
        child.mission.session_id is None
        and child.mission.parent_attention_mission_id is None
        and child.mission.revises_mission_id is None
    )
    assert child.manifest.authority_boundary.to_payload() == {
        "public_http": True,
        "official_api": False,
        "browser_session": False,
        "paid_quota": False,
    }
    assert child.manifest.required_channels == ("youtube",) and child.manifest.optional_channels == ()
    assert dict(child.manifest.quota_budget) == {"queries": 2}
    assert len(child.signals) == len(child.outcomes) == len(child.claims) == 0
    assert (await repository.load_research_work(mission.id)).work_items == before.work_items
    await repository.close()


@pytest.mark.asyncio
async def test_fact_registration_original_receipt_survives_missing_owner_provider(tmp_path):
    from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
    from ignis.domain.follow_up_admission import OperationalGap

    repository, mission, follow, _, _ = await ready(tmp_path)
    record = OperationalGap(
        gap_id=uuid4(), parent_work_id=follow.parent_work_id, inputs=follow.inputs, question="Bounded operational gap"
    )
    before = await repository.load_research_work(mission.id)
    cmd = FollowUpFactCommand(
        mission_id=mission.id,
        record=record,
        expected_revision=before.revision,
        idempotency_key="fact",
        host_authorized=True,
    )
    receipt = await repository.record_follow_up_fact(cmd)
    assert receipt.disposition == "APPLIED" and receipt.revision == before.revision + 1 and receipt.event_ids == ()
    repository.configure_follow_up_verifier(None)
    assert await repository.record_follow_up_fact(cmd) == receipt
    conflict = await repository.record_follow_up_fact(replace(cmd, expected_revision=0))
    assert conflict.reason_code == "IDEMPOTENCY_CONFLICT"
    after = await repository.load_research_work(mission.id)
    assert (
        after.revision == receipt.revision and after.events == before.events and after.work_items == before.work_items
    )
    await repository.close()


@pytest.mark.asyncio
async def test_new_parent_evidence_invalidates_recorded_gap_before_child(tmp_path):
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType, GeoCode

    repository, mission, follow, _, _ = await ready(tmp_path)
    await repository.save_signals(
        [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title="Synthetic new evidence",
                metric_value=1,
                geo_code=GeoCode.VN,
                source_url="https://example.com/new-bound-input",
                mission_id=mission.id,
            )
        ]
    )
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert result.reason_code == "STALE_INPUT_FRAME"
    assert (await repository.load_mission_follow_ups(mission.id)).relationships == ()
    await repository.close()


@pytest.mark.asyncio
async def test_alias_recovery_rejects_foreign_historical_receipt(tmp_path):
    from ignis.infrastructure.persistence.sqlite_follow_up_admission import encode

    repository, mission, follow, _, _ = await ready(tmp_path)
    cmd = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    original = await repository.admit_mission_follow_up(cmd)
    foreign = replace(original.relationship, child_mission_id=uuid4())
    corrupted = replace(original, relationship=foreign, reservation=replace(original.reservation, relationship=foreign))
    connection = repository._get_connection()
    connection.execute("DROP TRIGGER mission_follow_up_commands_update_immutable")
    connection.execute(
        "UPDATE mission_follow_up_commands SET receipt_payload=? WHERE operation='ADMIT'", (encode(corrupted),)
    )
    connection.commit()
    connection.close()
    repository.configure_follow_up_verifier(None)
    alias = replace(cmd, request=replace(cmd.request, idempotency_key="foreign-history"))
    result = await repository.admit_mission_follow_up(alias)
    assert result.reason_code == "STORAGE_FAILURE" and result.relationship is None
    connection = repository._get_connection()
    assert (
        connection.execute("SELECT count(*) FROM mission_follow_up_commands WHERE operation='ADMIT'").fetchone()[0] == 1
    )
    assert connection.execute("SELECT count(*) FROM mission_follow_ups").fetchone()[0] == 1
    connection.close()
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("alias", [False, True])
async def test_two_real_children_cannot_splice_frozen_work_ownership(tmp_path, alias):
    from ignis.infrastructure.persistence.sqlite_follow_up_admission import encode

    repository, mission, follow, authority, _ = await ready(tmp_path)
    first_command = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    first = await repository.admit_mission_follow_up(first_command)
    following, _ = await sibling(repository, mission, follow, authority)
    second = await repository.admit_mission_follow_up(
        command(mission, following, (await repository.load_research_work(mission.id)).revision, key="second-child")
    )
    assert first.disposition == second.disposition == "APPLIED"
    spliced = replace(second.relationship, work=first.relationship.work)
    forged = replace(first, relationship=spliced, reservation=replace(second.reservation, relationship=spliced))
    connection = repository._get_connection()
    connection.execute("DROP TRIGGER mission_follow_up_commands_update_immutable")
    connection.execute(
        "UPDATE mission_follow_up_commands SET receipt_payload=? WHERE operation='ADMIT' AND work_id=?",
        (encode(forged), str(follow.work_id)),
    )
    connection.commit()
    connection.close()
    repository.configure_follow_up_verifier(None)
    request = (
        replace(first_command, request=replace(first_command.request, idempotency_key="splice-alias"))
        if alias
        else first_command
    )
    result = await repository.admit_mission_follow_up(request)
    assert result.reason_code == "STORAGE_FAILURE" and result.relationship is None
    connection = repository._get_connection()
    assert connection.execute("SELECT count(*) FROM mission_follow_ups").fetchone()[0] == 2
    assert (
        connection.execute("SELECT count(*) FROM mission_follow_up_commands WHERE operation='ADMIT'").fetchone()[0] == 2
    )
    connection.close()
    await repository.close()


@pytest.mark.asyncio
async def test_later_child_evidence_and_terminal_state_preserve_original_recovery(tmp_path):
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType, GeoCode

    repository, mission, follow, _, _ = await ready(tmp_path)
    cmd = command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    original = await repository.admit_mission_follow_up(cmd)
    child = await repository.get_mission(original.relationship.child_mission_id)
    await repository.save_signals(
        [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title="Later synthetic child evidence",
                metric_value=2,
                source_url="https://example.com/later-child",
                geo_code=GeoCode.VN,
                mission_id=child.id,
            )
        ]
    )
    child.status = "COMPLETED"
    await repository.update_mission(child)
    repository.configure_follow_up_verifier(None)
    assert await repository.admit_mission_follow_up(cmd) == original
    alias = replace(cmd, request=replace(cmd.request, idempotency_key="later-child-alias"))
    recovered = await repository.admit_mission_follow_up(alias)
    assert recovered.disposition == "EXISTING" and recovered.relationship == original.relationship
    assert len((await repository.load_mission_evidence_snapshot(child.id)).signals) == 1
    await repository.close()


@pytest.mark.asyncio
async def test_guard_holds_policy_generation_through_physical_commit(tmp_path):
    repository, mission, follow, _, verifier = await ready(tmp_path)
    attempted = threading.Event()
    changed = threading.Event()
    threads = []
    original = repository._write_manifest_row

    def write(cursor, manifest):
        def revoke():
            attempted.set()
            with verifier.lock:
                verifier.generation += 1
                changed.set()

        thread = threading.Thread(target=revoke)
        threads.append(thread)
        thread.start()
        assert attempted.wait(1)
        assert not changed.wait(0.025), "Generation changed while physical transaction guard should be held"
        return original(cursor, manifest)

    repository._write_manifest_row = write
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    for thread in threads:
        thread.join(1)
    assert result.disposition == "APPLIED" and changed.is_set() and all(not t.is_alive() for t in threads)
    await repository.close()


@pytest.mark.asyncio
async def test_operational_generation_revocation_invalidates_cached_stop_proof(tmp_path):
    repository, mission, follow, _, verifier = await ready(tmp_path)
    original = verifier.hold_current

    @asynccontextmanager
    async def changed(request):
        async with original(request) as lease:
            verifier.operational_generation += 1
            yield lease

    verifier.hold_current = changed
    result = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert (await repository.load_mission_follow_ups(mission.id)).relationships == ()
    await repository.close()


@pytest.mark.asyncio
async def test_follow_up_reader_never_creates_missing_storage(tmp_path):
    from ignis.domain.exceptions import RepositoryException

    target = tmp_path / "missing-follow-up.db"
    repository = SqliteTrendRepository(str(target))
    with pytest.raises(RepositoryException):
        await repository.load_mission_follow_ups(uuid4())
    assert not target.exists()
    await repository.close()


@pytest.mark.asyncio
async def test_tightened_new_assignment_ceiling_does_not_reset_previous_allocation(tmp_path):
    repository, mission, follow, authority, _ = await ready(tmp_path)
    first = await repository.admit_mission_follow_up(
        command(mission, follow, (await repository.load_research_work(mission.id)).revision)
    )
    assert first.disposition == "APPLIED"
    following, _ = await sibling(repository, mission, follow, authority, new_epoch=True, quota_ceiling=2)
    result = await repository.admit_mission_follow_up(
        command(mission, following, (await repository.load_research_work(mission.id)).revision, key="tightened")
    )
    assert result.reason_code == "QUOTA_EXHAUSTED"
    assert len((await repository.load_mission_follow_ups(mission.id)).relationships) == 1
    await repository.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("plugin_type", ["creative", "grid"])
async def test_child_keeps_exact_plugin_and_verified_platform(tmp_path, plugin_type):
    from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
    from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin

    plugin_class = TikTokCreativeCenterPlugin if plugin_type == "creative" else TikTokPlugin
    # Read canonical property metadata without constructing any authentication manager.
    plugin = object.__new__(plugin_class)
    repository, mission, follow, _, _ = await ready(
        tmp_path, source_id=plugin.plugin_id, source_platform=plugin.platform.value
    )
    revision = (await repository.load_research_work(mission.id)).revision
    receipt = await repository.admit_mission_follow_up(command(mission, follow, revision))
    assert receipt.disposition == "APPLIED", receipt.reason_code
    child = await repository.load_mission_evidence_snapshot(receipt.relationship.child_mission_id)
    assert child.mission.platforms == [plugin.platform]
    assert child.manifest.required_channels == (plugin.plugin_id,)
    # These are the registry's exact selection predicates; no runtime/session is opened.
    selected = [
        p
        for p in (plugin,)
        if p.supports_search
        and p.platform in child.mission.platforms
        and p.plugin_id in child.manifest.required_channels
    ]
    assert selected == ([plugin] if plugin.supports_search else [])
