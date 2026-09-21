"""The boundary between a research workspace and whatever stores it.

The canonical record store is the configured shared Ignis database -- SQLite-local by default,
PostgreSQL when configured. The filesystem holds the manifest that lets a second Agent host find
the research, plus run journals and derived artifacts. This port covers both halves so a use case
never has to know which backend is configured or where the manifest lives.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from ignis.domain.research_workspace import (
    MarketBriefRevision,
    ResearchWorkspace,
    WorkspaceStatus,
)


@dataclass(frozen=True)
class WorkspaceProposal:
    """The read-only answer to "where would this research live?".

    A proposal writes nothing. Everything it reports about the target path is observed, not
    created: `exists`, `manifest_status` and `requires_adoption` describe the filesystem as it is
    at the moment of the proposal.
    """

    host_workspace: Path
    research_name: str
    slug: str
    proposed_path: Path
    exists: bool = False
    has_manifest: bool = False
    is_empty: bool = True
    requires_adoption: bool = False
    requires_confirmation: bool = True
    existing_workspace: Optional[ResearchWorkspace] = None
    manifest_status: Optional[WorkspaceStatus] = None
    notes: List[str] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "operation": "propose_workspace",
            "host_workspace": str(self.host_workspace),
            "research_name": self.research_name,
            "slug": self.slug,
            "proposed_path": str(self.proposed_path),
            "exists": self.exists,
            "has_manifest": self.has_manifest,
            "is_empty": self.is_empty,
            "requires_adoption": self.requires_adoption,
            "requires_confirmation": self.requires_confirmation,
            "manifest_status": self.manifest_status.value if self.manifest_status else None,
            "existing_workspace_id": (
                str(self.existing_workspace.workspace_id) if self.existing_workspace else None
            ),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class MissionWriterClaim:
    """Who is writing a mission right now, and since when.

    Readable rather than inferred. A claim left behind by a process that died is
    indistinguishable from an active run unless someone can look at it, and the age is what
    tells an operator which of the two they are looking at.
    """

    mission_id: UUID
    run_id: UUID
    claimed_at: Any


@dataclass(frozen=True)
class RunJournal:
    """One run's exclusive recovery record.

    `sequence` is allocated after the timestamp and is fixed width, so two runs that start in the
    same second still get distinct names and a sorted listing still ends at the newest one.
    """

    run_id: UUID
    mission_id: UUID
    workspace_id: UUID
    journal_path: Path
    sequence: int
    status: str
    started_at: Any
    completed_at: Any = None


class IResearchWorkspaceStore(ABC):
    """Canonical, workspace-scoped storage for research records.

    Every method that reads or writes a research-owned record takes the owning `workspace_id`.
    An implementation that is handed a record belonging to another workspace raises
    `WorkspaceScopeMismatchError`; it must not return an empty result, which would read as
    "this research has no such record".
    """

    @abstractmethod
    async def save_research_workspace(self, workspace: ResearchWorkspace) -> ResearchWorkspace:
        """Record a confirmed workspace identity. Called only after requester confirmation."""

    @abstractmethod
    async def get_research_workspace(self, workspace_id: UUID) -> Optional[ResearchWorkspace]:
        """Reopen a workspace by identity, from any Agent host on the same database."""

    @abstractmethod
    async def find_research_workspace_by_slug(
        self, slug: str, root_path: Optional[Path] = None
    ) -> Optional[ResearchWorkspace]:
        """Find a workspace by its child-folder name, optionally pinned to one host path."""

    @abstractmethod
    async def list_research_workspaces(self, limit: int = 50) -> List[ResearchWorkspace]:
        """List known research workspaces, newest first."""

    @abstractmethod
    async def save_brief_revision(self, revision: MarketBriefRevision) -> MarketBriefRevision:
        """Persist a requester-confirmed Brief revision. Drafts never reach this method."""

    @abstractmethod
    async def create_market_mission_with_brief(self, mission, revision):
        """Write a Market mission and the Brief that authorizes it, or write neither.

        One operation rather than two calls, because the two rows are one fact: a Market mission
        with no confirmed Brief cannot run -- the execution gate refuses it -- so a half-write
        leaves an unusable mission that nothing would ever clean up. Implementations must put
        both writes inside one transaction on both backends.

        The revision number is allocated here rather than by the caller, inside the same
        transaction: a number read before the write is a number two concurrent confirmations can
        both see. The returned revision carries the number that was actually taken.
        """

    @abstractmethod
    async def get_brief_revision(
        self, workspace_id: UUID, brief_revision_id: UUID
    ) -> Optional[MarketBriefRevision]:
        """Read one confirmed revision inside its owning workspace."""

    @abstractmethod
    async def get_brief_revision_for_mission(
        self, mission_id: UUID
    ) -> Optional[MarketBriefRevision]:
        """Read the confirmed revision that authorized a Market mission, if it has one."""

    @abstractmethod
    async def next_brief_revision_number(self, workspace_id: UUID) -> int:
        """The next monotonic revision number in this research line. Numbers are never reused.

        A read, for reporting what the next revision would be. The number a confirmation
        actually takes is allocated by `create_market_mission_with_brief` inside its own
        transaction.
        """

    @abstractmethod
    async def list_workspace_missions(
        self, workspace_id: UUID, limit: int = 50
    ) -> List[Any]:
        """List the missions this workspace owns, newest first."""

    @abstractmethod
    async def claim_mission_writer(self, mission_id: UUID, run_id: UUID) -> bool:
        """Take the single writer slot for a mission. False when another run already holds it."""

    @abstractmethod
    async def release_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        """Give the writer slot back. A run that never claimed it releases nothing."""

    @abstractmethod
    async def get_mission_writer_claim(self, mission_id: UUID) -> Optional["MissionWriterClaim"]:
        """Who holds the writer slot for this mission, or None when it is free.

        The recovery readback. A claim is only ever released by the run that took it, so a run
        that died holding one blocks the mission until an operator names that run id and
        releases it. Expiring claims on a timer instead would hand the slot to a second writer
        while the first may still be running, which is the failure the slot exists to prevent.
        """

    @abstractmethod
    async def record_run_journal(self, journal: RunJournal) -> RunJournal:
        """Record the run journal identity that the filesystem has already granted exclusively."""

    @abstractmethod
    async def list_run_journals(self, mission_id: UUID, limit: int = 20) -> List[RunJournal]:
        """The runs of one mission, newest first.

        `completed_at` is absent for a run that never finished. That is the difference between
        a run that ended and a run nobody ever heard from again, so it is read back as stored
        rather than filled in at read time.
        """
