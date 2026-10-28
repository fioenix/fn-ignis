"""Explicit host-search lifecycle; stage transport answers before MCP consumption."""

import asyncio
import copy
import json
import threading
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from importlib.resources import files
from urllib.parse import quote
from uuid import uuid4

from ignis.domain.host_browser_search import HostSearchQuery, HostSearchRequest
from ignis.infrastructure.caller_storage import current_caller_storage
from ignis.domain.source_identity import identity_free_source_url
from ignis.infrastructure.security.pii_sanitizer import mask_author_identity_text
from ignis.infrastructure.connectors.host_browser.relay import LoopbackRelay
from ignis.infrastructure.connectors.host_browser.action_labels import action_labels_from_rows, seeded_action_labels
from ignis.infrastructure.connectors.host_browser.attribution_locales import attribution_locales_from_rows, seeded_attribution_locales
from ignis.infrastructure.connectors.host_browser.validator import validate_answer
from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary, seeded_lexicon_terms


def _outward(receipt):
    """Return detached sanitized values; no member can mutate the shared replay cache."""
    if receipt is None:
        return None
    outward = copy.deepcopy(receipt)
    for record in outward.get("observations", ()):
        source = record.get("source", outward.get("source", "tiktok"))
        record["source_url"] = identity_free_source_url(source, record.get("source_url"), {})
        record["excerpt"] = mask_author_identity_text(record.get("excerpt"))
    return outward


@dataclass
class _MissionGroup:
    key: tuple
    binding: dict
    caller: object
    expected: tuple
    members: dict = field(default_factory=dict)
    state: str = "PREPARED"
    task: object = None
    loop: object = None
    started: bool = False
    cancel_sent: bool = False
    stop_reason: str | None = None
    receipt: dict | None = None
    failure: dict | None = None
    retain_until: object = None
    admission: asyncio.Lock = field(default_factory=asyncio.Lock)


async def _settle(task):
    """Drain owned execution despite repeated cancellation of an awaiting host call."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    return task.result()


class AttributionVocabularyMissing(ValueError):
    """Preparation refused: without attribution templates, excerpts would keep the poster's name."""


class HostBrowserSearchService:
    """Process-local tickets. Restart invalidates requests; no durable resume promised."""

    def __init__(self, attribution_templates=None, *, threads_attribution_templates=None) -> None:
        self._tickets: dict[str, dict] = {}
        self._groups: dict[tuple, _MissionGroup] = {}
        self._lock = threading.RLock()
        # Tactical preparation opens no database, so it starts from the shipped seed (Spec 012).
        if attribution_templates is None:
            attribution_templates = seeded_lexicon_terms("034_tiktok_attribution.sql", "tiktok_attribution")
        self._attribution_templates = tuple(attribution_templates)
        if threads_attribution_templates is None:
            threads_attribution_templates = seeded_lexicon_terms("036_threads_attribution.sql", "threads_attribution")
        self._threads_attribution_templates = tuple(threads_attribution_templates)

    def register_attribution_templates(self, templates, *, source="tiktok") -> None:
        """Replace one source's templates; empty means unavailable, never a cross-source fallback."""
        with self._lock:
            if source == "tiktok":
                self._attribution_templates = tuple(templates)
            elif source == "threads":
                self._threads_attribution_templates = tuple(templates)
            else:
                raise ValueError("Unsupported host search source")

    def attribution_templates_for(self, source="tiktok") -> tuple[str, ...]:
        """Return an immutable source snapshot or fail before creating a ticket/relay."""
        with self._lock:
            if source == "tiktok":
                templates = self._attribution_templates
            elif source == "threads":
                templates = self._threads_attribution_templates
            else:
                raise ValueError("Unsupported host search source")
            if not templates:
                raise AttributionVocabularyMissing("No attribution vocabulary is registered for the host source")
            return templates

    async def refresh_attribution_templates(self, repository, *, source="tiktok") -> tuple[str, ...]:
        """Load a caller-local immutable snapshot without changing tactical packaged vocabulary."""
        vocabulary = await load_market_vocabulary(repository)
        templates = (vocabulary.tiktok_attribution if source == "tiktok" else
                     vocabulary.threads_attribution if source == "threads" else ())
        if not templates:
            raise AttributionVocabularyMissing("No attribution vocabulary is registered for the host source")
        return tuple(templates)

    def prepare(self, host_task_ref: str, session_ref: str, queries: list[str],
                result_limit: int, lifetime_seconds: int, authorized: bool, *, mode="TACTICAL",
                attribution_templates=None, source="tiktok", self_identities=(), action_labels=None, attribution_locales=None) -> dict:
        if authorized is not True:
            raise ValueError("Explicit browser authorization is required")
        attribution_templates = (self.attribution_templates_for(source) if attribution_templates is None
                                 else tuple(attribution_templates))
        if not attribution_templates:
            raise AttributionVocabularyMissing("No attribution vocabulary is registered for the host source")
        locales = copy.deepcopy(seeded_attribution_locales() if attribution_locales is None else attribution_locales) if source == "tiktok" else {}
        if source == "tiktok" and not locales:
            raise AttributionVocabularyMissing("No attribution vocabulary is registered for the host source")
        if type(lifetime_seconds) is not int or not 0 < lifetime_seconds <= 3600:
            raise ValueError("Lifetime must be finite and at most one hour")
        now = datetime.now(timezone.utc)
        request = HostSearchRequest(
            request_id=str(uuid4()), host_task_ref=host_task_ref, session_ref=session_ref, mode=mode, source=source,
            issued_at=now, expires_at=now + timedelta(seconds=lifetime_seconds),
            queries=tuple(HostSearchQuery(query_id=str(uuid4()), query=query,
                          search_url=("https://www.threads.com/search?q=" if source == "threads" else
                                      "https://www.tiktok.com/search?q=") + quote(query, safe=""),
                          result_limit=result_limit) for query in queries),
        )
        if any(not query.query.strip() for query in request.queries):
            raise ValueError("Search queries cannot be blank")
        # The tab script finds its query by text, so each query may appear once (PR #79 review).
        if len({query.query for query in request.queries}) != len(request.queries):
            raise ValueError("Each search query may appear once in a batch")
        extractor = files("ignis.infrastructure.connectors.host_browser").joinpath(source + "_search.js").read_text()
        labels = (copy.deepcopy(seeded_action_labels() if action_labels is None else action_labels)
                  if source == "threads" else {})
        if source == "threads":
            # Data injection leaves the packaged handoff and relay transport unchanged.
            extractor = ("args => (" + extractor.strip() + ")({...args, action_labels: "
                         + json.dumps(labels, ensure_ascii=True) + "})")
        with self._lock:
            relays = self._prune(now)
        for relay in relays:
            relay.close()
        ticket, relay = None, None
        try:
            with self._lock:
                if len(self._tickets) >= 32:
                    raise ValueError("Too many active task receipts; finish or wait for expiry")
                ticket = dict(request=request, state="PREPARED", receipt=None, payload=None,
                              attribution_templates=attribution_templates, self_identities=tuple(self_identities),
                              action_labels=labels, attribution_locales=locales,
                              caller=current_caller_storage.get())
                self._tickets[request.request_id] = ticket
                relay = ticket["relay"] = LoopbackRelay(
                    {**request.model_dump(mode="json"), "extractor_version": request.extractor_version}, extractor,
                    lambda payload: self.stage(request.request_id, payload), lifetime_seconds,
                )
                result = request.model_dump(mode="json")
                result["relay_url"] = relay.url
                # Browser tooling may refuse to read a script back from the page (Spec 012 FR-013).
                result["tab_script"] = relay.tab_script
                result["extractor_version"] = request.extractor_version
                return result
        except BaseException:
            # Until prepare returns, this call alone owns its newly allocated ticket/relay.
            with self._lock:
                if ticket is not None and self._tickets.get(request.request_id) is ticket:
                    self._finish(ticket, "REJECTED", payload=None, receipt=None)
                    self._tickets.pop(request.request_id)
            if relay is not None:
                relay.close()
            raise

    def _ticket(self, request_id: str) -> dict:
        if request_id not in self._tickets:
            raise ValueError("UNKNOWN_REQUEST")
        return self._tickets[request_id]

    @staticmethod
    def _finish(ticket: dict, state: str, **fields) -> None:
        request = ticket["request"]
        for record in ticket.get("author_records") or ():
            record.clear()
        if ticket.get("author_records") is not None:
            ticket["author_records"].clear()
        # Keep a finite readback window after completion, without renewing collection authority.
        ticket.update(state=state, author_records=None, retain_until=datetime.now(timezone.utc)
                      + (request.expires_at - request.issued_at), **fields)

    @staticmethod
    def _require_identity(ticket: dict, host_task_ref: str, session_ref: str) -> None:
        request = ticket["request"]
        if ticket["caller"] is not current_caller_storage.get():
            raise ValueError("Original caller storage mismatch")
        if (host_task_ref, session_ref) != (request.host_task_ref, request.session_ref):
            raise ValueError("Task/session identity mismatch")

    def stage(self, request_id: str, payload: dict) -> dict:
        relay = None
        try:
            with self._lock:
                ticket = self._ticket(request_id)
                relay = ticket["relay"]
                if ticket["state"] != "PREPARED":
                    group = ticket.get("group")
                    if group is not None and group.state in {"PREPARED", "SUBMITTING"}:
                        self._stop_group(group, "REJECTED")
                    raise ValueError("Task is not accepting answers")
                author_records = [] if ticket["request"].mode == "MISSION" else None
                try:
                    receipt = validate_answer(ticket["request"], payload, datetime.now(timezone.utc),
                                              ticket["attribution_templates"], ticket["self_identities"],
                                              author_records=author_records, action_labels=ticket["action_labels"],
                                              attribution_locales=ticket["attribution_locales"])
                except ValueError:
                    group = ticket.get("group")
                    if group is not None:
                        self._stop_group(group, "REJECTED")
                    else:
                        self._finish(ticket, "REJECTED", receipt=None)
                    raise
                # Only mission policy input stays transient in memory; receipts are always masked.
                ticket.update(state="STAGED", payload=None, receipt=receipt, author_records=author_records)
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
                return _outward(ticket["receipt"])
            if ticket["state"] != "STAGED":
                raise ValueError("Task has no accepted staged answer")
            if datetime.now(timezone.utc) >= ticket["request"].expires_at:
                self._finish(ticket, "EXPIRED", payload=None, receipt=None)
                raise ValueError("Task expired")
            self._finish(ticket, "ACCEPTED", payload=None)
            return _outward(ticket["receipt"])

    def _prune(self, now):
        """Evict whole retained groups, never one collectible sibling or an owned writer."""
        relays = []
        for group in self._all_groups():
            if group.task is not None and not group.task.done():
                continue
            if group.state == "PREPARED" and now >= self._deadline(group):
                self._stop_group(group, "EXPIRED")
            if group.retain_until is not None and group.retain_until <= now:
                for key in group.members.values():
                    ticket = self._tickets.pop(key, None)
                    if ticket:
                        relays.append(ticket["relay"])
                if self._groups.get(group.key) is group:
                    self._groups.pop(group.key, None)
        for key, item in list(self._tickets.items()):
            if item.get("group") is None and item.get("retain_until", item["request"].expires_at) <= now:
                relays.append(self._tickets.pop(key)["relay"])
        return relays

    def _all_groups(self):
        """Ticket ownership retains replay/drain state independently of preparation lookup."""
        return list({id(ticket["group"]): ticket["group"] for ticket in self._tickets.values()
                     if ticket.get("group") is not None}.values())

    def _deadline(self, group):
        return min(self._tickets[key]["request"].expires_at for key in group.members.values())

    def _finish_group(self, group, state, *, receipt=None):
        group.state, group.receipt = state, receipt
        now = datetime.now(timezone.utc)
        lifetimes = []
        for key in group.members.values():
            ticket = self._tickets[key]
            self._finish(ticket, state, payload=None, receipt=None)
            lifetimes.append(ticket["request"].expires_at - ticket["request"].issued_at)
        group.retain_until = now + min(lifetimes)
        if self._groups.get(group.key) is group:
            self._groups.pop(group.key, None)

    def _stop_group(self, group, reason):
        if group.state in {"ACCEPTED", "FAILED", "CANCELLED", "EXPIRED", "REJECTED"}:
            return
        group.stop_reason = group.stop_reason or reason
        if group.task is not None and not group.task.done():
            group.state = "DRAINING"
            if group.started and not group.cancel_sent:
                group.cancel_sent = True
                group.loop.call_soon_threadsafe(group.task.cancel)
        else:
            self._finish_group(group, reason)
        # Schedule relay shutdown outside the ticket lock; a callback may itself hold a relay thread.
        for key in group.members.values():
            relay = self._tickets[key]["relay"]
            threading.Thread(target=relay.close, name="ignis-group-relay-close", daemon=True).start()

    async def prepare_mission(self, executor, mission_id, host_task_ref, session_ref, lifetime_seconds, authorized,
                              *, source="tiktok"):
        group, owned_request_id, previous_deadline = None, None, None
        try:
            from ignis.application.use_cases.host_browser_mission import prepare_scope
            from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry
            if authorized is not True:
                raise ValueError("Explicit browser authorization is required")
            with self._lock:
                relays = self._prune(datetime.now(timezone.utc))
            for relay in relays:
                relay.close()
            attribution_templates = await self.refresh_attribution_templates(executor._repo, source=source)
            labels = (action_labels_from_rows(await executor._repo.get_domain_lexicons())
                      if source == "threads" else {})
            locales = (attribution_locales_from_rows(await executor._repo.get_domain_lexicons())
                       if source == "tiktok" else {})
            binding = await prepare_scope(executor, mission_id, source)
            sync = getattr(executor, "_vocabulary_sync", None)
            identity_repo = getattr(sync, "_credential_repository", executor._repo)
            identities = await SelfIdentityRegistry(identity_repo).load()
            identities += list(getattr(executor._registry, "self_identities", ()))
            caller = current_caller_storage.get()
            key = (str(mission_id), caller, binding["digest"], binding["plan"]["plan_digest"])
            with self._lock:
                stale = [existing for existing in self._groups.values()
                         if existing.key[:2] == key[:2] and existing.key != key]
                if any(existing.state in {"SUBMITTING", "DRAINING"} for existing in stale):
                    raise ValueError("Mission group ingestion is already running")
                group = self._groups.get(key)
                if group is not None and (group.state != "PREPARED" or source in group.members):
                    raise ValueError("Duplicate or terminal source group")
                if group is not None and datetime.now(timezone.utc) >= self._deadline(group):
                    self._stop_group(group, "EXPIRED")
                    group = None
                if group is not None:
                    first = self._tickets[next(iter(group.members.values()))]["request"]
                    if (host_task_ref, session_ref) != (first.host_task_ref, first.session_ref):
                        raise ValueError("Sibling identity mismatch")
                    previous_deadline = group.binding.get("expires_at")
                request = self.prepare(host_task_ref, session_ref, binding["queries"], 20, lifetime_seconds, authorized,
                                       mode="MISSION", attribution_templates=attribution_templates,
                                       source=source, self_identities=identities, action_labels=labels, attribution_locales=locales)
                owned_request_id = request["request_id"]
                if group is None:
                    group = _MissionGroup(key, binding, caller, binding["required_host_sources"])
                    self._groups[key] = group
                group.members[source] = owned_request_id
                ticket = self._tickets[owned_request_id]
                ticket.update(group=group, binding=group.binding)
                group.binding["expires_at"] = self._deadline(group)
                request.update(mission_id=str(mission_id), collection_plan_digest=binding["plan"]["plan_digest"])
                # Reject stale prepared scope only after the replacement was successfully admitted.
                for existing in stale:
                    if existing.state == "PREPARED":
                        self._stop_group(existing, "REJECTED")
                return request
        except BaseException:
            relay = None
            with self._lock:
                # Validation owns nothing. Once a writer owns a group, preparation cannot revoke it.
                if owned_request_id is not None and (group is None or group.state == "PREPARED"):
                    ticket = self._tickets.pop(owned_request_id, None)
                    if ticket is not None:
                        self._finish(ticket, "REJECTED", payload=None, receipt=None)
                        relay = ticket.get("relay")
                    if group is not None:
                        if group.members.get(source) == owned_request_id:
                            group.members.pop(source)
                        if previous_deadline is not None:
                            group.binding["expires_at"] = previous_deadline
                        collectible = any(self._tickets[key]["state"] in {"PREPARED", "STAGED"}
                                          for key in group.members.values())
                        if not collectible:
                            if group.members:
                                self._stop_group(group, "REJECTED")
                            else:
                                group.state, group.stop_reason = "REJECTED", "REJECTED"
                                if self._groups.get(group.key) is group:
                                    self._groups.pop(group.key)
            if relay is not None:
                relay.close()
            raise

    async def submit_mission(self, executor, request_id, host_task_ref, session_ref):
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            group = ticket.get("group")
            if group is None:
                raise ValueError("Not a mission request")
        try:
            # Serialize admission across snapshot awaits. Siblings join the claimed task instead
            # of interpreting that task's own RUNNING/evidence changes as an external stale frame.
            async with group.admission:
                worker, cached = await self._claim_mission(executor, request_id, host_task_ref, session_ref)
            if cached is not None:
                return {**_outward(cached), "request_id": request_id}
            try:
                return {**_outward(await asyncio.shield(worker)), "request_id": request_id}
            except asyncio.CancelledError:
                if not asyncio.current_task().cancelling() and group.failure is not None:
                    exc = ValueError("Mission group terminated")
                    exc.host_search_failure = copy.deepcopy(group.failure)
                    raise exc from None
                raise
        except asyncio.CancelledError:
            with self._lock:
                self._stop_group(group, "CANCELLED")
                worker = group.task
            if worker is not None:
                try:
                    await _settle(worker)
                except BaseException:
                    pass
            raise
        except Exception as exc:
            if getattr(exc, "host_search_failure", None) is not None:
                detached = copy.copy(exc)
                detached.host_search_failure = {**copy.deepcopy(exc.host_search_failure), "request_id": request_id}
                raise detached from None
            raise

    async def _claim_mission(self, executor, request_id, host_task_ref, session_ref):
        from ignis.application.use_cases.host_browser_mission import prepare_scope, snapshot_digest
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            group = ticket.get("group")
            if group is None:
                raise ValueError("Not a mission request")
            if group.state == "ACCEPTED":
                return None, group.receipt
            if group.state not in {"PREPARED", "SUBMITTING", "DRAINING"}:
                exc = ValueError("Mission group is terminal")
                if group.failure is not None:
                    exc.host_search_failure = copy.deepcopy(group.failure)
                raise exc
            if group.task is not None:
                if len(group.members) == 1:
                    raise ValueError("Mission ingestion is already running")
                worker = group.task
            else:
                if datetime.now(timezone.utc) >= self._deadline(group):
                    self._stop_group(group, "EXPIRED")
                    raise ValueError("Mission group expired")
                if not set(group.expected).issubset(group.members) or any(
                    self._tickets[key]["state"] != "STAGED" for key in group.members.values()
                ):
                    raise ValueError("Every required sibling must be staged")
                worker = None
        if worker is None:
            # Revalidate before entering the writer, then again under its canonical claim.
            current_snapshot = await executor._workspace_store.load_mission_evidence_snapshot(group.binding["mission"].id)
            if snapshot_digest(current_snapshot) != group.binding["digest"]:
                with self._lock:
                    self._stop_group(group, "REJECTED")
                raise ValueError("STALE_SCOPE")
            current = await prepare_scope(executor, group.binding["mission"].id, group.binding["source"])
            with self._lock:
                if current["digest"] != group.binding["digest"] or current["plan"] != group.binding["plan"]:
                    self._stop_group(group, "REJECTED")
                    raise ValueError("STALE_SCOPE")
                if group.task is not None:
                    worker = group.task
                else:
                    if group.state != "PREPARED" or datetime.now(timezone.utc) >= self._deadline(group):
                        self._stop_group(group, "EXPIRED")
                        raise ValueError("Mission group is unavailable or expired")
                    group.state = "SUBMITTING"
                    for key in group.members.values():
                        self._tickets[key]["state"] = "SUBMITTING"
                    group.loop = asyncio.get_running_loop()
                    worker = group.task = asyncio.create_task(self._run_group(executor, group))
        return worker, None

    async def _run_group(self, executor, group):
        from ignis.application.use_cases.host_browser_mission import ingest_scope
        group.started = True
        failure = None
        try:
            def guard():
                if group.stop_reason is not None:
                    raise ValueError("Mission group terminated")
                if datetime.now(timezone.utc) >= self._deadline(group):
                    raise ValueError("Host mission request expired")
            guard()
            group.binding["lifecycle_guard"] = guard
            staged = {source: copy.deepcopy(self._tickets[key]["receipt"]) for source, key in group.members.items()}
            first = staged[next(iter(staged))]
            receipt = {**first, "observations": [r for part in staged.values() for r in part["observations"]],
                       "outcomes": [o for part in staged.values() for o in part["outcomes"]]}
            if len(staged) > 1:
                receipt.pop("source", None)
                receipt["observations"] = [{**r, "source": source} for source, part in staged.items() for r in part["observations"]]
                receipt["outcomes"] = [{**o, "source": source} for source, part in staged.items() for o in part["outcomes"]]
            remaining = (self._deadline(group) - datetime.now(timezone.utc)).total_seconds()
            async with asyncio.timeout(max(0, remaining)):
                policy_records = {source: self._tickets[key].get("author_records") or []
                                  for source, key in group.members.items()}
                receipt["mission"] = await ingest_scope(executor, group.binding, {**receipt, "sources": staged},
                                                        author_records=policy_records)
        except BaseException as exc:
            failure = exc

        async def reconcile():
            run = group.binding.get("run")
            journals = await executor._workspace_store.list_run_journals(group.binding["mission"].id)
            signals = await executor._repo.get_mission_signals(group.binding["mission"].id)
            claim = await executor._workspace_store.get_mission_writer_claim(group.binding["mission"].id)
            return dict(run=run, journals=[dict(run_id=str(j.run_id), status=j.status) for j in journals],
                        observations=len(signals), writer_active=claim is not None)
        try:
            readback = await _settle(asyncio.create_task(reconcile()))
        except BaseException:
            readback = dict(run=group.binding.get("run"), readback_required=True)
            failure = failure or ValueError("Mission reconciliation unavailable")
        # No await between observing cancellation and publishing the whole group's cache.
        with self._lock:
            if failure is not None or group.stop_reason is not None:
                group.failure = dict(status="FAILED", request_id=next(iter(group.members.values())),
                    mission_id=str(group.binding["mission"].id), reason_code="HOST_MISSION_INGESTION_FAILED",
                    run=group.binding.get("run"), readback=readback,
                    next_step="Read the mission journal and evidence frame before replacing this request; do not retry")
                self._finish_group(group, "FAILED")
            else:
                self._finish_group(group, "ACCEPTED", receipt=receipt)
        if failure is not None:
            if isinstance(failure, Exception):
                failure.host_search_failure = copy.deepcopy(group.failure)
            raise failure
        if group.stop_reason is not None:
            exc = ValueError("Mission group terminated")
            exc.host_search_failure = copy.deepcopy(group.failure)
            raise exc
        return receipt

    async def cancel_mission(self, request_id, host_task_ref, session_ref):
        with self._lock:
            ticket = self._ticket(request_id)
            self._require_identity(ticket, host_task_ref, session_ref)
            group = ticket.get("group")
            if group is None:
                raise ValueError("Not a mission request")
            if group.state not in {"PREPARED", "SUBMITTING", "DRAINING"}:
                raise ValueError("Mission group is terminal")
            self._stop_group(group, "CANCELLED")
            worker = group.task
        if worker is not None:
            try:
                await _settle(worker)
            except Exception:
                pass
            except asyncio.CancelledError:
                if not worker.done():
                    await _settle(worker)
        return dict(status="CANCELLED", request_id=request_id)

    def request_mode(self, request_id):
        """Non-authorizing routing hint; never returns bindings, receipts or record contents."""
        if not isinstance(request_id, str):
            return None
        with self._lock:
            ticket = self._tickets.get(request_id)
            return ticket["request"].mode if ticket is not None else None

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
            if ticket.get("group") is not None:
                self._stop_group(ticket["group"], "CANCELLED")
                return dict(status="CANCELLED", request_id=request_id)
            self._finish(ticket, "CANCELLED", payload=None, receipt=None)
            relay = ticket["relay"]
        relay.close()
        return dict(status="CANCELLED", request_id=request_id)

    async def aclose(self) -> None:
        """Drain every owned group before caller repositories and the event loop close."""
        self.close()
        with self._lock:
            workers = [group.task for group in self._all_groups() if group.task is not None]
        for worker in workers:
            try:
                await _settle(worker)
            except (Exception, asyncio.CancelledError):
                # The terminal group retains its persisted run/readback until final shutdown.
                pass
        self.close()

    def close(self) -> None:
        with self._lock:
            tickets = list(self._tickets.values())
            for group in self._all_groups():
                self._stop_group(group, "CANCELLED")
            if any(group.task is not None and not group.task.done() for group in self._all_groups()):
                # Retain owned tickets until their executor drains; shutdown may call close again.
                pass
            else:
                self._tickets.clear()
                self._groups.clear()
        for ticket in tickets:
            ticket["relay"].close()
