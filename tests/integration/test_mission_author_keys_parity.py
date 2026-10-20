"""T008 parity: both backends keep one encrypted author key per mission under the same contract."""

import pytest

from ignis.config import settings
from ignis.domain.entities import ResearchMission


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-parity-encryption-key")


def _stored(case, mission_id):
    return case.query_one(
        "SELECT encrypted_key FROM mission_author_keys WHERE mission_id = ?",
        "SELECT encrypted_key FROM mission_author_keys WHERE mission_id = %s",
        (str(mission_id),),
    )


async def _mission(repository):
    mission = ResearchMission(title="Author key parity", keywords=["matcha"])
    await repository.create_mission(mission)
    return mission.id


@pytest.mark.asyncio
async def test_a_mission_key_is_stable_encrypted_and_destroyable(repository_case, persistent_key):
    repository = repository_case.repository
    mission = await _mission(repository)

    first = await repository.get_or_create_mission_author_key(mission)
    second = await repository.get_or_create_mission_author_key(mission)
    (stored,) = _stored(repository_case, mission)

    assert isinstance(first, bytes) and len(first) == 32, repository_case.name
    assert first == second, repository_case.name
    assert first.hex() not in stored, repository_case.name

    await repository.destroy_mission_author_key(mission)

    assert _stored(repository_case, mission) is None, repository_case.name


@pytest.mark.asyncio
async def test_no_persistent_encryption_key_means_no_key(repository_case, monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "")
    repository = repository_case.repository
    mission = await _mission(repository)

    assert await repository.get_or_create_mission_author_key(mission) is None, repository_case.name
    assert _stored(repository_case, mission) is None, repository_case.name


@pytest.mark.asyncio
async def test_a_rotated_encryption_key_makes_the_mission_key_unavailable(repository_case, monkeypatch):
    repository = repository_case.repository
    mission = await _mission(repository)
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "key-at-collection-time")
    await repository.get_or_create_mission_author_key(mission)

    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "a-rotated-key")

    assert await repository.get_or_create_mission_author_key(mission) is None, repository_case.name
