"""Narrow fact/event commits and coherent internal reads for the mission relay.

These application records are not outward payloads or a second evidence store.
Projection owns sanitization; adapters own authorization and transaction isolation.
"""

import hashlib
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot, RunJournal
from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    MissionRelayEventPage,
    MissionRelayReadFailure,
    RelayProvenance,
)
from ignis.domain.research_workspace import EvidenceQualification, MissionClaim, MissionProbeOutcome
from ignis.domain.entities import ResearchMission, TrendSignal


def _typed(value: object, expected: type, name: str) -> None:
    if type(value) is not expected:
        raise ValueError(f"{name} has an invalid type.")


def _count(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}.")


def _aware(value: datetime) -> None:
    _typed(value, datetime, "timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")


def _fact_value(value: object, *, freeze: bool = False) -> object:
    """Normalize existing fact fields only; no caller-defined event payload is accepted."""
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("Attestation keys must be strings.")
        mapped = {key: _fact_value(item, freeze=freeze) for key, item in value.items()}
        return MappingProxyType(mapped) if freeze else mapped
    if isinstance(value, (list, tuple)):
        return tuple(_fact_value(item, freeze=freeze) for item in value)
    if isinstance(value, datetime):
        _aware(value)
        instant = value.astimezone(timezone.utc)
        return instant if freeze else instant.isoformat()
    if isinstance(value, UUID):
        return value if freeze else str(value)
    if isinstance(value, Enum):
        return _fact_value(value.value, freeze=freeze)
    if value is None or type(value) in (str, bool, int, float):
        return value
    raise ValueError("Outcome fields must retain their serializable canonical values.")


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeOutcomeCommitCommand:
    """One nonempty surface batch, with immutable canonical fact identity.

    The adapter resolves mission_id from the persisted run journal, never caller
    authority. Empty legacy no-ops stay on the unchanged producer and allocate no
    revision. Manifest completeness is checked inside the committing transaction.
    """

    mission_id: UUID
    run_id: UUID
    outcomes: tuple[MissionProbeOutcome, ...] = field(repr=False)
    payload_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        _typed(self.mission_id, UUID, "mission_id")
        _typed(self.run_id, UUID, "run_id")
        _typed(self.outcomes, tuple, "outcomes")
        if not self.outcomes:
            raise ValueError("A commit command requires a nonempty outcome batch.")
        identities, surfaces, copied = set(), set(), []
        for outcome in self.outcomes:
            _typed(outcome, MissionProbeOutcome, "outcome")
            if outcome.run_id != self.run_id:
                raise ValueError("Every outcome must belong to the command run.")
            if outcome.outcome_id in identities or outcome.connector_surface in surfaces:
                raise ValueError("Outcome identities and run surfaces must be unique.")
            identities.add(outcome.outcome_id)
            surfaces.add(outcome.connector_surface)
            copied.append(
                replace(
                    outcome,
                    completed_at=_fact_value(outcome.completed_at, freeze=True),
                    scope_attestation=_fact_value(
                        outcome.scope_attestation,
                        freeze=True,
                    ),
                )
            )
        copied.sort(key=lambda outcome: outcome.connector_surface)
        payload = [
            {item.name: _fact_value(getattr(outcome, item.name)) for item in fields(MissionProbeOutcome)}
            for outcome in copied
        ]
        try:
            encoded = json.dumps(
                payload, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("Outcome facts must have a deterministic JSON representation.") from exc
        object.__setattr__(self, "outcomes", tuple(copied))
        object.__setattr__(self, "payload_fingerprint", hashlib.sha256(encoded).hexdigest())

    @property
    def command_key(self) -> str:
        surfaces = sorted((outcome.platform, outcome.connector_surface) for outcome in self.outcomes)
        encoded = json.dumps(surfaces, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        scope = hashlib.sha256(encoded).hexdigest()
        return f"probe-outcomes:{self.mission_id}:{self.run_id}:{scope}"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProbeOutcomeCommitReceipt:
    """The original committed result; identical retries return this same receipt."""

    command_key: str
    payload_fingerprint: str
    outcome_count: int
    event: MissionProgressEvent

    def __post_init__(self) -> None:
        _typed(self.event, MissionProgressEvent, "event")
        _typed(self.command_key, str, "command_key")
        prefix = f"probe-outcomes:{self.event.cursor.mission_id}:{self.event.run_id}:"
        if (
            not self.command_key.startswith(prefix)
            or not re.fullmatch(r"[0-9a-f]{64}", self.command_key[len(prefix) :])
            or self.event.causation_key != self.command_key
        ):
            raise ValueError("Receipt must retain the committed command identity.")
        if type(self.payload_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.payload_fingerprint):
            raise ValueError("Receipt requires the committed payload fingerprint.")
        _count(self.outcome_count, "outcome_count", 1)
        if (
            self.event.kind is not MissionProgressKind.PROBE_OUTCOMES_RECORDED
            or self.event.provenance is not RelayProvenance.HARNESS_OBSERVED
        ):
            raise ValueError("Receipt must describe a harness-observed probe-fact commit.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayReadRequest:
    """Explicit selected read scope and bounded pagination, without mutation authority."""

    mission_id: UUID
    run_id: UUID | None
    page_size: int
    after_cursor: MissionRelayCursor | None = None
    evidence_offset: int = 0

    def __post_init__(self) -> None:
        _typed(self.mission_id, UUID, "mission_id")
        if self.run_id is not None:
            _typed(self.run_id, UUID, "run_id")
        _count(self.page_size, "page_size", 1)
        if self.page_size > 200:
            raise ValueError("page_size must not exceed 200.")
        _count(self.evidence_offset, "evidence_offset")
        if self.after_cursor is not None:
            _typed(self.after_cursor, MissionRelayCursor, "after_cursor")
            if self.after_cursor.mission_id != self.mission_id:
                raise ValueError("Read cursor must belong to the selected mission.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayRead:
    """Canonical evidence page, run receipt and events from one read transaction.

    Not safe for direct serialization. Existing evidence records retain raw internal
    fields; T023 must scope-check and project an explicit outward allowlist. A null
    selected run is explicitly unknown, never an invitation to invent a latest run.
    """

    request: MissionRelayReadRequest
    evidence: MissionEvidenceSnapshot = field(repr=False)
    run: RunJournal | None = field(repr=False)
    read_at: datetime
    events: MissionRelayEventPage
    total_observations: int
    source_count: int

    def __post_init__(self) -> None:
        _typed(self.request, MissionRelayReadRequest, "request")
        _typed(self.evidence, MissionEvidenceSnapshot, "evidence")
        _typed(self.events, MissionRelayEventPage, "events")
        _aware(self.read_at)
        if self.evidence.mission is None or self.evidence.mission.id != self.request.mission_id:
            raise ValueError("Read evidence must belong to the selected mission.")
        if self.run is None:
            if self.request.run_id is not None:
                raise ValueError("A selected known run requires its journal receipt.")
        else:
            _typed(self.run, RunJournal, "run")
            if (
                self.run.run_id != self.request.run_id
                or self.run.mission_id != self.request.mission_id
                or self.run.workspace_id != self.evidence.mission.workspace_id
            ):
                raise ValueError("Run receipt must match the selected mission, run and workspace.")
        if (
            self.events.high_water.mission_id != self.request.mission_id
            or self.events.page_size != self.request.page_size
            or not self.events.resync_required
            and self.events.after_cursor != self.request.after_cursor
        ):
            raise ValueError("Event page must retain the coherent selected read scope.")
        _count(self.total_observations, "total_observations")
        _count(self.source_count, "source_count")
        visible = len(self.evidence.signals)
        offset = self.request.evidence_offset
        if visible > self.request.page_size or offset + visible > self.total_observations:
            raise ValueError("Evidence page exceeds its declared bounds.")
        if not visible and offset < self.total_observations:
            raise ValueError("An incomplete evidence page must make forward progress.")
        if not (int(self.total_observations > 0) <= self.source_count <= self.total_observations):
            raise ValueError("Global source count is incompatible with the evidence total.")
        # Apply the accepted attainable-count bound when canonical source IDs are known.
        # Missing legacy IDs remain internal inputs for T023's scope/refusal projection.
        sources = {signal.source_id for signal in self.evidence.signals}
        if all(type(source) is UUID for source in sources):
            unique = len(sources)
            if not (
                max(unique, int(self.total_observations > 0))
                <= self.source_count
                <= unique + self.total_observations - visible
            ):
                raise ValueError("Global source count cannot be attained by this page.")

    @property
    def high_water(self) -> MissionRelayCursor:
        return self.events.high_water

    @property
    def next_evidence_offset(self) -> int | None:
        following = self.request.evidence_offset + len(self.evidence.signals)
        return following if following < self.total_observations else None


class ICollectionRelayWriter(Protocol):
    """Run-bound canonical collection mutations with matching durable events.

    Each operation is one transaction; a collection pass spans several commits.
    Legacy unscoped writes remain outside this boundary and emit no run receipts.
    """

    async def commit_collection_state(self, mission: ResearchMission, run_id: UUID) -> None: ...

    async def commit_collection_observations(
        self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]
    ) -> int: ...

    async def commit_collection_membership(
        self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]
    ) -> int: ...

    async def commit_collection_pruning(
        self, mission_id: UUID, run_id: UUID, retained_observation_ids: Sequence[UUID]
    ) -> int: ...


class IAnalysisRelayWriter(Protocol):
    """Canonical qualification and ledger mutations with matching durable receipts."""

    async def commit_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]
    ) -> int: ...

    async def commit_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]
    ) -> list[MissionClaim]: ...


class IMissionRelayWriter(ABC):
    """Only the first concrete atomic fact/event boundary; no generic transaction API."""

    @abstractmethod
    async def commit_probe_outcomes(
        self,
        command: ProbeOutcomeCommitCommand,
    ) -> ProbeOutcomeCommitReceipt:
        """Commit facts, command result, revision and one event together, or none.

        T010/T011's unchanged record_probe_outcomes(run_id, outcomes) resolves the
        authoritative mission from the run journal, constructs this command and
        returns receipt.outcome_count. Validate complete manifest coverage and
        canonical run/surface uniqueness inside the transaction. Lock/allocate the
        mission revision there, never in a separate sequence or before the write.

        Same command key and payload fingerprint returns the original receipt with
        no write or cursor advance. Any changed fact, including outcome_id, raises
        RepositoryException and preserves original facts/event/result. A new UUID
        is a new immutable fact, not a reconstruction of the original identity.
        Disjoint legacy surface batches have distinct keys; overlapping batches
        still obey canonical uniqueness. Manifested runs require full coverage.
        """


class IMissionRelayReader(ABC):
    """Read only initialized canonical storage; no setup, collectors or credentials."""

    @abstractmethod
    async def load_snapshot(
        self,
        request: MissionRelayReadRequest,
    ) -> MissionRelayRead | MissionRelayReadFailure:
        """Read evidence page, exact totals, selected journal and events coherently.

        Authorize selected scope before access. Pin canonical facts and event
        high-water to one read transaction; no event may exceed it. Missing/old
        schema or failed read returns typed unavailable/refusal, not an empty
        successful read. Unknown/missed cursors return resync without replay.
        Inspection uses this selected membership, never a global observation lookup.
        """
