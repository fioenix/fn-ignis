"""Privacy and scope of the mission snapshot an agent reads to build a tracking artifact.

R2 retired the built-in viewer, so its header, Host/Origin, CSP and expiry cases went with it. What
remains is the outward surface: get_mission_relay_snapshot must keep each read inside the selected
mission and must never carry private text, structured private metadata or unmasked contact data.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from test_mission_relay_read_boundary import _setup_traps, _state, relay_case  # noqa: F401 -- fixture
from test_mission_relay_mcp import _OwnedRepository, _caller_client, _observe_chain

REFUSED_SCOPE = {"schema_version": 1, "status": "REFUSED", "reason_code": "SCOPE_MISMATCH"}


def _forbid_bootstrap(monkeypatch):
    from ignis.interfaces.mcp import server

    def forbidden(*args, **kwargs):
        raise AssertionError("A snapshot read initialized writable components or credentials")
    monkeypatch.setattr(server, "get_components", forbidden)
    monkeypatch.setattr(server, "create_repository", forbidden)


async def _read(client, mission_id, run_id=None, page_size=200):
    arguments = {"mission_id": mission_id, "page_size": page_size}
    if run_id is not None:
        arguments["run_id"] = run_id
    result = (await client.call_tool("get_mission_relay_snapshot", arguments)).structured_content
    return result, json.dumps(result, ensure_ascii=False)


@pytest.mark.asyncio
async def test_parent_and_child_snapshots_expose_only_their_own_observations(relay_case, monkeypatch, tmp_path):
    from tests.integration.test_mission_follow_up_viewer import _link, _records
    case, parent, child, foreign = await _records(relay_case, tmp_path)
    await _link(case, parent, child)
    # Linked child sightings reuse parent source identities; source equality must not grant membership.
    shared_sources = {pair[1] for pair in parent.pairs} & {pair[1] for pair in child.pairs}
    assert shared_sources, "Fixture must link parent and child sightings through a shared source"
    records = {"parent": parent, "child": child, "foreign": foreign}
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    _forbid_bootstrap(monkeypatch)
    owned = _OwnedRepository(monkeypatch, case)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            for selected in ("parent", "child"):
                record = records[selected]
                snapshot, payload = await _read(client, str(record.mission.id), str(record.run.run_id))
                assert snapshot["status"] == "OK" and snapshot["mission_id"] == str(record.mission.id)
                assert {(row["observation_id"], row["source_id"]) for row in snapshot["evidence"]} == record.pairs
                for other in set(records) - {selected}:
                    for observation, _source in records[other].pairs:
                        assert observation not in payload, f"{selected} snapshot exposes a {other} observation"
            refused, _ = await _read(client, str(parent.mission.id), str(child.run.run_id))
            assert refused == REFUSED_SCOPE, "A parent read must not select a child run"
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)


# Synthetic private values; observation text is persisted raw, so the projection's PII policy must redact it.
PRIVATE_EMAIL = "relay.sentinel@example.com"
PRIVATE_PHONE = "+84 931 405 002"
PRIVATE_SECRET = "sk-RELAYSENTINELabcdefghijklmnop"
STORED_MARKUP = '<img src=x onerror="window.untrustedExecuted=true">'


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_snapshot_masks_private_research_and_observation_text(relay_case, monkeypatch, tmp_path):
    from dataclasses import replace
    from ignis.application.use_cases.record_mission_research_work import RecordMissionResearchWorkUseCase
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    from tests.integration.test_research_recording_mcp_boundary import public_handoff
    from tests.integration.test_research_work_persistence import _arrange
    case, mission, _, _, _, handoff, revision = await _arrange(relay_case, tmp_path)
    private = f"Contact {PRIVATE_EMAIL} or {PRIVATE_PHONE} with {PRIVATE_SECRET}."
    stored = replace(handoff, result=f"Recorded summary. {private} {STORED_MARKUP}",
                     findings=(replace(handoff.findings[0], statement=f"Observations differ. {private}"),))
    recorded = await RecordMissionResearchWorkUseCase(case.repository).execute(
        str(mission.id), public_handoff(stored, revision), host_authorized=True)
    assert recorded["disposition"] == "APPLIED"
    # Research recording already redacts at write time; the stored markup stays text for the agent to escape.
    persisted = await case.repository.load_research_work(mission.id)
    assert STORED_MARKUP in persisted.handoffs[0].result and PRIVATE_EMAIL not in persisted.handoffs[0].result
    await case.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE,
        raw_title=f"Public synthetic sighting {private}", source_url=f"https://example.invalid/{mission.id}/private",
        mission_id=mission.id, captured_at=datetime.now(timezone.utc),
        metadata={"excerpt": f"Public synthetic excerpt {private}"})])
    # The persisted observation really holds the private values, so their absence below is not vacuous.
    raw = next(s for s in await case.repository.get_mission_signals(mission.id)
               if s.raw_title.startswith("Public synthetic sighting"))
    assert all(value in raw.raw_title and value in raw.metadata["excerpt"]
               for value in (PRIVATE_EMAIL, PRIVATE_PHONE, PRIVATE_SECRET))
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    _forbid_bootstrap(monkeypatch)
    owned = _OwnedRepository(monkeypatch, case)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            snapshot, payload = await _read(client, str(mission.id))
            assert snapshot["status"] == "OK" and snapshot["mission_id"] == str(mission.id)
            sighting = next(row for row in snapshot["evidence"] if row["title"].startswith("Public synthetic sighting"))
            assert sighting["observation_id"] == str(raw.observation_id)
            assert sighting["title"].startswith("Public synthetic sighting Contact [REDACTED_EMAIL]")
            assert "Public synthetic excerpt" in (sighting["excerpt"] or "")
            results = [handoff_row["result"] for handoff_row in snapshot["research"]["handoffs"]]
            assert any("Recorded summary." in text and "[REDACTED_EMAIL]" in text for text in results)
            for value in (PRIVATE_EMAIL, PRIVATE_PHONE, PRIVATE_SECRET):
                assert value not in payload, f"The snapshot exposes {value[:12]}"
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)


# Synthetic structured metadata on one public observation. Every value is a unique non-secret sentinel
# that no PII rule redacts, so only the projection's field selection can keep it out of the snapshot.
PUBLIC_TITLE = "Public structured sighting for relay privacy"
PUBLIC_EXCERPT = "Public structured excerpt for relay privacy"
STRUCTURED_SENTINELS = {
    "access_token": "SENTINELACCESSTOKENQ7RELAY",
    "private_messages": "SENTINELPRIVATEMESSAGEQ7RELAY",
    "hidden_reasoning": "SENTINELHIDDENREASONINGQ7RELAY",
    "raw_source_owner_address": "SENTINELOWNERADDRESSQ7RELAY",
    "unknown_nested": "SENTINELUNKNOWNNESTEDQ7RELAY",
}
STRUCTURED_METADATA = {
    "excerpt": PUBLIC_EXCERPT,
    "auth": {"session": {"access_token": STRUCTURED_SENTINELS["access_token"]}},
    "private_messages": [{"direction": "inbound", "text": STRUCTURED_SENTINELS["private_messages"]}],
    "hidden_reasoning": {"summary": STRUCTURED_SENTINELS["hidden_reasoning"]},
    "raw_source": {"owner": {"address": STRUCTURED_SENTINELS["raw_source_owner_address"]}},
    "vendor_extension": {"layer": {"opaque": STRUCTURED_SENTINELS["unknown_nested"]}},
}


def _assert_absent(text, where, forbidden):
    """Report only safe labels, so a failure never echoes the payload, a sentinel or the capability."""
    __tracebackhide__ = True  # The traceback would otherwise print the forbidden values themselves.
    exposed = sorted(label for label, value in forbidden.items() if value in text)
    assert not exposed, f"{where} exposes {', '.join(exposed)}"


def _structured_row(rows, observation_id, source_id, where):
    matches = [row for row in rows if row["observation_id"] == observation_id]
    assert len(matches) == 1, f"{where} lacks the selected observation"
    row = matches[0]
    assert row["source_id"] == source_id, f"{where} changed the source identity"
    assert row["title"] == PUBLIC_TITLE, f"{where} lacks the public title"
    assert PUBLIC_EXCERPT in (row["excerpt"] or ""), f"{where} lacks the public excerpt"
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_snapshot_excludes_structured_private_observation_metadata(
        relay_case, monkeypatch, tmp_path, caplog, capsys):
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    from tests.unit.test_mission_claims import _eligible_mission
    caplog.set_level("DEBUG")
    case = relay_case[0]
    _, _, mission, _, _ = await _eligible_mission(tmp_path, repository=case.repository)
    mission_id = str(mission.id)
    await case.repository.save_signals([TrendSignal(platform=PlatformType.YOUTUBE, raw_title=PUBLIC_TITLE,
        source_url=f"https://example.invalid/{mission_id}/structured", mission_id=mission.id,
        captured_at=datetime.now(timezone.utc), metadata=STRUCTURED_METADATA)])
    # The canonical record really retains every private category, so the absence checks below are not vacuous.
    stored = [s for s in await case.repository.get_mission_signals(mission.id) if s.raw_title == PUBLIC_TITLE]
    assert len(stored) == 1 and stored[0].metadata == STRUCTURED_METADATA, "Storage did not retain the metadata"
    observation_id, source_id = str(stored[0].observation_id), str(stored[0].source_id)
    before = _state(case)
    _setup_traps(monkeypatch, case.repository)
    _forbid_bootstrap(monkeypatch)
    owned = _OwnedRepository(monkeypatch, case)
    with _observe_chain(case, monkeypatch) as observed:
        async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
            snapshot, payload = await _read(client, mission_id)
            assert snapshot["mission_id"] == mission_id and snapshot["run_id"] is None
            _structured_row(snapshot["evidence"], observation_id, source_id, "Snapshot")
            _assert_absent(payload, "Snapshot", STRUCTURED_SENTINELS)
            refused, refusal = await _read(client, "not-an-observation-or-mission")
            assert refused == REFUSED_SCOPE
            _assert_absent(refusal, "Refusal", STRUCTURED_SENTINELS)
        observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    captured = capsys.readouterr()
    _assert_absent(caplog.text, "Captured logs", STRUCTURED_SENTINELS)
    _assert_absent(captured.out + captured.err, "Captured output", STRUCTURED_SENTINELS)


# One dummy privacy class across the remaining outward-text consumers of a single disposable Market mission.
OUTWARD_EMAIL = "outward.sentinel@example.com"
OUTWARD_PUBLIC = "Outward public marker"
# queried_window is free text on MissionProbeOutcome; the real Gap generator copies it into attempted probes.
OUTWARD_WINDOW = f"{OUTWARD_PUBLIC} window {OUTWARD_EMAIL}"


async def _outward_mission(relay_case, tmp_path, monkeypatch):
    """Current permitted claim plus recorded research, through the existing fixture and owner write paths.

    Channel note, probe queried window and claim wording keep the email in storage (read-time masking). Research labels, the host
    receipt, ACK and the cancellation reason are redacted by the owner commit path at write time.
    """
    import tests.unit.test_mission_claims as claim_fixture
    from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
    from ignis.domain.research_work import ReasonWorkPayload
    from ignis.domain.research_workspace import MissionProbeOutcome
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_research_work_persistence import _arrange, _commit
    from tests.unit.test_mission_claims import _observation_candidate
    from uuid import uuid4
    from dataclasses import replace
    with monkeypatch.context() as patch:
        # The fixture's own probe outcomes carry a connector note and queried window through the real
        # record_probe_outcomes path, before the frame and claim exist; surface/status/fingerprint stay as built.
        def outcome(**fields):
            return MissionProbeOutcome(**{**fields, "queried_window": OUTWARD_WINDOW,
                                          "note": f"{OUTWARD_PUBLIC} channel note {OUTWARD_EMAIL}"})
        patch.setattr(claim_fixture, "MissionProbeOutcome", outcome)
        case, mission, domain, port, work, handoff, _ = await _arrange(relay_case, tmp_path)
    store = WorkspaceRepository(repository=case.repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    signal = next(s for s in evidence.signals if s.raw_title == "Demand evidence")
    submitted = await SubmitMissionClaimsUseCase(case.repository, store).execute(str(mission.id), work.inputs.frame_digest,
        [_observation_candidate(signal, wording=f"{OUTWARD_PUBLIC} claim wording {OUTWARD_EMAIL}")], created_by="t081-outward")
    assert submitted["permitted"] == 1
    claim = (await store.load_mission_evidence_snapshot(mission.id)).claims[0]
    revision = (await case.repository.load_research_work(mission.id)).revision
    other = replace(work, work_id=uuid4(), state="ASSIGNED", version=1, dependencies=(), ownership_fence="outward-fence",
                    question=f"{OUTWARD_PUBLIC} question {OUTWARD_EMAIL}", assignee_ref=f"assignee {OUTWARD_EMAIL}")
    assigned = await _commit(case.repository, port, mission, "ASSIGN_WORK", other, revision=revision)
    receipt = domain.ResearchActivityReceipt(work_id=other.work_id, epoch=1, ownership_fence=other.ownership_fence,
        execution_ref=f"{OUTWARD_PUBLIC} execution", occurred_at=handoff.occurred_at,
        fresh_until=handoff.occurred_at + timedelta(days=300), provenance="HOST_REPORTED")
    started = await _commit(case.repository, port, mission, "START_WORK", port.ResearchWorkStartAdmission(
        work_id=other.work_id, expected_version=1, ownership_fence=other.ownership_fence, receipt=receipt),
        revision=assigned.revision)
    finding = replace(handoff.findings[0], finding_id=uuid4(), handoff_id=uuid4(), work_id=other.work_id,
        statement=f"{OUTWARD_PUBLIC} finding {OUTWARD_EMAIL}", limitations=(f"limit {OUTWARD_EMAIL}",),
        open_questions=(f"open {OUTWARD_EMAIL}",), alternative_explanation=f"alternative {OUTWARD_EMAIL}")
    result = replace(handoff, handoff_id=finding.handoff_id, work_id=other.work_id, expected_version=started.work_version,
        ownership_fence=other.ownership_fence, consumer_ref=f"consumer {OUTWARD_EMAIL}",
        result=f"{OUTWARD_PUBLIC} result {OUTWARD_EMAIL}", limitations=(f"handoff limit {OUTWARD_EMAIL}",),
        open_questions=(f"handoff open {OUTWARD_EMAIL}",), findings=(finding,))
    recorded = await _commit(case.repository, port, mission, "SUBMIT_HANDOFF", result, revision=started.revision)
    acked = await _commit(case.repository, port, mission, "ACK_HANDOFF", port.ResearchHandoffAcknowledgement(
        handoff_id=result.handoff_id, consumer_ref=result.consumer_ref, expected_version=recorded.work_version,
        disposition="ACCEPTED", reason_code=None, inputs=result.inputs), revision=recorded.revision)
    cancelled = await _commit(case.repository, port, mission, "REQUEST_CANCEL", ReasonWorkPayload(work_id=work.work_id,
        expected_version=work.version, ownership_fence=work.ownership_fence,
        reason=f"{OUTWARD_PUBLIC} cancel {OUTWARD_EMAIL}"), revision=acked.revision)
    assert [r.disposition for r in (assigned, started, recorded, acked, cancelled)] == ["APPLIED"] * 5
    run = (await store.list_run_journals(mission.id))[0]
    return case, mission, run, signal, claim, other, result, finding, recorded.work_version, cancelled.revision


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_snapshot_masks_outward_text_across_current_and_withdrawn_permission(
        relay_case, monkeypatch, tmp_path, caplog, capsys):
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    from tests.integration.test_research_work_persistence import _sql
    caplog.set_level("DEBUG")
    case, mission, run, signal, claim, other, handoff, finding, ack_version, research_revision = await _outward_mission(
        relay_case, tmp_path, monkeypatch)
    mission_id, run_id = str(mission.id), str(run.run_id)
    # Storage truth first: which values are raw (read-time masking) and which were redacted on write.
    stored = await WorkspaceRepository(repository=case.repository).load_mission_evidence_snapshot(mission.id)
    assert all(OUTWARD_EMAIL in outcome.note for outcome in stored.outcomes), "Channel note was not retained raw"
    assert [o.queried_window for o in stored.outcomes] == [OUTWARD_WINDOW] * 2, "Queried window was not retained raw"
    pairs = {(str(s.observation_id), str(s.source_id)) for s in stored.signals}
    withdrawn = (str(signal.observation_id), str(signal.source_id))
    assert len(pairs) == 6 and withdrawn in pairs
    assert OUTWARD_EMAIL in stored.claims[0].wording, "Claim wording was not retained raw"
    private = {"email": OUTWARD_EMAIL}
    _setup_traps(monkeypatch, case.repository)
    _forbid_bootstrap(monkeypatch)
    owned = _OwnedRepository(monkeypatch, case)
    async with _caller_client(monkeypatch, tmp_path, {"repository": case.repository}) as client:
        # State 1: current permitted claim with recorded research.
        with _observe_chain(case, monkeypatch) as observed:
            data, payload = await _read(client, mission_id, run_id)
            assert (data["mission_id"], data["run_id"]) == (mission_id, run_id)
            assert data["counts"] == {"observations": 6, "sources": 6}
            assert {(e["observation_id"], e["source_id"]) for e in data["evidence"]} == pairs
            gate = data["claim_gate"]
            assert gate["state"] == "CURRENT" and [c["claim_id"] for c in gate["claims"]] == [str(claim.claim_id)]
            assert gate["claims"][0]["frame_digest"] == gate["frame_digest"] == claim.frame_digest
            assert gate["claims"][0]["wording"].startswith(f"{OUTWARD_PUBLIC} claim wording [REDACTED_EMAIL]")
            assert all(c["note"].startswith(f"{OUTWARD_PUBLIC} channel note [REDACTED") for c in data["channels"]
                       if c["status"] is not None)
            view = data["research"]
            assert (view["mission_id"], view["revision"]) == (mission_id, research_revision)
            [recorded] = [h for h in view["handoffs"] if h["handoff_id"] == str(handoff.handoff_id)]
            assert recorded["result"].startswith(f"{OUTWARD_PUBLIC} result [REDACTED_EMAIL]")
            [found] = [f for f in view["findings"] if f["finding_id"] == str(finding.finding_id)]
            assert (found["revision"], found["work_id"]) == (1, str(other.work_id))
            [ack] = [a for a in view["acknowledgements"] if a["handoff_id"] == str(handoff.handoff_id)]
            assert (ack["consumer_ref"], ack["expected_version"], ack["disposition"]) == (
                "consumer [REDACTED_EMAIL]", ack_version, "ACCEPTED")
            assert any(e["kind"] == "CANCELLATION_REQUESTED" and (e["reason"] or "").startswith(
                f"{OUTWARD_PUBLIC} cancel [REDACTED_EMAIL]") for e in data["event_page"]["events"])
            _assert_absent(payload, "Current snapshot", private)
            observed.assert_no_writes()
        # State 2: the existing fixture withdrawal invalidates current permission on the same mission.
        await _sql(case, "DELETE FROM mission_evidence WHERE mission_id=? AND observation_id=?",
                   (mission.id, signal.observation_id))
        before = _state(case)
        with _observe_chain(case, monkeypatch) as observed:
            data, payload = await _read(client, mission_id, run_id)
            gate = data["claim_gate"]
            assert data["counts"] == {"observations": 5, "sources": 5}
            assert {(e["observation_id"], e["source_id"]) for e in data["evidence"]} == pairs - {withdrawn}
            assert gate["state"] == "STALE" and gate["claims"] == []
            assert [h["claim_id"] for h in gate["history"]] == [str(claim.claim_id)]
            assert gate["history"][0]["wording"].startswith(f"{OUTWARD_PUBLIC} claim wording [REDACTED_EMAIL]")
            assert gate["gap_report"]["failed_gates"] == ["MISSING_DEMAND_EVIDENCE"]
            masked_window = f"{OUTWARD_PUBLIC} window [REDACTED_EMAIL]"
            assert sorted((p["connector_surface"], p["status"], p["queried_window"])
                          for p in gate["gap_report"]["attempted_probes"]) == [
                ("google", "HEALTHY", masked_window), ("youtube", "HEALTHY", masked_window)]
            _assert_absent(payload, "Withdrawn snapshot", private)
            observed.assert_no_writes()
    owned.assert_closed_unchanged(case, before)
    captured = capsys.readouterr()
    _assert_absent(caplog.text, "Captured logs", private)
    _assert_absent(captured.out + captured.err, "Captured output", private)
