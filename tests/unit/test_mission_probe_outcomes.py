"""Collection plans and probe outcomes state exactly what one bounded run measured."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    InvalidEvidenceQualificationError,
    MissionManifest,
    MissionOutputType,
    MissionProbeOutcome,
    build_evidence_frame,
    derive_collection_plan,
    require_complete_channel_outcomes,
)


NOW = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)


def _manifest():
    return MissionManifest(
        mission_id=uuid4(),
        outcome="Collect one transparent evidence frame",
        decision_context=None,
        required_channels=("youtube",),
        optional_channels=("threads",),
        authority_boundary=AuthorityBoundary(
            public_http=True,
            official_api=True,
            browser_session=False,
            paid_quota=False,
        ),
        quota_budget={"youtube_search_calls": 2},
        output_type=MissionOutputType.COLLECTION_FRAME,
        stop_conditions=("one run completed",),
        analysis_policy="evidence-gated-v1",
        retention_policy="mission-only",
        created_by="contract-test",
        confirmed_at=NOW,
    )


def _outcome(status, *, surface="youtube", count=0, note="Operational state recorded"):
    measured = status in (ChannelHealthStatus.HEALTHY, ChannelHealthStatus.EMPTY_NO_DATA)
    return MissionProbeOutcome(
        run_id=uuid4(),
        platform=surface,
        connector_surface=surface,
        status=status,
        signals_collected=count,
        queried_keywords=("retail setup friction",) if measured else (),
        queried_window="7d" if measured else None,
        query_fingerprint="a" * 64,
        completed_at=NOW,
        scope_attestation={"geo": "VN", "timeframe": "7d"} if measured else None,
        note=note,
        collection_plan_digest="b" * 64,
    )


def test_collection_plan_projects_every_surface_scope_role_authority_and_sampling():
    manifest = _manifest()

    plan = derive_collection_plan(
        mission_id=manifest.mission_id,
        manifest=manifest,
        keywords=("retail setup friction",),
        geo="VN",
        timeframe="7d",
        evidence_targets=("attention_question",),
        expected_role="CONTEXT",
        surface_requirements={
            "youtube": {
                "authority_tier": "official_api",
                "connector_path": "youtube.search",
                "connector_revision": "v3",
                "sampling": {"limit": 20, "ordering": "platform_default"},
            },
            "threads": {
                "authority_tier": "official_api",
                "connector_path": "threads.search",
                "connector_revision": "v1",
                "sampling": {"limit": 20, "ordering": "platform_default"},
            },
        },
    )

    assert plan["version"] == "collection-plan/v1"
    assert plan["manifest_digest"] == manifest.manifest_digest
    assert [probe["connector_surface"] for probe in plan["probes"]] == ["youtube", "threads"]
    for probe in plan["probes"]:
        assert probe["query_families"]["root"] == ["retail setup friction"]
        assert probe["evidence_targets"] == ["attention_question"]
        assert probe["expected_role"] == "CONTEXT"
        assert probe["scope"] == {
            "geo": "VN",
            "audience": None,
            "language": None,
            "timeframe": "7d",
        }
        assert probe["sampling"]["ordering"] == "platform_default"
        assert probe["authority_tier"] == "official_api"
        assert probe["connector_path"].endswith(".search")
        assert probe["connector_revision"] in {"v1", "v3"}
    assert len(plan["plan_digest"]) == 64


def test_market_collection_plan_separates_support_counterevidence_and_context_probes():
    manifest = _manifest()
    common_families = {"root": (), "expanded": (), "exclusions": ()}

    plan = derive_collection_plan(
        mission_id=manifest.mission_id,
        manifest=manifest,
        keywords=("retail setup friction",),
        geo="VN",
        timeframe="7d",
        surface_requirements={
            surface: {
                "authority_tier": "official_api",
                "connector_path": f"{surface}.search",
                "connector_revision": "v1",
                "sampling": {"limit": 20, "ordering": "platform_default"},
            }
            for surface in manifest.allowed_resources
        },
        evidence_targets=("core",),
        expected_role="SUPPORT",
        probe_intents=(
            {
                "evidence_targets": ("core",),
                "expected_role": "SUPPORT",
                "query_families": {**common_families, "root": ("retail setup friction",)},
            },
            {
                "evidence_targets": ("core",),
                "expected_role": "CONTRADICTION",
                "query_families": {
                    **common_families,
                    "falsification": ("operators reject setup tools",),
                },
            },
            {
                "evidence_targets": ("neutral",),
                "expected_role": "CONTEXT",
                "query_families": {**common_families, "root": ("retail setup friction",)},
            },
        ),
    )

    youtube = [probe for probe in plan["probes"] if probe["connector_surface"] == "youtube"]
    assert [(probe["evidence_targets"], probe["expected_role"]) for probe in youtube] == [
        (["core"], "SUPPORT"),
        (["core"], "CONTRADICTION"),
        (["neutral"], "CONTEXT"),
    ]
    assert youtube[1]["query_families"]["falsification"] == [
        "operators reject setup tools"
    ]
    assert ExecuteMissionUseCase._collection_queries(plan) == [
        "retail setup friction",
        "operators reject setup tools",
    ]


@pytest.mark.parametrize(
    "status",
    [
        ChannelHealthStatus.EMPTY_NO_DATA,
        ChannelHealthStatus.AUTH_REQUIRED,
        ChannelHealthStatus.RATE_LIMITED,
        ChannelHealthStatus.DEGRADED,
        ChannelHealthStatus.FAILED,
        ChannelHealthStatus.NOT_REQUESTED,
    ],
)
def test_every_non_healthy_channel_state_requires_an_operational_note(status):
    with pytest.raises(InvalidEvidenceQualificationError, match="operational note"):
        _outcome(status, note=None)


@pytest.mark.parametrize("status", [ChannelHealthStatus.HEALTHY, ChannelHealthStatus.EMPTY_NO_DATA])
def test_measured_states_require_scope_attestation(status):
    outcome = _outcome(
        status,
        count=1 if status is ChannelHealthStatus.HEALTHY else 0,
    )
    with pytest.raises(InvalidEvidenceQualificationError, match="scope_attestation"):
        MissionProbeOutcome(**{**outcome.__dict__, "scope_attestation": None})


def test_complete_outcomes_distinguish_measured_zero_from_every_unmeasured_state():
    manifest = _manifest()
    run_id = uuid4()
    outcomes = [
        MissionProbeOutcome(**{**_outcome(ChannelHealthStatus.EMPTY_NO_DATA).__dict__, "run_id": run_id}),
        MissionProbeOutcome(
            **{
                **_outcome(ChannelHealthStatus.NOT_REQUESTED, surface="threads").__dict__,
                "run_id": run_id,
            }
        ),
    ]

    require_complete_channel_outcomes(
        manifest.required_channels, manifest.optional_channels, outcomes
    )
    assert outcomes[0].measures_zero is True
    assert outcomes[1].measures_zero is False


def test_evidence_frame_digest_is_order_stable_but_changes_on_association_or_requalification():
    manifest = _manifest()
    common = {
        "mission_id": manifest.mission_id,
        "brief_revision_id": None,
        "manifest_digest": manifest.manifest_digest,
        "collection_plan_digest": "b" * 64,
        "analysis_policy": manifest.analysis_policy,
        "observations": [
            {"observation_id": "o-2", "content_digest": "2" * 64},
            {"observation_id": "o-1", "content_digest": "1" * 64},
        ],
        "qualifications": [
            {"observation_id": "o-1", "relation": "QUALIFIED_SUPPORT"},
        ],
        "channel_outcomes": [
            {"connector_surface": "youtube", "status": "EMPTY_NO_DATA"},
        ],
    }
    baseline = build_evidence_frame(**common)
    reordered = build_evidence_frame(
        **{**common, "observations": list(reversed(common["observations"]))}
    )
    reassessed = build_evidence_frame(
        **{
            **common,
            "qualifications": [
                {"observation_id": "o-1", "relation": "QUALIFIED_CONTRADICTION"}
            ],
        }
    )
    reassociated = build_evidence_frame(
        **{
            **common,
            "observations": common["observations"] + [
                {"observation_id": "o-prior", "content_digest": "3" * 64}
            ],
        }
    )
    provenance_changed = build_evidence_frame(
        **{
            **common,
            "observations": [
                {**common["observations"][0], "metadata": {"probe_keyword": "changed"}},
                common["observations"][1],
            ],
        }
    )
    evaluator_changed = build_evidence_frame(
        **{
            **common,
            "qualifications": [
                {**common["qualifications"][0], "judged_by": "different-evaluator"}
            ],
        }
    )
    outcome_scope_changed = build_evidence_frame(
        **{
            **common,
            "channel_outcomes": [
                {
                    **common["channel_outcomes"][0],
                    "queried_keywords": ["different query"],
                }
            ],
        }
    )

    assert baseline.frame_digest == reordered.frame_digest
    assert baseline.frame_digest != reassessed.frame_digest
    assert baseline.frame_digest != reassociated.frame_digest
    assert baseline.frame_digest != provenance_changed.frame_digest
    assert baseline.frame_digest != evaluator_changed.frame_digest
    assert baseline.frame_digest != outcome_scope_changed.frame_digest
