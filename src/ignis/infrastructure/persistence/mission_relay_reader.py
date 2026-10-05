"""Dedicated no-bootstrap SQLite reads of one committed mission view.

The returned records are internal evidence, not an outward serialization boundary.
SQLite may manage WAL/SHM coordination for an existing file; schema and evidence
writes remain prohibited by the read-only connection and query-only transaction.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row, tuple_row

from ignis.application.cancellation import await_settled
from ignis.application.ports.mission_relay_port import (
    IMissionRelayReader,
    MissionRelayRead,
    MissionRelayReadRequest,
)
from ignis.application.ports.research_workspace_port import MissionEvidenceSnapshot, RunJournal
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    MissionRelayEventPage,
    MissionRelayReadFailure,
    RelayEvidenceReference,
    RelayProvenance,
    RelayReadReason,
    RelayReadStatus,
)
from ignis.domain.research_workspace import (
    EvidenceDirection,
    EvidenceRole,
    IncompleteMarketBriefError,
    InvalidEvidenceQualificationError,
    InvalidMissionClaimError,
    InvalidMissionManifestError,
    MissionProbeOutcome,
    QualificationRelation,
)
from ignis.domain.value_objects import GeoCode, PlatformType, resolve_geo, resolve_timeframe
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository, _platforms_of
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository


# Explicit column reads detect incompatible empty tables as well as populated ones.
_SCHEMA_COLUMNS = {
    "research_missions": "id,title,keywords,platforms,shortcode,geo_code,timeframe,status,agent,session_id,summary,workspace_id,surface,parent_attention_mission_id,parent_cluster_id,brief_revision_id,revises_mission_id,created_at,updated_at",
    "mission_run_journals": "id,workspace_id,mission_id,journal_path,sequence,status,started_at,completed_at",
    "sources": "id,platform",
    "observations": "id,source_id,observed_title,metric_value,growth_velocity,source_url,geo_code,metadata,observed_at,published_at,cluster_id,identity_source,time_provenance",
    "mission_evidence": "mission_id,observation_id",
    "mission_manifests": "mission_id,outcome,decision_context,required_channels,optional_channels,authority_boundary,quota_budget,output_type,stop_conditions,analysis_policy,retention_policy,created_by,confirmed_at",
    "market_brief_revisions": "id,workspace_id,mission_id,revision_number,decision,target_user,problem,geo,timeframe,hypothesis,falsifiers,alternative_hypotheses,null_hypothesis,kill_criteria,revision_rule,evidence_contract_version,confirmed_by,confirmed_at",
    "mission_evidence_qualifications": "mission_id,observation_id,brief_revision_id,frame_fingerprint,relation,purpose,confidence,reason_code,judged_by,model,hypothesis_target,evidence_role,evidence_contract_version,created_at",
    "mission_probe_outcomes": "id,run_id,platform,connector_surface,status,signals_collected,query_fingerprint,completed_at,queried_keywords,queried_window,scope_attestation,note,collection_plan_digest",
    "mission_claims": "id,mission_id,brief_revision_id,frame_digest,client_claim_key,claim_type,wording,inference_method,metric_denominator,metric_timeframe,confidence,limitations,change_conditions,status,withheld_reasons,created_by,created_at",
    "mission_claim_evidence": "id,claim_id,observation_id,probe_outcome_id,role,hypothesis_target",
    "mission_progress_revisions": "mission_id,revision",
    "mission_progress_events": "id,mission_id,revision,ordinal,kind,provenance,causation_key,occurred_at,recorded_at,run_id,work_id,handoff_id,finding_id,claim_id,evidence_references,reason",
    "mission_progress_commands": "mission_id,command_key,payload_fingerprint,outcome_count,run_id,event_id,revision,ordinal,event_kind,event_provenance",
}


def _uuid(value):
    return UUID(value) if value is not None else None


def _time(value):
    return datetime.fromisoformat(value) if value is not None else None


def _mission(row) -> ResearchMission:
    mission = ResearchMission(
        id=UUID(row["id"]), title=row["title"], keywords=json.loads(row["keywords"] or "[]"),
        platforms=_platforms_of(row), shortcode=row["shortcode"], geo_code=resolve_geo(row["geo_code"]),
        timeframe=resolve_timeframe(row["timeframe"]), status=row["status"], agent=row["agent"],
        session_id=row["session_id"], summary=row["summary"], workspace_id=_uuid(row["workspace_id"]),
        surface=row["surface"], parent_attention_mission_id=_uuid(row["parent_attention_mission_id"]),
        parent_cluster_id=_uuid(row["parent_cluster_id"]), brief_revision_id=_uuid(row["brief_revision_id"]),
        revises_mission_id=_uuid(row["revises_mission_id"]), created_at=_time(row["created_at"]),
        updated_at=_time(row["updated_at"]),
    )
    # ResearchMission generates a missing shortcode on construction; this view retains storage.
    mission.shortcode = row["shortcode"]
    return mission


def _signal(row) -> TrendSignal:
    return TrendSignal(
        platform=PlatformType(row["platform"]), raw_title=row["observed_title"],
        metric_value=row["metric_value"], growth_velocity=row["growth_velocity"],
        source_url=row["source_url"], geo_code=GeoCode(row["geo_code"]),
        cluster_id=_uuid(row["cluster_id"]), mission_id=UUID(row["mission_id"]),
        observation_id=UUID(row["id"]), source_id=UUID(row["source_id"]),
        identity_source=row["identity_source"], time_provenance=row["time_provenance"],
        metadata=json.loads(row["metadata"] or "{}"), captured_at=_time(row["observed_at"]),
        published_at=_time(row["published_at"]),
    )


def _outcome(row) -> MissionProbeOutcome:
    return MissionProbeOutcome(
        outcome_id=UUID(row["id"]), run_id=UUID(row["run_id"]), platform=row["platform"],
        connector_surface=row["connector_surface"], status=row["status"],
        signals_collected=row["signals_collected"], query_fingerprint=row["query_fingerprint"],
        completed_at=_time(row["completed_at"]), queried_keywords=tuple(json.loads(row["queried_keywords"] or "[]")),
        queried_window=row["queried_window"], scope_attestation=json.loads(row["scope_attestation"])
        if row["scope_attestation"] is not None else None,
        note=row["note"], collection_plan_digest=row["collection_plan_digest"],
    )


def _event(row) -> MissionProgressEvent:
    references = tuple(
        RelayEvidenceReference(
            mission_id=UUID(ref["mission_id"]), observation_id=UUID(ref["observation_id"]),
            source_id=UUID(ref["source_id"]), evidence_role=EvidenceRole(ref["evidence_role"]),
            direction=EvidenceDirection(ref["direction"]) if ref["direction"] is not None else None,
            qualification_relation=QualificationRelation(ref["qualification_relation"])
            if ref["qualification_relation"] is not None else None,
            qualification_frame_fingerprint=ref["qualification_frame_fingerprint"],
        )
        for ref in json.loads(row["evidence_references"])
    )
    return MissionProgressEvent(
        event_id=UUID(row["id"]),
        cursor=MissionRelayCursor(mission_id=UUID(row["mission_id"]), revision=row["revision"], ordinal=row["ordinal"]),
        kind=MissionProgressKind(row["kind"]), provenance=RelayProvenance(row["provenance"]),
        recorded_at=_time(row["recorded_at"]), occurred_at=_time(row["occurred_at"]),
        causation_key=row["causation_key"], run_id=_uuid(row["run_id"]), work_id=_uuid(row["work_id"]),
        handoff_id=_uuid(row["handoff_id"]), finding_id=_uuid(row["finding_id"]), claim_id=_uuid(row["claim_id"]),
        evidence_references=references, reason=row["reason"],
    )


def _event_page(conn, request) -> MissionRelayEventPage:
    mission_id = str(request.mission_id)
    # Admission locks cannot protect journal ownership changed after publication. Validate
    # the complete mission stream in this pinned view, even when a cursor skips its history.
    if conn.execute(
        "SELECT 1 FROM mission_progress_events e"
        " LEFT JOIN mission_run_journals j ON j.id=e.run_id"
        " LEFT JOIN research_missions m ON m.id=e.mission_id"
        " WHERE e.mission_id=? AND e.run_id IS NOT NULL AND"
        " (j.id IS NULL OR j.mission_id IS NOT e.mission_id OR j.workspace_id IS NOT m.workspace_id) LIMIT 1",
        (mission_id,),
    ).fetchone() is not None:
        raise ValueError("Committed progress run has incompatible canonical ownership.")
    revision_row = conn.execute(
        "SELECT revision FROM mission_progress_revisions WHERE mission_id=?", (mission_id,),
    ).fetchone()
    revision = revision_row["revision"] if revision_row is not None else 0
    latest = conn.execute(
        "SELECT revision,ordinal FROM mission_progress_events WHERE mission_id=?"
        " ORDER BY revision DESC,ordinal DESC LIMIT 1", (mission_id,),
    ).fetchone()
    if (latest is None and revision != 0) or (latest is not None and latest["revision"] != revision):
        raise ValueError("Committed revision and event high-water are inconsistent.")
    high_water = MissionRelayCursor(
        mission_id=request.mission_id, revision=revision, ordinal=latest["ordinal"] if latest is not None else 0,
    )
    after = request.after_cursor
    position = after.position if after is not None else (0, 0)
    unknown = position > high_water.position
    if position != (0, 0) and not unknown:
        unknown = conn.execute(
            "SELECT 1 FROM mission_progress_events WHERE mission_id=? AND revision=? AND ordinal=?",
            (mission_id, *position),
        ).fetchone() is None
    # Revisions are allocated only by committed publications. A missing suffix needs
    # resynchronization even when the caller's own cursor is still retained.
    missed = conn.execute(
        "WITH suffix AS (SELECT revision,ordinal,"
        " lag(revision,1,?) OVER (ORDER BY revision,ordinal) AS previous_revision,"
        " lag(ordinal,1,?) OVER (ORDER BY revision,ordinal) AS previous_ordinal"
        " FROM mission_progress_events WHERE mission_id=? AND (revision,ordinal)>(?,?))"
        " SELECT 1 FROM suffix WHERE"
        " (revision=previous_revision AND ordinal<>previous_ordinal+1) OR"
        " (revision<>previous_revision AND (revision<>previous_revision+1 OR ordinal<>1)) LIMIT 1",
        (*position, mission_id, *position),
    ).fetchone() is not None
    if unknown or missed:
        return MissionRelayEventPage(high_water=high_water, page_size=request.page_size, events=(), resync_required=True)
    rows = conn.execute(
        "SELECT * FROM mission_progress_events WHERE mission_id=? AND (revision,ordinal)>(?,?)"
        " ORDER BY revision,ordinal LIMIT ?", (mission_id, *position, request.page_size + 1),
    ).fetchall()
    events = tuple(_event(row) for row in rows[:request.page_size])
    has_more = len(rows) > request.page_size
    return MissionRelayEventPage(
        high_water=high_water, page_size=request.page_size, after_cursor=after, events=events,
        has_more=has_more, next_cursor=events[-1].cursor if has_more else None,
    )


class SqliteMissionRelayReader(IMissionRelayReader):
    """Borrow configured identity, then own each read-only transaction and its settlement."""

    def __init__(self, repository: SqliteTrendRepository):
        self._repository = repository
        self._memory = repository._db_path == ":memory:"
        self._owner_connection = repository._mem_conn
        self._file_uri = None if self._memory else Path(repository._db_path).resolve().as_uri() + "?mode=ro"

    async def load_snapshot(self, request: MissionRelayReadRequest) -> MissionRelayRead | MissionRelayReadFailure:
        # Shield the entire resource lifetime, not just SQL dispatch. Repeated cancellation
        # cannot release backup ownership or abandon a connection still used by a thread.
        return await await_settled(self._load(request))

    async def _load(self, request):
        conn = None
        try:
            if self._memory:
                async with self._repository._lock:
                    if (
                        not self._repository._initialized or self._owner_connection is None
                        or self._repository._mem_conn is not self._owner_connection
                    ):
                        return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE)
                    conn = await asyncio.to_thread(self._copy_memory)
            else:
                conn = await asyncio.to_thread(sqlite3.connect, self._file_uri, uri=True, check_same_thread=False)
            return await asyncio.to_thread(self._read, conn, request)
        except (
            sqlite3.Error, OSError, ValueError, TypeError, KeyError, IndexError,
            IncompleteMarketBriefError, InvalidEvidenceQualificationError,
            InvalidMissionClaimError, InvalidMissionManifestError,
        ):
            return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE)
        finally:
            if conn is not None:
                await asyncio.to_thread(conn.close)

    def _copy_memory(self):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        try:
            self._owner_connection.backup(conn)
            return conn
        except BaseException:
            conn.close()
            raise

    @staticmethod
    def _read(conn, request):
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("BEGIN")
        for table, columns in _SCHEMA_COLUMNS.items():
            conn.execute(f"SELECT {columns} FROM {table} LIMIT 0")
        mission_id = str(request.mission_id)
        row = conn.execute("SELECT * FROM research_missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            return MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH)
        mission = _mission(row)
        run = None
        if request.run_id is not None:
            row = conn.execute("SELECT * FROM mission_run_journals WHERE id=?", (str(request.run_id),)).fetchone()
            if row is None or row["mission_id"] != mission_id or _uuid(row["workspace_id"]) != mission.workspace_id:
                return MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH)
            run = RunJournal(
                run_id=UUID(row["id"]), mission_id=UUID(row["mission_id"]), workspace_id=UUID(row["workspace_id"]),
                journal_path=Path(row["journal_path"]), sequence=row["sequence"], status=row["status"],
                started_at=_time(row["started_at"]), completed_at=_time(row["completed_at"]),
            )
        total, source_count, broken_lineage = conn.execute(
            "SELECT count(*),count(DISTINCT o.source_id),"
            " coalesce(sum(o.id IS NULL OR s.id IS NULL),0) FROM mission_evidence e"
            " LEFT JOIN observations o ON o.id=e.observation_id LEFT JOIN sources s ON s.id=o.source_id"
            " WHERE e.mission_id=?", (mission_id,),
        ).fetchone()
        if broken_lineage:
            raise ValueError("Canonical mission evidence has missing observation or source lineage.")
        signals = tuple(_signal(row) for row in conn.execute(
            "SELECT o.*,s.platform,e.mission_id FROM mission_evidence e"
            " JOIN observations o ON o.id=e.observation_id JOIN sources s ON s.id=o.source_id"
            " WHERE e.mission_id=? ORDER BY o.observed_at DESC,o.id LIMIT ? OFFSET ?",
            (mission_id, request.page_size, request.evidence_offset),
        ).fetchall())
        manifest_row = conn.execute("SELECT * FROM mission_manifests WHERE mission_id=?", (mission_id,)).fetchone()
        brief_row = conn.execute(SqliteTrendRepository._BRIEF_COLUMNS + " WHERE mission_id=?", (mission_id,)).fetchone()
        qualifications = tuple(SqliteTrendRepository._qualification_from_row(row) for row in conn.execute(
            SqliteTrendRepository._QUALIFICATION_COLUMNS + " WHERE mission_id=? ORDER BY observation_id", (mission_id,),
        ).fetchall())
        outcomes = tuple(_outcome(row) for row in conn.execute(
            "SELECT * FROM mission_probe_outcomes WHERE run_id=? ORDER BY connector_surface",
            (str(request.run_id) if request.run_id is not None else None,),
        ).fetchall())
        evidence = MissionEvidenceSnapshot(
            mission=mission,
            manifest=SqliteTrendRepository._manifest_from_row(manifest_row) if manifest_row is not None else None,
            brief=SqliteTrendRepository._brief_from_row(brief_row) if brief_row is not None else None,
            signals=signals, qualifications=qualifications, outcomes=outcomes,
            claims=tuple(SqliteTrendRepository._read_claims_sync(conn, request.mission_id, include_superseded=True)),
        )
        return MissionRelayRead(
            request=request, evidence=evidence, run=run, events=_event_page(conn, request),
            read_at=datetime.now(timezone.utc), total_observations=total, source_count=source_count,
        )


def _pg_uuid(value):
    return UUID(str(value)) if value is not None else None


def _pg_event(row) -> MissionProgressEvent:
    return MissionProgressEvent(
        event_id=_pg_uuid(row["id"]),
        cursor=MissionRelayCursor(mission_id=_pg_uuid(row["mission_id"]), revision=row["revision"], ordinal=row["ordinal"]),
        kind=MissionProgressKind(row["kind"]), provenance=RelayProvenance(row["provenance"]),
        recorded_at=row["recorded_at"], occurred_at=row["occurred_at"], causation_key=row["causation_key"],
        run_id=_pg_uuid(row["run_id"]), work_id=_pg_uuid(row["work_id"]), handoff_id=_pg_uuid(row["handoff_id"]),
        finding_id=_pg_uuid(row["finding_id"]), claim_id=_pg_uuid(row["claim_id"]), reason=row["reason"],
        evidence_references=tuple(RelayEvidenceReference(
            mission_id=_pg_uuid(ref["mission_id"]), observation_id=_pg_uuid(ref["observation_id"]),
            source_id=_pg_uuid(ref["source_id"]), evidence_role=EvidenceRole(ref["evidence_role"]),
            direction=EvidenceDirection(ref["direction"]) if ref["direction"] is not None else None,
            qualification_relation=QualificationRelation(ref["qualification_relation"])
            if ref["qualification_relation"] is not None else None,
            qualification_frame_fingerprint=ref["qualification_frame_fingerprint"],
        ) for ref in row["evidence_references"]),
    )


async def _pg_fetch(conn, query, params=(), *, many=False, tuples=False):
    async with conn.cursor(row_factory=tuple_row if tuples else dict_row) as cursor:
        await cursor.execute(query, params)
        return await cursor.fetchall() if many else await cursor.fetchone()


class PostgresMissionRelayReader(IMissionRelayReader):
    """Own one connection per invoking loop, borrowing only configured store identity."""

    def __init__(self, repository: PostgresTimescaleRepository):
        self._dsn = repository._dsn

    async def load_snapshot(self, request: MissionRelayReadRequest) -> MissionRelayRead | MissionRelayReadFailure:
        # Shield opening through transaction exit and close; never leave a connection
        # unsettled or hand its ownership to a caller running on another loop.
        return await await_settled(self._load(request))

    async def _load(self, request):
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    return await self._read(conn, request)
        except (
            psycopg.Error, OSError, ValueError, TypeError, KeyError, IndexError,
            IncompleteMarketBriefError, InvalidEvidenceQualificationError,
            InvalidMissionClaimError, InvalidMissionManifestError,
        ):
            return MissionRelayReadFailure(status=RelayReadStatus.UNAVAILABLE, reason_code=RelayReadReason.READ_UNAVAILABLE)

    @staticmethod
    async def _read(conn, request):
        for table, columns in _SCHEMA_COLUMNS.items():
            await _pg_fetch(conn, f"SELECT {columns} FROM {table} LIMIT 0")
        mission_id = request.mission_id
        row = await _pg_fetch(conn, "SELECT * FROM research_missions WHERE id=%s", (mission_id,))
        if row is None:
            return MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH)
        mission = ResearchMission(
            id=_pg_uuid(row["id"]), title=row["title"], keywords=list(row["keywords"] or ()),
            platforms=[PlatformType(value) for value in row["platforms"] or ()], shortcode=row["shortcode"],
            geo_code=resolve_geo(row["geo_code"]), timeframe=resolve_timeframe(row["timeframe"]),
            status=row["status"], agent=row["agent"], session_id=row["session_id"], summary=row["summary"],
            workspace_id=_pg_uuid(row["workspace_id"]), surface=row["surface"],
            parent_attention_mission_id=_pg_uuid(row["parent_attention_mission_id"]),
            parent_cluster_id=_pg_uuid(row["parent_cluster_id"]), brief_revision_id=_pg_uuid(row["brief_revision_id"]),
            revises_mission_id=_pg_uuid(row["revises_mission_id"]), created_at=row["created_at"], updated_at=row["updated_at"],
        )
        mission.shortcode = row["shortcode"]
        run = None
        if request.run_id is not None:
            row = await _pg_fetch(conn, "SELECT * FROM mission_run_journals WHERE id=%s", (request.run_id,))
            if row is None or _pg_uuid(row["mission_id"]) != mission_id or _pg_uuid(row["workspace_id"]) != mission.workspace_id:
                return MissionRelayReadFailure(status=RelayReadStatus.REFUSED, reason_code=RelayReadReason.SCOPE_MISMATCH)
            run = RunJournal(
                run_id=_pg_uuid(row["id"]), mission_id=_pg_uuid(row["mission_id"]), workspace_id=_pg_uuid(row["workspace_id"]),
                journal_path=Path(row["journal_path"]), sequence=row["sequence"], status=row["status"],
                started_at=row["started_at"], completed_at=row["completed_at"],
            )
        total, source_count, broken_lineage = await _pg_fetch(conn,
            "SELECT count(*),count(DISTINCT o.source_id),count(*) FILTER (WHERE o.id IS NULL OR s.id IS NULL)"
            " FROM mission_evidence e LEFT JOIN observations o ON o.id=e.observation_id"
            " LEFT JOIN sources s ON s.id=o.source_id WHERE e.mission_id=%s", (mission_id,), tuples=True,
        )
        if broken_lineage:
            raise ValueError("Canonical mission evidence has missing observation or source lineage.")
        rows = await _pg_fetch(conn,
            "SELECT o.*,s.platform FROM mission_evidence e JOIN observations o ON o.id=e.observation_id"
            " JOIN sources s ON s.id=o.source_id WHERE e.mission_id=%s"
            " ORDER BY o.observed_at DESC NULLS LAST,o.id LIMIT %s OFFSET %s",
            (mission_id, request.page_size, request.evidence_offset), many=True,
        )
        signals = tuple(TrendSignal(
            platform=PlatformType(row["platform"]), raw_title=row["observed_title"],
            metric_value=row["metric_value"], growth_velocity=row["growth_velocity"], source_url=row["source_url"],
            geo_code=GeoCode(row["geo_code"]), cluster_id=_pg_uuid(row["cluster_id"]), mission_id=mission_id,
            observation_id=_pg_uuid(row["id"]), source_id=_pg_uuid(row["source_id"]),
            identity_source=row["identity_source"], time_provenance=row["time_provenance"],
            metadata=row["metadata"] or {}, captured_at=row["observed_at"], published_at=row["published_at"],
        ) for row in rows)
        repository = PostgresTimescaleRepository
        manifest_row = await _pg_fetch(conn, repository._MANIFEST_COLUMNS + " WHERE mission_id=%s", (mission_id,), tuples=True)
        brief_row = await _pg_fetch(conn, repository._BRIEF_COLUMNS + " WHERE mission_id=%s", (mission_id,), tuples=True)
        qualifications = tuple(repository._qualification_from_row(row) for row in await _pg_fetch(conn,
            repository._QUALIFICATION_COLUMNS + " WHERE mission_id=%s ORDER BY observation_id", (mission_id,), many=True, tuples=True,
        ))
        outcomes = tuple(MissionProbeOutcome(
            outcome_id=_pg_uuid(row["id"]), run_id=_pg_uuid(row["run_id"]), platform=row["platform"],
            connector_surface=row["connector_surface"], status=row["status"], signals_collected=row["signals_collected"],
            query_fingerprint=row["query_fingerprint"], completed_at=row["completed_at"],
            queried_keywords=tuple(row["queried_keywords"] or ()), queried_window=row["queried_window"],
            scope_attestation=row["scope_attestation"], note=row["note"], collection_plan_digest=row["collection_plan_digest"],
        ) for row in await _pg_fetch(conn,
            "SELECT * FROM mission_probe_outcomes WHERE run_id=%s ORDER BY connector_surface", (request.run_id,), many=True,
        ))
        claims = []
        for row in await _pg_fetch(conn,
            repository._CLAIM_COLUMNS + " WHERE mission_id=%s ORDER BY created_at,id", (mission_id,), many=True, tuples=True,
        ):
            bindings = await _pg_fetch(conn,
                repository._BINDING_COLUMNS + " WHERE claim_id=%s ORDER BY id", (row[0],), many=True, tuples=True,
            )
            claims.append(repository._claim_from_rows(row, bindings))
        evidence = MissionEvidenceSnapshot(
            mission=mission, manifest=repository._manifest_from_row(manifest_row) if manifest_row is not None else None,
            brief=repository._brief_from_row(brief_row) if brief_row is not None else None,
            signals=signals, qualifications=qualifications, outcomes=outcomes, claims=tuple(claims),
        )
        return MissionRelayRead(
            request=request, evidence=evidence, run=run, events=await PostgresMissionRelayReader._event_page(conn, request),
            read_at=datetime.now(timezone.utc), total_observations=total, source_count=source_count,
        )

    @staticmethod
    async def _event_page(conn, request):
        mission_id = request.mission_id
        # Check all recorded runs before resync/pagination can omit corrupted history.
        if await _pg_fetch(conn,
            "SELECT 1 FROM mission_progress_events e"
            " LEFT JOIN mission_run_journals j ON j.id=e.run_id"
            " LEFT JOIN research_missions m ON m.id=e.mission_id"
            " WHERE e.mission_id=%s AND e.run_id IS NOT NULL AND"
            " (j.id IS NULL OR j.mission_id IS DISTINCT FROM e.mission_id"
            " OR j.workspace_id IS DISTINCT FROM m.workspace_id) LIMIT 1", (mission_id,),
        ) is not None:
            raise ValueError("Committed progress run has incompatible canonical ownership.")
        revision_row = await _pg_fetch(conn, "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s", (mission_id,))
        revision = revision_row["revision"] if revision_row is not None else 0
        latest = await _pg_fetch(conn,
            "SELECT revision,ordinal FROM mission_progress_events WHERE mission_id=%s ORDER BY revision DESC,ordinal DESC LIMIT 1",
            (mission_id,),
        )
        if (latest is None and revision != 0) or (latest is not None and latest["revision"] != revision):
            raise ValueError("Committed revision and event high-water are inconsistent.")
        high_water = MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=latest["ordinal"] if latest is not None else 0)
        after = request.after_cursor
        position = after.position if after is not None else (0, 0)
        unknown = position > high_water.position
        if position != (0, 0) and not unknown:
            unknown = await _pg_fetch(conn,
                "SELECT 1 FROM mission_progress_events WHERE mission_id=%s AND revision=%s AND ordinal=%s",
                (mission_id, *position),
            ) is None
        missed = await _pg_fetch(conn,
            "WITH suffix AS (SELECT revision,ordinal,"
            " lag(revision,1,%s) OVER (ORDER BY revision,ordinal) AS previous_revision,"
            " lag(ordinal,1,%s) OVER (ORDER BY revision,ordinal) AS previous_ordinal"
            " FROM mission_progress_events WHERE mission_id=%s AND (revision,ordinal)>(%s,%s))"
            " SELECT 1 FROM suffix WHERE"
            " (revision=previous_revision AND ordinal<>previous_ordinal+1) OR"
            " (revision<>previous_revision AND (revision<>previous_revision+1 OR ordinal<>1)) LIMIT 1",
            (*position, mission_id, *position),
        ) is not None
        if unknown or missed:
            return MissionRelayEventPage(high_water=high_water, page_size=request.page_size, events=(), resync_required=True)
        rows = await _pg_fetch(conn,
            "SELECT * FROM mission_progress_events WHERE mission_id=%s AND (revision,ordinal)>(%s,%s)"
            " ORDER BY revision,ordinal LIMIT %s", (mission_id, *position, request.page_size + 1), many=True,
        )
        events = tuple(_pg_event(row) for row in rows[:request.page_size])
        has_more = len(rows) > request.page_size
        return MissionRelayEventPage(
            high_water=high_water, page_size=request.page_size, after_cursor=after, events=events,
            has_more=has_more, next_cursor=events[-1].cursor if has_more else None,
        )
