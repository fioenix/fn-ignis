"""T006: watchlists, versions and runs behave the same on SQLite and PostgreSQL (Spec 016, FR-016)."""

import asyncio
import sqlite3
from uuid import uuid4

import pytest

from ignis.domain.entities import ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.research_workspace import ResearchWorkspace
from ignis.domain.watchlist import WatchlistConflict, parse_watchlist_definition

pytestmark = pytest.mark.asyncio


def definition(*keywords):
    return parse_watchlist_definition({"topics": [{
        "name": "Matcha drinks",
        "categories": ["đồ uống"],
        "keywords": list(keywords or ("matcha latte", "trà xanh")),
        "brands": [{"platform": "tiktok", "account": "@BrandX", "declared_name": "Brand X"}],
        "discovery_share": 0.1,
    }]})


async def _workspace(repository, tmp_path, slug="watchlists"):
    workspace = ResearchWorkspace(slug=slug, root_path=tmp_path / slug)
    await repository.save_research_workspace(workspace)
    return workspace.workspace_id


async def test_create_reads_back_the_first_version(repository_case, tmp_path):
    repository = repository_case.repository
    workspace = await _workspace(repository, tmp_path)
    created = await repository.create_watchlist(workspace, "Matcha", definition())
    read = await repository.get_watchlist(created.id)
    assert read == created
    assert read.workspace_id == str(workspace) and read.name == "Matcha"
    assert [v.version for v in read.versions] == [1]
    assert read.current.definition == definition()
    assert read.runs == ()


async def test_names_are_unique_per_workspace_ignoring_case(repository_case, tmp_path):
    repository = repository_case.repository
    workspace = await _workspace(repository, tmp_path)
    other = await _workspace(repository, tmp_path, "other")
    await repository.create_watchlist(workspace, "Trà Sữa", definition())
    with pytest.raises(WatchlistConflict) as caught:
        await repository.create_watchlist(workspace, "TRÀ SỮA", definition())
    assert caught.value.code == "DUPLICATE_NAME"
    assert (await repository.create_watchlist(other, "Trà Sữa", definition())).workspace_id == str(other)


async def test_concurrent_creates_of_one_name_leave_exactly_one(repository_case, tmp_path):
    repository = repository_case.repository
    workspace = await _workspace(repository, tmp_path)
    results = await asyncio.gather(
        *(repository.create_watchlist(workspace, "Matcha", definition()) for _ in range(4)),
        return_exceptions=True,
    )
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert all(r.code == "DUPLICATE_NAME" for r in results if isinstance(r, Exception))


async def test_versions_append_only_when_the_meaning_changes(repository_case, tmp_path):
    repository = repository_case.repository
    created = await repository.create_watchlist(await _workspace(repository, tmp_path), "Matcha", definition())
    same, added = await repository.add_watchlist_version(created.id, definition())
    assert not added and [v.version for v in same.versions] == [1]
    revised, added = await repository.add_watchlist_version(created.id, definition("matcha latte"))
    assert added and [v.version for v in revised.versions] == [1, 2]
    back, added = await repository.add_watchlist_version(created.id, definition())
    assert added and [v.version for v in back.versions] == [1, 2, 3]
    assert back.versions[0].definition == back.versions[2].definition


async def test_unknown_watchlist(repository_case):
    repository = repository_case.repository
    assert await repository.get_watchlist(uuid4()) is None
    with pytest.raises(WatchlistConflict) as caught:
        await repository.add_watchlist_version(uuid4(), definition())
    assert caught.value.code == "NOT_FOUND"


async def test_runs_stay_on_the_version_they_collected(repository_case, tmp_path):
    repository = repository_case.repository
    workspace = await _workspace(repository, tmp_path)
    created = await repository.create_watchlist(workspace, "Matcha", definition())
    missions = []
    for version in (1, 2):
        if version == 2:
            await repository.add_watchlist_version(created.id, definition("matcha latte"))
        mission = ResearchMission(title=f"run {version}", keywords=["matcha"], workspace_id=workspace)
        await repository.save_mission(mission)
        await repository.record_watchlist_run(mission.id, created.id, version)
        missions.append(mission)
    read = await repository.get_watchlist(created.id)
    assert [(r.mission_id, r.version) for r in read.runs] == [(str(m.id), v) for m, v in zip(missions, (1, 2))]
    assert all(r.mission_status for r in read.runs)
    # One mission belongs to one version: SQLite's constraint error, PostgreSQL's wrapped one.
    with pytest.raises((sqlite3.IntegrityError, RepositoryException)):
        await repository.record_watchlist_run(missions[0].id, created.id, 2)
