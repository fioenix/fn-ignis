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

import dataclasses
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from ignis.application.ports.repository_port import ITrendRepository
from ignis.application.ports.research_workspace_port import (
    IResearchWorkspaceStore,
    MissionWriterClaim,
    RunJournal,
)
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import (
    JOURNAL_DIRNAME,
    MANIFEST_FILENAME,
    EvidenceQualification,
    InvalidWorkspaceManifestError,
    MarketBriefRevision,
    MissionClaim,
    MissionManifest,
    MissionProbeOutcome,
    MissionTerminalStateError,
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


def _journal_payload(
    journal: RunJournal, collection_plan: Optional[Dict[str, Any]] = None
) -> str:
    """What one run writes about itself, in one place so start and finish agree.

    `completed_at` is omitted rather than nulled while the run is open, and the status is the
    run's own: a reader finding STARTED with no completion is looking at a run that never
    reported back, which is a different fact from one that failed.
    """
    payload: Dict[str, Any] = {
        "run_id": str(journal.run_id),
        "mission_id": str(journal.mission_id),
        "workspace_id": str(journal.workspace_id),
        "sequence": journal.sequence,
        "status": journal.status,
        "started_at": journal.started_at.isoformat() if journal.started_at else None,
    }
    if journal.completed_at is not None:
        payload["completed_at"] = journal.completed_at.isoformat()
    if collection_plan is not None:
        payload["collection_plan"] = collection_plan
        payload["collection_plan_digest"] = collection_plan.get("plan_digest")
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


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

    async def create_attention_mission_with_manifest(
        self, mission: ResearchMission, manifest: MissionManifest
    ) -> Tuple[ResearchMission, MissionManifest]:
        return await self._repo.create_attention_mission_with_manifest(mission, manifest)

    async def create_market_mission_with_brief_and_manifest(
        self,
        mission: ResearchMission,
        revision: MarketBriefRevision,
        manifest: MissionManifest,
    ) -> Tuple[ResearchMission, MarketBriefRevision, MissionManifest]:
        return await self._repo.create_market_mission_with_brief_and_manifest(
            mission, revision, manifest
        )

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

    async def save_mission_manifest(self, manifest: MissionManifest) -> MissionManifest:
        return await self._repo.save_mission_manifest(manifest)

    async def get_mission_manifest(self, mission_id: UUID) -> Optional[MissionManifest]:
        return await self._repo.get_mission_manifest(mission_id)

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

    async def get_mission_writer_claim(self, mission_id: UUID) -> Optional[MissionWriterClaim]:
        return await self._repo.get_mission_writer_claim(mission_id)

    async def require_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        """Take the writer slot, or say plainly that another run holds it.

        Failing loudly is the contract: a second writer that silently proceeded would interleave
        two runs' state updates on one mission and leave neither recoverable.
        """
        if not await self.claim_mission_writer(mission_id, run_id):
            held = await self.get_mission_writer_claim(mission_id)
            holder = f" Run {held.run_id} has held it since {held.claimed_at}." if held else ""
            raise MissionWriterConflictError(
                f"Mission {mission_id} already has an active writer.{holder} Wait for that run "
                "to finish, or start a new revision instead of writing into this one."
            )

    @asynccontextmanager
    async def mission_run(
        self,
        workspace: ResearchWorkspace,
        mission_id: UUID,
        run_id: Optional[UUID] = None,
    ) -> AsyncIterator[RunJournal]:
        """Take the mission for one run: claim the writer, take a journal, give both back.

        The order is the contract. The claim comes first, so a second run is refused before it
        takes a journal name and starts looking like a run that happened. The journal comes
        before the body, so anything the run writes is already recoverable. Both are given back
        in a `finally`, so a run that fails -- or fails while failing -- does not leave the
        mission locked behind a writer nobody is.

        The claim is per mission. Two missions of one research take two different rows and
        never wait for each other.
        """
        run_id = run_id or uuid4()
        await self.require_mission_writer(mission_id, run_id)
        try:
            # Preflight may have awaited while an earlier run completed. Recheck under the
            # writer slot, before allocating a journal, so delayed admission cannot restart it.
            mission = await self._repo.get_mission(mission_id)
            if mission is None:
                raise WorkspaceScopeMismatchError(f"Mission {mission_id} no longer exists.")
            status = str(mission.status).upper()
            if status in {"COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT_EVIDENCE"}:
                raise MissionTerminalStateError(mission_id, status)
            journal = await self.allocate_run_journal(workspace, mission_id, run_id=run_id)
        except BaseException:
            # No journal, so there is no run to record -- and holding the slot for a run that
            # never started is exactly the stale claim the release exists to prevent.
            await self.release_mission_writer(mission_id, run_id)
            raise

        try:
            yield journal
        except BaseException:
            await self._finish_run_journal(journal, status="FAILED")
            raise
        else:
            await self._finish_run_journal(journal, status="COMPLETED")
        finally:
            await self.release_mission_writer(mission_id, run_id)

    async def _finish_run_journal(self, journal: RunJournal, status: str) -> RunJournal:
        """Close a run's journal on disk and in the database, without raising over the run.

        A finalization failure must not replace the error the run is already carrying, and must
        not turn a successful run into a failed one. It is logged and the run keeps its own
        outcome; the journal is then simply a run that never reported back, which is a state
        the readback already describes honestly.
        """
        finished = dataclasses.replace(
            journal, status=status, completed_at=_utc_now()
        )
        try:
            existing = json.loads(journal.journal_path.read_text(encoding="utf-8"))
            journal.journal_path.write_text(
                _journal_payload(finished, collection_plan=existing.get("collection_plan")),
                encoding="utf-8",
            )
            return await self.record_run_journal(finished)
        except Exception:
            logger.exception(
                "Could not finalize run journal %s for mission %s; it stays readable as an "
                "unfinished run.",
                journal.journal_path,
                journal.mission_id,
            )
            return journal

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
            journal = RunJournal(
                run_id=run_id,
                mission_id=mission_id,
                workspace_id=workspace.workspace_id,
                journal_path=candidate,
                sequence=sequence,
                status="STARTED",
                started_at=started_at,
            )
            try:
                # Written through the handle that created it, so there is no moment at which the
                # journal exists and holds nothing a recovery could read.
                with open(candidate, "x", encoding="utf-8") as opened:
                    opened.write(_journal_payload(journal))
            except FileExistsError:
                continue

            return await self.record_run_journal(journal)

        raise RunJournalExhaustedError(
            f"{journal_dir} already holds {JOURNAL_SEQUENCE_LIMIT - 1} journals stamped {stamp}, "
            "so this run has no name of its own to write into. Nothing was overwritten."
        )

    async def record_run_journal(self, journal: RunJournal) -> RunJournal:
        return await self._repo.record_run_journal(journal)

    async def record_collection_plan(
        self, journal: RunJournal, plan: Dict[str, Any]
    ) -> None:
        """Add the readable projection without changing the journal's canonical database row."""
        digest = plan.get("plan_digest") if isinstance(plan, dict) else None
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("A run journal collection plan needs its canonical plan_digest.")
        current = json.loads(journal.journal_path.read_text(encoding="utf-8"))
        current["collection_plan"] = plan
        current["collection_plan_digest"] = digest
        temporary = journal.journal_path.with_suffix(journal.journal_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(journal.journal_path)

    async def list_run_journals(self, mission_id: UUID, limit: int = 20) -> List[RunJournal]:
        return await self._repo.list_run_journals(mission_id, limit)

    async def latest_run_journal(self, mission_id: UUID) -> Optional[RunJournal]:
        """The most recent run of a mission, or None when it has never run."""
        journals = await self.list_run_journals(mission_id, limit=1)
        return journals[0] if journals else None

    # ------------------------------------------------------------------
    # Probe outcomes and evidence qualifications (configured shared database)
    # ------------------------------------------------------------------

    async def record_probe_outcomes(
        self, run_id: UUID, outcomes: Sequence[MissionProbeOutcome]
    ) -> int:
        return await self._repo.record_probe_outcomes(run_id, outcomes)

    async def get_latest_completed_probe_outcomes(
        self, mission_id: UUID
    ) -> List[MissionProbeOutcome]:
        return await self._repo.get_latest_completed_probe_outcomes(mission_id)

    async def list_evidence_qualifications(
        self, mission_id: UUID
    ) -> List[EvidenceQualification]:
        return await self._repo.list_evidence_qualifications(mission_id)

    async def save_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]
    ) -> int:
        return await self._repo.save_evidence_qualifications(mission_id, qualifications)

    async def save_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]
    ) -> List[MissionClaim]:
        return await self._repo.save_mission_claims(mission_id, frame_digest, claims)

    async def list_mission_claims(
        self, mission_id: UUID, *, include_superseded: bool = False
    ) -> List[MissionClaim]:
        return await self._repo.list_mission_claims(
            mission_id, include_superseded=include_superseded
        )

    async def supersede_mission_claims(self, mission_id: UUID, current_frame_digest: str) -> int:
        return await self._repo.supersede_mission_claims(mission_id, current_frame_digest)

    async def load_mission_evidence_snapshot(self, mission_id: UUID):
        return await self._repo.load_mission_evidence_snapshot(mission_id)

    async def inventory_legacy_baseline(self) -> Dict[str, Any]:
        return await self._repo.inventory_legacy_baseline()
