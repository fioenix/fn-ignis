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
