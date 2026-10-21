"""T012 on both backends: the claim-binding trigger refuses SUPPORT on unverifiable content (SC-010)."""

import pytest

from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase

from tests.unit.test_mission_claims import _observation_candidate
from tests.unit.test_unverifiable_source import _eligible_with_unverifiable_support


@pytest.mark.asyncio
async def test_both_triggers_refuse_support_on_unverifiable_content(repository_case, tmp_path):
    repository = repository_case.repository
    store, mission, _signals, frame, unverifiable = await _eligible_with_unverifiable_support(tmp_path, repository)

    result = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id), frame.frame_digest, [_observation_candidate(unverifiable)], created_by="host-agent"
    )

    assert result.get("permitted", 0) == 0, repository_case.name
    assert not [
        claim for claim in await store.list_mission_claims(mission.id) if claim.status.value == "PERMITTED"
    ], repository_case.name
    held = {str(s.observation_id) for s in await repository.get_mission_signals(mission.id)}
    assert str(unverifiable.observation_id) in held, repository_case.name
