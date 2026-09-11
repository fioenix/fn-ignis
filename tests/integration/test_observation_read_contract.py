"""What the application layer must be able to say about an observation, on both backends.

The writer landed first, and it can only produce observations it collected itself: exact clock,
known route, one per sighting. The backfill produces the other kind -- 17,118 observations whose
ingestion time was never recorded -- and nothing above the repository can currently represent
one. These contracts are written before the backfill for that reason: a read path that quietly
turns "the collection time is unknown" into "collected just now" would make the migration look
successful and the data wrong.
"""

from datetime import datetime, timezone

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from conftest import YT_ID, YT_URL, OneSightingRegistry, SilentRegistry

pytestmark = pytest.mark.asyncio

PUBLISHED_AT = datetime(2026, 7, 1, 8, 30, tzinfo=timezone.utc)


async def _mission(repository, title="Read contract"):
    mission = ResearchMission(
        title=title,
        keywords=["read contract"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    return mission


# --- 1. a legacy observation survives the round trip -------------------------------------------


async def test_a_legacy_observation_keeps_its_null_clock_provenance_route_and_cluster(
    repository_case,
):
    """The shape the backfill writes, read back through the application layer.

    Four things have to survive: the absent ingestion time stays absent, the provenance label
    says why, the route says how the source was resolved, and the cluster membership comes back.
    A read path that fills any of them in is inventing data the corpus does not have.
    """
    repository = repository_case.repository
    mission = await _mission(repository)
    source_id = repository_case.insert_source("youtube", f"video:{YT_ID}")
    cluster_id = await _stored_cluster(repository, repository_case)
    observation_id = repository_case.insert_legacy_observation(
        source_id=source_id,
        cluster_id=cluster_id,
        observed_at=None,
        published_at=PUBLISHED_AT.isoformat() if repository_case.name == "sqlite" else PUBLISHED_AT,
        time_provenance="legacy_publish_only",
        identity_source="url_external_id",
        observed_title="A legacy sighting",
        metric_value=120000.0,
        growth_velocity=0.0,
        geo_code="VN",
        source_url=YT_URL,
        metadata="{}",
    )
    repository_case.attach_evidence(mission.id, observation_id)

    signals = await repository.get_mission_signals(mission.id)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.captured_at is None, (
        "the true collection time was never recorded; a read path that supplies one turns"
        " 'unknown' into 'just now'"
    )
    assert signal.published_at is not None
    assert signal.time_provenance == "legacy_publish_only"
    assert signal.identity_source == "url_external_id"
    assert str(signal.cluster_id) == str(cluster_id)
    assert signal.observation_id is not None


async def _stored_cluster(repository, repository_case):
    """Persist one cluster and return its id, so an observation may reference it."""
    from ignis.domain.entities import TopicCluster

    cluster = TopicCluster(canonical_name="read contract cluster")
    await repository.save_clusters([cluster])
    return cluster.id


# --- 2. the quota fallback preserves evidence without inventing a sighting ----------------------


async def test_a_quota_fallback_pass_adds_no_observation(repository_case):
    """Preserving a platform's history is not the same as claiming to have polled it again.

    The fallback exists because a connector can exhaust its quota mid-pass. Re-submitting the
    previous observations through the writer records them as fresh collection events: the second
    run doubled the observation count while the evidence count stayed put, so the corpus gained
    sightings that never happened.
    """
    repository = repository_case.repository
    mission = await _mission(repository, title="Quota fallback")
    first_pass = ExecuteMissionUseCase(
        repository=repository,
        registry=OneSightingRegistry(
            source_url=YT_URL, raw_title="Polled once", metadata={"video_id": YT_ID}
        ),
        clusterer=SemanticClusterer(),
    )
    await first_pass.execute(mission.id)
    after_first = repository_case.counts()
    assert after_first["observations"] == 1

    # The connector returns nothing this time, which is exactly the quota case.
    second_pass = ExecuteMissionUseCase(
        repository=repository, registry=SilentRegistry(), clusterer=SemanticClusterer()
    )
    await second_pass.execute(mission.id)

    after_second = repository_case.counts()
    assert after_second["observations"] == 1, (
        "a pass that collected nothing must not write an observation claiming it did"
    )
    assert after_second["mission_evidence"] == 1, "the mission keeps the evidence it had"
    assert len(await repository.get_mission_signals(mission.id)) == 1


# --- 3. cluster membership is recorded without duplicating the observation ----------------------


async def test_assigning_a_cluster_updates_the_observation_instead_of_adding_one(repository_case):
    """The discovery path persists signals first and clusters afterwards.

    Calling save_signals again to carry the cluster would be a second collection event for a
    sighting that happened once. Membership on an observation already written is an update, and
    the repository has to offer one.
    """
    repository = repository_case.repository
    signal = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Clustered after the fact",
        metric_value=100.0,
        source_url=YT_URL,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 9, 11, 1, 0, tzinfo=timezone.utc),
        metadata={"video_id": YT_ID},
    )
    await repository.save_signals([signal])
    assert repository_case.counts()["observations"] == 1
    assert signal.observation_id is not None, (
        "the writer has to tell the caller which observation it wrote, or the cluster cannot be"
        " attached to it later"
    )

    cluster_id = await _stored_cluster(repository, repository_case)
    signal.cluster_id = cluster_id
    await repository.assign_observation_clusters([signal])

    counts = repository_case.counts()
    assert counts["observations"] == 1, "membership is an update, not a new sighting"
    assert counts["clustered_observations"] == 1


# --- 4. the count means collection events --------------------------------------------------------


async def test_save_signals_counts_the_observations_it_wrote(repository_case):
    """Two passes over one source are two collection events, and both are reported as one each.

    The number used to come from the legacy table's insert count, so the second pass reported 0
    while the observation count went from 1 to 2 -- a caller logging "saved 0" for work that was
    done.
    """
    repository = repository_case.repository

    def sighting(hour, metric):
        return TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Counted",
            metric_value=metric,
            source_url=YT_URL,
            geo_code=GeoCode.VN,
            captured_at=datetime(2026, 9, 11, hour, 0, tzinfo=timezone.utc),
            metadata={"video_id": YT_ID},
        )

    assert await repository.save_signals([sighting(1, 100.0)]) == 1
    assert await repository.save_signals([sighting(2, 200.0)]) == 1
    assert repository_case.counts()["observations"] == 2

    # A signal identifying nothing is skipped, so it is not counted as written either.
    unidentifiable = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Nothing identifies this",
        metric_value=1.0,
        source_url=None,
        geo_code=GeoCode.VN,
        metadata={},
    )
    assert await repository.save_signals([unidentifiable]) == 0
