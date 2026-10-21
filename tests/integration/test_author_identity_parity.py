"""T011: removing author identity changes no claim, permission or Gap Report outcome (SC-008).

The claim fixture runs twice on each backend. Once as it is, and once with every sighting
carrying author fields and a handle link that the collection pass's policy then strips. Apart from
ids and digests, the two runs must give the same claims, the same permissions and the same Gap
Report.
"""

import pytest

from ignis.application.author_policy import apply_author_policy
from ignis.application.use_cases.get_mission_analysis import GetMissionAnalysisUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase

from tests.fixtures.author_identity_sentinels import (
    SENTINEL_YOUTUBE_CHANNEL_ID,
    SENTINEL_YOUTUBE_CHANNEL_TITLE,
    undeclared_sentinels,
)
from tests.unit.test_mission_claims import _eligible_mission, _observation_candidate, _signal_named

MISSION_KEY = bytes(range(32))


def _with_author_identity(repository):
    """Give every sighting an author and a channel link, then apply the pass's policy before saving."""
    save = repository.save_signals

    async def save_through_policy(signals):
        for signal in signals:
            signal.metadata = {
                **signal.metadata,
                "channel_id": SENTINEL_YOUTUBE_CHANNEL_ID,
                "channel_title": SENTINEL_YOUTUBE_CHANNEL_TITLE,
                "profile_url": f"https://www.youtube.com/channel/{SENTINEL_YOUTUBE_CHANNEL_ID}",
            }
        apply_author_policy(signals, MISSION_KEY)
        return await save(signals)

    repository.save_signals = save_through_policy


def _outcome(submission, analysis):
    claims = sorted(
        (claim["wording"], claim["status"], tuple(claim.get("withheld_reasons") or ()))
        for claim in submission.get("claims", ())
    )
    gap = analysis.get("gap_report") or {}
    return {
        "status": submission["status"],
        "analysis_status": submission.get("analysis_status"),
        "permitted": submission.get("permitted"),
        "withheld": submission.get("withheld"),
        "claims": claims,
        "rendered_status": analysis.get("analysis_status"),
        "failed_gates": sorted(gap.get("failed_gates", ())),
        "withheld_outputs": sorted(gap.get("withheld_outputs", ())),
        "ledger": sorted(
            (group, entry.get("wording"), entry.get("status"))
            for group, entries in (analysis.get("claim_ledger") or {}).items()
            for entry in entries
        ),
    }


async def _run(repository, tmp_path, *, contradiction):
    _repository, store, mission, signals, frame = await _eligible_mission(
        tmp_path, contradiction=contradiction, repository=repository
    )
    submission = await SubmitMissionClaimsUseCase(repository, store).execute(
        str(mission.id),
        frame.frame_digest,
        [_observation_candidate(_signal_named(signals, "Demand evidence"))],
        created_by="host-agent",
    )
    analysis = await GetMissionAnalysisUseCase(repository, store).execute(mission.id)
    return _outcome(submission, analysis), analysis


@pytest.mark.asyncio
@pytest.mark.parametrize("contradiction", [True, False], ids=["permitted", "withheld"])
async def test_the_policy_changes_no_claim_permission_or_gap_report(repository_case, tmp_path, contradiction):
    repository = repository_case.repository
    plain, _ = await _run(repository, tmp_path, contradiction=contradiction)

    _with_author_identity(repository)
    stripped, analysis = await _run(repository, tmp_path, contradiction=contradiction)

    assert plain["claims"] and plain["permitted"] == (1 if contradiction else 0), repository_case.name
    assert stripped == plain, repository_case.name
    assert [value for value in undeclared_sentinels() if value in str(analysis)] == [], repository_case.name
