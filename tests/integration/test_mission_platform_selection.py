"""A mission's platform selection has to survive being stored.

SQLite never had a platforms column, so a mission created for YouTube alone came back asking for
all five connectors. The damage was not only the extra calls: the summary counted responsive
platforms against the wrong denominator, so a pass that reached nothing could still report
"1 signal across 1/5 responsive platforms" and read like partial success.
"""

import json
import sqlite3

import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.domain.entities import ResearchMission
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from conftest import YT_ID, YT_URL, OneSightingRegistry

pytestmark = pytest.mark.asyncio


class RecordingRegistry(OneSightingRegistry):
    """Remembers what the use case asked it for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requested_platforms = None

    async def search_across_all(self, **kwargs):
        self.requested_platforms = kwargs.get("target_platforms")
        return await super().search_across_all(**kwargs)


async def _youtube_only(repository) -> ResearchMission:
    mission = ResearchMission(
        title="YouTube only",
        keywords=["one platform"],
        platforms=[PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository.save_mission(mission)
    return mission


async def test_a_single_platform_selection_survives_save_and_get(repository_case):
    mission = await _youtube_only(repository_case.repository)

    stored = await repository_case.repository.get_mission(mission.id)

    assert stored.platforms == [PlatformType.YOUTUBE]


async def test_the_selection_survives_a_listing(repository_case):
    mission = await _youtube_only(repository_case.repository)

    listed = {m.id: m for m in await repository_case.repository.list_missions(limit=10)}

    assert listed[mission.id].platforms == [PlatformType.YOUTUBE]


async def test_the_selection_survives_a_status_update(repository_case):
    """Every status write goes through the same upsert, so it can drop the column too."""
    mission = await _youtube_only(repository_case.repository)
    mission.status = "RUNNING"
    await repository_case.repository.update_mission(mission)

    stored = await repository_case.repository.get_mission(mission.id)

    assert stored.platforms == [PlatformType.YOUTUBE]
    assert stored.status == "RUNNING"


async def test_an_edited_selection_is_written_on_update(repository_case):
    """The conflict branch of the upsert has to carry the column, not only the insert branch.

    Asserting an unchanged selection after an update proves nothing: the value the insert wrote
    is already correct, so it survives whether or not the update mentions the column. Only a
    changed selection tells them apart.
    """
    mission = await _youtube_only(repository_case.repository)
    mission.platforms = [PlatformType.TIKTOK, PlatformType.THREADS]
    await repository_case.repository.update_mission(mission)

    stored = await repository_case.repository.get_mission(mission.id)

    assert stored.platforms == [PlatformType.TIKTOK, PlatformType.THREADS]


async def test_execution_asks_the_registry_for_exactly_that_platform(repository_case):
    """The registry is what turns the stored selection into real calls."""
    mission = await _youtube_only(repository_case.repository)
    registry = RecordingRegistry(
        source_url=YT_URL, raw_title="A sighting", metadata={"video_id": YT_ID}
    )
    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository,
        registry=registry,
        clusterer=SemanticClusterer(),
    )

    result = await use_case.execute(mission.id)

    assert registry.requested_platforms == [PlatformType.YOUTUBE]
    assert "1/1 responsive platforms" in result["summary"], (
        "the denominator is what the mission asked for, not the five it never selected"
    )


async def test_a_pass_that_collected_nothing_says_so(repository_case):
    """The reported shape of the old bug: 0 signals summarised as 1/5 responsive platforms."""
    mission = await _youtube_only(repository_case.repository)

    class Silent:
        async def search_across_all(self, **_kwargs):
            return []

    use_case = ExecuteMissionUseCase(
        repository=repository_case.repository, registry=Silent(), clusterer=SemanticClusterer()
    )

    result = await use_case.execute(mission.id)

    assert result["total_signals"] == 0
    assert "0 signals" in result["summary"]
    assert "0/1 responsive platforms" in result["summary"]


async def test_a_multi_platform_selection_round_trips_in_order(repository_case):
    mission = ResearchMission(
        title="Three platforms",
        keywords=["three"],
        platforms=[PlatformType.TIKTOK, PlatformType.THREADS, PlatformType.YOUTUBE],
        geo_code=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
    )
    await repository_case.repository.save_mission(mission)

    stored = await repository_case.repository.get_mission(mission.id)

    assert stored.platforms == [PlatformType.TIKTOK, PlatformType.THREADS, PlatformType.YOUTUBE]


async def test_a_sqlite_database_from_before_the_column_is_migrated(tmp_path):
    """A file created before platforms existed cannot say what the mission asked for.

    The selection was never written down, so there is nothing to recover. Those rows are given
    the five-platform default, which keeps them behaving exactly as they did before this change
    -- that is a migration assumption, not evidence about what those missions meant.
    """
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    db_path = tmp_path / "vintage.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE research_missions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, keywords TEXT NOT NULL,
                shortcode TEXT UNIQUE, geo_code TEXT DEFAULT 'VN',
                timeframe TEXT DEFAULT '30d', status TEXT DEFAULT 'INITIALIZED',
                agent TEXT DEFAULT 'generic', session_id TEXT, summary TEXT,
                created_at TEXT NOT NULL, updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO research_missions (id, title, keywords, created_at)"
            " VALUES ('11111111-1111-1111-1111-111111111111', 'an older mission', '[\"k\"]',"
            " '2026-08-01T00:00:00+00:00')"
        )

    repository = SqliteTrendRepository(str(db_path))
    try:
        from uuid import UUID

        stored = await repository.get_mission(UUID("11111111-1111-1111-1111-111111111111"))
        assert stored is not None, "the row must survive the migration"
        assert [p.value for p in stored.platforms] == [
            "youtube",
            "google",
            "tiktok",
            "threads",
            "reels",
        ], "the five connectors that existed when those rows were written, frozen as a literal"

        # And the column is really there now, so a new mission keeps its own selection.
        mission = await _youtube_only(repository)
        assert (await repository.get_mission(mission.id)).platforms == [PlatformType.YOUTUBE]

        # Idempotent: opening the same file again changes nothing.
        await repository.close()
        again = SqliteTrendRepository(str(db_path))
        try:
            await again._ensure_schema()
            with sqlite3.connect(db_path) as conn:
                assert conn.execute("SELECT count(*) FROM research_missions").fetchone()[0] == 2
                columns = {row[1] for row in conn.execute("PRAGMA table_info(research_missions)")}
                assert "platforms" in columns
        finally:
            await again.close()
    finally:
        await repository.close()


async def test_the_legacy_default_does_not_follow_a_sixth_connector(monkeypatch, tmp_path):
    """Reading the default off the enum would rewrite what an old mission is taken to have meant.

    The five values are what existed when those rows were written. Deriving them from
    PlatformType instead means the day a sixth connector is registered, every mission from
    before the column starts asking for it too -- a change to history, made by an unrelated
    commit. Registering that sixth connector here is the only way to tell a frozen literal
    apart from a list that happens to have five entries today.
    """
    from enum import Enum

    from ignis.infrastructure.persistence import sqlite_repository

    class SixConnectors(str, Enum):
        YOUTUBE = "youtube"
        GOOGLE_TRENDS = "google"
        TIKTOK = "tiktok"
        THREADS = "threads"
        REELS = "reels"
        SIXTH = "sixth"

    monkeypatch.setattr(sqlite_repository, "PlatformType", SixConnectors)

    db_path = tmp_path / "vintage_sixth.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE research_missions (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, keywords TEXT NOT NULL,
                shortcode TEXT UNIQUE, geo_code TEXT DEFAULT 'VN',
                timeframe TEXT DEFAULT '30d', status TEXT DEFAULT 'INITIALIZED',
                agent TEXT DEFAULT 'generic', session_id TEXT, summary TEXT,
                created_at TEXT NOT NULL, updated_at TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO research_missions (id, title, keywords, created_at)"
            " VALUES ('22222222-2222-2222-2222-222222222222', 'an older mission', '[\"k\"]',"
            " '2026-08-01T00:00:00+00:00')"
        )

    repository = sqlite_repository.SqliteTrendRepository(str(db_path))
    try:
        await repository._ensure_schema()
        with sqlite3.connect(db_path) as conn:
            stored = conn.execute("SELECT platforms FROM research_missions").fetchone()[0]
    finally:
        await repository.close()

    assert json.loads(stored) == ["youtube", "google", "tiktok", "threads", "reels"]
