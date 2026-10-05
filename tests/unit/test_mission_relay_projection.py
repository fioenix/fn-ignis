"""RED contracts for the typed relay projection, before its implementation exists.

Lazy discovery lets each contract collect and fail independently. These initial API
failures do not prove masking or refusal; the assertions after discovery must run
against the real T023 projection. Fixtures are existing canonical domain records,
not mock projection behavior or a substitute evidence policy.
"""

import importlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot, RunJournal
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import (
    AuthorityBoundary,
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
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_data


NOW = datetime(2026, 10, 4, 0, 0, tzinfo=timezone.utc)
MISSION = UUID("11111111-2222-4333-8444-555555555555")
RUN = UUID("22222222-3333-4444-8555-666666666666")
OBSERVATION = UUID("33333333-4444-4555-8666-777777777777")
SOURCE = UUID("44444444-5555-4666-8777-888888888888")
FOREIGN = UUID("55555555-6666-4777-8888-999999999999")
WORKSPACE = UUID("66666666-7777-4888-8999-aaaaaaaaaaaa")
MODULE = "ignis.application.use_cases.get_mission_relay_snapshot"
KINDS = ("snapshot", "inspection")


@pytest.fixture
def records():
    mission = ResearchMission(
        id=MISSION, title="Inspect recorded evidence", keywords=["work bag"],
        workspace_id=WORKSPACE,
        surface="ATTENTION", status="COMPLETED", created_at=NOW, updated_at=NOW,
    )
    manifest = MissionManifest(
        mission_id=MISSION, outcome="Inspect a bounded Attention sample",
        decision_context=None, required_channels=("youtube",), optional_channels=(),
        authority_boundary=AuthorityBoundary(
            public_http=True, official_api=False, browser_session=False, paid_quota=False,
        ),
        quota_budget={}, output_type=MissionOutputType.ATTENTION_REPORT,
        stop_conditions=("sample collected",), analysis_policy="evidence-gated-v1",
        retention_policy="retain recorded evidence", created_by="codex", confirmed_at=NOW,
    )
    signal = TrendSignal(
        observation_id=OBSERVATION, source_id=SOURCE, mission_id=MISSION,
        platform=PlatformType.YOUTUBE, raw_title="Work bag review", metric_value=125000,
        growth_velocity=2.5, source_url="https://www.youtube.com/watch?v=fixture-public",
        captured_at=NOW, published_at=NOW, time_provenance="exact_ingestion",
        metadata={"excerpt": "The handle broke after two weeks."},
    )
    qualification = EvidenceQualification(
        mission_id=MISSION, observation_id=OBSERVATION,
        frame_fingerprint=compute_frame_fingerprint(mission, None),
        relation=QualificationRelation.QUALIFIED_SUPPORT, purpose=EvidencePurpose.DEMAND,
        confidence=0.9, reason_code=QualificationReason.DIRECT_TO_FRAME,
        judged_by="codex", created_at=NOW,
    )
    outcome = MissionProbeOutcome(
        run_id=RUN, platform="youtube", connector_surface="youtube.search",
        status=ChannelHealthStatus.HEALTHY, signals_collected=1,
        query_fingerprint=compute_query_fingerprint(("work bag",), mission.geo_code, "7d"),
        completed_at=NOW, queried_keywords=("work bag",),
        queried_window="7d", collection_plan_digest="c" * 64,
        scope_attestation={"geo": "VN", "timeframe": "7d"},
    )
    evidence = MissionEvidenceSnapshot(
        mission=mission, manifest=manifest, brief=None, signals=(signal,),
        qualifications=(qualification,), outcomes=(outcome,), claims=(),
    )
    run = RunJournal(
        run_id=RUN, mission_id=MISSION, workspace_id=WORKSPACE,
        journal_path=Path("private/run-journal.md"), sequence=1, status="COMPLETED",
        started_at=NOW, completed_at=NOW,
    )
    return evidence, run


def _projection(kind, evidence, run, **overrides):
    """Call the real consuming API; do not skip, xfail or fabricate missing code."""
    name = f"project_mission_relay_{kind}"
    try:
        module = importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise  # Missing dependencies inside a future module are setup errors.
        pytest.fail(f"T005 API RED: {MODULE}.{name} is not implemented", pytrace=False)
    project = getattr(module, name, None)
    assert callable(project), f"T005 API RED: {name} must implement the typed projection"
    arguments = {
        "selected_mission_id": MISSION, "selected_run_id": RUN,
        "evidence": evidence, "run": run, "revision": 7, "read_at": NOW,
        "page_size": 100,
    }
    if kind == "inspection":
        arguments["observation_id"] = OBSERVATION
    arguments.update(overrides)
    result = project(**arguments)
    assert not isinstance(result, dict), "The consuming API must return a typed safe result"
    payload = result.to_payload()
    # This is the exact outward boundary, including every nested field and key.
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    return payload, serialized


def _observation(kind, payload):
    return payload["evidence"][0] if kind == "snapshot" else payload["observation"]


@pytest.mark.parametrize("kind", KINDS)
def test_safe_projection_preserves_immutable_identity_and_recorded_values(records, kind):
    """Catch title/URL identity substitution or over-masking legitimate evidence."""
    payload, _ = _projection(kind, *records)
    row = _observation(kind, payload)
    assert payload["mission_id"] == str(MISSION)
    assert payload["run_id"] == str(RUN)
    assert payload["revision"] == 7
    assert row["observation_id"] == str(OBSERVATION)
    assert row["source_id"] == str(SOURCE)
    assert row["title"] == "Work bag review"
    assert row["source_url"] == "https://www.youtube.com/watch?v=fixture-public"
    assert row["metric_value"] == 125000
    assert row["published_at"] == NOW.isoformat()


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("mismatch", (
    "selected_mission", "selected_run", "journal_mission", "journal_run", "journal_workspace",
    "signal_mission", "manifest_mission", "qualification_mission",
    "qualification_observation", "outcome_run",
))
def test_projection_refuses_each_incompatible_identity_without_echo(records, kind, mismatch):
    """Catch one unchecked mission/run/reference path admitting foreign evidence."""
    evidence, run = records
    overrides = {}
    if mismatch == "selected_mission":
        overrides["selected_mission_id"] = FOREIGN
    elif mismatch == "selected_run":
        overrides["selected_run_id"] = FOREIGN
    elif mismatch == "journal_mission":
        run = replace(run, mission_id=FOREIGN)
    elif mismatch == "journal_run":
        run = replace(run, run_id=FOREIGN)
    elif mismatch == "journal_workspace":
        run = replace(run, workspace_id=FOREIGN)
    elif mismatch == "signal_mission":
        evidence = replace(evidence, signals=(replace(evidence.signals[0], mission_id=FOREIGN),))
    elif mismatch == "manifest_mission":
        evidence = replace(evidence, manifest=replace(evidence.manifest, mission_id=FOREIGN))
    elif mismatch.startswith("qualification_"):
        field = "mission_id" if mismatch.endswith("mission") else "observation_id"
        evidence = replace(evidence, qualifications=(replace(evidence.qualifications[0], **{field: FOREIGN}),))
    else:
        evidence = replace(evidence, outcomes=(replace(evidence.outcomes[0], run_id=FOREIGN),))
    evidence.signals[0].raw_title = "foreign-record-payload-sentinel"
    payload, serialized = _projection(kind, evidence, run, **overrides)
    assert payload["status"] == "REFUSED"
    assert payload["reason_code"] == "SCOPE_MISMATCH"
    assert "foreign-record-payload-sentinel" not in serialized
    assert "private/run-journal.md" not in serialized


@pytest.mark.parametrize("kind", KINDS)
def test_projection_allowlist_drops_raw_metadata_and_unknown_attributes(records, kind):
    """Catch recursive raw-record/asdict serialization, including nested extras."""
    evidence, run = records
    signal = evidence.signals[0]
    signal.metadata.update({
        "access_token": "credential-field-sentinel",
        "private_messages": [{"text": "private-message-sentinel"}],
        "hidden_reasoning": {"trace": ["hidden-reasoning-sentinel"]},
        "raw_source": {"owner": {"address": "personal-address-sentinel"}},
        "new_unrecognized_field": {"nested": ["unknown-metadata-sentinel"]},
    })
    signal.unexpected_payload = {"nested": ["unknown-signal-attribute-sentinel"]}
    evidence.mission.unexpected_payload = {"nested": ["unknown-mission-attribute-sentinel"]}
    payload, serialized = _projection(kind, evidence, run)
    row = _observation(kind, payload)
    assert "metadata" not in row
    assert row["excerpt"] == "The handle broke after two weeks."
    for sentinel in (
        "credential-field-sentinel", "private-message-sentinel", "hidden-reasoning-sentinel",
        "personal-address-sentinel", "unknown-metadata-sentinel",
        "unknown-signal-attribute-sentinel", "unknown-mission-attribute-sentinel",
        "private/run-journal.md",
    ):
        assert sentinel not in serialized


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", ("title", "excerpt", "channel_note"))
def test_projection_masks_public_text_in_entire_serialized_result(records, kind, field):
    """Catch redaction on only the headline while nested text still leaks."""
    evidence, run = records
    sensitive = "Public review; contact 0931405002 or relay-person@example.invalid; access_token=relay-secret-sentinel"
    if field == "title":
        evidence.signals[0].raw_title = sensitive
    elif field == "excerpt":
        evidence.signals[0].metadata["excerpt"] = sensitive
    else:
        evidence = replace(evidence, outcomes=(replace(evidence.outcomes[0], note=sensitive),))
    payload, serialized = _projection(kind, evidence, run)
    _observation(kind, payload)  # Blanket refusal is not a successful safe observation.
    for sentinel in ("0931405002", "relay-person@example.invalid", "relay-secret-sentinel"):
        assert sentinel not in serialized
    if field != "channel_note":
        text = _observation(kind, payload)[field]
        assert "Public review" in text
        assert "[REDACTED_PHONE]" in text
        assert "[REDACTED_EMAIL]" in text
        assert "[REDACTED_SECRET]" in text
    if field == "title":
        assert evidence.signals[0].raw_title == sensitive
    elif field == "excerpt":
        assert evidence.signals[0].metadata["excerpt"] == sensitive
    else:
        assert evidence.outcomes[0].note == sensitive


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("url", (
    "javascript:alert('dangerous-url-sentinel')",
    "data:text/html,<script>dangerous-url-sentinel</script>",
    "file:///private/dangerous-url-sentinel",
    "https://user:dangerous-url-sentinel@example.invalid/source",
    "https://example.invalid/source?access_token=dangerous-url-sentinel",
))
def test_projection_does_not_publish_executable_or_credential_urls(records, kind, url):
    """Catch unsafe navigation or credential leakage from an otherwise public record."""
    evidence, run = records
    evidence.signals[0].source_url = url
    payload, serialized = _projection(kind, evidence, run)
    row = _observation(kind, payload)
    assert "dangerous-url-sentinel" not in serialized
    safe_url = row["source_url"]
    assert safe_url is None or safe_url.startswith(("https://", "http://"))
    if safe_url is not None:
        parsed = urlsplit(safe_url)
        assert parsed.username is None
        assert parsed.password is None
    assert evidence.signals[0].source_url == url


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", ("metric_value", "growth_velocity", "published_at", "captured_at"))
def test_projection_preserves_missing_numeric_and_timestamp_facts(records, kind, field):
    """Catch a default zero or ingestion/read clock substituted for an unknown fact."""
    evidence, run = records
    setattr(evidence.signals[0], field, None)
    if field == "captured_at":
        evidence.signals[0].time_provenance = "legacy_publish_only"
    payload, _ = _projection(kind, evidence, run)
    assert _observation(kind, payload)[field] is None
    assert payload["read_at"] == NOW.isoformat()


@pytest.mark.parametrize("kind", KINDS)
def test_projection_preserves_a_measured_zero(records, kind):
    """Catch truthiness-based masking that turns a recorded zero into unknown."""
    evidence, run = records
    evidence.signals[0].metric_value = 0
    payload, _ = _projection(kind, evidence, run)
    assert _observation(kind, payload)["metric_value"] == 0


def test_inspection_refuses_an_observation_outside_selected_membership(records):
    """Catch resolving an arbitrary global observation ID outside this snapshot."""
    payload, serialized = _projection("inspection", *records, observation_id=FOREIGN)
    assert payload["status"] == "REFUSED"
    assert payload["reason_code"] == "SCOPE_MISMATCH"
    assert "Work bag review" not in serialized


def test_unavailable_snapshot_does_not_become_successful_measured_emptiness(records):
    """Catch missing read data rendered as a fresh zero-count successful snapshot."""
    _, run = records
    payload, _ = _projection("snapshot", None, run)
    assert payload["status"] == "UNAVAILABLE"
    assert payload["reason_code"]
    assert payload.get("counts") is None
    assert payload.get("evidence") is None


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("page_size", (0, 201))
def test_projection_refuses_out_of_bound_page_sizes(records, kind, page_size):
    """Catch clamping an invalid request rather than an explicit bounded refusal."""
    payload, _ = _projection(kind, *records, page_size=page_size)
    assert payload["status"] == "REFUSED"
    assert payload["reason_code"] == "INVALID_PAGE_SIZE"


@pytest.mark.parametrize("kind", KINDS)
def test_projection_refuses_oversized_json_without_silent_text_truncation(records, kind):
    """Catch oversized output or truncation disguised as successful evidence."""
    evidence, run = records
    evidence.signals[0].raw_title = "x" * 1_048_577
    payload, serialized = _projection(kind, evidence, run)
    assert payload["status"] == "REFUSED"
    assert payload["reason_code"] == "RESPONSE_TOO_LARGE"
    assert len(serialized.encode("utf-8")) <= 1_048_576


def test_existing_recursive_sanitizer_masks_secrets_but_preserves_evidence_identity():
    """Real positive control only; this does not exercise the absent relay projection."""
    raw = {
        "observation_id": str(OBSERVATION), "source_id": str(SOURCE),
        "nested": [{"text": "125000 views; contact 0931405002 or relay-person@example.invalid"}],
        "access_token": "control-secret-sentinel",
    }
    safe = sanitize_pii_data(raw)
    serialized = json.dumps(safe, ensure_ascii=False, allow_nan=False)
    assert safe["observation_id"] == str(OBSERVATION)
    assert safe["source_id"] == str(SOURCE)
    assert "125000 views" in safe["nested"][0]["text"]
    for sentinel in ("0931405002", "relay-person@example.invalid", "control-secret-sentinel"):
        assert sentinel not in serialized
    assert raw["access_token"] == "control-secret-sentinel"
