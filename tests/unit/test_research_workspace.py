"""The research workspace boundary: proposed read-only, created only once confirmed.

A proposal is an answer to "where would this live?". Everything in this module is about the gap
between that answer and any durable write, and about what happens when the folder the requester
picked already holds something.
"""

from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio

from ignis.application.use_cases.create_research_workspace import (
    CreateResearchWorkspaceUseCase,
)
from ignis.domain.research_workspace import (
    MANIFEST_FILENAME,
    InvalidWorkspaceSlugError,
    WorkspaceAdoptionRequiredError,
    WorkspaceStatus,
    slugify_research_name,
    validate_slug,
)
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


@pytest_asyncio.fixture
async def workspace_use_case(tmp_path):
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    store = WorkspaceRepository(repository=repository)
    yield CreateResearchWorkspaceUseCase(store=store)
    await repository.close()


@pytest.fixture
def host_workspace(tmp_path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def test_a_research_name_becomes_the_child_folder_name():
    assert slugify_research_name("AI customer service") == "ai-customer-service"
    assert slugify_research_name("  Retail   Ops 2026 ") == "retail-ops-2026"


@pytest.mark.parametrize("name", ["", "   ", "///"])
def test_a_name_that_cannot_become_a_folder_name_is_refused(name):
    with pytest.raises(InvalidWorkspaceSlugError):
        slugify_research_name(name)


@pytest.mark.parametrize("slug", ["../escape", "research", "Upper-Case", "a/b", "-leading"])
def test_a_slug_that_would_escape_or_collide_with_the_layout_is_refused(slug):
    # validate_slug is the gate a caller reaches when it supplies a slug directly rather than a
    # research name. slugify_research_name would have normalised some of these into something
    # harmless, which is exactly why the explicit path needs its own refusal.
    with pytest.raises(InvalidWorkspaceSlugError):
        validate_slug(slug)


@pytest.mark.asyncio
async def test_a_proposal_writes_nothing_at_all(workspace_use_case, host_workspace):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")

    assert proposal.proposed_path == (
        host_workspace / ".ignis" / "research" / "ai-customer-service"
    )
    assert proposal.requires_confirmation is True
    # Not just the research folder: the `.ignis` parent is a durable write too.
    assert not (host_workspace / ".ignis").exists()
    assert list(host_workspace.iterdir()) == []


@pytest.mark.asyncio
async def test_a_proposal_stays_inside_the_host_workspace(workspace_use_case, host_workspace):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    assert host_workspace.resolve() in proposal.proposed_path.resolve().parents


@pytest.mark.asyncio
async def test_declining_the_proposal_leaves_no_trace(workspace_use_case, host_workspace):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    result = await workspace_use_case.confirm(proposal, confirmation=False)

    assert result is None
    assert not proposal.proposed_path.exists()
    assert not (host_workspace / ".ignis").exists()


@pytest.mark.asyncio
async def test_confirming_creates_the_folder_the_manifest_and_the_scoped_record(
    workspace_use_case, host_workspace
):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    workspace = await workspace_use_case.confirm(proposal, confirmation=True)

    assert workspace.status is WorkspaceStatus.READY
    assert workspace.manifest_path.is_file()

    reopened = await workspace_use_case.reopen(workspace.workspace_id)
    assert reopened is not None
    assert reopened.workspace_id == workspace.workspace_id
    assert reopened.slug == "ai-customer-service"


@pytest.mark.asyncio
async def test_a_second_host_reopens_the_same_research_from_the_manifest(
    workspace_use_case, host_workspace
):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    workspace = await workspace_use_case.confirm(proposal, confirmation=True)

    # A different Agent host on the same database re-proposes the same research and finds it.
    second = await workspace_use_case.propose(host_workspace, "AI customer service")
    assert second.has_manifest is True
    assert second.existing_workspace is not None
    assert second.existing_workspace.workspace_id == workspace.workspace_id
    assert second.requires_adoption is False


@pytest.mark.asyncio
async def test_reusing_a_matching_manifest_does_not_rewrite_it(
    workspace_use_case, host_workspace
):
    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    workspace = await workspace_use_case.confirm(proposal, confirmation=True)
    original = workspace.manifest_path.read_text()

    again = await workspace_use_case.propose(host_workspace, "AI customer service")
    reused = await workspace_use_case.confirm(again, confirmation=True)

    assert reused.workspace_id == workspace.workspace_id
    assert workspace.manifest_path.read_text() == original


@pytest.mark.asyncio
async def test_a_non_empty_folder_without_a_manifest_needs_explicit_adoption(
    workspace_use_case, host_workspace
):
    target = host_workspace / ".ignis" / "research" / "ai-customer-service"
    target.mkdir(parents=True)
    (target / "notes.md").write_text("field notes the requester wrote by hand\n")

    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    assert proposal.requires_adoption is True
    assert proposal.is_empty is False

    with pytest.raises(WorkspaceAdoptionRequiredError):
        await workspace_use_case.confirm(proposal, confirmation=True)


@pytest.mark.asyncio
async def test_adoption_preserves_every_unrelated_file(workspace_use_case, host_workspace):
    target = host_workspace / ".ignis" / "research" / "ai-customer-service"
    target.mkdir(parents=True)
    (target / "notes.md").write_text("field notes the requester wrote by hand\n")

    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    workspace = await workspace_use_case.confirm(proposal, confirmation=True, adopt=True)

    assert workspace.manifest_path.is_file()
    assert (target / "notes.md").read_text() == "field notes the requester wrote by hand\n"


@pytest.mark.asyncio
async def test_a_manifest_from_a_newer_format_is_reported_rather_than_half_read(
    workspace_use_case, host_workspace
):
    target = host_workspace / ".ignis" / "research" / "ai-customer-service"
    target.mkdir(parents=True)
    (target / MANIFEST_FILENAME).write_text(
        '{"workspace_id": "%s", "slug": "ai-customer-service", "format_version": 99,'
        ' "created_at": "2026-09-21T00:00:00+00:00"}' % uuid4()
    )

    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    assert proposal.manifest_status is WorkspaceStatus.INCOMPATIBLE

    with pytest.raises(WorkspaceAdoptionRequiredError):
        await workspace_use_case.confirm(proposal, confirmation=True)


@pytest.mark.asyncio
async def test_a_manifest_naming_another_research_is_not_silently_reused(
    workspace_use_case, host_workspace
):
    target = host_workspace / ".ignis" / "research" / "ai-customer-service"
    target.mkdir(parents=True)
    (target / MANIFEST_FILENAME).write_text(
        '{"workspace_id": "%s", "slug": "retail-ops", "format_version": 1,'
        ' "created_at": "2026-09-21T00:00:00+00:00"}' % uuid4()
    )

    proposal = await workspace_use_case.propose(host_workspace, "AI customer service")
    assert proposal.requires_adoption is True


# --- User Story 5: one writer per mission, one journal per run ---------------

@pytest_asyncio.fixture
async def concurrency_workspace(tmp_path):
    """A confirmed workspace on its own in-memory database, plus the store that owns it."""
    repository = SqliteTrendRepository(db_path="sqlite:///:memory:")
    store = WorkspaceRepository(repository=repository)
    use_case = CreateResearchWorkspaceUseCase(store=store)
    host = tmp_path / "concurrency-host"
    host.mkdir()
    workspace = await use_case.confirm(
        await use_case.propose(host, "AI customer service"), confirmation=True
    )
    try:
        yield repository, store, workspace
    finally:
        await repository.close()


async def _mission(repository, workspace, title="AI customer service"):
    from ignis.domain.entities import ResearchMission
    from ignis.domain.research_workspace import ResearchSurface

    mission = ResearchMission(
        title=title,
        keywords=["ai customer service"],
        workspace_id=workspace.workspace_id,
        surface=ResearchSurface.ATTENTION.value,
    )
    await repository.create_mission(mission)
    return mission


@pytest.mark.asyncio
async def test_a_second_writer_for_one_mission_is_refused_by_name(concurrency_workspace):
    from ignis.domain.research_workspace import MissionWriterConflictError

    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    holder, intruder = uuid4(), uuid4()
    await store.require_mission_writer(mission.id, holder)
    with pytest.raises(MissionWriterConflictError) as excinfo:
        await store.require_mission_writer(mission.id, intruder)
    assert str(mission.id) in str(excinfo.value)

    # The refusal changed nothing: the first run still holds the slot.
    claim = await store.get_mission_writer_claim(mission.id)
    assert claim is not None and claim.run_id == holder


@pytest.mark.asyncio
async def test_releasing_the_claim_hands_the_slot_to_the_next_run(concurrency_workspace):
    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    first, second = uuid4(), uuid4()
    await store.require_mission_writer(mission.id, first)
    await store.release_mission_writer(mission.id, first)
    assert await store.get_mission_writer_claim(mission.id) is None
    await store.require_mission_writer(mission.id, second)
    assert (await store.get_mission_writer_claim(mission.id)).run_id == second


@pytest.mark.asyncio
async def test_two_missions_in_one_workspace_are_claimed_independently(concurrency_workspace):
    """The claim is per mission. Serializing a whole research would be a different contract."""
    repository, store, workspace = concurrency_workspace
    first = await _mission(repository, workspace, title="First question")
    second = await _mission(repository, workspace, title="Second question")

    assert await store.claim_mission_writer(first.id, uuid4()) is True
    assert await store.claim_mission_writer(second.id, uuid4()) is True


@pytest.mark.asyncio
async def test_a_run_holds_the_slot_for_its_body_and_gives_it_back_on_success(
    concurrency_workspace,
):
    from ignis.domain.research_workspace import MissionWriterConflictError

    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    async with store.mission_run(workspace, mission.id) as journal:
        assert journal.mission_id == mission.id
        assert journal.workspace_id == workspace.workspace_id
        assert journal.status == "STARTED"
        with pytest.raises(MissionWriterConflictError):
            await store.require_mission_writer(mission.id, uuid4())

    assert await store.get_mission_writer_claim(mission.id) is None
    finished = await store.latest_run_journal(mission.id)
    assert (finished.run_id, finished.status) == (journal.run_id, "COMPLETED")
    assert finished.completed_at is not None


@pytest.mark.asyncio
async def test_a_failed_run_gives_the_slot_back_and_records_the_failure(concurrency_workspace):
    """The claim is released in a finally path, so a failed run does not lock the mission out."""
    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    with pytest.raises(RuntimeError):
        async with store.mission_run(workspace, mission.id):
            raise RuntimeError("ingress exploded")

    assert await store.get_mission_writer_claim(mission.id) is None
    failed = await store.latest_run_journal(mission.id)
    assert failed.status == "FAILED"
    assert failed.completed_at is not None
    # And the next run can start.
    async with store.mission_run(workspace, mission.id):
        pass
    assert len(await store.list_run_journals(mission.id)) == 2


@pytest.mark.asyncio
async def test_an_interrupted_run_reads_back_as_unfinished_rather_than_completed(
    concurrency_workspace,
):
    """A run that never finalized claims no completion.

    completed_at stays NULL, which is the difference between "this run ended" and "nobody ever
    heard from it again". Reporting NOW() at read time would turn the second into the first.
    """
    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    run_id = uuid4()
    await store.require_mission_writer(mission.id, run_id)
    journal = await store.allocate_run_journal(workspace, mission.id, run_id=run_id)

    interrupted = await store.latest_run_journal(mission.id)
    assert (interrupted.run_id, interrupted.status) == (run_id, "STARTED")
    assert interrupted.completed_at is None
    # The writer state is readable too, which is what makes the stale claim recoverable.
    claim = await store.get_mission_writer_claim(mission.id)
    assert claim.run_id == run_id and claim.claimed_at is not None
    assert journal.journal_path.is_file()


@pytest.mark.asyncio
async def test_the_journal_file_records_what_the_readback_reports(concurrency_workspace):
    import json

    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    async with store.mission_run(workspace, mission.id) as journal:
        started = json.loads(journal.journal_path.read_text(encoding="utf-8"))
        assert started["status"] == "STARTED"
        assert started["mission_id"] == str(mission.id)
        assert started["workspace_id"] == str(workspace.workspace_id)

    finished = json.loads(journal.journal_path.read_text(encoding="utf-8"))
    assert finished["status"] == "COMPLETED"
    assert finished["run_id"] == str(journal.run_id)
    assert finished["completed_at"]
    stored = await store.latest_run_journal(mission.id)
    assert finished["completed_at"] == stored.completed_at.isoformat()


@pytest.mark.asyncio
async def test_a_run_that_cannot_take_the_slot_writes_no_journal(concurrency_workspace):
    from ignis.domain.research_workspace import MissionWriterConflictError

    repository, store, workspace = concurrency_workspace
    mission = await _mission(repository, workspace)

    async with store.mission_run(workspace, mission.id):
        with pytest.raises(MissionWriterConflictError):
            async with store.mission_run(workspace, mission.id):
                pass
        # Exactly one journal exists: the refused run never got a name of its own.
        assert len(await store.list_run_journals(mission.id)) == 1
