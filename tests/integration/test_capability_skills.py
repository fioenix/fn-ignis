"""Independent collection and analysis cannot bypass the shared evidence frame."""

import json

import pytest

from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from test_evidence_grounded_market_mission import _candidate, _mission_case


@pytest.mark.parametrize(
    "external_input",
    [
        "/tmp/vendor-market-data.csv",
        "https://example.test/purchased-dataset.parquet",
        '{"rows":[{"trend":"stockout"}]}',
    ],
)
@pytest.mark.asyncio
async def test_external_dataset_is_context_only_at_market_analysis_boundaries(
    external_input, monkeypatch
):
    from ignis.interfaces.mcp import server

    def _must_not_open_components():
        raise AssertionError("External input must be refused before opening runtime components")

    monkeypatch.setattr(server, "get_components", _must_not_open_components)

    for handler in (
        server.handle_get_mission_analysis,
        server.handle_discover_market_opportunities,
        server.handle_generate_mission_artifact,
    ):
        response = json.loads(await handler(external_input))
        assert response["status"] == "CONTEXT_ONLY"
        assert response["reason_code"] == "MISSION_SCOPED_PROVENANCE_REQUIRED"
        assert response["primary_market_evidence"] is False
        assert "analysis_status" not in response
        assert "claim_ledger" not in response


@pytest.mark.parametrize(
    "condition, expected_gate",
    [
        ("auth_blocked", "REQUIRED_CHANNEL_NOT_MEASURED:youtube:AUTH_REQUIRED"),
        ("all_confirmatory", "MISSING_CONTRADICTION_COVERAGE"),
    ],
)
@pytest.mark.asyncio
async def test_analysis_skill_cannot_narrate_around_an_insufficient_frame(
    repository_case, tmp_path, condition, expected_gate
):
    repository = repository_case.repository
    store, mission, signals, frame = await _mission_case(
        repository, tmp_path, condition
    )
    submission = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_candidate(condition, signals)],
        created_by="test-host",
    )
    analysis = await GetMissionAnalysisUseCase(repository, store).execute(mission.id)

    assert submission["analysis_status"] == "INSUFFICIENT_EVIDENCE"
    assert analysis["analysis_status"] == "INSUFFICIENT_EVIDENCE"
    assert expected_gate in analysis["gap_report"]["failed_gates"]
    assert "claim_ledger" not in analysis
    for forbidden in analysis["gap_report"]["withheld_outputs"]:
        assert forbidden not in analysis
