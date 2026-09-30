"""End-to-end Market verdict controls through both persistence backends."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.domain.entities import TrendSignal
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
    compute_frame_fingerprint,
    compute_query_fingerprint,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.domain.harness_models import QualityScorecard
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)
BRIEF = {
    "decision": "Should the founder fund a retail operations MVP?",
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
        created_by="integration-test",
        confirmed_at=NOW,
    )


async def _mission_case(repository, tmp_path, condition):
    store = WorkspaceRepository(repository=repository)
    workspace_use_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / f"case-{condition}-{uuid4().hex}"
    host.mkdir()
    workspace = await workspace_use_case.confirm(
        await workspace_use_case.propose(host, f"Market {condition}"), confirmation=True
    )
    mission, brief = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["retail stockout"],
        manifest=_manifest(),
        **BRIEF,
    )
    definitions = [
        ("Demand", PlatformType.GOOGLE_TRENDS, EvidencePurpose.DEMAND),
        ("Supply one", PlatformType.YOUTUBE, EvidencePurpose.SUPPLY),
        ("Supply two", PlatformType.YOUTUBE, EvidencePurpose.SUPPLY),
        ("Counterevidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
        ("Alternative two evidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
        ("Null evidence", PlatformType.YOUTUBE, EvidencePurpose.VOC),
    ]
    for index, (title, platform, _purpose) in enumerate(definitions):
        await repository.save_signals([
            TrendSignal(
                platform=platform,
                raw_title=title,
                metric_value=100 + index,
                source_url=f"https://example.com/{condition}/{index}",
                geo_code=GeoCode.VN,
                captured_at=NOW,
                mission_id=mission.id,
                metadata={"keyword": "retail stockout", "connector_surface": "youtube"},
            )
        ])
    signals = await repository.get_mission_signals(mission.id)
    purpose_by_title = {title: purpose for title, _platform, purpose in definitions}
    target_by_title = {
        "Counterevidence": "alternative:1",
        "Alternative two evidence": "alternative:2",
        "Null evidence": "null",
    }
    frame_fingerprint = compute_frame_fingerprint(mission, brief)
    qualifications = []
    for signal in signals:
        if condition == "low_relevance":
            relation = QualificationRelation.EXCLUDED_IRRELEVANT
            role = EvidenceDirection.CONTEXT
            purpose = EvidencePurpose.CONTEXT
            target = "neutral"
            reason = QualificationReason.WRONG_AUDIENCE_OR_PROBLEM
        else:
            is_contradiction = (
                signal.raw_title in target_by_title and condition != "all_confirmatory"
            )
            relation = (
                QualificationRelation.QUALIFIED_CONTRADICTION
                if is_contradiction
                else QualificationRelation.QUALIFIED_SUPPORT
            )
            role = EvidenceDirection.CONTRADICTION if is_contradiction else EvidenceDirection.SUPPORT
            purpose = purpose_by_title[signal.raw_title]
            target = target_by_title.get(signal.raw_title, "core")
            reason = QualificationReason.DIRECT_TO_FRAME
        qualifications.append(
            EvidenceQualification(
                mission_id=mission.id,
                observation_id=signal.observation_id,
                brief_revision_id=brief.brief_revision_id,
                frame_fingerprint=frame_fingerprint,
                relation=relation,
                purpose=purpose,
                confidence=0.85,
                reason_code=reason,
                judged_by="integration-test",
                hypothesis_target=target,
                evidence_role=role,
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
    outcomes = []
    for surface in ("google", "youtube"):
        status = "AUTH_REQUIRED" if condition == "auth_blocked" and surface == "youtube" else "HEALTHY"
        outcomes.append(
            MissionProbeOutcome(
                run_id=run_id,
                platform=surface,
                connector_surface=surface,
                status=status,
                signals_collected=1 if status == "HEALTHY" else 0,
                queried_keywords=("retail stockout",),
                queried_window="7d",
                query_fingerprint=compute_query_fingerprint(
                    ("retail stockout",), GeoCode.VN, "7d"
                ),
                scope_attestation=(
                    {"geo": "VN", "timeframe": "7d"} if status == "HEALTHY" else None
                ),
                note="Authorized access was unavailable." if status == "AUTH_REQUIRED" else None,
                collection_plan_digest="p" * 64,
                completed_at=NOW,
            )
        )
    await store.record_probe_outcomes(run_id, outcomes)
    return store, mission, signals, await load_current_evidence_frame(repository, store, mission)


def _candidate(condition, signals):
    if condition == "low_relevance":
        return {
            "client_claim_key": "candidate",
            "claim_type": "UNKNOWN",
            "wording": "The market may still be relevant.",
        }
    demand = next(signal for signal in signals if signal.raw_title == "Demand")
    candidate = {
        "client_claim_key": "candidate",
        "claim_type": "MEASUREMENT" if condition == "missing_metric" else "OBSERVATION",
        "wording": "Retailers report a material stockout problem.",
        "confidence": 0.85,
        "evidence_bindings": [{
            "observation_id": str(demand.observation_id),
            "probe_outcome_id": None,
            "role": "SUPPORT",
            "hypothesis_target": "core",
        }],
    }
    if condition == "missing_metric":
        candidate["inference_method"] = "conversion-ratio-v1"
    return candidate


@pytest.mark.parametrize(
    "condition, expected_status, expected_gate",
    [
        ("sufficient", "READY", None),
        ("auth_blocked", "INSUFFICIENT_EVIDENCE", "REQUIRED_CHANNEL_NOT_MEASURED:youtube:AUTH_REQUIRED"),
        ("low_relevance", "INSUFFICIENT_EVIDENCE", "MISSING_SUPPORT_COVERAGE"),
        ("contradictory", "READY", None),
        ("all_confirmatory", "INSUFFICIENT_EVIDENCE", "MISSING_CONTRADICTION_COVERAGE"),
        ("missing_metric", "INSUFFICIENT_EVIDENCE", "MISSING_METRIC_DENOMINATOR:candidate"),
    ],
)
@pytest.mark.asyncio
async def test_market_mission_verdict_controls_across_backends(
    repository_case, tmp_path, monkeypatch, condition, expected_status, expected_gate
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, mission, signals, frame = await _mission_case(repository, tmp_path, condition)
    submission = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_candidate(condition, signals)],
        created_by="integration-host",
    )
    analysis_use_case = GetMissionAnalysisUseCase(repository, store)

    async def _skip_lexicon_sync(_components):
        return None

    monkeypatch.setattr(mcp_server, "_sync_lexicons_from_db", _skip_lexicon_sync)
    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "repository": repository,
            "workspace_store": store,
            "get_mission_analysis_use_case": analysis_use_case,
        },
    )
    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))

    assert submission["analysis_status"] == expected_status
    assert analysis["analysis_status"] == expected_status
    if expected_gate is None:
        assert analysis["claim_ledger"]
        assert analysis["retention_policy"] == "test-only"
        assert analysis["redaction_policy"] == "credentials-and-personal-data-redacted"
        assert analysis["platform_policy"] == "authorized-surface-terms-apply"
        assert "requalifies" in analysis["reuse_limit"]
        if condition == "contradictory":
            assert analysis["contradictory_evidence"]
    else:
        assert expected_gate in analysis["gap_report"]["failed_gates"]
        for forbidden in analysis["gap_report"]["withheld_outputs"]:
            assert forbidden not in analysis


@pytest.mark.asyncio
async def test_ready_artifact_returns_and_renders_evidence_policy(
    repository_case, tmp_path, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, mission, signals, frame = await _mission_case(
        repository, tmp_path, "sufficient"
    )
    await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_candidate("sufficient", signals)],
        created_by="integration-host",
    )

    class _TopClusters:
        async def execute(self, **_kwargs):
            return []

    class _Quality:
        def evaluate_quality(self, *_args, **_kwargs):
            return QualityScorecard()

    async def _skip_lexicon_sync(_components):
        return None

    monkeypatch.setattr(mcp_server, "_sync_lexicons_from_db", _skip_lexicon_sync)
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: tmp_path)
    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "repository": repository,
            "workspace_store": store,
            "get_mission_analysis_use_case": GetMissionAnalysisUseCase(repository, store),
            "top_clusters_use_case": _TopClusters(),
            "quality_evaluator": _Quality(),
            "artifact_builder": HtmlArtifactBuilder(),
        },
    )

    artifact = json.loads(await mcp_server.handle_generate_mission_artifact(str(mission.id)))
    rendered = Path(artifact["artifact_file"]).read_text(encoding="utf-8")

    assert artifact["analysis_status"] == "READY"
    assert artifact["template_revision"] == "mission-report/evidence-grounded-v1"
    assert artifact["retention_policy"] == "test-only"
    assert artifact["redaction_policy"] == "credentials-and-personal-data-redacted"
    assert artifact["platform_policy"] == "authorized-surface-terms-apply"
    assert "requalifies" in artifact["reuse_limit"]
    for value in (
        artifact["template_revision"],
        artifact["retention_policy"],
        artifact["redaction_policy"],
        artifact["platform_policy"],
        artifact["reuse_limit"],
    ):
        assert value in rendered


@pytest.mark.asyncio
async def test_every_public_market_boundary_fails_closed_without_a_persisted_contract(
    repository_case, tmp_path, monkeypatch
):
    from ignis.interfaces.mcp import server as mcp_server

    repository = repository_case.repository
    store, mission, _signals, _frame = await _mission_case(
        repository, tmp_path, "sufficient"
    )

    class _TopClusters:
        async def execute(self, **_kwargs):
            return []

    class _Quality:
        def evaluate_quality(self, *_args, **_kwargs):
            return QualityScorecard()

    class _ForbiddenReasoner:
        def analyze_mission(self, **_kwargs):
            raise AssertionError("Market boundary reached the legacy strategic reasoner")

    async def _skip_lexicon_sync(_components):
        return None

    monkeypatch.setattr(mcp_server, "_sync_lexicons_from_db", _skip_lexicon_sync)
    monkeypatch.setattr(mcp_server, "_get_secure_reports_dir", lambda: tmp_path)
    monkeypatch.setattr(
        mcp_server,
        "get_components",
        lambda: {
            "repository": repository,
            "workspace_store": store,
            "get_mission_analysis_use_case": GetMissionAnalysisUseCase(repository),
            "top_clusters_use_case": _TopClusters(),
            "quality_evaluator": _Quality(),
            "strategic_reasoner": _ForbiddenReasoner(),
            "artifact_builder": HtmlArtifactBuilder(),
        },
    )

    analysis = json.loads(await mcp_server.handle_get_mission_analysis(str(mission.id)))
    discovery = json.loads(
        await mcp_server.handle_discover_market_opportunities(str(mission.id))
    )
    artifact = json.loads(await mcp_server.handle_generate_mission_artifact(str(mission.id)))

    for result in (analysis, discovery, artifact):
        assert result["analysis_status"] == "INSUFFICIENT_EVIDENCE"
        assert result["gap_report"]["failed_gates"] == [
            "PERSISTED_ANALYSIS_CONTRACT_UNAVAILABLE"
        ]
        assert "market_opportunities" not in result
    rendered = Path(artifact["artifact_file"]).read_text(encoding="utf-8")
    assert "Evidence contract is not sufficient" in rendered
    assert "White Space Opportunity Matrix" not in rendered
