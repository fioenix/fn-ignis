"""Strict public command bridge to the held atomic research recording boundary."""

from dataclasses import fields
from datetime import datetime
import json
from typing import Any
from uuid import UUID

from ignis.application.ports.research_work_port import (
    IResearchWorkPort,
    ResearchAssignmentAdmission,
    ResearchHandoffAcknowledgement,
    ResearchWorkCommitCommand,
    ResearchWorkCommitReceipt,
    ResearchWorkStartAdmission,
    SAFE_REASONS,
)
from ignis.domain.research_findings import ResearchFindingRevision, ResearchHandoff
from ignis.domain.research_work import (
    AssignWorkPayload,
    EndResearchPayload,
    EndWorkPayload,
    ReasonWorkPayload,
    ResearchActivityReceipt,
    ResearchAssignment,
    ResearchAuthority,
    ResearchInputBindings,
    ResearchWorkItem,
    StartWorkPayload,
    StopWorkPayload,
)


class _InvalidReason(ValueError):
    pass


def _object(value: Any, names: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != names:
        raise ValueError("Invalid recording command.")
    return dict(value)


def _identity(value: Any) -> UUID:
    if type(value) is not str or len(value) != 36:
        raise ValueError("Invalid recording command.")
    identity = UUID(value)
    if str(identity) != value:
        raise ValueError("Invalid recording command.")
    return identity


def _timestamp(value: Any) -> datetime:
    if type(value) is not str or len(value) > 40:
        raise ValueError("Invalid recording command.")
    result = datetime.fromisoformat(value)
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Invalid recording command.")
    return result


def _list(value: Any, maximum: int) -> list[Any]:
    if type(value) is not list or len(value) > maximum:
        raise ValueError("Invalid recording command.")
    return value


def _bindings(value: Any) -> ResearchInputBindings:
    values = _object(value, {f.name for f in fields(ResearchInputBindings)})
    values["mission_id"] = _identity(values["mission_id"])
    values["observation_ids"] = tuple(_identity(v) for v in _list(values["observation_ids"], 1000))
    rows = []
    for item in _list(values["finding_revisions"], 1000):
        row = _object(item, {"finding_id", "revision"})
        rows.append((_identity(row["finding_id"]), row["revision"]))
    values["finding_revisions"] = tuple(rows)
    return ResearchInputBindings(**values)


def _record(cls: type, value: Any):
    """Decode only declared nested protocol fields; recorded metadata is never caller input."""
    values = _object(value, {f.name for f in fields(cls)} - {"recorded_at"})
    for key, item in list(values.items()):
        if key in {"work_id", "assignment_id", "handoff_id", "finding_id", "claim_id"}:
            values[key] = None if key == "claim_id" and item is None else _identity(item)
        elif key in {"occurred_at", "fresh_until"}:
            values[key] = None if key == "occurred_at" and item is None else _timestamp(item)
        elif key == "inputs":
            values[key] = _bindings(item)
        elif key in {
            "dependencies",
            "outcome_ids",
            "claim_ids",
            "supporting_observation_ids",
            "contradicting_observation_ids",
            "context_observation_ids",
        }:
            values[key] = tuple(_identity(v) for v in _list(item, 1000))
        elif key in {"limitations", "open_questions"}:
            values[key] = tuple(_list(item, 100))
        elif key == "observation_sources":
            rows = []
            for raw in _list(item, 1000):
                row = _object(raw, {"observation_id", "source_id"})
                rows.append((_identity(row["observation_id"]), _identity(row["source_id"])))
            values[key] = tuple(rows)
        elif key == "findings":
            values[key] = tuple(_record(ResearchFindingRevision, v) for v in _list(item, 1000))
    return cls(**values)


def _bounded_json(value: Any, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Invalid recording command.")
    if type(value) is dict:
        if len(value) > 32 or any(type(k) is not str for k in value):
            raise ValueError("Invalid recording command.")
        for item in value.values():
            _bounded_json(item, depth + 1)
    elif type(value) is list:
        for item in _list(value, 1000):
            _bounded_json(item, depth + 1)
    elif type(value) is int:
        if not 0 <= value < 2**63:
            raise ValueError("Invalid recording command.")
    elif value is not None and type(value) is not str:
        # bool is not an integer, and no public command field accepts a boolean.
        raise ValueError("Invalid recording command.")
    elif type(value) is str and len(value) > 4096:
        raise ValueError("Invalid recording command.")


def parse_recording_command(mission_id: str, raw: Any, *, host_authorized: bool) -> ResearchWorkCommitCommand:
    """Preserve requested identity and bindings; canonical admission belongs to the store."""
    try:
        mission = _identity(mission_id)
        _bounded_json(raw)
        if len(json.dumps(raw, ensure_ascii=False).encode("utf-8")) > 1048576:
            raise ValueError("Invalid recording command.")
        body = _object(raw, {"operation", "idempotency_key", "expected_revision", "expected_epoch", "payload"})
        operation = body["operation"]
        epoch = body["expected_epoch"]
        if type(operation) is not str:
            raise ValueError("Invalid recording command.")
        if operation == "ASSIGN_RESEARCH":
            values = _object(
                body["payload"],
                {
                    "assignment_id",
                    "expected_manifest_digest",
                    "expected_brief_revision_id",
                    "host_task_ref",
                    "authority",
                    "capability",
                },
            )
            envelope = _object(values["authority"], {f.name for f in fields(ResearchAuthority)})
            for key in ("actions", "sources"):
                items = _list(envelope[key], 100)
                if any(type(v) is not str for v in items) or len(set(items)) != len(items):
                    raise ValueError("Invalid recording command.")
                envelope[key] = frozenset(items)
            envelope["deadline"] = _timestamp(envelope["deadline"])
            assignment = ResearchAssignment(
                assignment_id=_identity(values["assignment_id"]),
                mission_id=mission,
                host_task_ref=values["host_task_ref"],
                epoch=epoch,
                authority=ResearchAuthority(**envelope),
                capability=values["capability"],
                state="ASSIGNED",
                version=1,
            )
            payload = ResearchAssignmentAdmission(
                assignment=assignment,
                expected_manifest_digest=values["expected_manifest_digest"],
                expected_brief_revision_id=_identity(values["expected_brief_revision_id"]),
            )
        elif operation == "ASSIGN_WORK":
            work = _record(AssignWorkPayload, body["payload"])
            payload = ResearchWorkItem(
                **{f.name: getattr(work, f.name) for f in fields(work)},
                mission_id=mission,
                run_id=None,
                epoch=epoch,
                state="ASSIGNED",
                version=1,
            )
        elif operation in {"START_WORK", "RECORD_ACTIVITY"}:
            start = _record(StartWorkPayload, body["payload"])
            payload = ResearchWorkStartAdmission(
                work_id=start.work_id,
                expected_version=start.expected_version,
                ownership_fence=start.ownership_fence,
                receipt=ResearchActivityReceipt(
                    work_id=start.work_id,
                    epoch=epoch,
                    ownership_fence=start.ownership_fence,
                    execution_ref=start.execution_ref,
                    occurred_at=start.occurred_at,
                    fresh_until=start.fresh_until,
                    provenance="HOST_REPORTED",
                ),
            )
        else:
            cls = {
                "SUBMIT_HANDOFF": ResearchHandoff,
                "ACK_HANDOFF": ResearchHandoffAcknowledgement,
                "WAIT_WORK": ReasonWorkPayload,
                "RESUME_WORK": ReasonWorkPayload,
                "REQUEST_CANCEL": ReasonWorkPayload,
                "ACK_STOP": StopWorkPayload,
                "END_WORK": EndWorkPayload,
                "END_RESEARCH": EndResearchPayload,
            }.get(operation)
            if cls is None:
                raise ValueError("Invalid recording command.")
            payload = _record(cls, body["payload"])
        for key in ("reason", "reason_code"):
            reason = getattr(payload, key, None)
            if reason is not None and reason not in SAFE_REASONS:
                raise _InvalidReason("Invalid recording reason.")
        return ResearchWorkCommitCommand(
            mission_id=mission, **{**body, "payload": payload}, host_authorized=host_authorized
        )
    except _InvalidReason:
        raise
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        raise ValueError("Invalid recording command.") from None


class RecordMissionResearchWorkUseCase:
    """Record only: no unlocked frame read, execution dispatch, provider or quota operation."""

    def __init__(self, store: IResearchWorkPort):
        self._store = store

    async def execute(self, mission_id: str, command: Any, *, host_authorized: bool) -> dict[str, Any]:
        try:
            typed = parse_recording_command(mission_id, command, host_authorized=host_authorized)
        except _InvalidReason:
            return self._refused("INVALID_REASON_CODE")
        except ValueError:
            return self._refused("INVALID_COMMAND")
        # The adapter owns current authority, CAS, exact scope, write-boundary masking and replay.
        # Storage failure is ephemeral and never echoes the driver exception or submitted body.
        try:
            receipt = await self._store.commit_research_work(typed)
        except Exception:
            return self._refused("STORAGE_FAILURE")
        if type(receipt) is not ResearchWorkCommitReceipt or receipt.reason_code == "STORAGE_FAILURE":
            return self._refused("STORAGE_FAILURE")
        result = receipt.to_payload()
        applied = receipt.disposition == "APPLIED"
        payload = typed.payload
        assignment_id = (
            payload.assignment.assignment_id
            if typed.operation == "ASSIGN_RESEARCH"
            else getattr(payload, "assignment_id", None)
        )
        return {
            **result,
            "assignment_id": str(assignment_id) if applied and assignment_id else None,
            "work_id": str(payload.work_id) if applied and hasattr(payload, "work_id") else None,
            "handoff_id": str(payload.handoff_id) if applied and hasattr(payload, "handoff_id") else None,
        }

    @staticmethod
    def _refused(reason: str) -> dict[str, Any]:
        return {
            "disposition": "REFUSED",
            "reason_code": reason,
            "revision": None,
            "work_version": None,
            "assignment_version": None,
            "receipt_id": None,
            "event_ids": [],
            "recorded_at": None,
            "assignment_id": None,
            "work_id": None,
            "handoff_id": None,
        }
