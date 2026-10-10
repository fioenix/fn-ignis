"""Explicit root-host activation; permission is received, never inferred from credentials.

Only the trusted owning host supplies fresh confirmed instruction records. Persisted scope
is a recovery constraint, not a capability grant or automatic activation after restart.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import timedelta
import json
import os
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError, FollowUpExecutionPlan
from ignis.domain.follow_up_admission import CapabilityProof, WorkAuthority, digest
from ignis.domain.research_work import _text
from ignis.infrastructure.follow_up_provider_bridge import RunBounds, TransportBinding, _plan_value
from ignis.domain.value_objects import GeoCode, Timeframe


@dataclass(frozen=True, slots=True, kw_only=True)
class RootOwnerConfirmation:
    reference: str
    credential_reference: str
    bounds: RunBounds
    selected_parent_id: UUID
    source: str
    platform: str
    tier: str
    revision: str
    geo: str
    timeframe: str

    def __post_init__(self):
        from ignis.domain.research_work import _uuid
        _uuid(self.selected_parent_id)
        if type(self.bounds) is not RunBounds:
            raise ValueError("Exact confirmed bounds required.")
        for value in (self.reference, self.credential_reference, self.source, self.platform, self.tier, self.revision):
            _text(value, maximum=128)
        _plan_value(self.geo, GeoCode)
        _plan_value(self.timeframe, Timeframe)


class RootHostController:
    """Process-local producer under explicit owner delegation to this root host.

    Root construction is the fresh confirmation action. No public client or persisted scope
    can call this action through MCP. Source availability/auth/health remain unmeasured here.
    """

    def __init__(self, confirmation, registry, *, scope_path, create=False, clock):
        if type(confirmation) is not RootOwnerConfirmation:
            raise FollowUpExecutionBoundaryError()
        self.confirmation, self.registry, self.clock = confirmation, registry, clock
        self.process_id = str(uuid4())
        self.capability_id = digest((confirmation.reference, confirmation.bounds.run_id))
        self.generation = 1
        self._lock = RLock()
        self._revoked = False
        self._enrollments = {}
        self._confirmed_facts = set()
        self._tokens = 0
        self._tasks = {}
        self._loop = asyncio.get_running_loop()
        self._settled = asyncio.Event()
        self._settled.set()
        self.scope_path = Path(scope_path)
        scope = {"owner_scope": digest(confirmation), "enrollments": {}}
        if self.scope_path.is_symlink():
            raise FollowUpExecutionBoundaryError()
        try:
            if create:
                with self.scope_path.open("x") as stream:
                    json.dump(scope, stream, sort_keys=True)
            else:
                stored = json.loads(self.scope_path.read_text())
                if stored["owner_scope"] != scope["owner_scope"] or type(stored["enrollments"]) is not dict:
                    raise FollowUpExecutionBoundaryError()
        except (OSError, ValueError):
            raise FollowUpExecutionBoundaryError() from None

    def _current(self):
        bounds, now = self.confirmation.bounds, self.clock()
        if self._revoked or not bounds.started_at <= now < bounds.deadline:
            raise FollowUpExecutionBoundaryError()

    def _metadata(self, binding, plan):
        self._current()
        confirmation = self.confirmation
        if (type(binding) is not TransportBinding or type(plan) is not FollowUpExecutionPlan
                or binding.inputs.mission_id != confirmation.selected_parent_id
                or binding.confirmation_ref != confirmation.reference
                or binding.geo != confirmation.geo or binding.timeframe != confirmation.timeframe
                or binding.plan_digest != plan.digest or plan.queries != binding.queries
                or plan.geo != confirmation.geo or plan.timeframe != confirmation.timeframe
                or len(binding.sources) != 1 or len(plan.connectors) != 1
                or not set(binding.queries) <= set(confirmation.bounds.queries)
                or dict(plan.resources) != {"queries": len(binding.queries), "youtube_search_calls": len(binding.queries)}):
            raise FollowUpExecutionBoundaryError()
        source = binding.sources[0]
        if ((source.source, source.platform, source.tier, source.connector_revision) !=
                (confirmation.source, confirmation.platform, confirmation.tier, confirmation.revision)
                or source.paid or source.capability_id != self.capability_id
                or source.capability_epoch != self.generation):
            raise FollowUpExecutionBoundaryError()
        plugin = self.registry.get_plugin_by_id(source.source)
        if (plugin is None or plugin.platform.value != source.platform
                or plugin.http_authority != source.tier or not plugin.supports_search
                or plugin.requires_paid_quota):
            raise FollowUpExecutionBoundaryError()
        self.registry._check_execution_metadata(plugin, source.tier, list(plan.queries), plan)
        return plugin

    def enroll_parent(self, binding, plan):
        """Root binds its own selected canonical parent; this never enrolls a child."""
        if binding.queries != self.confirmation.bounds.queries[:1]:
            raise FollowUpExecutionBoundaryError()
        self._enroll(binding, plan, None)

    def enroll_child(self, authority, binding, plan):
        """Root supplies actual gap-linked WorkAuthority; canonical admission is still required."""
        if (type(authority) is not WorkAuthority or binding.authority_digest != authority.digest
                or binding.inputs != authority.work.inputs or binding.work_id != authority.work.work_id
                or binding.epoch != authority.work.research_epoch or binding.sources != authority.sources
                or binding.queries != authority.work.requested_scope.queries
                or binding.queries != self.confirmation.bounds.queries[1:]):
            raise FollowUpExecutionBoundaryError()
        self._enroll(binding, plan, authority)

    def _enroll(self, binding, plan, authority):
        with self._lock:
            plugin = self._metadata(binding, plan)
            previous = self._enrollments.get(binding.authority_digest)
            enrollment = (binding, plan, authority, plugin)
            if previous is not None and previous != enrollment:
                raise FollowUpExecutionBoundaryError()
            # Original parent and sole conditional child bindings survive restart as constraints,
            # never as allowed proofs. Fresh root enrollment must match any existing receipt.
            stored = json.loads(self.scope_path.read_text())
            role, binding_digest = ("parent" if authority is None else "child"), digest((binding, plan))
            old = stored["enrollments"].get(role)
            if stored["owner_scope"] != digest(self.confirmation) or (old is not None and old != binding_digest):
                raise FollowUpExecutionBoundaryError()
            stored["enrollments"][role] = binding_digest
            temporary = self.scope_path.with_name(uuid4().hex + ".scope")
            with temporary.open("x") as stream:
                json.dump(stored, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.scope_path)
            self._enrollments[binding.authority_digest] = enrollment

    def confirm_fact(self, record):
        """Explicit root confirmation of an exact canonical fact, not a generic approval callback."""
        from ignis.domain.follow_up_admission import ParentBudget, AssignmentBudget
        if type(record) not in (ParentBudget, AssignmentBudget, WorkAuthority):
            raise FollowUpExecutionBoundaryError()
        self._current()
        if record.confirmation_ref != self.confirmation.reference:
            raise FollowUpExecutionBoundaryError()
        if type(record) is ParentBudget and record.mission_id != self.confirmation.selected_parent_id:
            raise FollowUpExecutionBoundaryError()
        if type(record) is WorkAuthority and record.digest not in self._enrollments:
            raise FollowUpExecutionBoundaryError()
        self._confirmed_facts.add(digest(record))

    def verify_owner(self, reference, content_digest):
        with self._lock:
            try:
                self._current()
            except FollowUpExecutionBoundaryError:
                return False
            return reference == self.confirmation.reference and (
                content_digest in self._confirmed_facts or any(
                    content_digest == digest((entry[0], self.confirmation.bounds)) for entry in self._enrollments.values()))

    def authorize_storage(self, operation, run_id, bounds_digest):
        """No persisted scope authorizes a new session; constructor confirmation must be fresh."""
        with self._lock:
            if self._revoked:
                return False
            if operation == "create":
                return run_id is None and bounds_digest is None
            if operation not in ("register", "reopen", "write", "purge"):
                return False
            if (run_id, bounds_digest) != (self.confirmation.bounds.run_id, digest(self.confirmation.bounds)):
                return False
            return operation == "purge" or self.confirmation.bounds.started_at <= self.clock() < self.confirmation.bounds.deadline

    def _check(self, lease):
        self._current()
        if lease.proof.process_id != self.process_id or lease.proof.policy_generation != self.generation:
            raise FollowUpExecutionBoundaryError()
        entry = self._enrollments.get(lease.proof.envelope_digest)
        if entry is None or self.clock() >= lease.proof.fresh_until:
            raise FollowUpExecutionBoundaryError()
        if self._metadata(entry[0], entry[1]) is not entry[3]:
            raise FollowUpExecutionBoundaryError()

    def _lease(self, binding, plan, authority=None):
        self._metadata(binding, plan)
        now = self.clock()
        proof = CapabilityProof(envelope_digest=binding.authority_digest, process_id=self.process_id,
            policy_generation=self.generation, operational_generation=self.generation,
            checked_at=now, fresh_until=min(now+timedelta(seconds=5), self.confirmation.bounds.deadline),
            sources=binding.sources, quota_unit=authority.quota_unit if authority else "queries",
            cost_unit=authority.cost_unit if authority else "calls",
            quota_required=authority.quota if authority else len(plan.queries),
            cost_required=authority.cost if authority else 0,
            resources=authority.resources if authority else plan.resources,
            allowed=True, stop_reached=False, cancel_requested=False)
        return _RootLease(self, proof)

    @asynccontextmanager
    async def hold_parent(self, binding):
        entry = self._enrollments.get(binding.authority_digest)
        if entry is None or entry[0] != binding or entry[2] is not None:
            raise FollowUpExecutionBoundaryError()
        yield self._lease(binding, entry[1])

    @asynccontextmanager
    async def hold_current(self, authority):
        entry = self._enrollments.get(authority.digest)
        if entry is None or entry[2] != authority:
            raise FollowUpExecutionBoundaryError()
        yield self._lease(entry[0], entry[1], authority)

    @asynccontextmanager
    async def hold_execution(self, authority, plan):
        entry = self._enrollments.get(authority.digest)
        if entry is None or entry[2] != authority or entry[1] != plan:
            raise FollowUpExecutionBoundaryError()
        yield self._lease(entry[0], plan, authority)

    async def revoke(self, *, timeout=5):
        """Publish revocation first, cancel only owned guarded tasks, then await settlement."""
        current_task = asyncio.current_task()
        def publish():
            with self._lock:
                self._revoked = True
                self.generation += 1
                return tuple(self._tasks)
        tasks = await asyncio.to_thread(publish)
        for task in tasks:
            if task is not current_task:
                task.cancel()
        async def settled():
            while True:
                with self._lock:
                    if not self._tokens:
                        return
                    self._settled.clear()
                await self._settled.wait()
        await asyncio.wait_for(settled(), timeout)


class _RootLease:
    def __init__(self, host, proof):
        self.host, self.proof = host, proof

    def is_current(self):
        try:
            with self.host._lock:
                self.host._check(self)
            return True
        except FollowUpExecutionBoundaryError:
            return False

    def _enter(self):
        self.host._check(self)
        self.host._tokens += 1
        self.host._settled.clear()

    def _exit(self):
        self.host._tokens -= 1
        if not self.host._tokens:
            self.host._loop.call_soon_threadsafe(self.host._settled.set)

    @contextmanager
    def guard(self):
        # Exclude generation publication through the worker's physical commit/rollback.
        with self.host._lock:
            self._enter()
            try:
                yield
            finally:
                self._exit()

    @asynccontextmanager
    async def async_guard(self):
        task = asyncio.current_task()
        with self.host._lock:
            self._enter()
            self.host._tasks[task] = self.host._tasks.get(task, 0)+1
        try:
            yield
        finally:
            with self.host._lock:
                self.host._tasks[task] -= 1
                if not self.host._tasks[task]:
                    del self.host._tasks[task]
                self._exit()


class IsolatedCanonicalSQLite:
    """Exclusive whole-store ownership with a separate deletion-only disposition."""

    def __init__(self, root, confirmation, *, create=False, deletion_only=False):
        self.root, self.confirmation = Path(root), confirmation
        self.path = self.root / "canonical.sqlite3"
        self.marker = self.root / "ownership.json"
        self.disposition = self.root / "deletion.json"
        self.closed = False
        self._delete_request = None
        self._deletion_only = deletion_only
        try:
            if create:
                if deletion_only:
                    raise FollowUpExecutionBoundaryError()
                self.root.mkdir(parents=False, exist_ok=False)
                with self.path.open("xb") as stream:
                    stream.flush()
                    os.fsync(stream.fileno())
                stat = self.path.stat()
                self._identity = (stat.st_dev, stat.st_ino)
                with self.marker.open("x") as stream:
                    json.dump({"owner_scope": digest(confirmation), "identity": self._identity,
                               "purged": False}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                self._sync_directory()
            record = self._ownership()
            self._identity = tuple(record["identity"])
            state = self._disposition()
            if state and state.get("purged"):
                raise FollowUpExecutionBoundaryError()
            if not create and state is None and not deletion_only:
                # Reopening an old store never silently restores canonical ingress.
                raise FollowUpExecutionBoundaryError()
            self.closed = deletion_only or bool(state)
            if not (state and not self.path.exists()):
                self._check_identity()
        except (OSError, ValueError, KeyError, TypeError):
            raise FollowUpExecutionBoundaryError() from None

    @classmethod
    def reopen_for_deletion(cls, root, confirmation):
        """Explicit root retention invocation; never open a canonical ingress writer."""
        return cls(root, confirmation, deletion_only=True)

    def _sync_directory(self):
        descriptor = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _ownership(self):
        if self.root.is_symlink() or self.marker.is_symlink():
            raise FollowUpExecutionBoundaryError()
        record = json.loads(self.marker.read_text())
        if record.get("owner_scope") != digest(self.confirmation) or record.get("purged") is not False:
            raise FollowUpExecutionBoundaryError()
        return record

    def _request(self):
        import hashlib
        return {"owner_scope": digest(self.confirmation), "identity": list(self._identity),
                "receipt_hash": hashlib.sha256(self.marker.read_bytes()).hexdigest(),
                "canonical_path": str(self.path.absolute())}

    def _disposition(self):
        if self.disposition.is_symlink():
            raise FollowUpExecutionBoundaryError()
        if not self.disposition.exists():
            return None
        record = json.loads(self.disposition.read_text())
        if any(record.get(key) != value for key, value in self._request().items()):
            raise FollowUpExecutionBoundaryError()
        if record.get("deletion_pending") is not True:
            raise FollowUpExecutionBoundaryError()
        return record

    def _publish(self, record):
        temporary = self.root / ("." + str(uuid4()) + ".deletion.tmp")
        try:
            with temporary.open("x") as stream:
                json.dump(record, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.disposition)
            self._sync_directory()
        finally:
            if temporary.exists():
                temporary.unlink()

    def check(self):
        if self.closed:
            raise FollowUpExecutionBoundaryError()
        self._check_identity()

    def _check_identity(self):
        if self.root.is_symlink() or self.path.is_symlink() or not self.path.is_file():
            raise FollowUpExecutionBoundaryError()
        stat = self.path.stat()
        if (stat.st_dev, stat.st_ino) != self._identity:
            raise FollowUpExecutionBoundaryError()

    async def purge(self, host, repository=None):
        import sqlite3
        record = self._ownership()
        if (host.confirmation != self.confirmation
                or tuple(record["identity"]) != self._identity
                or host.clock() < self.confirmation.bounds.retention_until):
            raise FollowUpExecutionBoundaryError()
        if repository is not None:
            owner = repository.enrollment
            if (owner.confirmation != self.confirmation or owner.path != self.path
                    or owner._identity != self._identity):
                raise FollowUpExecutionBoundaryError()
        state = self._disposition()
        request = self._request()
        if state and state.get("purged"):
            return state
        if not state and self._delete_request != request:
            if not host.authorize_storage("purge", self.confirmation.bounds.run_id,
                                          digest(self.confirmation.bounds)):
                raise FollowUpExecutionBoundaryError()
            if repository is None and not self._deletion_only:
                raise FollowUpExecutionBoundaryError()
            self._check_identity()
            self._delete_request = request
        # Publication failures cannot restore ingress. Same-host request remains sealed.
        await host.revoke()
        if repository is not None:
            await repository.close()
        self.closed = True
        if state is None:
            self._publish(dict(request, deletion_pending=True, purged=False))
        # Exact absence is recoverable only behind a validated durable pending intent.
        if self.path.is_symlink():
            raise FollowUpExecutionBoundaryError()
        if self.path.exists():
            self._check_identity()
            connection = sqlite3.connect(self.path.as_uri()+"?mode=rw", uri=True, timeout=2)
            try:
                connection.execute("BEGIN EXCLUSIVE")
                if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                    raise FollowUpExecutionBoundaryError()
                self._check_identity()
                if any((self.root / (self.path.name + suffix)).exists()
                       for suffix in ("-wal", "-shm", "-journal")):
                    raise FollowUpExecutionBoundaryError()
                connection.rollback()
            except sqlite3.Error:
                raise FollowUpExecutionBoundaryError() from None
            finally:
                connection.close()
            self.path.unlink()
            self._sync_directory()
        elif state is None:
            raise FollowUpExecutionBoundaryError()
        audit = dict(request, deletion_pending=True, purged=True,
                     purged_at=host.clock().isoformat(), stores_deleted=1)
        self._publish(audit)
        return audit


from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def open_owned_canonical_repository(enrollment):
    """Compose guards on an exact production SQLite instance for native consumer identity."""
    enrollment.check()
    repository = SqliteTrendRepository(str(enrollment.path))
    repository.enrollment = enrollment
    original_connection = repository._get_connection
    original_close = repository.close

    def connection():
        enrollment.check()
        return original_connection()

    async def close():
        await original_close()
        enrollment.closed = True

    repository._get_connection = connection
    repository.close = close
    return repository
