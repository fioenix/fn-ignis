"""T013 on both backends: the per-channel daily request count is atomic and all or nothing (FR-016)."""

import asyncio
from datetime import date, datetime, timezone

import pytest

NOW = datetime(2026, 10, 22, 3, 0, tzinfo=timezone.utc)
DAY = date(2026, 10, 22)


@pytest.mark.asyncio
async def test_requests_are_counted_per_day_and_channel_up_to_the_ceiling(repository_case):
    repository = repository_case.repository

    assert await repository.reserve_connector_requests(DAY, "tiktok", 3, 5, NOW) == (True, 3)
    assert await repository.reserve_connector_requests(DAY, "tiktok", 3, 5, NOW) == (False, 3)
    assert await repository.reserve_connector_requests(DAY, "tiktok", 2, 5, NOW) == (True, 5)
    assert await repository.reserve_connector_requests(DAY, "threads", 5, 5, NOW) == (True, 5)
    assert await repository.reserve_connector_requests(date(2026, 10, 23), "tiktok", 1, 5, NOW) == (True, 1)
    assert await repository.reserve_connector_requests(DAY, "youtube", 6, 5, NOW) == (False, 0)


@pytest.mark.asyncio
async def test_concurrent_passes_never_exceed_the_ceiling(repository_case):
    repository = repository_case.repository

    results = await asyncio.gather(
        *(repository.reserve_connector_requests(DAY, "reels", 1, 4, NOW) for _ in range(10))
    )

    assert sum(admitted for admitted, _ in results) == 4
    assert await repository.reserve_connector_requests(DAY, "reels", 0, 4, NOW) == (True, 4)
