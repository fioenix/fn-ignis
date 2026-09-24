"""Propose, confirm, reuse or adopt the child workspace one research lives in.

The shape of this use case is the product rule it enforces: proposing is read-only and confirming
is the only thing that writes. Nothing between the two is durable, so a requester who changes
their mind leaves no folder, no manifest, no database row and no journal behind.
"""

import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from ignis.application.ports.research_workspace_port import (
    IResearchWorkspaceStore,
    WorkspaceProposal,
)
from ignis.domain.research_workspace import (
    InvalidWorkspaceManifestError,
    InvalidWorkspaceSlugError,
    ResearchWorkspace,
    WorkspaceAdoptionRequiredError,
    WorkspaceStatus,
    research_root,
    slugify_research_name,
    validate_slug,
)
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository

logger = logging.getLogger(__name__)


class CreateResearchWorkspaceUseCase:
    """The workspace lifecycle: propose, confirm, reuse, adopt, reopen."""

    def __init__(self, store: IResearchWorkspaceStore):
        self._store = store

    async def propose(
        self,
        host_workspace: Path,
        research_name: str,
        slug: Optional[str] = None,
    ) -> WorkspaceProposal:
        """Answer where this research would live. Writes nothing, including no parent directory.

        Everything the proposal reports about the target path is observed. `requires_adoption`
        in particular is a statement about what is already on disk, not a decision about what to
        do with it -- that decision belongs to the requester.
        """
        host_root = Path(host_workspace).expanduser()
        resolved_slug = validate_slug(slug) if slug else slugify_research_name(research_name)
        proposed_path = research_root(host_root) / resolved_slug

        # Structural containment. The slug cannot hold a separator or a parent reference --
        # validate_slug refuses both -- so the join cannot climb out of the host workspace. The
        # assertion is kept because a future caller reaching this with a path is a real risk.
        if host_root.resolve() not in proposed_path.resolve().parents:
            raise InvalidWorkspaceSlugError(
                f"'{resolved_slug}' would place the research outside {host_root}."
            )

        exists = proposed_path.is_dir()
        entries = list(proposed_path.iterdir()) if exists else []
        is_empty = not entries

        manifest: Optional[ResearchWorkspace] = None
        manifest_status: Optional[WorkspaceStatus] = None
        notes = []
        requires_adoption = False

        if exists:
            try:
                manifest = WorkspaceRepository.read_manifest(proposed_path)
            except InvalidWorkspaceManifestError:
                manifest = None
                notes.append(
                    "A manifest is present but cannot be read. Adoption is required, and no "
                    "existing file will be deleted or overwritten."
                )
                requires_adoption = True

            if manifest is not None:
                manifest_status = manifest.status
                if manifest.status is WorkspaceStatus.INCOMPATIBLE:
                    requires_adoption = True
                    notes.append(
                        f"The manifest was written in format version {manifest.format_version}, "
                        "which this build cannot open."
                    )
                elif manifest.slug != resolved_slug:
                    requires_adoption = True
                    notes.append(
                        f"The folder already holds the research '{manifest.slug}', "
                        f"not '{resolved_slug}'."
                    )
            elif not is_empty and not requires_adoption:
                requires_adoption = True
                notes.append(
                    "The folder is not empty and holds no workspace manifest. Adopting it "
                    "leaves every file already there untouched."
                )

        existing = manifest if (manifest is not None and not requires_adoption) else None
        if existing is not None:
            # The manifest is the filesystem entry point; the database is the record store. A
            # manifest whose identity the database does not know is reported as-is rather than
            # quietly re-registered.
            known = await self._store.get_research_workspace(existing.workspace_id)
            if known is None:
                notes.append(
                    "The manifest names a research the configured Ignis database does not hold. "
                    "Confirming will register it under the identity the manifest already has."
                )

        return WorkspaceProposal(
            host_workspace=host_root,
            research_name=research_name,
            slug=resolved_slug,
            proposed_path=proposed_path,
            exists=exists,
            has_manifest=manifest is not None,
            is_empty=is_empty,
            requires_adoption=requires_adoption,
            requires_confirmation=True,
            existing_workspace=existing,
            manifest_status=manifest_status,
            notes=notes,
        )

    async def confirm(
        self,
        proposal: WorkspaceProposal,
        confirmation: bool,
        adopt: bool = False,
    ) -> Optional[ResearchWorkspace]:
        """Create, reuse or adopt the proposed workspace. Returns None when declined.

        `adopt` is a second, separate confirmation. It exists because "yes, create the research"
        and "yes, use this folder that already has my files in it" are different answers, and
        collapsing them would let one click reuse a directory the requester never looked at.
        """
        if not confirmation:
            logger.info("Workspace creation declined for '%s'; nothing was written.", proposal.slug)
            return None

        if proposal.requires_adoption and not adopt:
            raise WorkspaceAdoptionRequiredError(
                f"{proposal.proposed_path} cannot be used without an explicit adoption "
                "confirmation. "
                + (" ".join(proposal.notes) if proposal.notes else "")
            )

        if proposal.existing_workspace is not None:
            # Reuse. The manifest already on disk is the identity, and it is not rewritten.
            workspace = proposal.existing_workspace
            return await self._store.save_research_workspace(workspace)

        # A record the database already holds for this exact path keeps its identity. Minting a
        # second one would leave the same research addressable under two ids, and every mission
        # written afterwards would be scoped to whichever the caller happened to hold.
        existing_record = await self._store.find_research_workspace_by_slug(
            proposal.slug, root_path=proposal.proposed_path
        )
        workspace = ResearchWorkspace(
            slug=proposal.slug,
            root_path=proposal.proposed_path,
            name=proposal.research_name,
            **({"workspace_id": existing_record.workspace_id} if existing_record else {}),
        )

        try:
            WorkspaceRepository.write_manifest(workspace)
        except FileExistsError:
            # Another host wrote the manifest between the proposal and this confirmation. Its
            # identity wins; this one is discarded rather than overwriting a research that
            # already exists.
            adopted = WorkspaceRepository.read_manifest(proposal.proposed_path)
            if adopted is None:
                raise
            logger.info(
                "Workspace %s was created by another host first; reusing its identity %s.",
                proposal.slug,
                adopted.workspace_id,
            )
            return await self._store.save_research_workspace(adopted)

        return await self._store.save_research_workspace(workspace)

    async def reopen(self, workspace_id: UUID) -> Optional[ResearchWorkspace]:
        """Reopen a research by identity, from any Agent host on the same configured database."""
        return await self._store.get_research_workspace(workspace_id)
