"""Socket contracts for T024's separate read-only listener (initial API RED).

The inert provider returns existing typed projections only. It isolates transport,
not real mission authorization, persistence, collectors or browser acceptance.
Missing future API failures precede HTTP assertions and prove no security control.
"""

import asyncio
import base64
import hashlib
import http.client
import importlib
import json
import logging
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID

import pytest

from ignis.application.ports.mission_relay_port import MissionRelayReadRequest
from ignis.domain.mission_relay import (
    MissionRelayCursor,
    MissionRelayInspection,
    MissionRelayReadFailure,
    MissionRelaySnapshot,
    RelayObservation,
    RelayReadReason,
    RelayReadStatus,
)
from ignis.domain.research_workspace import EvidenceRole, ResearchSurface


MISSION = UUID("11111111-2222-4333-8444-555555555555")
OTHER = UUID("22222222-3333-4444-8555-666666666666")
OBSERVATION = UUID("33333333-4444-4555-8666-777777777777")
SOURCE = UUID("44444444-5555-4666-8777-888888888888")
RUN_A = UUID("55555555-6666-4777-8888-999999999999")
RUN_B = UUID("66666666-7777-4888-8999-aaaaaaaaaaaa")
READ_AT = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
MODULE = "ignis.infrastructure.mission_relay"
LIMIT = 1_048_576
MARKER = "INERT_PRIVATE_T017_MARKER"


def _listener_type():
    try:
        module = importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise
        pytest.fail("T017 API RED: the separate internal listener is absent", pytrace=False)
    listener = getattr(module, "MissionRelayHTTP", None)
    assert callable(listener), "T017 API RED: the internal typed listener is absent"
    return listener


def _snapshot(request, title="Recorded public fixture"):
    row = RelayObservation(
        mission_id=request.mission_id, observation_id=OBSERVATION, source_id=SOURCE,
        title=title, excerpt=None, source_url=None, metric_value=None,
        growth_velocity=None, published_at=None, captured_at=None,
        evidence_role=EvidenceRole.ATTENTION_CONTEXT, direction=None,
    )
    return MissionRelaySnapshot(
        mission_id=request.mission_id, run_id=request.run_id,
        high_water=MissionRelayCursor(mission_id=request.mission_id, revision=0, ordinal=0),
        read_at=READ_AT, page_size=request.page_size,
        evidence=(row,), total_observations=1, source_count=1,
        surface=ResearchSurface.ATTENTION,
    )


class InertReadProvider:
    """Controlled slow/error projection boundary; it never authorizes real data."""

    def __init__(self, owner_loop):
        self.owner_loop = owner_loop
        self.calls = []
        self.authorizations = []
        self.admission_times = []
        self.cancellation_times = []
        self.entered = threading.Semaphore(0)
        self.cancelled = threading.Event()
        self.settled = threading.Event()
        self.release = asyncio.Event()
        self.cancel_release = asyncio.Event()
        self.block = False
        self.hold_cancellation = False
        self.title = "Recorded public fixture"
        self.error = False
        self.refusal = None

    async def authorize_view(self, mission_id: UUID, run_id: UUID | None) -> MissionRelayReadFailure | None:
        assert asyncio.get_running_loop() is self.owner_loop
        self.authorizations.append((mission_id, run_id))
        return self.refusal

    async def _read(self, operation, request, observation_id=None):
        assert asyncio.get_running_loop() is self.owner_loop
        assert type(request) is MissionRelayReadRequest
        self.admission_times.append(time.monotonic())
        self.calls.append((operation, request, observation_id))
        self.entered.release()
        try:
            if self.block:
                await self.release.wait()
            if self.error:
                raise RuntimeError(MARKER)
            snapshot = _snapshot(request, self.title)
            if operation == "inspection":
                return MissionRelayInspection(
                    mission_id=request.mission_id, run_id=request.run_id,
                    high_water=snapshot.high_water, read_at=snapshot.read_at,
                    observation=snapshot.evidence[0],
                )
            return snapshot
        except asyncio.CancelledError:
            self.cancellation_times.append(time.monotonic())
            self.cancelled.set()
            if self.hold_cancellation:
                await self.cancel_release.wait()
            raise
        finally:
            self.settled.set()

    async def snapshot(self, request: MissionRelayReadRequest) -> MissionRelaySnapshot | MissionRelayReadFailure:
        return await self._read("snapshot", request)

    async def inspect(
        self, request: MissionRelayReadRequest, observation_id: UUID,
    ) -> MissionRelayInspection | MissionRelayReadFailure:
        return await self._read("inspection", request, observation_id)


@pytest.fixture
def loop_owner():
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run():
        asyncio.set_event_loop(loop)
        loop.call_soon(ready.set)
        loop.run_forever()

    thread = threading.Thread(target=run, name="t017-owner-loop")
    thread.start()
    assert ready.wait(2)
    try:
        yield loop
    finally:
        async def settle():
            tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run_coroutine_threadsafe(settle(), loop).result(5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(2)
        assert not thread.is_alive(), "The test owner loop did not settle"
        loop.close()


@pytest.fixture
def factory(loop_owner):
    resources = []

    def create(provider=None):
        listener_type = _listener_type()
        provider = provider or InertReadProvider(loop_owner)
        relay = listener_type(provider=provider, owner_loop=loop_owner)
        resources.append((relay, provider))
        return relay, provider

    try:
        yield create
    finally:
        for relay, provider in resources:
            loop_owner.call_soon_threadsafe(provider.release.set)
            loop_owner.call_soon_threadsafe(provider.cancel_release.set)
            relay.close()
        for relay, _ in resources:
            assert _await(loop_owner, relay.wait_closed(timeout=5)), "Listener teardown did not settle"


def _await(loop, coroutine):
    return asyncio.run_coroutine_threadsafe(coroutine, loop).result(7)


def _open(loop, relay, *, mission_id=MISSION, run_id=None, expires_at=None):
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
    capability = _await(loop, relay.open_view(
        mission_id=mission_id, run_id=run_id, expires_at=expires_at,
    ))
    assert not isinstance(capability, (dict, MissionRelayReadFailure)), "Valid scope must yield a typed capability"
    return capability


@dataclass(frozen=True)
class WireResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes

    def header(self, name):
        values = [value for key, value in self.headers if key.lower() == name.lower()]
        assert len(values) <= 1, "Duplicate response security header"
        return values[0] if values else None

    def payload(self):
        assert len(self.body) <= LIMIT, "Response exceeded the byte bound"
        try:
            return json.loads(self.body.decode("utf-8", errors="strict"))
        except (UnicodeError, ValueError):
            pytest.fail("Response is not bounded valid UTF-8 JSON", pytrace=False)


def _http(capability, suffix="snapshot?page_size=100", *, method="GET", headers=(), body=None):
    destination = urlsplit(capability.url)
    connection = http.client.HTTPConnection("127.0.0.1", destination.port, timeout=5)
    try:
        connection.putrequest(method, destination.path + suffix, skip_host=True)
        if not any(name.lower() == "host" for name, _ in headers):
            connection.putheader("Host", f"127.0.0.1:{destination.port}")
        for name, value in headers:
            connection.putheader(name, value)
        connection.endheaders(body)
        response = connection.getresponse()
        return WireResponse(response.status, tuple(response.getheaders()), response.read(LIMIT + 1))
    finally:
        connection.close()


def _refusal(response, status, reason, *, unavailable=False):
    assert response.status == status, "Wrong protocol refusal status"
    assert response.payload() == {
        "schema_version": 1, "status": "UNAVAILABLE" if unavailable else "REFUSED",
        "reason_code": reason,
    }, "Refusal must contain only an allowlisted typed reason"


def _closed(capability):
    with socket.socket() as connection:
        connection.settimeout(1)
        return connection.connect_ex(("127.0.0.1", urlsplit(capability.url).port)) != 0


def test_listener_binds_only_exact_loopback_and_ephemeral_port(factory, loop_owner):
    """Catch wildcard/public or fixed-port binding even when loopback GET works."""
    relay, _ = factory()
    cap = _open(loop_owner, relay)
    destination = urlsplit(cap.url)
    assert destination.scheme == "http" and destination.hostname == "127.0.0.1"
    assert destination.port is not None and destination.port > 0
    assert destination.path.endswith("/") and not destination.query and not destination.fragment
    assert cap.origin == f"http://127.0.0.1:{destination.port}"
    # A wildcard bind also admits another address within 127/8.
    with socket.socket() as connection:
        connection.settimeout(1)
        assert connection.connect_ex(("127.0.0.2", destination.port)) != 0
    other, _ = factory()
    assert urlsplit(_open(loop_owner, other).url).port != destination.port


@pytest.mark.parametrize("suffix", ("", "snapshot?page_size=1", f"inspect/{OBSERVATION}?page_size=1"))
def test_native_get_and_exact_origin_expose_typed_selected_scope(factory, loop_owner, suffix):
    """Catch wrong bridge loop, foreign scope or raw-dictionary serialization."""
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    assert provider.authorizations == [(MISSION, None)]
    for headers in ((), (("Origin", cap.origin),)):
        response = _http(cap, suffix, headers=headers)
        assert response.status == 200
        assert response.header("Cache-Control") == "no-store"
        assert response.header("Referrer-Policy") == "no-referrer"
        assert response.header("Access-Control-Allow-Origin") is None
        if suffix:
            payload = response.payload()
            assert payload["mission_id"] == str(MISSION) and payload["run_id"] is None
            assert payload["status"] == "OK" and payload["revision"] == 0
            row = payload["observation"] if suffix.startswith("inspect/") else payload["evidence"][0]
            assert row["observation_id"] == str(OBSERVATION)
            assert row["source_id"] == str(SOURCE)
    if suffix:
        assert len(provider.calls) == 2
        assert all(call[1].mission_id == MISSION and call[1].page_size == 1 for call in provider.calls)
        if suffix.startswith("inspect/"):
            assert all(call[2] == OBSERVATION for call in provider.calls)


def test_distinct_selected_runs_retain_authorization_reads_and_outward_identity(factory, loop_owner):
    """Catch discarded selected runs or one capability reusing another's run."""
    relay, provider = factory()
    capabilities = [_open(loop_owner, relay, run_id=run) for run in (RUN_A, RUN_B)]
    assert provider.authorizations == [(MISSION, RUN_A), (MISSION, RUN_B)]
    for capability, run in zip(capabilities, (RUN_A, RUN_B), strict=True):
        for suffix in ("snapshot?page_size=100", f"inspect/{OBSERVATION}?page_size=100"):
            response = _http(capability, suffix)
            assert response.status == 200
            payload = response.payload()
            assert payload["mission_id"] == str(MISSION) and payload["run_id"] == str(run)
            _, request, observation = provider.calls[-1]
            assert request.mission_id == MISSION and request.run_id == run
            assert request.page_size == 100
            assert observation == (OBSERVATION if suffix.startswith("inspect/") else None)
    assert [(operation, request.run_id) for operation, request, _ in provider.calls] == [
        ("snapshot", RUN_A), ("inspection", RUN_A), ("snapshot", RUN_B), ("inspection", RUN_B),
    ]


@pytest.mark.parametrize("host_kind", (
    "missing", "localhost", "foreign", "wrong_port", "port_omitted", "trailing_dot", "suffix", "duplicate",
))
def test_each_nonexact_host_is_refused_before_provider(factory, loop_owner, host_kind):
    """Catch one unchecked Host variant or duplicate enabling DNS rebinding."""
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    port = urlsplit(cap.url).port
    hosts = {
        "missing": "", "localhost": f"localhost:{port}", "foreign": f"attacker.invalid:{port}",
        "wrong_port": f"127.0.0.1:{port + 1}", "port_omitted": "127.0.0.1",
        "trailing_dot": f"127.0.0.1.:{port}", "suffix": f"127.0.0.1:{port}.attacker.invalid",
        "duplicate": f"127.0.0.1:{port}",
    }
    headers = (("Host", hosts[host_kind]),)
    if host_kind == "duplicate":
        headers += (("Host", hosts[host_kind]),)
    if host_kind == "missing":
        wire = f"GET {urlsplit(cap.url).path}snapshot?page_size=100 HTTP/1.1\r\n\r\n".encode("ascii")
        response = _raw_request(cap, wire)
    else:
        response = _http(cap, headers=headers)
    _refusal(response, 403, "SCOPE_MISMATCH")
    assert provider.calls == []


@pytest.mark.parametrize("origin_kind", ("foreign", "null", "empty", "wrong_scheme", "wrong_port", "slash", "duplicate"))
def test_each_nonexact_supplied_origin_is_refused_before_provider(factory, loop_owner, origin_kind):
    """Catch cross-origin read admission despite correct Host and capability."""
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    port = urlsplit(cap.url).port
    origins = {
        "foreign": "https://attacker.invalid", "null": "null", "empty": "",
        "wrong_scheme": f"https://127.0.0.1:{port}", "wrong_port": f"http://127.0.0.1:{port + 1}",
        "slash": cap.origin + "/", "duplicate": cap.origin,
    }
    headers = (("Origin", origins[origin_kind]),)
    if origin_kind == "duplicate":
        headers += (("Origin", cap.origin),)
    _refusal(_http(cap, headers=headers), 403, "SCOPE_MISMATCH")
    assert provider.calls == []


@pytest.mark.parametrize("method", ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"))
def test_each_mutation_or_unsupported_method_is_refused(factory, loop_owner, method):
    """Catch inherited Task Relay POST or permissive fallback method handling."""
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    _refusal(_http(cap, method=method), 405, "METHOD_NOT_ALLOWED")
    assert provider.calls == []


@pytest.mark.parametrize("suffix", ("stage", "cancel", "renew", "snapshot/mutate", "unknown"))
def test_mutation_and_unknown_routes_are_not_read_aliases(factory, loop_owner, suffix):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    _refusal(_http(cap, suffix), 404, "ROUTE_NOT_FOUND")
    assert provider.calls == []


@pytest.mark.parametrize("suffix", ("", "snapshot?page_size=100", f"inspect/{OBSERVATION}?page_size=100"))
def test_head_has_same_status_and_security_headers_without_body(factory, loop_owner, suffix):
    relay, _ = factory()
    cap = _open(loop_owner, relay)
    get = _http(cap, suffix)
    head = _http(cap, suffix, method="HEAD")
    assert head.status == get.status == 200 and head.body == b""
    for name in ("Cache-Control", "Referrer-Policy", "Content-Type"):
        assert head.header(name) == get.header(name)
    assert head.header("Access-Control-Allow-Origin") is None


@pytest.mark.parametrize("case", ("absent", "naive", "nonutc", "past", "now", "over60"))
def test_invalid_explicit_deadline_is_typed_refusal_before_authorization(factory, loop_owner, case):
    relay, provider = factory()
    now = datetime.now(timezone.utc)
    deadlines = {
        "absent": None, "naive": now.replace(tzinfo=None) + timedelta(minutes=15),
        "nonutc": (now + timedelta(minutes=15)).astimezone(timezone(timedelta(hours=7))),
        "past": now - timedelta(seconds=1), "now": now, "over60": now + timedelta(minutes=61),
    }
    result = _await(loop_owner, relay.open_view(mission_id=MISSION, run_id=None, expires_at=deadlines[case]))
    assert type(result) is MissionRelayReadFailure
    assert result.to_payload() == {"schema_version": 1, "status": "REFUSED", "reason_code": "INVALID_EXPIRY"}
    assert provider.calls == [] and provider.authorizations == []


@pytest.mark.parametrize("minutes", (15, 60))
def test_valid_explicit_deadline_is_preserved_without_renewal(factory, loop_owner, minutes):
    relay, _ = factory()
    deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    cap = _open(loop_owner, relay, expires_at=deadline)
    assert cap.expires_at == deadline
    assert _http(cap).status == 200
    assert _http(cap, "").status == 200
    assert cap.expires_at == deadline


def test_authorization_refusal_creates_no_capability_or_read(factory, loop_owner):
    relay, provider = factory()
    provider.refusal = MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH)
    result = _await(loop_owner, relay.open_view(
        mission_id=OTHER, run_id=None, expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    ))
    assert type(result) is MissionRelayReadFailure and result.to_payload() == {
        "schema_version": 1, "status": "REFUSED", "reason_code": "SCOPE_MISMATCH",
    }
    assert provider.authorizations == [(OTHER, None)] and provider.calls == []


def test_unknown_capability_is_refused_without_read(factory, loop_owner):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    destination = urlsplit(cap.url)
    connection = http.client.HTTPConnection("127.0.0.1", destination.port, timeout=5)
    try:
        connection.request("GET", "/inert-unknown-capability/snapshot?page_size=100")
        response = connection.getresponse()
        wire = WireResponse(response.status, tuple(response.getheaders()), response.read(LIMIT + 1))
        _refusal(wire, 403, "SCOPE_MISMATCH")
        assert provider.calls == []
    finally:
        connection.close()


def test_expiry_revokes_only_its_scope_and_does_not_renew_from_get(factory, loop_owner):
    relay, provider = factory()
    cap = _open(loop_owner, relay, expires_at=datetime.now(timezone.utc) + timedelta(seconds=0.2))
    other = _open(loop_owner, relay, mission_id=OTHER)
    assert _http(cap).status == 200
    # An actual owner-loop timer crosses expiry; no patched clock or polling loop.
    crossed = threading.Event()
    loop_owner.call_soon_threadsafe(loop_owner.call_later, 0.25, crossed.set)
    assert crossed.wait(1)
    before = len(provider.calls)
    _refusal(_http(cap), 403, "CAPABILITY_EXPIRED")
    assert len(provider.calls) == before
    assert _http(other).status == 200
    assert provider.calls[-1][1].mission_id == OTHER


@pytest.mark.parametrize("suffix", (
    "snapshot", "snapshot?page_size=0", "snapshot?page_size=201", "snapshot?page_size=-1",
    "snapshot?page_size=1.5", "snapshot?page_size=x", "snapshot?page_size=1&page_size=2",
))
def test_page_size_is_required_and_bounded_before_read(factory, loop_owner, suffix):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    reason = "INVALID_PAGE_SIZE" if suffix in ("snapshot?page_size=0", "snapshot?page_size=201", "snapshot?page_size=-1") else "INVALID_REQUEST"
    _refusal(_http(cap, suffix), 400, reason)
    assert provider.calls == []


@pytest.mark.parametrize("size", (1, 200))
def test_page_size_bounds_are_passed_to_typed_read(factory, loop_owner, size):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    response = _http(cap, f"snapshot?page_size={size}&evidence_offset=0&after_revision=0&after_ordinal=0")
    assert response.status == 200
    request = provider.calls[0][1]
    assert request.page_size == size and request.evidence_offset == 0
    assert request.after_cursor == MissionRelayCursor(mission_id=MISSION, revision=0, ordinal=0)


@pytest.mark.parametrize("extra", (
    "&mission_id=" + str(OTHER), "&after_revision=1", "&after_ordinal=1", "&after_revision=1&after_ordinal=0",
    "&after_revision=-1&after_ordinal=-1", "&evidence_offset=-1", "&evidence_offset=x",
))
def test_malformed_cursor_and_foreign_scope_query_are_refused(factory, loop_owner, extra):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    _refusal(_http(cap, "snapshot?page_size=100" + extra), 400, "INVALID_REQUEST")
    assert provider.calls == []


@pytest.mark.parametrize("method,headers", (
    ("GET", (("Content-Length", "1"),)), ("HEAD", (("Content-Length", "1"),)),
    ("GET", (("Transfer-Encoding", "chunked"),)), ("HEAD", (("Transfer-Encoding", "identity"),)),
    ("GET", (("Content-Length", "-1"),)), ("GET", (("Content-Length", "invalid"),)),
    ("GET", (("Content-Length", "0"), ("Content-Length", "1"))),
))
def test_body_or_ambiguous_framing_is_refused_without_waiting_for_body(factory, loop_owner, method, headers):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    before = time.monotonic()
    response = _http(cap, method=method, headers=headers)
    assert time.monotonic() - before < 1.5, "Header refusal incorrectly waited for body bytes"
    assert response.status == 400 and provider.calls == []
    if method == "HEAD":
        assert response.body == b""
    else:
        _refusal(response, 400, "INVALID_REQUEST")


def _raw_request(cap, wire):
    with socket.create_connection(("127.0.0.1", urlsplit(cap.url).port), timeout=5) as connection:
        connection.sendall(wire)
        response = http.client.HTTPResponse(connection)
        response.begin()
        return WireResponse(response.status, tuple(response.getheaders()), response.read(LIMIT + 1))


@pytest.mark.parametrize("overflow", (False, True))
def test_aggregate_request_line_and_headers_use_raw_8192_byte_bound(factory, loop_owner, overflow):
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    destination = urlsplit(cap.url)
    prefix = f"GET {destination.path}snapshot?page_size=100 HTTP/1.1\r\nHost: 127.0.0.1:{destination.port}\r\nX-Inert: ".encode("ascii")
    suffix = b"\r\n\r\n"
    size = 8193 if overflow else 8192
    # Raw obs-text bytes catch a decoded-character counter; no body is sent.
    wire = prefix + b"\xc3\xa9" * ((size - len(prefix) - len(suffix)) // 2)
    wire += b"x" * (size - len(wire) - len(suffix)) + suffix
    assert len(wire) == size
    response = _raw_request(cap, wire)
    if overflow:
        _refusal(response, 413, "REQUEST_TOO_LARGE")
        assert provider.calls == []
    else:
        assert response.status == 200 and len(provider.calls) == 1


@pytest.mark.parametrize("operation", ("snapshot", "inspection"))
def test_serialized_utf8_response_overflow_is_typed_not_truncated(factory, loop_owner, operation):
    relay, provider = factory()
    provider.title = "ữ" * 400_000  # Under a character bound, above the UTF-8 byte bound.
    cap = _open(loop_owner, relay)
    suffix = "snapshot?page_size=1" if operation == "snapshot" else f"inspect/{OBSERVATION}?page_size=1"
    _refusal(_http(cap, suffix), 413, "RESPONSE_TOO_LARGE")
    assert len(provider.calls) == 1


def test_bounded_multibyte_response_preserves_exact_statement(factory, loop_owner):
    relay, provider = factory()
    provider.title = "ữ" * 100_000
    cap = _open(loop_owner, relay)
    response = _http(cap)
    assert response.status == 200
    assert len(response.body) <= LIMIT
    title = response.payload()["evidence"][0]["title"]
    assert len(title) == 100_000 and set(title) == {"ữ"}, "Response silently truncated evidence"


@pytest.mark.parametrize("extra_byte", (False, True))
def test_exact_serialized_response_boundary_accepts_limit_and_refuses_next_byte(factory, loop_owner, extra_byte):
    relay, provider = factory()
    provider.title = ""
    cap = _open(loop_owner, relay)
    baseline = _http(cap)
    assert baseline.status == 200 and baseline.payload()["evidence"][0]["title"] == ""
    # Calibrate fixed receipt overhead on real wire, then add literal ASCII bytes.
    # The expected bound is independent of the listener's constant/serializer.
    provider.title = "x" * (LIMIT - len(baseline.body) + int(extra_byte))
    response = _http(cap)
    if extra_byte:
        _refusal(response, 413, "RESPONSE_TOO_LARGE")
    else:
        assert response.status == 200 and len(response.body) == LIMIT
        assert len(response.payload()["evidence"][0]["title"]) == len(provider.title)


@pytest.mark.parametrize("suffix", ("", "snapshot?page_size=100", "unknown"))
def test_cache_referrer_and_cors_controls_apply_to_success_and_refusal(factory, loop_owner, suffix):
    relay, _ = factory()
    cap = _open(loop_owner, relay)
    response = _http(cap, suffix)
    assert response.status == (404 if suffix == "unknown" else 200)
    assert response.header("Cache-Control") == "no-store"
    assert response.header("Referrer-Policy") == "no-referrer"
    assert response.header("Access-Control-Allow-Origin") is None
    assert response.header("Access-Control-Allow-Credentials") is None


def _assert_maintained_csp(csp, html):
    """Check header assertions only; helper controls are not browser/HTTP proof."""
    assert csp is not None
    directives = {}
    for item in csp.split(";"):
        parts = item.strip().split()
        if not parts:
            continue
        name = parts[0].lower()
        assert name not in directives, "Duplicate CSP directive changes effective browser policy"
        directives[name] = parts[1:]
    assert not {"script-src-elem", "script-src-attr", "style-src-elem", "style-src-attr"}.intersection(directives), "Override CSP directives are not admitted on this maintained surface"
    assert directives.get("default-src") == ["'none'"]
    assert directives.get("connect-src") == ["'self'"]
    assert directives.get("object-src") == ["'none'"]
    assert directives.get("base-uri") == ["'none'"]
    assert directives.get("frame-ancestors") == ["'none'"]
    for tag, directive in (("script", "script-src"), ("style", "style-src")):
        policy = directives.get(directive, [])
        allowed_origins = {"'self'"} if tag == "script" else {"'self'", "https://fonts.googleapis.com"}
        assert policy and all(
            item in allowed_origins or re.fullmatch(r"'(?:nonce-[A-Za-z0-9+/=_-]+|sha(?:256|384|512)-[A-Za-z0-9+/=]+)'", item)
            for item in policy
        )
        elements = re.findall(r"<" + tag + r"\b([^>]*)>(.*?)</" + tag + r">", html, flags=re.S | re.I)
        assert elements, "Maintained HTML must carry authorized inline code"
        for attributes, content in elements:
            assert not re.search(r"\bsrc\s*=", attributes, re.I)
            nonce = re.search(r'\bnonce=[\"\x27]([^\"\x27]+)[\"\x27]', attributes)
            authorized = nonce is not None and f"'nonce-{nonce.group(1)}'" in policy
            for algorithm in ("sha256", "sha384", "sha512"):
                digest = base64.b64encode(hashlib.new(algorithm, content.encode("utf-8")).digest()).decode("ascii")
                authorized |= f"'{algorithm}-{digest}'" in policy
            assert authorized, "CSP does not authorize the maintained inline bytes"
    assert "unsafe-eval" not in csp and "unsafe-inline" not in csp


def test_maintained_html_csp_authorizes_only_its_inline_code_and_self_fetch(factory, loop_owner):
    """Catch permissive script origins/eval, stale hashes and opaque token echo."""
    relay, _ = factory()
    cap = _open(loop_owner, relay)
    response = _http(cap, "")
    assert response.status == 200 and len(response.body) <= LIMIT
    try:
        html = response.body.decode("utf-8", errors="strict")
    except UnicodeError:
        pytest.fail("Maintained HTML is not valid UTF-8", pytrace=False)
    _assert_maintained_csp(response.header("Content-Security-Policy"), html)
    opaque = urlsplit(cap.url).path.strip("/").split("/")[-1]
    assert bool(opaque) and opaque not in html, "Capability token leaked into maintained HTML"


@pytest.mark.parametrize("mutation", (
    "none", "duplicate_script", "duplicate_style", "mixed_case_duplicate",
    "script_element_override", "style_element_override", "script_attribute_override", "style_attribute_override",
))
def test_csp_assertion_readiness_rejects_duplicate_and_override_policies(mutation):
    """Assertion readiness only: literal inert headers, no listener or browser."""
    html = '<script nonce="inertnonce">void 0;</script><style nonce="inertnonce">body {}</style>'
    csp = (
        "default-src 'none'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "script-src 'nonce-inertnonce'; style-src 'nonce-inertnonce'"
    )
    prefixes = {
        "duplicate_script": "script-src https://attacker.invalid; ",
        "duplicate_style": "style-src https://attacker.invalid; ",
        "mixed_case_duplicate": "SCRIPT-SRC https://attacker.invalid; ",
    }
    suffixes = {
        "script_element_override": "; script-src-elem 'nonce-inertnonce' https://attacker.invalid",
        "style_element_override": "; style-src-elem 'nonce-inertnonce' https://attacker.invalid",
        "script_attribute_override": "; script-src-attr 'unsafe-inline'",
        "style_attribute_override": "; style-src-attr 'unsafe-inline'",
    }
    if mutation == "none":
        _assert_maintained_csp(csp, html)
    else:
        with pytest.raises(AssertionError, match="Duplicate CSP|Override CSP"):
            _assert_maintained_csp(prefixes.get(mutation, "") + csp + suffixes.get(mutation, ""), html)


@pytest.mark.parametrize("failure", ("provider_error", "bad_request"))
def test_refusals_never_log_or_echo_request_capability_or_error(factory, loop_owner, capsys, caplog, failure):
    caplog.set_level(logging.DEBUG)
    relay, provider = factory()
    cap = _open(loop_owner, relay)
    if failure == "provider_error":
        provider.error = True
        response = _http(cap)
        _refusal(response, 503, "READ_UNAVAILABLE", unavailable=True)
        assert len(provider.calls) == 1
    else:
        response = _http(cap, "snapshot?page_size=100&inert_private=" + MARKER)
        _refusal(response, 400, "INVALID_REQUEST")
        assert provider.calls == []
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    opaque = urlsplit(cap.url).path.strip("/").split("/")[-1]
    assert all(marker not in logs for marker in (MARKER, cap.url, opaque)), "Private transport state was logged"
    assert all(marker.encode("utf-8") not in response.body for marker in (MARKER, cap.url, opaque)), "Private transport state was echoed"


@pytest.mark.parametrize("operation", ("snapshot", "inspection"))
def test_successful_evidence_payload_is_returned_without_logging(factory, loop_owner, capsys, caplog, operation):
    """Catch logging of legitimate successfully serialized evidence content."""
    caplog.set_level(logging.DEBUG)
    relay, provider = factory()
    provider.title = MARKER
    cap = _open(loop_owner, relay)
    suffix = "snapshot?page_size=100" if operation == "snapshot" else f"inspect/{OBSERVATION}?page_size=100"
    response = _http(cap, suffix)
    assert response.status == 200
    payload = response.payload()
    row = payload["evidence"][0] if operation == "snapshot" else payload["observation"]
    assert row["title"] == MARKER and MARKER.encode("utf-8") in response.body
    assert len(provider.calls) == 1 and provider.calls[0][0] == operation
    captured = capsys.readouterr()
    logs = captured.out + captured.err + caplog.text
    assert MARKER not in logs, "Successful evidence payload was logged"
    opaque = urlsplit(cap.url).path.strip("/").split("/")[-1]
    assert all(marker not in logs for marker in (cap.url, opaque)), "Capability was logged on successful read"


@pytest.mark.parametrize("second", ("snapshot?page_size=100", f"inspect/{OBSERVATION}?page_size=100"))
def test_capability_admission_is_one_shared_slot_without_waiter_queue(factory, loop_owner, second):
    relay, provider = factory()
    provider.block = True
    cap = _open(loop_owner, relay)
    with ThreadPoolExecutor(max_workers=1) as clients:
        first = clients.submit(_http, cap)
        try:
            assert provider.entered.acquire(timeout=1)
            start = time.monotonic()
            _refusal(_http(cap, second), 503, "READ_BUSY", unavailable=True)
            assert time.monotonic() - start < 1.5, "Excess request was queued"
            assert len(provider.calls) == 1
        finally:
            loop_owner.call_soon_threadsafe(provider.release.set)
        assert first.result(5).status == 200
    assert _http(cap, second).status == 200
    assert len(provider.calls) == 2


def test_process_admission_is_four_across_listener_instances(factory, loop_owner):
    relay, provider = factory()
    other, other_provider = factory()
    provider.block = other_provider.block = True
    caps = [_open(loop_owner, relay, mission_id=MISSION) for _ in range(3)]
    caps.append(_open(loop_owner, other, mission_id=OTHER))
    fifth = _open(loop_owner, other)
    with ThreadPoolExecutor(max_workers=4) as clients:
        pending = [clients.submit(_http, cap) for cap in caps]
        try:
            assert all(provider.entered.acquire(timeout=1) for _ in range(3))
            assert other_provider.entered.acquire(timeout=1)
            start = time.monotonic()
            _refusal(_http(fifth), 503, "READ_BUSY", unavailable=True)
            assert time.monotonic() - start < 1.5
            assert len(provider.calls) == 3 and len(other_provider.calls) == 1
        finally:
            loop_owner.call_soon_threadsafe(provider.release.set)
            loop_owner.call_soon_threadsafe(other_provider.release.set)
        assert all(future.result(5).status == 200 for future in pending)
    assert _http(fifth).status == 200


def _assert_admitted_deadline(admitted_at, cancelled_at):
    # Allow 200 ms early sampling and 250 ms loop scheduling delay, never 4 s.
    assert 2.8 <= cancelled_at - admitted_at < 3.25, "Admitted deadline did not enforce three seconds"


@pytest.mark.parametrize("interval,accepted", ((2.0, False), (3.0, True), (4.0, False)))
def test_deadline_assertion_readiness_excludes_four_second_timeout(interval, accepted):
    """Assertion readiness only: literal timestamps, no listener/timing proof."""
    if accepted:
        _assert_admitted_deadline(10.0, 10.0 + interval)
    else:
        with pytest.raises(AssertionError, match="Admitted deadline"):
            _assert_admitted_deadline(10.0, 10.0 + interval)


def test_admitted_read_times_out_at_three_seconds_and_never_looks_empty(factory, loop_owner):
    relay, provider = factory()
    provider.block = True
    cap = _open(loop_owner, relay)
    started = time.monotonic()
    response = _http(cap)
    delivered_at = time.monotonic()
    _refusal(response, 504, "READ_TIMEOUT", unavailable=True)
    assert provider.cancelled.wait(1) and provider.settled.wait(1)
    assert len(provider.calls) == 1
    assert len(provider.admission_times) == len(provider.cancellation_times) == 1
    admitted_at, cancelled_at = provider.admission_times[0], provider.cancellation_times[0]
    _assert_admitted_deadline(admitted_at, cancelled_at)
    # Transport delivery overhead is separate from the enforced read interval.
    assert started <= admitted_at <= cancelled_at
    assert abs(delivered_at - cancelled_at) < 1.5, "Timeout response delivery exceeded transport tolerance"


def test_timeout_retains_capability_slot_until_cancellation_actually_settles(factory, loop_owner):
    relay, provider = factory()
    provider.block = provider.hold_cancellation = True
    cap = _open(loop_owner, relay)
    try:
        _refusal(_http(cap), 504, "READ_TIMEOUT", unavailable=True)
        assert provider.cancelled.wait(1) and not provider.settled.is_set()
        _refusal(_http(cap), 503, "READ_BUSY", unavailable=True)
        assert len(provider.calls) == 1
    finally:
        loop_owner.call_soon_threadsafe(provider.cancel_release.set)
    assert provider.settled.wait(1)
    provider.block = False
    assert _http(cap).status == 200 and len(provider.calls) == 2


def test_uncertain_timed_out_reads_retain_all_four_process_slots(factory, loop_owner):
    relay, provider = factory()
    provider.block = provider.hold_cancellation = True
    caps = [_open(loop_owner, relay) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=4) as clients:
        futures = [clients.submit(_http, cap) for cap in caps[:4]]
        try:
            assert all(provider.entered.acquire(timeout=1) for _ in range(4))
            for future in futures:
                _refusal(future.result(5), 504, "READ_TIMEOUT", unavailable=True)
            assert not provider.settled.is_set()
            _refusal(_http(caps[4]), 503, "READ_BUSY", unavailable=True)
            assert len(provider.calls) == 4
        finally:
            loop_owner.call_soon_threadsafe(provider.cancel_release.set)


def test_expiry_refuses_new_reads_while_previous_read_is_pending(factory, loop_owner):
    relay, provider = factory()
    provider.block = True
    cap = _open(loop_owner, relay, expires_at=datetime.now(timezone.utc) + timedelta(seconds=0.3))
    with ThreadPoolExecutor(max_workers=1) as clients:
        pending = clients.submit(_http, cap)
        try:
            assert provider.entered.acquire(timeout=1)
            crossed = threading.Event()
            loop_owner.call_soon_threadsafe(loop_owner.call_later, 0.35, crossed.set)
            assert crossed.wait(1)
            _refusal(_http(cap), 403, "CAPABILITY_EXPIRED")
            assert len(provider.calls) == 1
        finally:
            loop_owner.call_soon_threadsafe(provider.release.set)
        result = pending.result(5)
        assert result.status != 200, "Late delivery after expiry exposed a successful read"


def test_close_revokes_all_urls_and_is_idempotent(factory, loop_owner):
    relay, provider = factory()
    caps = [_open(loop_owner, relay, mission_id=mission) for mission in (MISSION, OTHER)]
    relay.close()
    relay.close()
    assert _await(loop_owner, relay.wait_closed(timeout=3))
    assert all(_closed(cap) for cap in caps)
    assert provider.calls == []


def test_shutdown_waits_for_underlying_cancellation_without_blocking_owner_loop(factory, loop_owner):
    relay, provider = factory()
    provider.block = provider.hold_cancellation = True
    cap = _open(loop_owner, relay)
    with ThreadPoolExecutor(max_workers=1) as clients:
        pending = clients.submit(_http, cap)
        try:
            assert provider.entered.acquire(timeout=1)
            async def close_on_owner():
                relay.close()
                return "owner-loop-responsive"
            assert _await(loop_owner, close_on_owner()) == "owner-loop-responsive"
            assert provider.cancelled.wait(1) and not provider.settled.is_set()
            assert not _await(loop_owner, relay.wait_closed(timeout=0.1))
        finally:
            loop_owner.call_soon_threadsafe(provider.cancel_release.set)
        assert _await(loop_owner, relay.wait_closed(timeout=3))
        assert provider.settled.is_set() and _closed(cap)
        try:
            result = pending.result(5)
        except (OSError, http.client.HTTPException):
            pass  # Closed connection is a valid shutdown revocation.
        else:
            assert result.status != 200, "Shutdown exposed a late successful read"


def test_authorization_that_outlives_deadline_mints_no_capability(factory, loop_owner):
    """The finite lifetime includes authorization, rather than starting after it."""
    class SlowAuthorization(InertReadProvider):
        async def authorize_view(self, mission_id, run_id):
            await super().authorize_view(mission_id, run_id)
            await asyncio.sleep(0.08)
            return None

    relay, provider = factory(SlowAuthorization(loop_owner))
    result = _await(loop_owner, relay.open_view(
        mission_id=MISSION, run_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=0.04),
    ))
    assert type(result) is MissionRelayReadFailure
    assert result.reason_code is RelayReadReason.INVALID_EXPIRY
    assert provider.authorizations == [(MISSION, None)] and provider.calls == []


def test_shutdown_retains_pending_authorization_until_cleanup_settles(factory, loop_owner):
    """Authorization reads are loop-owned resources even before a URL exists."""
    class PendingAuthorization(InertReadProvider):
        async def authorize_view(self, mission_id, run_id):
            await super().authorize_view(mission_id, run_id)
            self.entered.release()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                await self.cancel_release.wait()
                raise
            finally:
                self.settled.set()

    relay, provider = factory(PendingAuthorization(loop_owner))
    pending = asyncio.run_coroutine_threadsafe(relay.open_view(
        mission_id=MISSION, run_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
    ), loop_owner)
    try:
        assert provider.entered.acquire(timeout=1)
        relay.close()
        assert provider.cancelled.wait(1)
        assert not _await(loop_owner, relay.wait_closed(timeout=0.1))
    finally:
        loop_owner.call_soon_threadsafe(provider.cancel_release.set)
        loop_owner.call_soon_threadsafe(provider.release.set)
    assert _await(loop_owner, relay.wait_closed(timeout=3))
    result = pending.result(5)
    assert type(result) is MissionRelayReadFailure
    assert provider.settled.is_set()
