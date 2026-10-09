"""Private checked execution context; records and host identity confer no authority."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID
from typing import Protocol
from contextlib import AbstractAsyncContextManager

from ignis.application.ports.follow_up_admission_port import AsyncFollowUpCapabilityLease
from ignis.application.ports.research_work_port import FollowUpCommitReceipt, ResearchWorkSnapshot
from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot, MissionWriterClaim, RunJournal
from ignis.domain.follow_up_admission import WorkAuthority, digest
from ignis.domain.entities import ResearchMission
from ignis.domain.research_workspace import MarketBriefRevision, MissionManifest
from ignis.domain.mission_follow_up import FollowUpReservation
from ignis.domain.research_work import _text
from ignis.domain.follow_up_admission import resources, _integer


class FollowUpExecutionBoundaryError(Exception):
    """A current authority refusal is never connector health or breaker failure."""

    def __init__(self, reason="SESSION_AUTHORITY_REQUIRED"):
        self.reason = "SESSION_AUTHORITY_REQUIRED"
        super().__init__(self.reason)


@dataclass(frozen=True, slots=True)
class FollowUpExecutionHistory:
    child: ResearchMission | None
    journals: tuple[RunJournal, ...]
    writer: MissionWriterClaim | None

    @classmethod
    def from_rows(cls, child, rows, claim):
        def timestamp(value, *, optional=False):
            if value is None and optional:
                return None
            value = datetime.fromisoformat(value) if isinstance(value, str) else value
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError("Timezone-aware canonical timestamp required.")
            return value
        journals = tuple(RunJournal(UUID(str(r[0])), UUID(str(r[2])), UUID(str(r[1])),
                                    Path(r[3]), int(r[4]), r[5], timestamp(r[6]), timestamp(r[7], optional=True))
                         for r in rows)
        writer = (MissionWriterClaim(UUID(str(claim[0])), UUID(str(claim[1])), timestamp(claim[2]))
                  if claim else None)
        if child is None or any(j.mission_id != child.id for j in journals):
            raise ValueError("Unbound execution history.")
        if writer and writer.mission_id != child.id:
            raise ValueError("Unbound execution writer.")
        return cls(child, journals, writer)


@dataclass(frozen=True, slots=True)
class FollowUpExecutionContext:
    authority: WorkAuthority | None
    canonical: MissionEvidenceSnapshot
    research: ResearchWorkSnapshot
    receipt: FollowUpCommitReceipt | None
    reason_code: str | None
    child: ResearchMission | None
    brief: MarketBriefRevision | None
    manifest: MissionManifest | None
    reservation: FollowUpReservation | None = None
    retry_revision: int | None = None
    retry_reason: str | None = None
    execution_history: FollowUpExecutionHistory | None = None


@dataclass(frozen=True, slots=True)
class FollowUpExecutionPlan:
    queries: tuple[str, ...]
    # Exact plugin ID/platform/tier/revision/path and sampling metadata, not a platform inference.
    connectors: tuple[tuple[str, str, str, str, str, int, str, bool], ...]
    resources: tuple[tuple[str, int], ...]
    geo: str
    timeframe: str

    def __post_init__(self):
        if type(self.queries) is not tuple or not 1 <= len(self.queries) <= 100:
            raise ValueError("Finite exact execution queries required.")
        for query in self.queries:
            _text(query, maximum=512)
        if len(set(self.queries)) != len(self.queries):
            raise ValueError("Duplicate execution query.")
        if type(self.connectors) is not tuple or not 1 <= len(self.connectors) <= 100:
            raise ValueError("Finite exact connector plan required.")
        for row in self.connectors:
            if type(row) is not tuple or len(row) != 8:
                raise ValueError("Invalid exact connector plan row.")
            for value in (*row[:5], row[6]):
                _text(value, maximum=512)
            _integer(row[5], 1)
            if type(row[7]) is not bool:
                raise ValueError("Invalid paid quota binding.")
        if len({row[0] for row in self.connectors}) != len(self.connectors):
            raise ValueError("Duplicate execution source.")
        resources(self.resources)
        _text(self.geo, maximum=128)
        _text(self.timeframe, maximum=128)

    @property
    def digest(self):
        return digest(self)


class FollowUpExecutionVerifier(Protocol):
    def hold_execution(self, authority: WorkAuthority, plan: FollowUpExecutionPlan
                       ) -> AbstractAsyncContextManager[AsyncFollowUpCapabilityLease]:
        """Verify the exact already-confirmed plan/session and current operational generations.

        Never acquire credentials or initialize authentication. Shared async generation tokens
        permit overlapping independent readers; publishers wait for all tokens to settle.
        Missing/incompatible providers refuse. A grant's plan digest binds this exact plan.
        """
        ...
