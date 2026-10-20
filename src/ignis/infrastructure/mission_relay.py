"""Bounded mission snapshot reads owned by one FastMCP async lifespan.

Reads run on the owning loop. Admission belongs to the underlying read task: cancellation does
not release capacity until repository cleanup settles. Ignis serves no tracking page; agents build
tracking artifacts from these reads with the ignis-track guidance.
"""

import asyncio
import json
import threading
from typing import Protocol

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.domain.mission_relay import (
    MissionRelayReadFailure,
    MissionRelaySnapshot,
    RelayReadReason,
    RelayReadStatus,
)

_RESPONSE_LIMIT = 1_048_576
_READ_SECONDS = 3.0
_PROCESS_LOCK = threading.Lock()
_process_reads = 0


class MissionRelayProvider(Protocol):
    async def snapshot(self, request: MissionRelayReadRequest) -> MissionRelaySnapshot | MissionRelayReadFailure: ...


def _failure(reason: RelayReadReason, unavailable: bool = False) -> MissionRelayReadFailure:
    return MissionRelayReadFailure(
        status=RelayReadStatus.UNAVAILABLE if unavailable else RelayReadStatus.REFUSED,
        reason_code=reason,
    )


def _encode(value) -> bytes:
    return json.dumps(value.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class MissionRelayReadService:
    """Shared bounded snapshot reads; opens no socket and mints no viewing authority."""

    def __init__(self, *, provider: MissionRelayProvider, owner_loop: asyncio.AbstractEventLoop):
        self.provider = provider
        self.owner_loop = owner_loop
        self._lock = threading.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def read_snapshot(self, request: MissionRelayReadRequest) -> MissionRelaySnapshot | MissionRelayReadFailure:
        global _process_reads
        self._require_owner()
        with _PROCESS_LOCK:
            if self._closed or _process_reads >= 4:
                return _failure(RelayReadReason.READ_BUSY, True)
            _process_reads += 1

        async def execute():
            try:
                value = await self.provider.snapshot(request)
                if type(value) is MissionRelayReadFailure:
                    return value
                if type(value) is not MissionRelaySnapshot or value.mission_id != request.mission_id or value.run_id != request.run_id:
                    return _failure(RelayReadReason.READ_UNAVAILABLE, True)
                if len(_encode(value)) > _RESPONSE_LIMIT:
                    return _failure(RelayReadReason.RESPONSE_TOO_LARGE)
                return value
            except Exception:
                return _failure(RelayReadReason.READ_UNAVAILABLE, True)

        task = self.owner_loop.create_task(execute())
        self._tasks.add(task)

        def release(settled):
            global _process_reads
            # Done callbacks also run if shutdown cancels a task before its first step.
            with _PROCESS_LOCK:
                _process_reads -= 1
            self._tasks.discard(settled)

        task.add_done_callback(release)
        try:
            done, _ = await asyncio.wait({task}, timeout=_READ_SECONDS)
            if not done:
                if not task.cancelling():
                    task.cancel()
                return _failure(RelayReadReason.READ_TIMEOUT, True)
            if self._closed or task.cancelled():
                return _failure(RelayReadReason.READ_UNAVAILABLE, True)
            return task.result()
        finally:
            if not task.done() and not task.cancelling():
                task.cancel()

    def _require_owner(self):
        if asyncio.get_running_loop() is not self.owner_loop:
            raise RuntimeError("Mission relay operation requires its owning loop.")

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True

        def cancel_reads():
            for task in tuple(self._tasks):
                if not task.done() and not task.cancelling():
                    task.cancel()

        self.owner_loop.call_soon_threadsafe(cancel_reads)

    async def wait_closed(self, *, timeout: float | None) -> bool:
        self._require_owner()
        tasks = tuple(self._tasks)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            if pending:
                return False
        return self._closed
