"""Fact and progress receipts through the real mission producer use cases.

The connector double returns a fixed public observation; storage, use cases,
transactions, and SQL visibility are real. Each backend is disposable.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql

from conftest import (
    RepositoryCase,
    _apply_postgres_schema,
    _drop_test_database,
    _postgres_dsns,
)
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.application.use_cases.confirm_market_brief import ConfirmMarketBriefUseCase
from ignis.application.use_cases.create_attention_mission import CreateAttentionMissionUseCase
from ignis.application.use_cases.create_research_workspace import CreateResearchWorkspaceUseCase
from ignis.application.use_cases.current_evidence_frame import load_current_evidence_frame
from ignis.application.use_cases.execute_mission import ExecuteMissionUseCase
from ignis.application.use_cases.submit_evidence_qualifications import SubmitEvidenceQualificationsUseCase
from ignis.application.use_cases.submit_mission_claims import SubmitMissionClaimsUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.exceptions import RepositoryException
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    MissionManifest,
    MissionOutputType,
    compute_frame_fingerprint,
)
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.connectors.registry import SearchPassResult, SurfaceProbeResult
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository


NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)
BRIEF = {
    "decision": "Should a retailer fund an inventory pilot?",
    "target_user": "Independent retailers",
    "problem": "Manual replenishment causes stockouts",
    "geo": "VN",
    "timeframe": "7d",
    "hypothesis": "A small inventory pilot reduces stockouts",
    "falsifiers": ["Retailers report no material stockout cost"],
    "alternative_hypotheses": ["Process redesign alone solves stockouts", "Outsourcing solves stockouts"],
    "null_hypothesis": "A pilot does not change replenishment decisions",
    "kill_criteria": ["No repeated decision-relevant pain appears"],
    "revision_rule": "Reframe when contradiction equals support",
}


@pytest_asyncio.fixture(params=("sqlite-file", "sqlite-memory", "postgres"))
async def ingress_case(request, tmp_path):
    if request.param.startswith("sqlite"):
        path = str(tmp_path / "ingress.sqlite") if request.param == "sqlite-file" else ":memory:"
        repository = SqliteTrendRepository(path)
        await repository._ensure_schema()
        await repository._ensure_progress_schema()
        case = RepositoryCase(name=request.param, repository=repository)
        try:
            yield case
        finally:
            await repository.close()
        return

    admin_dsn, test_dsn, database_name = _postgres_dsns()
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    try:
        _apply_postgres_schema(test_dsn)
        repository = PostgresTimescaleRepository(dsn=test_dsn, min_pool_size=1, max_pool_size=2)
        try:
            yield RepositoryCase(name="postgres", repository=repository, dsn=test_dsn)
        finally:
            await repository.close()
    finally:
        _drop_test_database(admin_dsn, database_name)


@contextmanager
def _connection(case):
    if case.name == "sqlite-memory":
        if callback := getattr(case, "_t016_fault_callback", None):
            case.repository._mem_conn.create_function("t016_fault_hit", 0, callback)
        yield case.repository._mem_conn
    elif case.name == "sqlite-file":
        with sqlite3.connect(case.repository._db_path) as conn:
            if callback := getattr(case, "_t016_fault_callback", None):
                conn.create_function("t016_fault_hit", 0, callback)
            yield conn
    else:
        with psycopg.connect(case.dsn) as conn:
            yield conn


def _rows(case, table, mission_id, columns="*", *, key="mission_id"):
    placeholder = "%s" if case.name == "postgres" else "?"
    with _connection(case) as conn:
        rows = conn.execute(
            f"SELECT {columns} FROM {table} WHERE {key} = {placeholder}",
            (str(mission_id),),
        ).fetchall()
    return [tuple(row) for row in rows]


def _events(case, mission_id, kind=None):
    placeholder = "%s" if case.name == "postgres" else "?"
    suffix = f" AND kind = {placeholder}" if kind else ""
    values = (str(mission_id), kind) if kind else (str(mission_id),)
    with _connection(case) as conn:
        rows = conn.execute(
            "SELECT kind, run_id, claim_id, evidence_references, revision, ordinal, id, reason"
            " FROM mission_progress_events"
            f" WHERE mission_id = {placeholder}{suffix} ORDER BY revision, ordinal",
            values,
        ).fetchall()
    return [
        (kind, str(run_id) if run_id else None, str(claim_id) if claim_id else None,
         json.loads(refs) if isinstance(refs, str) else refs, int(revision), int(ordinal),
         str(event_id), reason)
        for kind, run_id, claim_id, refs, revision, ordinal, event_id, reason in rows
    ]


def _revision(case, mission_id):
    rows = _rows(case, "mission_progress_revisions", mission_id, "revision")
    return int(rows[0][0]) if rows else 0


def _assert_revision_matches_events(case, mission_id):
    assert _revision(case, mission_id) == max(
        (event[4] for event in _events(case, mission_id)), default=0
    )


@contextmanager
def _refuse_write(case, table, *, kind=None, operation="INSERT"):
    """Deny the physical fact or selected event INSERT without replacing adapter SQL."""
    if case.name.startswith("sqlite"):
        condition = f" WHEN NEW.kind = '{kind}'" if kind else ""
        hits = []
        original_connect = case.repository._get_connection
        if kind:
            def hit():
                hits.append(1)
                return 1

            def instrumented_connect():
                conn = original_connect()
                conn.create_function("t016_fault_hit", 0, hit)
                return conn

            case._t016_fault_callback = hit
            case.repository._get_connection = instrumented_connect
        try:
            with _connection(case) as conn:
                conn.execute(
                    f"CREATE TRIGGER t016_refuse BEFORE {operation} ON {table}{condition}"
                    " BEGIN "
                    + ("SELECT t016_fault_hit(); " if kind else "")
                    + "SELECT RAISE(ABORT, 'Controlled write refusal'); END"
                )
            try:
                yield lambda: len(hits)
            finally:
                with _connection(case) as conn:
                    conn.execute("DROP TRIGGER t016_refuse")
        finally:
            if kind:
                case.repository._get_connection = original_connect
                case._t016_fault_callback = None
                if case.name == "sqlite-memory":
                    case.repository._mem_conn.create_function("t016_fault_hit", 0, None)
        return

    try:
        with psycopg.connect(case.dsn) as conn:
            if kind:
                conn.execute("CREATE SEQUENCE t016_fault_hits START 1")
            predicate = f"IF NEW.kind = '{kind}' THEN" if kind else ""
            ending = "END IF;" if kind else ""
            conn.execute(
                "CREATE FUNCTION t016_refuse() RETURNS trigger LANGUAGE plpgsql AS $$"
                f" BEGIN {predicate} "
                + ("PERFORM nextval('t016_fault_hits'); " if kind else "")
                + "RAISE EXCEPTION 'Controlled write refusal'"
                f" USING ERRCODE='23514'; {ending} RETURN NEW; END $$"
            )
            conn.execute(
                sql.SQL(f"CREATE TRIGGER t016_refuse BEFORE {operation} ON {{}}"
                        " FOR EACH ROW EXECUTE FUNCTION t016_refuse()").format(sql.Identifier(table))
            )

        def hit_count():
            if not kind:
                return 0
            with psycopg.connect(case.dsn) as conn:
                value, called = conn.execute(
                    "SELECT last_value, is_called FROM t016_fault_hits"
                ).fetchone()
            return int(value) if called else 0

        yield hit_count
    finally:
        with psycopg.connect(case.dsn) as conn:
            conn.execute(sql.SQL("DROP TRIGGER IF EXISTS t016_refuse ON {}").format(
                sql.Identifier(table)))
            conn.execute("DROP FUNCTION IF EXISTS t016_refuse()")
            if kind:
                conn.execute("DROP SEQUENCE IF EXISTS t016_fault_hits")


def _manifest(*, market=False):
    return MissionManifest(
        outcome="Inspect one bounded evidence frame",
        decision_context=BRIEF["decision"] if market else None,
        required_channels=("youtube",),
        optional_channels=(),
        authority_boundary=AuthorityBoundary(
            public_http=True, official_api=True, browser_session=False, paid_quota=False
        ),
        quota_budget={},
        output_type=MissionOutputType.MARKET_ANALYSIS if market else MissionOutputType.COLLECTION_FRAME,
        stop_conditions=("one pass completed",),
        analysis_policy="evidence-gated-v1",
        retention_policy="test-only",
        created_by="integration-test",
        confirmed_at=NOW,
    )


async def _workspace(case, tmp_path):
    store = WorkspaceRepository(repository=case.repository)
    creator = CreateResearchWorkspaceUseCase(store=store)
    root = tmp_path / "workspace"
    root.mkdir()
    workspace = await creator.confirm(
        await creator.propose(root, "Ingress progress"), confirmation=True
    )
    return store, workspace


def _signal(label="Bounded observation"):
    return TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title=label,
        source_url=f"https://www.youtube.com/watch?v={uuid4().hex[:11]}",
        geo_code=GeoCode.VN,
        captured_at=NOW,
        metadata={"connector_surface": "youtube", "keyword": "retail stockout"},
    )


class _OneObservationRegistry:
    async def resolve_execution_requirements(self, **_kwargs):
        return {"resources": ("youtube",), "authority": ("public_http",), "quota_costs": {}}

    async def search_with_outcomes(self, **kwargs):
        return SearchPassResult(
            signals=[_signal()],
            outcomes=[SurfaceProbeResult(
                platform="youtube", connector_surface="youtube",
                status=ChannelHealthStatus.HEALTHY, signals_collected=1,
                queried_keywords=tuple(kwargs["keywords"]), queried_window=kwargs["custom_timeframe"],
            )],
        )


class _NoNewObservationRegistry(_OneObservationRegistry):
    async def search_with_outcomes(self, **kwargs):
        return SearchPassResult(
            signals=[],
            outcomes=[SurfaceProbeResult(
                platform="youtube", connector_surface="youtube",
                status=ChannelHealthStatus.RATE_LIMITED, signals_collected=0,
                queried_keywords=tuple(kwargs["keywords"]), queried_window=kwargs["custom_timeframe"],
            )],
        )


class _NoClusters:
    async def cluster_signals(self, _signals):
        return []


async def _attention(case, tmp_path):
    store, workspace = await _workspace(case, tmp_path)
    mission = await CreateAttentionMissionUseCase(case.repository, store).execute(
        workspace_id=workspace.workspace_id,
        title="Observed collection",
        keywords=["retail stockout"],
        platforms=[PlatformType.YOUTUBE],
        manifest=_manifest(),
    )
    executor = ExecuteMissionUseCase(case.repository, _OneObservationRegistry(), _NoClusters(), store)
    return store, mission, executor


async def _market(case, tmp_path):
    store, workspace = await _workspace(case, tmp_path)
    mission, brief = await ConfirmMarketBriefUseCase(case.repository, store).execute(
        workspace_id=workspace.workspace_id,
        confirmed_by="requester",
        keywords=["retail stockout"],
        manifest=_manifest(market=True),
        **BRIEF,
    )
    executor = ExecuteMissionUseCase(case.repository, _OneObservationRegistry(), _NoClusters(), store)
    assert (await executor.execute(mission.id))["status"] == "COMPLETED"
    held = (await case.repository.get_mission_signals(mission.id))[0]
    return store, mission, brief, held


def _qualification(signal):
    return {
        "observation_id": str(signal.observation_id),
        "relation": "QUALIFIED_SUPPORT", "purpose": "DEMAND", "confidence": 0.9,
        "reason_code": "DIRECT_TO_FRAME", "judged_by": "integration-host",
        "hypothesis_target": "core", "evidence_role": "SUPPORT",
    }


async def _submit_qualification(case, store, mission, brief, signal):
    return await SubmitEvidenceQualificationsUseCase(case.repository, store).execute(
        str(mission.id), compute_frame_fingerprint(mission, brief), [_qualification(signal)]
    )


async def _submit_claim(case, store, mission):
    held = (await case.repository.get_mission_signals(mission.id))[0]
    brief = await store.get_brief_revision_for_mission(mission.id)
    assert (await _submit_qualification(case, store, mission, brief, held))["status"] == "RECORDED"
    frame = await load_current_evidence_frame(case.repository, store, mission)
    return await SubmitMissionClaimsUseCase(case.repository, store).execute(
        str(mission.id), frame.frame_digest,
        [{"client_claim_key": "bounded-candidate", "claim_type": "OBSERVATION",
          "wording": "One retailer reported a stockout.",
          "evidence_bindings": [{
              "observation_id": str(held.observation_id), "role": "SUPPORT",
              "hypothesis_target": "core",
          }]}],
        created_by="integration-host",
    )


@pytest.mark.asyncio
async def test_collection_commits_canonical_observation_membership_and_receipt(ingress_case, tmp_path):
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    result = await executor.execute(mission.id)
    assert result["status"] == "COMPLETED"
    evidence = _rows(case, "mission_evidence", mission.id, "observation_id")
    assert len(evidence) == 1
    with _connection(case) as conn:
        source_observation = conn.execute(
            "SELECT o.id, o.source_id FROM observations o JOIN sources s ON s.id = o.source_id"
        ).fetchall()
    assert len(source_observation) == 1
    observation_id, source_id = map(str, source_observation[0])
    assert str(evidence[0][0]) == observation_id
    events = _events(case, mission.id, "OBSERVATIONS_COMMITTED")
    assert len(events) == 1, "A committed observation and membership need one durable arrival receipt"
    assert events[0][1] == result["run"]["run_id"]
    assert events[0][3] == [{
        "mission_id": str(mission.id), "observation_id": observation_id,
        "source_id": source_id, "evidence_role": "ATTENTION_CONTEXT",
        "direction": None, "qualification_relation": None,
        "qualification_frame_fingerprint": None,
    }]
    outcomes = _events(case, mission.id, "PROBE_OUTCOMES_RECORDED")
    assert len(outcomes) == 1 and outcomes[0][3] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", (
    "COLLECTION_STARTED", "OBSERVATIONS_COMMITTED", "QUALIFICATION_RECORDED", "CLAIM_GATE_CHANGED",
))
async def test_selective_event_refusal_trigger_is_a_physical_control_only(ingress_case, tmp_path, kind):
    """Direct SQL checks the fault gate; it is not evidence of producer behavior."""
    case = ingress_case
    store, mission, _executor = await _attention(case, tmp_path)
    run_id = uuid4()
    await store.record_run_journal(RunJournal(
        run_id=run_id, mission_id=mission.id, workspace_id=mission.workspace_id,
        journal_path=tmp_path / "physical-control.json", sequence=1,
        status="STARTED", started_at=NOW,
    ))
    before_events = _events(case, mission.id)
    before_revision = _rows(case, "mission_progress_revisions", mission.id, "revision")
    placeholder = "%s" if case.name == "postgres" else "?"
    statement = (
        "INSERT INTO mission_progress_events"
        " (mission_id, revision, ordinal, kind, provenance, causation_key, run_id)"
        f" VALUES ({', '.join([placeholder] * 7)})"
    )
    with _refuse_write(case, "mission_progress_events", kind=kind) as fault_hits:
        with pytest.raises((sqlite3.DatabaseError, psycopg.Error), match="Controlled write refusal") as refusal:
            with _connection(case) as conn:
                conn.execute(statement, (
                    str(mission.id), 1, 1, kind,
                    "HARNESS_OBSERVED", "physical-control",
                    str(run_id) if kind in ("COLLECTION_STARTED", "OBSERVATIONS_COMMITTED") else None,
                ))
        assert fault_hits() == 1
    if case.name == "postgres":
        assert refusal.value.sqlstate == "23514"
    else:
        assert refusal.value.sqlite_errorname == "SQLITE_CONSTRAINT_TRIGGER"
    assert _events(case, mission.id) == before_events
    assert _rows(case, "mission_progress_revisions", mission.id, "revision") == before_revision


@pytest.mark.asyncio
async def test_collection_started_and_terminal_state_have_distinct_durable_receipts(ingress_case, tmp_path):
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    result = await executor.execute(mission.id)
    run_id = result["run"]["run_id"]
    assert _rows(case, "research_missions", mission.id, "status", key="id") == [("COMPLETED",)]
    started = _events(case, mission.id, "COLLECTION_STARTED")
    settled = _events(case, mission.id, "COLLECTION_STATE_CHANGED")
    assert len(started) == len(settled) == 1
    assert started[0][1] == settled[0][1] == run_id
    assert started[0][7] == "RUNNING"
    assert settled[0][7] == "COMPLETED"
    assert started[0][4:6] < settled[0][4:6]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", (
    "OBSERVATIONS_COMMITTED", "COLLECTION_STARTED", "COLLECTION_STATE_CHANGED",
))
async def test_collection_event_refusal_rolls_back_only_its_fact_unit(ingress_case, tmp_path, kind):
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    before_evidence = _rows(case, "mission_evidence", mission.id, "observation_id")
    before_selected_events = _events(case, mission.id, kind)
    with _refuse_write(case, "mission_progress_events", kind=kind) as fault_hits:
        try:
            await executor.execute(mission.id)
        except (sqlite3.DatabaseError, psycopg.Error, RepositoryException):
            refused = True
        else:
            refused = False
        reached_selected_event = fault_hits() > 0
    event_rows = _events(case, mission.id, kind)
    evidence_rows = _rows(case, "mission_evidence", mission.id, "observation_id")
    status_rows = _rows(case, "research_missions", mission.id, "status", key="id")
    arrival_rows = _events(case, mission.id, "OBSERVATIONS_COMMITTED")
    outcome_rows = _events(case, mission.id, "PROBE_OUTCOMES_RECORDED")
    with _connection(case) as conn:
        observation_count = conn.execute("SELECT count(*) FROM observations").fetchone()[0]
    assert event_rows == before_selected_events
    _assert_revision_matches_events(case, mission.id)
    if kind == "OBSERVATIONS_COMMITTED":
        assert evidence_rows == before_evidence and observation_count == 0
    elif kind == "COLLECTION_STARTED":
        assert status_rows not in ([("RUNNING",)], [("COMPLETED",)])
        assert evidence_rows == [] and outcome_rows == []
    else:
        # A failed terminal transition leaves the earlier RUNNING, observation,
        # and probe-fact units durable. The FAILED fallback hits this same fault.
        assert status_rows == [("RUNNING",)]
        assert len(evidence_rows) == observation_count == len(arrival_rows) == len(outcome_rows) == 1
    assert reached_selected_event, "Collection must reach the selected event fault"
    assert refused, "A selected event fault must refuse its fact transaction"


@pytest.mark.asyncio
async def test_prune_refusal_preserves_prior_membership_and_earlier_committed_arrival(ingress_case, tmp_path):
    """A failed later pass unit cannot erase earlier committed evidence or its receipt."""
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    prior = _signal("Prior observation")
    prior.mission_id = mission.id
    await case.repository.save_signals([prior])
    old_id = str((await case.repository.get_mission_signals(mission.id))[0].observation_id)
    with _refuse_write(case, "mission_evidence", operation="DELETE"):
        with pytest.raises((sqlite3.DatabaseError, psycopg.Error, RepositoryException)):
            await executor.execute(mission.id)
    held = {str(row[0]) for row in _rows(case, "mission_evidence", mission.id, "observation_id")}
    assert len(held) == 2 and old_id in held
    arrived = (held - {old_id}).pop()
    events = _events(case, mission.id, "OBSERVATIONS_COMMITTED")
    assert len(events) == 1, "The earlier committed arrival cannot vanish with a later prune failure"
    assert [ref["observation_id"] for ref in events[0][3]] == [arrived]


@pytest.mark.asyncio
async def test_preserved_observation_reattaches_membership_without_new_arrival(
    ingress_case, tmp_path, monkeypatch,
):
    """A controlled external prune after a real read exposes the re-attach path."""
    case = ingress_case
    store, mission, _executor = await _attention(case, tmp_path)
    prior = _signal("Preserved observation")
    prior.mission_id = mission.id
    await case.repository.save_signals([prior])
    before_membership = _rows(case, "mission_evidence", mission.id, "observation_id")
    assert len(before_membership) == 1
    with _connection(case) as conn:
        before_lineage = [tuple(row) for row in conn.execute(
            "SELECT o.id, o.source_id FROM observations o ORDER BY o.id"
        ).fetchall()]
    assert len(before_lineage) == 1
    observation_id, source_id = map(str, before_lineage[0])
    assert str(before_membership[0][0]) == observation_id

    original_read = case.repository.get_mission_signals
    detached_membership = []

    async def read_then_prune(mission_id):
        snapshot = await original_read(mission_id)
        if mission_id == mission.id and not detached_membership:
            assert [str(item.observation_id) for item in snapshot] == [observation_id]
            assert await case.repository.prune_mission_evidence(mission.id, []) == 1
            detached_membership.append(_rows(case, "mission_evidence", mission.id,
                                             "observation_id"))
        return snapshot

    monkeypatch.setattr(case.repository, "get_mission_signals", read_then_prune)
    executor = ExecuteMissionUseCase(
        case.repository, _NoNewObservationRegistry(), _NoClusters(), store
    )
    result = await executor.execute(mission.id)
    assert result["status"] == "COMPLETED"
    assert detached_membership == [[]]
    assert _rows(case, "mission_evidence", mission.id, "observation_id") == before_membership
    with _connection(case) as conn:
        after_lineage = [tuple(row) for row in conn.execute(
            "SELECT o.id, o.source_id FROM observations o ORDER BY o.id"
        ).fetchall()]
    assert after_lineage == before_lineage
    receipts = _events(case, mission.id, "OBSERVATIONS_COMMITTED")
    assert len(receipts) == 1
    assert receipts[0][1] == result["run"]["run_id"]
    assert receipts[0][7] == "MEMBERSHIP_REATTACHED"
    assert receipts[0][3] == [{
        "mission_id": str(mission.id), "observation_id": observation_id,
        "source_id": source_id, "evidence_role": "ATTENTION_CONTEXT",
        "direction": None, "qualification_relation": None,
        "qualification_frame_fingerprint": None,
    }]


@pytest.mark.asyncio
async def test_preserved_observation_with_existing_membership_has_no_new_receipt(
    ingress_case, tmp_path,
):
    """A preserved no-op attachment is not a new observation or membership delta."""
    case = ingress_case
    store, mission, _executor = await _attention(case, tmp_path)
    prior = _signal("Already attached observation")
    prior.mission_id = mission.id
    await case.repository.save_signals([prior])
    before_membership = _rows(
        case, "mission_evidence", mission.id, "id, observation_id, recorded_at"
    )
    assert len(before_membership) == 1
    with _connection(case) as conn:
        before_lineage = [tuple(row) for row in conn.execute(
            "SELECT o.id, o.source_id FROM observations o ORDER BY o.id"
        ).fetchall()]
    assert len(before_lineage) == 1
    assert str(before_membership[0][1]) == str(before_lineage[0][0])
    before_receipts = _events(case, mission.id, "OBSERVATIONS_COMMITTED")

    executor = ExecuteMissionUseCase(
        case.repository, _NoNewObservationRegistry(), _NoClusters(), store
    )
    result = await executor.execute(mission.id)
    assert result["status"] == "COMPLETED"
    assert _rows(case, "mission_evidence", mission.id,
                 "id, observation_id, recorded_at") == before_membership
    with _connection(case) as conn:
        after_lineage = [tuple(row) for row in conn.execute(
            "SELECT o.id, o.source_id FROM observations o ORDER BY o.id"
        ).fetchall()]
    assert after_lineage == before_lineage
    assert _events(case, mission.id, "OBSERVATIONS_COMMITTED") == before_receipts


@pytest.mark.asyncio
async def test_collection_observation_fact_refusal_has_no_arrival_receipt(ingress_case, tmp_path):
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    before_facts = _rows(case, "mission_evidence", mission.id, "observation_id")
    before_events = _events(case, mission.id)
    before_revision = _revision(case, mission.id)
    with _refuse_write(case, "observations"):
        with pytest.raises((sqlite3.DatabaseError, psycopg.Error, RepositoryException)):
            await executor.execute(mission.id)
    assert _rows(case, "mission_evidence", mission.id, "observation_id") == before_facts
    after_events = _events(case, mission.id)
    assert after_events[:len(before_events)] == before_events
    later = after_events[len(before_events):]
    assert [(event[0], event[7]) for event in later] == [
        ("COLLECTION_STARTED", "RUNNING"),
        ("COLLECTION_STATE_CHANGED", "FAILED"),
    ]
    assert _events(case, mission.id, "OBSERVATIONS_COMMITTED") == []
    assert _revision(case, mission.id) == before_revision + len(later)
    _assert_revision_matches_events(case, mission.id)


@pytest.mark.asyncio
async def test_collection_state_fact_refusal_has_no_start_receipt(ingress_case, tmp_path):
    case = ingress_case
    _store, mission, executor = await _attention(case, tmp_path)
    before = _rows(case, "research_missions", mission.id, "status", key="id")
    before_events = _events(case, mission.id)
    before_revision = _revision(case, mission.id)
    with _refuse_write(case, "research_missions", operation="UPDATE"):
        with pytest.raises((sqlite3.DatabaseError, psycopg.Error, RepositoryException)):
            await executor.execute(mission.id)
    assert _rows(case, "research_missions", mission.id, "status", key="id") == before
    assert _events(case, mission.id) == before_events
    assert _revision(case, mission.id) == before_revision


@pytest.mark.asyncio
async def test_qualification_commits_canonical_fact_and_receipt(ingress_case, tmp_path):
    case = ingress_case
    store, mission, brief, signal = await _market(case, tmp_path)
    result = await _submit_qualification(case, store, mission, brief, signal)
    assert result["status"] == "RECORDED"
    rows = _rows(case, "mission_evidence_qualifications", mission.id,
                 "id, observation_id, frame_fingerprint")
    assert [(str(oid), frame) for _fact_id, oid, frame in rows] == [
        (str(signal.observation_id), compute_frame_fingerprint(mission, brief))
    ]
    events = _events(case, mission.id, "QUALIFICATION_RECORDED")
    first_revision = _revision(case, mission.id)
    assert (await _submit_qualification(case, store, mission, brief, signal))["status"] == "RECORDED"
    replay_rows = _rows(case, "mission_evidence_qualifications", mission.id,
                        "id, observation_id, frame_fingerprint")
    replay_events = _events(case, mission.id, "QUALIFICATION_RECORDED")
    assert replay_rows == rows
    assert replay_events == events
    assert _revision(case, mission.id) == first_revision
    assert len(events) == 1, "A recorded judgment needs a durable matching receipt"
    assert events[0][1] is None
    assert events[0][3] == [{
        "mission_id": str(mission.id), "observation_id": str(signal.observation_id),
        "source_id": str(signal.source_id), "evidence_role": "MARKET_EVIDENCE",
        "direction": "SUPPORT", "qualification_relation": "QUALIFIED_SUPPORT",
        "qualification_frame_fingerprint": compute_frame_fingerprint(mission, brief),
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize("table,kind", (
    ("mission_progress_events", "QUALIFICATION_RECORDED"),
    ("mission_evidence_qualifications", None),
))
async def test_qualification_refusal_leaves_neither_fact_nor_receipt(ingress_case, tmp_path, table, kind):
    case = ingress_case
    store, mission, brief, signal = await _market(case, tmp_path)
    before_facts = _rows(case, "mission_evidence_qualifications", mission.id)
    before_events = _events(case, mission.id, "QUALIFICATION_RECORDED")
    before_revision = _revision(case, mission.id)
    with _refuse_write(case, table, kind=kind) as fault_hits:
        try:
            result = await _submit_qualification(case, store, mission, brief, signal)
        except (sqlite3.DatabaseError, psycopg.Error, RepositoryException):
            result = None
        reached_selected_event = fault_hits() > 0 if kind else None
    facts = _rows(case, "mission_evidence_qualifications", mission.id)
    events = _events(case, mission.id, "QUALIFICATION_RECORDED")
    revision = _revision(case, mission.id)
    assert (facts, events, revision) == (before_facts, before_events, before_revision)
    _assert_revision_matches_events(case, mission.id)
    if kind:
        assert reached_selected_event, "Qualification must reach the selected event fault"
    if result is not None:
        assert result["status"] == "INVALID"
        if table == "mission_evidence_qualifications":
            assert result["reason_code"] == "FOREIGN_OBSERVATION"


@pytest.mark.asyncio
async def test_claim_submission_commits_ledger_fact_and_gate_receipt(ingress_case, tmp_path):
    case = ingress_case
    store, mission, _brief, signal = await _market(case, tmp_path)
    result = await _submit_claim(case, store, mission)
    assert result["status"] == "RECORDED"
    rows = _rows(case, "mission_claims", mission.id, "id, frame_digest, status")
    assert len(rows) == 1
    claim_id, frame_digest, status = rows[0]
    assert frame_digest == result["frame_digest"] and status == "WITHHELD"
    with _connection(case) as conn:
        placeholder = "%s" if case.name == "postgres" else "?"
        bindings = conn.execute(
            "SELECT observation_id FROM mission_claim_evidence"
            f" WHERE claim_id = {placeholder}", (str(claim_id),),
        ).fetchall()
    assert [str(row[0]) for row in bindings] == [str(signal.observation_id)]
    events = _events(case, mission.id, "CLAIM_GATE_CHANGED")
    first_revision = _revision(case, mission.id)
    assert (await _submit_claim(case, store, mission))["status"] == "RECORDED"
    replay_rows = _rows(case, "mission_claims", mission.id, "id, frame_digest, status")
    replay_events = _events(case, mission.id, "CLAIM_GATE_CHANGED")
    assert replay_rows == rows
    assert replay_events == events
    assert _revision(case, mission.id) == first_revision
    assert len(events) == 1, "A recorded candidate needs a durable claim-gate receipt"
    assert events[0][1] is None and events[0][2] == str(claim_id)
    assert events[0][3][0]["mission_id"] == str(mission.id)
    assert events[0][3][0]["observation_id"] == str(signal.observation_id)
    assert events[0][3][0]["source_id"] == str(signal.source_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("table,kind", (
    ("mission_progress_events", "CLAIM_GATE_CHANGED"),
    ("mission_claims", None),
))
async def test_claim_refusal_leaves_neither_ledger_fact_nor_receipt(ingress_case, tmp_path, table, kind):
    case = ingress_case
    store, mission, brief, signal = await _market(case, tmp_path)
    assert (await _submit_qualification(case, store, mission, brief, signal))["status"] == "RECORDED"
    before_facts = _rows(case, "mission_claims", mission.id)
    before_events = _events(case, mission.id, "CLAIM_GATE_CHANGED")
    before_revision = _revision(case, mission.id)
    with _refuse_write(case, table, kind=kind) as fault_hits:
        try:
            result = await _submit_claim(case, store, mission)
        except (sqlite3.DatabaseError, psycopg.Error, RepositoryException):
            result = None
        reached_selected_event = fault_hits() > 0 if kind else None
    facts = _rows(case, "mission_claims", mission.id)
    events = _events(case, mission.id, "CLAIM_GATE_CHANGED")
    revision = _revision(case, mission.id)
    assert (facts, events, revision) == (before_facts, before_events, before_revision)
    _assert_revision_matches_events(case, mission.id)
    if kind:
        assert reached_selected_event, "Claim must reach the selected event fault"
    if result is not None:
        assert result["status"] == "INVALID"
        if table == "mission_claims":
            assert result["reason_code"] == "INVALID_CLAIM_BATCH"


@pytest.mark.asyncio
async def test_stale_claim_frame_refuses_fact_and_event(ingress_case, tmp_path):
    case = ingress_case
    store, mission, _brief, _signal_record = await _market(case, tmp_path)
    frame = await load_current_evidence_frame(case.repository, store, mission)
    later = _signal("Later observation")
    later.mission_id = mission.id
    await case.repository.save_signals([later])
    result = await SubmitMissionClaimsUseCase(case.repository, store).execute(
        str(mission.id), frame.frame_digest,
        [{"client_claim_key": "stale", "claim_type": "UNKNOWN", "wording": "Stale candidate."}],
        created_by="integration-host",
    )
    assert result["status"] == "CONFLICT" and result["reason_code"] == "STALE_FRAME"
    assert _rows(case, "mission_claims", mission.id) == []
    assert _events(case, mission.id, "CLAIM_GATE_CHANGED") == []


@pytest.mark.asyncio
async def test_stale_qualification_frame_refuses_fact_and_event(ingress_case, tmp_path):
    case = ingress_case
    store, mission, _brief, signal = await _market(case, tmp_path)
    result = await SubmitEvidenceQualificationsUseCase(case.repository, store).execute(
        str(mission.id), "0" * 64, [_qualification(signal)]
    )
    assert result["status"] == "CONFLICT" and result["reason_code"] == "STALE_FRAME"
    assert _rows(case, "mission_evidence_qualifications", mission.id) == []
    assert _events(case, mission.id, "QUALIFICATION_RECORDED") == []


@pytest.mark.asyncio
async def test_legacy_adhoc_signal_write_keeps_existing_signature_and_no_mission_receipt(ingress_case):
    case = ingress_case
    await case.repository.save_signals([_signal("Unscoped tactical observation")])
    with _connection(case) as conn:
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM mission_progress_events").fetchone()[0] == 0
