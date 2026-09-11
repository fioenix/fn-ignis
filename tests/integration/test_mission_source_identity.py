"""Behavioral contract for source identity and mission evidence across both repositories."""

from datetime import datetime, timezone

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer

from conftest import OneSightingRegistry, TwoObservationRegistry

@pytest.mark.asyncio
async def test_one_source_keeps_distinct_evidence_for_two_missions(repository_case):
    """One external source is canonical once while each mission keeps its metric snapshot."""
    repository = repository_case.repository
    source_url = "https://www.youtube.com/watch?v=one-source"
    raw_title = "One source observed by two missions"
    registry = TwoObservationRegistry(source_url=source_url, raw_title=raw_title)
    use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
    )
    mission_a = ResearchMission(
        title="Mission A",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    mission_b = ResearchMission(
        title="Mission B",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission_a)
    await repository.save_mission(mission_b)

    result_a = await use_case.execute(mission_a.id)
    result_b = await use_case.execute(mission_b.id)

    evidence_a = await repository.get_mission_signals(mission_a.id)
    evidence_b = await repository.get_mission_signals(mission_b.id)
    assert result_a["total_signals"] == result_b["total_signals"] == 1
    identity_rows = repository_case.count_identity_rows("youtube", source_url, raw_title)
    assert identity_rows == 1, f"{repository_case.name} stored one external source as {identity_rows} rows"
    assert len(evidence_a) == 1, "mission A lost the source it observed"
    assert len(evidence_b) == 1, "mission B lost the source it observed"
    assert [signal.metric_value for signal in evidence_a] == [100.0]
    assert [signal.metric_value for signal in evidence_b] == [200.0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata_carries_the_id", "expected_route"),
    ((True, "metadata_external_id"), (False, "url_external_id")),
)
async def test_an_observation_records_the_route_that_resolved_it(
    repository_case, metadata_carries_the_id, expected_route
):
    """The live writer has to store the route the resolver returned, not a default.

    A real YouTube id is 11 characters and the URL pattern needs at least 6, so a short stand-in
    would resolve by the normalized-URL fallback and this test would assert the wrong route.
    """
    repository = repository_case.repository
    source_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    raw_title = "One source, one route"
    registry = OneSightingRegistry(
        source_url=source_url,
        raw_title=raw_title,
        metadata={"video_id": "dQw4w9WgXcQ"} if metadata_carries_the_id else {},
    )
    use_case = ExecuteMissionUseCase(
        repository=repository,
        registry=registry,
        clusterer=SemanticClusterer(),
    )
    mission = ResearchMission(
        title="Route",
        keywords=["one source"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    await use_case.execute(mission.id)

    assert repository_case.observation_routes() == [expected_route]


@pytest.mark.asyncio
async def test_repeating_a_pass_adds_an_observation_and_no_second_source(repository_case):
    """Two ingress passes over one video: one canonical row, two collection events.

    The upsert is a single statement for the same reason -- a SELECT then an INSERT lets two
    passes both find nothing and both insert, which is how the legacy table came to hold more
    rows than there are objects.
    """
    repository = repository_case.repository
    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Repeat",
            metric_value=metric,
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            geo_code=GeoCode.VN,
            captured_at=datetime(2026, 9, 11, hour, 0, tzinfo=timezone.utc),
            metadata={"video_id": "dQw4w9WgXcQ"},
        )
        for hour, metric in ((1, 100.0), (2, 200.0))
    ]
    for signal in signals:
        await repository.save_signals([signal])

    counts = repository_case.counts()
    assert counts["sources"] == 1
    assert counts["observations"] == 2


@pytest.mark.asyncio
async def test_an_identical_payload_twice_is_still_two_observations(repository_case):
    """Nothing is deduplicated on the payload: only the surrogate id separates two sightings."""
    repository = repository_case.repository

    def one_signal():
        return TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Identical",
            metric_value=100.0,
            growth_velocity=5.0,
            source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            geo_code=GeoCode.VN,
            captured_at=datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc),
            metadata={"video_id": "dQw4w9WgXcQ"},
        )

    await repository.save_signals([one_signal()])
    await repository.save_signals([one_signal()])

    assert repository_case.counts()["observations"] == 2


@pytest.mark.asyncio
async def test_withdrawing_a_mission_keeps_the_source_the_observation_and_the_cluster(
    repository_case,
):
    """delete_mission_signals withdraws claims. It is not a delete of shared history.

    The name is older than the model. A source and its observations belong to every mission that
    observed them, and the cluster membership is a column on those observations, so deleting any
    of it here would take another mission's evidence with it.
    """
    repository = repository_case.repository
    registry = TwoObservationRegistry(
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", raw_title="Withdrawn"
    )
    use_case = ExecuteMissionUseCase(
        repository=repository, registry=registry, clusterer=SemanticClusterer()
    )
    mission = ResearchMission(
        title="Withdrawn",
        keywords=["withdrawn"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    await use_case.execute(mission.id)

    before = repository_case.counts()
    assert before["mission_evidence"] == 1
    assert before["clustered_observations"] == 1

    withdrawn = await repository.delete_mission_signals(mission.id)

    after = repository_case.counts()
    assert withdrawn == 1
    assert after["mission_evidence"] == 0
    assert after["sources"] == before["sources"]
    assert after["observations"] == before["observations"]
    assert after["clustered_observations"] == before["clustered_observations"]


@pytest.mark.asyncio
async def test_saving_a_cluster_writes_no_observation(repository_case):
    """save_clusters persists the cluster and labels signals in memory. Nothing else.

    On SQLite it used to insert every signal under a fresh uuid4, which stored one external
    source as two rows -- the defect the first contract measured.
    """
    repository = repository_case.repository
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Cluster only",
        metric_value=100.0,
        source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        geo_code=GeoCode.VN,
        metadata={"video_id": "dQw4w9WgXcQ"},
    )
    cluster = TopicCluster(canonical_name="cluster only", signals=[signal])

    await repository.save_clusters([cluster])

    counts = repository_case.counts()
    assert counts["observations"] == 0
    assert counts["sources"] == 0
    # It still did its own job: the signal now carries the cluster it belongs to.
    assert signal.cluster_id == cluster.id


@pytest.mark.asyncio
async def test_a_signal_identifying_nothing_is_skipped_not_given_a_key(repository_case):
    """Every row in the corpus resolves, and one that does not is not worth an invented key."""
    repository = repository_case.repository
    await repository.save_signals(
        [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title="Nothing identifies this",
                metric_value=100.0,
                source_url=None,
                geo_code=GeoCode.VN,
                metadata={},
            )
        ]
    )

    counts = repository_case.counts()
    assert counts["sources"] == 0
    assert counts["observations"] == 0
