"""T068 executable test design; missing future APIs are not behavioral RED.

The four public execution arguments follow contracts/follow-up.md. Internal DI,
record/load payloads and reason tokens below are proposed seams for T070-T075,
not implemented interfaces. Only external ingress is doubled; admission and
reservation must run on the fixture's physical store. No live credentials.
"""

import asyncio
import importlib
import inspect
import sqlite3
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID, uuid4

import psycopg
from psycopg import sql
import pytest

from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
from tests.integration.test_mission_relay_read_boundary import NOW, _state, relay_case as _relay_case
from tests.unit.test_mission_claims import _eligible_mission

relay_case = _relay_case
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
    for name in ("record_mission_follow_up", "load_mission_follow_ups"):
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
        async def execute(self, mission_id):
            ingress.child_executions.append(str(mission_id))
            return await actual.execute(mission_id)

    return ObservedExecutor()


async def _arrange(case, tmp_path, **changes):
    """Record explicit collection authority; never promote ANALYZE-only US4 work."""
    factory = _api(case.repository)
    _, store, mission, _, frame = await _eligible_mission(tmp_path, repository=case.repository)
    mission.status = "COMPLETED"
    await case.repository.update_mission(mission)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    payload = {
        "parent_mission_id": str(mission.id), "assignment_id": str(uuid4()),
        "work_id": str(uuid4()), "gap_id": str(uuid4()), "research_epoch": 1,
        "assignment_version": 1, "work_version": 1, "research_state": "ACTIVE",
        "cancel_requested": False, "actions": ["ANALYZE", "FOLLOW_UP"],
        "allowed_sources": ["youtube"],
        "approved_queries": ["retail stockout", *evidence.brief.falsifiers],
        "work_sources": ["youtube"],
        "work_queries": ["retail stockout", *evidence.brief.falsifiers],
        "session_authorized": True, "deadline": (NOW + timedelta(hours=1)).isoformat(),
        "quota_ceiling": 4, "cost_ceiling": 4, "reservation_cost": 2,
        "manifest_digest": frame.manifest_digest,
        "brief_revision_id": str(evidence.brief.brief_revision_id),
        "frame_digest": frame.frame_digest,
        "observation_ids": sorted(str(signal.observation_id) for signal in evidence.signals),
        "expected_manifest_digest": frame.manifest_digest,
        "expected_brief_revision_id": str(evidence.brief.brief_revision_id),
        "expected_frame_digest": frame.frame_digest,
        "stop_requested": False,
    }
    payload.update(changes)
    # Proposed owner-recording port: it must persist the supplied state, including
    # invalid execution candidates, without silently granting execution authority.
    await case.repository.record_mission_follow_up(payload, host_authorized=True)
    ingress = Ingress()
    ingress.release.set()
    service = factory(repository=case.repository, mission_executor=_executor(case.repository, ingress),
                      selected_parent_id=str(mission.id), clock=lambda: NOW,
                      session_initializer=ingress.initialize_session)
    assert set(inspect.signature(service.execute).parameters) == {
        "mission_id", "follow_up_work_id", "expected_research_epoch", "idempotency_key",
    }
    recorded = await _inventory(case.repository, mission.id)
    assert recorded["work_items"][payload["work_id"]] == payload
    return factory, mission, payload, ingress, service


async def _inventory(repository, mission_id):
    result = await repository.load_mission_follow_ups(str(mission_id))
    return deepcopy(result.to_payload())


async def _execute(service, payload, *, epoch=None, key=None, parent=None):
    result = await service.execute(
        mission_id=parent or payload["parent_mission_id"],
        follow_up_work_id=payload["work_id"],
        expected_research_epoch=payload["research_epoch"] if epoch is None else epoch,
        idempotency_key=key or uuid4().hex,
    )
    return result.to_payload()


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
    assert child.platforms == payload["work_sources"]
    manifest = await case.repository.get_mission_manifest(child.id)
    assert manifest is not None
    assert set(manifest.allowed_resources) == set(payload["work_sources"])
    required = {"reservation_id", "child_mission_id", "parent_mission_id"}
    if case.name == "postgres":
        with psycopg.connect(case.dsn) as conn:
            columns = conn.execute("SELECT table_name, column_name FROM information_schema.columns "
                                   "WHERE table_schema='public'").fetchall()
            tables = {}
            for table, column in columns:
                tables.setdefault(table, set()).add(column)
            matches = [table for table, names in tables.items() if required <= names]
            assert len(matches) == 1, "One canonical physical reservation relation is required"
            rows = conn.execute(sql.SQL("SELECT reservation_id, child_mission_id FROM {} "
                                        "WHERE parent_mission_id=%s").format(sql.Identifier(matches[0])),
                                (UUID(payload["parent_mission_id"]),)).fetchall()
    else:
        conn = case.repository._mem_conn
        owned = conn is None
        if owned:
            conn = sqlite3.connect(case.repository._db_path)
        try:
            names = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            # Identifiers are engine-owned schema names, never caller strings.
            matches = [name for name in names if required <= {
                row[1] for row in conn.execute('PRAGMA table_info("' + name.replace('"', '""') + '")')
            }]
            assert len(matches) == 1, "One canonical physical reservation relation is required"
            rows = conn.execute('SELECT reservation_id, child_mission_id FROM "' +
                                matches[0].replace('"', '""') + '" WHERE parent_mission_id=?',
                                (payload["parent_mission_id"],)).fetchall()
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
        second_service = factory(repository=other, mission_executor=_executor(other, ingress),
                                 selected_parent_id=str(mission.id), clock=lambda: NOW,
                      session_initializer=ingress.initialize_session)
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
    next_work = {**payload, "work_id": str(uuid4()), "gap_id": str(uuid4())}
    await case.repository.record_mission_follow_up(next_work, host_authorized=True)
    before = await _inventory(case.repository, mission.id)
    refused = await _execute(service, next_work)
    assert refused["status"] == "REFUSED" and refused["reason_code"] == reason
    after = await _inventory(case.repository, mission.id)
    assert after["children"] == before["children"]
    assert after["reservations"] == before["reservations"] == uncertain["reservations"]
    assert ingress.connector_calls == ingress.auth_initializations == 1
    assert ingress.child_executions == [uncertain["children"][0]["mission_id"]]
    assert (await case.repository.get_mission(mission.id)).status == "COMPLETED"
