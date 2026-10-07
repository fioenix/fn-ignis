"""Finite loopback read capabilities, isolated from the writable host relay.

HTTP workers bridge to the owning async loop. Admission belongs to the underlying
read task: cancellation does not release capacity until repository cleanup settles.
"""

import asyncio
import base64
import hashlib
import json
import secrets
import socketserver
import threading
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.domain.mission_relay import (
    MissionRelayCursor,
    MissionRelayInspection,
    MissionRelayReadFailure,
    MissionRelaySnapshot,
    RelayReadReason,
    RelayReadStatus,
)

_REQUEST_LIMIT = 8192
_RESPONSE_LIMIT = 1_048_576
_READ_SECONDS = 3.0
_PROCESS_LOCK = threading.Lock()
_process_reads = 0


class MissionRelayProvider(Protocol):
    async def authorize_view(self, mission_id: UUID, run_id: UUID | None) -> MissionRelayReadFailure | None: ...
    async def snapshot(self, request: MissionRelayReadRequest) -> MissionRelaySnapshot | MissionRelayReadFailure: ...
    async def inspect(
        self, request: MissionRelayReadRequest, observation_id: UUID
    ) -> MissionRelayInspection | MissionRelayReadFailure: ...


@dataclass(frozen=True, slots=True)
class MissionRelayCapability:
    url: str
    origin: str
    expires_at: datetime


@dataclass(slots=True)
class _Scope:
    mission_id: UUID
    run_id: UUID | None
    expires_at: datetime
    task: asyncio.Task | None = None


def _failure(reason: RelayReadReason, unavailable: bool = False) -> MissionRelayReadFailure:
    return MissionRelayReadFailure(
        status=RelayReadStatus.UNAVAILABLE if unavailable else RelayReadStatus.REFUSED,
        reason_code=reason,
    )


def _encode(value) -> bytes:
    return json.dumps(value.to_payload(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class _Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False

    def __init__(self, relay):
        self.relay = relay
        # Bound parsing workers as well as database reads; slow headers cannot grow threads.
        self.workers = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", 0), _Handler)

    def process_request(self, request, client_address):
        if not self.workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.workers.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.workers.release()

    def handle_error(self, request, client_address):
        # Exception text, locals and the target may contain evidence or capabilities.
        pass


class _Handler(socketserver.StreamRequestHandler):
    timeout = 4.0

    def handle(self):
        self.method = "GET"
        try:
            self._handle()
        except (OSError, UnicodeError, ValueError):
            # Do not send parser diagnostics, request targets or exception messages.
            try:
                self._refuse(400, RelayReadReason.INVALID_REQUEST)
            except OSError:
                pass

    def _refuse(self, status, reason, unavailable=False):
        self._send(status, _encode(_failure(reason, unavailable)), "application/json")

    def _send(self, status, body, content_type, csp=None):
        if len(body) > _RESPONSE_LIMIT:
            return self._refuse(413, RelayReadReason.RESPONSE_TOO_LARGE)
        fields = [
            f"HTTP/1.1 {status} Response",
            f"Content-Type: {content_type}",
            f"Content-Length: {len(body)}",
            "Connection: close",
            "Cache-Control: no-store",
            "Referrer-Policy: no-referrer",
            "X-Content-Type-Options: nosniff",
        ]
        if csp:
            fields.append(f"Content-Security-Policy: {csp}")
        self.wfile.write(("\r\n".join(fields) + "\r\n\r\n").encode("ascii"))
        if self.method != "HEAD":
            self.wfile.write(body)

    def _handle(self):
        remaining = _REQUEST_LIMIT
        lines = []
        while True:
            line = self.rfile.readline(remaining + 1)
            if len(line) > remaining:
                return self._refuse(413, RelayReadReason.REQUEST_TOO_LARGE)
            remaining -= len(line)
            if not line or not line.endswith(b"\r\n"):
                return self._refuse(400, RelayReadReason.INVALID_REQUEST)
            if line == b"\r\n":
                break
            lines.append(line[:-2])
        if not lines:
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        parts = lines[0].decode("ascii").split(" ")
        if len(parts) != 3 or parts[2] not in ("HTTP/1.0", "HTTP/1.1"):
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        self.method, target, _ = parts
        headers = {}
        for line in lines[1:]:
            name, separator, value = line.partition(b":")
            if not separator or not name or any(c <= 32 or c >= 127 for c in name):
                return self._refuse(400, RelayReadReason.INVALID_REQUEST)
            headers.setdefault(name.decode("ascii").lower(), []).append(value.decode("latin1").strip())
        relay = self.server.relay
        if headers.get("host") != [relay.origin.removeprefix("http://")]:
            return self._refuse(403, RelayReadReason.SCOPE_MISMATCH)
        if "origin" in headers and headers["origin"] != [relay.origin]:
            return self._refuse(403, RelayReadReason.SCOPE_MISMATCH)
        if self.method not in ("GET", "HEAD"):
            return self._refuse(405, RelayReadReason.METHOD_NOT_ALLOWED)
        if "transfer-encoding" in headers or headers.get("content-length", ["0"]) != ["0"]:
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        url = urlsplit(target)
        if url.scheme or url.netloc or url.fragment:
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        path = url.path.split("/")
        if len(path) < 4 or path[:2] != ["", "view"]:
            return self._refuse(403, RelayReadReason.SCOPE_MISMATCH)
        with relay._lock:
            scope = None if relay._closed else relay._scopes.get(path[2])
        if scope is None:
            return self._refuse(403, RelayReadReason.SCOPE_MISMATCH)
        if scope.expires_at <= datetime.now(timezone.utc):
            return self._refuse(403, RelayReadReason.CAPABILITY_EXPIRED)
        route = "/".join(path[3:])
        document = route == ""
        if document:
            if url.query:
                return self._refuse(400, RelayReadReason.INVALID_REQUEST)
            route = "snapshot"
        observation_id = None
        if route != "snapshot":
            if route.startswith("inspect/") and route.count("/") == 1:
                try:
                    observation_id = UUID(route.split("/")[1])
                except ValueError:
                    return self._refuse(400, RelayReadReason.INVALID_REQUEST)
            else:
                return self._refuse(404, RelayReadReason.ROUTE_NOT_FOUND)
        try:
            pairs = parse_qsl(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=5)
            query = dict(pairs)
            if len(query) != len(pairs) or set(query) - {
                "page_size",
                "evidence_offset",
                "after_revision",
                "after_ordinal",
            }:
                raise ValueError
            page_size = 100 if document else int(query["page_size"])
        except (ValueError, KeyError):
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        if not 1 <= page_size <= 200:
            return self._refuse(400, RelayReadReason.INVALID_PAGE_SIZE)
        try:
            cursor = None
            if "after_revision" in query or "after_ordinal" in query:
                cursor = MissionRelayCursor(
                    mission_id=scope.mission_id,
                    revision=int(query["after_revision"]),
                    ordinal=int(query["after_ordinal"]),
                )
            request = MissionRelayReadRequest(
                mission_id=scope.mission_id,
                run_id=scope.run_id,
                page_size=page_size,
                after_cursor=cursor,
                evidence_offset=int(query.get("evidence_offset", "0")),
            )
        except (ValueError, KeyError):
            return self._refuse(400, RelayReadReason.INVALID_REQUEST)
        future = asyncio.run_coroutine_threadsafe(relay._read(scope, request, observation_id), relay.owner_loop)
        try:
            status, value = future.result(timeout=4)
        except FutureTimeout:
            future.cancel()
            return self._refuse(504, RelayReadReason.READ_TIMEOUT, True)
        except Exception:
            return self._refuse(503, RelayReadReason.READ_UNAVAILABLE, True)
        if relay._closed or scope.expires_at <= datetime.now(timezone.utc):
            return self._refuse(403, RelayReadReason.CAPABILITY_EXPIRED)
        if document and type(value) is MissionRelaySnapshot:
            try:
                body, csp = relay._document(value, scope, relay.origin + url.path + "snapshot")
            except (ValueError, RuntimeError):
                return self._refuse(503, RelayReadReason.READ_UNAVAILABLE, True)
            if relay._closed or scope.expires_at <= datetime.now(timezone.utc):
                return self._refuse(403, RelayReadReason.CAPABILITY_EXPIRED)
            return self._send(200, body, "text/html; charset=utf-8", csp)
        self._send(status, _encode(value), "application/json")


class MissionRelayReadService:
    """Shared bounded reads without opening a socket or minting viewing authority."""

    def __init__(self, *, provider: MissionRelayProvider, owner_loop: asyncio.AbstractEventLoop):
        self.provider = provider
        self.owner_loop = owner_loop
        self._lock = threading.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._closed = False

    async def read_snapshot(self, request: MissionRelayReadRequest):
        _, result = await self._read(
            _Scope(request.mission_id, request.run_id, datetime.max.replace(tzinfo=timezone.utc)), request, None
        )
        return result

    async def authorize_view(self, mission_id: UUID, run_id: UUID | None, expires_at: datetime):
        _, result = await self._read(_Scope(mission_id, run_id, expires_at), None, None)
        return result

    def _require_owner(self):
        if asyncio.get_running_loop() is not self.owner_loop:
            raise RuntimeError("Mission relay operation requires its owning loop.")

    async def _read(self, scope, request, observation_id):
        global _process_reads
        self._require_owner()
        if scope.expires_at <= datetime.now(timezone.utc):
            return 403, _failure(RelayReadReason.CAPABILITY_EXPIRED)
        with _PROCESS_LOCK:
            if self._closed or scope.task is not None or _process_reads >= 4:
                return 503, _failure(RelayReadReason.READ_BUSY, True)
            _process_reads += 1

        async def execute():
            global _process_reads
            try:
                if request is None:
                    value = await self.provider.authorize_view(scope.mission_id, scope.run_id)
                    if value is None:
                        return 200, None
                    if type(value) is MissionRelayReadFailure:
                        return (503 if value.status is RelayReadStatus.UNAVAILABLE else 403), value
                    return 503, _failure(RelayReadReason.READ_UNAVAILABLE, True)
                if observation_id is None:
                    value = await self.provider.snapshot(request)
                    expected = MissionRelaySnapshot
                else:
                    value = await self.provider.inspect(request, observation_id)
                    expected = MissionRelayInspection
                if type(value) is MissionRelayReadFailure:
                    return (503 if value.status is RelayReadStatus.UNAVAILABLE else 403), value
                if type(value) is not expected or value.mission_id != scope.mission_id or value.run_id != scope.run_id:
                    return 503, _failure(RelayReadReason.READ_UNAVAILABLE, True)
                if len(_encode(value)) > _RESPONSE_LIMIT:
                    return 413, _failure(RelayReadReason.RESPONSE_TOO_LARGE)
                return 200, value
            except Exception:
                return 503, _failure(RelayReadReason.READ_UNAVAILABLE, True)

        task = self.owner_loop.create_task(execute())
        scope.task = task
        self._tasks.add(task)

        def release(settled):
            global _process_reads
            # Done callbacks also run if shutdown cancels a task before its first step.
            with _PROCESS_LOCK:
                _process_reads -= 1
            scope.task = None
            self._tasks.discard(settled)

        task.add_done_callback(release)
        try:
            done, _ = await asyncio.wait({task}, timeout=_READ_SECONDS)
            if not done:
                if not task.cancelling():
                    task.cancel()
                return 504, _failure(RelayReadReason.READ_TIMEOUT, True)
            if self._closed or task.cancelled():
                return 503, _failure(RelayReadReason.READ_UNAVAILABLE, True)
            return task.result()
        finally:
            if not task.done() and not task.cancelling():
                task.cancel()

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


class MissionRelayHTTP(MissionRelayReadService):
    def __init__(self, *, provider: MissionRelayProvider, owner_loop: asyncio.AbstractEventLoop):
        super().__init__(provider=provider, owner_loop=owner_loop)
        self._scopes: dict[str, _Scope] = {}
        self._server = _Server(self)
        self.origin = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True, name="mission-relay-http"
        )
        self._thread.start()
        self._shutdown_thread = None

    async def open_view(self, *, mission_id: UUID, run_id: UUID | None, expires_at: datetime):
        self._require_owner()
        now = datetime.now(timezone.utc)
        if (
            type(expires_at) is not datetime
            or expires_at.tzinfo is None
            or expires_at.utcoffset() != timedelta(0)
            or not now < expires_at <= now + timedelta(minutes=60)
        ):
            return _failure(RelayReadReason.INVALID_EXPIRY)
        if type(mission_id) is not UUID or run_id is not None and type(run_id) is not UUID:
            return _failure(RelayReadReason.SCOPE_MISMATCH)
        if self._closed:
            return _failure(RelayReadReason.READ_UNAVAILABLE, True)
        # Authorization is a real read and has the same ownership, capacity and deadline.
        _, refusal = await self._read(_Scope(mission_id, run_id, expires_at), None, None)
        if refusal is not None:
            return refusal
        with self._lock:
            if self._closed:
                return _failure(RelayReadReason.READ_UNAVAILABLE, True)
            now = datetime.now(timezone.utc)
            if expires_at <= now:
                return _failure(RelayReadReason.INVALID_EXPIRY)
            # Expired capabilities are never renewed by reads or reused as new scopes.
            self._scopes = {
                key: value for key, value in self._scopes.items() if value.expires_at > now or value.task is not None
            }
            token = secrets.token_urlsafe(32)
            self._scopes[token] = _Scope(mission_id, run_id, expires_at)
        return MissionRelayCapability(f"{self.origin}/view/{token}/", self.origin, expires_at)

    def _document(self, snapshot, scope, snapshot_url):
        from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder
        body = HtmlArtifactBuilder().build_mission_relay_artifact(
            snapshot, snapshot_url=snapshot_url, expires_at=scope.expires_at,
        ).encode("utf-8")
        # Hash exact maintained inline bytes; no capability is embedded into the page.
        import re

        def hashes(tag):
            return " ".join(
                "'sha256-" + base64.b64encode(hashlib.sha256(value).digest()).decode("ascii") + "'"
                for value in re.findall(rb"<" + tag + rb"\b[^>]*>(.*?)</" + tag + rb">", body, re.S)
            )

        csp = (
            "default-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; script-src 'self' "
            + hashes(b"script")
            + "; style-src 'self' https://fonts.googleapis.com "
            + hashes(b"style")
            + "; font-src https://fonts.gstatic.com"
        )
        return body, csp

    def close(self):
        if self._closed:
            return
        super().close()
        with self._lock:
            self._scopes.clear()

        def shutdown():
            self._server.shutdown()
            self._server.server_close()

        self._shutdown_thread = threading.Thread(target=shutdown, daemon=True, name="mission-relay-shutdown")
        self._shutdown_thread.start()

    async def wait_closed(self, *, timeout: float | None) -> bool:
        self._require_owner()
        deadline = None if timeout is None else self.owner_loop.time() + timeout
        if not await super().wait_closed(timeout=timeout):
            return False
        # Closure prevents new admissions. Join each finite server thread without polling
        # or cancelling ownership-sensitive read tasks when an observer times out.
        for thread in (self._thread, self._shutdown_thread):
            if thread is None:
                continue
            remaining = None if deadline is None else max(0, deadline - self.owner_loop.time())
            await asyncio.to_thread(thread.join, remaining)
            if thread.is_alive():
                return False
        return self._closed
