"""Mission Manifest contracts for explicit, bounded execution authority."""

from datetime import datetime, timezone

import pytest

from ignis.domain import research_workspace as workspace


NOW = datetime(2026, 9, 30, 9, 0, tzinfo=timezone.utc)


def _contract(name: str):
    assert hasattr(workspace, name), f"{name} is required by the mission-bound contract"
    return getattr(workspace, name)


def _manifest(**overrides):
    AuthorityBoundary = _contract("AuthorityBoundary")
    MissionManifest = _contract("MissionManifest")
    MissionOutputType = _contract("MissionOutputType")
    values = {
        "outcome": "Decide whether the observed problem merits a bounded validation",
        "decision_context": "A founder decides whether to spend one week on validation",
        "required_channels": ("youtube", "threads"),
        "optional_channels": ("tiktok",),
        "authority_boundary": AuthorityBoundary(
            public_http=True,
            official_api=False,
            browser_session=False,
            paid_quota=False,
        ),
        "quota_budget": {"youtube_search_calls": 25},
        "output_type": MissionOutputType.MARKET_ANALYSIS,
        "stop_conditions": ("evidence frame complete", "new authority required"),
        "analysis_policy": "evidence-gated-v1",
        "retention_policy": "retain mission evidence until requester deletes the workspace",
        "created_by": "codex",
        "confirmed_at": NOW,
    }
    values.update(overrides)
    return MissionManifest(**values)


def test_manifest_digest_is_stable_for_equivalent_ordered_payloads():
    first = _manifest()
    replay = _manifest(quota_budget={"youtube_search_calls": 25})

    assert first.manifest_digest == replay.manifest_digest
    assert len(first.manifest_digest) == 64
    assert first.to_payload()["authority_boundary"] == {
        "public_http": True,
        "official_api": False,
        "browser_session": False,
        "paid_quota": False,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"outcome": ""},
        {"required_channels": ()},
        {"required_channels": ("youtube",), "optional_channels": ("youtube",)},
        {"stop_conditions": ()},
        {"analysis_policy": ""},
        {"created_by": ""},
        {"quota_budget": {"youtube_search_calls": -1}},
    ],
)
def test_manifest_refuses_incomplete_or_self_contradictory_boundaries(overrides):
    InvalidMissionManifestError = _contract("InvalidMissionManifestError")

    with pytest.raises(InvalidMissionManifestError):
        _manifest(**overrides)


def test_market_output_requires_a_decision_context():
    InvalidMissionManifestError = _contract("InvalidMissionManifestError")

    with pytest.raises(InvalidMissionManifestError, match="decision_context"):
        _manifest(decision_context="")


def test_authority_boundary_is_boolean_policy_not_a_credential_carrier():
    AuthorityBoundary = _contract("AuthorityBoundary")
    InvalidMissionManifestError = _contract("InvalidMissionManifestError")

    with pytest.raises(InvalidMissionManifestError):
        AuthorityBoundary(public_http="yes", official_api=False, browser_session=False, paid_quota=False)
    with pytest.raises(TypeError):
        AuthorityBoundary(
            public_http=True,
            official_api=False,
            browser_session=False,
            paid_quota=False,
            token="secret",
        )


def test_manifest_is_immutable_after_confirmation():
    manifest = _manifest()

    with pytest.raises((AttributeError, TypeError)):
        manifest.outcome = "a different outcome"
