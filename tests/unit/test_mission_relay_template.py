"""Maintained template boundary: typed escaped data and inert offline text."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ignis.domain.mission_relay import MissionRelayCursor, MissionRelaySnapshot, RelayObservation
from ignis.domain.research_workspace import EvidenceRole, ResearchSurface
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


def _snapshot(title=None):
    mission = uuid4()
    evidence = () if title is None else (RelayObservation(
        mission_id=mission, observation_id=uuid4(), source_id=uuid4(), title=title,
        excerpt=title, source_url=None, metric_value=None, growth_velocity=None,
        published_at=None, captured_at=None, evidence_role=EvidenceRole.ATTENTION_CONTEXT,
        direction=None,
    ),)
    return MissionRelaySnapshot(mission_id=mission, run_id=None,
        high_water=MissionRelayCursor(mission_id=mission, revision=0, ordinal=0),
        read_at=datetime.now(timezone.utc), page_size=100, evidence=evidence,
        total_observations=len(evidence), source_count=len(evidence), surface=ResearchSurface.ATTENTION)


def _build(snapshot, url="http://127.0.0.1:43118/view/inert-fixture/snapshot"):
    build = getattr(HtmlArtifactBuilder(), "build_mission_relay_artifact", None)
    assert callable(build), "T027 API RED: maintained typed relay builder is absent"
    return build(snapshot, snapshot_url=url, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15))


def test_maintained_initial_document_has_readable_offline_receipt_and_theme():
    snapshot = _snapshot()
    html = _build(snapshot)
    assert 'product-mode' in html
    for value in (str(snapshot.mission_id), snapshot.read_at.isoformat(), "Unknown", "Sources", "Cleaning", "Research", "Cross-check", "Synthesis"):
        assert value in html
    assert '--color-foreground:' in html and '--color-chart-1:' in html
    assert '<noscript>' in html
    assert 'inert-fixture' not in html, "Capability path must not be copied into document data"


def test_typed_builder_escapes_markup_and_script_termination():
    title = '</script><script>window.privateMarker = 1</script><img src=x onerror=alert(1)> Trà'
    html = _build(_snapshot(title))
    assert title not in html
    assert '&lt;img' in html
    assert '\\u003c/script\\u003e' in html
    assert 'Trà' in html or '\\u00e0' in html


def test_builder_rejects_untyped_repository_payload():
    with pytest.raises(ValueError):
        _build({"mission_id": str(uuid4()), "raw_metadata": "not an outward record"})


@pytest.mark.parametrize("url", (
    "https://foreign.invalid/snapshot", "http://localhost:43118/view/inert/snapshot",
    "http://user:password@127.0.0.1:43118/view/inert/snapshot", "javascript:alert(1)",
    "http://127.0.0.1:43118/view/inert/snapshot?token=private", "http://127.0.0.1:43118/view/inert/snapshot#private",
    "http://127.0.0.1:43118/view//snapshot", "http://127.0.0.1:43118/view/inert/extra/snapshot",
    "http://127.0.0.1:43118/view/inert/../../snapshot", "http://127.0.0.1:43118/view/inert%2Fother/snapshot",
))
def test_builder_refuses_external_or_secret_bearing_read_targets(url):
    with pytest.raises(ValueError):
        _build(_snapshot(), url)
