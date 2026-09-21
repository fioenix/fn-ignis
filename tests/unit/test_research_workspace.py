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
