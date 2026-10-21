"""T009: the repository refuses to store author identity, whatever path the signal took.

The identity policy runs in the mission pass. This guard is the second line: a caller that skips
the policy -- a dormant use case, a future connector path -- fails loudly instead of leaking
silently, and the whole batch is refused so nothing half-written survives.
"""

import sqlite3
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import RepositoryException
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

from tests.fixtures.author_identity_sentinels import (
    SENTINEL_PROFILE_URL,
    SENTINEL_TIKTOK_COMMENTER,
    SENTINEL_TIKTOK_HANDLE,
    TIKTOK_HANDLE_URL,
    TIKTOK_ITEM_ID,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def store(tmp_path):
    path = tmp_path / "guard.sqlite"
    repository = SqliteTrendRepository(str(path))
    await repository._ensure_schema()
    yield repository, path
    await repository.close()


def _signal(metadata=None, source_url=None, title="Áo thun form rộng"):
    return TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title=title,
        source_url=source_url,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 10, 21, 1, 0, tzinfo=timezone.utc),
        metadata={"item_id": TIKTOK_ITEM_ID, "views": 10} if metadata is None else metadata,
    )


def _counts(path):
    with sqlite3.connect(path) as conn:
        return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("sources", "observations"))


@pytest.mark.parametrize(
    "signal",
    [
        pytest.param(_signal({"item_id": TIKTOK_ITEM_ID, "author": SENTINEL_TIKTOK_HANDLE}), id="author-key"),
        pytest.param(
            _signal({"item_id": TIKTOK_ITEM_ID, "comments": [{"text": "đẹp", "author_id": SENTINEL_TIKTOK_COMMENTER}]}),
            id="nested-author-key",
        ),
        pytest.param(_signal({"item_id": TIKTOK_ITEM_ID, "share": {"video_url": TIKTOK_HANDLE_URL}}), id="nested-handle-link"),
        pytest.param(_signal(source_url=TIKTOK_HANDLE_URL), id="handle-source-url"),
        pytest.param(_signal({}, source_url=SENTINEL_PROFILE_URL), id="profile-url-only"),
    ],
)
async def test_a_signal_carrying_author_identity_is_refused(store, signal):
    repository, path = store

    with pytest.raises(RepositoryException) as refused:
        await repository.save_signals([signal])

    assert _counts(path) == (0, 0)
    # The refusal names the kind of leak, never the value it refused to store.
    assert SENTINEL_TIKTOK_HANDLE not in str(refused.value)
    assert "sentinel" not in str(refused.value)
    assert signal.observation_id is None


async def test_one_leaking_signal_refuses_the_whole_batch(store):
    repository, path = store
    clean = _signal()
    leaking = _signal({"item_id": "1", "nickname": "Sentinel Nguyễn Văn"})

    with pytest.raises(RepositoryException):
        await repository.save_signals([clean, leaking])

    assert _counts(path) == (0, 0)
    assert clean.observation_id is None


async def test_a_clean_signal_is_stored(store):
    repository, path = store
    signal = _signal(source_url=f"https://www.tiktok.com/share/video/{TIKTOK_ITEM_ID}")

    assert await repository.save_signals([signal]) == 1

    assert _counts(path) == (1, 1)
    assert signal.observation_id is not None


async def test_a_handle_free_url_without_content_id_is_stored_as_unverifiable_content(store):
    """With the profile link dropped, the content itself still counts as context (research R6)."""
    repository, path = store
    signal = _signal({"views": 3})

    assert await repository.save_signals([signal]) == 1

    assert signal.identity_source == "unverifiable_content"
    with sqlite3.connect(path) as conn:
        (external_id,) = conn.execute("SELECT external_id FROM sources").fetchone()
    assert external_id.startswith("content:")
