"""Workspace-scoped access to the one configured shared Ignis database, plus the files beside it.

Two halves, and they answer different questions:

- the configured database is the canonical record store, and every research-owned read and write
  goes through it under an explicit `workspace_id`; and
- `.ignis/research/<slug>/` holds the manifest that lets a second Agent host find the research at
  all, plus one exclusive journal per run.

Which backend is configured is not this class's decision. It delegates to whichever
`ITrendRepository` the installation built -- SQLite-local by default, PostgreSQL when configured
-- so the workspace contract is identical on both.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import (
    IResearchWorkspaceStore,
    RunJournal,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    JOURNAL_DIRNAME,
    MANIFEST_FILENAME,
    InvalidWorkspaceManifestError,
    MarketBriefRevision,
    MissionWriterConflictError,
    ResearchWorkspace,
    WorkspaceScopeMismatchError,
)
from ignis.infrastructure.persistence import create_repository

logger = logging.getLogger(__name__)

JOURNAL_PREFIX = "run-"
# One more would be four digits wide, and a name of a different width sorts out of order. The
# same bound and the same reason as the cutover journal in scripts/t020_cutover.py.
JOURNAL_SEQUENCE_LIMIT = 1000


def _utc_now() -> datetime:
    """The run clock, in one place so a test can freeze it.

    The collision this allocator exists to prevent only happens inside one second, so a test
    that cannot hold the clock still is not testing the invariant -- it is testing whether two
    statements happened to land in the same second, which on a loaded run they do not.
    """
    return datetime.now(timezone.utc)


class RunJournalExhaustedError(Exception):
    """Every journal name for this second is taken, so this run has no name of its own."""


class WorkspaceRepository(IResearchWorkspaceStore):
    """Canonical workspace storage, delegating to the configured shared database."""

    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._repo = repository if repository is not None else create_repository()

    @property
    def repository(self) -> ITrendRepository:
        """The underlying evidence repository, for callers that also need mission evidence."""
        return self._repo

    # ------------------------------------------------------------------
    # Canonical records (configured shared database)
    # ------------------------------------------------------------------

    async def save_research_workspace(self, workspace: ResearchWorkspace) -> ResearchWorkspace:
        return await self._repo.save_research_workspace(workspace)

    async def get_research_workspace(self, workspace_id: UUID) -> Optional[ResearchWorkspace]:
        return await self._repo.get_research_workspace(workspace_id)

    async def find_research_workspace_by_slug(
        self, slug: str, root_path: Optional[Path] = None
    ) -> Optional[ResearchWorkspace]:
        return await self._repo.find_research_workspace_by_slug(slug, root_path)

    async def list_research_workspaces(self, limit: int = 50) -> List[ResearchWorkspace]:
        return await self._repo.list_research_workspaces(limit)

    async def save_brief_revision(self, revision: MarketBriefRevision) -> MarketBriefRevision:
        return await self._repo.save_brief_revision(revision)

    async def create_market_mission_with_brief(
        self, mission: ResearchMission, revision: MarketBriefRevision
    ) -> Tuple[ResearchMission, MarketBriefRevision]:
        return await self._repo.create_market_mission_with_brief(mission, revision)

    async def get_brief_revision(
        self, workspace_id: UUID, brief_revision_id: UUID
    ) -> Optional[MarketBriefRevision]:
        return await self._repo.get_brief_revision(workspace_id, brief_revision_id)

    async def get_brief_revision_for_mission(
        self, mission_id: UUID
    ) -> Optional[MarketBriefRevision]:
        return await self._repo.get_brief_revision_for_mission(mission_id)

    async def next_brief_revision_number(self, workspace_id: UUID) -> int:
        return await self._repo.next_brief_revision_number(workspace_id)

    async def list_workspace_missions(
        self, workspace_id: UUID, limit: int = 50
    ) -> List[ResearchMission]:
        return await self._repo.list_workspace_missions(workspace_id, limit)

    async def get_scoped_mission(
        self, workspace_id: UUID, mission_id: Any
    ) -> Optional[ResearchMission]:
        """Read a mission through the research that is supposed to own it.

        A mission belonging to another workspace raises rather than coming back as None. None
        would read as "this research has no such mission", which is a different and much quieter
        untruth than "you are looking at the wrong research".
        """
        mission = await self._repo.get_mission(mission_id)
        if mission is None:
            return None
        if mission.workspace_id != workspace_id:
            raise WorkspaceScopeMismatchError(
                f"Mission {mission.id} belongs to workspace {mission.workspace_id}, "
                f"not to {workspace_id}."
            )
        return mission

    # ------------------------------------------------------------------
    # Single writer per mission
    # ------------------------------------------------------------------

    async def claim_mission_writer(self, mission_id: UUID, run_id: UUID) -> bool:
        return await self._repo.claim_mission_writer(mission_id, run_id)

    async def release_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        await self._repo.release_mission_writer(mission_id, run_id)

    async def require_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        """Take the writer slot, or say plainly that another run holds it.

        Failing loudly is the contract: a second writer that silently proceeded would interleave
        two runs' state updates on one mission and leave neither recoverable.
        """
        if not await self.claim_mission_writer(mission_id, run_id):
            raise MissionWriterConflictError(
                f"Mission {mission_id} already has an active writer. Wait for that run to "
                "finish, or start a new revision instead of writing into this one."
            )

    # ------------------------------------------------------------------
    # Filesystem: manifest and run journals
    # ------------------------------------------------------------------

    @staticmethod
    def read_manifest(root_path: Path) -> Optional[ResearchWorkspace]:
        """Read the manifest in a folder, or None when there is none.

        A manifest that exists but cannot be parsed raises: an unreadable manifest is not the
        same fact as an absent one, and treating it as absent is how a research gets a second
        identity written on top of its first.
        """
        import json

        manifest_path = Path(root_path) / MANIFEST_FILENAME
        if not manifest_path.is_file():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise InvalidWorkspaceManifestError(
                f"{manifest_path} exists but is not readable as a workspace manifest."
            ) from exc
        if not isinstance(payload, dict):
            raise InvalidWorkspaceManifestError(
                f"{manifest_path} exists but is not readable as a workspace manifest."
            )
        return ResearchWorkspace.from_manifest(payload, Path(root_path))

    @staticmethod
    def write_manifest(workspace: ResearchWorkspace) -> Path:
        """Write the manifest exclusively, never over one that is already there.

        The exclusive create is what makes "reuse an existing research" and "create a new one"
        different operations rather than the same one with a different outcome. A check followed
        by a write would close over a window in which another host wrote first.
        """
        workspace.root_path.mkdir(parents=True, exist_ok=True)
        with open(workspace.manifest_path, "x", encoding="utf-8") as opened:
            opened.write(workspace.manifest_json())
        return workspace.manifest_path

    async def allocate_run_journal(
        self,
        workspace: ResearchWorkspace,
        mission_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> RunJournal:
        """A journal path no other run holds, taken rather than assumed to be free.

        The same allocation the cutover journal uses, and for the same reason: two runs starting
        in the same second used to build the same second-precision name, and the second one
        overwrote the first one's evidence. The timestamp names the run, the fixed-width sequence
        makes the name unique, and the exclusive create is what proves it.
        """
        run_id = run_id or uuid4()
        started_at = _utc_now()
        journal_dir = workspace.root_path / JOURNAL_DIRNAME
        journal_dir.mkdir(parents=True, exist_ok=True)
        stamp = started_at.strftime("%Y%m%d-%H%M%S")

        for sequence in range(1, JOURNAL_SEQUENCE_LIMIT):
            candidate = journal_dir / f"{JOURNAL_PREFIX}{stamp}-{sequence:03d}.json"
            try:
                # Written through the handle that created it, so there is no moment at which the
                # journal exists and holds nothing a recovery could read.
                with open(candidate, "x", encoding="utf-8") as opened:
                    opened.write(
                        '{\n  "run_id": "%s",\n  "mission_id": "%s",\n'
                        '  "workspace_id": "%s",\n  "started_at": "%s",\n'
                        '  "status": "STARTED"\n}\n'
                        % (run_id, mission_id, workspace.workspace_id, started_at.isoformat())
                    )
            except FileExistsError:
                continue

            journal = RunJournal(
                run_id=run_id,
                mission_id=mission_id,
                workspace_id=workspace.workspace_id,
                journal_path=candidate,
                sequence=sequence,
                status="STARTED",
                started_at=started_at,
            )
            return await self.record_run_journal(journal)

        raise RunJournalExhaustedError(
            f"{journal_dir} already holds {JOURNAL_SEQUENCE_LIMIT - 1} journals stamped {stamp}, "
            "so this run has no name of its own to write into. Nothing was overwritten."
        )

    async def record_run_journal(self, journal: RunJournal) -> RunJournal:
        return await self._repo.record_run_journal(journal)
