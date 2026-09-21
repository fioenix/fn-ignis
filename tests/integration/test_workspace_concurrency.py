"""Two runs in one research workspace must not overwrite each other.

The foundational half of that contract: one writer per mission, and an exclusive journal name
per run even when two runs start inside the same second. The wider concurrency hardening --
independent progress for unrelated missions, and recovery readback -- is P2 work and is not
covered here.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import ResearchSurface
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest.fixture
def host_workspace(tmp_path) -> Path:
    root = tmp_path / "host-project"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_two_runs_starting_in_the_same_second_get_distinct_journals(
    repository_case, host_workspace
):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await use_case.confirm(
        await use_case.propose(host_workspace, "AI customer service"), confirmation=True
    )

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    first = await store.allocate_run_journal(workspace, mission.id, run_id=uuid4())
    original_bytes = first.journal_path.read_bytes()
    second = await store.allocate_run_journal(workspace, mission.id, run_id=uuid4())

    assert first.journal_path != second.journal_path
    assert first.sequence != second.sequence
    # The earlier run's evidence is still exactly what it wrote.
    assert first.journal_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_a_mission_has_at_most_one_active_writer(repository_case, host_workspace):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    workspace = await use_case.confirm(
        await use_case.propose(host_workspace, "AI customer service"), confirmation=True
    )

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    first_run, second_run = uuid4(), uuid4()
    assert await store.claim_mission_writer(mission.id, first_run) is True
    assert await store.claim_mission_writer(mission.id, second_run) is False

    # A run that does not hold the claim cannot release it either.
    await store.release_mission_writer(mission.id, second_run)
    assert await store.claim_mission_writer(mission.id, second_run) is False

    await store.release_mission_writer(mission.id, first_run)
    assert await store.claim_mission_writer(mission.id, second_run) is True
