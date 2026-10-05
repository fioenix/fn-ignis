"""US3 negatives use canonical frames and ledger facts, never permission mocks."""

from dataclasses import replace
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.application.use_cases.get_mission_relay_snapshot import (
    GetMissionRelaySnapshotUseCase, project_mission_relay_snapshot,
)
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
from ignis.domain.mission_relay import MissionRelayCursor
from ignis.domain.research_workspace import ClaimStatus, QualificationContext, assess_strategic_sufficiency
from ignis.infrastructure.persistence.mission_relay_reader import SqliteMissionRelayReader
from test_mission_claims import _eligible_mission, _observation_candidate, _signal_named


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def market_records(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    try:
        submitted = await SubmitMissionClaimsUseCase(repository, store).execute(
            str(mission.id), frame.frame_digest, [_observation_candidate(_signal_named(signals, "Demand evidence"))],
            created_by="relay-contract-test",
        )
        assert submitted.get("permitted") == 1, "Canonical fixture must establish persisted permission before viewer tests"
        evidence = await store.load_mission_evidence_snapshot(mission.id)
        withheld_id = uuid4()
        withheld = replace(evidence.claims[0], claim_id=withheld_id, client_claim_key="withheld-control",
                           status=ClaimStatus.WITHHELD, withheld_reasons=("UNVERIFIED_CONTROL",),
                           evidence_bindings=tuple(replace(b, binding_id=uuid4(), claim_id=withheld_id)
                                                   for b in evidence.claims[0].evidence_bindings))
        await store.commit_mission_claims(mission.id, frame.frame_digest, [withheld])
        evidence = await store.load_mission_evidence_snapshot(mission.id)
        run = (await store.list_run_journals(mission.id))[0]
        yield repository, store, evidence, run, frame
    finally:
        await repository.close()


def project(evidence, run, *, selected_run_id=None):
    result = project_mission_relay_snapshot(
        selected_mission_id=evidence.mission.id, selected_run_id=selected_run_id or run.run_id,
        evidence=evidence, run=run, revision=1, read_at=run.completed_at,
        page_size=200, high_water=MissionRelayCursor(mission_id=evidence.mission.id, revision=1, ordinal=1),
    )
    return result.to_payload()


def gate(payload):
    assert "claim_gate" in payload, "US3 must expose an explicit permission/missingness gate"
    return payload["claim_gate"]


async def test_exact_completed_frame_renders_only_persisted_permitted_claims(market_records):
    _, _, evidence, run, frame = market_records
    payload = project(evidence, run)
    actual = gate(payload)
    assert payload["frame_digest"] == frame.frame_digest
    assert actual["state"] == "CURRENT"
    assert actual["render_status"] == "PERMITTED"
    permitted = next(c for c in evidence.claims if c.status is ClaimStatus.PERMITTED)
    assert [c["claim_id"] for c in actual["claims"]] == [str(permitted.claim_id)]
    assert actual["claims"][0]["evidence_bindings"] == [b.to_payload() for b in permitted.evidence_bindings]


@pytest.mark.parametrize("state", ["STARTED", "RUNNING", "FAILED", "CANCELLED"])
async def test_incomplete_or_failed_selected_run_never_reuses_old_completed_permission(market_records, state):
    _, _, evidence, run, _ = market_records
    payload = project(evidence, replace(run, status=state))
    actual = gate(payload)
    assert actual["render_status"] == "WITHHELD"
    assert actual["claims"] == []
    assert payload["frame_digest"] is None
    assert actual["state"] == ("PENDING" if state in ("STARTED", "RUNNING") else "UNAVAILABLE")


async def test_changed_corpus_keeps_old_ledger_as_labeled_history_only(market_records):
    _, _, evidence, run, _ = market_records
    changed = replace(evidence.signals[0], raw_title="A changed canonical observation")
    payload = project(replace(evidence, signals=(changed, *evidence.signals[1:])), run)
    actual = gate(payload)
    assert actual["render_status"] == "WITHHELD"
    assert actual["claims"] == []
    assert {c["claim_id"] for c in actual["history"]} == {str(c.claim_id) for c in evidence.claims}
    assert all(c["status"] == "SUPERSEDED" for c in actual["history"])
    assert actual["gap_report"]["next_best_probe"]


async def test_unknown_metric_annotation_never_exports_placeholder_number(market_records):
    _, _, evidence, run, _ = market_records
    signals = tuple(replace(s, metric_value=500, growth_velocity=3.5, published_at=None,
                            metadata={**s.metadata, "metric_known": False}) for s in evidence.signals)
    payload = project(replace(evidence, signals=signals), run)
    assert all(row["metric_value"] is None and row["growth_velocity"] is None
               and row["published_at"] is None for row in payload["evidence"])


async def test_known_zero_is_retained_as_measured_zero(market_records):
    _, _, evidence, run, _ = market_records
    signals = tuple(replace(s, metric_value=0, growth_velocity=0,
                            metadata={**s.metadata, "metric_known": True}) for s in evidence.signals)
    payload = project(replace(evidence, signals=signals), run)
    assert all(row["metric_value"] == 0 and row["growth_velocity"] == 0 for row in payload["evidence"])


async def test_paginated_coherent_read_uses_full_canonical_frame_not_page_digest(market_records):
    repository, _, evidence, run, frame = market_records
    use_case = GetMissionRelaySnapshotUseCase(SqliteMissionRelayReader(repository))
    payload = (await use_case.execute(MissionRelayReadRequest(
        mission_id=evidence.mission.id, run_id=run.run_id, page_size=1,
    ))).to_payload()
    assert len(payload["evidence"]) == 1
    assert payload["counts"]["observations"] == len(evidence.signals)
    assert payload["frame_digest"] == frame.frame_digest
    assert gate(payload)["render_status"] == "PERMITTED"


async def test_foreign_run_or_claim_scope_refuses_before_exposing_wording(market_records):
    _, _, evidence, run, _ = market_records
    for bad_evidence, bad_run in [
        (evidence, replace(run, mission_id=uuid4())),
        (replace(evidence, claims=(replace(evidence.claims[0], mission_id=uuid4()),)), run),
    ]:
        payload = project(bad_evidence, bad_run)
        assert payload == {"schema_version": 1, "status": "REFUSED", "reason_code": "SCOPE_MISMATCH"}


async def test_requested_run_identity_cannot_be_replaced_by_another_journal(market_records):
    _, _, evidence, run, _ = market_records
    assert project(evidence, run, selected_run_id=uuid4()) == {
        "schema_version": 1, "status": "REFUSED", "reason_code": "SCOPE_MISMATCH",
    }


async def test_missing_qualification_retains_actual_gap_and_no_commercial_verdict(market_records):
    _, _, evidence, run, _ = market_records
    missing = replace(evidence, qualifications=())
    frame = frame_from_snapshot(missing)
    context = QualificationContext.build([s.observation_id for s in missing.signals], (), missing.outcomes,
                                         geo=missing.mission.geo_code, timeframe=missing.mission.timeframe)
    expected = assess_strategic_sufficiency(
        manifest=missing.manifest, brief=missing.brief, qualifications=(), probe_outcomes=missing.outcomes,
        assessment_state=context.assessment_state, current_frame_digest=frame.frame_digest,
        submitted_frame_digest=frame.frame_digest, observations=missing.signals, query_topics=missing.mission.keywords,
    ).gap_report.to_payload()
    actual = gate(project(missing, run))
    assert actual["claims"] == [] and actual["render_status"] == "WITHHELD"
    assert actual["gap_report"]["failed_gates"] == expected["failed_gates"]
    assert actual["gap_report"]["missing_evidence"] == expected["missing_evidence"]
    assert actual["gap_report"]["next_best_probe"] == expected["next_best_probe"]
    assert "commercial_recommendations" in actual["gap_report"]["withheld_outputs"]
