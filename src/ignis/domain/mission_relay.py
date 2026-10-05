"""Immutable relay read contracts; projection owns sanitization and authorization.

These records are derived views, never a replacement evidence store. Explicit
serializers keep repository metadata and future unreviewed fields off the wire.
"""

import math
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from ignis.domain.research_workspace import (
    EvidenceDirection,
    EvidenceRole,
    QualificationRelation,
    ResearchSurface,
)


class RelayProvenance(str, Enum):
    HARNESS_OBSERVED = "HARNESS_OBSERVED"
    HOST_REPORTED = "HOST_REPORTED"


class MissionProgressKind(str, Enum):
    COLLECTION_STARTED = "COLLECTION_STARTED"
    COLLECTION_STATE_CHANGED = "COLLECTION_STATE_CHANGED"
    PROBE_OUTCOMES_RECORDED = "PROBE_OUTCOMES_RECORDED"
    OBSERVATIONS_COMMITTED = "OBSERVATIONS_COMMITTED"
    QUALIFICATION_RECORDED = "QUALIFICATION_RECORDED"
    CLAIM_GATE_CHANGED = "CLAIM_GATE_CHANGED"
    WORK_STARTED = "WORK_STARTED"
    WORK_WAITING = "WORK_WAITING"
    HANDOFF_COMMITTED = "HANDOFF_COMMITTED"
    FINDING_REVISED = "FINDING_REVISED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    CANCELLATION_ACKNOWLEDGED = "CANCELLATION_ACKNOWLEDGED"


class RelayReadStatus(str, Enum):
    OK = "OK"
    REFUSED = "REFUSED"
    UNAVAILABLE = "UNAVAILABLE"


class RelayReadReason(str, Enum):
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    INVALID_PAGE_SIZE = "INVALID_PAGE_SIZE"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    READ_UNAVAILABLE = "READ_UNAVAILABLE"


class RelayFramePendingReason(str, Enum):
    UNKNOWN = "UNKNOWN"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"


def _require_type(value: object, expected: type, name: str) -> None:
    # Exact types prevent subclasses from overriding an allowlisted serializer.
    if type(value) is not expected:
        raise ValueError(f"{name} has an invalid type.")


def _integer(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer at least {minimum}.")


def _page_size(value: int) -> None:
    _integer(value, "page_size", 1)
    if value > 200:
        raise ValueError("page_size must not exceed 200.")


def _time(value: datetime | None, name: str, optional: bool = False) -> None:
    if value is None and optional:
        return
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware.")


def _optional_uuid(value: UUID | None, name: str) -> None:
    if value is not None:
        _require_type(value, UUID, name)


def _digest(value: str | None, name: str) -> None:
    if value is not None and (type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value)):
        raise ValueError(f"{name} must be a SHA-256 digest.")


def _text(value: str | None, name: str, optional: bool = False) -> None:
    if value is None and optional:
        return
    _require_type(value, str, name)


def _items(values: tuple, expected: type, name: str) -> None:
    _require_type(values, tuple, name)
    for item in values:
        _require_type(item, expected, name)


def _recorded_roles(
    association: EvidenceRole,
    direction: EvidenceDirection | None,
    relation: QualificationRelation | None,
    fingerprint: str | None,
) -> None:
    _require_type(association, EvidenceRole, "evidence_role")
    if direction is not None:
        _require_type(direction, EvidenceDirection, "direction")
    if relation is not None:
        _require_type(relation, QualificationRelation, "qualification_relation")
    _digest(fingerprint, "qualification_frame_fingerprint")
    if (relation is None) != (fingerprint is None):
        raise ValueError("A recorded qualification requires its question frame fingerprint.")


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayCursor:
    """A committed position in one mission; (0, 0) means no recorded event."""

    mission_id: UUID
    revision: int
    ordinal: int

    def __post_init__(self) -> None:
        _require_type(self.mission_id, UUID, "mission_id")
        _integer(self.revision, "revision")
        _integer(self.ordinal, "ordinal")
        if (self.revision == 0) != (self.ordinal == 0):
            raise ValueError("Only the initial cursor may have a zero position.")

    @property
    def position(self) -> tuple[int, int]:
        return self.revision, self.ordinal

    def to_payload(self) -> dict[str, object]:
        return {"mission_id": str(self.mission_id), "revision": self.revision, "ordinal": self.ordinal}


@dataclass(frozen=True, slots=True, kw_only=True)
class RelayEvidenceReference:
    """Canonical immutable identities and existing roles, without source content."""

    mission_id: UUID
    observation_id: UUID
    source_id: UUID
    evidence_role: EvidenceRole
    direction: EvidenceDirection | None
    qualification_relation: QualificationRelation | None = None
    qualification_frame_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name in ("mission_id", "observation_id", "source_id"):
            _require_type(getattr(self, name), UUID, name)
        _recorded_roles(
            self.evidence_role,
            self.direction,
            self.qualification_relation,
            self.qualification_frame_fingerprint,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "mission_id": str(self.mission_id),
            "observation_id": str(self.observation_id),
            "source_id": str(self.source_id),
            "evidence_role": self.evidence_role.value,
            "direction": self.direction.value if self.direction is not None else None,
            "qualification_relation": self.qualification_relation.value
            if self.qualification_relation is not None
            else None,
            "qualification_frame_fingerprint": self.qualification_frame_fingerprint,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionProgressEvent:
    """A safe committed receipt, not raw event JSON or a claim of observed work."""

    event_id: UUID
    cursor: MissionRelayCursor
    kind: MissionProgressKind
    provenance: RelayProvenance
    recorded_at: datetime
    causation_key: str
    occurred_at: datetime | None = None
    run_id: UUID | None = None
    work_id: UUID | None = None
    handoff_id: UUID | None = None
    finding_id: UUID | None = None
    claim_id: UUID | None = None
    evidence_references: tuple[RelayEvidenceReference, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        _require_type(self.event_id, UUID, "event_id")
        _require_type(self.cursor, MissionRelayCursor, "cursor")
        if self.cursor.revision == 0:
            raise ValueError("A recorded event must have a positive revision and ordinal.")
        _require_type(self.kind, MissionProgressKind, "kind")
        _require_type(self.provenance, RelayProvenance, "provenance")
        _time(self.recorded_at, "recorded_at")
        _time(self.occurred_at, "occurred_at", optional=True)
        _text(self.causation_key, "causation_key")
        if not self.causation_key.strip():
            raise ValueError("causation_key must be nonempty.")
        for name in ("run_id", "work_id", "handoff_id", "finding_id", "claim_id"):
            _optional_uuid(getattr(self, name), name)
        if self.kind is MissionProgressKind.PROBE_OUTCOMES_RECORDED and self.run_id is None:
            raise ValueError("A recorded probe outcome requires its collection run identity.")
        _text(self.reason, "reason", optional=True)
        _items(self.evidence_references, RelayEvidenceReference, "evidence_references")
        if any(ref.mission_id != self.cursor.mission_id for ref in self.evidence_references):
            raise ValueError("Event references must belong to the event mission.")

    def to_payload(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            **self.cursor.to_payload(),
            "kind": self.kind.value,
            "provenance": self.provenance.value,
            "recorded_at": self.recorded_at.isoformat(),
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at is not None else None,
            "causation_key": self.causation_key,
            "run_id": str(self.run_id) if self.run_id is not None else None,
            "work_id": str(self.work_id) if self.work_id is not None else None,
            "handoff_id": str(self.handoff_id) if self.handoff_id is not None else None,
            "finding_id": str(self.finding_id) if self.finding_id is not None else None,
            "claim_id": str(self.claim_id) if self.claim_id is not None else None,
            "evidence_references": [ref.to_payload() for ref in self.evidence_references],
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayEventPage:
    """An ordered bounded page from the same coherent high-water as the read."""

    high_water: MissionRelayCursor
    page_size: int
    events: tuple[MissionProgressEvent, ...]
    after_cursor: MissionRelayCursor | None = None
    next_cursor: MissionRelayCursor | None = None
    has_more: bool = False
    resync_required: bool = False

    def __post_init__(self) -> None:
        _require_type(self.high_water, MissionRelayCursor, "high_water")
        _page_size(self.page_size)
        _items(self.events, MissionProgressEvent, "events")
        _require_type(self.has_more, bool, "has_more")
        _require_type(self.resync_required, bool, "resync_required")
        if len(self.events) > self.page_size:
            raise ValueError("Event page exceeds page_size.")
        for bound in (self.after_cursor, self.next_cursor):
            if bound is not None:
                _require_type(bound, MissionRelayCursor, "page cursor")
                if bound.mission_id != self.high_water.mission_id or bound.position > self.high_water.position:
                    raise ValueError("Page cursor exceeds the mission high-water.")
        previous = self.after_cursor.position if self.after_cursor is not None else (0, 0)
        identities: set[UUID] = set()
        for event in self.events:
            if event.cursor.mission_id != self.high_water.mission_id:
                raise ValueError("Event page contains a foreign mission.")
            if not previous < event.cursor.position <= self.high_water.position:
                raise ValueError("Event positions must be ordered within the high-water.")
            if event.event_id in identities:
                raise ValueError("Event page contains a duplicate event identity.")
            identities.add(event.event_id)
            previous = event.cursor.position
        if self.resync_required:
            if self.events or self.has_more or self.next_cursor is not None or self.after_cursor is not None:
                raise ValueError("A resync response cannot replay events or promise a continuation.")
        elif self.has_more:
            if not self.events or self.next_cursor != self.events[-1].cursor or previous >= self.high_water.position:
                raise ValueError("An incomplete page requires its last event as continuation.")
        elif self.next_cursor is not None or previous != self.high_water.position:
            raise ValueError("A complete page must reach its high-water without a continuation.")

    def to_payload(self) -> dict[str, object]:
        return {
            "high_water": self.high_water.to_payload(),
            "page_size": self.page_size,
            "after_cursor": self.after_cursor.to_payload() if self.after_cursor is not None else None,
            "next_cursor": self.next_cursor.to_payload() if self.next_cursor is not None else None,
            "events": [event.to_payload() for event in self.events],
            "has_more": self.has_more,
            "resync_required": self.resync_required,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class RelayObservation:
    """Allowlisted observation facts; text and navigation are sanitized by projection."""

    mission_id: UUID
    observation_id: UUID
    source_id: UUID
    title: str
    excerpt: str | None
    source_url: str | None
    metric_value: int | float | None
    growth_velocity: int | float | None
    published_at: datetime | None
    captured_at: datetime | None
    evidence_role: EvidenceRole
    direction: EvidenceDirection | None
    qualification_relation: QualificationRelation | None = None
    qualification_frame_fingerprint: str | None = None

    def __post_init__(self) -> None:
        for name in ("mission_id", "observation_id", "source_id"):
            _require_type(getattr(self, name), UUID, name)
        _recorded_roles(
            self.evidence_role,
            self.direction,
            self.qualification_relation,
            self.qualification_frame_fingerprint,
        )
        _text(self.title, "title")
        _text(self.excerpt, "excerpt", optional=True)
        _text(self.source_url, "source_url", optional=True)
        for name in ("metric_value", "growth_velocity"):
            value = getattr(self, name)
            if value is not None:
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError(f"{name} must be finite or unknown.")
        _time(self.published_at, "published_at", optional=True)
        _time(self.captured_at, "captured_at", optional=True)

    def to_payload(self) -> dict[str, object]:
        return {
            "mission_id": str(self.mission_id),
            "observation_id": str(self.observation_id),
            "source_id": str(self.source_id),
            "title": self.title,
            "excerpt": self.excerpt,
            "source_url": self.source_url,
            "metric_value": self.metric_value,
            "growth_velocity": self.growth_velocity,
            "published_at": self.published_at.isoformat() if self.published_at is not None else None,
            "captured_at": self.captured_at.isoformat() if self.captured_at is not None else None,
            "evidence_role": self.evidence_role.value,
            "direction": self.direction.value if self.direction is not None else None,
            "qualification_relation": self.qualification_relation.value
            if self.qualification_relation is not None
            else None,
            "qualification_frame_fingerprint": self.qualification_frame_fingerprint,
        }


def _read_identity(mission_id: UUID, run_id: UUID | None, high_water: MissionRelayCursor, read_at: datetime) -> None:
    _require_type(mission_id, UUID, "mission_id")
    _optional_uuid(run_id, "run_id")
    _require_type(high_water, MissionRelayCursor, "high_water")
    if high_water.mission_id != mission_id:
        raise ValueError("Read high-water belongs to a different mission.")
    _time(read_at, "read_at")


def _receipt(
    mission_id: UUID, run_id: UUID | None, high_water: MissionRelayCursor, read_at: datetime
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": RelayReadStatus.OK.value,
        "mission_id": str(mission_id),
        "run_id": str(run_id) if run_id is not None else None,
        "revision": high_water.revision,
        "read_at": read_at.isoformat(),
        "high_water": high_water.to_payload(),
    }


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelaySnapshot:
    """One bounded safe evidence read; it grants no strategic claim permission."""

    mission_id: UUID
    run_id: UUID | None
    high_water: MissionRelayCursor
    read_at: datetime
    page_size: int
    evidence: tuple[RelayObservation, ...]
    total_observations: int
    source_count: int
    surface: ResearchSurface
    evidence_offset: int = 0
    manifest_digest: str | None = None
    brief_revision_id: UUID | None = None
    frame_digest: str | None = None
    frame_pending_reason: RelayFramePendingReason | None = RelayFramePendingReason.UNKNOWN
    event_page: MissionRelayEventPage | None = None

    def __post_init__(self) -> None:
        _read_identity(self.mission_id, self.run_id, self.high_water, self.read_at)
        _page_size(self.page_size)
        _items(self.evidence, RelayObservation, "evidence")
        _require_type(self.surface, ResearchSurface, "surface")
        for name in ("total_observations", "source_count", "evidence_offset"):
            _integer(getattr(self, name), name)
        if len(self.evidence) > self.page_size or self.evidence_offset + len(self.evidence) > self.total_observations:
            raise ValueError("Observation page exceeds its bounds or total.")
        if not self.evidence and self.evidence_offset < self.total_observations:
            raise ValueError("An incomplete observation page cannot be represented as empty.")
        if any(row.mission_id != self.mission_id for row in self.evidence):
            raise ValueError("Observation page contains a foreign mission.")
        if len({row.observation_id for row in self.evidence}) != len(self.evidence):
            raise ValueError("Observation page contains duplicate immutable identities.")
        visible_sources = len({row.source_id for row in self.evidence})
        minimum_sources = max(visible_sources, 1 if self.total_observations > 0 else 0)
        # Each observation outside this page can introduce at most one new source.
        maximum_sources = visible_sources + self.total_observations - len(self.evidence)
        if not minimum_sources <= self.source_count <= maximum_sources:
            raise ValueError("Source count is inconsistent with observation counts.")
        _digest(self.manifest_digest, "manifest_digest")
        _digest(self.frame_digest, "frame_digest")
        _optional_uuid(self.brief_revision_id, "brief_revision_id")
        if self.frame_digest is None:
            _require_type(self.frame_pending_reason, RelayFramePendingReason, "frame_pending_reason")
        elif self.frame_pending_reason is not None:
            raise ValueError("A bound frame cannot also be labeled pending or unknown.")
        if self.event_page is not None:
            _require_type(self.event_page, MissionRelayEventPage, "event_page")
            if self.event_page.high_water != self.high_water:
                raise ValueError("Event page must share the snapshot high-water.")

    def to_payload(self) -> dict[str, object]:
        end = self.evidence_offset + len(self.evidence)
        return {
            **_receipt(self.mission_id, self.run_id, self.high_water, self.read_at),
            "manifest_digest": self.manifest_digest,
            "brief_revision_id": str(self.brief_revision_id) if self.brief_revision_id is not None else None,
            "surface": self.surface.value,
            "frame_digest": self.frame_digest,
            "frame_pending_reason": self.frame_pending_reason.value if self.frame_pending_reason is not None else None,
            "counts": {"observations": self.total_observations, "sources": self.source_count},
            "page_size": self.page_size,
            "evidence_offset": self.evidence_offset,
            "next_evidence_offset": end if end < self.total_observations else None,
            "evidence": [row.to_payload() for row in self.evidence],
            "event_page": self.event_page.to_payload() if self.event_page is not None else None,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayInspection:
    mission_id: UUID
    run_id: UUID | None
    high_water: MissionRelayCursor
    read_at: datetime
    observation: RelayObservation

    def __post_init__(self) -> None:
        _read_identity(self.mission_id, self.run_id, self.high_water, self.read_at)
        _require_type(self.observation, RelayObservation, "observation")
        if self.observation.mission_id != self.mission_id:
            raise ValueError("Inspected observation belongs to a different mission.")

    def to_payload(self) -> dict[str, object]:
        return {
            **_receipt(self.mission_id, self.run_id, self.high_water, self.read_at),
            "observation": self.observation.to_payload(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class MissionRelayReadFailure:
    """A bounded failure receipt never carries raw records or successful empty counts."""

    status: RelayReadStatus
    reason_code: RelayReadReason

    def __post_init__(self) -> None:
        _require_type(self.status, RelayReadStatus, "status")
        _require_type(self.reason_code, RelayReadReason, "reason_code")
        if self.status is RelayReadStatus.OK:
            raise ValueError("A read failure cannot carry successful status.")

    def to_payload(self) -> dict[str, object]:
        return {"schema_version": 1, "status": self.status.value, "reason_code": self.reason_code.value}
