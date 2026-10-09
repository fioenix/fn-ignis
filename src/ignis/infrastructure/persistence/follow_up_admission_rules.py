"""Pure follow-up codec, authority, child construction and original recovery comparisons."""

from dataclasses import fields, is_dataclass, replace
from datetime import datetime
from hashlib import sha256
import json
from uuid import UUID

from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
from ignis.application.ports.research_work_port import (
    FollowUpAdmissionCommand,
    FollowUpCommitReceipt,
    FollowUpWorkCommand,
    ResearchWorkCommitReceipt,
)
from ignis.domain.follow_up_admission import (
    AssignmentBudget,
    OperationalGap,
    ParentBudget,
    SourceGrant,
    WorkAuthority,
    digest,
)
from ignis.domain.mission_follow_up import (
    FollowUpWork,
    FollowUpScope,
    FollowUpRelationship,
    FollowUpReservation,
    FollowUpExecutionRequest,
)
from ignis.domain.research_work import ResearchInputBindings, TERMINAL
from ignis.domain.research_workspace import compute_frame_fingerprint
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.value_objects import resolve_platform
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import AuthorityBoundary

_TYPES = {
    c.__name__: c
    for c in (
        AssignmentBudget,
        OperationalGap,
        ParentBudget,
        SourceGrant,
        WorkAuthority,
        FollowUpWork,
        FollowUpScope,
        ResearchInputBindings,
        FollowUpRelationship,
        FollowUpReservation,
        FollowUpCommitReceipt,
        ResearchWorkCommitReceipt,
        FollowUpFactCommand,
        FollowUpAdmissionCommand,
        FollowUpWorkCommand,
        FollowUpExecutionRequest,
    )
}


def pack(value):
    if is_dataclass(value):
        return {"type": type(value).__name__, "fields": {f.name: pack(getattr(value, f.name)) for f in fields(value)}}
    if type(value) is UUID:
        return {"uuid": str(value)}
    if type(value) is datetime:
        return {"time": value.isoformat()}
    if type(value) is tuple:
        return {"tuple": [pack(v) for v in value]}
    if type(value) is frozenset:
        return {"set": sorted(value)}
    return value


def unpack(value):
    if type(value) is not dict:
        return value
    if "type" in value:
        return _TYPES[value["type"]](**{k: unpack(v) for k, v in value["fields"].items()})
    if "uuid" in value:
        return UUID(value["uuid"])
    if "time" in value:
        return datetime.fromisoformat(value["time"])
    if "tuple" in value:
        return tuple(unpack(v) for v in value["tuple"])
    if "set" in value:
        return frozenset(value["set"])
    raise ValueError("Invalid persisted admission record.")


def encode(value):
    return json.dumps(pack(value), sort_keys=True, separators=(",", ":"))


def decode(value):
    return unpack(json.loads(value))


def input_reason(inputs, canonical, research):
    if canonical.mission is None or canonical.manifest is None or canonical.brief is None:
        return "STALE_INPUT_FRAME"
    if inputs.manifest_digest != canonical.manifest.manifest_digest:
        return "MANIFEST_MISMATCH"
    if inputs.brief_digest != compute_frame_fingerprint(canonical.mission, canonical.brief):
        return "BRIEF_REVISION_MISMATCH"
    try:
        current_frame = frame_from_snapshot(canonical).frame_digest
    except ValueError:
        return "STALE_INPUT_FRAME"
    if inputs.frame_digest != current_frame:
        return "STALE_INPUT_FRAME"
    if not set(inputs.observation_ids) <= set(dict(research.observation_sources)):
        return "INPUT_IDENTITY_MISMATCH"
    if not set(inputs.finding_revisions) <= set(research.current_finding_revisions):
        return "STALE_DEPENDENCY_REVISION"
    return None


def origin_reason(gap, research):
    parent = next((w for w in research.work_items if w.work_id == gap.parent_work_id), None)
    if parent is None or parent.inputs != gap.inputs:
        return "INPUT_IDENTITY_MISMATCH"
    if gap.finding_id is None:
        return None if gap.question == parent.question else "INPUT_IDENTITY_MISMATCH"
    finding = next(
        (f for f in research.findings if (f.finding_id, f.revision) == (gap.finding_id, gap.finding_revision)), None
    )
    if finding is None or (gap.finding_id, gap.finding_revision) not in research.current_finding_revisions:
        return "STALE_DEPENDENCY_REVISION"
    if (
        finding.work_id != parent.work_id
        or finding.inputs != gap.inputs
        or gap.question_index >= len(finding.open_questions)
    ):
        return "INPUT_IDENTITY_MISMATCH"
    return None if finding.open_questions[gap.question_index] == gap.question else "INPUT_IDENTITY_MISMATCH"


def authority_reason(authority, canonical, research, gap, root, binding, now):
    work = authority.work
    assignment = next((a for a in research.assignments if a.assignment_id == work.assignment_id), None)
    current = next((w for w in research.work_items if w.work_id == work.work_id), None)
    if assignment is None or current is None or current.assignment_id != assignment.assignment_id:
        return "SCOPE_MISMATCH"
    if assignment.epoch != work.research_epoch or research.current_epoch != work.research_epoch:
        return "STALE_EPOCH"
    if assignment.version != work.assignment_version or current.version != work.work_version:
        return "STALE_VERSION"
    if current.inputs != work.inputs:
        return "INPUT_IDENTITY_MISMATCH"
    reason = input_reason(work.inputs, canonical, research)
    if reason:
        return reason
    if canonical.brief.brief_revision_id != work.brief_revision_id:
        return "BRIEF_REVISION_MISMATCH"
    if canonical.mission.status == "CANCELLED":
        return "CANCEL_REQUESTED"
    if assignment.state in TERMINAL:
        return "RESEARCH_TERMINAL"
    if current.state in TERMINAL:
        return "WORK_TERMINAL"
    if assignment.state == "CANCEL_PENDING" or current.state == "CANCEL_PENDING":
        return "CANCEL_REQUESTED"
    if "FOLLOW_UP" not in assignment.authority.actions:
        return "COLLECTION_AUTHORITY_REQUIRED"
    if min(assignment.authority.deadline, work.authority_deadline) <= now:
        return "AUTHORITY_EXPIRED"
    if work.authority_deadline > assignment.authority.deadline:
        return "AUTHORITY_WIDENING"
    if not work.approved_scope.contains(work.requested_scope):
        return "AUTHORITY_WIDENING"
    if not work.approved_scope.sources <= assignment.authority.sources:
        return "SOURCE_MISMATCH"
    if not work.approved_scope.sources <= set(canonical.manifest.allowed_resources):
        return "SOURCE_MISMATCH"
    if {s.source for s in authority.sources} != work.requested_scope.sources:
        return "SOURCE_MISMATCH"
    for source in authority.sources:
        if not getattr(canonical.manifest.authority_boundary, source.tier):
            return "SESSION_AUTHORITY_REQUIRED"
        if source.paid and not canonical.manifest.authority_boundary.paid_quota:
            return "SESSION_AUTHORITY_REQUIRED"
    if gap is None:
        return "UNKNOWN_FOLLOW_UP"
    if gap.inputs != work.inputs or gap.parent_work_id != work.parent_work_id:
        return "INPUT_IDENTITY_MISMATCH"
    reason = origin_reason(gap, research)
    if reason:
        return reason
    if root is None or binding is None:
        return "COLLECTION_AUTHORITY_REQUIRED"
    if (
        root.mission_id != work.inputs.mission_id
        or root.manifest_digest != work.inputs.manifest_digest
        or root.brief_digest != work.inputs.brief_digest
    ):
        return "STALE_INPUT_FRAME"
    if (
        binding.budget_id != root.budget_id
        or binding.assignment_id != assignment.assignment_id
        or binding.epoch != assignment.epoch
        or binding.assignment_version != assignment.version
    ):
        return "STALE_VERSION"
    if binding.assignment_quota != assignment.authority.quota_ceiling or binding.quota_unit != root.quota_unit:
        return "AUTHORITY_WIDENING"
    if authority.quota_unit != root.quota_unit or authority.cost_unit != root.cost_unit:
        return "AUTHORITY_WIDENING"
    if authority.quota_ceiling > min(root.quota_ceiling, binding.assignment_quota) or authority.cost_ceiling > min(
        root.cost_ceiling, binding.cost_ceiling
    ):
        return "AUTHORITY_WIDENING"
    manifest = dict(canonical.manifest.quota_budget)
    limits = dict(root.resources)
    if any(k not in manifest or v > manifest[k] for k, v in limits.items()):
        return "AUTHORITY_WIDENING"
    if any(k not in limits or v > limits[k] for k, v in authority.resources):
        return "AUTHORITY_WIDENING"
    # Every requested plan resource has an explicit allocation; the provider checks actual plan coverage.
    if not authority.resources:
        return "AUTHORITY_WIDENING"
    return None


def command_identity(row, mission_id):
    stored = decode(row["command_payload"])
    receipt = decode(row["receipt_payload"])
    if type(stored) is FollowUpAdmissionCommand:
        parent = stored.request.mission_id
        work = stored.request.follow_up_work_id
        key = stored.request.idempotency_key
        operation = "ADMIT"
        expected_type = FollowUpCommitReceipt
    elif type(stored) is FollowUpWorkCommand:
        parent = stored.work.inputs.mission_id
        work = stored.work.work_id
        key = stored.idempotency_key
        operation = "RECORD"
        expected_type = ResearchWorkCommitReceipt
    elif type(stored) is FollowUpFactCommand:
        parent = stored.mission_id
        key = stored.idempotency_key
        operation = "FACT"
        expected_type = ResearchWorkCommitReceipt
        record = stored.record
        work = (
            record.work.work_id
            if type(record) is WorkAuthority
            else record.gap_id
            if type(record) is OperationalGap
            else record.budget_id
            if type(record) is ParentBudget
            else record.binding_id
        )
    else:
        raise ValueError("Invalid original command type.")
    if (
        parent != mission_id
        or str(work) != row["work_id"]
        or operation != row["operation"]
        or digest(stored) != row["fingerprint"]
        or sha256(key.encode()).hexdigest() != row["command_key"]
        or type(receipt) is not expected_type
    ):
        raise ValueError("Original command identity mismatch.")
    return stored, receipt, work


def child_records(canonical, live, revision_number, child_id, brief_id):
    work = live.work
    brief = replace(canonical.brief, brief_revision_id=brief_id, mission_id=child_id, revision_number=revision_number)
    tiers = {s.tier for s in live.sources}
    boundary = AuthorityBoundary(
        public_http="public_http" in tiers,
        official_api="official_api" in tiers,
        browser_session="browser_session" in tiers,
        paid_quota=any(s.paid for s in live.sources),
    )
    manifest = replace(
        canonical.manifest,
        mission_id=child_id,
        required_channels=tuple(sorted(work.requested_scope.sources)),
        optional_channels=(),
        authority_boundary=boundary,
        quota_budget=dict(live.resources),
    )
    child = ResearchMission(
        id=child_id,
        title=canonical.mission.title,
        shortcode=child_id.hex[:8],
        keywords=list(work.requested_scope.queries),
        platforms=[resolve_platform(p) for p in sorted({s.platform for s in live.sources})],
        status="PENDING",
        geo_code=canonical.mission.geo_code,
        timeframe=canonical.mission.timeframe,
        agent=canonical.mission.agent,
        workspace_id=canonical.mission.workspace_id,
        surface=canonical.mission.surface,
        brief_revision_id=brief_id,
    )
    return child, brief, manifest


def recovery_binding(
    receipt,
    mission_id,
    work,
    *,
    physical,
    proposal,
    envelope,
    root,
    binding,
    allocation,
    allocated_resources,
    child,
    parent_workspace,
    manifest,
    manifest_digest,
    original_briefs,
):
    relation = receipt.relationship
    expected = (
        str(relation.follow_up_id),
        str(mission_id),
        str(relation.child_mission_id),
        str(work),
        str(relation.reservation_id),
        relation.child_manifest_digest,
        relation.child_brief_digest,
        relation.idempotency_key,
    )
    keys = (
        "follow_up_id",
        "parent_mission_id",
        "child_mission_id",
        "work_id",
        "reservation_id",
        "child_manifest_digest",
        "child_brief_digest",
        "idempotency_key",
    )
    if physical is None or tuple(physical[k] for k in keys) != expected or proposal != relation.work:
        raise ValueError("Full original work/relationship ownership mismatch.")
    if envelope is None or envelope.work != relation.work:
        raise ValueError("Original proposal authority mismatch.")
    if (
        root is None
        or binding is None
        or root.mission_id != mission_id
        or binding.budget_id != root.budget_id
        or binding.assignment_id != relation.work.assignment_id
    ):
        raise ValueError("Original budget binding mismatch.")
    frozen = receipt.reservation
    keys = (
        "reservation_id",
        "follow_up_id",
        "parent_mission_id",
        "child_mission_id",
        "reserved_quota",
        "reserved_cost",
    )
    expected = (
        str(relation.reservation_id),
        str(relation.follow_up_id),
        str(mission_id),
        str(relation.child_mission_id),
        envelope.quota,
        envelope.cost,
    )
    if (
        allocation is None
        or frozen.state != "RESERVED"
        or frozen.measured_quota is not None
        or frozen.measured_cost is not None
        or frozen.measurement_receipt_id is not None
        or frozen.reserved_quota != envelope.quota
        or frozen.reserved_cost != envelope.cost
        or tuple(allocation[k] for k in keys) != expected
    ):
        raise ValueError("Original immutable allocation mismatch.")
    if dict(allocated_resources) != dict(envelope.resources):
        raise ValueError("Original resource allocation mismatch.")
    if (
        child is None
        or parent_workspace is None
        or child[0] != parent_workspace[0]
        or child[1] != "MARKET"
        or manifest is None
    ):
        raise ValueError("Original child ownership mismatch.")
    if manifest.manifest_digest != relation.child_manifest_digest or manifest_digest != relation.child_manifest_digest:
        raise ValueError("Original child manifest mismatch.")
    identity = ResearchMission(
        id=relation.child_mission_id, title="Historical child identity", keywords=[], surface="MARKET"
    )
    matches = [b for b in original_briefs if compute_frame_fingerprint(identity, b) == relation.child_brief_digest]
    if len(matches) != 1:
        raise ValueError("Original child Brief revision is absent or ambiguous.")


def execution_budget_reason(authority, root, reservations, allocations, *, admitted):
    """Read-only execution preflight retains all epochs and unknown resource allocations."""
    from ignis.domain.mission_follow_up import encumbered_budget

    used_quota, used_cost = encumbered_budget(authority.work.inputs.mission_id, reservations)
    if used_quota + (0 if admitted else authority.quota) > authority.quota_ceiling:
        return "QUOTA_EXHAUSTED"
    if used_cost + (0 if admitted else authority.cost) > authority.cost_ceiling:
        return "COST_EXHAUSTED"
    used = {}
    for resource, allocated in allocations:
        used[resource] = used.get(resource, 0) + allocated
    limits = dict(root.resources)
    required = dict(authority.resources) if not admitted else {}
    if any(used.get(k, 0) + required.get(k, 0) > ceiling for k, ceiling in limits.items()):
        return "QUOTA_EXHAUSTED"
    if set(used) - limits.keys():
        raise ValueError("Unbound resource history.")
    return None
