"""T008: one encrypted author key per mission, usable only by the identity policy."""

import base64
import logging
import sqlite3
import uuid

import pytest
import pytest_asyncio

from ignis.config import settings
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

NOW = "2026-10-21T01:00:00+00:00"


@pytest.fixture
def persistent_key(monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "spec-015-test-encryption-key")


@pytest_asyncio.fixture
async def store(tmp_path):
    path = tmp_path / "keys.sqlite"
    repository = SqliteTrendRepository(str(path))
    await repository._ensure_schema()
    yield repository, path
    await repository.close()


def _mission(path):
    mission = str(uuid.uuid4())
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO research_missions (id, title, keywords, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (mission, "keys", "[]", "RUNNING", NOW),
    )
    conn.commit()
    conn.close()
    return mission


def _stored(path, mission):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT encrypted_key FROM mission_author_keys WHERE mission_id = ?", (mission,)).fetchone()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_a_mission_gets_one_stable_32_byte_key(store, persistent_key):
    repository, path = store
    mission = _mission(path)

    first = await repository.get_or_create_mission_author_key(mission)
    second = await repository.get_or_create_mission_author_key(mission)

    assert isinstance(first, bytes) and len(first) == 32
    assert first == second


@pytest.mark.asyncio
async def test_two_missions_get_different_keys(store, persistent_key):
    repository, path = store

    one = await repository.get_or_create_mission_author_key(_mission(path))
    two = await repository.get_or_create_mission_author_key(_mission(path))

    assert one != two


@pytest.mark.asyncio
async def test_the_stored_key_is_encrypted_and_never_the_raw_bytes(store, persistent_key):
    repository, path = store
    mission = _mission(path)

    key = await repository.get_or_create_mission_author_key(mission)

    (stored,) = _stored(path, mission)
    assert key.hex() not in stored
    assert base64.urlsafe_b64encode(key).decode().rstrip("=") not in stored
    assert base64.b64encode(key).decode().rstrip("=") not in stored


@pytest.mark.asyncio
async def test_without_a_persistent_encryption_key_there_is_no_key_and_nothing_is_stored(store, monkeypatch):
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "")
    repository, path = store
    mission = _mission(path)

    assert await repository.get_or_create_mission_author_key(mission) is None
    assert _stored(path, mission) is None


@pytest.mark.asyncio
async def test_a_key_that_can_no_longer_be_decrypted_is_unavailable(store, monkeypatch):
    repository, path = store
    mission = _mission(path)
    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "the-key-at-collection-time")
    await repository.get_or_create_mission_author_key(mission)

    monkeypatch.setattr(settings, "IGNIS_ENCRYPTION_KEY", "a-rotated-key")

    assert await repository.get_or_create_mission_author_key(mission) is None


@pytest.mark.asyncio
async def test_destroying_the_key_makes_old_markers_unrecomputable(store, persistent_key):
    repository, path = store
    mission = _mission(path)
    before = await repository.get_or_create_mission_author_key(mission)

    await repository.destroy_mission_author_key(mission)

    assert _stored(path, mission) is None
    assert await repository.get_or_create_mission_author_key(mission) != before


@pytest.mark.asyncio
async def test_the_key_never_reaches_the_logs(store, persistent_key, caplog):
    repository, path = store
    caplog.set_level(logging.DEBUG)

    key = await repository.get_or_create_mission_author_key(_mission(path))

    assert key.hex() not in caplog.text
    assert base64.urlsafe_b64encode(key).decode() not in caplog.text


@pytest.mark.asyncio
async def test_deleting_a_missions_evidence_destroys_its_markers_for_good(store, persistent_key):
    """T027: once the evidence is gone, no marker of that mission can be recomputed."""
    from ignis.domain.author_identity import author_marker

    repository, path = store
    mission = _mission(path)
    before = await repository.get_or_create_mission_author_key(mission)

    await repository.delete_mission_signals(mission)

    assert _stored(path, mission) is None
    after = await repository.get_or_create_mission_author_key(mission)
    assert author_marker(after, "tiktok:someone") != author_marker(before, "tiktok:someone")


@pytest.mark.asyncio
async def test_pruning_evidence_keeps_the_key(store, persistent_key):
    repository, path = store
    mission = _mission(path)
    before = await repository.get_or_create_mission_author_key(mission)

    await repository.prune_mission_evidence(mission, [])

    assert await repository.get_or_create_mission_author_key(mission) == before
