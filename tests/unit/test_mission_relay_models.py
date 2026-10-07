"""Typed boundary tests: reject invented progress, foreign refs and unsafe shapes."""

import importlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from ignis.domain.research_workspace import (
    EvidenceDirection,
    EvidenceRole,
    QualificationRelation,
    ResearchSurface,
)


MISSION = UUID("11111111-2222-4333-8444-555555555555")
RUN = UUID("22222222-3333-4444-8555-666666666666")
OBSERVATION = UUID("33333333-4444-4555-8666-777777777777")
SOURCE = UUID("44444444-5555-4666-8777-888888888888")
FOREIGN = UUID("55555555-6666-4777-8888-999999999999")
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)


@pytest.fixture
def relay():
    return _RelayAPI()


class _RelayAPI:
    """Discover the absent API inside each test rather than failing fixture setup."""

    def __getattr__(self, name):
        try:
            module = importlib.import_module("ignis.domain.mission_relay")
        except ModuleNotFoundError as exc:
            if exc.name != "ignis.domain.mission_relay":
                raise
            pytest.fail("T006 API RED: typed mission relay domain is absent")
        return getattr(module, name)


def cursor(relay, revision=1, ordinal=1, mission_id=MISSION):
    return relay.MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=ordinal)


def event(relay, **changes):
    values = dict(
        event_id=OBSERVATION,
        cursor=cursor(relay),
        kind=relay.MissionProgressKind.OBSERVATIONS_COMMITTED,
        provenance=relay.RelayProvenance.HARNESS_OBSERVED,
        recorded_at=NOW,
        run_id=RUN,
        causation_key="fixture-command",
    )
    values.update(changes)
    return relay.MissionProgressEvent(**values)


def observation(relay, **changes):
    values = dict(
        mission_id=MISSION,
        observation_id=OBSERVATION,
        source_id=SOURCE,
        title="Work bag review",
        excerpt="The handle broke after two weeks.",
        source_url="https://example.invalid/public",
        metric_value=None,
        growth_velocity=None,
        published_at=None,
        captured_at=None,
        evidence_role=EvidenceRole.ATTENTION_CONTEXT,
        direction=EvidenceDirection.CONTEXT,
    )
    values.update(changes)
    return relay.RelayObservation(**values)


def snapshot(relay, **changes):
    values = dict(
        mission_id=MISSION,
        run_id=RUN,
        read_at=NOW,
        high_water=cursor(relay),
        page_size=1,
        evidence=(observation(relay),),
        total_observations=2,
        source_count=1,
        surface=ResearchSurface.ATTENTION,
    )
    values.update(changes)
    return relay.MissionRelaySnapshot(**values)


def test_initial_cursor_does_not_invent_an_event(relay):
    initial = cursor(relay, 0, 0)
    assert initial.to_payload() == {"mission_id": str(MISSION), "revision": 0, "ordinal": 0}
    empty = relay.MissionRelayEventPage(high_water=initial, page_size=1, events=())
    assert empty.to_payload()["events"] == []
    with pytest.raises(ValueError):
        event(relay, cursor=initial)


@pytest.mark.parametrize("revision,ordinal", ((-1, 1), (1, -1), (0, 1), (1, 0), (True, 1), (1, 1.5)))
def test_cursor_rejects_invalid_position(relay, revision, ordinal):
    with pytest.raises(ValueError):
        cursor(relay, revision, ordinal)


@pytest.mark.parametrize("mission_id", (str(MISSION), None, 123))
def test_cursor_requires_uuid_scope(relay, mission_id):
    with pytest.raises(ValueError):
        cursor(relay, mission_id=mission_id)


@pytest.mark.parametrize("size", (0, 201, True, 1.5, None))
def test_page_size_is_explicit_and_bounded(relay, size):
    with pytest.raises(ValueError):
        relay.MissionRelayEventPage(high_water=cursor(relay), page_size=size, events=())
    with pytest.raises(ValueError):
        snapshot(relay, page_size=size)


def test_progress_event_preserves_provenance_and_unknown_time(relay):
    item = event(relay, provenance=relay.RelayProvenance.HOST_REPORTED)
    payload = item.to_payload()
    assert set(payload) == {
        "event_id",
        "mission_id",
        "revision",
        "ordinal",
        "kind",
        "provenance",
        "recorded_at",
        "occurred_at",
        "causation_key",
        "run_id",
        "work_id",
        "handoff_id",
        "finding_id",
        "claim_id",
        "evidence_references",
        "reason",
    }
    assert payload["provenance"] == "HOST_REPORTED"
    assert payload["occurred_at"] is None
    assert payload["recorded_at"] == NOW.isoformat()
    assert payload["mission_id"] == str(MISSION)
    assert payload["revision"] == 1
    assert payload["ordinal"] == 1


def test_probe_outcome_receipt_does_not_claim_observations_committed(relay):
    item = event(relay, kind=relay.MissionProgressKind.PROBE_OUTCOMES_RECORDED)
    payload = item.to_payload()
    assert payload["kind"] == "PROBE_OUTCOMES_RECORDED"
    assert payload["run_id"] == str(RUN)
    assert payload["evidence_references"] == []


def test_probe_outcome_receipt_requires_recorded_run_identity(relay):
    with pytest.raises(ValueError):
        event(relay, kind=relay.MissionProgressKind.PROBE_OUTCOMES_RECORDED, run_id=None)


@pytest.mark.parametrize(
    "changes",
    (
        {"provenance": "HOST_REPORTED"},
        {"kind": "arbitrary-event"},
        {"recorded_at": NOW.replace(tzinfo=None)},
        {"recorded_at": None},
        {"occurred_at": NOW.replace(tzinfo=None)},
        {"run_id": str(RUN)},
        {"causation_key": ""},
        {"event_id": str(OBSERVATION)},
    ),
)
def test_progress_event_rejects_untyped_or_unrecorded_facts(relay, changes):
    with pytest.raises(ValueError):
        event(relay, **changes)


def test_event_reference_must_belong_to_its_mission(relay):
    ref = relay.RelayEvidenceReference(
        mission_id=FOREIGN,
        observation_id=OBSERVATION,
        source_id=SOURCE,
        evidence_role=EvidenceRole.ATTENTION_CONTEXT,
        direction=EvidenceDirection.CONTEXT,
    )
    with pytest.raises(ValueError):
        event(relay, evidence_references=(ref,))
    local = replace(ref, mission_id=MISSION)
    assert event(relay, evidence_references=(local,)).to_payload()["evidence_references"] == [
        {
            "mission_id": str(MISSION),
            "observation_id": str(OBSERVATION),
            "source_id": str(SOURCE),
            "evidence_role": "ATTENTION_CONTEXT",
            "direction": "CONTEXT",
            "qualification_relation": None,
            "qualification_frame_fingerprint": None,
        }
    ]


def test_event_page_exposes_exact_continuation_under_high_water(relay):
    first = event(relay)
    second = event(relay, event_id=SOURCE, cursor=cursor(relay, 2, 1))
    page = relay.MissionRelayEventPage(
        high_water=cursor(relay, 2, 2),
        page_size=2,
        events=(first, second),
        next_cursor=second.cursor,
        has_more=True,
    )
    payload = page.to_payload()
    assert set(payload) == {
        "high_water",
        "page_size",
        "after_cursor",
        "next_cursor",
        "events",
        "has_more",
        "resync_required",
    }
    assert payload["high_water"] == {"mission_id": str(MISSION), "revision": 2, "ordinal": 2}
    assert payload["next_cursor"] == {"mission_id": str(MISSION), "revision": 2, "ordinal": 1}
    assert payload["has_more"] is True


@pytest.mark.parametrize(
    "breakage",
    (
        "foreign_event",
        "future_event",
        "unordered",
        "duplicate",
        "overfull",
        "foreign_after",
        "future_after",
        "not_after",
        "missing_next",
        "wrong_next",
        "false_next",
        "resync_events",
        "duplicate_identity",
        "complete_before_high_water",
    ),
)
def test_event_page_refuses_incoherent_positions(relay, breakage):
    first = event(relay)
    second = event(relay, event_id=SOURCE, cursor=cursor(relay, 1, 2))
    values = dict(high_water=cursor(relay, 1, 2), page_size=2, events=(first, second))
    if breakage == "foreign_event":
        values["events"] = (replace(first, cursor=cursor(relay, mission_id=FOREIGN)),)
    elif breakage == "future_event":
        values["high_water"] = first.cursor
    elif breakage == "unordered":
        values["events"] = (second, first)
    elif breakage == "duplicate":
        values["events"] = (first, first)
    elif breakage == "overfull":
        values["page_size"] = 1
    elif breakage == "foreign_after":
        values["after_cursor"] = cursor(relay, mission_id=FOREIGN)
    elif breakage == "future_after":
        values["after_cursor"] = cursor(relay, 2, 1)
    elif breakage == "not_after":
        values["after_cursor"] = first.cursor
    elif breakage == "missing_next":
        values["has_more"] = True
    elif breakage == "wrong_next":
        values.update(has_more=True, next_cursor=first.cursor)
    elif breakage == "false_next":
        values["next_cursor"] = second.cursor
    elif breakage == "resync_events":
        values["resync_required"] = True
    elif breakage == "duplicate_identity":
        values["events"] = (first, replace(second, event_id=first.event_id))
    else:
        values["events"] = (first,)
    with pytest.raises(ValueError):
        relay.MissionRelayEventPage(**values)


def test_unknown_cursor_requests_resync_without_replay(relay):
    page = relay.MissionRelayEventPage(
        high_water=cursor(relay),
        page_size=100,
        events=(),
        resync_required=True,
    )
    assert page.to_payload()["resync_required"] is True
    assert page.to_payload()["next_cursor"] is None


@pytest.mark.parametrize("field", ("metric_value", "growth_velocity"))
@pytest.mark.parametrize("value", (float("nan"), float("inf"), -float("inf"), True, "12"))
def test_observation_rejects_nonfinite_or_untyped_measurements(relay, field, value):
    with pytest.raises(ValueError):
        observation(relay, **{field: value})


@pytest.mark.parametrize("field", ("published_at", "captured_at"))
def test_observation_rejects_naive_fact_times(relay, field):
    with pytest.raises(ValueError):
        observation(relay, **{field: NOW.replace(tzinfo=None)})


def test_unknown_facts_and_measured_zero_survive_serialization(relay):
    row = observation(relay).to_payload()
    for field in ("published_at", "captured_at", "metric_value", "growth_velocity"):
        assert row[field] is None
    measured = observation(relay, metric_value=0, growth_velocity=-1.25, published_at=NOW)
    assert measured.to_payload()["metric_value"] == 0
    assert measured.to_payload()["growth_velocity"] == -1.25
    assert measured.to_payload()["published_at"] == NOW.isoformat()


def test_safe_snapshot_and_inspection_have_concrete_nested_allowlists(relay):
    safe = snapshot(relay)
    payload = safe.to_payload()
    assert set(payload) == {
        "schema_version",
        "status",
        "mission_id",
        "run_id",
        "revision",
        "read_at",
        "high_water",
        "manifest_digest",
        "brief_revision_id",
        "surface",
        "frame_digest",
        "frame_pending_reason",
        "collection_state",
        "counts",
        "page_size",
        "evidence_offset",
        "next_evidence_offset",
        "evidence",
        "event_page",
        "channels",
        "claim_gate",
        "research",
    }
    assert payload["research"] == {"availability": "SCHEMA_UNAVAILABLE"}
    assert set(payload["claim_gate"]) == {"state", "frame_digest", "render_status", "reason_code", "claims", "history", "gap_report"}
    assert payload["claim_gate"]["render_status"] == "WITHHELD"
    observation_keys = {
        "mission_id",
        "observation_id",
        "source_id",
        "title",
        "excerpt",
        "source_url",
        "metric_value",
        "growth_velocity",
        "published_at",
        "captured_at",
        "evidence_role",
        "direction",
        "qualification_relation",
        "qualification_frame_fingerprint",
    }
    assert set(payload["evidence"][0]) == observation_keys
    assert set(payload["counts"]) == {"observations", "sources"}
    assert payload["counts"] == {"observations": 2, "sources": 1}
    assert payload["next_evidence_offset"] == 1
    assert payload["frame_digest"] is None
    assert payload["frame_pending_reason"] == "UNKNOWN"
    inspection = relay.MissionRelayInspection(
        mission_id=MISSION,
        run_id=RUN,
        high_water=cursor(relay),
        read_at=NOW,
        observation=observation(relay),
    ).to_payload()
    assert set(inspection) == {
        "schema_version",
        "status",
        "mission_id",
        "run_id",
        "revision",
        "read_at",
        "high_water",
        "observation",
    }
    assert set(inspection["observation"]) == observation_keys
    encoded = json.dumps(payload, allow_nan=False)
    assert "metadata" not in encoded
    assert "journal_path" not in encoded


@pytest.mark.parametrize(
    "breakage",
    (
        "foreign_cursor",
        "foreign_observation",
        "overfull",
        "too_few_total",
        "negative_count",
        "bad_source_count",
        "duplicate_observation",
        "naive_read",
        "bad_surface",
        "bad_digest",
        "contradictory_frame",
        "empty_incomplete_page",
        "foreign_event_page",
    ),
)
def test_snapshot_refuses_incompatible_identity_counts_and_frame(relay, breakage):
    values = {}
    if breakage == "foreign_cursor":
        values["high_water"] = cursor(relay, mission_id=FOREIGN)
    elif breakage == "foreign_observation":
        values["evidence"] = (observation(relay, mission_id=FOREIGN),)
    elif breakage == "overfull":
        values["evidence"] = (observation(relay), observation(relay, observation_id=SOURCE))
    elif breakage == "too_few_total":
        values["total_observations"] = 0
    elif breakage == "negative_count":
        values["total_observations"] = -1
    elif breakage == "bad_source_count":
        values["source_count"] = 0
    elif breakage == "duplicate_observation":
        values.update(page_size=2, evidence=(observation(relay), observation(relay)))
    elif breakage == "naive_read":
        values["read_at"] = NOW.replace(tzinfo=None)
    elif breakage == "bad_surface":
        values["surface"] = "MARKET"
    elif breakage == "bad_digest":
        values["frame_digest"] = "question-fingerprint-is-not-a-frame"
    elif breakage == "contradictory_frame":
        values.update(frame_digest="a" * 64, frame_pending_reason=relay.RelayFramePendingReason.PENDING)
    elif breakage == "empty_incomplete_page":
        values["evidence"] = ()
    else:
        values["event_page"] = relay.MissionRelayEventPage(
            high_water=cursor(relay, mission_id=FOREIGN),
            page_size=1,
            events=(),
            resync_required=True,
        )
    with pytest.raises(ValueError):
        snapshot(relay, **values)


@pytest.mark.parametrize(
    "total,source_count,empty_end_page",
    ((2, 2, False), (3, 3, False), (1, 0, True)),
    ids=("complete_shared_source_overcount", "partial_impossible_overcount", "nonempty_zero_source_end_page"),
)
def test_snapshot_refuses_impossible_global_source_totals(relay, total, source_count, empty_end_page):
    """Catch global totals that visible shared sources or a nonempty corpus disprove."""
    rows = () if empty_end_page else (observation(relay), observation(relay, observation_id=SOURCE))
    with pytest.raises(ValueError):
        snapshot(
            relay,
            page_size=2,
            evidence=rows,
            total_observations=total,
            source_count=source_count,
            evidence_offset=total if empty_end_page else 0,
        )


@pytest.mark.parametrize(
    "total,source_count,page_shape,offset",
    (
        (0, 0, "empty", 0),
        (1, 1, "empty", 1),
        (2, 1, "shared", 0),
        (2, 2, "distinct", 0),
        (3, 1, "shared", 0),
        (3, 2, "shared", 0),
        (3, 2, "shared", 1),
    ),
    ids=(
        "empty_corpus",
        "nonempty_end_page",
        "complete_shared_source",
        "complete_distinct_sources",
        "unseen_shared_source",
        "unseen_new_source",
        "source_before_visible_page",
    ),
)
def test_snapshot_preserves_feasible_global_source_totals(relay, total, source_count, page_shape, offset):
    """Catch replacing global totals with page-only diversity or discarding valid counts."""
    rows = (
        ()
        if page_shape == "empty"
        else (
            observation(relay),
            observation(relay, observation_id=SOURCE, source_id=FOREIGN if page_shape == "distinct" else SOURCE),
        )
    )
    safe = snapshot(
        relay,
        page_size=2,
        evidence=rows,
        total_observations=total,
        source_count=source_count,
        evidence_offset=offset,
    )
    assert safe.to_payload()["counts"] == {"observations": total, "sources": source_count}
    assert safe.evidence == rows


def test_valid_frame_and_manifest_bindings_remain_distinct(relay):
    safe = snapshot(
        relay,
        manifest_digest="b" * 64,
        brief_revision_id=FOREIGN,
        frame_digest="a" * 64,
        frame_pending_reason=None,
    )
    assert safe.to_payload()["manifest_digest"] == "b" * 64
    assert safe.to_payload()["frame_digest"] == "a" * 64
    assert safe.to_payload()["brief_revision_id"] == str(FOREIGN)


def test_association_direction_and_recorded_qualification_remain_distinct(relay):
    pending = observation(relay, evidence_role=EvidenceRole.MARKET_EVIDENCE, direction=None)
    assert pending.to_payload()["evidence_role"] == "MARKET_EVIDENCE"
    assert pending.to_payload()["direction"] is None
    assert pending.to_payload()["qualification_relation"] is None
    excluded = observation(
        relay,
        direction=None,
        qualification_relation=QualificationRelation.EXCLUDED_IRRELEVANT,
        qualification_frame_fingerprint="c" * 64,
    )
    assert excluded.to_payload()["qualification_relation"] == "EXCLUDED_IRRELEVANT"
    assert excluded.to_payload()["qualification_frame_fingerprint"] == "c" * 64
    with pytest.raises(ValueError):
        observation(relay, qualification_relation=QualificationRelation.EXCLUDED_IRRELEVANT)
    with pytest.raises(ValueError):
        observation(relay, qualification_frame_fingerprint="c" * 64)
    with pytest.raises(ValueError):
        observation(relay, qualification_relation="EXCLUDED_IRRELEVANT", qualification_frame_fingerprint="c" * 64)


def test_inspection_refuses_foreign_scope_and_unknown_constructor_fields(relay):
    values = dict(mission_id=MISSION, run_id=RUN, high_water=cursor(relay), read_at=NOW)
    with pytest.raises(ValueError):
        relay.MissionRelayInspection(**values, observation=observation(relay, mission_id=FOREIGN))
    with pytest.raises(TypeError):
        relay.MissionRelayInspection(**values, observation=observation(relay), metadata={})


def test_unknown_run_is_not_replaced_by_a_fabricated_identity(relay):
    initial = cursor(relay, 0, 0)
    safe = snapshot(relay, run_id=None, high_water=initial)
    assert safe.to_payload()["run_id"] is None
    assert safe.to_payload()["mission_id"] == str(MISSION)
    inspected = relay.MissionRelayInspection(
        mission_id=MISSION,
        run_id=None,
        high_water=initial,
        read_at=NOW,
        observation=observation(relay),
    )
    assert inspected.to_payload()["run_id"] is None
    with pytest.raises(ValueError):
        snapshot(relay, run_id=str(RUN))
    with pytest.raises(ValueError):
        relay.MissionRelayInspection(
            mission_id=MISSION,
            run_id=str(RUN),
            high_water=initial,
            read_at=NOW,
            observation=observation(relay),
        )


def test_models_refuse_raw_shapes_and_are_immutable(relay):
    with pytest.raises(TypeError):
        relay.MissionRelayCursor(mission_id=MISSION, revision=1, ordinal=1, metadata={})
    with pytest.raises(TypeError):
        observation(relay, metadata={"unknown": None})
    with pytest.raises(TypeError):
        event(relay, payload={})
    with pytest.raises(TypeError):
        snapshot(relay, journal_path="private/path")
    with pytest.raises(ValueError):
        event(relay, evidence_references=({"mission_id": MISSION},))
    with pytest.raises(ValueError):
        snapshot(relay, evidence=({"observation_id": OBSERVATION},))
    safe = snapshot(relay)
    with pytest.raises(FrozenInstanceError):
        safe.run_id = FOREIGN
    with pytest.raises((AttributeError, TypeError)):
        safe.metadata = {}
    outward = safe.to_payload()
    outward["evidence"][0]["title"] = "changed outside"
    assert safe.evidence[0].title == "Work bag review"


def test_refusal_and_unavailable_have_no_success_or_raw_payload(relay):
    for status in (relay.RelayReadStatus.REFUSED, relay.RelayReadStatus.UNAVAILABLE):
        failure = relay.MissionRelayReadFailure(
            status=status,
            reason_code=relay.RelayReadReason.SCOPE_MISMATCH,
        ).to_payload()
        assert failure == {"schema_version": 1, "status": status.value, "reason_code": "SCOPE_MISMATCH"}
    with pytest.raises(ValueError):
        relay.MissionRelayReadFailure(
            status=relay.RelayReadStatus.OK,
            reason_code=relay.RelayReadReason.SCOPE_MISMATCH,
        )
    with pytest.raises(TypeError):
        relay.MissionRelayReadFailure(
            status=relay.RelayReadStatus.REFUSED,
            reason_code=relay.RelayReadReason.SCOPE_MISMATCH,
            raw_record={},
        )
