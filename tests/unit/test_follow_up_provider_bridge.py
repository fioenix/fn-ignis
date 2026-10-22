"""Private opt-in provider boundaries; all HTTP responses and credentials are synthetic."""

import httpx
import pytest
import asyncio
from contextlib import asynccontextmanager, contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ignis.domain.follow_up_admission import CapabilityProof, SourceGrant, WorkAuthority, digest
from ignis.domain.research_work import ResearchInputBindings
from ignis.infrastructure.follow_up_provider_bridge import (
    HostBoundYouTubePlugin, HostProviderBridge, RunBounds, RunCallBudget, TransportBinding,
)

from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin


class Quota:
    def __init__(self):
        self.calls = 0

    async def reserve(self, *args, **kwargs):
        self.calls += 1


@pytest.mark.asyncio
async def test_private_client_boundary_caps_readiness_before_fifth_request(monkeypatch):
    """Ignoring the private client boundary permits a fifth real provider request."""
    calls = []
    original_client = httpx.AsyncClient

    async def response(request):
        calls.append(request)
        return httpx.Response(200, json={"items": []})

    class BoundedPlugin(YouTubeDataPlugin):
        def _client(self, **kwargs):
            async def guarded(request):
                if len(calls) >= 4:
                    raise ValueError("Approved call allowance exhausted.")
                return await response(request)
            return original_client(transport=httpx.MockTransport(guarded), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(response), **kwargs))
    plugin = BoundedPlugin(api_key="synthetic-only", quota_manager=Quota())
    results = [await plugin.is_healthy() for _ in range(5)]
    assert len(calls) == 4
    assert results == [True, True, True, True, False]


class Host:
    def __init__(self):
        self.confirmations = {}
        self.revoked = False

    def verify_owner(self, reference, content_digest):
        return self.confirmations.get(reference) == content_digest


class Lease:
    def __init__(self, proof, host):
        self.proof, self.host = proof, host
        self.tokens = 0

    def is_current(self):
        return not self.host.revoked

    @contextmanager
    def guard(self):
        yield

    @asynccontextmanager
    async def async_guard(self):
        self.tokens += 1
        try:
            yield
        finally:
            self.tokens -= 1


def setup_bridge(*, duration=timedelta(minutes=15)):
    now = datetime.now(timezone.utc)
    bounds = RunBounds(run_id=uuid4(), started_at=now, deadline=now + duration,
        retention_until=now + timedelta(days=7), queries=("n8n Việt Nam", "n8n tự động hóa"),
        video_limit=5, search_calls=2, other_calls=4)
    host = Host()
    fresh = {bounds.run_id}
    def admit(run_id, content_digest):
        if run_id not in fresh or content_digest != digest(bounds):
            return False
        fresh.remove(run_id)
        return True
    clock = [now]
    budget = RunCallBudget(bounds, admit_fresh_run=admit, clock=lambda: clock[0])
    selected = uuid4()
    bridge = HostProviderBridge(host, budget, selected_parent_id=selected)
    sources = (SourceGrant(source="youtube", platform="youtube", tier="official_api", paid=False,
        plan_digest="a" * 64, connector_revision="unversioned", capability_id="private-host",
        capability_epoch=1),)
    inputs = ResearchInputBindings(mission_id=selected, manifest_digest="b" * 64,
        brief_digest="c" * 64, frame_digest="d" * 64, observation_ids=(), finding_revisions=())
    bindings, leases = [], []
    for index, query in enumerate(bounds.queries):
        binding = TransportBinding(inputs=inputs, work_id=uuid4(), epoch=1,
            authority_digest=str(index + 1) * 64, plan_digest="a" * 64, sources=sources,
            geo='GeoCode.VN', timeframe='Timeframe.LAST_30D',
            queries=(query,), confirmation_ref=f"owner-{index}")
        host.confirmations[binding.confirmation_ref] = digest((binding, bounds))
        bridge.register(binding)
        proof = CapabilityProof(envelope_digest=binding.authority_digest, process_id="synthetic-process",
            policy_generation=1, operational_generation=1, checked_at=now,
            fresh_until=now + duration, sources=sources, quota_unit="calls",
            cost_unit="paid", quota_required=1, cost_required=0, resources=(("youtube", 1),),
            allowed=True, stop_reached=False, cancel_requested=False)
        bindings.append(binding)
        leases.append(Lease(proof, host))
    calls, credentials = [], []
    async def response(request):
        calls.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith('/search'):
            return httpx.Response(200, json={"items": [
                {"id": {"videoId": f"video-{i}"}} for i in range(5)]})
        if request.url.params.get('id'):
            return httpx.Response(200, json={"items": [{"id": f"video-{i}",
                "snippet": {"title": f"Synthetic n8n tự động hóa ở Việt Nam video {i}", "publishedAt": now.isoformat()},
                "statistics": {"viewCount": "10", "likeCount": "1", "commentCount": "0"}}
                for i in range(5)]})
        return httpx.Response(200, json={"items": []})
    def resolve():
        credentials.append("lookup")
        return "synthetic-not-a-live-key"
    quota = Quota()
    plugin = HostBoundYouTubePlugin(bridge=bridge, resolve_credential=resolve,
        transport=httpx.MockTransport(response), quota_manager=quota)
    return bridge, host, bindings, leases, plugin, calls, credentials, quota, clock, admit


@pytest.mark.asyncio
async def test_shared_parent_child_calls_include_health_metrics_and_retry():
    """Removing aggregate accounting or the effective sampling cap reaches extra HTTP calls."""
    bridge, _, bindings, leases, plugin, calls, credentials, _, _, _ = setup_bridge()
    for binding, lease in zip(bindings, leases):
        async with bridge.hold_parent_transport(binding, lease):
            assert await plugin.is_healthy() is True
            result = await plugin.search_signals(list(binding.queries), limit=20)
            assert len(result) == 5
    assert [path.rsplit('/', 1)[-1] for path, _ in calls] == [
        'videos', 'search', 'videos', 'videos', 'search', 'videos']
    searches = [params for path, params in calls if path.endswith('/search')]
    assert [params['q'] for params in searches] == ['n8n Việt Nam', 'n8n tự động hóa']
    assert [params['maxResults'] for params in searches] == ['5', '5']
    assert [params['regionCode'] for params in searches] == ['VN', 'VN']
    assert [params['relevanceLanguage'] for params in searches] == ['vi', 'vi']
    expected_after = (bridge.budget.bounds.started_at - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
    assert [params['publishedAfter'] for params in searches] == [expected_after, expected_after]
    async with bridge.hold_parent_transport(bindings[1], leases[1]):
        assert await plugin.is_healthy() is False
        await plugin.search_signals(list(bindings[1].queries))
    assert len(calls) == len(credentials) == 6
    assert all(lease.tokens == 0 for lease in leases)


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ('missing', 'revoked', 'expired', 'stale', 'cancel', 'scope', 'owner', 'source'))
async def test_invalid_context_never_resolves_credential_or_reserves_quota(failure):
    """A context, owner, source or generation bypass would reach credential/HTTP ingress."""
    bridge, host, bindings, leases, plugin, calls, credentials, quota, clock, _ = setup_bridge()
    binding, lease = bindings[0], leases[0]
    if failure == 'missing':
        assert await plugin.is_healthy() is False
    else:
        if failure == 'revoked':
            host.revoked = True
        elif failure == 'expired':
            clock[0] = bridge.budget.bounds.deadline
        elif failure == 'stale':
            lease.proof = replace(lease.proof, envelope_digest='e' * 64)
        elif failure == 'cancel':
            lease.proof = replace(lease.proof, cancel_requested=True)
        elif failure == 'scope':
            binding = replace(binding, epoch=2)
        elif failure == 'owner':
            host.confirmations.clear()
        elif failure == 'source':
            lease.proof = replace(lease.proof, sources=())
        with pytest.raises(Exception, match='SESSION_AUTHORITY_REQUIRED'):
            async with bridge.hold_parent_transport(binding, lease):
                await plugin.is_healthy()
    assert calls == credentials == []
    assert quota.calls == lease.tokens == 0


@pytest.mark.asyncio
async def test_owned_context_cancellation_and_late_task_cannot_reuse_lease():
    """Context inheritance must not permit an orphan task to use a released guard."""
    bridge, _, bindings, leases, plugin, calls, credentials, _, _, _ = setup_bridge()
    entered, release = asyncio.Event(), asyncio.Event()
    async def child():
        await release.wait()
        return await plugin.is_healthy()
    late = None
    async def owner():
        nonlocal late
        async with bridge.hold_parent_transport(bindings[0], leases[0]):
            late = asyncio.create_task(child())
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(owner())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        release.set()
        assert await asyncio.wait_for(late, 1) is False
    finally:
        release.set()
        for pending in (task, late):
            if pending is not None and not pending.done():
                pending.cancel()
        await asyncio.gather(*(t for t in (task, late) if t is not None), return_exceptions=True)
    assert calls == credentials == []
    assert leases[0].tokens == 0


def test_reopen_cannot_reset_unknown_budget_without_fresh_host_accounting():
    bridge, _, _, _, _, _, _, _, _, admit = setup_bridge()
    with pytest.raises(Exception, match='SESSION_AUTHORITY_REQUIRED'):
        RunCallBudget(bridge.budget.bounds, admit_fresh_run=admit)


@pytest.mark.asyncio
async def test_actual_executor_guard_uses_composed_host_proof_without_minting():
    """The bridge must be callable by the existing executor's execution guard."""
    from ignis.application.use_cases.execute_mission_follow_up import ExecuteMissionFollowUpUseCase
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionPlan
    from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope
    bridge, host, bindings, leases, plugin, calls, credentials, _, _, _ = setup_bridge()
    binding, lease = bindings[1], leases[1]
    plan = FollowUpExecutionPlan(binding.queries, (("youtube", "youtube", "official_api", "unversioned",
        "ignis.infrastructure.follow_up_provider_bridge.HostBoundYouTubePlugin.search_signals",
        20, "platform_default", False),), (("youtube", 1),), binding.geo, binding.timeframe)
    sources = tuple(replace(source, plan_digest=plan.digest) for source in binding.sources)
    scope = FollowUpScope(queries=binding.queries, sources=frozenset({'youtube'}))
    work = FollowUpWork(work_id=binding.work_id, parent_work_id=uuid4(), assignment_id=uuid4(),
        gap_id=uuid4(), inputs=binding.inputs, research_epoch=1, assignment_version=1,
        work_version=1, brief_revision_id=uuid4(), approved_scope=scope, requested_scope=scope,
        authority_deadline=bridge.budget.bounds.deadline)
    authority = WorkAuthority(work=work, budget_id=uuid4(), binding_id=uuid4(), quota_unit='calls',
        cost_unit='paid', quota=1, cost=0, quota_ceiling=2, cost_ceiling=0,
        resources=(("youtube", 1),), sources=sources, confirmation_ref=binding.confirmation_ref)
    binding = replace(binding, authority_digest=authority.digest, plan_digest=plan.digest, sources=sources)
    host.confirmations[binding.confirmation_ref] = digest((binding, bridge.budget.bounds))
    bridge.register(binding)
    lease.proof = replace(lease.proof, envelope_digest=authority.digest, sources=sources)
    @asynccontextmanager
    async def held(request, checked_plan):
        assert request == authority and checked_plan == plan
        yield lease
    host.hold_execution = held
    service = ExecuteMissionFollowUpUseCase(None, None, selected_parent_id=binding.inputs.mission_id)
    async with service._execution_guard(bridge.hold_execution, authority, plan) as composed:
        assert composed.proof is lease.proof
        assert lease.tokens == 1
        assert await plugin.is_healthy() is True
    assert lease.tokens == 0
    assert len(calls) == len(credentials) == 1
    with pytest.raises(Exception, match='SESSION_AUTHORITY_REQUIRED'):
        async with bridge.hold_execution(authority, replace(plan, timeframe='90d')):
            pytest.fail('Mismatched plan acquired execution capability.')
    assert len(calls) == len(credentials) == 1


@pytest.mark.asyncio
async def test_held_foreign_plugin_proof_cannot_authorize_youtube_ingress():
    bridge, host, bindings, leases, plugin, calls, credentials, quota, _, _ = setup_bridge()
    foreign = replace(bindings[0].sources[0], source='foreign')
    binding = replace(bindings[0], authority_digest='f' * 64, sources=(foreign,))
    host.confirmations[binding.confirmation_ref] = digest((binding, bridge.budget.bounds))
    bridge.register(binding)
    lease = leases[0]
    lease.proof = replace(lease.proof, envelope_digest=binding.authority_digest, sources=(foreign,))
    async with bridge.hold_parent_transport(binding, lease):
        assert await plugin.is_healthy() is False
    assert calls == credentials == []
    assert quota.calls == 0


@pytest.mark.asyncio
async def test_successful_guarded_request_keeps_key_out_of_httpx_logs_and_response(caplog):
    """Mutating the outer HTTP request leaks injected credentials after a successful call."""
    bridge, _, bindings, leases, plugin, _, _, _, _, _ = setup_bridge()
    sentinel = 'SYNTHETIC-KEY-DO-NOT-LOG-731'
    plugin._resolve_credential = lambda: sentinel
    underlying = []
    async def response(request):
        underlying.append(request.url.params['key'] == sentinel)
        return httpx.Response(200, json={'items': []}, request=request)
    plugin._transport = httpx.MockTransport(response)
    caplog.set_level('INFO', logger='httpx')
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        async with plugin._client() as client:
            result = await client.get(plugin.BASE_API_URL, params={'key': 'host-deferred'})
    assert underlying == [True]
    assert sentinel not in caplog.text
    assert result.request.url.params['key'] == 'host-deferred'
    assert sentinel not in repr(result.request.url)


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ('run_deadline', 'lease_deadline', 'revoke'))
async def test_inflight_response_cannot_become_success_after_authority_changes(change):
    """Authority must be checked after the actual provider await, before parsing success."""
    bridge, host, bindings, leases, plugin, _, credentials, _, clock, _ = setup_bridge()
    async def delayed(request):
        await asyncio.sleep(0)
        if change == 'revoke':
            host.revoked = True
        elif change == 'lease_deadline':
            leases[0].proof = replace(leases[0].proof, fresh_until=clock[0] + timedelta(microseconds=1))
            clock[0] += timedelta(microseconds=1)
        else:
            clock[0] = bridge.budget.bounds.deadline
        return httpx.Response(200, json={'items': []})
    plugin._transport = httpx.MockTransport(delayed)
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        result = await plugin.is_healthy()
    assert result is False
    assert credentials == ['lookup']
    assert bridge.budget._used == {'search': 0, 'other': 1}
    assert leases[0].tokens == 0


@pytest.mark.asyncio
async def test_remaining_authority_timeout_cancels_and_settles_owned_transport():
    """A transport ignoring httpx timeouts cannot outlive the remaining run allowance."""
    bridge, _, bindings, leases, plugin, _, credentials, _, _, _ = setup_bridge(
        duration=timedelta(milliseconds=30))
    entered, settled = asyncio.Event(), asyncio.Event()
    received = []
    async def blocked(request):
        received.append(request)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            settled.set()
    plugin._transport = httpx.MockTransport(blocked)
    task = None
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        try:
            task = asyncio.create_task(plugin.is_healthy())
            await asyncio.wait_for(entered.wait(), 1)
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done, 'Remaining authority did not bound the actual transport await.'
            assert task.result() is False
            assert settled.is_set()
        finally:
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
    assert credentials == ['lookup']
    assert bridge.budget._used == {'search': 0, 'other': 1}
    assert leases[0].tokens == 0
    assert received[0].url.params['key'] == 'host-deferred'


@pytest.mark.asyncio
async def test_guarded_provider_error_is_sanitized_without_refund(caplog):
    bridge, _, bindings, leases, plugin, _, _, _, _, _ = setup_bridge()
    sentinel = 'SYNTHETIC-ERROR-KEY-DO-NOT-LOG-519'
    plugin._resolve_credential = lambda: sentinel
    async def failing(request):
        raise httpx.ConnectError(str(request.url), request=request)
    plugin._transport = httpx.MockTransport(failing)
    caplog.set_level('INFO')
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        async with plugin._client() as client:
            with pytest.raises(Exception) as error:
                await client.get(plugin.BASE_API_URL, params={'key': 'host-deferred'})
    assert str(error.value) == 'SESSION_AUTHORITY_REQUIRED'
    assert sentinel not in caplog.text + repr(error.value)
    assert bridge.budget._used == {'search': 0, 'other': 1}
    assert leases[0].tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('change', ('current', 'run_deadline', 'lease_deadline', 'revoke'))
async def test_streamed_body_cannot_escape_authority_guard(change):
    """Headers are insufficient: the actual async body must remain in the held guard."""
    bridge, host, bindings, leases, plugin, _, credentials, _, clock, _ = setup_bridge()
    closed = []
    class DelayedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0)
            if change == 'revoke':
                host.revoked = True
            elif change == 'lease_deadline':
                leases[0].proof = replace(leases[0].proof, fresh_until=clock[0] + timedelta(microseconds=1))
                clock[0] += timedelta(microseconds=1)
            elif change == 'run_deadline':
                clock[0] = bridge.budget.bounds.deadline
            yield b'{"items": []}'
        async def aclose(self):
            closed.append('closed')
    async def headers(request):
        return httpx.Response(200, stream=DelayedBody(), request=request)
    plugin._transport = httpx.MockTransport(headers)
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        assert await plugin.is_healthy() is (change == 'current')
    assert closed == ['closed']
    assert credentials == ['lookup']
    assert bridge.budget._used == {'search': 0, 'other': 1}
    assert leases[0].tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('stop', ('deadline', 'caller_cancel'))
async def test_streamed_body_timeout_or_cancellation_closes_owned_response(stop):
    bridge, _, bindings, leases, plugin, _, credentials, _, _, _ = setup_bridge(
        duration=timedelta(milliseconds=30) if stop == 'deadline' else timedelta(minutes=15))
    entered, settled, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    received = []
    class BlockedBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            try:
                await asyncio.Event().wait()
                yield b'{"items": []}'
            finally:
                settled.set()
        async def aclose(self):
            closed.set()
    async def headers(request):
        received.append(request)
        return httpx.Response(200, stream=BlockedBody(), request=request)
    plugin._transport = httpx.MockTransport(headers)
    task = None
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        try:
            task = asyncio.create_task(plugin.is_healthy())
            await asyncio.wait_for(entered.wait(), 1)
            if stop == 'caller_cancel':
                task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.3)
            assert task in done, 'Remaining authority did not bound actual response body consumption.'
            if stop == 'caller_cancel':
                with pytest.raises(asyncio.CancelledError):
                    task.result()
            else:
                assert task.result() is False
            assert settled.is_set() and closed.is_set()
        finally:
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
    assert received[0].url.params['key'] == 'host-deferred'
    assert credentials == ['lookup']
    assert bridge.budget._used == {'search': 0, 'other': 1}
    assert leases[0].tokens == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('argument', ('geo', 'timeframe', 'custom_timeframe'))
async def test_approved_query_with_changed_provider_arguments_never_crosses_ingress(argument):
    """A correct query does not authorize an alternate region or extended evidence window."""
    from ignis.domain.value_objects import GeoCode, Timeframe
    bridge, _, bindings, leases, plugin, calls, credentials, quota, _, _ = setup_bridge()
    kwargs = {'geo': GeoCode.VN, 'timeframe': Timeframe.LAST_30D}
    kwargs[argument] = GeoCode.US if argument == 'geo' else Timeframe.LAST_90D
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        try:
            await plugin.search_signals(list(bindings[0].queries), **kwargs)
        except Exception as error:
            assert str(error) == 'SESSION_AUTHORITY_REQUIRED'
    assert credentials == calls == []
    assert quota.calls == 0
    assert bridge.budget._used == {'search': 0, 'other': 0}


@pytest.mark.asyncio
@pytest.mark.parametrize('parameter', ('regionCode', 'relevanceLanguage', 'publishedAfter',
    'missing_region', 'missing_language', 'missing_window', 'malformed_window'))
async def test_changed_physical_search_scope_is_refused_before_credential(parameter):
    bridge, _, bindings, leases, plugin, calls, credentials, _, _, _ = setup_bridge()
    params = {'q': bindings[0].queries[0], 'maxResults': '5', 'regionCode': 'VN',
        'relevanceLanguage': 'vi', 'publishedAfter':
        (bridge.budget.bounds.started_at - timedelta(days=30)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'key': 'host-deferred'}
    if parameter.startswith('missing_'):
        del params[{'missing_region': 'regionCode', 'missing_language': 'relevanceLanguage',
                    'missing_window': 'publishedAfter'}[parameter]]
    elif parameter == 'malformed_window':
        params['publishedAfter'] = 'not-a-timestamp'
    else:
        params[parameter] = {'regionCode': 'US', 'relevanceLanguage': 'en',
            'publishedAfter': '2000-01-01T00:00:00Z'}[parameter]
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        async with plugin._client() as client:
            try:
                await client.get(plugin.SEARCH_API_URL, params=params)
            except Exception as error:
                assert str(error) == 'SESSION_AUTHORITY_REQUIRED'
    assert calls == credentials == []
    assert bridge.budget._used == {'search': 0, 'other': 0}


@pytest.mark.asyncio
async def test_host_bound_cache_cannot_borrow_unrelated_global_payload(monkeypatch):
    """An approved private run must not read or overwrite another collector's cache."""
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    from ignis.infrastructure.connectors.youtube import youtube_plugin
    bridge, _, bindings, leases, plugin, calls, credentials, _, _, _ = setup_bridge()
    foreign = TrendSignal(platform=PlatformType.YOUTUBE, raw_title='Unrelated synthetic cache payload',
        metadata={'video_id': 'unrelated-cache'})
    global_cache = {'n8n việt nam|VN|30d|5': [foreign]}
    monkeypatch.setattr(youtube_plugin, '_YOUTUBE_QUERY_CACHE', global_cache)
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        result = await plugin.search_signals(list(bindings[0].queries))
    assert [path.rsplit('/', 1)[-1] for path, _ in calls] == ['search', 'videos']
    assert len(result) == 5
    assert all(signal.raw_title != foreign.raw_title for signal in result)
    assert global_cache == {'n8n việt nam|VN|30d|5': [foreign]}
    assert credentials == ['lookup', 'lookup']


def durable_budget(tmp_path, bounds, clock, *, create=True):
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage, DurableRunCallBudget
    storage = PrivateRunStorage(tmp_path / 'private', authorize=lambda *_: True, create=create)
    return DurableRunCallBudget(bounds, storage=storage, register=create, clock=lambda: clock[0])


@pytest.mark.asyncio
async def test_durable_reopen_cannot_reset_shared_provider_attempts(tmp_path):
    bridge, _, bindings, leases, plugin, calls, credentials, _, clock, _ = setup_bridge()
    budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    bridge.budget = budget
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        await plugin.search_signals(list(bindings[0].queries))
    assert budget._used == {'search': 1, 'other': 1}
    bridge.budget = durable_budget(tmp_path, budget.bounds, clock, create=False)
    async with bridge.hold_parent_transport(bindings[1], leases[1]):
        await plugin.search_signals(list(bindings[1].queries))
        await plugin.is_healthy()
        await plugin.is_healthy()
        assert await plugin.is_healthy() is False
    assert bridge.budget._used == {'search': 2, 'other': 4}
    assert len(calls) == len(credentials) == 6
    assert all(params.get('maxResults', '5') in ('1', '5') for _, params in calls)


@pytest.mark.asyncio
async def test_durable_failed_attempt_is_encumbered_before_credential_resolution(tmp_path):
    bridge, _, bindings, leases, plugin, calls, credentials, _, clock, _ = setup_bridge()
    bridge.budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    def failed_credential():
        assert bridge.budget._used == {'search': 1, 'other': 0}
        raise RuntimeError('Synthetic resolution failure')
    plugin._resolve_credential = failed_credential
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        assert await plugin.search_signals(list(bindings[0].queries)) == []
    reopened = durable_budget(tmp_path, bridge.budget.bounds, clock, create=False)
    assert reopened._used == {'search': 1, 'other': 0}
    assert calls == credentials == []


def test_durable_reopen_missing_changed_or_duplicate_registration_refuses(tmp_path):
    import sqlite3
    from ignis.infrastructure.follow_up_run_storage import DurableRunCallBudget
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    bridge, _, _, _, _, _, _, _, clock, _ = setup_bridge()
    bounds = bridge.budget.bounds
    with pytest.raises(FollowUpExecutionBoundaryError):
        durable_budget(tmp_path, bounds, clock, create=False)
    assert not (tmp_path / 'private').exists()
    budget = durable_budget(tmp_path, bounds, clock)
    budget.charge('search')
    with pytest.raises(FollowUpExecutionBoundaryError):
        DurableRunCallBudget(replace(bounds, search_calls=3), storage=budget.storage, clock=lambda: clock[0])
    with pytest.raises(FollowUpExecutionBoundaryError):
        DurableRunCallBudget(bounds, storage=budget.storage, register=True, clock=lambda: clock[0])
    assert budget._used == {'search': 1, 'other': 0}
    with sqlite3.connect(budget.storage.path) as connection:
        connection.execute('DELETE FROM runs')
    with pytest.raises(FollowUpExecutionBoundaryError):
        durable_budget(tmp_path, bounds, clock, create=False)
    with sqlite3.connect(budget.storage.path) as connection:
        assert connection.execute('SELECT COUNT(*) FROM runs').fetchone() == (0,)
    with pytest.raises(FollowUpExecutionBoundaryError):
        DurableRunCallBudget(bounds, storage=budget.storage, register=True, clock=lambda: clock[0])
    budget.storage.path.unlink()
    with pytest.raises(FollowUpExecutionBoundaryError):
        budget.storage.counts(bounds)
    assert not budget.storage.path.exists()


@pytest.mark.asyncio
async def test_host_purge_physically_removes_only_registered_private_payloads(tmp_path):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    bridge, _, bindings, leases, plugin, calls, _, _, clock, _ = setup_bridge()
    bridge.budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    bounds, storage = bridge.budget.bounds, bridge.budget.storage
    async with bridge.hold_parent_transport(bindings[0], leases[0]):
        result = await plugin.search_signals(list(bindings[0].queries))
        cache = plugin._query_cache()
        result[0].raw_title = 'SYNTHETIC_RETAINED_PAYLOAD_SENTINEL'
        cache['synthetic-isolated-key'] = result
    artifact = storage.write_artifact(bounds, b'SYNTHETIC_ARTIFACT_SENTINEL')
    unrelated = tmp_path / 'unrelated.payload'
    unrelated.write_bytes(b'Unrelated owner data')
    assert b'SYNTHETIC_RETAINED_PAYLOAD_SENTINEL' in storage.path.read_bytes()
    with pytest.raises(FollowUpExecutionBoundaryError):
        storage.purge(bounds, now=clock[0])
    assert artifact.exists()
    # Host-off expiry refuses execution but has not performed deletion.
    clock[0] = bounds.retention_until
    assert bridge.budget.current() is False
    assert artifact.exists()
    audit = storage.purge(bounds, now=clock[0])
    assert audit == (digest(bounds), clock[0].isoformat(), 2, 1)
    assert not artifact.exists()
    assert b'SYNTHETIC_RETAINED_PAYLOAD_SENTINEL' not in storage.path.read_bytes()
    assert b'SYNTHETIC_ARTIFACT_SENTINEL' not in storage.path.read_bytes()
    assert unrelated.read_bytes() == b'Unrelated owner data'
    assert storage.purge(bounds, now=clock[0]) == audit
    assert storage.counts(bounds) == {'search': 1, 'other': 1}
    with pytest.raises(FollowUpExecutionBoundaryError):
        durable_budget(tmp_path, bounds, clock, create=False)
    assert len(calls) == 2


def test_private_purge_refuses_replaced_artifact_and_preserves_other_run(tmp_path):
    from ignis.infrastructure.follow_up_run_storage import DurableRunCallBudget
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    bridge, _, _, _, _, _, _, _, clock, _ = setup_bridge()
    budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    other_bounds = replace(budget.bounds, run_id=uuid4())
    other = DurableRunCallBudget(other_bounds, storage=budget.storage, register=True, clock=lambda: clock[0])
    own_file = budget.storage.write_artifact(budget.bounds, b'Synthetic original')
    other_file = budget.storage.write_artifact(other_bounds, b'Synthetic other run')
    own_file.write_bytes(b'Replacement owner content')
    with pytest.raises(FollowUpExecutionBoundaryError):
        budget.storage.purge(budget.bounds, now=budget.bounds.retention_until)
    assert own_file.read_bytes() == b'Replacement owner content'
    assert other_file.read_bytes() == b'Synthetic other run'
    assert other.current() is True
    with pytest.raises(FollowUpExecutionBoundaryError):
        durable_budget(tmp_path, budget.bounds, clock, create=False)


@pytest.mark.parametrize('interrupt', [RuntimeError, KeyboardInterrupt], ids=['failed-commit', 'interrupted-commit'])
def test_artifact_enrollment_interruption_remains_purgeable_after_reopen(tmp_path, monkeypatch, interrupt):
    """Loss of the writing transaction cannot leave an unregistered owned payload."""
    from ignis.infrastructure.follow_up_run_storage import PrivateRunStorage
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    bridge, _, _, _, _, _, _, _, clock, _ = setup_bridge()
    budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    storage, bounds = budget.storage, budget.bounds
    original = storage._connection
    @contextmanager
    def fail_after_payload_before_commit():
        with original() as connection:
            yield connection
            if list(storage.root.glob('*.payload')):
                raise interrupt('Synthetic write-to-commit interruption')
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_connection', fail_after_payload_before_commit)
        with pytest.raises((FollowUpExecutionBoundaryError, KeyboardInterrupt)):
            storage.write_artifact(bounds, b'SYNTHETIC_INTERRUPTED_ARTIFACT')
    payloads = list(storage.root.glob('*.payload'))
    assert len(payloads) == 1
    assert payloads[0].read_bytes() == b'SYNTHETIC_INTERRUPTED_ARTIFACT'
    reopened = PrivateRunStorage(storage.root, authorize=lambda *_: True)
    audit = reopened.purge(bounds, now=bounds.retention_until)
    assert not payloads[0].exists()
    assert audit == (digest(bounds), bounds.retention_until.isoformat(), 0, 1)
    assert reopened.counts(bounds) == {'search': 0, 'other': 0}


def test_failed_initial_enrollment_creates_no_artifact_payload(tmp_path, monkeypatch):
    """Registration must commit before payload creation can begin."""
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionBoundaryError
    bridge, _, _, _, _, _, _, _, clock, _ = setup_bridge()
    budget = durable_budget(tmp_path, bridge.budget.bounds, clock)
    storage = budget.storage
    original = storage._connection
    @contextmanager
    def failed_commit():
        with original() as connection:
            yield connection
            raise RuntimeError('Synthetic initial enrollment commit failure')
    with monkeypatch.context() as patch:
        patch.setattr(storage, '_connection', failed_commit)
        with pytest.raises(FollowUpExecutionBoundaryError):
            storage.write_artifact(budget.bounds, b'SYNTHETIC_UNENROLLED_ARTIFACT')
    assert list(storage.root.glob('*.payload')) == []
    with original() as connection:
        assert connection.execute('SELECT COUNT(*) FROM artifacts').fetchone() == (0,)
