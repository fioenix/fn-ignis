"""Two runs in one research workspace must not overwrite each other.

The foundational half of that contract: one writer per mission, and an exclusive journal name
per run even when two runs start inside the same second. The wider concurrency hardening --
independent progress for unrelated missions, and recovery readback -- is P2 work and is not
covered here.
"""

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import ResearchSurface
from ignis.infrastructure.persistence import workspace_repository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest.fixture
def host_workspace(tmp_path) -> Path:
    root = tmp_path / "host-project"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_two_runs_starting_in_the_same_second_get_distinct_journals(
    repository_case, host_workspace, monkeypatch
):
    """The clock is frozen, because the collision only exists inside one second.

    Allocating twice and hoping both land in the same second is not a test of anything: on a
    slow run the two straddle a second boundary, each starts its sequence at 001, and the
    assertion fails while the allocator was right the whole time. Freezing the clock is what the
    quickstart asks for and what makes the invariant deterministic on both backends.
    """
    frozen = datetime(2026, 9, 21, 10, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(workspace_repository, "_utc_now", lambda: frozen)

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

    # Same second, same stamp, so only the fixed-width sequence keeps the two names apart.
    assert first.journal_path != second.journal_path
    assert (first.sequence, second.sequence) == (1, 2)
    assert "20260921-103000-001" in first.journal_path.name
    assert "20260921-103000-002" in second.journal_path.name
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
