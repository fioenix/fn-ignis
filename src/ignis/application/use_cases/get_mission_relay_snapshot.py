"""Project a selected coherent read without credentials, collectors or write access.

The public boundary serializes only typed allowlists. It never derives a corpus
frame from a bounded page or grants permission from unprojected ledger history.
"""

import json
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from urllib.parse import parse_qsl, unquote, urlsplit
from uuid import UUID

from ignis.application.ports.mission_relay_port import (
    IMissionRelayReader, MissionRelayRead, MissionRelayReadRequest,
)
from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot, RunJournal
from ignis.domain.mission_relay import (
    MissionRelayCursor, MissionRelayInspection,
    MissionRelayReadFailure, MissionRelaySnapshot, RelayChannelOutcome, RelayCollectionState,
    RelayFramePendingReason, RelayObservation, RelayReadReason, RelayReadStatus,
)
from ignis.domain.research_workspace import EvidenceRole, ResearchSurface
from ignis.infrastructure.security.pii_sanitizer import SENSITIVE_FIELD_NAMES, sanitize_pii_text


_MAX_RESPONSE_BYTES = 1_048_576
RelayResult = MissionRelaySnapshot | MissionRelayInspection | MissionRelayReadFailure


def _failure(reason: RelayReadReason, *, unavailable: bool = False) -> MissionRelayReadFailure:
    return MissionRelayReadFailure(
        status=RelayReadStatus.UNAVAILABLE if unavailable else RelayReadStatus.REFUSED,
        reason_code=reason,
    )


def _safe_text(value: str | None) -> str | None:
    if value is not None and type(value) is not str:
        raise ValueError("Public text must be a string or unknown.")
    return sanitize_pii_text(value) if value is not None else None


def _safe_url(value: str | None) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError("Source URL must be a string or unknown.")
    try:
        parsed = urlsplit(value)
        decoded = unquote(value)
        if (
            parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or any(ord(char) <= 32 or ord(char) == 127 or char == "\\" for char in value)
            or _safe_text(decoded) != decoded
            or any(key.replace("-", "_").casefold() in SENSITIVE_FIELD_NAMES for key, _ in parse_qsl(parsed.query))
        ):
            return None
        parsed.port  # Reject malformed ports before publishing navigation.
        return value
    except ValueError:
        return None


def _scope_matches(evidence, run, mission_id, run_id, *, complete: bool) -> bool:
    mission = evidence.mission
    if type(mission_id) is not UUID or mission is None or mission.id != mission_id:
        return False
    if run_id is None:
        if run is not None or evidence.outcomes:
            return False
    elif type(run_id) is not UUID or run is None or (
        run.run_id != run_id or run.mission_id != mission_id or run.workspace_id != mission.workspace_id
    ):
        return False
    if evidence.manifest is not None and evidence.manifest.mission_id != mission_id:
        return False
    if evidence.brief is not None and (
        evidence.brief.mission_id != mission_id or evidence.brief.workspace_id != mission.workspace_id
        or evidence.brief.brief_revision_id != mission.brief_revision_id
    ):
        return False
    ids = set()
    for signal in evidence.signals:
        if (
            signal.mission_id != mission_id or type(signal.observation_id) is not UUID
            or type(signal.source_id) is not UUID or signal.observation_id in ids
        ):
            return False
        ids.add(signal.observation_id)
    # Readers can retain canonical qualifications outside this bounded page.
    # Complete direct inputs must not smuggle a foreign observation judgment.
    for qualification in evidence.qualifications:
        if qualification.mission_id != mission_id or complete and qualification.observation_id not in ids:
            return False
    if any(outcome.run_id != run_id for outcome in evidence.outcomes):
        return False
    if any(claim.mission_id != mission_id for claim in evidence.claims):
        return False
    return True


def _observation(signal, evidence, surface) -> RelayObservation:
    if not isinstance(signal.metadata, Mapping):
        raise ValueError("Recorded observation metadata must be a mapping.")
    qualification = next((q for q in evidence.qualifications if q.observation_id == signal.observation_id), None)
    return RelayObservation(
        mission_id=signal.mission_id, observation_id=signal.observation_id, source_id=signal.source_id,
        title=_safe_text(signal.raw_title), excerpt=_safe_text(signal.metadata.get("excerpt")),
        source_url=_safe_url(signal.source_url), metric_value=signal.metric_value,
        growth_velocity=signal.growth_velocity, published_at=signal.published_at, captured_at=signal.captured_at,
        evidence_role=EvidenceRole.ATTENTION_CONTEXT if surface is ResearchSurface.ATTENTION else EvidenceRole.MARKET_EVIDENCE,
        direction=qualification.evidence_role if qualification is not None else None,
        qualification_relation=qualification.relation if qualification is not None else None,
        qualification_frame_fingerprint=qualification.frame_fingerprint if qualification is not None else None,
    )


def _channels(evidence) -> tuple[RelayChannelOutcome, ...]:
    channels = [RelayChannelOutcome(
        platform=_safe_text(outcome.platform), connector_surface=_safe_text(outcome.connector_surface),
        status=outcome.status, signals_collected=outcome.signals_collected,
        completed_at=outcome.completed_at, note=_safe_text(outcome.note),
    ) for outcome in evidence.outcomes]
    recorded = {outcome.platform for outcome in evidence.outcomes}
    if evidence.manifest is not None:
        for platform in dict.fromkeys((*evidence.manifest.required_channels, *evidence.manifest.optional_channels)):
            if platform not in recorded:
                channels.append(RelayChannelOutcome(
                    platform=_safe_text(platform), connector_surface=None, status=None,
                    signals_collected=None, completed_at=None, note=None,
                ))
    return tuple(channels)


def _bounded(result: RelayResult) -> RelayResult:
    serialized = json.dumps(result.to_payload(), ensure_ascii=False, allow_nan=False)
    if len(serialized.encode("utf-8")) > _MAX_RESPONSE_BYTES:
        return _failure(RelayReadReason.RESPONSE_TOO_LARGE)
    return result


def _project(
    *, selected_mission_id: UUID, selected_run_id: UUID | None,
    evidence: MissionEvidenceSnapshot | None, run: RunJournal | None,
    revision: int, read_at: datetime, page_size: int,
    observation_id: UUID | None = None, inspection: bool = False,
    evidence_offset: int = 0, coherent_read: MissionRelayRead | None = None,
    high_water: MissionRelayCursor | None = None,
) -> RelayResult:
    if type(page_size) is not int or not 1 <= page_size <= 200:
        return _failure(RelayReadReason.INVALID_PAGE_SIZE)
    if evidence is None or evidence.mission is None:
        return _failure(RelayReadReason.READ_UNAVAILABLE, unavailable=True)
    if type(evidence_offset) is not int or evidence_offset < 0:
        return _failure(RelayReadReason.SCOPE_MISMATCH)
    complete = coherent_read is None or coherent_read.total_observations == len(evidence.signals)
    if not _scope_matches(evidence, run, selected_mission_id, selected_run_id, complete=complete):
        return _failure(RelayReadReason.SCOPE_MISMATCH)
    try:
        surface = ResearchSurface(evidence.mission.surface)
        if coherent_read is not None:
            if (
                coherent_read.request.mission_id != selected_mission_id
                or coherent_read.request.run_id != selected_run_id
                or coherent_read.evidence is not evidence or coherent_read.run is not run
                or coherent_read.read_at != read_at or coherent_read.high_water.revision != revision
                or coherent_read.request.page_size != page_size or coherent_read.request.evidence_offset != evidence_offset
            ):
                return _failure(RelayReadReason.SCOPE_MISMATCH)
            high_water = coherent_read.high_water
            rows = evidence.signals
            total = coherent_read.total_observations
            source_count = coherent_read.source_count
            events = replace(coherent_read.events, events=tuple(
                replace(event, reason=_safe_text(event.reason), causation_key=_safe_text(event.causation_key))
                for event in coherent_read.events.events
            ))
        else:
            if high_water is None:
                return _failure(RelayReadReason.READ_UNAVAILABLE, unavailable=True)
            if type(high_water) is not MissionRelayCursor or high_water.mission_id != selected_mission_id or high_water.revision != revision:
                return _failure(RelayReadReason.SCOPE_MISMATCH)
            total = len(evidence.signals)
            source_count = len({signal.source_id for signal in evidence.signals})
            rows = evidence.signals[evidence_offset:evidence_offset + page_size]
            events = None
        if inspection:
            signal = next((row for row in rows if row.observation_id == observation_id), None)
            if type(observation_id) is not UUID or signal is None:
                return _failure(RelayReadReason.SCOPE_MISMATCH)
            return _bounded(MissionRelayInspection(
                mission_id=selected_mission_id, run_id=selected_run_id, high_water=high_water,
                read_at=read_at, observation=_observation(signal, evidence, surface),
            ))
        try:
            collection_state = RelayCollectionState(run.status if run is not None else evidence.mission.status)
        except (ValueError, TypeError):
            collection_state = None
        return _bounded(MissionRelaySnapshot(
            mission_id=selected_mission_id, run_id=selected_run_id, high_water=high_water,
            read_at=read_at, page_size=page_size,
            evidence=tuple(_observation(row, evidence, surface) for row in rows),
            total_observations=total, source_count=source_count, surface=surface,
            evidence_offset=evidence_offset,
            manifest_digest=evidence.manifest.manifest_digest if evidence.manifest is not None else None,
            brief_revision_id=evidence.brief.brief_revision_id if evidence.brief is not None else None,
            frame_pending_reason=RelayFramePendingReason.PENDING if run is not None and run.status != "COMPLETED" else RelayFramePendingReason.UNKNOWN,
            event_page=events, channels=_channels(evidence), collection_state=collection_state,
        ))
    except (ValueError, TypeError, OverflowError, UnicodeError):
        return _failure(RelayReadReason.READ_UNAVAILABLE, unavailable=True)


def project_mission_relay_snapshot(
    *, selected_mission_id: UUID, selected_run_id: UUID | None,
    evidence: MissionEvidenceSnapshot | None, run: RunJournal | None,
    revision: int, read_at: datetime, page_size: int,
    evidence_offset: int = 0, high_water: MissionRelayCursor | None = None,
) -> MissionRelaySnapshot | MissionRelayReadFailure:
    """Consume canonical typed records; direct input is an entire corpus."""
    return _project(
        selected_mission_id=selected_mission_id, selected_run_id=selected_run_id,
        evidence=evidence, run=run, revision=revision, read_at=read_at,
        page_size=page_size, evidence_offset=evidence_offset, high_water=high_water,
    )


def project_mission_relay_inspection(
    *, selected_mission_id: UUID, selected_run_id: UUID | None,
    evidence: MissionEvidenceSnapshot | None, run: RunJournal | None,
    revision: int, read_at: datetime, page_size: int, observation_id: UUID,
    evidence_offset: int = 0, high_water: MissionRelayCursor | None = None,
) -> MissionRelayInspection | MissionRelayReadFailure:
    """Inspect only an observation on the explicitly selected membership page."""
    return _project(
        selected_mission_id=selected_mission_id, selected_run_id=selected_run_id,
        evidence=evidence, run=run, revision=revision, read_at=read_at,
        page_size=page_size, evidence_offset=evidence_offset, high_water=high_water,
        observation_id=observation_id, inspection=True,
    )


class GetMissionRelaySnapshotUseCase:
    """Own one coherent reader call; never perform a second evidence lookup."""

    def __init__(self, reader: IMissionRelayReader):
        self._reader = reader

    async def _read(self, request: MissionRelayReadRequest, observation_id: UUID | None = None, *, inspection: bool = False) -> RelayResult:
        read = await self._reader.load_snapshot(request)
        if type(read) is MissionRelayReadFailure:
            return read
        if type(read) is not MissionRelayRead:
            return _failure(RelayReadReason.READ_UNAVAILABLE, unavailable=True)
        return _project(
            selected_mission_id=request.mission_id, selected_run_id=request.run_id,
            evidence=read.evidence, run=read.run, revision=read.high_water.revision,
            read_at=read.read_at, page_size=request.page_size, evidence_offset=request.evidence_offset,
            coherent_read=read, observation_id=observation_id, inspection=inspection,
        )

    async def execute(self, request: MissionRelayReadRequest) -> MissionRelaySnapshot | MissionRelayReadFailure:
        return await self._read(request)

    async def inspect(self, request: MissionRelayReadRequest, observation_id: UUID) -> MissionRelayInspection | MissionRelayReadFailure:
        return await self._read(request, observation_id, inspection=True)
