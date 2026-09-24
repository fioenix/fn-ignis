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


def _write_brief_revision(case, workspace_id, mission_id, revision_number, falsifiers):
    """Insert one Brief revision directly, so the schema is what answers, not the use case.

    The application already refuses an empty falsifier list. That is the layer a later caller
    can bypass -- a backfill, a repair script, another service on the same database -- so the
    question here is whether the schema refuses it too.
    """
    import json

    columns = (
        "id, workspace_id, mission_id, revision_number, decision, target_user, problem,"
        " geo, timeframe, hypothesis, falsifiers, confirmed_by"
    )
    values = (
        str(uuid4()), str(workspace_id), str(mission_id), revision_number,
        "decision", "target user", "problem", "VN", "30d", "hypothesis",
    )
    if case.name == "sqlite":
        import sqlite3

        with sqlite3.connect(case.repository._db_path) as conn:
            conn.execute(
                f"INSERT INTO market_brief_revisions ({columns}, confirmed_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                values + (json.dumps(falsifiers), "requester", "2026-01-01T00:00:00+00:00"),
            )
        return

    import psycopg

    with psycopg.connect(case.dsn) as conn:
        conn.execute(
            f"INSERT INTO market_brief_revisions ({columns})"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            values + (list(falsifiers), "requester"),
        )


def _integrity_errors(case):
    if case.name == "sqlite":
        import sqlite3

        return (sqlite3.IntegrityError,)
    import psycopg

    return (psycopg.errors.IntegrityError,)


async def _market_mission_in_a_confirmed_research(repository_case, host_workspace):
    store = WorkspaceRepository(repository=repository_case.repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    proposal = await use_case.propose(host_workspace, "AI customer service")
    workspace = await use_case.confirm(proposal, confirmation=True)
    mission = ResearchMission(
        title="Market investigation",
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.MARKET.value,
    )
    await repository_case.repository.save_mission(mission)
    return store, workspace, mission


@pytest.mark.asyncio
async def test_the_schema_refuses_a_brief_with_no_falsifier_on_both_backends(
    repository_case, host_workspace
):
    """A hypothesis that cannot lose is not a hypothesis, and the database has to say so.

    PostgreSQL used to accept it: `array_length('{}', 1)` is NULL, and a CHECK that evaluates
    to NULL is not a violation. SQLite refused the same write, so the two backends disagreed
    about the one rule that makes a Brief falsifiable.
    """
    store, workspace, mission = await _market_mission_in_a_confirmed_research(
        repository_case, host_workspace
    )

    with pytest.raises(_integrity_errors(repository_case)) as raised:
        _write_brief_revision(
            repository_case, workspace.workspace_id, mission.id, 1, falsifiers=[]
        )

    # Refused by the falsifier rule itself, not by a foreign key or a unique index.
    assert "falsifiers" in str(raised.value).lower()
    assert await store.get_brief_revision_for_mission(mission.id) is None


@pytest.mark.asyncio
async def test_the_schema_accepts_a_brief_that_names_one_falsifier(
    repository_case, host_workspace
):
    """The positive control: the constraint refuses emptiness, not every Brief."""
    store, workspace, mission = await _market_mission_in_a_confirmed_research(
        repository_case, host_workspace
    )

    _write_brief_revision(
        repository_case, workspace.workspace_id, mission.id, 1,
        falsifiers=["No retailer names reply latency among their top three costs"],
    )

    stored = await store.get_brief_revision_for_mission(mission.id)
    assert stored is not None
    assert list(stored.falsifiers) == [
        "No retailer names reply latency among their top three costs"
    ]
