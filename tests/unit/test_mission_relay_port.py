"""Consumer contracts for typed commands and coherent internal reads, not database proof."""

import importlib
import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone, tzinfo
from enum import Enum
from pathlib import Path
from typing import get_type_hints
from uuid import UUID

import pytest

from ignis.application.ports.research_workspace_port import (
    IResearchWorkspaceStore,
    MissionEvidenceSnapshot,
    RunJournal,
)
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    MissionRelayEventPage,
    RelayProvenance,
)
from ignis.domain.research_workspace import MissionProbeOutcome
from ignis.domain.value_objects import PlatformType


MISSION = UUID("11111111-2222-4333-8444-555555555555")
RUN = UUID("22222222-3333-4444-8555-666666666666")
WORKSPACE = UUID("33333333-4444-4555-8666-777777777777")
FACT = UUID("44444444-5555-4666-8777-888888888888")
OTHER = UUID("55555555-6666-4777-8888-999999999999")
NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
KEY = f"probe-outcomes:{MISSION}:{RUN}:aa2ed62bc55b451c8950470c9d5d3994872a2e1def112df5e1a32d733c7f0210"


def api():
    try:
        return importlib.import_module("ignis.application.ports.mission_relay_port")
    except ModuleNotFoundError as exc:
        if exc.name != "ignis.application.ports.mission_relay_port":
            raise
        pytest.fail("T007 API RED: narrow mission relay port is absent")


def outcome(**changes):
    values = dict(
        outcome_id=FACT,
        run_id=RUN,
        platform="youtube",
        connector_surface="youtube.search",
        status=ChannelHealthStatus.EMPTY_NO_DATA,
        signals_collected=0,
        queried_keywords=("work bag",),
        queried_window="30d",
        query_fingerprint="a" * 64,
        completed_at=NOW,
        scope_attestation={"keywords": ["work bag"]},
        note="Measured empty.",
    )
    values.update(changes)
    return MissionProbeOutcome(**values)


def command(**changes):
    values = dict(mission_id=MISSION, run_id=RUN, outcomes=(outcome(),))
    values.update(changes)
    return api().ProbeOutcomeCommitCommand(**values)


def event(**changes):
    values = dict(
        event_id=FACT,
        cursor=MissionRelayCursor(mission_id=MISSION, revision=1, ordinal=1),
        kind=MissionProgressKind.PROBE_OUTCOMES_RECORDED,
        provenance=RelayProvenance.HARNESS_OBSERVED,
        run_id=RUN,
        recorded_at=NOW,
        causation_key=KEY,
    )
    values.update(changes)
    return MissionProgressEvent(**values)


def request(**changes):
    values = dict(mission_id=MISSION, run_id=RUN, page_size=100)
    values.update(changes)
    return api().MissionRelayReadRequest(**values)


def read(**changes):
    page = MissionRelayEventPage(high_water=event().cursor, page_size=100, events=(event(),))
    evidence = MissionEvidenceSnapshot(
        mission=ResearchMission(id=MISSION, title="Bounded probe", keywords=["work bag"], workspace_id=WORKSPACE),
        manifest=None,
        brief=None,
        signals=(),
        qualifications=(),
        outcomes=(outcome(),),
        claims=(),
    )
    run = RunJournal(
        run_id=RUN,
        mission_id=MISSION,
        workspace_id=WORKSPACE,
        journal_path=Path("/inert/run.md"),
        sequence=1,
        status="COMPLETED",
        started_at=NOW,
        completed_at=NOW,
    )
    values = dict(
        request=request(), evidence=evidence, run=run, read_at=NOW, events=page, total_observations=0, source_count=0
    )
    values.update(changes)
    return api().MissionRelayRead(**values)


def test_command_preserves_canonical_fact_and_derives_scoped_identity():
    item = command()
    assert item.command_key == KEY
    assert item.outcomes[0].outcome_id == FACT
    assert item.outcomes[0].scope_attestation["keywords"] == ("work bag",)
    assert len(item.payload_fingerprint) == 64
    assert command(run_id=OTHER, outcomes=(outcome(run_id=OTHER),)).command_key != KEY
    with pytest.raises(FrozenInstanceError):
        item.run_id = OTHER


def test_reordered_batch_replays_the_same_canonical_fact_set():
    first = outcome()
    second = outcome(outcome_id=OTHER, connector_surface="youtube.comments")
    left = command(outcomes=(first, second))
    right = command(outcomes=(second, first))
    assert left.command_key == right.command_key
    assert left.payload_fingerprint == right.payload_fingerprint
    assert {item.outcome_id for item in left.outcomes} == {FACT, OTHER}


@pytest.mark.parametrize(
    "changes",
    (
        {"connector_surface": "youtube.comments"},
        {"platform": "threads"},
    ),
)
def test_disjoint_legacy_batch_keeps_its_distinct_logical_command_scope(changes):
    original = command()
    different = command(outcomes=(outcome(**changes),))
    assert original.command_key != different.command_key
    assert original.payload_fingerprint != different.payload_fingerprint


@pytest.mark.parametrize(
    "changes",
    (
        {"outcome_id": OTHER},
        {"status": ChannelHealthStatus.AUTH_REQUIRED},
        {"note": "Changed fact."},
        {"scope_attestation": {"keywords": ["other query"]}},
        {"query_fingerprint": "b" * 64},
        {"queried_window": "7d"},
        {"queried_keywords": ("other query",)},
        {"completed_at": NOW.replace(day=3)},
        {"collection_plan_digest": "b" * 64},
    ),
)
def test_conflicting_facts_keep_command_identity_but_change_payload(changes):
    original = command()
    changed = command(outcomes=(outcome(**changes),))
    assert changed.command_key == original.command_key == KEY
    assert changed.payload_fingerprint != original.payload_fingerprint


def test_command_freezes_nested_attestation_without_mutating_canonical_input():
    metadata = {"keywords": ["work bag"], "scope": {"geo": "VN"}}
    fact = outcome(scope_attestation=metadata)
    item = command(outcomes=(fact,))
    fingerprint = item.payload_fingerprint
    metadata["keywords"].append("later")
    metadata["scope"]["geo"] = "US"
    assert item.outcomes[0].scope_attestation["keywords"] == ("work bag",)
    assert item.outcomes[0].scope_attestation["scope"]["geo"] == "VN"
    assert item.payload_fingerprint == fingerprint
    assert fact.scope_attestation is metadata
    with pytest.raises(TypeError):
        item.outcomes[0].scope_attestation["scope"]["geo"] = "US"


@pytest.mark.parametrize("shape", ("mapping", "sequence"))
def test_admitted_enum_value_is_an_immutable_snapshot_after_original_mutation(shape):
    class AttestedScope(Enum):
        GEO = {"geo": "VN"} if shape == "mapping" else [{"geo": "VN"}]

    item = command(outcomes=(outcome(scope_attestation={"scope": AttestedScope.GEO}),))
    fingerprint = item.payload_fingerprint
    if shape == "mapping":
        AttestedScope.GEO.value["geo"] = "US"
    else:
        AttestedScope.GEO.value[0]["geo"] = "US"
        AttestedScope.GEO.value.append({"geo": "CA"})

    reconstructed = command(outcomes=item.outcomes)
    assert reconstructed.payload_fingerprint == fingerprint
    assert reconstructed.command_key == item.command_key == KEY
    retained = item.outcomes[0].scope_attestation["scope"]
    if shape == "sequence":
        assert type(retained) is tuple
        assert len(retained) == 1
        retained = retained[0]
    assert retained["geo"] == "VN"
    with pytest.raises(TypeError):
        retained["geo"] = "US"


@pytest.mark.parametrize("location", ("completed_at", "nested_attestation"))
def test_admitted_timestamp_snapshots_instant_before_original_timezone_mutation(location):
    class MutableOffset(tzinfo):
        offset = timedelta(hours=7)

        def utcoffset(self, _dt):
            return self.offset

        def dst(self, _dt):
            return timedelta(0)

    original_zone = MutableOffset()
    original_time = datetime(2026, 10, 4, tzinfo=original_zone)
    changes = (
        {"completed_at": original_time}
        if location == "completed_at"
        else {
            "scope_attestation": {"receipt": {"time": original_time}},
        }
    )
    item = command(outcomes=(outcome(**changes),))
    fingerprint = item.payload_fingerprint
    original_zone.offset = timedelta(0)

    reconstructed = command(outcomes=item.outcomes)
    assert reconstructed.payload_fingerprint == fingerprint
    assert reconstructed.command_key == item.command_key == KEY
    retained = (
        item.outcomes[0].completed_at
        if location == "completed_at"
        else (item.outcomes[0].scope_attestation["receipt"]["time"])
    )
    assert retained == datetime(2026, 10, 3, 17, tzinfo=timezone.utc)
    assert retained.tzinfo is timezone.utc
    assert original_time.tzinfo is original_zone
    assert original_time.utcoffset() == timedelta(0)


@pytest.mark.parametrize("offset", (0, 7, -4))
def test_ordinary_scalar_enum_and_aware_timestamps_retain_canonical_facts(offset):
    class ScalarScope(Enum):
        GEO = "VN"

    time = datetime(2026, 10, 4, 7, tzinfo=timezone(timedelta(hours=offset)))
    item = command(
        outcomes=(
            outcome(
                completed_at=time,
                scope_attestation={
                    "geo": ScalarScope.GEO,
                    "time": time,
                    "missing": None,
                    "scalars": [True, 0, 1.25, "public value"],
                },
            ),
        )
    )
    equivalent = command(
        outcomes=(
            outcome(
                completed_at=time,
                scope_attestation={
                    "geo": "VN",
                    "time": time,
                    "missing": None,
                    "scalars": [True, 0, 1.25, "public value"],
                },
            ),
        )
    )
    assert item.outcomes[0].status is ChannelHealthStatus.EMPTY_NO_DATA
    assert item.outcomes[0].outcome_id == FACT
    assert item.outcomes[0].completed_at == time
    assert item.payload_fingerprint == equivalent.payload_fingerprint
    assert item.command_key == equivalent.command_key == KEY
    assert item.outcomes[0].scope_attestation["missing"] is None
    assert item.outcomes[0].scope_attestation["scalars"] == (True, 0, 1.25, "public value")


@pytest.mark.parametrize("location", ("completed_at", "nested_attestation"))
def test_command_refuses_naive_fact_time_without_inventing_timezone(location):
    naive = NOW.replace(tzinfo=None)
    changes = {"completed_at": naive} if location == "completed_at" else {"scope_attestation": {"time": naive}}
    with pytest.raises(ValueError):
        command(outcomes=(outcome(**changes),))


@pytest.mark.parametrize("number", (float("nan"), float("inf"), float("-inf")))
def test_command_refuses_nonfinite_attestation_facts(number):
    with pytest.raises(ValueError):
        command(outcomes=(outcome(scope_attestation={"measurement": number}),))


@pytest.mark.parametrize(
    "changes",
    (
        {"mission_id": str(MISSION)},
        {"run_id": str(RUN)},
        {"outcomes": ()},
        {"outcomes": [{"run_id": RUN}]},
        {"outcomes": (outcome(run_id=OTHER),)},
        {"outcomes": (outcome(), outcome(outcome_id=OTHER))},
        {"outcomes": (outcome(), outcome(connector_surface="youtube.comments"))},
    ),
)
def test_command_refuses_raw_wrong_run_empty_and_duplicate_facts(changes):
    with pytest.raises(ValueError):
        command(**changes)


def test_committed_receipt_exposes_legacy_result_and_exact_recorded_event():
    item = api().ProbeOutcomeCommitReceipt(
        command_key=KEY,
        payload_fingerprint=command().payload_fingerprint,
        outcome_count=1,
        event=event(),
    )
    assert item.outcome_count == 1
    assert item.event.cursor.position == (1, 1)
    assert item.event.causation_key == KEY
    assert item.event.run_id == RUN


@pytest.mark.parametrize(
    "changes",
    (
        {"command_key": "different"},
        {"payload_fingerprint": "raw payload"},
        {"outcome_count": 0},
        {"outcome_count": True},
        {"event": event(kind=MissionProgressKind.OBSERVATIONS_COMMITTED)},
        {"event": event(provenance=RelayProvenance.HOST_REPORTED)},
    ),
)
def test_receipt_refuses_incompatible_command_result_or_progress(changes):
    values = dict(command_key=KEY, payload_fingerprint=command().payload_fingerprint, outcome_count=1, event=event())
    values.update(changes)
    with pytest.raises(ValueError):
        api().ProbeOutcomeCommitReceipt(**values)


@pytest.mark.parametrize(
    "changes",
    (
        {"mission_id": str(MISSION)},
        {"run_id": str(RUN)},
        {"page_size": 0},
        {"page_size": 201},
        {"page_size": True},
        {"evidence_offset": -1},
        {"after_cursor": MissionRelayCursor(mission_id=OTHER, revision=1, ordinal=1)},
    ),
)
def test_read_request_refuses_unbounded_or_foreign_scope(changes):
    with pytest.raises(ValueError):
        request(**changes)


def test_unknown_run_is_explicit_and_read_envelope_is_internal():
    item = read(request=request(run_id=None), run=None)
    assert item.request.run_id is None
    assert item.run is None
    assert item.high_water == item.events.high_water
    assert item.evidence.mission.id == MISSION
    assert item.read_at == NOW
    assert item.next_evidence_offset is None
    assert not hasattr(item, "to_payload")


def test_read_page_requires_forward_progress_until_the_declared_end():
    with pytest.raises(ValueError):
        read(total_observations=2, source_count=1)


def test_read_page_refuses_impossible_complete_page_source_count():
    item = read()
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Public evidence",
        mission_id=MISSION,
        observation_id=FACT,
        source_id=OTHER,
        captured_at=None,
    )
    evidence = replace(item.evidence, signals=(signal, replace(signal, observation_id=WORKSPACE)))
    with pytest.raises(ValueError):
        read(evidence=evidence, total_observations=2, source_count=2)


def test_read_page_preserves_global_totals_and_exact_continuation():
    item = read()
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Public evidence",
        mission_id=MISSION,
        observation_id=FACT,
        source_id=OTHER,
        captured_at=None,
    )
    evidence = replace(item.evidence, signals=(signal,))
    page = read(evidence=evidence, total_observations=3, source_count=2)
    assert page.total_observations == 3
    assert page.source_count == 2
    assert page.next_evidence_offset == 1
    assert page.evidence.signals[0].observation_id == FACT
    end = read(request=request(evidence_offset=3), total_observations=3, source_count=2)
    assert end.next_evidence_offset is None


def test_unknown_cursor_resync_preserves_snapshot_high_water_without_arrival_replay():
    resync = MissionRelayEventPage(high_water=event().cursor, page_size=100, events=(), resync_required=True)
    item = read(request=request(after_cursor=event().cursor), events=resync)
    assert item.high_water.position == (1, 1)
    assert item.events.resync_required
    assert item.events.events == ()


@pytest.mark.parametrize(
    "change",
    (
        "mission",
        "journal_run",
        "journal_mission",
        "workspace",
        "missing_run",
        "page_scope",
        "page_size",
        "after_cursor",
        "time",
        "count",
        "sources",
        "offset",
    ),
)
def test_read_envelope_refuses_incoherent_identity_or_receipt(change):
    item = read()
    changes = {}
    if change == "mission":
        changes["evidence"] = replace(item.evidence, mission=replace(item.evidence.mission, id=OTHER))
    elif change in ("journal_run", "journal_mission", "workspace"):
        field = {"journal_run": "run_id", "journal_mission": "mission_id", "workspace": "workspace_id"}[change]
        changes["run"] = replace(item.run, **{field: OTHER})
    elif change == "missing_run":
        changes["run"] = None
    elif change == "page_scope":
        changes["request"] = request(mission_id=OTHER)
    elif change == "page_size":
        changes["request"] = request(page_size=1)
    elif change == "after_cursor":
        changes["request"] = request(after_cursor=event().cursor)
    elif change == "time":
        changes["read_at"] = NOW.replace(tzinfo=None)
    elif change == "count":
        changes["total_observations"] = True
    elif change == "sources":
        changes["source_count"] = 1
    else:
        changes["request"] = request(evidence_offset=1)
    with pytest.raises(ValueError):
        read(**changes)


def test_ports_are_separate_narrow_abstract_boundaries_and_preserve_public_producer():
    module = api()
    assert module.IMissionRelayWriter.__abstractmethods__ == {"commit_probe_outcomes"}
    assert module.IMissionRelayReader.__abstractmethods__ == {"load_snapshot"}
    writer = get_type_hints(module.IMissionRelayWriter.commit_probe_outcomes)
    reader = get_type_hints(module.IMissionRelayReader.load_snapshot)
    assert writer["command"] is module.ProbeOutcomeCommitCommand
    assert writer["return"] is module.ProbeOutcomeCommitReceipt
    assert reader["request"] is module.MissionRelayReadRequest
    assert module.MissionRelayRead in reader["return"].__args__
    assert tuple(inspect.signature(IResearchWorkspaceStore.record_probe_outcomes).parameters) == (
        "self",
        "run_id",
        "outcomes",
    )
    with pytest.raises(TypeError):
        module.IMissionRelayReader()
    with pytest.raises(TypeError):
        request(sql="SELECT * FROM observations")
    with pytest.raises(TypeError):
        command(callback=lambda: None)
