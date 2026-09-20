"""A wider timeframe must never return less than a narrower one, on either backend.

Both readers derived their SQL window from a dict covering three of the five Timeframe members,
so LAST_90D and LAST_12M fell through to a default -- twenty-four hours in one reader, seven days
in the other. A caller asking for ninety days was served twenty-four hours, with a successful
status and no warning. Measured against the live corpus on 20/09/2026: 30d returned five clusters
while 90d returned none, which cannot both be right of nested windows.

The containment these tests assert, 24h subset 7d subset 30d subset 90d subset 12m, is the
property a window has by definition. Asserting counts per timeframe rather than the dict's
contents is deliberate: the dict was the token, the window is the behaviour.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe

pytestmark = pytest.mark.asyncio

# One observation just inside each window, so each timeframe admits exactly one more than the
# one below it. Hours rather than days at the 24h edge, because a signal written "1 day ago"
# sits on the boundary and makes the test flap.
AGES = (
    timedelta(hours=12),
    timedelta(days=3),
    timedelta(days=20),
    timedelta(days=60),
    timedelta(days=200),
)

# Cumulative: the nth timeframe contains every observation the ones before it contain.
EXPECTED = (
    (Timeframe.LAST_24H, 1),
    (Timeframe.LAST_7D, 2),
    (Timeframe.LAST_30D, 3),
    (Timeframe.LAST_90D, 4),
    (Timeframe.LAST_12M, 5),
)


async def _cluster_with_one_observation_per_window(repository):
    """One cluster, five sightings, each in a different band of the past year."""
    cluster = TopicCluster(canonical_name=f"timeframe window {uuid4()}")
    await repository.save_clusters([cluster])

    now = datetime.now(timezone.utc)
    signals = [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title=f"Sighting {index}",
            metric_value=100.0 + index,
            growth_velocity=1.0,
            source_url=f"https://www.youtube.com/watch?v=tfwindow{index:03d}",
            geo_code=GeoCode.VN,
            cluster_id=cluster.id,
            metadata={"video_id": f"tfwindow{index:03d}"},
            captured_at=now - age,
        )
        for index, age in enumerate(AGES)
    ]
    await repository.save_signals(signals)
    return cluster.id


@pytest.mark.parametrize("timeframe,expected", EXPECTED, ids=[t.value for t, _ in EXPECTED])
async def test_get_top_clusters_honours_every_timeframe(repository_case, timeframe, expected):
    repository = repository_case.repository
    await _cluster_with_one_observation_per_window(repository)

    clusters = await repository.get_top_clusters(geo=GeoCode.VN, timeframe=timeframe, limit=10)
    counted = sum(len(c.signals) for c in clusters)
    assert counted == expected, (
        f"{timeframe.value} returned {counted} observations, expected {expected};"
        " a wider window cannot hold fewer sightings than a narrower one"
    )


@pytest.mark.parametrize("timeframe,expected", EXPECTED, ids=[t.value for t, _ in EXPECTED])
async def test_get_cluster_signals_honours_every_timeframe(repository_case, timeframe, expected):
    repository = repository_case.repository
    cluster_id = await _cluster_with_one_observation_per_window(repository)

    signals = await repository.get_cluster_signals(cluster_id=cluster_id, timeframe=timeframe)
    assert len(signals) == expected, (
        f"{timeframe.value} returned {len(signals)} observations, expected {expected};"
        " a wider window cannot hold fewer sightings than a narrower one"
    )


async def test_a_timeframe_that_is_not_a_member_is_refused_by_get_top_clusters(repository_case):
    """Refused, not windowed to a default.

    Timeframe._missing_ manufactures a member for any string, so an arbitrary value reaches the
    repository as something that looks like a Timeframe. Silently choosing a window for it is how
    one input came to mean three different spans: ninety days from the day helper, twenty-four
    hours from one reader's default and seven days from the other's.
    """
    repository = repository_case.repository
    with pytest.raises(ValueError):
        await repository.get_top_clusters(geo=GeoCode.VN, timeframe=Timeframe("banana"), limit=10)


async def test_a_timeframe_that_is_not_a_member_is_refused_by_get_cluster_signals(repository_case):
    repository = repository_case.repository
    cluster_id = await _cluster_with_one_observation_per_window(repository)
    with pytest.raises(ValueError):
        await repository.get_cluster_signals(cluster_id=cluster_id, timeframe=Timeframe("banana"))
