"""An invalid timeframe must be refused where the mission is created, not where it is read.

`CreateMissionUseCase` persisted whatever string it was handed. Timeframe._missing_ manufactures
a member for any value, so `timeframe="banana"` reached the database intact and only failed later,
when analysis asked `timeframe_to_days` for a span. By then the corpus held a mission nobody could
window.

The validation therefore belongs in the use case, which every caller goes through, rather than in
one handler. These tests drive the real use case against a spying repository so that "refused"
means the write never happened, not that a mock returned early.
"""

from unittest.mock import AsyncMock

import pytest

from ignis.application.use_cases.create_mission import CreateMissionUseCase
from ignis.domain.value_objects import Timeframe
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

INVALID = "banana"


def _spying_repository():
    repository = AsyncMock()
    repository.create_mission = AsyncMock(
        side_effect=AssertionError("create_mission was called with an unvalidated timeframe")
    )
    return repository


async def _sqlite_repository(tmp_path):
    repository = SqliteTrendRepository(str(tmp_path / "missions.sqlite"))
    await repository._ensure_schema()
    return repository


# --- the use case is the boundary --------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_use_case_refuses_before_it_reaches_the_repository():
    repository = _spying_repository()
    use_case = CreateMissionUseCase(repository=repository)

    with pytest.raises(ValueError):
        await use_case.execute(title="Bad", keywords=["x"], timeframe=INVALID)

    repository.create_mission.assert_not_awaited()


@pytest.mark.asyncio
async def test_nothing_is_persisted_when_the_timeframe_is_refused(tmp_path):
    """The repository is real here, so an empty mission list is the proof rather than a mock."""
    repository = await _sqlite_repository(tmp_path)
    try:
        use_case = CreateMissionUseCase(repository=repository)
        with pytest.raises(ValueError):
            await use_case.execute(title="Bad", keywords=["x"], timeframe=INVALID)
        assert await repository.list_missions(limit=10) == []
    finally:
        await repository.close()

@pytest.mark.asyncio
@pytest.mark.parametrize("timeframe", tuple(Timeframe), ids=[t.value for t in Timeframe])
async def test_every_valid_timeframe_still_creates_a_mission(tmp_path, timeframe):
    repository = await _sqlite_repository(tmp_path)
    try:
        use_case = CreateMissionUseCase(repository=repository)
        mission = await use_case.execute(
            title=f"Mission {timeframe.value}", keywords=["x"], timeframe=timeframe.value
        )
        assert mission.timeframe == timeframe.value
        assert len(await repository.list_missions(limit=10)) == 1
    finally:
        await repository.close()
