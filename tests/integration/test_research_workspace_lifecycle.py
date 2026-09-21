"""The workspace lifecycle against a real database, on both configured backends.

A research has to be reopenable from a second Agent host that shares the Ignis database and
never saw the chat that created it. These tests use two repository instances over one database
to stand for those two hosts, and they assert the two halves of the contract: nothing durable
before confirmation, and a scope that refuses another research's records rather than returning
an empty answer for them.
"""

from pathlib import Path
from uuid import uuid4

import pytest

from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    MANIFEST_FILENAME,
    ResearchSurface,
    WorkspaceAdoptionRequiredError,
    WorkspaceScopeMismatchError,
)
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


def _second_host_repository(case):
    """A second repository over the same database: a different Agent host, same Ignis install."""
    if case.name == "sqlite":
        return SqliteTrendRepository(db_path=case.repository._db_path)
    return PostgresTimescaleRepository(dsn=case.dsn, min_pool_size=1, max_pool_size=2)


@pytest.fixture
def host_workspace(tmp_path) -> Path:
    root = tmp_path / "host-project"
    root.mkdir()
    return root


@pytest.mark.asyncio
async def test_no_durable_research_state_exists_before_confirmation(repository_case, host_workspace):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)

    proposal = await use_case.propose(host_workspace, "AI customer service")

    assert not proposal.proposed_path.exists()
    assert not (host_workspace / ".ignis").exists()
    assert await store.list_research_workspaces() == []


@pytest.mark.asyncio
async def test_a_confirmed_research_reopens_from_a_second_agent_host(
    repository_case, host_workspace
):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)

    proposal = await use_case.propose(host_workspace, "AI customer service")
    workspace = await use_case.confirm(proposal, confirmation=True)

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    second_repo = _second_host_repository(repository_case)
    try:
        second_store = WorkspaceRepository(repository=second_repo)
        reopened = await second_store.get_research_workspace(workspace.workspace_id)

        assert reopened is not None
        assert reopened.workspace_id == workspace.workspace_id
        assert reopened.slug == "ai-customer-service"
        assert reopened.root_path == workspace.root_path

        scoped = await second_store.list_workspace_missions(workspace.workspace_id)
        assert [m.id for m in scoped] == [mission.id]
        assert scoped[0].surface == "ATTENTION"
    finally:
        await second_repo.close()


@pytest.mark.asyncio
async def test_a_mission_addressed_through_the_wrong_research_is_an_error_not_an_empty_answer(
    repository_case, host_workspace
):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)

    first = await use_case.confirm(
        await use_case.propose(host_workspace, "AI customer service"), confirmation=True
    )
    second = await use_case.confirm(
        await use_case.propose(host_workspace, "Retail ops"), confirmation=True
    )

    mission = ResearchMission(
        title="AI customer service",
        keywords=["ai customer service"],
        workspace_id=first.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository_case.repository.save_mission(mission)

    assert await store.get_scoped_mission(first.workspace_id, mission.id) is not None
    with pytest.raises(WorkspaceScopeMismatchError):
        await store.get_scoped_mission(second.workspace_id, mission.id)

    # And the other research genuinely holds nothing, which is a different fact.
    assert await store.list_workspace_missions(second.workspace_id) == []


@pytest.mark.asyncio
async def test_adopting_a_non_empty_folder_preserves_the_files_already_in_it(
    repository_case, host_workspace
):
    target = host_workspace / ".ignis" / "research" / "ai-customer-service"
    target.mkdir(parents=True)
    (target / "interview-notes.md").write_text("what three retailers actually said\n")

    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    proposal = await use_case.propose(host_workspace, "AI customer service")

    with pytest.raises(WorkspaceAdoptionRequiredError):
        await use_case.confirm(proposal, confirmation=True)

    workspace = await use_case.confirm(proposal, confirmation=True, adopt=True)
    assert (target / MANIFEST_FILENAME).is_file()
    assert (target / "interview-notes.md").read_text() == "what three retailers actually said\n"
    assert await store.get_research_workspace(workspace.workspace_id) is not None


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
