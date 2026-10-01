import asyncio
from datetime import datetime, timezone

import pytest

from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.mark.asyncio
async def test_requested_calls_never_admit_more_than_the_shared_limit(tmp_path):
    """Removing atomic admission would let concurrent processes overspend the final calls."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.exceptions import ConnectorQuotaExceededException
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    repo = SqliteTrendRepository(f"sqlite:///{tmp_path / 'quota.db'}")
    manager = YouTubeQuotaManager(
        repo,
        policy=YouTubeQuotaPolicy(search_daily_limit=2),
        now=lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
    )

    first = await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    second = await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)

    assert (first.used, second.used) == (1, 2)
    with pytest.raises(ConnectorQuotaExceededException) as refused:
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    assert refused.value.bucket == "search_list"
    assert refused.value.used == 2
    assert refused.value.limit == 2
    assert refused.value.reset_at.isoformat() == "2026-09-30T07:00:00+00:00"


@pytest.mark.asyncio
async def test_pacific_day_rollover_opens_a_fresh_bucket_without_restart(tmp_path):
    """Using a UTC date would reset at the wrong provider boundary."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    current = [datetime(2026, 9, 30, 6, 59, tzinfo=timezone.utc)]
    manager = YouTubeQuotaManager(
        SqliteTrendRepository(f"sqlite:///{tmp_path / 'rollover.db'}"),
        policy=YouTubeQuotaPolicy(search_daily_limit=1),
        now=lambda: current[0],
    )

    before = await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    current[0] = datetime(2026, 9, 30, 7, 1, tzinfo=timezone.utc)
    after = await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)

    assert before.quota_day.isoformat() == "2026-09-29"
    assert after.quota_day.isoformat() == "2026-09-30"
    assert after.used == 1


@pytest.mark.asyncio
async def test_provider_exhaustion_closes_only_the_named_bucket_until_reset(tmp_path):
    """Dropping the exhausted flag would retry a provider-known daily refusal all day."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.exceptions import ConnectorQuotaExceededException
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    manager = YouTubeQuotaManager(
        SqliteTrendRepository(f"sqlite:///{tmp_path / 'exhausted.db'}"),
        policy=YouTubeQuotaPolicy(search_daily_limit=5),
        now=lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
    )
    await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    exhausted = await manager.mark_exhausted(YouTubeQuotaBucket.SEARCH_LIST)

    assert exhausted.exhausted is True
    with pytest.raises(ConnectorQuotaExceededException):
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    other = await manager.reserve(YouTubeQuotaBucket.DEFAULT_UNITS, IngressTrigger.REQUESTED)
    assert other.used == 1


@pytest.mark.asyncio
async def test_admitted_reservation_is_not_refunded_when_the_caller_fails(tmp_path):
    """Provider failures still spend quota, so a caller exception cannot reopen capacity."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.exceptions import ConnectorQuotaExceededException
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    manager = YouTubeQuotaManager(
        SqliteTrendRepository(f"sqlite:///{tmp_path / 'no-refund.db'}"),
        policy=YouTubeQuotaPolicy(search_daily_limit=1),
        now=lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
    )

    async def failing_caller():
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
        raise RuntimeError("provider transport failed after admission")

    with pytest.raises(RuntimeError):
        await failing_caller()
    with pytest.raises(ConnectorQuotaExceededException):
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)

    status = await manager.status()
    assert status["buckets"]["search_list"]["used"] == 1


def test_pacific_reset_uses_daylight_saving_rules():
    """A fixed UTC-8 offset would report the wrong reset during Pacific daylight time."""
    from ignis.domain.youtube_quota import quota_window

    summer = quota_window(datetime(2026, 7, 1, 12, tzinfo=timezone.utc))
    winter = quota_window(datetime(2026, 1, 1, 12, tzinfo=timezone.utc))

    assert summer.reset_at.isoformat().endswith("07:00:00+00:00")
    assert winter.reset_at.isoformat().endswith("08:00:00+00:00")


@pytest.mark.asyncio
async def test_separate_sqlite_repository_instances_cannot_overspend_concurrently(tmp_path):
    """Removing BEGIN IMMEDIATE would let two requested callers take the final call."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.exceptions import ConnectorQuotaExceededException
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    dsn = f"sqlite:///{tmp_path / 'shared.db'}"

    def clock():
        return datetime(2026, 9, 29, 12, tzinfo=timezone.utc)

    policy = YouTubeQuotaPolicy(search_daily_limit=3)
    managers = [
        YouTubeQuotaManager(SqliteTrendRepository(dsn), policy=policy, now=clock)
        for _ in range(5)
    ]
    await managers[0].status()

    results = await asyncio.gather(
        *[
            manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
            for manager in managers
        ],
        return_exceptions=True,
    )

    admitted = [result for result in results if not isinstance(result, Exception)]
    refused = [
        result for result in results if isinstance(result, ConnectorQuotaExceededException)
    ]
    assert len(admitted) == 3
    assert len(refused) == 2
    status = await managers[0].status()
    assert status["buckets"]["search_list"]["used"] == 3


@pytest.mark.asyncio
async def test_scheduled_identity_cannot_reserve_quota(tmp_path):
    """Historical scheduled usage is readable, but no new scheduled call may be admitted."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    manager = YouTubeQuotaManager(
        SqliteTrendRepository(f"sqlite:///{tmp_path / 'allocation.db'}"),
        policy=YouTubeQuotaPolicy(search_daily_limit=4),
        now=lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="requested work"):
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, "scheduled")

    first = await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
    assert first.used == 1
    assert first.scheduled_used == 0


@pytest.mark.asyncio
async def test_requested_work_can_use_the_full_shared_capacity(tmp_path):
    """The former scheduled partition no longer reserves capacity."""
    from ignis.application.youtube_quota import YouTubeQuotaManager
    from ignis.domain.value_objects import IngressTrigger
    from ignis.domain.youtube_quota import YouTubeQuotaBucket, YouTubeQuotaPolicy

    manager = YouTubeQuotaManager(
        SqliteTrendRepository(f"sqlite:///{tmp_path / 'borrow.db'}"),
        policy=YouTubeQuotaPolicy(search_daily_limit=4),
        now=lambda: datetime(2026, 9, 29, 12, tzinfo=timezone.utc),
    )

    snapshots = [
        await manager.reserve(YouTubeQuotaBucket.SEARCH_LIST, IngressTrigger.REQUESTED)
        for _ in range(4)
    ]
    assert snapshots[-1].used == 4
    assert snapshots[-1].scheduled_used == 0
