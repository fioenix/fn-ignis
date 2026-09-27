"""Evidence qualification: typed judgments, historical probe outcomes, and the frame they bind to.

A citation that reaches a canonical observation proves traceability. It does not prove support:
the post-v0.5 validation found traceable citations on films and drama that merely repeated a probe
keyword. The records here are the boundary between the two. The host Agent supplies the semantic
judgment; these types make sure nothing it submits can be half-formed, self-contradictory, or a
carrier for a prompt transcript.
"""

import math
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ignis.domain.entities import ResearchMission
from ignis.domain.harness_models import ChannelHealthStatus, QualityScorecard
from ignis.domain.research_workspace import (
    EvidencePurpose,
    EvidenceQualification,
    EvidenceSufficiency,
    InvalidEvidenceQualificationError,
    MarketBriefRevision,
    MissionProbeOutcome,
    QualificationProgress,
    QualificationReason,
    QualificationRelation,
    QualificationStatus,
    compute_frame_fingerprint,
    compute_query_fingerprint,
)
from ignis.domain.value_objects import GeoCode

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


def _qualification(**overrides) -> EvidenceQualification:
    values = dict(
        mission_id=uuid4(),
        observation_id=uuid4(),
        frame_fingerprint="a" * 64,
        relation=QualificationRelation.QUALIFIED_SUPPORT,
        purpose=EvidencePurpose.SUPPLY,
        confidence=0.82,
        reason_code=QualificationReason.DIRECT_TO_FRAME,
        judged_by="claude-code",
    )
    values.update(overrides)
    return EvidenceQualification(**values)


def _brief(**overrides) -> MarketBriefRevision:
    values = dict(
        decision="Decide whether to pursue the segment",
        target_user="Small Vietnamese retailers",
        problem="Manual store operations",
        geo="VN",
        timeframe="7d",
        hypothesis="A lightweight AI copilot removes repeated work",
        falsifiers=("No repeated operational pain is observed",),
        confirmed_by="requester",
    )
    values.update(overrides)
    return MarketBriefRevision(**values)


# --- the four relations, and what each is allowed to measure ------------------------------------


def test_every_relation_purpose_and_reason_named_by_the_contract_exists():
    assert {r.value for r in QualificationRelation} == {
        "QUALIFIED_SUPPORT", "CONTEXT_ONLY", "EXCLUDED_IRRELEVANT", "UNASSESSED",
    }
    assert {p.value for p in EvidencePurpose} == {"DEMAND", "SUPPLY", "VOC", "CONTEXT"}
    assert {r.value for r in QualificationReason} == {
        "DIRECT_TO_FRAME", "ADJACENT_ONLY", "KEYWORD_ONLY", "WRONG_AUDIENCE_OR_PROBLEM",
        "FICTION_NEWS_OR_ENTERTAINMENT", "INSUFFICIENT_CONTENT", "EVALUATOR_UNAVAILABLE",
    }
    assert {s.value for s in QualificationStatus} == {
        "QUALIFICATION_REQUIRED", "READY", "INSUFFICIENT_RELEVANT_EVIDENCE", "UNAVAILABLE",
        "NOT_APPLICABLE",
    }
    assert {s.value for s in EvidenceSufficiency} == {
        "SUFFICIENT_POSITIVE_SUPPLY", "SUFFICIENT_ZERO_SUPPLY", "MISSING_DEMAND",
        "MISSING_SUPPLY", "QUALIFICATION_REQUIRED", "QUALIFIER_UNAVAILABLE",
    }


def test_values_submitted_as_strings_are_read_into_the_enums():
    judged = _qualification(relation="CONTEXT_ONLY", purpose="CONTEXT", reason_code="ADJACENT_ONLY")

    assert judged.relation is QualificationRelation.CONTEXT_ONLY
    assert judged.purpose is EvidencePurpose.CONTEXT
    assert judged.reason_code is QualificationReason.ADJACENT_ONLY


@pytest.mark.parametrize(
    "overrides",
    [
        {"relation": "RELEVANT"},
        {"purpose": "BUZZ"},
        {"reason_code": "LOOKS_GOOD_TO_ME"},
    ],
)
def test_a_value_outside_the_contract_is_refused(overrides):
    with pytest.raises(InvalidEvidenceQualificationError):
        _qualification(**overrides)


def test_qualified_support_must_measure_something():
    with pytest.raises(InvalidEvidenceQualificationError, match="CONTEXT"):
        _qualification(purpose=EvidencePurpose.CONTEXT)


def test_context_only_measures_nothing():
    with pytest.raises(InvalidEvidenceQualificationError):
        _qualification(relation=QualificationRelation.CONTEXT_ONLY, purpose=EvidencePurpose.DEMAND)


def test_an_excluded_observation_contributes_to_no_purpose_whatever_the_caller_sent():
    excluded = _qualification(
        relation=QualificationRelation.EXCLUDED_IRRELEVANT,
        purpose=EvidencePurpose.SUPPLY,
        reason_code=QualificationReason.FICTION_NEWS_OR_ENTERTAINMENT,
    )

    assert excluded.purpose is EvidencePurpose.SUPPLY, "the submitted value is kept for audit"
    assert excluded.contributes_to is None


def test_only_qualified_support_contributes():
    assert _qualification().contributes_to is EvidencePurpose.SUPPLY
    context = _qualification(relation="CONTEXT_ONLY", purpose="CONTEXT", reason_code="ADJACENT_ONLY")
    assert context.contributes_to is None


def test_an_unassessed_row_admits_it_holds_no_judgment():
    honest = _qualification(
        relation=QualificationRelation.UNASSESSED,
        purpose=EvidencePurpose.CONTEXT,
        confidence=None,
        reason_code=QualificationReason.EVALUATOR_UNAVAILABLE,
    )
    assert honest.contributes_to is None

    with pytest.raises(InvalidEvidenceQualificationError, match="confidence"):
        _qualification(
            relation=QualificationRelation.UNASSESSED,
            confidence=0.4,
            reason_code=QualificationReason.EVALUATOR_UNAVAILABLE,
        )
    with pytest.raises(InvalidEvidenceQualificationError, match="reason"):
        _qualification(
            relation=QualificationRelation.UNASSESSED,
            confidence=None,
            reason_code=QualificationReason.KEYWORD_ONLY,
        )


@pytest.mark.parametrize("confidence", [None, -0.01, 1.01, math.nan, True, "0.8"])
def test_an_assessed_judgment_needs_a_real_probability(confidence):
    with pytest.raises(InvalidEvidenceQualificationError, match="confidence"):
        _qualification(confidence=confidence)


@pytest.mark.parametrize("confidence", [0, 0.0, 1, 1.0, 0.5])
def test_the_whole_closed_probability_range_is_accepted(confidence):
    assert _qualification(confidence=confidence).confidence == float(confidence)


@pytest.mark.parametrize(
    "field_name, value",
    [
        ("judged_by", ""),
        ("judged_by", "x" * 129),
        # A bounded identifier, not a place to paste a prompt or a model's reasoning.
        ("judged_by", "The model thought about this carefully and concluded"),
        ("model", "claude opus with this system prompt: you are"),
        ("model", "m" * 129),
    ],
)
def test_evaluator_identity_is_a_bounded_identifier_not_free_text(field_name, value):
    with pytest.raises(InvalidEvidenceQualificationError):
        _qualification(**{field_name: value})


def test_a_judgment_keyed_to_nothing_is_refused():
    with pytest.raises(InvalidEvidenceQualificationError, match="frame"):
        _qualification(frame_fingerprint="")
    with pytest.raises(InvalidEvidenceQualificationError):
        _qualification(observation_id="not-a-uuid")


def test_two_byte_equivalent_judgments_compare_equal_and_a_different_one_does_not():
    first = _qualification()
    replay = _qualification(
        mission_id=first.mission_id, observation_id=first.observation_id, created_at=NOW
    )
    rewrite = _qualification(
        mission_id=first.mission_id, observation_id=first.observation_id, confidence=0.83
    )

    assert first.same_judgment(replay), "the persisted time is not part of the judgment"
    assert not first.same_judgment(rewrite)


# --- probe outcomes: a measured zero is a recorded fact, not an absent row -----------------------


def _outcome(**overrides) -> MissionProbeOutcome:
    values = dict(
        run_id=uuid4(),
        platform="youtube",
        connector_surface="youtube",
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        signals_collected=0,
        queried_keywords=("ai cho cửa hàng",),
        query_fingerprint="b" * 64,
        completed_at=NOW,
    )
    values.update(overrides)
    return MissionProbeOutcome(**values)


def test_only_a_completed_empty_surface_measures_zero():
    assert _outcome().measures_zero is True
    assert _outcome(status="HEALTHY", signals_collected=3).measures_zero is False
    for failed in ("AUTH_REQUIRED", "RATE_LIMITED", "DEGRADED"):
        assert _outcome(status=failed).measures_zero is False, failed


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "EMPTY_NO_DATA", "signals_collected": 2},
        {"status": "HEALTHY", "signals_collected": 0},
        {"status": "DEGRADED", "signals_collected": 1},
        {"signals_collected": -1},
        {"status": "FINE"},
        {"connector_surface": ""},
        {"query_fingerprint": ""},
        # A measured zero has to name what it measured.
        {"queried_keywords": ()},
    ],
)
def test_a_probe_outcome_that_contradicts_itself_is_refused(overrides):
    with pytest.raises(InvalidEvidenceQualificationError):
        _outcome(**overrides)


def test_the_query_fingerprint_names_the_query_and_carries_no_input_text():
    fingerprint = compute_query_fingerprint(["AI cho cửa hàng", "copilot"], GeoCode.VN, "7d")

    assert fingerprint == compute_query_fingerprint(["copilot", "AI cho cửa hàng"], "VN", "7d")
    assert fingerprint != compute_query_fingerprint(["copilot"], "VN", "7d")
    assert fingerprint != compute_query_fingerprint(["AI cho cửa hàng", "copilot"], "VN", "30d")
    assert "copilot" not in fingerprint and len(fingerprint) == 64


# --- the frame a judgment is made against ------------------------------------------------------


def test_a_market_frame_changes_with_any_confirmed_brief_field_and_nothing_else():
    mission = ResearchMission(title="Retail copilot", keywords=["ai retail"], surface="MARKET")
    brief = _brief(mission_id=mission.id)

    fingerprint = compute_frame_fingerprint(mission, brief)
    assert fingerprint == compute_frame_fingerprint(mission, brief)
    assert fingerprint != compute_frame_fingerprint(mission, _brief(mission_id=mission.id))
    assert fingerprint != compute_frame_fingerprint(
        mission, _brief(brief_revision_id=brief.brief_revision_id, target_user="Enterprise CIOs")
    )
    mission.status = "COMPLETED"
    mission.summary = "a later run happened"
    assert compute_frame_fingerprint(mission, brief) == fingerprint, (
        "run state is not part of the question"
    )


def test_an_attention_frame_is_its_declared_scope():
    mission = ResearchMission(
        title="What is gaining attention", keywords=["ai retail", "pos"], surface="ATTENTION"
    )
    fingerprint = compute_frame_fingerprint(mission, None)

    other = ResearchMission(
        id=mission.id, title="What is gaining attention", keywords=["ai retail"],
        surface="ATTENTION",
    )
    assert compute_frame_fingerprint(other, None) != fingerprint


def test_a_market_frame_without_its_brief_cannot_be_fingerprinted():
    mission = ResearchMission(title="Retail copilot", keywords=["ai retail"], surface="MARKET")
    with pytest.raises(InvalidEvidenceQualificationError):
        compute_frame_fingerprint(mission, None)


# --- progress ----------------------------------------------------------------------------------


def test_progress_counts_every_current_association_and_scores_relevance_over_assessed_evidence():
    ids = [uuid4() for _ in range(6)]
    mission_id = uuid4()

    def judged(observation_id, relation, purpose, reason, confidence=0.9):
        return _qualification(
            mission_id=mission_id, observation_id=observation_id, relation=relation,
            purpose=purpose, reason_code=reason, confidence=confidence,
        )

    qualifications = [
        judged(ids[0], "QUALIFIED_SUPPORT", "DEMAND", "DIRECT_TO_FRAME"),
        judged(ids[1], "CONTEXT_ONLY", "CONTEXT", "ADJACENT_ONLY"),
        judged(ids[2], "EXCLUDED_IRRELEVANT", "CONTEXT", "KEYWORD_ONLY"),
        judged(ids[3], "UNASSESSED", "CONTEXT", "EVALUATOR_UNAVAILABLE", confidence=None),
        # A judgment on an observation the mission no longer holds is not counted.
        judged(uuid4(), "QUALIFIED_SUPPORT", "SUPPLY", "DIRECT_TO_FRAME"),
    ]
    progress = QualificationProgress.from_evidence(ids, qualifications)

    assert progress.to_payload() == {
        "total_evidence": 6,
        "qualified_support": 1,
        "context_only": 1,
        "excluded_irrelevant": 1,
        # ids[4] and ids[5] carry no row, ids[3] carries an explicit UNASSESSED one.
        "unassessed": 3,
    }
    assert progress.evaluator_unavailable == 1
    assert progress.question_relevance_score == pytest.approx(33.3)
    assert progress.is_complete is False


def test_relevance_is_zero_rather_than_undefined_when_nothing_was_assessed():
    progress = QualificationProgress.from_evidence([uuid4()], [])
    assert progress.question_relevance_score == 0.0
    assert QualificationProgress.from_evidence([], []).is_complete is True


# --- scorecard -----------------------------------------------------------------------------------


def test_a_legacy_scorecard_carries_no_relevance_dimension():
    scorecard = QualityScorecard()
    assert scorecard.question_relevance_score is None
    assert scorecard.qualification_counts is None


# --- User Story 2: the two MCP operations, as use cases over a real store -----------------------
#
# The host Agent reads bounded batches and submits typed judgments. Ignis cannot prove a semantic
# judgment, so what it enforces is identity and integrity: every judgment names evidence the
# mission holds, against the frame the mission was framed by, and a batch lands whole or not at all.

import json  # noqa: E402

import pytest_asyncio  # noqa: E402

from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase  # noqa: E402
from ignis.application.use_cases.create_attention_mission import (  # noqa: E402
    CreateAttentionMissionUseCase,
)
from ignis.application.use_cases.create_research_workspace import (  # noqa: E402
    CreateResearchWorkspaceUseCase,
)
from ignis.application.use_cases.get_evidence_qualification_batch import (  # noqa: E402
    GetEvidenceQualificationBatchUseCase,
)
from ignis.application.use_cases.submit_evidence_qualifications import (  # noqa: E402
    SubmitEvidenceQualificationsUseCase,
)
from ignis.domain.entities import TrendSignal  # noqa: E402
from ignis.domain.value_objects import PlatformType  # noqa: E402
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository  # noqa: E402
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository  # noqa: E402

BRIEF = dict(
    decision="Decide whether to build an AI operations copilot for small retailers",
    target_user="Owners of independent Vietnamese retail shops",
    problem="Daily sales and inventory decisions depend on manual checking",
    geo="VN",
    timeframe="7d",
    hypothesis="Independent retailers want affordable AI help with daily operating data",
    falsifiers=["Probes find only generic AI content"],
    confirmed_by="requester",
)


@pytest_asyncio.fixture
async def research(tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "qualification.sqlite"))
    store = WorkspaceRepository(repository=repository)
    workspaces = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / "host"
    host.mkdir()
    workspace = await workspaces.confirm(await workspaces.propose(host, "Retail copilot"), confirmation=True)
    yield repository, store, workspace
    await repository.close()


async def _market(repository, store, workspace, titles=("AI quản lý kho cho shop nhỏ",)):
    mission, brief = await ConfirmMarketBriefUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, keywords=["ai cho cửa hàng"], **BRIEF
    )
    return mission, brief, await _hold(repository, mission, titles)


async def _hold(repository, mission, titles):
    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title=title,
            metric_value=1000.0 + index,
            source_url=f"https://www.youtube.com/watch?v=q{index:010d}",
            captured_at=NOW,
            mission_id=mission.id,
            metadata={"keyword": "ai cho cửa hàng", "connector_surface": "youtube",
                      "top_comment": "gọi 0912345678 để mua"},
        )
        for index, title in enumerate(titles)
    ]
    await repository.save_signals(signals)
    return sorted(await repository.get_mission_signals(mission.id), key=lambda s: str(s.observation_id))


def _assessment(observation_id, **overrides):
    values = {
        "observation_id": str(observation_id),
        "relation": "QUALIFIED_SUPPORT",
        "purpose": "SUPPLY",
        "confidence": 0.9,
        "reason_code": "DIRECT_TO_FRAME",
        "judged_by": "claude-code",
        "model": "claude-opus-5-5",
    }
    values.update(overrides)
    return values


def _use_cases(repository, store):
    return (
        GetEvidenceQualificationBatchUseCase(repository=repository, store=store),
        SubmitEvidenceQualificationsUseCase(repository=repository, store=store),
    )


@pytest.mark.asyncio
async def test_a_market_batch_carries_the_frame_the_brief_revision_and_only_unjudged_evidence(research):
    repository, store, workspace = research
    mission, brief, held = await _market(repository, store, workspace, ("a", "b", "c"))
    read, submit = _use_cases(repository, store)

    batch = await read.execute(str(mission.id))

    assert batch["status"] == "QUALIFICATION_REQUIRED"
    assert batch["surface"] == "MARKET"
    assert batch["frame_fingerprint"] == compute_frame_fingerprint(mission, brief)
    assert batch["frame"]["brief_revision_id"] == str(brief.brief_revision_id)
    assert batch["frame"]["target_user"] == BRIEF["target_user"]
    assert batch["frame"]["falsifiers"] == BRIEF["falsifiers"]
    assert batch["progress"] == {"total_evidence": 3, "qualified_support": 0, "context_only": 0,
                                 "excluded_irrelevant": 0, "unassessed": 3}
    assert [e["observation_id"] for e in batch["evidence"]] == [str(s.observation_id) for s in held]
    first = batch["evidence"][0]
    assert first["probe_keyword"] == "ai cho cửa hàng" and first["connector_surface"] == "youtube"
    assert first["source_id"] == str(held[0].source_id)
    assert "0912345678" not in json.dumps(batch, ensure_ascii=False), "a phone number leaked"
    assert set(batch["recommended_judgment"]["relation"]) == {r.value for r in QualificationRelation}

    await submit.execute(str(mission.id), batch["frame_fingerprint"], [_assessment(held[0].observation_id)])
    again = await read.execute(str(mission.id))
    assert [e["observation_id"] for e in again["evidence"]] == [str(s.observation_id) for s in held[1:]]


@pytest.mark.asyncio
async def test_batches_paginate_stably_and_end_ready(research):
    repository, store, workspace = research
    mission, _brief, held = await _market(repository, store, workspace, tuple("abcde"))
    read, submit = _use_cases(repository, store)

    first = await read.execute(str(mission.id), limit=2)
    second = await read.execute(str(mission.id), cursor=first["next_cursor"], limit=2)
    third = await read.execute(str(mission.id), cursor=second["next_cursor"], limit=2)

    seen = [e["observation_id"] for page in (first, second, third) for e in page["evidence"]]
    assert seen == [str(s.observation_id) for s in held]
    assert third["next_cursor"] is None
    assert (await read.execute(str(mission.id), limit=500))["evidence"].__len__() == 5, "limit caps at 50"

    await submit.execute(
        str(mission.id), first["frame_fingerprint"],
        [_assessment(s.observation_id, relation="EXCLUDED_IRRELEVANT", reason_code="KEYWORD_ONLY") for s in held],
    )
    done = await read.execute(str(mission.id))
    assert done["status"] == "READY" and done["evidence"] == [] and done["next_cursor"] is None
    assert done["progress"]["excluded_irrelevant"] == 5


@pytest.mark.asyncio
async def test_a_cursor_from_another_mission_or_frame_is_a_conflict(research):
    repository, store, workspace = research
    mission, _brief, _held = await _market(repository, store, workspace, tuple("abc"))
    other, _other_brief, _ = await _market(repository, store, workspace, tuple("de"))
    read, _submit = _use_cases(repository, store)

    cursor = (await read.execute(str(mission.id), limit=1))["next_cursor"]

    refused = await read.execute(str(other.id), cursor=cursor)
    assert refused["status"] == "CONFLICT" and refused["evidence"] == []
    assert (await read.execute(str(mission.id), cursor="not-a-cursor"))["status"] == "CONFLICT"


@pytest.mark.asyncio
async def test_an_attention_frame_is_its_declared_scope_and_carries_no_brief(research):
    repository, store, workspace = research
    mission = await CreateAttentionMissionUseCase(repository, store).execute(
        workspace_id=workspace.workspace_id, title="What is gaining attention", seed="ai bán lẻ",
        keywords=["pos"],
    )
    await _hold(repository, mission, ("x",))
    read, _submit = _use_cases(repository, store)

    batch = await read.execute(str(mission.id))

    assert batch["surface"] == "ATTENTION"
    assert batch["frame"]["title"] == "What is gaining attention"
    assert batch["frame"]["keywords"] == ["ai bán lẻ", "pos"]
    assert "brief_revision_id" not in batch["frame"] and "target_user" not in batch["frame"]


@pytest.mark.asyncio
async def test_unknown_legacy_and_unauthorized_missions_are_refused_without_state(research):
    repository, store, workspace = research
    read, submit = _use_cases(repository, store)
    legacy = ResearchMission(title="Legacy", keywords=["ai"])
    await repository.create_mission(legacy)

    assert (await read.execute(str(uuid4())))["status"] == "NOT_FOUND"
    assert (await read.execute(str(legacy.id)))["status"] == "NOT_APPLICABLE"
    assert (await submit.execute(str(legacy.id), "f" * 64, [_assessment(uuid4())]))["status"] == "NOT_APPLICABLE"

    unauthorized = ResearchMission(
        title="Unframed market", keywords=["ai"], surface="MARKET", workspace_id=workspace.workspace_id
    )
    await repository.create_mission(unauthorized)
    assert (await read.execute(str(unauthorized.id)))["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_a_submission_against_a_stale_frame_writes_nothing(research):
    repository, store, workspace = research
    mission, _brief, held = await _market(repository, store, workspace)
    _read, submit = _use_cases(repository, store)

    refused = await submit.execute(str(mission.id), "0" * 64, [_assessment(held[0].observation_id)])

    assert refused["status"] == "CONFLICT" and refused["reason_code"] == "STALE_FRAME"
    assert await store.list_evidence_qualifications(mission.id) == []


@pytest.mark.parametrize(
    "mutate, reason_code",
    [
        (lambda held: [_assessment(held[0].observation_id), _assessment(uuid4())], "FOREIGN_OBSERVATION"),
        (lambda held: [_assessment(held[0].observation_id), _assessment(held[0].observation_id)],
         "DUPLICATE_OBSERVATION"),
        (lambda held: [_assessment(held[0].observation_id), _assessment(held[1].observation_id, purpose="CONTEXT")],
         "INVALID_JUDGMENT"),
        (lambda held: [_assessment(held[0].observation_id), _assessment(held[1].observation_id, confidence=2)],
         "INVALID_JUDGMENT"),
        (lambda held: [_assessment(held[0].observation_id, judged_by="an agent that thought hard")],
         "INVALID_JUDGMENT"),
        (lambda held: [], "INVALID_BATCH_SIZE"),
        (lambda held: [_assessment(held[0].observation_id)] * 51, "INVALID_BATCH_SIZE"),
    ],
)
@pytest.mark.asyncio
async def test_one_invalid_assessment_refuses_the_whole_batch(research, mutate, reason_code):
    repository, store, workspace = research
    mission, brief, held = await _market(repository, store, workspace, ("a", "b"))
    _read, submit = _use_cases(repository, store)

    refused = await submit.execute(str(mission.id), compute_frame_fingerprint(mission, brief), mutate(held))

    assert refused["status"] == "INVALID", refused
    assert refused["reason_code"] == reason_code
    assert await store.list_evidence_qualifications(mission.id) == []


@pytest.mark.asyncio
async def test_a_replay_is_idempotent_and_a_rewrite_is_a_conflict(research):
    repository, store, workspace = research
    mission, brief, held = await _market(repository, store, workspace, ("a", "b"))
    _read, submit = _use_cases(repository, store)
    frame = compute_frame_fingerprint(mission, brief)
    batch = [_assessment(held[0].observation_id), _assessment(held[1].observation_id, relation="CONTEXT_ONLY",
                                                               purpose="CONTEXT", reason_code="ADJACENT_ONLY")]

    recorded = await submit.execute(str(mission.id), frame, batch)
    replay = await submit.execute(str(mission.id), frame, batch)
    rewrite = await submit.execute(
        str(mission.id), frame,
        [_assessment(held[0].observation_id, relation="EXCLUDED_IRRELEVANT", reason_code="KEYWORD_ONLY")],
    )

    assert recorded["status"] == "RECORDED" and recorded["recorded"] == 2
    assert recorded["progress"]["qualified_support"] == 1 and recorded["progress"]["context_only"] == 1
    assert replay["status"] == "RECORDED" and replay["progress"] == recorded["progress"]
    assert rewrite["status"] == "CONFLICT" and rewrite["reason_code"] == "CONFLICTING_REWRITE"
    stored = {str(q.observation_id): q for q in await store.list_evidence_qualifications(mission.id)}
    assert stored[str(held[0].observation_id)].relation is QualificationRelation.QUALIFIED_SUPPORT
    assert stored[str(held[0].observation_id)].brief_revision_id == brief.brief_revision_id
    assert "get_mission_evidence_qualification_batch" in recorded["next_step"]


# --- User Story 4: question relevance is its own dimension, and it caps confidence --------------

from ignis.domain.harness_models import ConfidenceLevel, QualificationSummary  # noqa: E402
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator  # noqa: E402


def _strong_scorecard() -> QualityScorecard:
    """High freshness and diversity: everything but relevance says HIGH."""
    return QualityScorecard(
        coverage_score=100.0, language_precision=95.0, data_freshness_score=100.0,
        creator_diversity_score=100.0, overall_confidence=92.0,
        confidence_level=ConfidenceLevel.HIGH,
    )


def _summary(status, unassessed=0, qualified=0, context=0, excluded=40, relevance=0.0):
    return QualificationSummary(
        status=status, total_evidence=qualified + context + excluded + unassessed,
        qualified_support=qualified, context_only=context, excluded_irrelevant=excluded,
        unassessed=unassessed, question_relevance_score=relevance,
        reason=None if status == "READY" else "withheld", reason_code=None,
    )


def test_question_relevance_is_reported_beside_the_other_dimensions_not_inside_them():
    scorecard = _strong_scorecard()
    QualityEvaluator().apply_qualification(scorecard, _summary("READY", qualified=8, context=12, relevance=13.3))

    assert scorecard.question_relevance_score == 13.3
    assert scorecard.qualification_counts == {
        "qualified_support": 8, "context_only": 12, "excluded_irrelevant": 40, "unassessed": 0,
    }
    assert (scorecard.coverage_score, scorecard.data_freshness_score,
            scorecard.creator_diversity_score, scorecard.language_precision) == (100.0, 100.0, 100.0, 95.0)


def test_complete_but_insufficient_evidence_caps_confidence_at_low_whatever_else_is_high():
    scorecard = _strong_scorecard()
    QualityEvaluator().apply_qualification(scorecard, _summary("INSUFFICIENT_RELEVANT_EVIDENCE"))

    assert scorecard.confidence_level is ConfidenceLevel.LOW
    assert scorecard.overall_confidence < settings_medium_threshold()
    assert any("relevant" in flaw.lower() for flaw in scorecard.flaws_detected)


@pytest.mark.parametrize(
    "summary",
    [
        _summary("QUALIFICATION_REQUIRED", unassessed=10),
        _summary("UNAVAILABLE", unassessed=1),
        # Complete but carrying an explicit UNASSESSED row: still not trustworthy.
        _summary("INSUFFICIENT_RELEVANT_EVIDENCE", unassessed=2),
        _summary("READY", qualified=5, unassessed=1, relevance=11.0),
    ],
)
def test_pending_unavailable_or_unassessed_evidence_caps_confidence_at_unreliable(summary):
    scorecard = _strong_scorecard()
    QualityEvaluator().apply_qualification(scorecard, summary)

    assert scorecard.confidence_level is ConfidenceLevel.UNRELIABLE
    assert scorecard.overall_confidence < settings_low_threshold()


def test_a_fully_assessed_sufficient_mission_keeps_its_confidence():
    scorecard = _strong_scorecard()
    QualityEvaluator().apply_qualification(scorecard, _summary("READY", qualified=30, excluded=10, relevance=75.0))

    assert scorecard.confidence_level is ConfidenceLevel.HIGH and scorecard.overall_confidence == 92.0


def test_a_legacy_mission_scorecard_is_untouched():
    scorecard = _strong_scorecard()
    QualityEvaluator().apply_qualification(scorecard, None)

    assert scorecard == _strong_scorecard()


def settings_medium_threshold():
    from ignis.config import settings

    return settings.CONFIDENCE_MEDIUM_THRESHOLD


def settings_low_threshold():
    from ignis.config import settings

    return settings.CONFIDENCE_LOW_THRESHOLD


@pytest.mark.parametrize(
    "reason, expected",
    [
        ("INSUFFICIENT_CONTENT", QualificationStatus.QUALIFICATION_REQUIRED),
        ("EVALUATOR_UNAVAILABLE", QualificationStatus.UNAVAILABLE),
    ],
)
def test_an_explicit_unassessed_row_never_opens_the_verdict_gate(reason, expected):
    """Every row persisted is not every observation assessed: UNASSESSED is not an assessment."""
    from ignis.domain.research_workspace import QualificationContext

    mission_id, judged, thin = uuid4(), uuid4(), uuid4()
    rows = [
        _qualification(mission_id=mission_id, observation_id=judged),
        _qualification(mission_id=mission_id, observation_id=thin, relation="UNASSESSED",
                       purpose="CONTEXT", confidence=None, reason_code=reason),
    ]

    context = QualificationContext.build([judged, thin], rows, (), geo="VN", timeframe="7d")

    assert context.progress.unjudged == 0 and context.progress.unassessed == 1
    assert context.assessment_state is expected


@pytest.mark.parametrize(
    "reason, status",
    [("INSUFFICIENT_CONTENT", "QUALIFICATION_REQUIRED"), ("EVALUATOR_UNAVAILABLE", "UNAVAILABLE")],
)
@pytest.mark.asyncio
async def test_the_batch_is_not_ready_while_an_explicit_unassessed_row_remains(research, reason, status):
    """Nothing is left to hand out, but an UNASSESSED row is not an assessment."""
    repository, store, workspace = research
    mission, brief, held = await _market(repository, store, workspace, ("a", "b"))
    read, submit = _use_cases(repository, store)
    frame = compute_frame_fingerprint(mission, brief)
    await submit.execute(str(mission.id), frame, [
        _assessment(held[0].observation_id),
        _assessment(held[1].observation_id, relation="UNASSESSED", purpose="CONTEXT",
                    confidence=None, reason_code=reason),
    ])

    batch = await read.execute(str(mission.id))

    assert batch["status"] == status
    assert batch["evidence"] == [] and batch["next_cursor"] is None
    assert batch["progress"]["unassessed"] == 1
    assert batch["reason_code"] == ("UNASSESSED_EVIDENCE" if status == "QUALIFICATION_REQUIRED" else "EVALUATOR_UNAVAILABLE")
    assert "new mission" in batch["next_step"] and "Brief revision" in batch["next_step"]
    assert "get_mission_evidence_qualification_batch" not in batch["next_step"], "a read loop cannot help"
