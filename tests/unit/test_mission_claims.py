"""Claim Ledger acceptance is current-frame, evidence-bound, and fail closed."""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.get_mission_claims import GetMissionClaimsUseCase
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    EvidenceDirection,
    EvidencePurpose,
    EvidenceQualification,
    MissionManifest,
    MissionOutputType,
    MissionProbeOutcome,
    QualificationReason,
    QualificationRelation,
    ResearchSurface,
    compute_frame_fingerprint,
    compute_query_fingerprint,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


NOW = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
BRIEF = {
    "decision": "Should a founder fund a retail operations MVP?",
    "target_user": "Independent Vietnamese retailers",
    "problem": "Manual inventory decisions create stockouts",
    "geo": "VN",
    "timeframe": "7d",
    "hypothesis": "Retailers will adopt an assistant that reduces stockouts",
    "falsifiers": ["Retailers report no material stockout cost"],
    "alternative_hypotheses": [
        "Retailers need process redesign rather than software",
        "Retailers prefer outsourced inventory services",
    ],
    "null_hypothesis": "Stockout assistance does not change retailer decisions",
    "kill_criteria": ["No repeated decision-relevant stockout pain appears"],
    "revision_rule": "Reframe when contradiction is at least as strong as support",
}


def _manifest():
    return MissionManifest(
        outcome="Decide whether to fund one bounded MVP",
        decision_context=BRIEF["decision"],
        required_channels=("google", "youtube"),
        optional_channels=(),
        authority_boundary=AuthorityBoundary(
            public_http=True,
            official_api=True,
            browser_session=False,
            paid_quota=False,
        ),
        quota_budget={},
        output_type=MissionOutputType.MARKET_ANALYSIS,
        stop_conditions=("one frame completed",),
        analysis_policy="evidence-gated-v1",
        retention_policy="test-only",
        created_by="unit-test",
        confirmed_at=NOW,
    )


async def _eligible_mission(tmp_path, *, contradiction=True):
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    await repository._ensure_schema()
    store = WorkspaceRepository(repository=repository)
    workspace_use_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / uuid4().hex
    host.mkdir()
    workspace = await workspace_use_case.confirm(
        await workspace_use_case.propose(host, "Claim controls"), confirmation=True
    )
    mission, brief = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["retail stockout"],
        manifest=_manifest(),
        **BRIEF,
    )
    definitions = [
        ("Demand evidence", PlatformType.GOOGLE_TRENDS, EvidencePurpose.DEMAND),
        ("Supply evidence one", PlatformType.YOUTUBE, EvidencePurpose.SUPPLY),
        ("Supply evidence two", PlatformType.YOUTUBE, EvidencePurpose.SUPPLY),
        ("Counterevidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
        ("Alternative two evidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
        ("Null evidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
    ]
    raw = []
    for index, (title, platform, _purpose) in enumerate(definitions):
        signal = TrendSignal(
            platform=platform,
            raw_title=title,
            metric_value=100 + index,
            source_url=f"https://example.com/evidence/{index}",
            geo_code=GeoCode.VN,
            captured_at=NOW,
            mission_id=mission.id,
            metadata={"keyword": "retail stockout", "connector_surface": "youtube"},
        )
        raw.append(signal)
    await repository.save_signals(raw)
    signals = await repository.get_mission_signals(mission.id)
    frame_fingerprint = compute_frame_fingerprint(mission, brief)
    qualifications = []
    purpose_by_title = {title: purpose for title, _platform, purpose in definitions}
    target_by_title = {
        "Counterevidence": "alternative:1",
        "Alternative two evidence": "alternative:2",
        "Null evidence": "null",
    }
    for signal in signals:
        purpose = purpose_by_title[signal.raw_title]
        is_contradiction = signal.raw_title in target_by_title and contradiction
        qualifications.append(
            EvidenceQualification(
                mission_id=mission.id,
                observation_id=signal.observation_id,
                brief_revision_id=brief.brief_revision_id,
                frame_fingerprint=frame_fingerprint,
                relation=(
                    QualificationRelation.QUALIFIED_CONTRADICTION
                    if is_contradiction
                    else QualificationRelation.QUALIFIED_SUPPORT
                ),
                purpose=purpose,
                confidence=0.85,
                reason_code=QualificationReason.DIRECT_TO_FRAME,
                judged_by="unit-test",
                hypothesis_target=target_by_title.get(signal.raw_title, "core"),
                evidence_role=(
                    EvidenceDirection.CONTRADICTION
                    if is_contradiction
                    else EvidenceDirection.SUPPORT
                ),
                evidence_contract_version=2,
            )
        )
    await store.save_evidence_qualifications(mission.id, qualifications)

    run_id = uuid4()
    await store.record_run_journal(
        RunJournal(
            run_id=run_id,
            mission_id=mission.id,
            workspace_id=workspace.workspace_id,
            journal_path=Path(f"/tmp/{run_id}.md"),
            sequence=1,
            status="COMPLETED",
            started_at=NOW,
            completed_at=NOW,
        )
    )
    outcomes = [
        MissionProbeOutcome(
            run_id=run_id,
            platform=surface,
            connector_surface=surface,
            status="HEALTHY",
            signals_collected=1,
            queried_keywords=("retail stockout",),
            queried_window="7d",
            query_fingerprint=compute_query_fingerprint(
                ("retail stockout",), GeoCode.VN, "7d"
            ),
            scope_attestation={"geo": "VN", "timeframe": "7d"},
            collection_plan_digest="p" * 64,
            completed_at=NOW,
        )
        for surface in ("google", "youtube")
    ]
    await store.record_probe_outcomes(run_id, outcomes)
    frame = await load_current_evidence_frame(repository, store, mission)
    return repository, store, mission, signals, frame


def _observation_candidate(signal, wording="Retailers report a material stockout problem."):
    return {
        "client_claim_key": "direct-observation",
        "claim_type": "OBSERVATION",
        "wording": wording,
        "confidence": 0.85,
        "evidence_bindings": [
            {
                "observation_id": str(signal.observation_id),
                "probe_outcome_id": None,
                "role": "SUPPORT",
                "hypothesis_target": "core",
            }
        ],
    }


def _signal_named(signals, title):
    return next(signal for signal in signals if signal.raw_title == title)


@pytest.mark.asyncio
async def test_claim_ledger_is_not_available_to_attention_missions():
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    await repository._ensure_schema()
    store = WorkspaceRepository(repository=repository)
    mission = ResearchMission(
        title="Explore retail attention",
        keywords=["retail"],
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository.create_mission(mission)

    result = await GetMissionClaimsUseCase(repository, store).execute(str(mission.id))

    assert result["status"] == "NOT_APPLICABLE"
    assert result["reason_code"] == "MARKET_MISSION_REQUIRED"
    assert result["render_status"] == "WITHHELD"
    await repository.close()


@pytest.mark.asyncio
async def test_a_sufficient_current_frame_permits_and_idempotently_replays_a_claim(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    use_case = SubmitMissionClaimsUseCase(repository, store)
    candidate = _observation_candidate(_signal_named(signals, "Demand evidence"))

    first = await use_case.execute(
        str(mission.id), frame.frame_digest, [candidate], created_by="host-agent"
    )
    replay = await use_case.execute(
        str(mission.id), frame.frame_digest, [candidate], created_by="host-agent"
    )

    assert first["analysis_status"] == "READY"
    assert first["permitted"] == 1 and first["withheld"] == 0
    assert replay["claims"][0]["claim_id"] == first["claims"][0]["claim_id"]
    await repository.close()


@pytest.mark.asyncio
async def test_conflicting_replay_and_stale_frame_refuse_the_whole_batch(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    use_case = SubmitMissionClaimsUseCase(repository, store)
    demand = _signal_named(signals, "Demand evidence")
    candidate = _observation_candidate(demand)
    await use_case.execute(
        str(mission.id), frame.frame_digest, [candidate], created_by="host-agent"
    )

    conflict = await use_case.execute(
        str(mission.id),
        frame.frame_digest,
        [_observation_candidate(demand, wording="Changed wording")],
        created_by="host-agent",
    )
    stale = await use_case.execute(
        str(mission.id), "s" * 64, [candidate], created_by="host-agent"
    )

    assert conflict["status"] == "INVALID"
    assert conflict["reason_code"] == "INVALID_CLAIM_BATCH"
    assert stale["status"] == "CONFLICT" and stale["reason_code"] == "STALE_FRAME"
    assert len(await store.list_mission_claims(mission.id, include_superseded=True)) == 1
    await repository.close()


@pytest.mark.asyncio
async def test_all_confirmatory_evidence_persists_the_candidate_as_withheld(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(
        tmp_path, contradiction=False
    )
    result = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_observation_candidate(_signal_named(signals, "Demand evidence"))],
        created_by="host-agent",
    )

    assert result["analysis_status"] == "INSUFFICIENT_EVIDENCE"
    assert result["permitted"] == 0 and result["withheld"] == 1
    assert "MISSING_CONTRADICTION_COVERAGE" in result["claims"][0]["withheld_reasons"]
    await repository.close()


@pytest.mark.asyncio
async def test_an_unbound_assumption_cannot_become_a_strategic_claim(tmp_path):
    repository, store, mission, _signals, frame = await _eligible_mission(tmp_path)

    result = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [{
            "client_claim_key": "unbound-assumption",
            "claim_type": "ASSUMPTION",
            "wording": "Retailers may value proactive inventory recommendations.",
        }],
        created_by="host-agent",
    )

    assert result["status"] == "INVALID"
    assert result["reason_code"] == "INVALID_CLAIM_BATCH"
    assert "ASSUMPTION requires at least one current evidence binding" in result["error"]
    assert await store.list_mission_claims(mission.id, include_superseded=True) == []
    await repository.close()


@pytest.mark.asyncio
async def test_measurement_without_its_own_metric_basis_is_persisted_withheld(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    demand = _signal_named(signals, "Demand evidence")
    candidate = {
        **_observation_candidate(demand),
        "client_claim_key": "conversion-rate",
        "claim_type": "MEASUREMENT",
        "wording": "Observed conversion rate is 12 percent.",
        "inference_method": "ratio-v1",
    }

    missing = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id), frame.frame_digest, [candidate], created_by="host-agent"
    )

    assert missing["status"] == "RECORDED"
    assert missing["permitted"] == 0 and missing["withheld"] == 1
    assert set(missing["claims"][0]["withheld_reasons"]) >= {
        "MISSING_METRIC_DENOMINATOR:conversion-rate",
        "MISSING_METRIC_TIMEFRAME:conversion-rate",
    }
    assert missing["claims"][0]["metric_denominator"] is None
    assert missing["claims"][0]["metric_timeframe"] is None

    complete = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [{
            **candidate,
            "client_claim_key": "conversion-rate-with-basis",
            "metric_denominator": "qualified purchase-intent observations",
            "metric_timeframe": "7d",
        }],
        created_by="host-agent",
    )
    assert complete["analysis_status"] == "READY"
    assert complete["claims"][0]["metric_denominator"] == (
        "qualified purchase-intent observations"
    )
    assert complete["claims"][0]["metric_timeframe"] == "7d"
    await repository.close()


@pytest.mark.asyncio
async def test_a_new_frame_supersedes_old_claims_for_current_rendering(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_observation_candidate(_signal_named(signals, "Demand evidence"))],
        created_by="host-agent",
    )
    extra = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="New unassessed evidence",
        source_url="https://example.com/evidence/new",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        mission_id=mission.id,
    )
    await repository.save_signals([extra])

    ledger = await GetMissionClaimsUseCase(repository, store).execute(
        str(mission.id), include_superseded=True
    )

    assert ledger["render_status"] == "WITHHELD"
    assert ledger["counts"] == {"permitted": 0, "withheld": 0, "superseded": 1}
    assert ledger["claims"][0]["status"] == "SUPERSEDED"
    await repository.close()


@pytest.mark.asyncio
async def test_analysis_omits_every_forbidden_verdict_until_a_claim_is_permitted(tmp_path):
    repository, store, mission, signals, frame = await _eligible_mission(tmp_path)
    analysis = GetMissionAnalysisUseCase(repository, store)

    before = await analysis.execute(mission.id)
    assert before["analysis_status"] == "INSUFFICIENT_EVIDENCE"
    assert before["gap_report"]["failed_gates"] == ["NO_PERMITTED_CLAIMS"]
    for forbidden in before["gap_report"]["withheld_outputs"]:
        assert forbidden not in before

    await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_observation_candidate(_signal_named(signals, "Demand evidence"))],
        created_by="host-agent",
    )
    after = await analysis.execute(mission.id)

    assert after["analysis_status"] == "READY"
    assert [claim["wording"] for claim in after["claim_ledger"]["OBSERVATION"]] == [
        "Retailers report a material stockout problem."
    ]
    assert {item["hypothesis_target"] for item in after["contradictory_evidence"]} == {
        "alternative:1", "alternative:2", "null"
    }
    assert "market_opportunities" not in after
    await repository.close()
