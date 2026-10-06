"""Explicit host-search lifecycle; stage transport answers before MCP consumption."""

import asyncio
import copy
import threading
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from urllib.parse import quote
from uuid import uuid4

from ignis.domain.host_browser_search import HostSearchQuery, HostSearchRequest
from ignis.infrastructure.connectors.host_browser.relay import LoopbackRelay
from ignis.infrastructure.connectors.host_browser.validator import validate_answer


class HostBrowserSearchService:
    """Process-local tickets. Restart invalidates requests; no durable resume promised."""

    def __init__(self) -> None:
        self._tickets: dict[str, dict] = {}
        self._lock = threading.RLock()

    def prepare(self, host_task_ref: str, session_ref: str, queries: list[str],
                result_limit: int, lifetime_seconds: int, authorized: bool, *, mode="TACTICAL") -> dict:
        if authorized is not True:
            raise ValueError("Explicit browser authorization is required")
        if type(lifetime_seconds) is not int or not 0 < lifetime_seconds <= 3600:
            raise ValueError("Lifetime must be finite and at most one hour")
        now = datetime.now(timezone.utc)
        request = HostSearchRequest(
            request_id=str(uuid4()), host_task_ref=host_task_ref, session_ref=session_ref, mode=mode,
            issued_at=now, expires_at=now + timedelta(seconds=lifetime_seconds),
            queries=tuple(HostSearchQuery(query_id=str(uuid4()), query=query,
                          search_url="https://www.tiktok.com/search?q=" + quote(query, safe=""),
                          result_limit=result_limit) for query in queries),
        )
        if any(not query.query.strip() for query in request.queries):
            raise ValueError("Search queries cannot be blank")
        extractor = files("ignis.infrastructure.connectors.host_browser").joinpath("tiktok_search.js").read_text()
        with self._lock:
            expired = [key for key, item in self._tickets.items()
                       if item["state"] != "SUBMITTING"
                       and item.get("retain_until", item["request"].expires_at) <= now]
            relays = [self._tickets.pop(key)["relay"] for key in expired]
        for relay in relays:
            relay.close()
        with self._lock:
            if len(self._tickets) >= 32:
                raise ValueError("Too many active task receipts; finish or wait for expiry")
            ticket = dict(request=request, state="PREPARED", receipt=None, payload=None)
            self._tickets[request.request_id] = ticket
            try:
                ticket["relay"] = LoopbackRelay(
                    request.model_dump(mode="json"), extractor,
                    lambda payload: self.stage(request.request_id, payload), lifetime_seconds,
                )
            except Exception:
                self._tickets.pop(request.request_id)
                raise
            result = request.model_dump(mode="json")
            result["relay_url"] = ticket["relay"].url
            result["extractor_version"] = "tiktok-public-grid-v1"
            return result

    def _ticket(self, request_id: str) -> dict:
        if request_id not in self._tickets:
            raise ValueError("UNKNOWN_REQUEST")
        return self._tickets[request_id]

    @staticmethod
    def _finish(ticket: dict, state: str, **fields) -> None:
        request = ticket["request"]
        # Keep a finite readback window after completion, without renewing collection authority.
        ticket.update(state=state, retain_until=datetime.now(timezone.utc)
                      + (request.expires_at - request.issued_at), **fields)

    @staticmethod
    def _require_identity(ticket: dict, host_task_ref: str, session_ref: str) -> None:
        request = ticket["request"]
        if (host_task_ref, session_ref) != (request.host_task_ref, request.session_ref):
            raise ValueError("Task/session identity mismatch")

    def stage(self, request_id: str, payload: dict) -> dict:
        relay = None
        try:
            with self._lock:
                ticket = self._ticket(request_id)
                relay = ticket["relay"]
                if ticket["state"] != "PREPARED":
                    raise ValueError("Task is not accepting answers")
                try:
                    receipt = validate_answer(ticket["request"], payload, datetime.now(timezone.utc))
                except ValueError:
                    self._finish(ticket, "REJECTED")
                    raise
                # Only the masked receipt is needed after validation; do not retain raw excerpts.
                ticket.update(state="STAGED", payload=None, receipt=receipt)
                return dict(status="STAGED", request_id=request_id)
        finally:
            # Never join a server callback while holding the ticket lock.
            if relay is not None:
                relay.close()

    def submit(self, request_id: str, host_task_ref: str, session_ref: str) -> dict:
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            if ticket["request"].mode != "TACTICAL":
                raise ValueError("Mission answer requires canonical mission ingestion")
            if ticket["state"] == "ACCEPTED":
                return copy.deepcopy(ticket["receipt"])
            if ticket["state"] != "STAGED":
                raise ValueError("Task has no accepted staged answer")
            if datetime.now(timezone.utc) >= ticket["request"].expires_at:
                self._finish(ticket, "EXPIRED", payload=None, receipt=None)
                raise ValueError("Task expired")
            self._finish(ticket, "ACCEPTED", payload=None)
            return copy.deepcopy(ticket["receipt"])

    async def prepare_mission(self, executor, mission_id, host_task_ref, session_ref, lifetime_seconds, authorized):
        from ignis.application.use_cases.host_browser_mission import prepare_scope
        if authorized is not True:
            raise ValueError("Explicit browser authorization is required")
        binding = await prepare_scope(executor, mission_id)
        request = self.prepare(host_task_ref, session_ref, binding["queries"], 20,
                               lifetime_seconds, authorized, mode="MISSION")
        with self._lock:
            binding["expires_at"] = self._tickets[request["request_id"]]["request"].expires_at
            self._tickets[request["request_id"]]["binding"] = binding
        request["mission_id"] = str(mission_id)
        request["collection_plan_digest"] = binding["plan"]["plan_digest"]
        return request

    async def submit_mission(self, executor, request_id, host_task_ref, session_ref):
        from ignis.application.use_cases.host_browser_mission import ingest_scope
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            if ticket["request"].mode != "MISSION":
                raise ValueError("Not a mission request")
            if ticket["state"] == "ACCEPTED":
                return copy.deepcopy(ticket["receipt"])
            if ticket["state"] != "STAGED" or datetime.now(timezone.utc) >= ticket["request"].expires_at:
                raise ValueError("Mission answer is unavailable or expired")
            ticket["state"] = "SUBMITTING"
            receipt, binding = copy.deepcopy(ticket["receipt"]), ticket["binding"]
        try:
            remaining = (ticket["request"].expires_at - datetime.now(timezone.utc)).total_seconds()
            async with asyncio.timeout(max(0, remaining)):
                receipt["mission"] = await ingest_scope(executor, binding, receipt)
        except BaseException as exc:
            with self._lock:
                self._finish(ticket, "FAILED", payload=None, receipt=None)
            if isinstance(exc, Exception):
                exc.host_search_failure = dict(
                    status="FAILED", request_id=request_id, mission_id=str(binding["mission"].id),
                    reason_code="HOST_MISSION_INGESTION_FAILED", run=binding.get("run"),
                    next_step="Read the mission journal and evidence frame before replacing this request; do not retry",
                )
            raise
        with self._lock:
            self._finish(ticket, "ACCEPTED", payload=None, receipt=receipt)
        return copy.deepcopy(receipt)

    def mode(self, request_id, host_task_ref, session_ref):
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            return ticket["request"].mode

    def cancel(self, request_id: str, host_task_ref: str, session_ref: str) -> dict:
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            if ticket["state"] not in {"PREPARED", "STAGED"}:
                raise ValueError("Task is already terminal")
            self._finish(ticket, "CANCELLED", payload=None, receipt=None)
            relay = ticket["relay"]
        relay.close()
        return dict(status="CANCELLED", request_id=request_id)

    def close(self) -> None:
        with self._lock:
            tickets = list(self._tickets.values())
            self._tickets.clear()
        for ticket in tickets:
            ticket["relay"].close()
