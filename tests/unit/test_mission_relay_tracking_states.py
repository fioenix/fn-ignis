"""Every tracking-artifact display state has a snapshot source (T099).

specs/014-evidence-factory/data-model.md "Tracking artifact" maps each state an agent-generated
artifact may show to snapshot fields. These tests read canonical records through the real
projection and fail if a mapped source is absent, so the ignis-track guidance never asks an
agent to infer a state. Research work states and finding revisions are covered by
tests/integration/test_mission_relay_research_projection.py.
"""
from dataclasses import replace
from datetime import datetime

import pytest

from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.mission_relay import RelayChannelOutcome, RelayFramePendingReason
from test_mission_relay_claim_gate import gate, market_records, project  # noqa: F401 -- canonical fixture

pytestmark = pytest.mark.asyncio


async def test_permitted_state_comes_from_current_gate_and_exact_frame_claims(market_records):  # noqa: F811
    _, _, evidence, run, _ = market_records
    payload = project(evidence, run)
    actual = gate(payload)
    assert actual["state"] == "CURRENT"
    assert actual["render_status"] == "PERMITTED"
    assert actual["frame_digest"] == payload["frame_digest"] is not None
    assert actual["claims"], "The fixture must expose one permitted claim"
    for claim in actual["claims"]:
        assert claim["status"] == "PERMITTED"
        assert claim["frame_digest"] == actual["frame_digest"]
    assert "withheld-control" not in {claim["client_claim_key"] for claim in actual["claims"]}, \
        "A withheld claim must never appear among permitted claims"


@pytest.mark.parametrize("status", ["STARTED", "RUNNING", "FAILED", "CANCELLED"])
async def test_withheld_state_comes_from_gate_state_reason_and_gap_report(market_records, status):  # noqa: F811
    _, _, evidence, run, _ = market_records
    payload = project(evidence, replace(run, status=status))
    actual = gate(payload)
    assert actual["state"] in {"PENDING", "UNAVAILABLE"}
    assert actual["render_status"] == "WITHHELD" and actual["claims"] == []
    assert isinstance(actual["reason_code"], str) and actual["reason_code"], \
        "A withheld gate must carry a reason code the artifact can show"
    assert actual["gap_report"] is not None, "A withheld gate must carry the gap the artifact shows"


async def test_stale_state_comes_from_gate_state_and_labeled_history(market_records):  # noqa: F811
    _, _, evidence, run, _ = market_records
    changed = replace(evidence.signals[0], raw_title="A changed canonical observation")
    actual = gate(project(replace(evidence, signals=(changed, *evidence.signals[1:])), run))
    assert actual["render_status"] == "WITHHELD" and actual["claims"] == []
    assert actual["state"] in {"STALE", "HISTORY"}
    assert actual["history"] and all(claim["status"] != "PERMITTED" for claim in actual["history"]), \
        "Earlier claims stay visible only as history without permission"
    assert isinstance(actual["reason_code"], str) and actual["reason_code"]


async def test_missing_states_come_from_frame_pending_reason_and_channel_status(market_records):  # noqa: F811
    _, _, evidence, run, _ = market_records
    pending = project(evidence, replace(run, status="RUNNING"))
    assert pending["frame_digest"] is None
    assert pending["frame_pending_reason"] in {reason.value for reason in RelayFramePendingReason}
    bound = project(evidence, run)
    assert bound["frame_digest"] is not None and bound["frame_pending_reason"] is None
    for payload in (pending, bound):
        assert isinstance(payload["channels"], list)
        for channel in payload["channels"]:
            assert set(channel) >= {"platform", "status", "signals_collected", "completed_at"}
            assert channel["status"] is None or channel["status"] in {s.value for s in ChannelHealthStatus}
            if channel["status"] is None:
                assert channel["signals_collected"] is None, "An unmeasured channel must not report a count"


async def test_unmeasured_channel_is_null_not_zero():
    payload = RelayChannelOutcome(platform="tiktok", connector_surface=None, status=None,
                                  signals_collected=None, completed_at=None, note=None).to_payload()
    assert payload["status"] is None and payload["signals_collected"] is None, \
        "An unmeasured channel must stay unknown so an artifact cannot show it as zero demand"


async def test_point_in_time_state_comes_from_read_time_revision_and_totals(market_records):  # noqa: F811
    _, _, evidence, run, _ = market_records
    payload = project(evidence, run)
    read_at = datetime.fromisoformat(payload["read_at"])
    assert read_at.tzinfo is not None
    assert isinstance(payload["revision"], int)
    assert payload["mission_id"] == str(evidence.mission.id)
    assert payload["run_id"] == str(run.run_id)
    assert set(payload["counts"]) == {"observations", "sources"}
    assert {"page_size", "evidence_offset", "next_evidence_offset", "collection_state"} <= set(payload)
    assert payload["research"]["availability"] in {"AVAILABLE", "SCHEMA_UNAVAILABLE"}
