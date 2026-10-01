"""Typed contracts shared by collection, qualification, claims, and gap outputs."""

import inspect
from datetime import datetime
from uuid import uuid4

import pytest

from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain import research_workspace as workspace


def _contract(name: str):
    assert hasattr(workspace, name), f"{name} is required by the evidence-grounded contract"
    return getattr(workspace, name)


def test_market_brief_signature_carries_the_complete_hypothesis_register():
    parameters = inspect.signature(workspace.MarketBriefRevision).parameters

    for name in (
        "alternative_hypotheses",
        "null_hypothesis",
        "kill_criteria",
        "revision_rule",
    ):
        assert name in parameters


def test_channel_states_distinguish_every_measured_and_unmeasured_outcome():
    assert {status.value for status in ChannelHealthStatus} == {
        "HEALTHY",
        "EMPTY_NO_DATA",
        "AUTH_REQUIRED",
        "RATE_LIMITED",
        "DEGRADED",
        "FAILED",
        "NOT_REQUESTED",
    }


def test_qualification_direction_does_not_repurpose_mission_lineage_role():
    EvidenceDirection = _contract("EvidenceDirection")

    assert {role.value for role in EvidenceDirection} == {
        "SUPPORT",
        "CONTRADICTION",
        "CONTEXT",
    }
    assert {role.value for role in workspace.EvidenceRole} == {
        "MARKET_EVIDENCE",
        "ATTENTION_CONTEXT",
    }


def test_contradiction_is_a_first_class_relation_not_sentiment():
    assert {relation.value for relation in workspace.QualificationRelation} == {
        "QUALIFIED_SUPPORT",
        "QUALIFIED_CONTRADICTION",
        "CONTEXT_ONLY",
        "EXCLUDED_IRRELEVANT",
        "UNASSESSED",
    }


def test_collection_plan_digest_changes_with_probe_role_scope_or_authority():
    digest = _contract("compute_collection_plan_digest")
    plan = {
        "query_families": ["root", "falsification"],
        "evidence_targets": ["core", "alternative:price"],
        "expected_role": "CONTRADICTION",
        "connector_surface": "threads_search",
        "scope": {"geo": "VN", "timeframe": "30d"},
        "sampling": {"limit": 50, "ordering": "platform"},
        "authority_tier": "public_http",
    }

    assert digest(plan) == digest(dict(reversed(tuple(plan.items()))))
    assert digest(plan) != digest({**plan, "expected_role": "SUPPORT"})
    assert digest(plan) != digest({**plan, "authority_tier": "browser_session"})


def test_evidence_frame_digest_binds_every_constituent_identity():
    digest = _contract("compute_evidence_frame_digest")
    frame = {
        "mission_id": str(uuid4()),
        "brief_revision_id": str(uuid4()),
        "manifest_digest": "a" * 64,
        "collection_plan_digest": "b" * 64,
        "observations_digest": "c" * 64,
        "qualifications_digest": "d" * 64,
        "channel_outcomes_digest": "e" * 64,
        "analysis_policy": "evidence-gated-v1",
    }

    baseline = digest(**frame)
    assert len(baseline) == 64
    assert baseline != digest(**{**frame, "qualifications_digest": "f" * 64})


def test_claim_enums_name_statement_semantics_and_render_permission():
    ClaimType = _contract("ClaimType")
    ClaimStatus = _contract("ClaimStatus")

    assert {kind.value for kind in ClaimType} == {
        "OBSERVATION",
        "MEASUREMENT",
        "INFERENCE",
        "ASSUMPTION",
        "RECOMMENDATION",
        "UNKNOWN",
    }
    assert {status.value for status in ClaimStatus} == {
        "PERMITTED",
        "WITHHELD",
        "SUPERSEDED",
    }


def test_claim_binding_accepts_exactly_one_evidence_identity():
    EvidenceDirection = _contract("EvidenceDirection")
    InvalidMissionClaimError = _contract("InvalidMissionClaimError")
    MissionClaimEvidence = _contract("MissionClaimEvidence")
    claim_id = uuid4()

    observation = MissionClaimEvidence(
        claim_id=claim_id,
        observation_id=uuid4(),
        probe_outcome_id=None,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )
    assert observation.observation_id is not None

    with pytest.raises(InvalidMissionClaimError):
        MissionClaimEvidence(
            claim_id=claim_id,
            observation_id=None,
            probe_outcome_id=None,
            role=EvidenceDirection.CONTEXT,
            hypothesis_target=None,
        )
    with pytest.raises(InvalidMissionClaimError):
        MissionClaimEvidence(
            claim_id=claim_id,
            observation_id=uuid4(),
            probe_outcome_id=uuid4(),
            role=EvidenceDirection.SUPPORT,
            hypothesis_target="core",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"created_by": "x" * 129},
        {"created_at": datetime(2026, 9, 30, 10, 0)},
    ],
)
def test_claim_identity_and_clock_match_the_persistence_contract(overrides):
    MissionClaim = _contract("MissionClaim")
    InvalidMissionClaimError = _contract("InvalidMissionClaimError")

    values = {
        "mission_id": uuid4(),
        "frame_digest": "a" * 64,
        "client_claim_key": "claim-1",
        "claim_type": "ASSUMPTION",
        "wording": "A bounded assumption.",
        "status": "WITHHELD",
        "withheld_reasons": ("NO_EVIDENCE",),
        "created_by": "contract-test",
        **overrides,
    }
    with pytest.raises(InvalidMissionClaimError):
        MissionClaim(**values)


def test_gap_report_is_structured_and_contains_no_placeholder_verdict():
    GapReport = _contract("GapReport")
    report = GapReport(
        withheld_outputs=("OPPORTUNITY_INDEX", "COMMERCIAL_VERDICT"),
        failed_gates=("MISSING_REQUIRED_METRIC",),
        missing_evidence=("purchase-intent denominator",),
        attempted_probes=({"surface": "threads", "state": "AUTH_REQUIRED"},),
        safe_partial_conclusions=("The available sample discusses setup friction",),
        next_best_probe="Authorize one bounded Threads keyword search",
        required_authority="threads browser session",
        estimated_cost=None,
    )

    payload = report.to_payload()
    assert payload["withheld_outputs"] == ["OPPORTUNITY_INDEX", "COMMERCIAL_VERDICT"]
    assert "opportunity_index" not in payload
    assert payload["next_best_probe"] == "Authorize one bounded Threads keyword search"
