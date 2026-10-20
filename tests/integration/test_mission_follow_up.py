"""T068 physical follow-up execution controls against the canonical typed ports.

The four public execution arguments follow contracts/follow-up.md. Explicit
synthetic capability/session proof and external ingress are offline doubles;
admission, reservation, actual deterministic execution and readback use real
physical stores. Missing APIs/setup errors are not behavioral RED.
"""

import asyncio
import importlib
import inspect
import sqlite3
from dataclasses import dataclass, field, replace
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
import pytest_asyncio

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from tests.integration.test_mission_relay_read_boundary import NOW, _state, relay_case as _relay_case

@pytest_asyncio.fixture(params=("file", "memory", "postgres"))
async def relay_case(request, tmp_path):
    """Reuse canonical relay setup; follow-up PG additionally uses accepted owner role."""
    from tests.integration.follow_up_execution_setup import postgres_case, cleanup_disposable
    async for values in _relay_case.__wrapped__(request, tmp_path):
        case, missions, runs = values
        if case.name != "postgres":
            yield values
        else:
            async with postgres_case(case) as scoped:
                try:
                    yield scoped, missions, runs
                finally:
                    cleanup_disposable(scoped)

MODULE = "ignis.application.use_cases.execute_mission_follow_up"


def _api(repository):
    try:
        module = importlib.import_module(MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != MODULE:
            raise
        pytest.fail(f"T068 API unavailable: {MODULE}; no admission behavior executed", pytrace=False)
    factory = getattr(module, "ExecuteMissionFollowUpUseCase", None)
    if not callable(factory):
        pytest.fail("T068 API unavailable: ExecuteMissionFollowUpUseCase", pytrace=False)
    for name in ("record_follow_up_fact", "record_follow_up_work", "load_mission_follow_ups"):
        if not callable(getattr(repository, name, None)):
            pytest.fail(f"T068 API unavailable: repository.{name}", pytrace=False)
    return factory


@dataclass
class Ingress:
    """Counters at lazy session initialization and the external probe boundary."""

    auth_initializations: int = 0
    connector_calls: int = 0
    child_executions: list = field(default_factory=list)
    queries: list = field(default_factory=list)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    interrupt: bool = False

    def initialize_session(self):
        self.auth_initializations += 1


class InterruptedProbe(BaseException):
    """Process-interruption control bypasses ordinary connector error recovery."""


class OfflinePlugin(IConnectorPlugin):
    platform = PlatformType.YOUTUBE
    name = "T068 offline connector"
    connector_revision = "offline-v1"

    @property
    def plugin_id(self):
        return "youtube"

    def __init__(self, ingress):
        self.ingress = ingress

    async def is_healthy(self):
        return True

    async def fetch_signals(self, *args, **kwargs):
        raise AssertionError("Follow-up must execute its recorded query, not a feed")

    async def search_signals(self, keywords, geo, timeframe, attestation=None, **kwargs):
        assert self.ingress.auth_initializations == 1
        self.ingress.connector_calls += 1
        self.ingress.queries.append(tuple(keywords))
        self.ingress.entered.set()
        await asyncio.wait_for(self.ingress.release.wait(), timeout=5)
        if self.ingress.interrupt:
            raise InterruptedProbe()
        if attestation is not None:
            for keyword in keywords:
                attestation.executed(keyword)
        return []


class EmptyClusterer:
    async def cluster_signals(self, signals):
        assert signals == []
        return []


def _executor(repository, ingress):
    registry = ConnectorPluginRegistry(repository)
    registry.register(OfflinePlugin(ingress))
    actual = ExecuteMissionUseCase(repository, registry, EmptyClusterer(), WorkspaceRepository(repository))

    class ObservedExecutor:
        def __getattr__(self, name):
            return getattr(actual, name)

        async def _execute_authorized(self, mission, *args, **kwargs):
            original = kwargs["scope_guard"]
            async def observed(journal):
                ingress.child_executions.append(str(mission.id))
                return await original(journal)
            kwargs["scope_guard"] = observed
            return await actual._execute_authorized(mission, *args, **kwargs)

    return ObservedExecutor()


async def _arrange(case, tmp_path, **changes):
    """Persist a valid typed history before changing a negative control."""
    from tests.integration.follow_up_execution_setup import ready
    from tests.integration.test_follow_up_execution import OfflineExecutionVerifier
    factory = _api(case.repository)
    repository, mission, work, authority, _ = await ready(
        case.repository, tmp_path, _executor(case.repository, Ingress()), factory, budget=max(2, changes.get("quota_ceiling", 4)),
        cost_budget=max(2, changes.get("cost_ceiling", 4)))
    if case.name == "postgres":
        from tests.integration.test_follow_up_postgres_admission import AsyncVerifier
        class PostgresExecutionVerifier(OfflineExecutionVerifier):
            hold_current = AsyncVerifier.hold_current
        verifier = PostgresExecutionVerifier()
    else:
        verifier = OfflineExecutionVerifier()
    repository.configure_follow_up_verifier(verifier)
    ingress = Ingress()
    ingress.release.set()

    async def initialize(sources):
        assert sources == frozenset({"youtube"})
        ingress.initialize_session()

    service = factory(repository=repository, mission_executor=_executor(repository, ingress),
                      selected_parent_id=str(mission.id), host_authorized=True,
                      session_initializer=initialize)
    assert set(inspect.signature(service.execute).parameters) == {
        "mission_id", "follow_up_work_id", "expected_research_epoch", "idempotency_key",
    }
    context = await repository._follow_up_execution_context(mission.id, work.work_id)
    plan, _ = await service._plan(context)
    assert plan.digest == authority.sources[0].plan_digest, (plan, authority.sources)
    payload = _work_payload(work, authority.cost)
    payload.update(_authority=authority, _verifier=verifier, _initializer=initialize)
    if changes:
        await _negative_control(case, service, work, authority, verifier, changes)
    return factory, mission, payload, ingress, service


def _work_payload(work, cost):
    return {"parent_mission_id": str(work.inputs.mission_id),
            "assignment_id": str(work.assignment_id), "work_id": str(work.work_id),
            "gap_id": str(work.gap_id), "research_epoch": work.research_epoch,
            "work_queries": list(work.requested_scope.queries),
            "work_sources": sorted(work.requested_scope.sources), "reservation_cost": cost}


async def _negative_control(case, service, work, authority, verifier, changes):
    from contextlib import asynccontextmanager
    from tests.integration.follow_up_execution_setup import corrupt_disposable
    from ignis.infrastructure.persistence.follow_up_admission_rules import encode
    import json
    if changes == {"session_authorized": False}:
        verifier.allowed = False
        return
    if "stop_requested" in changes or "cancel_requested" in changes:
        original = verifier.hold_execution
        @asynccontextmanager
        async def operational(*args):
            async with original(*args) as lease:
                lease.proof = replace(lease.proof, stop_reached=changes.get("stop_requested", False),
                                      cancel_requested=changes.get("cancel_requested", False))
                yield lease
        verifier.hold_execution = operational
        return
    if "deadline" in changes:
        service._clock = lambda: work.authority_deadline + (
            timedelta(seconds=1) if changes["deadline"] != NOW.isoformat() else timedelta())
        return
    statements = []
    if "research_state" in changes:
        statements.append(("research_assignments", "UPDATE research_assignments SET state=? WHERE assignment_id=?",
                           (changes["research_state"], str(work.assignment_id))))
    if "actions" in changes:
        # Explicit legacy READ-only rows are distinct from ANALYZE-only rows.
        # The valid registrar was used first; this is a disposable negative control.
        actions = changes["actions"]
        statements.append(("research_assignments", "UPDATE research_assignments SET actions=? WHERE assignment_id=?",
                           (actions if case.name == "postgres" else json.dumps(actions), str(work.assignment_id))))
    if "quota_ceiling" in changes or "cost_ceiling" in changes:
        key = "quota_ceiling" if "quota_ceiling" in changes else "cost_ceiling"
        changed = replace(authority, **{key: changes[key]})
        statements.append(("mission_follow_up_authorities", "UPDATE mission_follow_up_authorities SET payload=? WHERE work_id=?",
                           (encode(changed), str(work.work_id))))
    if "work_queries" in changes or "work_sources" in changes:
        requested = replace(work.requested_scope,
                            queries=tuple(changes.get("work_queries", work.requested_scope.queries)),
                            sources=frozenset(changes.get("work_sources", work.requested_scope.sources)))
        changed_work = replace(work, requested_scope=requested)
        statements += [
            ("mission_follow_up_authorities", "UPDATE mission_follow_up_authorities SET payload=? WHERE work_id=?",
             (encode(replace(authority, work=changed_work)), str(work.work_id))),
            ("mission_follow_up_work", "UPDATE mission_follow_up_work SET requested_queries=?,requested_sources=? WHERE work_id=?",
             (json.dumps(list(requested.queries)), json.dumps(sorted(requested.sources)), str(work.work_id))),
        ]
    if any(key.startswith("expected_") for key in changes):
        # Keep the same physical input identity and gap/work bindings while its
        # historical digest conflicts with the canonical current evidence frame.
        field = ("manifest_digest" if "expected_manifest_digest" in changes else
                 "brief_digest" if "expected_brief_revision_id" in changes else "frame_digest")
        changed_inputs = replace(work.inputs, **{field: "0" * 64})
        changed_work = replace(work, inputs=changed_inputs)
        # All work items in this setup use the exact same canonical input set.
        statements += [
            ("research_input_sets", f"UPDATE research_input_sets SET {field}=? WHERE mission_id=?",
             ("0" * 64, str(work.inputs.mission_id))),
            ("mission_follow_up_authorities", "UPDATE mission_follow_up_authorities SET payload=? WHERE work_id=?",
             (encode(replace(authority, work=changed_work)), str(work.work_id))),
        ]
    assert statements, f"Missing canonical negative fixture: {changes}"
    corrupt_disposable(case, statements)


async def _inventory(repository, mission_id):
    snapshot = await repository.load_mission_follow_ups(UUID(str(mission_id)))
    children = []
    for relationship in snapshot.relationships:
        work = relationship.work
        child = await repository.get_mission(relationship.child_mission_id)
        assert child is not None
        manifest = await repository.get_mission_manifest(child.id)
        assert manifest is not None
        children.append({"mission_id": str(child.id), "parent_mission_id": str(work.inputs.mission_id),
                         "assignment_id": str(work.assignment_id), "work_id": str(work.work_id),
                         "gap_id": str(work.gap_id), "queries": child.keywords,
                         "sources": sorted(manifest.allowed_resources)})
    return {"work_items": {str(w.work_id): _work_payload(w, None) for w in snapshot.work_items},
            "children": children,
            "reservations": [{"reservation_id": str(r.relationship.reservation_id),
                              "child_mission_id": str(r.relationship.child_mission_id),
                              "cost": r.reserved_cost, "state": r.state} for r in snapshot.reservations]}


async def _execute(service, payload, *, epoch=None, key=None, parent=None):
    result = await service.execute(
        mission_id=parent or payload["parent_mission_id"],
        follow_up_work_id=payload["work_id"],
        expected_research_epoch=payload["research_epoch"] if epoch is None else epoch,
        idempotency_key=key or uuid4().hex,
    )
    relationship = result.relationship
    result = result.to_payload()
    result["work_id"] = result.get("follow_up_work_id")
    result["parent_mission_id"] = str(relationship.work.inputs.mission_id) if relationship else None
    return result


def _assert_refusal(result, reason, before, after, ingress):
    assert result["status"] == "REFUSED"
    assert result["reason_code"] == reason
    assert result["child_mission_id"] is None and result["reservation_id"] is None
    assert after["children"] == before["children"]
    assert after["reservations"] == before["reservations"]
    assert ingress.connector_calls == 0
    assert ingress.auth_initializations == 0
    assert ingress.child_executions == []


def _assert_single(result, inventory, payload, ingress):
    assert result["status"] in {"ADMITTED", "RUNNING", "COMPLETED"}
    assert len(inventory["children"]) == len(inventory["reservations"]) == 1
    child, reservation = inventory["children"][0], inventory["reservations"][0]
    assert result["child_mission_id"] == child["mission_id"] != payload["parent_mission_id"]
    assert result["reservation_id"] == reservation["reservation_id"]
    for key in ("assignment_id", "work_id", "gap_id", "parent_mission_id"):
        assert child[key] == result[key] == payload[key]
    assert reservation["child_mission_id"] == child["mission_id"]
    assert reservation["cost"] == payload["reservation_cost"]
    assert child["queries"] == payload["work_queries"]
    assert child["sources"] == payload["work_sources"]
    assert ingress.child_executions == [child["mission_id"]]
    assert ingress.connector_calls == ingress.auth_initializations == 1
    assert ingress.queries == [tuple(payload["work_queries"])]


def _assert_unresolved(inventory, cost):
    assert len(inventory["children"]) == len(inventory["reservations"]) == 1
    reservation = inventory["reservations"][0]
    assert reservation["state"] == "UNRESOLVED"
    assert reservation["cost"] == cost
    assert reservation["child_mission_id"] == inventory["children"][0]["mission_id"]
    return reservation


async def _assert_durable(case, result, payload):
    """Independent physical query; no dependence on a future loader's inventory."""
    child = await case.repository.get_mission(UUID(result["child_mission_id"]))
    assert child is not None and str(child.id) != payload["parent_mission_id"]
    assert child.keywords == payload["work_queries"]
    assert [p.value for p in child.platforms] == payload["work_sources"]
    manifest = await case.repository.get_mission_manifest(child.id)
    assert manifest is not None
    assert set(manifest.allowed_resources) == set(payload["work_sources"])
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as conn:
            rows = conn.execute("SELECT reservation_id, child_mission_id FROM mission_follow_up_reservations "
                                "WHERE parent_mission_id=%s", (UUID(payload["parent_mission_id"]),)).fetchall()
    else:
        conn = case.repository._mem_conn
        owned = conn is None
        if owned:
            conn = sqlite3.connect(case.repository._db_path)
        try:
            rows = conn.execute("SELECT reservation_id, child_mission_id FROM mission_follow_up_reservations "
                                "WHERE parent_mission_id=?", (payload["parent_mission_id"],)).fetchall()
        finally:
            if owned:
                conn.close()
    assert [(str(reservation), str(child_id)) for reservation, child_id in rows] == [
        (result["reservation_id"], result["child_mission_id"]),
    ]


REFUSALS = (
    ({"work_queries": ["unapproved query"]}, "SCOPE_MISMATCH"),
    ({"work_sources": ["threads"]}, "SOURCE_MISMATCH"),
    ({"session_authorized": False}, "SESSION_AUTHORITY_REQUIRED"),
    ({"expected_brief_revision_id": str(uuid4())}, "BRIEF_REVISION_MISMATCH"),
    ({"expected_manifest_digest": "0" * 64}, "MANIFEST_MISMATCH"),
    ({"expected_frame_digest": "0" * 64}, "INPUT_REVISION_MISMATCH"),
    ({"deadline": (NOW - timedelta(seconds=1)).isoformat()}, "AUTHORITY_EXPIRED"),
    ({"quota_ceiling": 0}, "QUOTA_EXHAUSTED"),
    ({"cost_ceiling": 0}, "COST_EXHAUSTED"),
    ({"research_state": "COMPLETED"}, "RESEARCH_TERMINAL"),
    ({"research_state": "FAILED"}, "RESEARCH_TERMINAL"),
    ({"research_state": "CANCELLED"}, "RESEARCH_TERMINAL"),
    ({"deadline": NOW.isoformat()}, "AUTHORITY_EXPIRED"),
    ({"research_state": "INSUFFICIENT_EVIDENCE"}, "RESEARCH_TERMINAL"),
    ({"cancel_requested": True}, "CANCEL_REQUESTED"),
    ({"stop_requested": True}, "STOP_CONDITION_REACHED"),
    ({"actions": ["ANALYZE"]}, "COLLECTION_AUTHORITY_REQUIRED"),
    ({"actions": ["READ"]}, "COLLECTION_AUTHORITY_REQUIRED"),
)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,reason", REFUSALS)
async def test_recorded_authority_refuses_before_child_or_ingress(relay_case, tmp_path, changes, reason):
    case, _, _ = relay_case
    _, mission, payload, ingress, service = await _arrange(case, tmp_path, **changes)
    before = await _inventory(case.repository, mission.id)
    physical = _state(case)
    result = await _execute(service, payload)
    _assert_refusal(result, reason, before, await _inventory(case.repository, mission.id), ingress)
    # Refusals may return diagnostics, but cannot write collection/admission state.
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary,reason", (("epoch", "STALE_EPOCH"), ("parent", "SCOPE_MISMATCH"),
                                              ("work", "UNKNOWN_FOLLOW_UP")))
async def test_execution_identity_is_not_caller_authority(relay_case, tmp_path, boundary, reason):
    case, parents, _ = relay_case
    _, mission, payload, ingress, service = await _arrange(case, tmp_path)
    before = await _inventory(case.repository, mission.id)
    physical = _state(case)
    request = dict(payload)
    if boundary == "work":
        request["work_id"] = str(uuid4())
    result = await _execute(service, request, epoch=0 if boundary == "epoch" else None,
                            parent=str(parents[1].id) if boundary == "parent" else None)
    _assert_refusal(result, reason, before, await _inventory(case.repository, mission.id), ingress)
    assert _state(case) == physical


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", (True, False))
async def test_duplicate_reuses_canonical_child_and_reservation(relay_case, tmp_path, same_key):
    case, _, _ = relay_case
    _, mission, payload, ingress, service = await _arrange(case, tmp_path)
    key = uuid4().hex
    first = await _execute(service, payload, key=key)
    settled = await _inventory(case.repository, mission.id)
    second = await _execute(service, payload, key=key if same_key else uuid4().hex)
    assert second["child_mission_id"] == first["child_mission_id"]
    assert second["reservation_id"] == first["reservation_id"]
    assert await _inventory(case.repository, mission.id) == settled
    _assert_single(first, settled, payload, ingress)
    await _assert_durable(case, first, payload)
    assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file", "postgres"), indirect=True)
@pytest.mark.parametrize("same_key", (True, False))
@pytest.mark.parametrize("overlap_only", (False, True))
async def test_racing_connections_share_one_admission(relay_case, tmp_path, same_key, overlap_only):
    case, _, _ = relay_case
    factory, mission, payload, ingress, first_service = await _arrange(case, tmp_path)
    other = (PostgresTimescaleRepository(case.dsn, min_pool_size=1, max_pool_size=2)
             if case.name == "postgres" else SqliteTrendRepository(case.repository._db_path))
    if case.name != "postgres":
        # Authorized fixture setup, before either dispatch owns a read transaction.
        await other._ensure_schema()
    ingress.release.clear()
    key = uuid4().hex
    start = asyncio.Event()

    async def dispatch(service, call_key):
        await start.wait()
        return await _execute(service, payload, key=call_key)

    first = asyncio.create_task(dispatch(first_service, key))
    second = None
    try:
        if overlap_only:
            start.set()
            await asyncio.wait_for(ingress.entered.wait(), timeout=5)
        other.configure_follow_up_verifier(payload["_verifier"])
        second_service = factory(repository=other, mission_executor=_executor(other, ingress),
                                 selected_parent_id=str(mission.id), host_authorized=True,
                                 session_initializer=payload["_initializer"])
        second = asyncio.create_task(dispatch(second_service, key if same_key else uuid4().hex))
        start.set()
        # Common dispatch gate races admissions; overlap-only checks in-flight replay.
        # Either connection may win the common-gate race.
        done, _ = await asyncio.wait((first, second), timeout=5, return_when=asyncio.FIRST_COMPLETED)
        assert len(done) == 1, "One duplicate must return while the canonical probe is held"
        replay_task = next(iter(done))
        replay_result = replay_task.result()
        held = await _inventory(case.repository, mission.id)
        assert len(held["children"]) == len(held["reservations"]) == 1
        ingress.release.set()
        results = await asyncio.wait_for(asyncio.gather(first, second), timeout=5)
        assert results[0]["child_mission_id"] == results[1]["child_mission_id"] == replay_result["child_mission_id"]
        assert results[0]["reservation_id"] == results[1]["reservation_id"] == replay_result["reservation_id"]
        _assert_single(results[0], await _inventory(case.repository, mission.id), payload, ingress)
        await _assert_durable(case, results[0], payload)
        assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"
    finally:
        ingress.release.set()
        for task in (first, second):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task is not None), return_exceptions=True)
        await other.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("quota,cost,reason", ((2, 4, "QUOTA_EXHAUSTED"), (4, 2, "COST_EXHAUSTED")))
async def test_interrupted_probe_retains_unknown_reservation_without_reprobe(relay_case, tmp_path, quota, cost, reason):
    case, _, _ = relay_case
    _, mission, payload, ingress, service = await _arrange(case, tmp_path, quota_ceiling=quota, cost_ceiling=cost)
    ingress.interrupt = True
    with pytest.raises(InterruptedProbe):
        await _execute(service, payload)
    uncertain = await _inventory(case.repository, mission.id)
    reservation = _assert_unresolved(uncertain, payload["reservation_cost"])
    recovered = await _execute(service, payload)
    assert recovered["status"] == "RECONCILIATION_REQUIRED"
    assert recovered["reason_code"] == "UNRESOLVED_EXECUTION"
    assert recovered["child_mission_id"] == uncertain["children"][0]["mission_id"]
    assert recovered["reservation_id"] == reservation["reservation_id"]
    assert await _inventory(case.repository, mission.id) == uncertain
    await _assert_durable(case, recovered, payload)
    from tests.integration.follow_up_execution_setup import sibling
    following = await sibling(case.repository, mission, payload["_authority"])
    next_work = _work_payload(following, payload["reservation_cost"])
    before = await _inventory(case.repository, mission.id)
    refused = await _execute(service, next_work)
    assert refused["status"] == "REFUSED" and refused["reason_code"] == reason
    after = await _inventory(case.repository, mission.id)
    assert after["children"] == before["children"]
    assert after["reservations"] == before["reservations"] == uncertain["reservations"]
    assert ingress.connector_calls == ingress.auth_initializations == 1
    assert ingress.child_executions == [uncertain["children"][0]["mission_id"]]
    assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("relay_case", ("file",), indirect=True)
async def test_negative_sql_fixture_restores_every_guard_after_statement_failure(relay_case, tmp_path):
    """Fixture safety control; setup failure never counts as execution refusal."""
    from tests.integration.follow_up_execution_setup import corrupt_disposable
    case, _, _ = relay_case
    _, mission, payload, ingress, service = await _arrange(case, tmp_path)
    before = _state(case)
    with pytest.raises(sqlite3.OperationalError):
        corrupt_disposable(case, [("research_assignments",
            "UPDATE research_assignments SET missing_negative_column=? WHERE assignment_id=?",
            ("fault", payload["assignment_id"]))])
    assert _state(case) == before
    conn = case.repository._get_connection()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE research_assignments SET actions=? WHERE assignment_id=?",
                         ('["READ"]', payload["assignment_id"]))
        conn.rollback()
    finally:
        conn.close()
    assert _state(case) == before
    assert ingress.auth_initializations == ingress.connector_calls == 0
    assert ingress.child_executions == []
