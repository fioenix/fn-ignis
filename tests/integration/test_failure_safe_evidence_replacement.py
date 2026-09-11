"""A mission that fails mid-pass keeps the evidence it already had.

The replace used to withdraw first: delete_mission_signals committed on its own connection, and
anything that failed afterwards left the mission with nothing at all -- no new evidence and none
of the old. It was called an Atomic Replace and it was neither atomic nor a replace.

Writing first and pruning last cannot be atomic either, and does not pretend to be. What it
guarantees is weaker and sufficient: at every point where the pass can fail, the mission holds
at least the evidence it started with, and a retry converges on the intended set.
"""

from datetime import datetime, timezone

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from conftest import YT_ID, YT_URL, OneSightingRegistry

pytestmark = pytest.mark.asyncio


class Boom(RuntimeError):
    """Injected failure. Distinct from any exception the code raises on its own."""


async def _mission(repository, title="Failure safe"):
    mission = ResearchMission(
        title=title,
        keywords=["k"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    return mission


def _registry(video_id=YT_ID, title="A sighting"):
    return OneSightingRegistry(
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        raw_title=title,
        metadata={"video_id": video_id},
    )


async def _seed_prior_evidence(repository_case, mission):
    """One pass that succeeds, so there is something to lose."""
    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository,
        registry=_registry(title="The evidence it already had"),
        clusterer=SemanticClusterer(),
    )
    await use_case.execute(mission.id)
    assert repository_case.counts()["mission_evidence"] == 1
    return await repository_case.repository.get_mission_signals(mission.id)


async def _run_failing(repository_case, mission, method, registry=None):
    """Execute a pass with one repository operation replaced by a failure."""
    repository = repository_case.repository
    original = getattr(repository, method)

    async def boom(*_args, **_kwargs):
        raise Boom(method)

    setattr(repository, method, boom)
    try:
        use_case = ExecuteMissionUseCase(
            repository=repository,
            registry=registry or _registry(title="The pass that fails"),
            clusterer=SemanticClusterer(),
        )
        with pytest.raises(Boom):
            await use_case.execute(mission.id)
    finally:
        setattr(repository, method, original)


@pytest.mark.parametrize("failing_step", ("save_clusters", "save_signals"))
async def test_a_failure_while_writing_keeps_the_previous_evidence(
    repository_case, failing_step
):
    mission = await _mission(repository_case.repository)
    before = await _seed_prior_evidence(repository_case, mission)

    await _run_failing(repository_case, mission, failing_step)

    after = await repository_case.repository.get_mission_signals(mission.id)
    assert [s.observation_id for s in after] == [s.observation_id for s in before]


async def test_a_failure_while_attaching_preserved_evidence_keeps_the_previous_evidence(
    repository_case,
):
    """The quota path: a connector returns nothing and the mission keeps what it had.

    The pass fails while re-attaching, which is after the new observations exist. The old
    evidence must still be there; new evidence may be there as well, and that is the honest
    trade -- this is failure-safe, not atomic.
    """
    mission = await _mission(repository_case.repository)
    before = await _seed_prior_evidence(repository_case, mission)

    class Silent:
        async def search_across_all(self, **_kwargs):
            return []

    await _run_failing(
        repository_case, mission, "attach_mission_evidence", registry=Silent()
    )

    kept = {s.observation_id for s in await repository_case.repository.get_mission_signals(mission.id)}
    assert {s.observation_id for s in before} <= kept


async def test_a_failure_while_pruning_leaves_both_sets_and_a_retry_converges(repository_case):
    """Stale evidence surviving a failure is recoverable. Evidence deleted is not."""
    mission = await _mission(repository_case.repository)
    before = await _seed_prior_evidence(repository_case, mission)

    await _run_failing(
        repository_case, mission, "prune_mission_evidence", registry=_registry("9bZkp7q19f0")
    )

    during = await repository_case.repository.get_mission_signals(mission.id)
    assert len(during) == 2, "the failed prune leaves the old association alongside the new"
    assert {s.observation_id for s in before} <= {s.observation_id for s in during}

    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository,
        registry=_registry("9bZkp7q19f0", title="The retry"),
        clusterer=SemanticClusterer(),
    )
    await use_case.execute(mission.id)

    after = await repository_case.repository.get_mission_signals(mission.id)
    assert len(after) == 1, "the retry converges on the intended set, without duplicates"
    assert after[0].observation_id not in {s.observation_id for s in before}


async def test_a_successful_pass_drops_the_evidence_it_replaced(repository_case):
    mission = await _mission(repository_case.repository)
    before = await _seed_prior_evidence(repository_case, mission)

    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository,
        registry=_registry("9bZkp7q19f0", title="The replacement"),
        clusterer=SemanticClusterer(),
    )
    await use_case.execute(mission.id)

    after = await repository_case.repository.get_mission_signals(mission.id)
    assert len(after) == 1
    assert {s.observation_id for s in after}.isdisjoint({s.observation_id for s in before})
    assert repository_case.counts()["mission_evidence"] == 1
    # The observations themselves survive: they are shared, and only the claim was withdrawn.
    assert repository_case.counts()["observations"] == 2


async def test_a_preserved_platform_is_not_pruned_as_stale(repository_case):
    """What the mission keeps through the quota path has to survive the prune that follows."""
    mission = await _mission(repository_case.repository)
    before = await _seed_prior_evidence(repository_case, mission)

    class Silent:
        async def search_across_all(self, **_kwargs):
            return []

    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository,
        registry=Silent(),
        clusterer=SemanticClusterer(),
    )
    await use_case.execute(mission.id)

    after = await repository_case.repository.get_mission_signals(mission.id)
    assert [s.observation_id for s in after] == [s.observation_id for s in before]


async def test_withdrawal_is_still_available_on_its_own(repository_case):
    """delete_mission_signals stays, for the explicit withdrawal it was always meant to be."""
    mission = await _mission(repository_case.repository)
    await _seed_prior_evidence(repository_case, mission)

    withdrawn = await repository_case.repository.delete_mission_signals(mission.id)

    assert withdrawn == 1
    assert await repository_case.repository.get_mission_signals(mission.id) == []
    assert repository_case.counts()["observations"] == 1, "the observation is shared, not owned"


async def test_pruning_nothing_retained_withdraws_everything(repository_case):
    """The degenerate case has to be a withdrawal, not a no-op that keeps stale claims."""
    mission = await _mission(repository_case.repository)
    await _seed_prior_evidence(repository_case, mission)

    removed = await repository_case.repository.prune_mission_evidence(mission.id, [])

    assert removed == 1
    assert repository_case.counts()["mission_evidence"] == 0


async def test_pruning_is_scoped_to_one_mission(repository_case):
    """Another mission standing on the same observation keeps its own claim."""
    keeper = await _mission(repository_case.repository, title="Keeps its evidence")
    other = await _mission(repository_case.repository, title="Replaces its evidence")
    for mission in (keeper, other):
        use_case = ExecuteMissionUseCase(
            repository=repository_case.repository,
            registry=_registry(title="One source, two missions"),
            clusterer=SemanticClusterer(),
        )
        await use_case.execute(mission.id)

    await repository_case.repository.prune_mission_evidence(other.id, [])

    assert len(await repository_case.repository.get_mission_signals(keeper.id)) == 1
    assert await repository_case.repository.get_mission_signals(other.id) == []


async def test_the_clock_on_a_fresh_sighting_is_this_pass(repository_case):
    """Guards the seed helper: each pass writes its own observation rather than reusing one."""
    mission = await _mission(repository_case.repository)
    await _seed_prior_evidence(repository_case, mission)

    signals = await repository_case.repository.get_mission_signals(mission.id)

    assert signals[0].captured_at is not None
    assert signals[0].captured_at <= datetime.now(timezone.utc)
    assert signals[0].source_url == YT_URL
