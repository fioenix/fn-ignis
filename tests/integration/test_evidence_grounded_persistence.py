"""Dual-backend contracts for mission authority, frames, claims, and bindings."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.get_evidence_qualification_batch import (
    GetEvidenceQualificationBatchUseCase,
)
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    ClaimStatus,
    ClaimType,
    EvidenceDirection,
    EvidencePurpose,
    EvidenceQualification,
    InvalidEvidenceQualificationError,
    InvalidMissionClaimError,
    InvalidMissionManifestError,
    MarketBriefRevision,
    MissionClaim,
    MissionClaimEvidence,
    MissionManifest,
    MissionOutputType,
    MissionProbeOutcome,
    QualificationReason,
    QualificationRelation,
    ResearchSurface,
    compute_frame_fingerprint,
    compute_query_fingerprint,
)
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)


async def _mission(repository, tmp_path, **manifest_overrides):
    root = tmp_path / "host"
    root.mkdir()
    store = WorkspaceRepository(repository=repository)
    workspace_use_case = CreateResearchWorkspaceUseCase(store=store)
    proposal = await workspace_use_case.propose(root, "Evidence controls")
    workspace = await workspace_use_case.confirm(proposal, confirmation=True)
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Collect customer friction",
        keywords=["retail setup friction"],
        manifest=replace(_manifest(None), **manifest_overrides),
    )
    return store, workspace, mission


def _manifest(mission_id):
    return MissionManifest(
        mission_id=mission_id,
        outcome="Collect an auditable evidence frame",
        decision_context=None,
        required_channels=("youtube",),
        optional_channels=(),
        authority_boundary=AuthorityBoundary(
            public_http=True,
            official_api=False,
            browser_session=False,
            paid_quota=False,
        ),
        quota_budget={"youtube_search_calls": 5},
        output_type=MissionOutputType.COLLECTION_FRAME,
        stop_conditions=("frame complete", "new authority required"),
        analysis_policy="evidence-gated-v1",
        retention_policy="mission-only",
        created_by="contract-test",
        confirmed_at=NOW,
    )


def _database_value(repository_case, query: str, params=()):
    if repository_case.name == "sqlite":
        import sqlite3

        with sqlite3.connect(repository_case.repository._db_path) as conn:
            return conn.execute(query.replace("%s", "?"), params).fetchone()[0]

    import psycopg

    with psycopg.connect(repository_case.dsn) as conn:
        return conn.execute(query, params).fetchone()[0]


async def _qualify_observation(store, mission_id, observation_id, frame_digest):
    qualification = EvidenceQualification(
        mission_id=mission_id,
        observation_id=observation_id,
        frame_fingerprint=frame_digest,
        relation=QualificationRelation.QUALIFIED_SUPPORT,
        purpose=EvidencePurpose.VOC,
        confidence=0.9,
        reason_code=QualificationReason.DIRECT_TO_FRAME,
        judged_by="contract-test",
        hypothesis_target="core",
        evidence_role=EvidenceDirection.SUPPORT,
    )
    await store.save_evidence_qualifications(mission_id, [qualification])


@pytest.mark.asyncio
async def test_prior_mission_observation_needs_current_association_and_requalification(
    repository_case, tmp_path
):
    repository = repository_case.repository
    store, workspace, first = await _mission(repository, tmp_path)
    second = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Reassess the same source",
        keywords=["retail setup friction"],
        manifest=_manifest(None),
    )
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="A source observed in the first mission",
        metric_value=12,
        source_url="https://youtube.example/watch?v=shared-observation",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        mission_id=first.id,
        metadata={"connector_surface": "youtube"},
    )
    await repository.save_signals([signal])
    first_frame = compute_frame_fingerprint(first, None)
    await _qualify_observation(store, first.id, signal.observation_id, first_frame)
    reader = GetEvidenceQualificationBatchUseCase(repository, store)

    before_association = await reader.execute(str(second.id))
    assert before_association["evidence"] == []
    assert await store.list_evidence_qualifications(second.id) == []

    await repository.attach_mission_evidence(second.id, [signal])
    after_association = await reader.execute(str(second.id))
    assert [item["observation_id"] for item in after_association["evidence"]] == [
        str(signal.observation_id)
    ]
    assert after_association["progress"]["unassessed"] == 1
    assert after_association["frame_fingerprint"] != first_frame
    assert await store.list_evidence_qualifications(second.id) == []

    await _qualify_observation(
        store,
        second.id,
        signal.observation_id,
        after_association["frame_fingerprint"],
    )
    assert len(await store.list_evidence_qualifications(first.id)) == 1
    assert len(await store.list_evidence_qualifications(second.id)) == 1


def _delete_mission(repository_case, mission_id):
    if repository_case.name == "sqlite":
        import sqlite3

        with sqlite3.connect(repository_case.repository._db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("DELETE FROM research_missions WHERE id = ?", (str(mission_id),))
        return

    import psycopg

    with psycopg.connect(repository_case.dsn) as conn:
        conn.execute("DELETE FROM research_missions WHERE id = %s", (str(mission_id),))


async def _completed_outcome(
    store, workspace, mission, *, status, surface, signals=0, sequence=1, completed_at=NOW
):
    run_id = uuid4()
    await store.record_run_journal(
        RunJournal(
            run_id=run_id,
            mission_id=mission.id,
            workspace_id=workspace.workspace_id,
            journal_path=Path(f"/tmp/{run_id}.md"),
            sequence=sequence,
            status="COMPLETED",
            started_at=completed_at,
            completed_at=completed_at,
        )
    )
    outcome = MissionProbeOutcome(
        run_id=run_id,
        platform=surface.split(".", 1)[0],
        connector_surface=surface,
        status=status,
        signals_collected=signals,
        queried_keywords=("retail setup friction",),
        queried_window="30d",
        query_fingerprint=compute_query_fingerprint(
            ("retail setup friction",), GeoCode.VN, "30d"
        ),
        scope_attestation={"geo": "VN", "timeframe": "30d"},
        note=(
            "No qualifying observations were returned for the attested scope."
            if status is ChannelHealthStatus.EMPTY_NO_DATA
            else "measurement unavailable"
            if status is not ChannelHealthStatus.HEALTHY
            else None
        ),
        collection_plan_digest="p" * 64,
        completed_at=completed_at,
    )
    await store.record_probe_outcomes(run_id, [outcome])
    return run_id


@pytest.mark.asyncio
async def test_manifest_round_trips_exactly_and_replay_is_idempotent(repository_case, tmp_path):
    store, _workspace, mission = await _mission(
        repository_case.repository, tmp_path, optional_channels=("threads",)
    )
    manifest = replace(_manifest(mission.id), optional_channels=("threads",))

    first = await store.save_mission_manifest(manifest)
    replay = await store.save_mission_manifest(manifest)
    stored = await store.get_mission_manifest(mission.id)

    assert first.manifest_digest == replay.manifest_digest == stored.manifest_digest
    assert stored.to_payload() == manifest.to_payload()

    with pytest.raises(InvalidMissionManifestError):
        await store.save_mission_manifest(replace(manifest, outcome="A different outcome"))


@pytest.mark.asyncio
async def test_manifest_declared_channels_require_one_complete_outcome_set(
    repository_case, tmp_path
):
    store, workspace, mission = await _mission(
        repository_case.repository, tmp_path, required_channels=("youtube", "threads")
    )
    await store.save_mission_manifest(
        replace(_manifest(mission.id), required_channels=("youtube", "threads"))
    )
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
    youtube_only = MissionProbeOutcome(
        run_id=run_id,
        platform="youtube",
        connector_surface="youtube",
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        signals_collected=0,
        queried_keywords=("retail setup friction",),
        queried_window="30d",
        query_fingerprint="f" * 64,
        scope_attestation={"geo": "VN", "timeframe": "30d"},
        note="No qualifying observations were returned for the attested scope.",
        collection_plan_digest="p" * 64,
        completed_at=NOW,
    )

    with pytest.raises(InvalidEvidenceQualificationError, match="declared channels"):
        await store.record_probe_outcomes(run_id, [])
    with pytest.raises(InvalidEvidenceQualificationError, match="declared channels"):
        await store.record_probe_outcomes(run_id, [youtube_only])

    assert await store.get_latest_completed_probe_outcomes(mission.id) == []


@pytest.mark.asyncio
async def test_manifested_run_refuses_legacy_outcomes_without_one_plan_identity(
    repository_case, tmp_path
):
    store, workspace, mission = await _mission(repository_case.repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
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
    legacy_outcome = MissionProbeOutcome(
        run_id=run_id,
        platform="youtube",
        connector_surface="youtube",
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        signals_collected=0,
        queried_keywords=("retail setup friction",),
        queried_window="30d",
        query_fingerprint="f" * 64,
        completed_at=NOW,
    )

    with pytest.raises(InvalidEvidenceQualificationError, match="collection_plan_digest"):
        await store.record_probe_outcomes(run_id, [legacy_outcome])

    assert await store.get_latest_completed_probe_outcomes(mission.id) == []


@pytest.mark.asyncio
async def test_claim_binding_round_trips_and_old_frames_become_superseded(repository_case, tmp_path):
    repository = repository_case.repository
    store, _workspace, mission = await _mission(repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Retail setup remains manual",
        source_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"external_id": "dQw4w9WgXcQ"},
    )
    signal.mission_id = mission.id
    await repository.save_signals([signal])
    held = await repository.get_mission_signals(mission.id)
    await _qualify_observation(store, mission.id, held[0].observation_id, "a" * 64)

    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="claim-1",
        claim_type=ClaimType.OBSERVATION,
        wording="One collected source describes manual setup friction.",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    binding = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=held[0].observation_id,
        probe_outcome_id=None,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )
    claim = MissionClaim(
        mission_id=claim.mission_id,
        frame_digest=claim.frame_digest,
        client_claim_key=claim.client_claim_key,
        claim_type=claim.claim_type,
        wording=claim.wording,
        status=claim.status,
        created_by=claim.created_by,
        claim_id=claim.claim_id,
        evidence_bindings=(binding,),
    )

    first = await store.save_mission_claims(mission.id, claim.frame_digest, [claim])
    replay_claim_id = uuid4()
    replay_binding = replace(binding, binding_id=uuid4(), claim_id=replay_claim_id)
    replay_claim = replace(
        claim,
        claim_id=replay_claim_id,
        created_at=datetime(2026, 9, 30, 10, 5, tzinfo=timezone.utc),
        evidence_bindings=(replay_binding,),
    )
    replay = await store.save_mission_claims(
        mission.id, claim.frame_digest, [replay_claim]
    )
    superseded = await store.supersede_mission_claims(mission.id, "b" * 64)
    current = await store.list_mission_claims(mission.id)
    history = await store.list_mission_claims(mission.id, include_superseded=True)

    assert [item.claim_id for item in first] == [item.claim_id for item in replay]
    assert superseded == 1
    assert current == []
    assert len(history) == 1 and history[0].status is ClaimStatus.SUPERSEDED
    assert history[0].evidence_bindings[0].observation_id == held[0].observation_id

    conflicting = replace(claim, wording="A changed payload using the same caller key.")
    with pytest.raises(InvalidMissionClaimError):
        await store.save_mission_claims(mission.id, claim.frame_digest, [conflicting])


@pytest.mark.asyncio
async def test_claim_binding_requires_a_compatible_persisted_qualification(
    repository_case, tmp_path
):
    repository = repository_case.repository
    store, _workspace, mission = await _mission(repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Evidence that contradicts the core hypothesis",
        source_url="https://youtube.com/watch?v=contra12345",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"external_id": "contra12345"},
    )
    signal.mission_id = mission.id
    await repository.save_signals([signal])
    observation_id = (await repository.get_mission_signals(mission.id))[0].observation_id
    await store.save_evidence_qualifications(
        mission.id,
        [
            EvidenceQualification(
                mission_id=mission.id,
                observation_id=observation_id,
                frame_fingerprint="a" * 64,
                relation=QualificationRelation.QUALIFIED_CONTRADICTION,
                purpose=EvidencePurpose.VOC,
                confidence=0.9,
                reason_code=QualificationReason.DIRECT_TO_FRAME,
                judged_by="contract-test",
                hypothesis_target="core",
                evidence_role=EvidenceDirection.CONTRADICTION,
            )
        ],
    )
    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="wrong-role",
        claim_type=ClaimType.OBSERVATION,
        wording="This must not be recorded as support.",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    wrong_role = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=observation_id,
        probe_outcome_id=None,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )

    with pytest.raises(InvalidMissionClaimError, match="binding contract"):
        await store.save_mission_claims(
            mission.id,
            claim.frame_digest,
            [replace(claim, evidence_bindings=(wrong_role,))],
        )

    excluded_signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Keyword-only adjacent content",
        source_url="https://youtube.com/watch?v=exclude1234",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"external_id": "exclude1234"},
    )
    excluded_signal.mission_id = mission.id
    await repository.save_signals([excluded_signal])
    excluded_id = next(
        item.observation_id
        for item in await repository.get_mission_signals(mission.id)
        if item.raw_title == excluded_signal.raw_title
    )
    await store.save_evidence_qualifications(
        mission.id,
        [
            EvidenceQualification(
                mission_id=mission.id,
                observation_id=excluded_id,
                frame_fingerprint="a" * 64,
                relation=QualificationRelation.EXCLUDED_IRRELEVANT,
                purpose=EvidencePurpose.CONTEXT,
                confidence=0.9,
                reason_code=QualificationReason.KEYWORD_ONLY,
                judged_by="contract-test",
                evidence_role=EvidenceDirection.CONTEXT,
            )
        ],
    )
    context_claim = replace(claim, claim_id=uuid4(), client_claim_key="excluded-context")
    excluded_context = MissionClaimEvidence(
        claim_id=context_claim.claim_id,
        observation_id=excluded_id,
        probe_outcome_id=None,
        role=EvidenceDirection.CONTEXT,
        hypothesis_target=None,
    )

    with pytest.raises(InvalidMissionClaimError, match="binding contract"):
        await store.save_mission_claims(
            mission.id,
            context_claim.frame_digest,
            [replace(context_claim, evidence_bindings=(excluded_context,))],
        )


@pytest.mark.asyncio
async def test_claim_replay_returns_the_requested_frame_when_client_key_is_reused(
    repository_case, tmp_path
):
    store, _workspace, mission = await _mission(repository_case.repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    frame_a = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="reused-key",
        claim_type=ClaimType.ASSUMPTION,
        wording="Frame A assumption.",
        status=ClaimStatus.WITHHELD,
        withheld_reasons=("NO_EVIDENCE",),
        created_by="contract-test",
    )
    frame_b = replace(
        frame_a,
        claim_id=uuid4(),
        frame_digest="b" * 64,
        wording="Frame B assumption.",
        created_at=datetime(2026, 9, 30, 10, 5, tzinfo=timezone.utc),
    )
    await store.save_mission_claims(mission.id, frame_a.frame_digest, [frame_a])
    current = await store.save_mission_claims(mission.id, frame_b.frame_digest, [frame_b])

    assert current[0].claim_id == frame_b.claim_id
    assert current[0].wording == "Frame B assumption."
    replay = await store.save_mission_claims(mission.id, frame_a.frame_digest, [frame_a])
    assert replay[0].claim_id == frame_a.claim_id
    assert replay[0].wording == "Frame A assumption."


@pytest.mark.asyncio
async def test_legacy_brief_remains_readable_without_fabricated_hypotheses(
    repository_case, tmp_path
):
    root = tmp_path / "legacy-host"
    root.mkdir()
    store = WorkspaceRepository(repository=repository_case.repository)
    workspace_use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await workspace_use_case.confirm(
        await workspace_use_case.propose(root, "Legacy brief"), confirmation=True
    )
    mission = ResearchMission(
        title="Legacy market mission",
        keywords=["legacy"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.MARKET.value,
    )
    brief = MarketBriefRevision(
        workspace_id=workspace.workspace_id,
        mission_id=mission.id,
        decision="Decide whether to continue",
        target_user="Operators",
        problem="Manual setup",
        geo="VN",
        timeframe="30d",
        hypothesis="Setup friction is material",
        falsifiers=("No repeated friction",),
        confirmed_by="owner",
    )

    _mission_row, stored = await store.create_market_mission_with_brief(mission, brief)
    reopened = await store.get_brief_revision_for_mission(mission.id)

    assert stored.evidence_contract_version == 1
    assert reopened is not None
    assert reopened.alternative_hypotheses is None
    assert reopened.null_hypothesis is None
    assert reopened.kill_criteria is None
    assert reopened.revision_rule is None


@pytest.mark.asyncio
async def test_manifest_mission_delete_cascades_new_control_plane_rows(repository_case, tmp_path):
    store, _workspace, mission = await _mission(repository_case.repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="cascade",
        claim_type=ClaimType.ASSUMPTION,
        wording="A candidate assumption.",
        status=ClaimStatus.WITHHELD,
        withheld_reasons=("NO_EVIDENCE",),
        created_by="contract-test",
    )
    await store.save_mission_claims(mission.id, claim.frame_digest, [claim])

    _delete_mission(repository_case, mission.id)

    assert _database_value(
        repository_case,
        "SELECT count(*) FROM mission_manifests WHERE mission_id = %s",
        (str(mission.id),),
    ) == 0
    assert _database_value(
        repository_case,
        "SELECT count(*) FROM mission_claims WHERE mission_id = %s",
        (str(mission.id),),
    ) == 0


@pytest.mark.asyncio
async def test_claim_refuses_foreign_observation_and_nonempty_probe_outcome(
    repository_case, tmp_path
):
    repository = repository_case.repository
    store, workspace, mission = await _mission(repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))

    foreign = ResearchMission(
        title="Foreign mission",
        keywords=["foreign"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository.save_mission(foreign)
    foreign_signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Foreign evidence",
        source_url="https://youtube.com/watch?v=foreign12345",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"external_id": "foreign12345"},
    )
    foreign_signal.mission_id = foreign.id
    await repository.save_signals([foreign_signal])
    foreign_observation = (await repository.get_mission_signals(foreign.id))[0].observation_id

    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="foreign-observation",
        claim_type=ClaimType.OBSERVATION,
        wording="Foreign evidence must not cross mission boundaries.",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    foreign_binding = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=foreign_observation,
        probe_outcome_id=None,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )
    with pytest.raises(InvalidMissionClaimError):
        await store.save_mission_claims(
            mission.id,
            claim.frame_digest,
            [replace(claim, evidence_bindings=(foreign_binding,))],
        )

    healthy_run = await _completed_outcome(
        store,
        workspace,
        mission,
        status=ChannelHealthStatus.HEALTHY,
        surface="youtube",
        signals=1,
    )
    outcome_id = _database_value(
        repository_case,
        "SELECT id FROM mission_probe_outcomes WHERE run_id = %s",
        (str(healthy_run),),
    )
    measured_claim = replace(claim, client_claim_key="nonempty-outcome")
    outcome_binding = MissionClaimEvidence(
        claim_id=measured_claim.claim_id,
        observation_id=None,
        probe_outcome_id=outcome_id,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )
    with pytest.raises(InvalidMissionClaimError):
        await store.save_mission_claims(
            mission.id,
            measured_claim.frame_digest,
            [replace(measured_claim, evidence_bindings=(outcome_binding,))],
        )


@pytest.mark.asyncio
async def test_exact_empty_outcome_can_bind_measured_absence_for_its_mission(
    repository_case, tmp_path
):
    store, workspace, mission = await _mission(repository_case.repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    run_id = await _completed_outcome(
        store,
        workspace,
        mission,
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        surface="youtube",
    )
    outcome = (await store.get_latest_completed_probe_outcomes(mission.id))[0]
    assert outcome.measured_zero_for("retail setup friction", GeoCode.VN, "30d")
    outcome_id = _database_value(
        repository_case,
        "SELECT id FROM mission_probe_outcomes WHERE run_id = %s",
        (str(run_id),),
    )
    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="measured-absence",
        claim_type=ClaimType.MEASUREMENT,
        wording="The declared query returned no qualifying observations.",
        inference_method="exact-empty-v1",
        metric_denominator="all qualifying observations returned by the declared query",
        metric_timeframe="30d",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    binding = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=None,
        probe_outcome_id=outcome_id,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )

    saved = await store.save_mission_claims(
        mission.id, claim.frame_digest, [replace(claim, evidence_bindings=(binding,))]
    )

    assert str(saved[0].evidence_bindings[0].probe_outcome_id) == str(outcome_id)


@pytest.mark.asyncio
async def test_an_empty_outcome_from_a_superseded_collection_run_cannot_bind(
    repository_case, tmp_path
):
    store, workspace, mission = await _mission(repository_case.repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    old_run = await _completed_outcome(
        store,
        workspace,
        mission,
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        surface="youtube",
        sequence=1,
        completed_at=NOW,
    )
    await _completed_outcome(
        store,
        workspace,
        mission,
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        surface="youtube",
        sequence=2,
        completed_at=NOW + timedelta(minutes=1),
    )
    old_outcome_id = _database_value(
        repository_case,
        "SELECT id FROM mission_probe_outcomes WHERE run_id = %s",
        (str(old_run),),
    )
    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="stale-measured-absence",
        claim_type=ClaimType.MEASUREMENT,
        wording="An old measured absence must not bind to the current collection frame.",
        inference_method="exact-empty-v1",
        metric_denominator="all qualifying observations returned by the declared query",
        metric_timeframe="30d",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    binding = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=None,
        probe_outcome_id=old_outcome_id,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )

    with pytest.raises(InvalidMissionClaimError, match="binding contract"):
        await store.save_mission_claims(
            mission.id,
            claim.frame_digest,
            [replace(claim, evidence_bindings=(binding,))],
        )


@pytest.mark.asyncio
async def test_pruning_last_support_withholds_claim_and_removes_binding(repository_case, tmp_path):
    repository = repository_case.repository
    store, _workspace, mission = await _mission(repository, tmp_path)
    await store.save_mission_manifest(_manifest(mission.id))
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Evidence that will be pruned",
        source_url="https://youtube.com/watch?v=pruned12345",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"external_id": "pruned12345"},
    )
    signal.mission_id = mission.id
    await repository.save_signals([signal])
    observation_id = (await repository.get_mission_signals(mission.id))[0].observation_id
    await _qualify_observation(store, mission.id, observation_id, "a" * 64)
    claim = MissionClaim(
        mission_id=mission.id,
        frame_digest="a" * 64,
        client_claim_key="pruned-support",
        claim_type=ClaimType.OBSERVATION,
        wording="This claim loses its only support.",
        status=ClaimStatus.PERMITTED,
        created_by="contract-test",
    )
    binding = MissionClaimEvidence(
        claim_id=claim.claim_id,
        observation_id=observation_id,
        probe_outcome_id=None,
        role=EvidenceDirection.SUPPORT,
        hypothesis_target="core",
    )
    await store.save_mission_claims(
        mission.id, claim.frame_digest, [replace(claim, evidence_bindings=(binding,))]
    )

    await repository.prune_mission_evidence(mission.id, [])
    history = await store.list_mission_claims(mission.id, include_superseded=True)

    assert len(history) == 1
    assert history[0].status is ClaimStatus.WITHHELD
    assert history[0].evidence_bindings == ()
    assert "EVIDENCE_BINDING_INVALIDATED" in history[0].withheld_reasons


def test_claim_triggers_do_not_inherit_caller_search_path(repository_case):
    if repository_case.name != "postgres":
        pytest.skip("PostgreSQL function configuration contract")
    row = repository_case.query_one(
        "",
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname IN "
        "('validate_mission_claim_evidence_binding', 'prune_claim_binding_with_mission_evidence', "
        "'withhold_claim_without_support') AND NOT p.prosecdef "
        "AND 'search_path=public, pg_temp' = ANY(p.proconfig)",
    )
    assert row[0] == 3
