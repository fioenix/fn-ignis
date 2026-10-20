"""T074 durable dispatch controls on the actual workspace writer/journal lifecycle."""

import asyncio
from uuid import uuid4

import pytest

from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.domain.entities import ResearchMission
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


async def arranged(repository_case, tmp_path):
    repository = repository_case.repository
    store = WorkspaceRepository(repository)
    root = tmp_path / "host"
    root.mkdir()
    creator = CreateResearchWorkspaceUseCase(store)
    workspace = await creator.confirm(await creator.propose(root, "Offline dispatch"), confirmation=True)
    mission = ResearchMission(title="Offline child", keywords=["bounded"], workspace_id=workspace.workspace_id)
    await repository.save_mission(mission)
    return repository, store, workspace, mission


@pytest.mark.asyncio
async def test_cancelled_committed_journal_setup_settles_canonical_start(repository_case, tmp_path, monkeypatch):
    repository, store, workspace, mission = await arranged(repository_case, tmp_path)
    allocated = asyncio.Event()
    held = asyncio.Event()
    original = store.allocate_run_journal

    async def allocate(*args, **kwargs):
        journal = await original(*args, **kwargs)
        allocated.set()
        await held.wait()
        return journal

    monkeypatch.setattr(store, "allocate_run_journal", allocate)
    probes = []

    async def execute():
        async with store.mission_run(workspace, mission.id):
            probes.append("probe")

    task = asyncio.create_task(execute())
    await asyncio.wait_for(allocated.wait(), 5)
    task.cancel()
    held.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    journals = await repository.list_run_journals(mission.id)
    assert len(journals) == 1
    assert journals[0].status == "FAILED"
    assert await repository.get_mission_writer_claim(mission.id) is None
    assert probes == []


@pytest.mark.asyncio
async def test_failed_setup_journal_finalization_still_releases_exact_claim(repository_case, tmp_path, monkeypatch):
    repository, store, workspace, mission = await arranged(repository_case, tmp_path)
    allocated = asyncio.Event()
    release = asyncio.Event()
    original = store.allocate_run_journal

    async def allocate(*args, **kwargs):
        journal = await original(*args, **kwargs)
        allocated.set()
        await release.wait()
        return journal

    async def fail_finalization(journal):
        raise RuntimeError("Synthetic journal finalization failure")

    monkeypatch.setattr(store, "allocate_run_journal", allocate)
    monkeypatch.setattr(store, "_finish_interrupted_run_journal", fail_finalization)

    body_entries = []

    async def execute():
        async with store.mission_run(workspace, mission.id):
            body_entries.append("entered")

    task = asyncio.create_task(execute())
    await asyncio.wait_for(allocated.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert body_entries == []
    assert await repository.get_mission_writer_claim(mission.id) is None
    assert len(await repository.list_run_journals(mission.id)) == 1


@pytest.mark.asyncio
async def test_cancelled_committed_claim_acknowledgement_leaves_no_writer_or_journal(repository_case, tmp_path, monkeypatch):
    repository, store, workspace, mission = await arranged(repository_case, tmp_path)
    acquired = asyncio.Event()
    release = asyncio.Event()
    original = store.claim_mission_writer

    async def claim(*args):
        result = await original(*args)
        acquired.set()
        await release.wait()
        return result

    monkeypatch.setattr(store, "claim_mission_writer", claim)

    async def execute():
        async with store.mission_run(workspace, mission.id):
            pytest.fail("Cancelled setup must not dispatch")

    task = asyncio.create_task(execute())
    await asyncio.wait_for(acquired.wait(), 5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await repository.get_mission_writer_claim(mission.id) is None
    assert await repository.list_run_journals(mission.id) == []


@pytest.mark.asyncio
async def test_losing_same_id_claimant_cannot_release_winner(repository_case, tmp_path):
    from ignis.domain.research_workspace import MissionWriterConflictError
    repository, store, workspace, mission = await arranged(repository_case, tmp_path)
    run_id = uuid4()
    assert await repository.claim_mission_writer(mission.id, run_id)
    with pytest.raises(MissionWriterConflictError):
        async with store.mission_run(workspace, mission.id, run_id=run_id):
            pytest.fail("Losing claimant must not dispatch")
    assert (await repository.get_mission_writer_claim(mission.id)).run_id == run_id
    assert await repository.list_run_journals(mission.id) == []
    await repository.release_mission_writer(mission.id, run_id)
