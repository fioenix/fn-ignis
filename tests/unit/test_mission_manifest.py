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
        {"analysis_policy": "x" * 129},
        {"created_by": ""},
        {"created_by": "x" * 129},
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
    digest = manifest.manifest_digest
    with pytest.raises(TypeError):
        manifest.quota_budget["youtube_search_calls"] = 999
    assert manifest.manifest_digest == digest


def test_manifest_authorizes_only_declared_connector_surfaces():
    InvalidMissionAuthorizationError = _contract("InvalidMissionAuthorizationError")
    manifest = _manifest(required_channels=("youtube",), optional_channels=("threads",))

    manifest.require_execution_authority(
        resources=("youtube",),
        authority=("public_http",),
    )

    with pytest.raises(InvalidMissionAuthorizationError) as excinfo:
        manifest.require_execution_authority(
            resources=("tiktok_video_grid",),
            authority=("browser_session",),
        )

    assert excinfo.value.reason_code == "OUT_OF_SCOPE_RESOURCE"
    assert excinfo.value.out_of_scope_resources == ("tiktok_video_grid",)


@pytest.mark.parametrize(
    ("required_authority", "reason_code"),
    [
        (("browser_session",), "MISSING_AUTHORITY"),
        (("official_api",), "MISSING_AUTHORITY"),
        (("paid_quota",), "MISSING_AUTHORITY"),
    ],
)
def test_manifest_refuses_browser_token_and_paid_quota_outside_boundary(
    required_authority, reason_code
):
    InvalidMissionAuthorizationError = _contract("InvalidMissionAuthorizationError")
    manifest = _manifest(required_channels=("youtube",), optional_channels=())

    with pytest.raises(InvalidMissionAuthorizationError) as excinfo:
        manifest.require_execution_authority(
            resources=("youtube",),
            authority=required_authority,
        )

    assert excinfo.value.reason_code == reason_code
    assert excinfo.value.missing_authority == required_authority


def test_manifest_refuses_material_scope_change_and_budget_overrun():
    InvalidMissionAuthorizationError = _contract("InvalidMissionAuthorizationError")
    manifest = _manifest(
        required_channels=("youtube",),
        optional_channels=(),
        quota_budget={"youtube_search_calls": 2},
    )

    with pytest.raises(InvalidMissionAuthorizationError) as scope_exc:
        manifest.require_execution_authority(
            resources=("youtube",),
            authority=("public_http",),
            material_scope_change=True,
        )
    assert scope_exc.value.reason_code == "MATERIAL_SCOPE_CHANGE"

    with pytest.raises(InvalidMissionAuthorizationError) as quota_exc:
        manifest.require_execution_authority(
            resources=("youtube",),
            authority=("public_http",),
            quota_costs={"youtube_search_calls": 3},
        )
    assert quota_exc.value.reason_code == "QUOTA_BUDGET_EXCEEDED"
    assert quota_exc.value.quota_overruns == {"youtube_search_calls": {"budget": 2, "requested": 3}}


def test_manifest_authority_check_is_retry_stable_and_never_mutates_the_boundary():
    manifest = _manifest(required_channels=("youtube",), optional_channels=())
    original_digest = manifest.manifest_digest

    for _ in range(2):
        manifest.require_execution_authority(
            resources=("youtube",),
            authority=("public_http",),
            quota_costs={"youtube_search_calls": 1},
        )

    assert manifest.manifest_digest == original_digest
