"""Opt-in host composition; this module never issues owner or source capability grants."""

from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from uuid import UUID

import httpx

from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
from ignis.domain.follow_up_admission import CapabilityProof, SourceGrant, WorkAuthority, digest
from ignis.domain.research_work import ResearchInputBindings, _digest, _integer, _time, _uuid
from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin


def _plan_value(value, enum):
    """Normalize actual str(Enum) plan values without guessing a collection window."""
    if type(value) is enum:
        result = value
    elif type(value) is str and value.startswith(enum.__name__ + "."):
        result = enum.__members__.get(value.split(".", 1)[1])
        if result is None:
            raise FollowUpExecutionBoundaryError()
    else:
        try:
            result = enum(value)
        except (TypeError, ValueError):
            raise FollowUpExecutionBoundaryError() from None
    if enum is Timeframe and result.value not in {member.value for member in Timeframe}:
        raise FollowUpExecutionBoundaryError()
    return result.value


@dataclass(frozen=True, slots=True, kw_only=True)
class RunBounds:
    run_id: UUID
    started_at: datetime
    deadline: datetime
    retention_until: datetime
    queries: tuple[str, ...]
    video_limit: int
    search_calls: int
    other_calls: int

    def __post_init__(self):
        _uuid(self.run_id)
        for value in (self.started_at, self.deadline, self.retention_until):
            _time(value)
        if not self.started_at < self.deadline <= self.retention_until:
            raise ValueError("Invalid run expiry bounds.")
        if type(self.queries) is not tuple or not self.queries or len(set(self.queries)) != len(self.queries):
            raise ValueError("Explicit unique run queries required.")
        if any(type(q) is not str or not q.strip() or len(q) > 512 for q in self.queries):
            raise ValueError("Invalid run query.")
        for amount in (self.video_limit, self.search_calls, self.other_calls):
            _integer(amount, 1)


@dataclass(frozen=True, slots=True, kw_only=True)
class TransportBinding:
    """Owner-confirmed canonical context; parent and child have distinct bindings."""
    inputs: ResearchInputBindings
    work_id: UUID
    epoch: int
    authority_digest: str
    plan_digest: str
    geo: str
    timeframe: str
    sources: tuple[SourceGrant, ...]
    queries: tuple[str, ...]
    confirmation_ref: str

    def __post_init__(self):
        if type(self.inputs) is not ResearchInputBindings or self.inputs.brief_digest is None or self.inputs.frame_digest is None:
            raise ValueError("Exact canonical frame required.")
        _uuid(self.work_id)
        _integer(self.epoch, 1)
        _digest(self.authority_digest)
        _digest(self.plan_digest)
        if type(self.geo) is not str or type(self.timeframe) is not str:
            raise ValueError("Exact checked plan region/window required.")
        _plan_value(self.geo, GeoCode)
        _plan_value(self.timeframe, Timeframe)
        if (type(self.sources) is not tuple or not self.sources
                or any(type(s) is not SourceGrant or s.paid or s.plan_digest != self.plan_digest for s in self.sources)):
            raise ValueError("Exact unpaid source plan bindings required.")
        if type(self.queries) is not tuple or not self.queries or any(type(q) is not str for q in self.queries):
            raise ValueError("Exact query scope required.")
        if type(self.confirmation_ref) is not str or not self.confirmation_ref:
            raise ValueError("Owner confirmation reference required.")


class RunCallBudget:
    """Shared live-run accounting; no refund or recovery/reset inference on uncertain calls."""

    def __init__(self, bounds, *, admit_fresh_run, clock=None):
        if type(bounds) is not RunBounds:
            raise ValueError("Exact run bounds required.")
        # Host callback must attest fresh run accounting, not merely owner scope approval.
        if not callable(admit_fresh_run) or admit_fresh_run(bounds.run_id, digest(bounds)) is not True:
            raise FollowUpExecutionBoundaryError()
        self.bounds = bounds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = Lock()
        self._used = {"search": 0, "other": 0}
        self._closed = False

    def close(self):
        """Refuse further calls; host separately owns retention expiry handling/deletion."""
        with self._lock:
            self._closed = True

    def current(self):
        now = self.clock()
        return not self._closed and self.bounds.started_at <= now < self.bounds.deadline and now < self.bounds.retention_until

    def charge(self, bucket):
        with self._lock:
            limit = self.bounds.search_calls if bucket == "search" else self.bounds.other_calls
            if not self.current() or self._used[bucket] >= limit:
                raise FollowUpExecutionBoundaryError()
            self._used[bucket] += 1


class HostProviderBridge:
    """Compose independent host leases with owner-bound scope and one shared run budget."""

    def __init__(self, host_verifier, budget, *, selected_parent_id):
        self._host = host_verifier
        self.budget = budget
        _uuid(selected_parent_id)
        self.selected_parent_id = selected_parent_id
        self._bindings = {}
        self._active = ContextVar("ignis_private_provider_binding", default=None)

    def verify_owner(self, reference, content_digest):
        callback = getattr(self._host, "verify_owner", None)
        return callable(callback) and callback(reference, content_digest) is True

    def register(self, binding):
        """Registration requires external confirmation; it is not itself approval."""
        if type(binding) is not TransportBinding or binding.inputs.mission_id != self.selected_parent_id:
            raise FollowUpExecutionBoundaryError()
        if not set(binding.queries) <= set(self.budget.bounds.queries):
            raise FollowUpExecutionBoundaryError()
        if not self.verify_owner(binding.confirmation_ref, digest((binding, self.budget.bounds))):
            raise FollowUpExecutionBoundaryError()
        old = self._bindings.get(binding.authority_digest)
        if old is not None and old != binding:
            raise FollowUpExecutionBoundaryError()
        self._bindings[binding.authority_digest] = binding

    def _binding(self, authority, plan=None):
        if type(authority) is not WorkAuthority:
            raise FollowUpExecutionBoundaryError()
        binding = self._bindings.get(authority.digest)
        work = authority.work
        if (binding is None or binding.inputs != work.inputs or binding.work_id != work.work_id
                or binding.epoch != work.research_epoch or binding.queries != work.requested_scope.queries
                or binding.sources != authority.sources
                or any(source.plan_digest != binding.plan_digest for source in authority.sources)
                or (plan is not None and (plan.digest != binding.plan_digest
                    or plan.geo != binding.geo or plan.timeframe != binding.timeframe))):
            raise FollowUpExecutionBoundaryError()
        return binding

    def _check(self, lease, binding):
        proof = lease.proof
        now = self.budget.clock()
        if (type(proof) is not CapabilityProof or proof.envelope_digest != binding.authority_digest
                or proof.sources != binding.sources
                or not proof.allowed or proof.cancel_requested or proof.stop_reached
                or not proof.checked_at <= now < proof.fresh_until or lease.is_current() is not True
                or not self.budget.current() or self._bindings.get(binding.authority_digest) != binding
                or not self.verify_owner(binding.confirmation_ref, digest((binding, self.budget.bounds)))):
            raise FollowUpExecutionBoundaryError()

    @asynccontextmanager
    async def hold_current(self, authority):
        binding = self._binding(authority)
        async with self._host.hold_current(authority) as lease:
            self._check(lease, binding)
            yield _Lease(self, lease, binding, execution=False)

    @asynccontextmanager
    async def hold_execution(self, authority, plan):
        binding = self._binding(authority, plan)
        provider = getattr(self._host, "hold_execution", None)
        if not callable(provider):
            raise FollowUpExecutionBoundaryError()
        async with provider(authority, plan) as lease:
            self._check(lease, binding)
            yield _Lease(self, lease, binding, execution=True)

    @asynccontextmanager
    async def hold_parent_transport(self, binding, lease):
        """Host supplies its separately held parent execution lease, never child permission."""
        self._check(lease, binding)
        async with lease.async_guard():
            self._check(lease, binding)
            alive = [True]
            token = self._active.set((lease, binding, alive))
            try:
                yield
            finally:
                alive[0] = False
                self._active.reset(token)

    def transport_context(self):
        context = self._active.get()
        if context is None or not context[2][0]:
            raise FollowUpExecutionBoundaryError()
        self._check(context[0], context[1])
        return context[:2]


class _Lease:
    def __init__(self, bridge, lease, binding, *, execution):
        self._bridge, self._lease, self._binding, self._execution = bridge, lease, binding, execution
        self.proof = lease.proof

    def is_current(self):
        try:
            self._bridge._check(self._lease, self._binding)
            return True
        except FollowUpExecutionBoundaryError:
            return False

    @contextmanager
    def guard(self):
        with self._lease.guard():
            self._bridge._check(self._lease, self._binding)
            yield

    @asynccontextmanager
    async def async_guard(self):
        async with self._lease.async_guard():
            self._bridge._check(self._lease, self._binding)
            alive = [True]
            token = self._bridge._active.set((self._lease, self._binding, alive)) if self._execution else None
            try:
                yield
            finally:
                alive[0] = False
                if token is not None:
                    self._bridge._active.reset(token)


class _GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, plugin):
        self._plugin = plugin

    async def handle_async_request(self, request):
        plugin = self._plugin
        _, binding = plugin._context()
        search = request.url.path.endswith("/search")
        if request.url.host != "www.googleapis.com" or request.url.path not in {"/youtube/v3/search", "/youtube/v3/videos"}:
            raise FollowUpExecutionBoundaryError()
        if search and (request.url.params.get("q") not in binding.queries
                       or int(request.url.params.get("maxResults", "0")) > plugin._bridge.budget.bounds.video_limit):
            raise FollowUpExecutionBoundaryError()
        geo = _plan_value(binding.geo, GeoCode)
        if search and (request.url.params.get("regionCode") != plugin._geo_to_region_code(geo)
                       or request.url.params.get("relevanceLanguage") != plugin._geo_to_relevance_language(geo)
                       or request.url.params.get("publishedAfter") !=
                          plugin._timeframe_to_published_after(_plan_value(binding.timeframe, Timeframe))[0]):
            raise FollowUpExecutionBoundaryError()
        plugin._bridge.budget.charge("search" if search else "other")
        # No await or provider request occurs between the final guard and credential lookup.
        plugin._context()
        try:
            key = plugin._resolve_credential()
            if type(key) is not str or not key:
                raise ValueError
        except Exception:
            raise FollowUpExecutionBoundaryError() from None
        # httpx logs and attaches the outer request after this method returns. Keep
        # the credential on a separate transport request and scrub that request too.
        safe_url = request.url
        private_request = httpx.Request(request.method, safe_url.copy_set_param("key", key),
            headers=request.headers, stream=request.stream, extensions=request.extensions)
        lease, _ = plugin._context()
        remaining = (min(plugin._bridge.budget.bounds.deadline,
                         plugin._bridge.budget.bounds.retention_until,
                         lease.proof.fresh_until) - plugin._bridge.budget.clock()).total_seconds()
        response = None
        try:
            if remaining <= 0:
                raise FollowUpExecutionBoundaryError()
            # timeout cancels this owned await and waits for its cancellation cleanup;
            # attempts remain charged even when the provider outcome is uncertain.
            async with asyncio.timeout(remaining):
                response = await plugin._transport.handle_async_request(private_request)
                response.request = request
                # Real transports return headers and an unread async stream. Drain
                # inside the same authority timeout; outer httpx then sees safe,
                # already-loaded content rather than reading after guard release.
                await response.aread()
                plugin._context()
            return response
        except Exception:
            # Provider exceptions may include secret-bearing URLs; expose only safe type.
            raise FollowUpExecutionBoundaryError() from None
        finally:
            private_request.url = safe_url
            if response is not None:
                try:
                    await response.aclose()
                except Exception:
                    raise FollowUpExecutionBoundaryError() from None


class HostBoundYouTubePlugin(YouTubeDataPlugin):
    """Explicit host opt-in; no live key resolution, transport creation or activation defaults."""

    def __init__(self, *, bridge, resolve_credential, transport, quota_manager):
        super().__init__(api_key="host-deferred", quota_manager=quota_manager)
        self._bridge = bridge
        self._resolve_credential = resolve_credential
        self._transport = transport
        self._private_caches = {}

    def _query_cache(self):
        _, binding = self._context()
        storage = getattr(self._bridge.budget, "storage", None)
        if storage is not None:
            return storage.cache(self._bridge.budget.bounds, digest(binding))
        return self._private_caches.setdefault(digest(binding), {})

    def _client(self, **kwargs):
        return httpx.AsyncClient(transport=_GuardedTransport(self), **kwargs)

    def _window_clock(self):
        self._context()
        return self._bridge.budget.bounds.started_at

    def _context(self):
        context = self._bridge.transport_context()
        if not any((source.source, source.platform, source.tier, source.connector_revision) ==
                   (self.plugin_id, self.platform.value, self.http_authority, self.connector_revision)
                   for source in context[1].sources):
            raise FollowUpExecutionBoundaryError()
        return context

    async def _reserve(self, *args, **kwargs):
        self._context()
        await super()._reserve(*args, **kwargs)

    async def search_signals(self, keywords, geo=None, timeframe=None, limit=20,
                             custom_timeframe=None, attestation=None, trigger=None):
        from ignis.domain.value_objects import IngressTrigger
        _, binding = self._context()
        expected_geo = _plan_value(binding.geo, GeoCode)
        expected_window = _plan_value(binding.timeframe, Timeframe)
        if (tuple(keywords) != binding.queries
                or (geo is not None and _plan_value(geo, GeoCode) != expected_geo)
                or (timeframe is not None and _plan_value(timeframe, Timeframe) != expected_window)
                or (custom_timeframe is not None and _plan_value(custom_timeframe, Timeframe) != expected_window)):
            raise FollowUpExecutionBoundaryError()
        return await super().search_signals(keywords, expected_geo, expected_window,
            min(limit, self._bridge.budget.bounds.video_limit), None, attestation,
            trigger or IngressTrigger.REQUESTED)

    async def fetch_signals(self, *args, **kwargs):
        raise FollowUpExecutionBoundaryError()
