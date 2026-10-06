import asyncio
import dataclasses
import copy
import json
import logging
import re
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, TypeVar
from uuid import UUID, uuid4

from ignis.application.cancellation import await_settled
from ignis.application.ports.mission_relay_port import (
    IMissionRelayWriter,
    ProbeOutcomeCommitCommand,
    ProbeOutcomeCommitReceipt,
)
from ignis.application.ports.repository_port import (
    ITrendRepository,
    PlatformCredentialRecord,
    PlatformCredentialSummary,
)
from ignis.resources import sql_seed_file
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.cross_platform_score import cluster_rank_key, cross_platform_score
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    ClaimStatus,
    ClaimType,
    EvidenceDirection,
    EvidenceRole,
    compute_frame_fingerprint,
    EvidenceQualification,
    EvidenceQualificationConflictError,
    InvalidEvidenceQualificationError,
    InvalidMissionClaimError,
    StaleEvidenceQualificationError,
    StaleMissionClaimError,
    InvalidMissionManifestError,
    MarketBriefRevision,
    MissionClaim,
    MissionClaimEvidence,
    MissionManifest,
    MissionProbeOutcome,
    ResearchWorkspace,
    WorkspaceScopeMismatchError,
    WorkspaceStatus,
    require_complete_channel_outcomes,
)
from ignis.application.ports.research_workspace_port import (
    MissionWriterClaim,
    RunJournal,
)
from ignis.infrastructure.persistence.identifiers import (
    ambiguous_platform_message as _ambiguous_platform_message,
    log_level as _log_level,
    platform_key as _platform_key,
    utc_datetime as _utc_datetime,
    utc_iso as _utc_iso,
    uuid_or_none as _uuid_or_none,
    uuid_text as _uuid_text,
)
from ignis.domain.source_identity import (
    alias_namespace_prefix,
    resolve_identity_alias,
    resolve_source_identity,
)
from ignis.domain.value_objects import (
    GeoCode,
    IngressTrigger,
    PlatformType,
    Timeframe,
    resolve_geo,
    resolve_platform,
    resolve_timeframe,
    timeframe_to_days,
)
from ignis.domain.youtube_quota import (
    YouTubeQuotaBucket,
    YouTubeQuotaReservation,
    YouTubeQuotaUsage,
)

from ignis.domain.exceptions import RepositoryException
from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    RelayProvenance,
    RelayEvidenceReference,
)
from ignis.infrastructure.auth.crypto import decrypt_credentials, encrypt_credentials
from ignis.infrastructure.persistence.migration_state import (
    UNBACKFILLED_CORPUS,
    is_unbackfilled,
)

logger = logging.getLogger(__name__)
_WriteResult = TypeVar("_WriteResult")


def _platforms_of(row) -> List[PlatformType]:
    """Hydrate the stored selection, through resolve_platform so an unknown name is dropped.

    An empty or missing value means the mission never recorded one, and every connector is the
    behaviour those rows have always had.
    """
    try:
        raw = row["platforms"]
    except (IndexError, KeyError):
        raw = None
    try:
        names = json.loads(raw) if raw else []
    except (TypeError, ValueError):
        names = []
    resolved = []
    for name in names:
        try:
            resolved.append(resolve_platform(name))
        except ValueError:
            # resolve_platform raises on a name PlatformType does not know. Dropping it is
            # better than failing the read: a connector removed from the enum should not make
            # every mission that once selected it unreadable.
            logger.warning("Mission names a platform this build does not know: %s", name)
    return resolved or list(PlatformType)


# The connectors that existed before research_missions had a platforms column. Frozen as a
# literal rather than read off PlatformType: the rows this default is written into were created
# when these five were the whole registry, and deriving it from the enum would mean the day a
# sixth connector is added, every mission from before the column starts asking for it too.
LEGACY_MISSION_PLATFORMS = ["youtube", "google", "tiktok", "threads", "reels"]

# One wording for the refusal, shared by both write paths, so a caller cannot tell from the
# message whether it collided on the mission or on the revision number -- both mean the same
# thing: this confirmed Brief already exists and is not being rewritten.
BRIEF_ALREADY_CONFIRMED = (
    "A confirmed Market Brief revision already exists for this mission. Create a new revision "
    "instead of rewriting the confirmed one."
)


class SqliteTrendRepository(ITrendRepository, IMissionRelayWriter):
    """
    Lightweight, zero-dependency SQLite repository adapter for fn-ignis.
    Supports file-based SQLite databases (sqlite:///path/to/db.sqlite) and in-memory databases (sqlite:///:memory:).
    All queries run in thread pool executors to maintain 100% async non-blocking execution.
    """

    def __init__(self, db_path: str = "sqlite:///ignis.db"):
        clean_path = db_path.replace("sqlite:///", "").replace("sqlite://", "")
        self._db_path = clean_path if clean_path else "ignis.db"
        self._initialized = False
        self._lock = asyncio.Lock()
        self._mem_conn: Optional[sqlite3.Connection] = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            # The pragma is per connection, and this one is handed straight back by
            # _get_connection without passing the line that sets it there.
            self._mem_conn.execute("PRAGMA foreign_keys = ON")

    async def _run_write(self, operation: Callable[[], _WriteResult]) -> _WriteResult:
        """Keep ownership until the synchronous mutation settles, even after cancellation."""
        async with self._lock:
            return await await_settled(asyncio.to_thread(operation))

    async def close(self) -> None:
        """Close SQLite connection if in-memory."""
        async with self._lock:
            if self._mem_conn is not None:
                self._mem_conn.close()
                self._mem_conn = None

    @staticmethod
    def _youtube_quota_usage_from_row(row) -> YouTubeQuotaUsage:
        return YouTubeQuotaUsage(
            quota_day=date.fromisoformat(row["quota_day"]),
            bucket=YouTubeQuotaBucket(row["bucket"]),
            used=int(row["used"]),
            scheduled_used=int(row["scheduled_used"]),
            exhausted=bool(row["exhausted"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    async def reserve_youtube_quota(
        self,
        quota_day: date,
        bucket: YouTubeQuotaBucket,
        cost: int,
        trigger: IngressTrigger,
        daily_limit: int,
        now: datetime,
    ) -> YouTubeQuotaReservation:
        await self._ensure_schema()

        def _sync_reserve() -> YouTubeQuotaReservation:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                    " FROM youtube_quota_buckets WHERE quota_day = ? AND bucket = ?",
                    (quota_day.isoformat(), bucket.value),
                ).fetchone()
                used = int(row["used"]) if row else 0
                exhausted = bool(row["exhausted"]) if row else False
                if trigger != IngressTrigger.REQUESTED:
                    raise ValueError("YouTube quota can only be reserved for requested work.")
                admitted = (
                    not exhausted
                    and used + cost <= daily_limit
                )
                if admitted:
                    stamp = now.astimezone(timezone.utc).isoformat()
                    conn.execute(
                        "INSERT INTO youtube_quota_buckets"
                        " (quota_day, bucket, used, scheduled_used, exhausted, created_at, updated_at)"
                        " VALUES (?, ?, ?, ?, 0, ?, ?)"
                        " ON CONFLICT (quota_day, bucket) DO UPDATE SET"
                        " used = youtube_quota_buckets.used + excluded.used,"
                        " scheduled_used = youtube_quota_buckets.scheduled_used + excluded.scheduled_used,"
                        " updated_at = excluded.updated_at",
                        (
                            quota_day.isoformat(),
                            bucket.value,
                            cost,
                            0,
                            stamp,
                            stamp,
                        ),
                    )
                    row = conn.execute(
                        "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                        " FROM youtube_quota_buckets WHERE quota_day = ? AND bucket = ?",
                        (quota_day.isoformat(), bucket.value),
                    ).fetchone()
                conn.commit()
                usage = (
                    self._youtube_quota_usage_from_row(row)
                    if row
                    else YouTubeQuotaUsage(
                        quota_day=quota_day,
                        bucket=bucket,
                        used=0,
                        scheduled_used=0,
                        exhausted=False,
                        updated_at=now,
                    )
                )
                return YouTubeQuotaReservation(admitted=admitted, usage=usage)
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_reserve)

    async def mark_youtube_quota_exhausted(
        self,
        quota_day: date,
        bucket: YouTubeQuotaBucket,
        now: datetime,
    ) -> YouTubeQuotaUsage:
        await self._ensure_schema()

        def _sync_mark() -> YouTubeQuotaUsage:
            conn = self._get_connection()
            stamp = now.astimezone(timezone.utc).isoformat()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT INTO youtube_quota_buckets"
                    " (quota_day, bucket, used, scheduled_used, exhausted, created_at, updated_at)"
                    " VALUES (?, ?, 0, 0, 1, ?, ?)"
                    " ON CONFLICT (quota_day, bucket) DO UPDATE SET exhausted = 1,"
                    " updated_at = excluded.updated_at",
                    (quota_day.isoformat(), bucket.value, stamp, stamp),
                )
                row = conn.execute(
                    "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                    " FROM youtube_quota_buckets WHERE quota_day = ? AND bucket = ?",
                    (quota_day.isoformat(), bucket.value),
                ).fetchone()
                conn.commit()
                return self._youtube_quota_usage_from_row(row)
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_mark)

    async def get_youtube_quota_usage(self, quota_day: date) -> List[YouTubeQuotaUsage]:
        await self._ensure_schema()

        def _sync_get() -> List[YouTubeQuotaUsage]:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                    " FROM youtube_quota_buckets WHERE quota_day = ? ORDER BY bucket",
                    (quota_day.isoformat(),),
                ).fetchall()
                return [self._youtube_quota_usage_from_row(row) for row in rows]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    def _get_connection(self) -> sqlite3.Connection:

        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # SQLite defaults foreign keys off per connection, which would make every REFERENCES
        # clause in the schema decoration: ON DELETE SET NULL would never fire and a dangling
        # source_id would insert cleanly. Only the three tables from sql/016 declare any.
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    async def _ensure_schema(self) -> None:
        if self._initialized:
            return

        def _sync_initialize() -> None:
            if not self._initialized:
                self._create_tables_and_seed()
                self._refuse_an_unbackfilled_corpus()
                self._initialized = True

        await self._run_write(_sync_initialize)

    async def _ensure_progress_schema(self) -> None:
        """Explicit additive setup for authorized writers, never canonical bootstrap or reads."""
        await self._run_write(self._create_progress_tables)

    def _create_progress_tables(self) -> None:
        """Mirror sql/027 without upgrading canonical rows or fabricating historical receipts."""
        conn = self._get_connection()
        try:
            for table, required in (
                ("research_missions", {"id"}),
                ("mission_run_journals", {"id", "mission_id"}),
                ("mission_claims", {"id", "mission_id"}),
            ):
                info = conn.execute(f"PRAGMA table_info({table})").fetchall()
                target = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
                ).fetchone()
                if (
                    target is None
                    or not required <= {row[1] for row in info}
                    or [row[1] for row in info if row[5]] != ["id"]
                ):
                    raise RepositoryException(
                        "Mission progress setup requires initialized canonical tables."
                    )

            uuid_pattern = "-".join("[0-9a-f]" * size for size in (8, 4, 4, 4, 12))

            def uuid_check(expression: str) -> str:
                return (
                    f"(typeof({expression}) = 'text' AND instr({expression}, char(0)) = 0"
                    f" AND {expression} GLOB '{uuid_pattern}')"
                )

            optional_ids = "\n".join(
                f"CHECK ({name} IS NULL OR {uuid_check(name)}),"
                for name in ("run_id", "work_id", "handoff_id", "finding_id", "claim_id")
            )
            schema = f"""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS mission_progress_revisions (
                    mission_id TEXT PRIMARY KEY NOT NULL
                        REFERENCES research_missions(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL DEFAULT 0
                        CHECK (typeof(revision) = 'integer' AND revision >= 0),
                    CHECK {uuid_check('mission_id')}
                );
                CREATE TABLE IF NOT EXISTS mission_progress_events (
                    id TEXT PRIMARY KEY NOT NULL DEFAULT (
                        lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-4' ||
                        substr(lower(hex(randomblob(2))), 2) || '-' ||
                        substr('89ab', (random() & 3) + 1, 1) ||
                        substr(lower(hex(randomblob(2))), 2) || '-' || lower(hex(randomblob(6)))
                    ),
                    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision > 0),
                    ordinal INTEGER NOT NULL CHECK (
                        typeof(ordinal) = 'integer' AND ordinal > 0 AND ordinal <= 2147483647
                    ),
                    kind TEXT NOT NULL CHECK (kind IN (
                        'COLLECTION_STARTED', 'COLLECTION_STATE_CHANGED', 'PROBE_OUTCOMES_RECORDED', 'OBSERVATIONS_COMMITTED',
                        'QUALIFICATION_RECORDED', 'CLAIM_GATE_CHANGED', 'WORK_STARTED', 'WORK_WAITING',
                        'HANDOFF_COMMITTED', 'FINDING_REVISED', 'CANCELLATION_REQUESTED',
                        'CANCELLATION_ACKNOWLEDGED', 'RESEARCH_ASSIGNED', 'WORK_ASSIGNED',
                        'WORK_ACTIVITY_RECORDED', 'WORK_RESUMED', 'WORK_ENDED', 'RESEARCH_ENDED'
                    )),
                    provenance TEXT NOT NULL CHECK (provenance IN ('HARNESS_OBSERVED', 'HOST_REPORTED')),
                    causation_key TEXT NOT NULL CHECK (length(trim(causation_key)) > 0),
                    occurred_at TEXT,
                    recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    run_id TEXT REFERENCES mission_run_journals(id),
                    work_id TEXT,
                    handoff_id TEXT,
                    finding_id TEXT,
                    claim_id TEXT REFERENCES mission_claims(id),
                    evidence_references TEXT NOT NULL DEFAULT '[]',
                    reason TEXT,
                    CHECK {uuid_check('id')},
                    CHECK {uuid_check('mission_id')},
                    {optional_ids}
                    UNIQUE (mission_id, revision, ordinal),
                    UNIQUE (mission_id, id, revision, ordinal, run_id, causation_key, kind, provenance),
                    CHECK (kind <> 'PROBE_OUTCOMES_RECORDED' OR run_id IS NOT NULL)
                );
                CREATE TABLE IF NOT EXISTS mission_progress_commands (
                    mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                    command_key TEXT NOT NULL,
                    payload_fingerprint TEXT NOT NULL CHECK (
                        instr(payload_fingerprint, char(0)) = 0 AND length(payload_fingerprint) = 64
                        AND payload_fingerprint NOT GLOB '*[^0-9a-f]*'
                    ),
                    outcome_count INTEGER NOT NULL CHECK (
                        typeof(outcome_count) = 'integer' AND outcome_count > 0
                        AND outcome_count <= 2147483647
                    ),
                    run_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    revision INTEGER NOT NULL CHECK (typeof(revision) = 'integer' AND revision > 0),
                    ordinal INTEGER NOT NULL CHECK (
                        typeof(ordinal) = 'integer' AND ordinal > 0 AND ordinal <= 2147483647
                    ),
                    event_kind TEXT NOT NULL DEFAULT 'PROBE_OUTCOMES_RECORDED'
                        CHECK (event_kind = 'PROBE_OUTCOMES_RECORDED'),
                    event_provenance TEXT NOT NULL DEFAULT 'HARNESS_OBSERVED'
                        CHECK (event_provenance = 'HARNESS_OBSERVED'),
                    PRIMARY KEY (mission_id, command_key),
                    CHECK {uuid_check('mission_id')},
                    CHECK {uuid_check('run_id')},
                    CHECK {uuid_check('event_id')},
                    CHECK (
                        instr(command_key, char(0)) = 0
                        AND length(command_key) = length('probe-outcomes:' || mission_id || ':' || run_id || ':') + 64
                        AND substr(command_key, 1, length(command_key) - 64) =
                            'probe-outcomes:' || mission_id || ':' || run_id || ':'
                        AND substr(command_key, -64) NOT GLOB '*[^0-9a-f]*'
                    ),
                    FOREIGN KEY (
                        mission_id, event_id, revision, ordinal, run_id, command_key,
                        event_kind, event_provenance
                    ) REFERENCES mission_progress_events (
                        mission_id, id, revision, ordinal, run_id, causation_key, kind, provenance
                    ) ON DELETE CASCADE
                );
            """
            reference_check = f"""
                (SELECT count(*) FROM json_each(reference.value)) = 7
                AND NOT EXISTS (
                    SELECT 1 FROM json_each(reference.value) field
                    WHERE field.key NOT IN (
                        'mission_id', 'observation_id', 'source_id', 'evidence_role', 'direction',
                        'qualification_relation', 'qualification_frame_fingerprint'
                    )
                )
                AND {uuid_check("json_extract(reference.value, '$.mission_id')")}
                AND json_extract(reference.value, '$.mission_id') = NEW.mission_id
                AND {uuid_check("json_extract(reference.value, '$.observation_id')")}
                AND {uuid_check("json_extract(reference.value, '$.source_id')")}
                AND json_extract(reference.value, '$.evidence_role') IN ('MARKET_EVIDENCE', 'ATTENTION_CONTEXT')
                AND (json_type(reference.value, '$.direction') = 'null'
                    OR json_extract(reference.value, '$.direction') IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT'))
                AND ((json_type(reference.value, '$.qualification_relation') = 'null'
                        AND json_type(reference.value, '$.qualification_frame_fingerprint') = 'null')
                    OR (json_extract(reference.value, '$.qualification_relation') IN (
                            'QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION', 'CONTEXT_ONLY',
                            'EXCLUDED_IRRELEVANT', 'UNASSESSED'
                        )
                        AND json_type(reference.value, '$.qualification_frame_fingerprint') = 'text'
                        AND instr(json_extract(reference.value, '$.qualification_frame_fingerprint'), char(0)) = 0
                        AND length(json_extract(reference.value, '$.qualification_frame_fingerprint')) = 64
                        AND json_extract(reference.value, '$.qualification_frame_fingerprint')
                            NOT GLOB '*[^0-9a-f]*'))
            """
            # Sequential guards and lazy CASE prevent malformed JSON/scalars from reaching
            # object extraction. IS NOT TRUE refuses missing fields instead of accepting NULL.
            for operation in ("INSERT", "UPDATE"):
                schema += f"""
                    CREATE TRIGGER IF NOT EXISTS mission_progress_events_validate_{operation.lower()}
                    BEFORE {operation} ON mission_progress_events
                    BEGIN
                        SELECT CASE WHEN EXISTS (
                            SELECT 1 FROM mission_run_journals
                            WHERE id = NEW.run_id AND mission_id <> NEW.mission_id
                        ) THEN RAISE(ABORT, 'Progress run belongs to another mission') END;
                        SELECT CASE WHEN EXISTS (
                            SELECT 1 FROM mission_claims
                            WHERE id = NEW.claim_id AND mission_id <> NEW.mission_id
                        ) THEN RAISE(ABORT, 'Progress claim belongs to another mission') END;
                        SELECT CASE WHEN typeof(NEW.evidence_references) <> 'text'
                            THEN RAISE(ABORT, 'Progress references must be JSON text') END;
                        SELECT CASE WHEN json_valid(NEW.evidence_references) IS NOT TRUE
                            THEN RAISE(ABORT, 'Progress references must be valid JSON') END;
                        SELECT CASE WHEN json_type(NEW.evidence_references) IS NOT 'array'
                            THEN RAISE(ABORT, 'Progress references must be a typed array') END;
                        SELECT CASE WHEN EXISTS (
                            SELECT 1 FROM json_each(NEW.evidence_references) reference
                            WHERE CASE WHEN reference.type <> 'object' THEN 1
                                ELSE ({reference_check}) IS NOT TRUE END
                        ) THEN RAISE(ABORT, 'Progress reference has invalid typed fields') END;
                    END;
                """
            conn.executescript(schema + "COMMIT;")
        except BaseException:
            conn.rollback()
            raise
        finally:
            if self._mem_conn is None:
                conn.close()

    def _refuse_an_unbackfilled_corpus(self) -> None:
        """Checked once the schema is ready, which is this backend's equivalent of opening."""
        conn = self._get_connection()
        try:
            row = conn.execute(
                "SELECT EXISTS (SELECT 1 FROM trend_signals),"
                " EXISTS (SELECT 1 FROM observations)"
            ).fetchone()
        finally:
            if self._mem_conn is None:
                conn.close()
        if is_unbackfilled(row[0], row[1]):
            raise RepositoryException(UNBACKFILLED_CORPUS)

    @staticmethod
    def _upgrade_evidence_grounded_schema(conn: sqlite3.Connection) -> None:
        """Rebuild legacy SQLite tables whose CHECK constraints changed in contract v2."""
        cur = conn.cursor()

        def _table_sql(table: str) -> str:
            row = cur.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()
            return (row[0] or "") if row else ""

        brief_sql = _table_sql("market_brief_revisions")
        outcome_sql = _table_sql("mission_probe_outcomes")
        qualification_sql = _table_sql("mission_evidence_qualifications")
        rebuild_briefs = "market_brief_revisions_evidence_contract" not in brief_sql
        rebuild_outcomes = (
            "collection_plan_digest" not in outcome_sql or "'NOT_REQUESTED'" not in outcome_sql
            or "mission_probe_outcomes_partial_count_check" not in outcome_sql
        )
        rebuild_qualifications = (
            "evidence_role" not in qualification_sql
            or "'QUALIFIED_CONTRADICTION'" not in qualification_sql
        )
        if not any((rebuild_briefs, rebuild_outcomes, rebuild_qualifications)):
            return

        def _columns(table: str) -> set[str]:
            return {row[1] for row in cur.execute(f"PRAGMA table_info({table})")}

        def _select(existing: set[str], name: str, fallback: str) -> str:
            return name if name in existing else f"{fallback} AS {name}"

        # Changing PRAGMA foreign_keys inside a transaction is a no-op. Commit the schema script
        # first, then perform each table swap in one explicit transaction while references are
        # disabled. The replacement keeps the same table names, so dependent foreign keys resolve
        # again before enforcement is restored.
        conn.commit()
        cur.execute("PRAGMA foreign_keys = OFF")
        try:
            cur.execute("BEGIN IMMEDIATE")
            if rebuild_briefs:
                existing = _columns("market_brief_revisions")
                cur.execute("DROP TABLE IF EXISTS market_brief_revisions_rebuilt")
                cur.execute(
                    """
                    CREATE TABLE market_brief_revisions_rebuilt (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
                        mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                        revision_number INTEGER NOT NULL,
                        decision TEXT NOT NULL,
                        target_user TEXT NOT NULL,
                        problem TEXT NOT NULL,
                        geo TEXT NOT NULL,
                        timeframe TEXT NOT NULL,
                        hypothesis TEXT NOT NULL,
                        falsifiers TEXT NOT NULL,
                        alternative_hypotheses TEXT,
                        null_hypothesis TEXT,
                        kill_criteria TEXT,
                        revision_rule TEXT,
                        evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                        confirmed_by TEXT NOT NULL,
                        confirmed_at TEXT NOT NULL,
                        UNIQUE (mission_id),
                        UNIQUE (workspace_id, revision_number),
                        CHECK (falsifiers <> '[]'),
                        CONSTRAINT market_brief_revisions_evidence_contract CHECK (
                            (evidence_contract_version = 1
                                AND alternative_hypotheses IS NULL
                                AND null_hypothesis IS NULL
                                AND kill_criteria IS NULL
                                AND revision_rule IS NULL)
                            OR
                            (evidence_contract_version = 2
                                AND json_array_length(alternative_hypotheses) >= 2
                                AND null_hypothesis IS NOT NULL
                                AND trim(null_hypothesis) <> ''
                                AND json_array_length(kill_criteria) >= 1
                                AND revision_rule IS NOT NULL
                                AND trim(revision_rule) <> '')
                        )
                    )
                    """
                )
                selections = [
                    _select(existing, "id", "NULL"),
                    _select(existing, "workspace_id", "NULL"),
                    _select(existing, "mission_id", "NULL"),
                    _select(existing, "revision_number", "NULL"),
                    _select(existing, "decision", "NULL"),
                    _select(existing, "target_user", "NULL"),
                    _select(existing, "problem", "NULL"),
                    _select(existing, "geo", "NULL"),
                    _select(existing, "timeframe", "NULL"),
                    _select(existing, "hypothesis", "NULL"),
                    _select(existing, "falsifiers", "'[]'"),
                    _select(existing, "alternative_hypotheses", "NULL"),
                    _select(existing, "null_hypothesis", "NULL"),
                    _select(existing, "kill_criteria", "NULL"),
                    _select(existing, "revision_rule", "NULL"),
                    _select(existing, "evidence_contract_version", "1"),
                    _select(existing, "confirmed_by", "NULL"),
                    _select(existing, "confirmed_at", "NULL"),
                ]
                cur.execute(
                    "INSERT INTO market_brief_revisions_rebuilt SELECT " + ", ".join(selections)
                    + " FROM market_brief_revisions"
                )
                cur.execute("DROP TABLE market_brief_revisions")
                cur.execute(
                    "ALTER TABLE market_brief_revisions_rebuilt RENAME TO market_brief_revisions"
                )
                cur.execute(
                    "CREATE INDEX idx_market_brief_revisions_workspace"
                    " ON market_brief_revisions (workspace_id, revision_number DESC)"
                )

            if rebuild_outcomes:
                existing = _columns("mission_probe_outcomes")
                # SQLite validates triggers on other tables during RENAME. Restore the existing
                # claim guards inside this transaction after the replacement table exists.
                dependent_triggers = cur.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'trigger'"
                    " AND sql LIKE '%mission_probe_outcomes%'"
                ).fetchall()
                for name, _ in dependent_triggers:
                    quoted_name = name.replace('"', '""')
                    cur.execute(f'DROP TRIGGER "{quoted_name}"')
                cur.execute("DROP TABLE IF EXISTS mission_probe_outcomes_rebuilt")
                cur.execute(
                    """
                    CREATE TABLE mission_probe_outcomes_rebuilt (
                        id TEXT PRIMARY KEY,
                        run_id TEXT NOT NULL REFERENCES mission_run_journals(id) ON DELETE CASCADE,
                        platform TEXT NOT NULL,
                        connector_surface TEXT NOT NULL,
                        status TEXT NOT NULL CHECK (
                            status IN ('HEALTHY', 'EMPTY_NO_DATA', 'AUTH_REQUIRED', 'RATE_LIMITED',
                                       'DEGRADED', 'FAILED', 'NOT_REQUESTED')
                        ),
                        signals_collected INTEGER NOT NULL,
                        queried_keywords TEXT NOT NULL DEFAULT '[]',
                        queried_window TEXT,
                        query_fingerprint TEXT NOT NULL,
                        scope_attestation TEXT,
                        note TEXT,
                        collection_plan_digest TEXT,
                        evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                        completed_at TEXT NOT NULL,
                        UNIQUE (run_id, connector_surface),
                        CONSTRAINT mission_probe_outcomes_partial_count_check CHECK (signals_collected >= 0
                               AND ((status = 'HEALTHY' AND signals_collected > 0)
                                    OR status = 'DEGRADED'
                                    OR (status NOT IN ('HEALTHY', 'DEGRADED') AND signals_collected = 0))),
                        CHECK (status <> 'EMPTY_NO_DATA' OR queried_keywords <> '[]'),
                        CHECK (evidence_contract_version = 1 OR (
                            evidence_contract_version = 2
                            AND collection_plan_digest IS NOT NULL
                            AND ((status IN ('HEALTHY', 'EMPTY_NO_DATA')
                                  AND scope_attestation IS NOT NULL)
                                 OR (status NOT IN ('HEALTHY', 'EMPTY_NO_DATA')
                                     AND note IS NOT NULL AND trim(note) <> ''))
                        ))
                    )
                    """
                )
                names = (
                    "id",
                    "run_id",
                    "platform",
                    "connector_surface",
                    "status",
                    "signals_collected",
                    "queried_keywords",
                    "queried_window",
                    "query_fingerprint",
                    "scope_attestation",
                    "note",
                    "collection_plan_digest",
                    "evidence_contract_version",
                    "completed_at",
                )
                fallbacks = {
                    "queried_keywords": "'[]'",
                    "scope_attestation": "NULL",
                    "note": "NULL",
                    "collection_plan_digest": "NULL",
                    "evidence_contract_version": "1",
                }
                selections = [_select(existing, name, fallbacks.get(name, "NULL")) for name in names]
                cur.execute(
                    "INSERT INTO mission_probe_outcomes_rebuilt SELECT "
                    + ", ".join(selections)
                    + " FROM mission_probe_outcomes"
                )
                cur.execute("DROP TABLE mission_probe_outcomes")
                cur.execute(
                    "ALTER TABLE mission_probe_outcomes_rebuilt RENAME TO mission_probe_outcomes"
                )
                for _, trigger_sql in dependent_triggers:
                    cur.execute(trigger_sql)

            if rebuild_qualifications:
                existing = _columns("mission_evidence_qualifications")
                cur.execute("DROP TABLE IF EXISTS mission_evidence_qualifications_rebuilt")
                cur.execute(
                    """
                    CREATE TABLE mission_evidence_qualifications_rebuilt (
                        id TEXT PRIMARY KEY,
                        mission_id TEXT NOT NULL,
                        observation_id TEXT NOT NULL,
                        brief_revision_id TEXT REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
                        frame_fingerprint TEXT NOT NULL,
                        relation TEXT NOT NULL CHECK (
                            relation IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION',
                                         'CONTEXT_ONLY', 'EXCLUDED_IRRELEVANT', 'UNASSESSED')
                        ),
                        purpose TEXT NOT NULL CHECK (
                            purpose IN ('DEMAND', 'SUPPLY', 'VOC', 'CONTEXT')
                        ),
                        confidence REAL,
                        reason_code TEXT NOT NULL CHECK (
                            reason_code IN ('DIRECT_TO_FRAME', 'ADJACENT_ONLY', 'KEYWORD_ONLY',
                                            'WRONG_AUDIENCE_OR_PROBLEM',
                                            'FICTION_NEWS_OR_ENTERTAINMENT',
                                            'INSUFFICIENT_CONTENT', 'EVALUATOR_UNAVAILABLE')
                        ),
                        judged_by TEXT NOT NULL,
                        model TEXT,
                        hypothesis_target TEXT,
                        evidence_role TEXT,
                        evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        UNIQUE (mission_id, observation_id),
                        FOREIGN KEY (mission_id, observation_id)
                            REFERENCES mission_evidence (mission_id, observation_id) ON DELETE CASCADE,
                        CHECK ((relation NOT IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION')
                               OR purpose <> 'CONTEXT')
                               AND (relation <> 'CONTEXT_ONLY' OR purpose = 'CONTEXT')),
                        CHECK (CASE
                            WHEN relation = 'UNASSESSED' THEN
                                confidence IS NULL
                                AND reason_code IN ('INSUFFICIENT_CONTENT',
                                                    'EVALUATOR_UNAVAILABLE')
                            ELSE confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1
                        END),
                        CHECK ((evidence_contract_version = 1
                            AND relation <> 'QUALIFIED_CONTRADICTION'
                            AND evidence_role IS NULL
                            AND hypothesis_target IS NULL) OR (
                            evidence_contract_version = 2
                            AND evidence_role IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT')
                            AND ((relation = 'QUALIFIED_SUPPORT' AND evidence_role = 'SUPPORT'
                                  AND hypothesis_target IS NOT NULL
                                  AND trim(hypothesis_target) <> '')
                                 OR (relation = 'QUALIFIED_CONTRADICTION'
                                     AND evidence_role = 'CONTRADICTION'
                                     AND hypothesis_target IS NOT NULL
                                     AND trim(hypothesis_target) <> '')
                                 OR relation NOT IN ('QUALIFIED_SUPPORT',
                                                     'QUALIFIED_CONTRADICTION'))
                        ))
                    )
                    """
                )
                names = (
                    "id",
                    "mission_id",
                    "observation_id",
                    "brief_revision_id",
                    "frame_fingerprint",
                    "relation",
                    "purpose",
                    "confidence",
                    "reason_code",
                    "judged_by",
                    "model",
                    "hypothesis_target",
                    "evidence_role",
                    "evidence_contract_version",
                    "created_at",
                )
                fallbacks = {
                    "hypothesis_target": "NULL",
                    "evidence_role": "NULL",
                    "evidence_contract_version": "1",
                }
                selections = [_select(existing, name, fallbacks.get(name, "NULL")) for name in names]
                cur.execute(
                    "INSERT INTO mission_evidence_qualifications_rebuilt SELECT "
                    + ", ".join(selections)
                    + " FROM mission_evidence_qualifications"
                )
                cur.execute("DROP TABLE mission_evidence_qualifications")
                cur.execute(
                    "ALTER TABLE mission_evidence_qualifications_rebuilt"
                    " RENAME TO mission_evidence_qualifications"
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            cur.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _ensure_evidence_grounded_triggers(conn: sqlite3.Connection) -> None:
        """Install cross-table evidence rules after every legacy table rebuild is complete."""
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS validate_manifest_channel_sets;
            CREATE TRIGGER IF NOT EXISTS validate_manifest_channel_sets
            BEFORE INSERT ON mission_manifests
            WHEN EXISTS (
                SELECT 1
                FROM json_each(NEW.required_channels) required
                JOIN json_each(NEW.optional_channels) optional
                  ON required.value = optional.value
            )
            BEGIN
                SELECT RAISE(ABORT, 'required and optional manifest channels must be disjoint');
            END;

            DROP TRIGGER IF EXISTS validate_claim_observation_binding;
            CREATE TRIGGER IF NOT EXISTS validate_claim_observation_binding
            BEFORE INSERT ON mission_claim_evidence
            WHEN NEW.observation_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1
                     FROM mission_claims c
                     JOIN mission_evidence e
                       ON e.mission_id = c.mission_id
                      AND e.observation_id = NEW.observation_id
                     JOIN mission_evidence_qualifications q
                       ON q.mission_id = e.mission_id
                      AND q.observation_id = e.observation_id
                     WHERE c.id = NEW.claim_id
                       AND q.evidence_contract_version = 2
                       AND (
                           (NEW.role = 'SUPPORT'
                            AND q.relation = 'QUALIFIED_SUPPORT'
                            AND q.evidence_role = 'SUPPORT'
                            AND q.hypothesis_target = NEW.hypothesis_target)
                           OR (NEW.role = 'CONTRADICTION'
                               AND q.relation = 'QUALIFIED_CONTRADICTION'
                               AND q.evidence_role = 'CONTRADICTION'
                               AND q.hypothesis_target = NEW.hypothesis_target)
                           OR (NEW.role = 'CONTEXT'
                               AND q.relation = 'CONTEXT_ONLY'
                               AND q.evidence_role = 'CONTEXT')
                       )
                 )
            BEGIN
                SELECT RAISE(ABORT, 'claim observation lacks a compatible mission qualification');
            END;

            DROP TRIGGER IF EXISTS validate_claim_measured_absence_binding;
            CREATE TRIGGER IF NOT EXISTS validate_claim_measured_absence_binding
            BEFORE INSERT ON mission_claim_evidence
            WHEN NEW.probe_outcome_id IS NOT NULL
                 AND NOT EXISTS (
                     SELECT 1
                     FROM mission_claims c
                     JOIN mission_probe_outcomes o ON o.id = NEW.probe_outcome_id
                     JOIN mission_run_journals j ON j.id = o.run_id
                     WHERE c.id = NEW.claim_id
                       AND j.mission_id = c.mission_id
                       AND o.status = 'EMPTY_NO_DATA'
                       AND o.collection_plan_digest IS NOT NULL
                       AND NEW.role = 'SUPPORT'
                       AND o.run_id = (
                           SELECT latest.id
                           FROM mission_run_journals latest
                           WHERE latest.mission_id = c.mission_id
                             AND latest.status = 'COMPLETED'
                           ORDER BY latest.started_at DESC, latest.sequence DESC
                           LIMIT 1
                       )
                 )
            BEGIN
                SELECT RAISE(ABORT, 'claim outcome is not same-mission measured absence');
            END;

            CREATE TRIGGER IF NOT EXISTS prune_claim_binding_with_mission_evidence
            AFTER DELETE ON mission_evidence
            BEGIN
                DELETE FROM mission_claim_evidence
                WHERE observation_id = OLD.observation_id
                  AND claim_id IN (
                      SELECT id FROM mission_claims WHERE mission_id = OLD.mission_id
                  );
            END;

            CREATE TRIGGER IF NOT EXISTS withhold_claim_without_support
            AFTER DELETE ON mission_claim_evidence
            WHEN OLD.role = 'SUPPORT'
            BEGIN
                UPDATE mission_claims
                SET status = 'WITHHELD',
                    withheld_reasons = '["EVIDENCE_BINDING_INVALIDATED"]'
                WHERE id = OLD.claim_id
                  AND status = 'PERMITTED'
                  AND NOT EXISTS (
                      SELECT 1 FROM mission_claim_evidence
                      WHERE claim_id = OLD.claim_id AND role = 'SUPPORT'
                  );
            END;
            """
        )

    def _create_tables_and_seed(self) -> None:
        if self._db_path != ":memory:":
            p = Path(self._db_path)
            if p.parent and not p.parent.exists():
                p.parent.mkdir(parents=True, exist_ok=True)

        conn = self._get_connection()
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS trend_signals (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                raw_title TEXT NOT NULL,
                metric_value REAL NOT NULL,
                growth_velocity REAL DEFAULT 0.0,
                source_url TEXT,
                geo_code TEXT DEFAULT 'VN',
                cluster_id TEXT,
                mission_id TEXT,
                metadata TEXT,
                captured_at TEXT NOT NULL,
                published_at TEXT
            );

            CREATE TABLE IF NOT EXISTS signal_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                metric_value REAL DEFAULT 0.0,
                growth_velocity REAL DEFAULT 0.0
            );
            CREATE INDEX IF NOT EXISTS idx_signal_metrics_sig ON signal_metrics (signal_id, captured_at DESC);

            -- The three entities sql/016_source_observation_model.sql creates on Postgres.
            -- SQLite does not read the sql/ files, so the same constraints are restated here;
            -- a backend that only agrees on column names is not the same contract.
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                -- "<kind>:<value>", so that a TikTok hashtag named "12345" and item 12345 stay
                -- two objects. See the migration header for why the namespace is inside the key.
                external_id TEXT NOT NULL,
                -- Three columns only. A URL, a resolution route and a first/last seen range
                -- are all facts about a sighting, so they live on observations; see the header
                -- of sql/016_source_observation_model.sql.
                UNIQUE (platform, external_id)
            );

            CREATE TABLE IF NOT EXISTS observations (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                cluster_id TEXT REFERENCES topic_clusters(id) ON DELETE SET NULL,
                observed_at TEXT,
                published_at TEXT,
                time_provenance TEXT NOT NULL
                    CHECK (time_provenance IN ('exact_ingestion', 'legacy_publish_only', 'unknown')),
                identity_source TEXT NOT NULL
                    CHECK (identity_source IN ('metadata_external_id', 'url_external_id',
                                               'normalized_url_fallback')),
                observed_title TEXT,
                metric_value REAL DEFAULT 0.0,
                growth_velocity REAL DEFAULT 0.0,
                geo_code TEXT DEFAULT 'VN',
                source_url TEXT,
                metadata TEXT,
                CHECK (time_provenance <> 'exact_ingestion' OR observed_at IS NOT NULL)
            );
            CREATE INDEX IF NOT EXISTS idx_observations_source ON observations (source_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_observations_cluster ON observations (cluster_id, observed_at DESC);

            -- The ordering index from sql/019_observations_latest_per_source_index.sql. Its
            -- column list is get_top_clusters' ORDER BY term for term, including the two
            -- COALESCE expressions, because an index that merely resembles the ordering leaves
            -- the temp B-tree in place. Partial on the two predicates the reader always applies,
            -- which excludes every legacy observation this path can never read.
            CREATE INDEX IF NOT EXISTS idx_observations_latest_per_source
                ON observations (
                    cluster_id,
                    source_id,
                    observed_at DESC,
                    COALESCE(metric_value, 0) DESC,
                    COALESCE(growth_velocity, 0) DESC,
                    id DESC
                )
                WHERE cluster_id IS NOT NULL AND time_provenance = 'exact_ingestion';

            CREATE TABLE IF NOT EXISTS mission_evidence (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                observation_id TEXT NOT NULL REFERENCES observations(id) ON DELETE CASCADE,
                recorded_at TEXT NOT NULL,
                UNIQUE (mission_id, observation_id)
            );
            CREATE INDEX IF NOT EXISTS idx_mission_evidence_observation ON mission_evidence (observation_id);

            -- The alias ledger from sql/018_source_identity_aliases.sql. Restated here for the
            -- same reason as the three tables above: SQLite does not read the sql/ files, and a
            -- backend missing this table would keep filing two rows per Threads or Reels post
            -- while the other one reconciled them.
            CREATE TABLE IF NOT EXISTS source_identity_aliases (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                -- Both carry their namespace, "<kind>:<value>", as sources.external_id does.
                alias_external_id TEXT NOT NULL,
                canonical_external_id TEXT NOT NULL,
                witnessed_by TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                -- One canonical per alias, forever. See the migration header for why a second
                -- claim is kept out rather than allowed to overwrite.
                UNIQUE (platform, alias_external_id),
                CHECK (alias_external_id <> canonical_external_id)
            );

            CREATE TABLE IF NOT EXISTS topic_clusters (
                id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL UNIQUE,
                topic_label TEXT,
                cross_platform_score REAL DEFAULT 0.0,
                summary_text TEXT,
                category TEXT DEFAULT 'general',
                -- Nullable: a cluster built only from observations whose ingestion time was
                -- never recorded has no first sighting to store.
                first_seen_at TEXT,
                last_updated_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS research_missions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                keywords TEXT NOT NULL,
                -- JSON list. A mission that asked for one connector must not come back asking
                -- for five: the extra calls are the smaller harm, the summary counting
                -- responsive platforms against the wrong denominator is the larger one.
                platforms TEXT NOT NULL DEFAULT '[]',
                shortcode TEXT UNIQUE,
                geo_code TEXT DEFAULT 'VN',
                timeframe TEXT DEFAULT '30d',
                status TEXT DEFAULT 'INITIALIZED',
                agent TEXT DEFAULT 'generic',
                session_id TEXT,
                summary TEXT,
                -- Which research owns the mission and which question it answers. Nullable, and
                -- that is the honest shape: a mission created outside a research workspace
                -- belongs to none and declared no surface.
                workspace_id TEXT REFERENCES research_workspaces(id) ON DELETE CASCADE,
                surface TEXT CHECK (surface IS NULL OR surface IN ('ATTENTION', 'MARKET')),
                parent_attention_mission_id TEXT REFERENCES research_missions(id) ON DELETE SET NULL,
                parent_cluster_id TEXT REFERENCES topic_clusters(id) ON DELETE SET NULL,
                brief_revision_id TEXT,
                -- The Market mission whose confirmed Brief was changed to produce this one.
                -- Recorded on the newer mission, because the revised one is immutable from the
                -- moment its Brief was confirmed.
                revises_mission_id TEXT REFERENCES research_missions(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT,
                -- An Attention mission has no Brief, by definition. Stating it as a constraint
                -- keeps a caller from binding one and then reading an Opportunity Index off the
                -- result.
                CHECK (surface <> 'ATTENTION' OR brief_revision_id IS NULL),
                -- And with no Brief there is nothing for it to revise.
                CHECK (surface <> 'ATTENTION' OR revises_mission_id IS NULL),
                CHECK (revises_mission_id IS NULL OR revises_mission_id <> id)
            );

            CREATE TABLE IF NOT EXISTS platform_credentials (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL UNIQUE,
                auth_type TEXT NOT NULL,
                encrypted_data TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS system_audit_logs (
                id TEXT PRIMARY KEY,
                component TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT DEFAULT 'INFO',
                details TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS market_lexicons (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                term TEXT NOT NULL,
                category TEXT DEFAULT 'vernacular',
                created_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                UNIQUE(domain, term)
            );

            CREATE TABLE IF NOT EXISTS industry_taxonomies (
                id TEXT PRIMARY KEY,
                industry_code TEXT NOT NULL UNIQUE,
                industry_name TEXT NOT NULL,
                keywords TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS runtime_configs (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT DEFAULT 'connector',
                description TEXT,
                updated_by TEXT DEFAULT 'system',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- The PostgreSQL table added by sql/024_youtube_quota_ledger.sql. One aggregate row
            -- per Pacific-Time day and provider bucket is enough for atomic admission and keeps
            -- credentials out of the ledger.
            CREATE TABLE IF NOT EXISTS youtube_quota_buckets (
                quota_day TEXT NOT NULL,
                bucket TEXT NOT NULL CHECK (bucket IN ('search_list', 'default_units')),
                used INTEGER NOT NULL DEFAULT 0,
                scheduled_used INTEGER NOT NULL DEFAULT 0,
                exhausted INTEGER NOT NULL DEFAULT 0 CHECK (exhausted IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (quota_day, bucket),
                CHECK (used >= 0 AND scheduled_used >= 0 AND scheduled_used <= used)
            );

            -- The five entities sql/017_research_workspace.sql creates on Postgres. SQLite does
            -- not read the sql/ files, so the same constraints are restated here; a backend that
            -- only agrees on column names is not the same contract.
            CREATE TABLE IF NOT EXISTS research_workspaces (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                name TEXT,
                -- Recorded, not derived. One shared database serves several host workspaces, and
                -- two of them may legitimately hold a research with the same slug, so the slug
                -- alone is not the identity.
                root_path TEXT NOT NULL,
                format_version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'READY'
                    CHECK (status IN ('READY', 'INCOMPATIBLE')),
                created_at TEXT NOT NULL,
                UNIQUE (root_path, slug)
            );
            CREATE INDEX IF NOT EXISTS idx_research_workspaces_slug ON research_workspaces (slug);

            CREATE TABLE IF NOT EXISTS market_brief_revisions (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                revision_number INTEGER NOT NULL,
                decision TEXT NOT NULL,
                target_user TEXT NOT NULL,
                problem TEXT NOT NULL,
                geo TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                -- JSON list, and never empty: a Brief with no disconfirming condition is a
                -- hypothesis that cannot lose, which is not a hypothesis.
                falsifiers TEXT NOT NULL,
                alternative_hypotheses TEXT,
                null_hypothesis TEXT,
                kill_criteria TEXT,
                revision_rule TEXT,
                evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                confirmed_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                -- One confirmed revision per Market mission. Changing a confirmed Brief
                -- therefore cannot update in place; it has to create a new revision under a new
                -- mission, which is the whole point.
                UNIQUE (mission_id),
                UNIQUE (workspace_id, revision_number),
                CHECK (falsifiers <> '[]'),
                CONSTRAINT market_brief_revisions_evidence_contract CHECK (
                    (evidence_contract_version = 1
                        AND alternative_hypotheses IS NULL
                        AND null_hypothesis IS NULL
                        AND kill_criteria IS NULL
                        AND revision_rule IS NULL)
                    OR
                    (evidence_contract_version = 2
                        AND json_array_length(alternative_hypotheses) >= 2
                        AND null_hypothesis IS NOT NULL
                        AND trim(null_hypothesis) <> ''
                        AND json_array_length(kill_criteria) >= 1
                        AND revision_rule IS NOT NULL
                        AND trim(revision_rule) <> '')
                )
            );
            CREATE INDEX IF NOT EXISTS idx_market_brief_revisions_workspace
                ON market_brief_revisions (workspace_id, revision_number DESC);

            CREATE TABLE IF NOT EXISTS mission_run_journals (
                id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL REFERENCES research_workspaces(id) ON DELETE CASCADE,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                -- UNIQUE because the filesystem already granted this name exclusively. The row
                -- records what was granted rather than reserving a name the filesystem has not
                -- agreed to.
                journal_path TEXT NOT NULL UNIQUE,
                sequence INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'STARTED',
                started_at TEXT NOT NULL,
                -- Absent for an interrupted run. NULL says the run did not finish; a timestamp
                -- would say it finished the moment someone asked.
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_mission_run_journals_mission
                ON mission_run_journals (mission_id, started_at DESC);

            -- At most one active writer per mission. The primary key is what enforces it: a
            -- second writer's INSERT conflicts, which is the clear failure the contract asks
            -- for rather than a silently lost update.
            CREATE TABLE IF NOT EXISTS mission_writer_claims (
                mission_id TEXT PRIMARY KEY REFERENCES research_missions(id) ON DELETE CASCADE,
                run_id TEXT NOT NULL,
                claimed_at TEXT NOT NULL
            );

            -- The two tables sql/023_evidence_qualification.sql creates on Postgres, restated
            -- with the same keys and checks. See the migration header for why each exists.
            -- No mission_id here: the mission is derived through the run journal, so an outcome
            -- cannot name a mission different from the run that probed.
            CREATE TABLE IF NOT EXISTS mission_probe_outcomes (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES mission_run_journals(id) ON DELETE CASCADE,
                platform TEXT NOT NULL,
                connector_surface TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('HEALTHY', 'EMPTY_NO_DATA', 'AUTH_REQUIRED', 'RATE_LIMITED',
                               'DEGRADED', 'FAILED', 'NOT_REQUESTED')
                ),
                signals_collected INTEGER NOT NULL,
                -- JSON list of the keywords the surface attested to querying.
                queried_keywords TEXT NOT NULL DEFAULT '[]',
                queried_window TEXT,
                query_fingerprint TEXT NOT NULL,
                scope_attestation TEXT,
                note TEXT,
                collection_plan_digest TEXT,
                evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                completed_at TEXT NOT NULL,
                UNIQUE (run_id, connector_surface),
                CONSTRAINT mission_probe_outcomes_partial_count_check CHECK (signals_collected >= 0
                       AND ((status = 'HEALTHY' AND signals_collected > 0)
                            OR status = 'DEGRADED'
                            OR (status NOT IN ('HEALTHY', 'DEGRADED') AND signals_collected = 0))),
                CHECK (status <> 'EMPTY_NO_DATA' OR queried_keywords <> '[]'),
                CHECK (evidence_contract_version = 1 OR (
                    evidence_contract_version = 2
                    AND collection_plan_digest IS NOT NULL
                    AND ((status IN ('HEALTHY', 'EMPTY_NO_DATA')
                          AND scope_attestation IS NOT NULL)
                         OR (status NOT IN ('HEALTHY', 'EMPTY_NO_DATA')
                             AND note IS NOT NULL AND trim(note) <> ''))
                ))
            );

            -- Keyed to the mission_evidence pair, so a mission cannot judge an observation it
            -- does not hold and pruning the association removes the judgment.
            CREATE TABLE IF NOT EXISTS mission_evidence_qualifications (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                observation_id TEXT NOT NULL,
                brief_revision_id TEXT REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
                frame_fingerprint TEXT NOT NULL,
                relation TEXT NOT NULL CHECK (
                    relation IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION', 'CONTEXT_ONLY',
                                 'EXCLUDED_IRRELEVANT', 'UNASSESSED')
                ),
                purpose TEXT NOT NULL CHECK (purpose IN ('DEMAND', 'SUPPLY', 'VOC', 'CONTEXT')),
                confidence REAL,
                reason_code TEXT NOT NULL CHECK (
                    reason_code IN ('DIRECT_TO_FRAME', 'ADJACENT_ONLY', 'KEYWORD_ONLY',
                                    'WRONG_AUDIENCE_OR_PROBLEM', 'FICTION_NEWS_OR_ENTERTAINMENT',
                                    'INSUFFICIENT_CONTENT', 'EVALUATOR_UNAVAILABLE')
                ),
                judged_by TEXT NOT NULL,
                model TEXT,
                hypothesis_target TEXT,
                evidence_role TEXT,
                evidence_contract_version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE (mission_id, observation_id),
                FOREIGN KEY (mission_id, observation_id)
                    REFERENCES mission_evidence (mission_id, observation_id) ON DELETE CASCADE,
                CHECK ((relation NOT IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION')
                       OR purpose <> 'CONTEXT')
                       AND (relation <> 'CONTEXT_ONLY' OR purpose = 'CONTEXT')),
                CHECK (CASE
                    WHEN relation = 'UNASSESSED' THEN
                        confidence IS NULL
                        AND reason_code IN ('INSUFFICIENT_CONTENT', 'EVALUATOR_UNAVAILABLE')
                    ELSE confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1
                END),
                CHECK ((evidence_contract_version = 1
                    AND relation <> 'QUALIFIED_CONTRADICTION'
                    AND evidence_role IS NULL
                    AND hypothesis_target IS NULL) OR (
                    evidence_contract_version = 2
                    AND evidence_role IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT')
                    AND ((relation = 'QUALIFIED_SUPPORT' AND evidence_role = 'SUPPORT'
                          AND hypothesis_target IS NOT NULL AND trim(hypothesis_target) <> '')
                         OR (relation = 'QUALIFIED_CONTRADICTION'
                             AND evidence_role = 'CONTRADICTION'
                             AND hypothesis_target IS NOT NULL AND trim(hypothesis_target) <> '')
                         OR relation NOT IN ('QUALIFIED_SUPPORT', 'QUALIFIED_CONTRADICTION'))
                ))
            );

            -- The evidence-grounded control plane from sql/025, restated because SQLite never
            -- executes PostgreSQL migrations.
            CREATE TABLE IF NOT EXISTS mission_manifests (
                mission_id TEXT PRIMARY KEY REFERENCES research_missions(id) ON DELETE CASCADE,
                outcome TEXT NOT NULL,
                decision_context TEXT,
                required_channels TEXT NOT NULL,
                optional_channels TEXT NOT NULL DEFAULT '[]',
                authority_boundary TEXT NOT NULL,
                quota_budget TEXT NOT NULL DEFAULT '{}',
                output_type TEXT NOT NULL CHECK (
                    output_type IN ('COLLECTION_FRAME', 'ATTENTION_REPORT', 'MARKET_ANALYSIS',
                                    'STRATEGIC_ARTIFACT')
                ),
                stop_conditions TEXT NOT NULL,
                analysis_policy TEXT NOT NULL,
                retention_policy TEXT NOT NULL,
                created_by TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                manifest_digest TEXT NOT NULL UNIQUE,
                CHECK (json_array_length(required_channels) >= 1),
                CHECK (json_array_length(stop_conditions) >= 1),
                CHECK (json_valid(required_channels)
                       AND json_type(required_channels) = 'array'),
                CHECK (json_valid(optional_channels)
                       AND json_type(optional_channels) = 'array'),
                CHECK (json_valid(stop_conditions) AND json_type(stop_conditions) = 'array'),
                CHECK (json_valid(authority_boundary)
                       AND json_type(authority_boundary) = 'object'),
                CHECK (json_valid(quota_budget) AND json_type(quota_budget) = 'object'),
                CHECK (output_type NOT IN ('MARKET_ANALYSIS', 'STRATEGIC_ARTIFACT')
                       OR (decision_context IS NOT NULL AND trim(decision_context) <> ''))
            );

            CREATE TABLE IF NOT EXISTS mission_claims (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL REFERENCES research_missions(id) ON DELETE CASCADE,
                brief_revision_id TEXT REFERENCES market_brief_revisions(id) ON DELETE CASCADE,
                frame_digest TEXT NOT NULL,
                client_claim_key TEXT NOT NULL,
                claim_type TEXT NOT NULL CHECK (
                    claim_type IN ('OBSERVATION', 'MEASUREMENT', 'INFERENCE', 'ASSUMPTION',
                                   'RECOMMENDATION', 'UNKNOWN')
                ),
                wording TEXT NOT NULL,
                inference_method TEXT,
                metric_denominator TEXT,
                metric_timeframe TEXT,
                confidence REAL,
                limitations TEXT NOT NULL DEFAULT '[]',
                change_conditions TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL CHECK (status IN ('PERMITTED', 'WITHHELD', 'SUPERSEDED')),
                withheld_reasons TEXT NOT NULL DEFAULT '[]',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE (mission_id, frame_digest, client_claim_key),
                CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
                CHECK (claim_type NOT IN ('MEASUREMENT', 'INFERENCE', 'RECOMMENDATION')
                       OR (inference_method IS NOT NULL AND trim(inference_method) <> '')),
                CHECK (claim_type <> 'MEASUREMENT' OR status <> 'PERMITTED'
                       OR ((metric_denominator IS NOT NULL AND trim(metric_denominator) <> '')
                           AND (metric_timeframe IS NOT NULL AND trim(metric_timeframe) <> ''))),
                CHECK (claim_type NOT IN ('INFERENCE', 'RECOMMENDATION')
                       OR (limitations <> '[]' AND change_conditions <> '[]'))
            );
            CREATE INDEX IF NOT EXISTS idx_mission_claims_current
                ON mission_claims (mission_id, frame_digest, status, created_at);

            CREATE TABLE IF NOT EXISTS mission_claim_evidence (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES mission_claims(id) ON DELETE CASCADE,
                observation_id TEXT REFERENCES observations(id) ON DELETE CASCADE,
                probe_outcome_id TEXT REFERENCES mission_probe_outcomes(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('SUPPORT', 'CONTRADICTION', 'CONTEXT')),
                hypothesis_target TEXT,
                CHECK ((observation_id IS NOT NULL) + (probe_outcome_id IS NOT NULL) = 1),
                CHECK (role = 'CONTEXT'
                       OR (hypothesis_target IS NOT NULL AND trim(hypothesis_target) <> ''))
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_claim_evidence_observation
                ON mission_claim_evidence (claim_id, observation_id)
                WHERE observation_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_mission_claim_evidence_outcome
                ON mission_claim_evidence (claim_id, probe_outcome_id)
                WHERE probe_outcome_id IS NOT NULL;

        """)

        self._upgrade_evidence_grounded_schema(conn)
        self._ensure_evidence_grounded_triggers(conn)

        # CREATE TABLE IF NOT EXISTS leaves an existing database untouched, so columns added
        # after a user's file was created have to be applied here.
        existing_cluster_columns = {row[1] for row in cur.execute("PRAGMA table_info(topic_clusters)")}
        if "topic_label" not in existing_cluster_columns:
            cur.execute("ALTER TABLE topic_clusters ADD COLUMN topic_label TEXT")

        # SQLite cannot drop a NOT NULL, so relaxing one means rebuilding the table. Only a
        # database created before clusters could be clock-less needs it, which is what the
        # PRAGMA check decides. Foreign keys go off for the swap: dropping the old table would
        # otherwise fire ON DELETE SET NULL and strip the cluster off every observation.
        cluster_info = list(cur.execute("PRAGMA table_info(topic_clusters)"))
        first_seen = next((row for row in cluster_info if row[1] == "first_seen_at"), None)
        if first_seen is not None and first_seen[3] == 1:
            cur.execute("PRAGMA foreign_keys = OFF")
            cur.executescript(
                """
                CREATE TABLE topic_clusters_rebuilt (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL UNIQUE,
                    topic_label TEXT,
                    cross_platform_score REAL DEFAULT 0.0,
                    summary_text TEXT,
                    category TEXT DEFAULT 'general',
                    first_seen_at TEXT,
                    last_updated_at TEXT NOT NULL
                );
                INSERT INTO topic_clusters_rebuilt
                    (id, canonical_name, topic_label, cross_platform_score, summary_text,
                     category, first_seen_at, last_updated_at)
                SELECT id, canonical_name, topic_label, cross_platform_score, summary_text,
                       category, first_seen_at, last_updated_at
                FROM topic_clusters;
                DROP TABLE topic_clusters;
                ALTER TABLE topic_clusters_rebuilt RENAME TO topic_clusters;
                """
            )
            conn.commit()
            cur.execute("PRAGMA foreign_keys = ON")

        existing_mission_columns = {
            row[1] for row in cur.execute("PRAGMA table_info(research_missions)")
        }
        if existing_mission_columns and "platforms" not in existing_mission_columns:
            # Rows written before this column cannot say what the mission asked for -- the
            # selection was never stored, so there is nothing to recover. They are given the
            # default every mission used to behave as, which keeps them working exactly as they
            # did. That is a migration assumption, not evidence about what those missions meant.
            cur.execute("ALTER TABLE research_missions ADD COLUMN platforms TEXT")
            cur.execute(
                "UPDATE research_missions SET platforms = ? WHERE platforms IS NULL",
                (json.dumps(LEGACY_MISSION_PLATFORMS),),
            )

        # Missions written before sql/017 belong to no workspace and declared no surface. The
        # columns are added empty rather than defaulted: a NOT NULL DEFAULT 'MARKET' would claim
        # every one of them was a hypothesis-driven investigation and gate it on a Brief nobody
        # was ever asked to confirm.
        existing_mission_columns = {
            row[1] for row in cur.execute("PRAGMA table_info(research_missions)")
        }
        for column in (
            "workspace_id",
            "surface",
            "parent_attention_mission_id",
            "parent_cluster_id",
            "brief_revision_id",
            "revises_mission_id",
        ):
            if existing_mission_columns and column not in existing_mission_columns:
                cur.execute(f"ALTER TABLE research_missions ADD COLUMN {column} TEXT")
        # After the columns exist, never inside the schema script: an index over a column a
        # user's existing database has not been migrated to yet fails the whole script.
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_research_missions_workspace"
            " ON research_missions (workspace_id, created_at DESC)"
        )

        existing_signal_columns = {row[1] for row in cur.execute("PRAGMA table_info(trend_signals)")}
        if "published_at" not in existing_signal_columns:
            # captured_at used to hold the publish time for YouTube and the Google Trends feed.
            # New rows keep the two apart; rows already written cannot have their ingestion time
            # recovered, so they are left alone rather than stamped with an invented one.
            cur.execute("ALTER TABLE trend_signals ADD COLUMN published_at TEXT")

        # Seed Initial Lexicons & Configs from SQL files if table is empty
        cur.execute("SELECT COUNT(*) FROM market_lexicons")
        count = cur.fetchone()[0]
        if count == 0:
            now_str = datetime.now(timezone.utc).isoformat()
            for sql_filename in ("003_market_lexicons.sql", "004_global_lexicons.sql"):
                sql_path = sql_seed_file(sql_filename)
                if not sql_path:
                    continue
                content = sql_path.read_text(encoding="utf-8")
                matches = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", content)
                for dom, term, cat in matches:
                    cur.execute(
                        "INSERT OR IGNORE INTO market_lexicons (id, domain, term, category, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (str(uuid4()), dom, term, cat, "system", now_str),
                    )

        # Refreshed on every bootstrap rather than seeded once. Taxonomies are system-owned --
        # no tool writes them -- so there is no user edit to preserve, and INSERT OR IGNORE meant
        # a database created before a keyword set was widened kept the narrow one forever and
        # classified differently from Postgres.
        tax_path = sql_seed_file("003_market_lexicons.sql")
        if tax_path:
            now_str = datetime.now(timezone.utc).isoformat()
            content = tax_path.read_text(encoding="utf-8")
            tax_matches = re.findall(r"\('([^']+)',\s*'([^']+)',\s*ARRAY\[([^\]]+)\]\)", content)
            for code, name, kw_blob in tax_matches:
                keywords = re.findall(r"'([^']+)'", kw_blob)
                cur.execute(
                    "INSERT INTO industry_taxonomies (id, industry_code, industry_name, keywords, created_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(industry_code) DO UPDATE SET "
                    "industry_name = excluded.industry_name, keywords = excluded.keywords",
                    (str(uuid4()), code, name, json.dumps(keywords, ensure_ascii=False), now_str),
                )

        # System-owned vocabulary that replaced hardcoded Python constants. Unlike the seeds
        # above it is re-applied on every bootstrap: no MCP tool writes these domains, so there
        # is no user edit to preserve, and a database created before a list was widened would
        # otherwise keep the narrow one and behave differently from Postgres.
        now_str = datetime.now(timezone.utc).isoformat()
        for vocab_filename in (
            "012_vocabulary_from_constants.sql",
            "013_tiktok_ui_noise.sql",
            "014_language_detection_vocabulary.sql",
        ):
            vocab_path = sql_seed_file(vocab_filename)
            if not vocab_path:
                continue
            vocab_content = vocab_path.read_text(encoding="utf-8")
            for dom, term, cat in re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", vocab_content):
                cur.execute(
                    "INSERT OR IGNORE INTO market_lexicons (id, domain, term, category, created_by, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), dom, term, cat, "system", now_str),
                )

        # Vocabulary retirements, run as shipped and after the replay above. The replay puts back
        # every row its seed still lists, so a retirement applied before it -- or only once --
        # would be undone by the next start.
        for retirement_filename in ("020_retire_ambiguous_tiktok_ui_noise.sql",):
            retirement_path = sql_seed_file(retirement_filename)
            if not retirement_path:
                continue
            retirement_sql = "\n".join(
                line
                for line in retirement_path.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("--")
            )
            for statement in retirement_sql.split(";"):
                if statement.strip():
                    cur.execute(statement)

        cur.execute("SELECT COUNT(*) FROM runtime_configs")
        rc_count = cur.fetchone()[0]
        if rc_count == 0:
            rc_path = sql_seed_file("007_runtime_configs.sql")
            if rc_path:
                rc_content = rc_path.read_text(encoding="utf-8")
                rc_matches = re.findall(r"\('([^']+)',\s*'([^']*)',\s*'([^']+)',\s*'([^']+)',\s*'([^']+)'\)", rc_content)
                now_str = datetime.now(timezone.utc).isoformat()
                for k, v, cat, desc, updater in rc_matches:
                    cur.execute(
                        "INSERT OR IGNORE INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (k, v, cat, desc, updater, now_str, now_str),
                    )

        conn.commit()
        if self._mem_conn is None:
            conn.close()

    @staticmethod
    def _require_collection_run(conn: sqlite3.Connection, mission_id: UUID, run_id: UUID) -> None:
        row = conn.execute(
            "SELECT j.mission_id, j.workspace_id, m.workspace_id AS mission_workspace"
            " FROM mission_run_journals j JOIN research_missions m ON m.id = j.mission_id"
            " WHERE j.id = ?", (str(run_id),),
        ).fetchone()
        if row is None or row["mission_id"] != str(mission_id) or row["workspace_id"] != row["mission_workspace"]:
            raise RepositoryException("The recorded collection run does not belong to this mission scope.")

    def _commit_snapshot(self, conn: sqlite3.Connection, mission_id: UUID):
        """Reuse canonical decoders on the held write transaction, without a second snapshot."""
        from ignis.infrastructure.persistence.evidence_snapshot import read_evidence_snapshot

        reader = copy.copy(self)
        reader._mem_conn = conn
        # This method runs in the serialized worker thread; decoder coroutines only read
        # this connection and cannot release or commit the owning transaction.
        return asyncio.run(read_evidence_snapshot(reader, mission_id))

    @staticmethod
    def _progress_reference(
        conn: sqlite3.Connection, mission_id: UUID, observation_id: UUID
    ) -> RelayEvidenceReference:
        row = conn.execute(
            "SELECT o.source_id, m.surface, q.relation, q.frame_fingerprint, q.evidence_role"
            " FROM mission_evidence e JOIN observations o ON o.id = e.observation_id"
            " JOIN research_missions m ON m.id = e.mission_id"
            " LEFT JOIN mission_evidence_qualifications q"
            " ON q.mission_id = e.mission_id AND q.observation_id = e.observation_id"
            " WHERE e.mission_id = ? AND e.observation_id = ?",
            (str(mission_id), str(observation_id)),
        ).fetchone()
        if row is None:
            raise RepositoryException("A progress reference requires canonical mission membership.")
        from ignis.domain.research_workspace import QualificationRelation

        role = {"ATTENTION": EvidenceRole.ATTENTION_CONTEXT, "MARKET": EvidenceRole.MARKET_EVIDENCE}.get(row["surface"])
        if role is None:
            raise RepositoryException("A relay commit requires a declared mission surface.")
        return RelayEvidenceReference(
            mission_id=mission_id, observation_id=observation_id, source_id=UUID(row["source_id"]),
            evidence_role=role,
            direction=EvidenceDirection(row["evidence_role"]) if row["evidence_role"] else None,
            qualification_relation=QualificationRelation(row["relation"]) if row["relation"] else None,
            qualification_frame_fingerprint=row["frame_fingerprint"],
        )

    @staticmethod
    def _record_progress(
        conn: sqlite3.Connection, mission_id: UUID, kind: MissionProgressKind, causation_key: str,
        *, run_id: UUID | None = None, claim_id: UUID | None = None,
        work_id: UUID | None = None, handoff_id: UUID | None = None, finding_id: UUID | None = None,
        references: tuple[RelayEvidenceReference, ...] = (), reason: str | None = None,
        revision: int | None = None, ordinal: int = 1,
    ) -> int:
        """Allocate one revision inside its fact transaction; never commit independently."""
        if revision is None:
            conn.execute(
                "INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (?, 1)"
                " ON CONFLICT(mission_id) DO UPDATE SET revision = revision + 1", (str(mission_id),),
            )
            revision = conn.execute(
                "SELECT revision FROM mission_progress_revisions WHERE mission_id = ?", (str(mission_id),),
            ).fetchone()["revision"]
        event = MissionProgressEvent(
            event_id=uuid4(), cursor=MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=ordinal),
            kind=kind, provenance=RelayProvenance.HARNESS_OBSERVED, recorded_at=datetime.now(timezone.utc),
            causation_key=causation_key, run_id=run_id, claim_id=claim_id,
            work_id=work_id, handoff_id=handoff_id, finding_id=finding_id,
            evidence_references=references, reason=reason,
        )
        conn.execute(
            "INSERT INTO mission_progress_events (id, mission_id, revision, ordinal, kind, provenance,"
            " recorded_at, causation_key, run_id, claim_id, work_id, handoff_id, finding_id, evidence_references, reason)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(event.event_id), str(mission_id), revision, ordinal, kind.value, event.provenance.value,
             event.recorded_at.isoformat(), causation_key, str(run_id) if run_id else None,
             str(claim_id) if claim_id else None,
             str(work_id) if work_id else None, str(handoff_id) if handoff_id else None,
             str(finding_id) if finding_id else None,
             json.dumps([ref.to_payload() for ref in references], separators=(",", ":")), reason),
        )
        return revision

    async def commit_collection_state(self, mission: ResearchMission, run_id: UUID) -> None:
        """Record a collection state transition and its run-scoped receipt atomically."""
        if mission.status not in ("RUNNING", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT"):
            raise RepositoryException("Unsupported collection state transition.")
        await self._ensure_schema()
        await self._ensure_progress_schema()

        def commit():
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_collection_run(conn, mission.id, run_id)
                row = conn.execute("SELECT status FROM research_missions WHERE id = ?", (str(mission.id),)).fetchone()
                kind = (MissionProgressKind.COLLECTION_STARTED if mission.status == "RUNNING"
                        else MissionProgressKind.COLLECTION_STATE_CHANGED)
                original = conn.execute(
                    "SELECT id FROM mission_progress_events WHERE mission_id = ? AND run_id = ?"
                    " AND kind = ? AND reason = ?",
                    (str(mission.id), str(run_id), kind.value, mission.status),
                ).fetchone()
                if original is not None and row["status"] == mission.status:
                    conn.rollback()
                    return
                if row["status"] in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT"):
                    raise RepositoryException("Terminal collection cannot be reopened or rewritten.")
                conn.execute(
                    "UPDATE research_missions SET status = ?, summary = ?, updated_at = ? WHERE id = ?",
                    (mission.status, mission.summary, datetime.now(timezone.utc).isoformat(), str(mission.id)),
                )
                self._record_progress(conn, mission.id, kind, f"collection:{run_id}:{mission.status}",
                                      run_id=run_id, reason=mission.status)
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(commit)

    async def commit_collection_observations(
        self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]
    ) -> int:
        """Publish fresh sightings plus memberships; retries retain their canonical identities."""
        signals = tuple(signals)
        if any(signal.mission_id not in (None, mission_id) for signal in signals):
            raise RepositoryException("Collection signals cannot name another mission.")
        await self._ensure_schema()
        await self._ensure_progress_schema()

        def commit():
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_collection_run(conn, mission_id, run_id)
                batch = [dataclasses.replace(signal, mission_id=mission_id) for signal in signals]
                fresh = []
                for signal in batch:
                    if signal.observation_id is not None:
                        self._progress_reference(conn, mission_id, signal.observation_id)
                        continue
                    if self._record_observations(conn.cursor(), [signal]):
                        signal.source_id = UUID(conn.execute(
                            "SELECT source_id FROM observations WHERE id = ?", (str(signal.observation_id),)
                        ).fetchone()["source_id"])
                        fresh.append(signal)
                if fresh:
                    refs = tuple(self._progress_reference(conn, mission_id, signal.observation_id) for signal in fresh)
                    self._record_progress(conn, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                                          f"observations:{run_id}:{uuid4()}", run_id=run_id, references=refs)
                conn.commit()
                # Publish identities before releasing write ownership, including when the
                # waiting coroutine is cancelled after a successful durable commit.
                for original, staged in zip(signals, batch):
                    if original.observation_id is None and staged.observation_id is not None:
                        for name in ("observation_id", "source_id", "identity_source", "time_provenance"):
                            setattr(original, name, getattr(staged, name))
                return len(fresh)
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(commit)

    async def commit_collection_membership(
        self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]
    ) -> int:
        """Reattach canonical observations without describing another sighting."""
        observation_ids = tuple(dict.fromkeys(signal.observation_id for signal in signals))
        if None in observation_ids:
            raise RepositoryException("Membership commits require stored observation identities.")
        await self._ensure_schema()
        await self._ensure_progress_schema()

        def commit():
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_collection_run(conn, mission_id, run_id)
                refs = []
                for observation_id in observation_ids:
                    inserted = conn.execute(
                        "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                        " VALUES (?, ?, ?, ?) ON CONFLICT(mission_id, observation_id) DO NOTHING",
                        (str(uuid4()), str(mission_id), str(observation_id), datetime.now(timezone.utc).isoformat()),
                    ).rowcount
                    if inserted:
                        refs.append(self._progress_reference(conn, mission_id, observation_id))
                if refs:
                    self._record_progress(conn, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                        f"membership:{run_id}:{uuid4()}", run_id=run_id, references=tuple(refs), reason="MEMBERSHIP_REATTACHED")
                conn.commit()
                return len(refs)
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(commit)

    async def commit_collection_pruning(
        self, mission_id: UUID, run_id: UUID, retained_observation_ids: Sequence[UUID]
    ) -> int:
        """Commit removed memberships and cascades with their original immutable references."""
        retained = {str(value) for value in retained_observation_ids}
        await self._ensure_schema()
        await self._ensure_progress_schema()

        def commit():
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_collection_run(conn, mission_id, run_id)
                removed = [UUID(row["observation_id"]) for row in conn.execute(
                    "SELECT observation_id FROM mission_evidence WHERE mission_id = ? ORDER BY observation_id",
                    (str(mission_id),),
                ) if row["observation_id"] not in retained]
                refs = tuple(self._progress_reference(conn, mission_id, value) for value in removed)
                affected = {}
                for claim in conn.execute(
                    "SELECT DISTINCT c.id, c.status FROM mission_claims c"
                    " JOIN mission_claim_evidence b ON b.claim_id = c.id"
                    " WHERE c.mission_id = ? AND b.observation_id IS NOT NULL ORDER BY c.id",
                    (str(mission_id),),
                ):
                    bindings = [UUID(row["observation_id"]) for row in conn.execute(
                        "SELECT observation_id FROM mission_claim_evidence"
                        " WHERE claim_id = ? AND observation_id IS NOT NULL", (claim["id"],),
                    )]
                    invalidated = tuple(ref for ref in refs if ref.observation_id in bindings)
                    if invalidated:
                        affected[claim["id"]] = (claim["status"], invalidated)
                conn.executemany(
                    "DELETE FROM mission_evidence WHERE mission_id = ? AND observation_id = ?",
                    [(str(mission_id), str(value)) for value in removed],
                )
                if removed:
                    revision = self._record_progress(conn, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                        f"membership:{run_id}:{uuid4()}", run_id=run_id, references=refs, reason="MEMBERSHIP_PRUNED")
                    ordinal = 1
                    for claim_id, (old_status, invalidated) in affected.items():
                        current = conn.execute("SELECT status FROM mission_claims WHERE id = ?", (claim_id,)).fetchone()
                        if current["status"] != old_status:
                            ordinal += 1
                            self._record_progress(conn, mission_id, MissionProgressKind.CLAIM_GATE_CHANGED,
                                f"claim-pruned:{claim_id}:{uuid4()}", claim_id=UUID(claim_id),
                                references=invalidated, reason=current["status"], revision=revision, ordinal=ordinal)
                conn.commit()
                return len(removed)
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(commit)

    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Record each sighting in the source/observation model. Nothing else is written.

        trend_signals and signal_metrics are read-only from here on. They stay in the schema --
        the audit reads them, the backfill reads them, and they are the only record of what the
        corpus looked like before the migration -- but a write to them now would restart the
        divergence the migration closed: the legacy side growing while the new model stands
        still, with nothing linking a row on one side to an observation on the other.
        """
        if not signals:
            return 0
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                recorded = self._record_observations(cur, signals)
                conn.commit()
                return recorded
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    @staticmethod
    def _claim_from_row(row: Any, binding_rows: Sequence[Any]) -> MissionClaim:
        bindings = tuple(
            MissionClaimEvidence(
                binding_id=UUID(binding["id"]),
                claim_id=UUID(binding["claim_id"]),
                observation_id=_uuid_or_none(binding["observation_id"]),
                probe_outcome_id=_uuid_or_none(binding["probe_outcome_id"]),
                role=EvidenceDirection(binding["role"]),
                hypothesis_target=binding["hypothesis_target"],
            )
            for binding in binding_rows
        )
        return MissionClaim(
            claim_id=UUID(row["id"]),
            mission_id=UUID(row["mission_id"]),
            brief_revision_id=_uuid_or_none(row["brief_revision_id"]),
            frame_digest=row["frame_digest"],
            client_claim_key=row["client_claim_key"],
            claim_type=ClaimType(row["claim_type"]),
            wording=row["wording"],
            inference_method=row["inference_method"],
            metric_denominator=row["metric_denominator"],
            metric_timeframe=row["metric_timeframe"],
            confidence=row["confidence"],
            limitations=tuple(json.loads(row["limitations"] or "[]")),
            change_conditions=tuple(json.loads(row["change_conditions"] or "[]")),
            status=ClaimStatus(row["status"]),
            withheld_reasons=tuple(json.loads(row["withheld_reasons"] or "[]")),
            created_by=row["created_by"],
            created_at=datetime.fromisoformat(row["created_at"]),
            evidence_bindings=bindings,
        )

    @classmethod
    def _read_claims_sync(
        cls, conn: sqlite3.Connection, mission_id: UUID, *, include_superseded: bool
    ) -> List[MissionClaim]:
        where = "WHERE mission_id = ?"
        params: List[Any] = [str(mission_id)]
        if not include_superseded:
            where += " AND status <> 'SUPERSEDED'"
        rows = conn.execute(
            "SELECT * FROM mission_claims " + where + " ORDER BY created_at, id", params
        ).fetchall()
        claims: List[MissionClaim] = []
        for row in rows:
            bindings = conn.execute(
                "SELECT * FROM mission_claim_evidence WHERE claim_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
            claims.append(cls._claim_from_row(row, bindings))
        return claims

    async def save_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]
    ) -> List[MissionClaim]:
        return await self._save_mission_claims(mission_id, frame_digest, claims, progress=False)

    async def commit_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]
    ) -> List[MissionClaim]:
        """Commit current-frame ledger candidates and their gate receipts together."""
        return await self._save_mission_claims(mission_id, frame_digest, claims, progress=True)

    async def _save_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim], *, progress: bool
    ) -> List[MissionClaim]:
        batch = list(claims)
        if any(
            str(claim.mission_id) != str(mission_id) or claim.frame_digest != frame_digest
            for claim in batch
        ):
            raise InvalidMissionClaimError(
                "Every claim in a batch must name the requested mission and evidence frame."
            )
        if not batch:
            return []
        await self._ensure_schema()
        if progress:
            await self._ensure_progress_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                if progress:
                    from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot

                    snapshot = self._commit_snapshot(conn, mission_id)
                    if frame_from_snapshot(snapshot).frame_digest != frame_digest:
                        raise StaleMissionClaimError("The submitted claim frame is stale.")
                recorded = []
                for claim in batch:
                    inserted = conn.execute(
                        "INSERT INTO mission_claims"
                        " (id, mission_id, brief_revision_id, frame_digest, client_claim_key,"
                        " claim_type, wording, inference_method, metric_denominator,"
                        " metric_timeframe, confidence, limitations,"
                        " change_conditions, status, withheld_reasons, created_by, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                        " ON CONFLICT (mission_id, frame_digest, client_claim_key) DO NOTHING",
                        (
                            str(claim.claim_id),
                            str(claim.mission_id),
                            str(claim.brief_revision_id) if claim.brief_revision_id else None,
                            claim.frame_digest,
                            claim.client_claim_key,
                            claim.claim_type.value,
                            claim.wording,
                            claim.inference_method,
                            claim.metric_denominator,
                            claim.metric_timeframe,
                            claim.confidence,
                            json.dumps(list(claim.limitations), ensure_ascii=False),
                            json.dumps(list(claim.change_conditions), ensure_ascii=False),
                            claim.status.value,
                            json.dumps(list(claim.withheld_reasons), ensure_ascii=False),
                            claim.created_by,
                            claim.created_at.isoformat(),
                        ),
                    ).rowcount
                    if inserted:
                        for binding in claim.evidence_bindings:
                            if binding.claim_id != claim.claim_id:
                                raise InvalidMissionClaimError(
                                    "Every evidence binding must name the claim carrying it."
                                )
                            conn.execute(
                                "INSERT INTO mission_claim_evidence"
                                " (id, claim_id, observation_id, probe_outcome_id, role,"
                                " hypothesis_target) VALUES (?, ?, ?, ?, ?, ?)",
                                (
                                    str(binding.binding_id),
                                    str(binding.claim_id),
                                    str(binding.observation_id) if binding.observation_id else None,
                                    (
                                        str(binding.probe_outcome_id)
                                        if binding.probe_outcome_id
                                        else None
                                    ),
                                    binding.role.value,
                                    binding.hypothesis_target,
                                ),
                            )
                        recorded.append(claim)
                        continue
                    existing = conn.execute(
                        "SELECT * FROM mission_claims WHERE mission_id = ?"
                        " AND frame_digest = ? AND client_claim_key = ?",
                        (str(mission_id), frame_digest, claim.client_claim_key),
                    ).fetchone()
                    bindings = conn.execute(
                        "SELECT * FROM mission_claim_evidence WHERE claim_id = ? ORDER BY id",
                        (existing["id"],),
                    ).fetchall()
                    stored = self._claim_from_row(existing, bindings)
                    if stored.idempotency_payload() != claim.idempotency_payload():
                        raise InvalidMissionClaimError(
                            f"client_claim_key {claim.client_claim_key!r} already names a different claim."
                        )
                revision = None
                for ordinal, claim in enumerate(recorded, start=1) if progress else ():
                    refs = tuple(self._progress_reference(conn, mission_id, binding.observation_id)
                                 for binding in claim.evidence_bindings if binding.observation_id)
                    revision = self._record_progress(
                        conn, mission_id, MissionProgressKind.CLAIM_GATE_CHANGED,
                        f"claim:{claim.claim_id}", claim_id=claim.claim_id,
                        references=refs, reason=claim.status.value, revision=revision, ordinal=ordinal,
                    )
                conn.commit()
                return self._read_claims_sync(
                    conn, mission_id, include_superseded=True
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise InvalidMissionClaimError(
                    f"The claim batch violates its evidence binding contract: {exc}"
                ) from exc
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        stored = await self._run_write(_sync_save)
        by_identity = {
            (claim.frame_digest, claim.client_claim_key): claim for claim in stored
        }
        return [
            by_identity[(claim.frame_digest, claim.client_claim_key)] for claim in batch
        ]

    async def list_mission_claims(
        self, mission_id: UUID, *, include_superseded: bool = False
    ) -> List[MissionClaim]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                return self._read_claims_sync(
                    conn, mission_id, include_superseded=include_superseded
                )
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def supersede_mission_claims(self, mission_id: UUID, current_frame_digest: str) -> int:
        await self._ensure_schema()

        def _sync_supersede():
            conn = self._get_connection()
            try:
                changed = conn.execute(
                    "UPDATE mission_claims SET status = 'SUPERSEDED'"
                    " WHERE mission_id = ? AND frame_digest <> ? AND status <> 'SUPERSEDED'",
                    (str(mission_id), current_frame_digest),
                ).rowcount
                conn.commit()
                return changed
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_supersede)

    async def load_mission_evidence_snapshot(self, mission_id: UUID):
        from ignis.infrastructure.persistence.evidence_snapshot import read_evidence_snapshot

        await self._ensure_schema()

        def _open_snapshot():
            if self._mem_conn is not None:
                # A transaction on the shared in-memory connection cannot isolate other
                # threads using that connection. SQLite's backup captures a separate view.
                conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._mem_conn.backup(conn)
                conn.row_factory = sqlite3.Row
            else:
                conn = self._get_connection()
            conn.execute("PRAGMA query_only = ON")
            conn.execute("BEGIN")
            return conn

        conn = await asyncio.to_thread(_open_snapshot)
        reader = copy.copy(self)
        reader._mem_conn = conn
        try:
            return await read_evidence_snapshot(reader, mission_id)
        finally:
            await asyncio.to_thread(conn.close)

    async def inventory_legacy_baseline(self) -> Dict[str, Any]:
        """Open the existing database read-only; inventory is never a schema bootstrap."""

        def _sync_inventory() -> Dict[str, Any]:
            if self._mem_conn is not None:
                conn = self._mem_conn
            else:
                database = Path(self._db_path).resolve()
                if not database.is_file():
                    raise FileNotFoundError("The inventory database does not exist.")
                conn = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
            previous_query_only = conn.execute("PRAGMA query_only").fetchone()[0]
            try:
                conn.execute("PRAGMA query_only = ON")
                signals = conn.execute(
                    "SELECT id, captured_at, source_url, metadata FROM trend_signals"
                    " WHERE mission_id IS NULL ORDER BY id"
                ).fetchall()
                metrics = conn.execute(
                    "SELECT sm.id, sm.signal_id FROM signal_metrics sm"
                    " JOIN trend_signals ts ON ts.id = sm.signal_id"
                    " WHERE ts.mission_id IS NULL ORDER BY sm.signal_id, sm.id"
                ).fetchall()
                orphans = conn.execute(
                    "SELECT sm.id FROM signal_metrics sm LEFT JOIN trend_signals ts"
                    " ON ts.id = sm.signal_id WHERE ts.id IS NULL ORDER BY sm.id"
                ).fetchall()
                excluded = conn.execute(
                    "SELECT count(*) FROM trend_signals WHERE mission_id IS NOT NULL"
                ).fetchone()[0]
                return {
                    "signals": [
                        {
                            "id": str(row["id"]),
                            "captured_at": row["captured_at"],
                            "source_url_present": bool(row["source_url"]),
                            "metadata_present": bool(row["metadata"] and row["metadata"] != "{}"),
                        }
                        for row in signals
                    ],
                    "metrics": [
                        {"id": int(row["id"]), "signal_id": str(row["signal_id"])}
                        for row in metrics
                    ],
                    "orphan_metric_ids": [int(row["id"]) for row in orphans],
                    "excluded_mission_rows": int(excluded),
                }
            finally:
                if self._mem_conn is not None:
                    conn.execute(f"PRAGMA query_only = {int(previous_query_only)}")
                else:
                    conn.close()

        return await asyncio.to_thread(_sync_inventory)

    # One observation per source, the most recent in the window, and only observations whose
    # collection time is known. published_at is not a substitute clock: for the 17,118 legacy
    # observations it says when the content was posted, and a window built on it would report a
    # two-year-old video as something seen this week.
    # Recency, then the payload, then the row id. Two observations of one source may share an
    # instant -- the schema allows it and a pass that sees one object twice in the same second
    # produces it -- and ordering on the clock alone left the winner to whatever order the rows
    # came back in. metric_value and growth_velocity come next because they are what the reader
    # returns and the score is computed from; once those tie, nothing downstream can tell the
    # two rows apart, and id only makes the choice repeatable.
    _LATEST_FIRST = (
        "o.observed_at DESC, COALESCE(o.metric_value, 0) DESC,"
        " COALESCE(o.growth_velocity, 0) DESC, o.id DESC"
    )

    _LATEST_PER_SOURCE = """
        WITH latest AS (
            SELECT
                o.id AS observation_id, o.source_id, o.cluster_id, o.metric_value,
                o.growth_velocity, o.observed_at, o.published_at, o.time_provenance,
                o.identity_source, o.observed_title, o.geo_code, o.source_url, o.metadata,
                s.platform,
                -- (cluster_id, source_id), not source_id alone: see the Postgres reader.
                ROW_NUMBER() OVER (
                    PARTITION BY o.cluster_id, o.source_id
                    -- The same order the Postgres reader uses; see _LATEST_FIRST there.
                    ORDER BY o.observed_at DESC, COALESCE(o.metric_value, 0) DESC,
                             COALESCE(o.growth_velocity, 0) DESC, o.id DESC
                ) AS rank
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.cluster_id IS NOT NULL
              AND o.time_provenance = 'exact_ingestion'
              AND o.observed_at IS NOT NULL
              AND o.observed_at >= datetime('now', '{modifier}')
              {cluster_filter}
        )
    """

    async def prune_empty_clusters(self) -> int:
        """Remove clusters holding no observation at all.

        Membership, not recency: a cluster whose only observations are legacy ones outside the
        default analysis window still describes something the corpus contains.
        """
        await self._ensure_schema()

        def _sync_prune():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM topic_clusters
                    WHERE id NOT IN (
                        SELECT DISTINCT cluster_id FROM observations WHERE cluster_id IS NOT NULL
                    )
                    -- A cluster the legacy corpus still points at is not empty; see the
                    -- Postgres reader for what deleting it would cascade into.
                    AND id NOT IN (
                        SELECT DISTINCT cluster_id FROM trend_signals WHERE cluster_id IS NOT NULL
                    );
                    """
                )
                removed = cur.rowcount or 0
                conn.commit()
                return removed
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_prune)

    def _reconcile_through_aliases(self, cur, platform, signal, identity):
        """The canonical identity for this sighting once the alias ledger has had its say.

        Two cases, and only two. A record that carries both the platform's primary key and a
        permalink shortcode witnesses their relationship, so the alias is registered and the
        record keeps the primary-key identity it already resolved to. A record that resolved into
        the shortcode namespace and witnessed nothing is looked up, and follows the ledger when
        an earlier record proved where it belongs.

        Everything else is left exactly as the resolver returned it -- which is the pre-ledger
        behavior, and the behavior any platform that declares no alias pair keeps forever.
        """
        alias = resolve_identity_alias(platform, signal.source_url, signal.metadata)
        if alias is not None:
            self._register_identity_alias(cur, alias)
            return identity

        prefix = alias_namespace_prefix(platform)
        if prefix is None or not identity.external_id.startswith(prefix):
            return identity

        row = cur.execute(
            "SELECT canonical_external_id FROM source_identity_aliases"
            " WHERE platform = ? AND alias_external_id = ?;",
            (platform, identity.external_id),
        ).fetchone()
        if row is None:
            return identity
        canonical = row["canonical_external_id"] if hasattr(row, "keys") else row[0]
        return dataclasses.replace(identity, external_id=canonical)

    def _register_identity_alias(self, cur, alias) -> None:
        """Record the alias unless one is already recorded for this shortcode.

        DO NOTHING, then read back what is actually stored. A second record claiming the same
        shortcode for a different primary key cannot be reconciled -- the ledger has no way to
        tell which claim is wrong -- so the stored one stands and the divergence is logged rather
        than resolved. The conflicting record is still written, under its own primary key, which
        leaves two rows where two objects were asserted instead of one wrong merge.
        """
        cur.execute(
            "INSERT INTO source_identity_aliases"
            " (id, platform, alias_external_id, canonical_external_id, witnessed_by, recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (platform, alias_external_id) DO NOTHING;",
            (
                str(uuid4()),
                alias.platform,
                alias.alias_external_id,
                alias.canonical_external_id,
                alias.witnessed_by,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        row = cur.execute(
            "SELECT canonical_external_id FROM source_identity_aliases"
            " WHERE platform = ? AND alias_external_id = ?;",
            (alias.platform, alias.alias_external_id),
        ).fetchone()
        stored = row["canonical_external_id"] if hasattr(row, "keys") else row[0]
        if stored != alias.canonical_external_id:
            logger.warning(
                "Conflicting alias claim on %s %s: ledger holds %s, this record claims %s."
                " Keeping the recorded alias and storing this record under its own identifier.",
                alias.platform,
                alias.alias_external_id,
                stored,
                alias.canonical_external_id,
            )

    def _record_observations(self, cur, signals: List[TrendSignal]) -> int:
        """Write each signal as one observation of one canonical source.

        The same three properties as the Postgres path, restated here rather than shared, because
        the two backends speak different SQL. What is shared is the part that must never diverge:
        both resolve identity through ignis.domain.source_identity.
        """
        written = 0
        for signal in signals:
            platform = (
                signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
            )
            identity = resolve_source_identity(platform, signal.source_url, signal.metadata)
            if identity is None:
                logger.warning("Signal has no resolvable external identity, skipped: %s", platform)
                continue

            identity = self._reconcile_through_aliases(cur, platform, signal, identity)

            # One statement, not a SELECT then an INSERT: two passes racing on one video would
            # both find nothing and both insert.
            row = cur.execute(
                "INSERT INTO sources (id, platform, external_id) VALUES (?, ?, ?)"
                " ON CONFLICT (platform, external_id) DO UPDATE SET platform = excluded.platform"
                " RETURNING id;",
                (str(uuid4()), identity.platform, identity.external_id),
            ).fetchone()
            source_id = row["id"] if hasattr(row, "keys") else row[0]

            # A live write knows its own collection time, so the clock is exact. Legacy rows
            # carrying a publish time arrive through the backfill, not through here.
            observed_at = (
                signal.captured_at.isoformat()
                if signal.captured_at
                else datetime.now(timezone.utc).isoformat()
            )
            observation_id = str(uuid4())
            cur.execute(
                "INSERT INTO observations (id, source_id, cluster_id, observed_at, published_at,"
                " time_provenance, identity_source, observed_title, metric_value,"
                " growth_velocity, geo_code, source_url, metadata)"
                " VALUES (?, ?, ?, ?, ?, 'exact_ingestion', ?, ?, ?, ?, ?, ?, ?);",
                (
                    observation_id,
                    source_id,
                    str(signal.cluster_id) if signal.cluster_id else None,
                    observed_at,
                    signal.published_at.isoformat() if signal.published_at else None,
                    identity.identity_source,
                    signal.raw_title,
                    signal.metric_value,
                    signal.growth_velocity,
                    signal.geo_code.value
                    if hasattr(signal.geo_code, "value")
                    else str(signal.geo_code),
                    signal.source_url,
                    json.dumps(signal.metadata or {}, ensure_ascii=False),
                ),
            )
            signal.observation_id = UUID(observation_id)
            signal.identity_source = identity.identity_source
            signal.time_provenance = "exact_ingestion"
            written += 1

            if signal.mission_id:
                cur.execute(
                    "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                    (
                        str(uuid4()),
                        str(signal.mission_id),
                        observation_id,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
        return written

    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        if not clusters:
            return
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                for c in clusters:
                    c_id = str(c.id)
                    now_str = datetime.now(timezone.utc).isoformat()
                    first_seen = c.first_seen_at.isoformat() if c.first_seen_at else None
                    last_updated = c.last_updated_at.isoformat() if c.last_updated_at else now_str

                    # An upsert, not INSERT OR REPLACE. REPLACE is a DELETE followed by an
                    # INSERT, so with foreign keys enforced it fires ON DELETE SET NULL on every
                    # observation already pointing at this cluster -- re-saving a cluster would
                    # quietly erase the membership history it exists to accumulate.
                    cur.execute(
                        """
                        INSERT INTO topic_clusters
                        (id, canonical_name, topic_label, cross_platform_score, summary_text, category, first_seen_at, last_updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            canonical_name = excluded.canonical_name,
                            topic_label = excluded.topic_label,
                            cross_platform_score = excluded.cross_platform_score,
                            summary_text = excluded.summary_text,
                            category = excluded.category,
                            last_updated_at = excluded.last_updated_at
                        """,
                        (c_id, c.canonical_name, c.topic_label, c.cross_platform_score, c.summary_text, c.category, first_seen, last_updated)
                    )

                    # Assign the cluster in memory and stop there. This used to insert every
                    # signal under a fresh uuid4, which made save_clusters a second write path:
                    # one external source became two rows, and the contract test measured it.
                    # save_signals is the only place a signal is written, and the pipeline calls
                    # this first so the cluster exists before an observation references it.
                    for s in c.signals:
                        s.cluster_id = c.id
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(_sync_save)

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        """Rank clusters by what was observed in the window, from the new model only.

        Two statements, not one, and the reason is the limit. Ranking needs an aggregate from
        every cluster in the window, but the caller asked for ten of them -- so the first
        statement reads only what ranking needs (four numbers per cluster) and the second reads
        the payload for the ten that survived. Building all of it and slicing afterwards meant
        constructing a thousand signal objects to return fifty, which was measured as roughly a
        quarter of the read at 10,000 observations.

        Nothing about the answer changes. The aggregates are the same aggregates, computed over
        the same one-observation-per-source set, and the score is still `cross_platform_score`
        rather than arithmetic restated in SQL -- which is the drift this codebase has already
        paid for once.
        """
        await self._ensure_schema()

        # Built from the canonical day count rather than a local map. Four such maps existed,
        # each covering three of the five Timeframe members, each with a different silent
        # default -- which is how a ninety-day request came to be served a twenty-four hour
        # window with a successful status.
        interval_modifier = f"-{timeframe_to_days(timeframe)} days"

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                ranked = self._rank_clusters(cur, interval_modifier, limit)
                if not ranked:
                    return []
                return self._read_cluster_payloads(cur, interval_modifier, ranked)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    def _rank_clusters(self, cur, interval_modifier: str, limit: int):
        """The cluster ids the caller asked for, strongest first, with their aggregates.

        The join to topic_clusters is here as well as in the payload read, and deliberately so:
        it decides which clusters exist at all. Ranking without it could hand a slot to a cluster
        the payload read then drops, and the caller would get fewer than `limit` results for a
        reason nothing in the query says out loud.
        """
        rows = cur.execute(
            f"""
            {self._LATEST_PER_SOURCE.format(modifier=interval_modifier, cluster_filter='')}
            SELECT
                l.cluster_id,
                COUNT(*) AS source_count,
                COUNT(DISTINCT l.platform) AS platform_count,
                COALESCE(SUM(l.metric_value), 0.0) AS total_metric,
                COALESCE(AVG(l.growth_velocity), 0.0) AS avg_velocity
            FROM latest l
            JOIN topic_clusters tc ON tc.id = l.cluster_id
            WHERE l.rank = 1
            GROUP BY l.cluster_id
            """
        ).fetchall()

        scored = [
            (
                row["cluster_id"],
                cross_platform_score(
                    distinct_platforms=int(row["platform_count"] or 0),
                    total_metric=float(row["total_metric"] or 0.0),
                    average_velocity=float(row["avg_velocity"] or 0.0),
                ),
                int(row["source_count"] or 0),
            )
            for row in rows
        ]
        scored.sort(
            key=lambda item: cluster_rank_key(item[1], item[2], item[0]), reverse=True
        )
        return scored[:limit]

    def _read_cluster_payloads(self, cur, interval_modifier: str, ranked):
        """Every signal of the ranked clusters, in the order ranking already decided."""
        cluster_ids = [cluster_id for cluster_id, _score, _count in ranked]
        placeholders = ", ".join("?" for _ in cluster_ids)
        # Pushed into the CTE rather than applied to its output: with the ordering index leading
        # on cluster_id this turns a scan of the whole window into one range per chosen cluster.
        cluster_filter = f"AND o.cluster_id IN ({placeholders})"
        rows = cur.execute(
            f"""
            {self._LATEST_PER_SOURCE.format(
                modifier=interval_modifier, cluster_filter=cluster_filter
            )}
            SELECT
                tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                tc.first_seen_at, tc.last_updated_at,
                l.platform, l.observed_title, l.metric_value, l.growth_velocity,
                l.source_url, l.geo_code, l.metadata, l.observed_at, l.published_at,
                l.observation_id, l.identity_source, l.time_provenance
            FROM latest l
            JOIN topic_clusters tc ON tc.id = l.cluster_id
            WHERE l.rank = 1
            """,
            cluster_ids,
        ).fetchall()

        grouped: Dict[str, List[Any]] = {}
        for row in rows:
            grouped.setdefault(row["id"], []).append(row)

        clusters: List[TopicCluster] = []
        for cluster_id, score, _source_count in ranked:
            cluster_rows = grouped.get(cluster_id)
            if not cluster_rows:
                continue
            head = cluster_rows[0]
            signals = [
                self._signal_from_observation(row, UUID(cluster_id)) for row in cluster_rows
            ]
            cluster = TopicCluster(
                id=UUID(cluster_id),
                canonical_name=head["canonical_name"],
                summary_text=head["summary_text"]
                or f"{len(signals)} sources across"
                f" {len({s.platform for s in signals})} platforms.",
                category=head["category"] or "general",
                cross_platform_score=score,
                signals=signals,
                first_seen_at=datetime.fromisoformat(head["first_seen_at"])
                if head["first_seen_at"]
                else None,
                last_updated_at=datetime.fromisoformat(head["last_updated_at"])
                if head["last_updated_at"]
                else datetime.now(timezone.utc),
            )
            cluster.topic_label = head["topic_label"]
            clusters.append(cluster)
        return clusters

    @staticmethod
    def _signal_from_observation(row, cluster_id: UUID) -> TrendSignal:
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
        except (TypeError, ValueError):
            metadata = {}
        return TrendSignal(
            platform=PlatformType(row["platform"]),
            raw_title=row["observed_title"] or "",
            metric_value=float(row["metric_value"] or 0.0),
            growth_velocity=float(row["growth_velocity"] or 0.0),
            source_url=row["source_url"],
            geo_code=GeoCode(row["geo_code"] or "VN"),
            cluster_id=cluster_id,
            metadata=metadata,
            captured_at=datetime.fromisoformat(row["observed_at"]) if row["observed_at"] else None,
            published_at=datetime.fromisoformat(row["published_at"])
            if row["published_at"]
            else None,
            observation_id=UUID(row["observation_id"]) if row["observation_id"] else None,
            identity_source=row["identity_source"],
            time_provenance=row["time_provenance"],
        )

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
        """One signal per source, the most recent observation of it in the window.

        Deduplication is on source_id, not on the URL: the corpus holds one source seen under
        two URL variants, and a feed-level URL shared by many items.
        """
        await self._ensure_schema()

        # Built from the canonical day count rather than a local map. Four such maps existed,
        # each covering three of the five Timeframe members, each with a different silent
        # default -- which is how a ninety-day request came to be served a twenty-four hour
        # window with a successful status.
        interval_modifier = f"-{timeframe_to_days(timeframe)} days"

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                rows = cur.execute(
                    f"""
                    {self._LATEST_PER_SOURCE.format(modifier=interval_modifier, cluster_filter='')}
                    SELECT * FROM latest WHERE rank = 1 AND cluster_id = ?
                    ORDER BY observed_at ASC
                    """,
                    (str(cluster_id),),
                ).fetchall()
            finally:
                if self._mem_conn is None:
                    conn.close()
            return [self._signal_from_observation(row, cluster_id) for row in rows]

        return await asyncio.to_thread(_sync_get)

    async def create_mission(self, mission: ResearchMission) -> ResearchMission:

        return await self.save_mission(mission)

    @staticmethod
    def _write_mission_row(cur, mission: ResearchMission) -> None:
        """One mission upsert, so every caller writes the same row the same way.

        An upsert, not INSERT OR REPLACE. REPLACE deletes the row first, and mission_evidence
        cascades on that delete: every status update would have thrown away the evidence the
        mission had just recorded.

        `surface` is not in the DO UPDATE list. A mission answers one question for its whole
        life, and letting a later save move it from ATTENTION to MARKET would re-label evidence
        that was collected to answer the other one.
        """
        geo = mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code)
        tf = mission.timeframe.value if hasattr(mission.timeframe, "value") else str(mission.timeframe)
        now_str = datetime.now(timezone.utc).isoformat()
        cur.execute(
            """
            INSERT INTO research_missions
            (id, title, keywords, platforms, shortcode, geo_code, timeframe, status, agent, session_id, summary,
             workspace_id, surface, parent_attention_mission_id, parent_cluster_id, brief_revision_id,
             revises_mission_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                keywords = excluded.keywords,
                platforms = excluded.platforms,
                shortcode = excluded.shortcode,
                geo_code = excluded.geo_code,
                timeframe = excluded.timeframe,
                status = excluded.status,
                agent = excluded.agent,
                session_id = excluded.session_id,
                summary = excluded.summary,
                workspace_id = excluded.workspace_id,
                parent_attention_mission_id = excluded.parent_attention_mission_id,
                parent_cluster_id = excluded.parent_cluster_id,
                brief_revision_id = excluded.brief_revision_id,
                revises_mission_id = excluded.revises_mission_id,
                updated_at = excluded.updated_at
            """,
            (
                str(mission.id),
                mission.title,
                json.dumps(mission.keywords, ensure_ascii=False),
                json.dumps(
                    [p.value if hasattr(p, "value") else str(p) for p in (mission.platforms or [])]
                ),
                mission.shortcode, geo, tf,
                mission.status, mission.agent, mission.session_id, mission.summary,
                _uuid_text(mission.workspace_id),
                mission.surface,
                _uuid_text(mission.parent_attention_mission_id),
                _uuid_text(mission.parent_cluster_id),
                _uuid_text(mission.brief_revision_id),
                _uuid_text(mission.revises_mission_id),
                mission.created_at.isoformat() if mission.created_at else now_str,
                now_str,
            ),
        )

    async def save_mission(self, mission: ResearchMission) -> ResearchMission:
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                self._write_mission_row(conn.cursor(), mission)
                conn.commit()
                return mission
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    async def get_mission(self, mission_id: UUID) -> Optional[ResearchMission]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title, keywords, platforms, shortcode, geo_code, timeframe, status, agent, session_id, summary, workspace_id, surface, parent_attention_mission_id, parent_cluster_id, brief_revision_id, revises_mission_id, created_at, updated_at FROM research_missions WHERE id = ? OR shortcode = ?",
                    (str(mission_id), str(mission_id))
                )
                r = cur.fetchone()
                if not r:
                    return None
                kws = json.loads(r["keywords"]) if r["keywords"] else []
                c_at = datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(timezone.utc)
                u_at = datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else None

                return ResearchMission(
                    id=UUID(r["id"]),
                    title=r["title"],
                    keywords=kws,
                    platforms=_platforms_of(r),
                    shortcode=r["shortcode"],
                    geo_code=resolve_geo(r["geo_code"]),
                    timeframe=resolve_timeframe(r["timeframe"]),
                    status=r["status"],
                    agent=r["agent"],
                    session_id=r["session_id"],
                    summary=r["summary"],
                    workspace_id=_uuid_or_none(r["workspace_id"]),
                    surface=r["surface"],
                    parent_attention_mission_id=_uuid_or_none(r["parent_attention_mission_id"]),
                    parent_cluster_id=_uuid_or_none(r["parent_cluster_id"]),
                    brief_revision_id=_uuid_or_none(r["brief_revision_id"]),
                    revises_mission_id=_uuid_or_none(r["revises_mission_id"]),
                    created_at=c_at,
                    updated_at=u_at,
                )
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def update_mission(self, mission: ResearchMission) -> None:
        await self.save_mission(mission)

    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, title, keywords, platforms, shortcode, geo_code, timeframe, status, agent, session_id, summary, workspace_id, surface, parent_attention_mission_id, parent_cluster_id, brief_revision_id, revises_mission_id, created_at, updated_at FROM research_missions ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                )
                rows = cur.fetchall()
                missions: List[ResearchMission] = []
                for r in rows:
                    kws = json.loads(r["keywords"]) if r["keywords"] else []
                    c_at = datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.now(timezone.utc)
                    missions.append(
                        ResearchMission(
                            id=UUID(r["id"]),
                            title=r["title"],
                            keywords=kws,
                            platforms=_platforms_of(r),
                            shortcode=r["shortcode"],
                            geo_code=resolve_geo(r["geo_code"]),
                            timeframe=resolve_timeframe(r["timeframe"]),
                            status=r["status"],
                            agent=r["agent"],
                            session_id=r["session_id"],
                            summary=r["summary"],
                            workspace_id=_uuid_or_none(r["workspace_id"]),
                            surface=r["surface"],
                            parent_attention_mission_id=_uuid_or_none(
                                r["parent_attention_mission_id"]
                            ),
                            parent_cluster_id=_uuid_or_none(r["parent_cluster_id"]),
                            brief_revision_id=_uuid_or_none(r["brief_revision_id"]),
                            revises_mission_id=_uuid_or_none(r["revises_mission_id"]),
                            created_at=c_at,
                        )
                    )
                return missions

            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # mission_evidence -> observations -> sources. The legacy mission_id column
                # held one mission per source, so whichever mission wrote last owned the row.
                cur.execute(
                    "SELECT s.platform, o.observed_title, o.metric_value, o.growth_velocity,"
                    " o.source_url, o.geo_code, e.mission_id, o.metadata, o.observed_at,"
                    " o.published_at, o.cluster_id, o.id AS observation_id, o.source_id,"
                    " o.identity_source, o.time_provenance"
                    " FROM mission_evidence e"
                    " JOIN observations o ON o.id = e.observation_id"
                    " JOIN sources s ON s.id = o.source_id"
                    " WHERE e.mission_id = ? ORDER BY o.observed_at DESC",
                    (str(mission_id),)
                )
                rows = cur.fetchall()
                signals: List[TrendSignal] = []
                for r in rows:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                    # No substitute clock. A NULL observed_at means the collection time was
                    # never recorded, and datetime.now() here would have turned every one of
                    # the 17,118 legacy observations into "collected when you ran the query".
                    cap_at = (
                        datetime.fromisoformat(r["observed_at"]) if r["observed_at"] else None
                    )
                    pub_at = datetime.fromisoformat(r["published_at"]) if r["published_at"] else None
                    signals.append(
                        TrendSignal(
                            platform=PlatformType(r["platform"]),
                            raw_title=r["observed_title"],
                            metric_value=r["metric_value"],
                            growth_velocity=r["growth_velocity"],
                            source_url=r["source_url"],
                            geo_code=GeoCode(r["geo_code"]),
                            cluster_id=UUID(r["cluster_id"]) if r["cluster_id"] else None,
                            mission_id=UUID(r["mission_id"]) if r["mission_id"] else None,
                            observation_id=UUID(r["observation_id"]),
                            source_id=_uuid_or_none(r["source_id"]),
                            identity_source=r["identity_source"],
                            time_provenance=r["time_provenance"],
                            metadata=meta,
                            captured_at=cap_at,
                            published_at=pub_at,
                        )
                    )

                return signals
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def assign_observation_clusters(self, signals: List[TrendSignal]) -> int:
        """Set the cluster on observations already written. See the Postgres docstring."""
        updates = [
            (str(s.cluster_id), str(s.observation_id))
            for s in signals
            if s.observation_id and s.cluster_id
        ]
        if not updates:
            return 0
        await self._ensure_schema()

        def _sync_assign():
            conn = self._get_connection()
            try:
                conn.executemany("UPDATE observations SET cluster_id = ? WHERE id = ?", updates)
                conn.commit()
                return len(updates)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_assign)

    async def attach_mission_evidence(self, mission_id: UUID, signals: List[TrendSignal]) -> int:
        """Record that a mission used observations that already exist. See Postgres."""
        rows = [
            (str(uuid4()), str(mission_id), str(s.observation_id),
             datetime.now(timezone.utc).isoformat())
            for s in signals
            if s.observation_id
        ]
        if not rows:
            return 0
        await self._ensure_schema()

        def _sync_attach():
            conn = self._get_connection()
            try:
                conn.executemany(
                    "INSERT INTO mission_evidence (id, mission_id, observation_id, recorded_at)"
                    " VALUES (?, ?, ?, ?) ON CONFLICT (mission_id, observation_id) DO NOTHING",
                    rows,
                )
                conn.commit()
                return len(rows)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_attach)

    async def prune_mission_evidence(self, mission_id: UUID, retained_observation_ids) -> int:
        """Drop this mission's claims on anything outside the retained set. See Postgres."""
        retained = [str(observation_id) for observation_id in retained_observation_ids]
        await self._ensure_schema()

        def _sync_prune():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if retained:
                    placeholders = ", ".join("?" for _ in retained)
                    cur.execute(
                        "DELETE FROM mission_evidence"
                        f" WHERE mission_id = ? AND observation_id NOT IN ({placeholders})",
                        (str(mission_id), *retained),
                    )
                else:
                    cur.execute(
                        "DELETE FROM mission_evidence WHERE mission_id = ?", (str(mission_id),)
                    )
                removed = cur.rowcount or 0
                conn.commit()
                return removed
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_prune)

    async def delete_mission_signals(self, mission_id: UUID) -> int:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # Only the mission's claims. A source and its observations are shared with
                # every other mission that observed them, and the cluster history is built on
                # those observations.
                cur.execute("DELETE FROM mission_evidence WHERE mission_id = ?", (str(mission_id),))
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_del)

    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        await self._ensure_schema()

        from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, sanitize_pii_data

        def _sync_log():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                log_id = str(uuid4())
                clean_msg = sanitize_pii_text(message)
                clean_details = sanitize_pii_data(details or {})
                details_json = json.dumps(clean_details, ensure_ascii=False)
                now_str = datetime.now(timezone.utc).isoformat()

                cur.execute(
                    "INSERT INTO system_audit_logs (id, component, event_type, message, level, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (log_id, component, event_type, clean_msg, _log_level(level), details_json, now_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(_sync_log)

    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                query = "SELECT id, component, event_type, message, level, details, created_at FROM system_audit_logs WHERE 1=1"
                params = []
                if level:
                    # upper() on the column as well: rows written before the level was
                    # canonical are still stored verbatim, and must stay findable by it.
                    query += " AND upper(level) = ?"
                    params.append(_log_level(level))
                if component:
                    query += " AND component = ?"
                    params.append(component)
                query += " ORDER BY created_at DESC LIMIT ?"
                params.append(limit)

                cur.execute(query, tuple(params))
                rows = cur.fetchall()
                logs = []
                for r in rows:
                    details = json.loads(r["details"]) if r["details"] else {}
                    logs.append({
                        "id": r["id"],
                        "component": r["component"],
                        "event_type": r["event_type"],
                        "message": r["message"],
                        "level": _log_level(r["level"]),
                        "details": details,
                        "created_at": r["created_at"],
                    })
                return logs
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def save_platform_credentials(
        self,
        platform: str,
        auth_type: str,
        credentials_data: Dict[str, Any],
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
    ) -> None:
        await self._ensure_schema()
        key = _platform_key(platform)

        def _sync_save():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # A row stored under another casing is this platform's credential, so saving
                # replaces it under the canonical key instead of adding a second row beside it.
                cur.execute(
                    "SELECT platform FROM platform_credentials WHERE lower(trim(platform)) = ?",
                    (key,),
                )
                stored = [r["platform"] for r in cur.fetchall()]
                if len(stored) > 1:
                    raise RepositoryException(_ambiguous_platform_message(key, stored))
                if stored and stored[0] != key:
                    cur.execute(
                        "UPDATE platform_credentials SET platform = ? WHERE platform = ?",
                        (key, stored[0]),
                    )
                encrypted = encrypt_credentials(credentials_data)
                encrypted_str = json.dumps(encrypted, ensure_ascii=False)
                cred_id = str(uuid4())
                now_str = datetime.now(timezone.utc).isoformat()
                exp_utc = _utc_datetime(expires_at)
                exp_str = exp_utc.isoformat() if exp_utc else None

                cur.execute(
                    """
                    INSERT INTO platform_credentials (id, platform, auth_type, encrypted_data, is_active, created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform) DO UPDATE SET
                        auth_type = excluded.auth_type,
                        encrypted_data = excluded.encrypted_data,
                        is_active = excluded.is_active,
                        updated_at = excluded.updated_at,
                        expires_at = excluded.expires_at
                    """,
                    (cred_id, key, auth_type, encrypted_str, 1 if is_active else 0, now_str, now_str, exp_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(_sync_save)

    async def get_platform_credentials(self, platform: str) -> Optional[PlatformCredentialRecord]:
        await self._ensure_schema()
        key = _platform_key(platform)

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT id, platform, auth_type, encrypted_data, is_active, created_at, updated_at, expires_at FROM platform_credentials WHERE lower(trim(platform)) = ?",
                    (key,),
                )
                rows = cur.fetchall()
                if len(rows) > 1:
                    raise RepositoryException(
                        _ambiguous_platform_message(key, [row["platform"] for row in rows])
                    )
                # Counted before the active filter: an inactive second row still means two
                # credentials for one platform, and save refuses the same pair.
                if not rows or rows[0]["is_active"] != 1:
                    return None
                r = rows[0]
                enc_data = json.loads(r["encrypted_data"]) if r["encrypted_data"] else {}
                decrypted = decrypt_credentials(enc_data)
                return {
                    "platform": key,
                    "auth_type": r["auth_type"],
                    "credentials_data": decrypted,
                    "is_active": True,
                    "expires_at": _utc_iso(r["expires_at"]),
                    "updated_at": _utc_iso(r["updated_at"]),
                }


            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def list_platform_credentials(self) -> List[PlatformCredentialSummary]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT id, platform, auth_type, is_active, created_at, updated_at, expires_at FROM platform_credentials")
                rows = cur.fetchall()
                creds = []
                for r in rows:
                    creds.append({
                        "platform": _platform_key(r["platform"]),
                        "auth_type": r["auth_type"],
                        # The same test get applies, so a row lists as active only when it
                        # would also read as connected.
                        "is_active": r["is_active"] == 1,
                        "expires_at": _utc_iso(r["expires_at"]),
                        "updated_at": _utc_iso(r["updated_at"]),
                    })
                return creds
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def delete_platform_credentials(self, platform: str) -> bool:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                # Every row that normalizes to the platform, so erasure never leaves a legacy
                # spelling of the same secret behind.
                cur.execute(
                    "DELETE FROM platform_credentials WHERE lower(trim(platform)) = ?",
                    (_platform_key(platform),),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_del)

    async def get_domain_lexicons(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if domain:
                    cur.execute("SELECT domain, term, category, created_by, created_at FROM market_lexicons WHERE domain = ? ORDER BY domain, term", (domain,))
                else:
                    cur.execute("SELECT domain, term, category, created_by, created_at FROM market_lexicons ORDER BY domain, term")
                rows = cur.fetchall()
                lexicons = []
                for r in rows:
                    lexicons.append({
                        "domain": r["domain"],
                        "term": r["term"],
                        "category": r["category"],
                        "created_by": r["created_by"],
                        "created_at": r["created_at"],
                    })
                return lexicons
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def register_lexicon_terms(
        self,
        domain: str,
        terms: List[str],
        category: str = "vernacular",
        created_by: str = "agent",
    ) -> int:
        if not terms:
            return 0
        await self._ensure_schema()

        def _sync_reg():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                inserted = 0
                now_str = datetime.now(timezone.utc).isoformat()
                for term in terms:
                    clean_term = term.strip().lower()
                    if not clean_term:
                        continue
                    cur.execute(
                        """
                        INSERT INTO market_lexicons (id, domain, term, category, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(domain, term) DO UPDATE SET
                            category = excluded.category,
                            created_by = excluded.created_by
                        """,
                        (str(uuid4()), domain.strip().lower(), clean_term, category, created_by, now_str),
                    )
                    inserted += 1
                conn.commit()
                return inserted
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_reg)

    async def get_industry_taxonomies(self) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT industry_code, industry_name, keywords, created_at FROM industry_taxonomies")
                rows = cur.fetchall()
                taxonomies = []
                for r in rows:
                    kws = json.loads(r["keywords"]) if r["keywords"] else []
                    taxonomies.append({
                        "industry_code": r["industry_code"],
                        "industry_name": r["industry_name"],
                        "keywords": kws,
                        "created_at": r["created_at"],
                    })
                return taxonomies
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_runtime_config(self, key: str) -> Optional[str]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT value FROM runtime_configs WHERE key = ?", (key,))
                row = cur.fetchone()
                return str(row["value"]) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_all_runtime_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        await self._ensure_schema()

        def _sync_get_all():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                if category:
                    cur.execute(
                        "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs WHERE category = ? ORDER BY key ASC",
                        (category,),
                    )
                else:
                    cur.execute(
                        "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs ORDER BY category ASC, key ASC"
                    )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get_all)

    async def set_runtime_config(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        await self._ensure_schema()

        def _sync_set():
            conn = self._get_connection()
            try:
                now_str = datetime.now(timezone.utc).isoformat()
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        category = COALESCE(excluded.category, runtime_configs.category),
                        description = COALESCE(excluded.description, runtime_configs.description),
                        updated_by = excluded.updated_by,
                        updated_at = excluded.updated_at
                    """,
                    (key, str(value), category, description, updated_by, now_str, now_str),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(_sync_set)

    async def delete_runtime_config(self, key: str) -> bool:
        await self._ensure_schema()

        def _sync_del():
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM runtime_configs WHERE key = ?", (key,))
                conn.commit()
                return cur.rowcount > 0
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_del)


    # ------------------------------------------------------------------
    # Research workspace scope (sql/017)
    # ------------------------------------------------------------------

    async def save_research_workspace(self, workspace: ResearchWorkspace) -> ResearchWorkspace:
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO research_workspaces
                    (id, slug, name, root_path, format_version, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO UPDATE SET
                        name = excluded.name,
                        status = excluded.status,
                        format_version = excluded.format_version
                    """,
                    (
                        str(workspace.workspace_id),
                        workspace.slug,
                        workspace.name or workspace.slug,
                        str(workspace.root_path),
                        workspace.format_version,
                        workspace.status.value,
                        workspace.created_at.isoformat(),
                    ),
                )
                conn.commit()
                return workspace
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    @staticmethod
    def _workspace_from_row(row: Any) -> ResearchWorkspace:
        return ResearchWorkspace(
            slug=row["slug"],
            root_path=Path(row["root_path"]),
            workspace_id=UUID(row["id"]),
            name=row["name"],
            format_version=int(row["format_version"]),
            status=WorkspaceStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def get_research_workspace(self, workspace_id: UUID) -> Optional[ResearchWorkspace]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT id, slug, name, root_path, format_version, status, created_at"
                    " FROM research_workspaces WHERE id = ?",
                    (str(workspace_id),),
                ).fetchone()
                return self._workspace_from_row(row) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def find_research_workspace_by_slug(
        self, slug: str, root_path: Optional[Path] = None
    ) -> Optional[ResearchWorkspace]:
        await self._ensure_schema()

        def _sync_find():
            conn = self._get_connection()
            try:
                base = (
                    "SELECT id, slug, name, root_path, format_version, status, created_at"
                    " FROM research_workspaces WHERE slug = ?"
                )
                if root_path is not None:
                    row = conn.execute(
                        base + " AND root_path = ?", (slug, str(root_path))
                    ).fetchone()
                else:
                    row = conn.execute(
                        base + " ORDER BY created_at DESC LIMIT 1", (slug,)
                    ).fetchone()
                return self._workspace_from_row(row) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_find)

    async def list_research_workspaces(self, limit: int = 50) -> List[ResearchWorkspace]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, slug, name, root_path, format_version, status, created_at"
                    " FROM research_workspaces ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                return [self._workspace_from_row(r) for r in rows]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    @staticmethod
    def _next_revision_number(cur, workspace_id: UUID) -> int:
        """The next number in this research line, read inside the writing transaction."""
        row = cur.execute(
            "SELECT MAX(revision_number) FROM market_brief_revisions WHERE workspace_id = ?",
            (str(workspace_id),),
        ).fetchone()
        return int((row[0] if row else None) or 0) + 1

    @staticmethod
    def _write_brief_revision_row(cur, revision: MarketBriefRevision) -> None:
        """A plain INSERT, never an upsert.

        A confirmed Brief is immutable, so a second write against the same mission or revision
        number is a caller trying to edit history rather than a retry to absorb.
        """
        cur.execute(
            """
            INSERT INTO market_brief_revisions
            (id, workspace_id, mission_id, revision_number, decision, target_user,
             problem, geo, timeframe, hypothesis, falsifiers, alternative_hypotheses,
             null_hypothesis, kill_criteria, revision_rule, evidence_contract_version,
             confirmed_by, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(revision.brief_revision_id),
                str(revision.workspace_id),
                str(revision.mission_id),
                revision.revision_number,
                revision.decision,
                revision.target_user,
                revision.problem,
                revision.geo,
                revision.timeframe,
                revision.hypothesis,
                json.dumps(list(revision.falsifiers), ensure_ascii=False),
                (
                    json.dumps(list(revision.alternative_hypotheses), ensure_ascii=False)
                    if revision.alternative_hypotheses is not None
                    else None
                ),
                revision.null_hypothesis,
                (
                    json.dumps(list(revision.kill_criteria), ensure_ascii=False)
                    if revision.kill_criteria is not None
                    else None
                ),
                revision.revision_rule,
                revision.evidence_contract_version,
                revision.confirmed_by,
                revision.confirmed_at.isoformat(),
            ),
        )

    async def save_brief_revision(self, revision: MarketBriefRevision) -> MarketBriefRevision:
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                self._write_brief_revision_row(conn.cursor(), revision)
                conn.commit()
                return revision
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RepositoryException(BRIEF_ALREADY_CONFIRMED) from exc
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    async def create_market_mission_with_brief(
        self, mission: ResearchMission, revision: MarketBriefRevision
    ) -> Tuple[ResearchMission, MarketBriefRevision]:
        """Write the Market mission and the Brief that authorizes it, or write neither.

        One transaction, because the two rows are one fact. Writing the mission first and the
        revision second left an orphan MARKET mission behind whenever the second write failed --
        a mission that cannot run, because the execution gate refuses a Market mission with no
        confirmed Brief, and that nothing would ever clean up. A compensating delete is not the
        fix: the mission row cascades to mission_evidence, so a delete that raced anything would
        withdraw evidence rather than undo a half-write.
        """
        await self._ensure_schema()

        def _sync_create():
            conn = self._get_connection()
            try:
                # The write lock is taken before the maximum is read. Reading it first and
                # inserting afterwards left a window in which two confirmations saw the same
                # number, and the loser failed on the unique constraint reporting the Brief as
                # already confirmed -- which is not what had happened.
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                numbered = dataclasses.replace(
                    revision,
                    revision_number=self._next_revision_number(cur, revision.workspace_id),
                )
                self._write_mission_row(cur, mission)
                self._write_brief_revision_row(cur, numbered)
                conn.commit()
                return mission, numbered
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RepositoryException(BRIEF_ALREADY_CONFIRMED) from exc
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_create)

    async def create_attention_mission_with_manifest(
        self, mission: ResearchMission, manifest: MissionManifest
    ) -> Tuple[ResearchMission, MissionManifest]:
        """Write the surfaced mission and its authority contract in one transaction."""
        if manifest.mission_id != mission.id:
            raise InvalidMissionManifestError(
                "The persisted manifest must carry the mission it authorizes."
            )
        await self._ensure_schema()

        def _sync_create():
            conn = self._get_connection()
            try:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                self._write_mission_row(cur, mission)
                self._write_manifest_row(cur, manifest)
                conn.commit()
                return mission, manifest
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_create)

    async def create_market_mission_with_brief_and_manifest(
        self,
        mission: ResearchMission,
        revision: MarketBriefRevision,
        manifest: MissionManifest,
    ) -> Tuple[ResearchMission, MarketBriefRevision, MissionManifest]:
        """Write all three records that make one Market assignment executable."""
        if manifest.mission_id != mission.id:
            raise InvalidMissionManifestError(
                "The persisted manifest must carry the mission it authorizes."
            )
        await self._ensure_schema()

        def _sync_create():
            conn = self._get_connection()
            try:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                numbered = dataclasses.replace(
                    revision,
                    revision_number=self._next_revision_number(cur, revision.workspace_id),
                )
                self._write_mission_row(cur, mission)
                self._write_brief_revision_row(cur, numbered)
                self._write_manifest_row(cur, manifest)
                conn.commit()
                return mission, numbered, manifest
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RepositoryException(BRIEF_ALREADY_CONFIRMED) from exc
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_create)

    @staticmethod
    def _brief_from_row(row: Any) -> MarketBriefRevision:
        return MarketBriefRevision(
            brief_revision_id=UUID(row["id"]),
            workspace_id=UUID(row["workspace_id"]),
            mission_id=UUID(row["mission_id"]),
            revision_number=int(row["revision_number"]),
            decision=row["decision"],
            target_user=row["target_user"],
            problem=row["problem"],
            geo=row["geo"],
            timeframe=row["timeframe"],
            hypothesis=row["hypothesis"],
            falsifiers=tuple(json.loads(row["falsifiers"])),
            alternative_hypotheses=(
                tuple(json.loads(row["alternative_hypotheses"]))
                if row["alternative_hypotheses"] is not None
                else None
            ),
            null_hypothesis=row["null_hypothesis"],
            kill_criteria=(
                tuple(json.loads(row["kill_criteria"]))
                if row["kill_criteria"] is not None
                else None
            ),
            revision_rule=row["revision_rule"],
            confirmed_by=row["confirmed_by"],
            confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        )

    _BRIEF_COLUMNS = (
        "SELECT id, workspace_id, mission_id, revision_number, decision, target_user, problem,"
        " geo, timeframe, hypothesis, falsifiers, alternative_hypotheses, null_hypothesis,"
        " kill_criteria, revision_rule, evidence_contract_version, confirmed_by, confirmed_at"
        " FROM market_brief_revisions"
    )

    async def get_brief_revision(
        self, workspace_id: UUID, brief_revision_id: UUID
    ) -> Optional[MarketBriefRevision]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    self._BRIEF_COLUMNS + " WHERE id = ?", (str(brief_revision_id),)
                ).fetchone()
                if not row:
                    return None
                if row["workspace_id"] != str(workspace_id):
                    # An error, not an empty result. An empty result reads as "this research has
                    # no such Brief", which is a different and much quieter untruth.
                    raise WorkspaceScopeMismatchError(
                        f"Brief revision {brief_revision_id} belongs to workspace "
                        f"{row['workspace_id']}, not to {workspace_id}."
                    )
                return self._brief_from_row(row)
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def get_brief_revision_for_mission(
        self, mission_id: UUID
    ) -> Optional[MarketBriefRevision]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    self._BRIEF_COLUMNS + " WHERE mission_id = ?", (str(mission_id),)
                ).fetchone()
                return self._brief_from_row(row) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def next_brief_revision_number(self, workspace_id: UUID) -> int:
        await self._ensure_schema()

        def _sync_next():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT MAX(revision_number) FROM market_brief_revisions WHERE workspace_id = ?",
                    (str(workspace_id),),
                ).fetchone()
                return int(row[0] or 0) + 1
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_next)

    async def list_workspace_missions(
        self, workspace_id: UUID, limit: int = 50
    ) -> List[ResearchMission]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, title, keywords, platforms, shortcode, geo_code, timeframe,"
                    " status, agent, session_id, summary, workspace_id, surface,"
                    " parent_attention_mission_id, parent_cluster_id, brief_revision_id,"
                    " revises_mission_id, created_at, updated_at FROM research_missions"
                    " WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (str(workspace_id), limit),
                ).fetchall()
                missions: List[ResearchMission] = []
                for r in rows:
                    missions.append(
                        ResearchMission(
                            id=UUID(r["id"]),
                            title=r["title"],
                            keywords=json.loads(r["keywords"]) if r["keywords"] else [],
                            platforms=_platforms_of(r),
                            shortcode=r["shortcode"],
                            geo_code=resolve_geo(r["geo_code"]),
                            timeframe=resolve_timeframe(r["timeframe"]),
                            status=r["status"],
                            agent=r["agent"],
                            session_id=r["session_id"],
                            summary=r["summary"],
                            workspace_id=_uuid_or_none(r["workspace_id"]),
                            surface=r["surface"],
                            parent_attention_mission_id=_uuid_or_none(
                                r["parent_attention_mission_id"]
                            ),
                            parent_cluster_id=_uuid_or_none(r["parent_cluster_id"]),
                            brief_revision_id=_uuid_or_none(r["brief_revision_id"]),
                            revises_mission_id=_uuid_or_none(r["revises_mission_id"]),
                            created_at=datetime.fromisoformat(r["created_at"]),
                        )
                    )
                return missions
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    @staticmethod
    def _manifest_from_row(row: Any) -> MissionManifest:
        authority = json.loads(row["authority_boundary"])
        return MissionManifest(
            mission_id=UUID(row["mission_id"]),
            outcome=row["outcome"],
            decision_context=row["decision_context"],
            required_channels=tuple(json.loads(row["required_channels"])),
            optional_channels=tuple(json.loads(row["optional_channels"])),
            authority_boundary=AuthorityBoundary(**authority),
            quota_budget=json.loads(row["quota_budget"]),
            output_type=row["output_type"],
            stop_conditions=tuple(json.loads(row["stop_conditions"])),
            analysis_policy=row["analysis_policy"],
            retention_policy=row["retention_policy"],
            created_by=row["created_by"],
            confirmed_at=datetime.fromisoformat(row["confirmed_at"]),
        )

    @staticmethod
    def _write_manifest_row(cur, manifest: MissionManifest) -> None:
        cur.execute(
            "INSERT INTO mission_manifests"
            " (mission_id, outcome, decision_context, required_channels, optional_channels,"
            " authority_boundary, quota_budget, output_type, stop_conditions,"
            " analysis_policy, retention_policy, created_by, confirmed_at, manifest_digest)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(manifest.mission_id),
                manifest.outcome,
                manifest.decision_context,
                json.dumps(list(manifest.required_channels), ensure_ascii=False),
                json.dumps(list(manifest.optional_channels), ensure_ascii=False),
                json.dumps(manifest.authority_boundary.to_payload(), sort_keys=True),
                json.dumps(dict(manifest.quota_budget), sort_keys=True),
                manifest.output_type.value,
                json.dumps(list(manifest.stop_conditions), ensure_ascii=False),
                manifest.analysis_policy,
                manifest.retention_policy,
                manifest.created_by,
                manifest.confirmed_at.isoformat(),
                manifest.manifest_digest,
            ),
        )

    async def save_mission_manifest(self, manifest: MissionManifest) -> MissionManifest:
        if manifest.mission_id is None:
            raise InvalidMissionManifestError("A persisted manifest requires mission_id.")
        await self._ensure_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                conn.execute("SAVEPOINT save_manifest")
                try:
                    self._write_manifest_row(conn.cursor(), manifest)
                except sqlite3.IntegrityError:
                    conn.execute("ROLLBACK TO save_manifest")
                finally:
                    conn.execute("RELEASE save_manifest")
                row = conn.execute(
                    "SELECT * FROM mission_manifests WHERE mission_id = ?",
                    (str(manifest.mission_id),),
                ).fetchone()
                stored = self._manifest_from_row(row)
                if stored.manifest_digest != manifest.manifest_digest:
                    raise InvalidMissionManifestError(
                        f"Mission {manifest.mission_id} already has a different immutable manifest."
                    )
                conn.commit()
                return stored
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    async def get_mission_manifest(self, mission_id: UUID) -> Optional[MissionManifest]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT * FROM mission_manifests WHERE mission_id = ?", (str(mission_id),)
                ).fetchone()
                return self._manifest_from_row(row) if row else None
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def claim_mission_writer(self, mission_id: UUID, run_id: UUID) -> bool:
        await self._ensure_schema()

        def _sync_claim():
            conn = self._get_connection()
            try:
                # One statement, and the primary key is what decides. A SELECT followed by an
                # INSERT would leave a window in which two runs both saw the slot free.
                cur = conn.execute(
                    "INSERT OR IGNORE INTO mission_writer_claims (mission_id, run_id, claimed_at)"
                    " VALUES (?, ?, ?)",
                    (str(mission_id), str(run_id), datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
                return cur.rowcount > 0
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_claim)

    async def release_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        await self._ensure_schema()

        def _sync_release():
            conn = self._get_connection()
            try:
                # Scoped to the run that holds it: a run that never claimed the slot must not be
                # able to release another run's claim.
                conn.execute(
                    "DELETE FROM mission_writer_claims WHERE mission_id = ? AND run_id = ?",
                    (str(mission_id), str(run_id)),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(_sync_release)

    async def get_mission_writer_claim(self, mission_id: UUID) -> Optional[MissionWriterClaim]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT mission_id, run_id, claimed_at FROM mission_writer_claims"
                    " WHERE mission_id = ?",
                    (str(mission_id),),
                ).fetchone()
                if not row:
                    return None
                return MissionWriterClaim(
                    mission_id=UUID(row["mission_id"]),
                    run_id=UUID(row["run_id"]),
                    claimed_at=datetime.fromisoformat(row["claimed_at"])
                    if row["claimed_at"]
                    else None,
                )
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    async def list_run_journals(self, mission_id: UUID, limit: int = 20) -> List[RunJournal]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT id, workspace_id, mission_id, journal_path, sequence, status,"
                    " started_at, completed_at FROM mission_run_journals"
                    " WHERE mission_id = ? ORDER BY started_at DESC, sequence DESC LIMIT ?",
                    (str(mission_id), limit),
                ).fetchall()
                return [
                    RunJournal(
                        run_id=UUID(r["id"]),
                        mission_id=UUID(r["mission_id"]),
                        workspace_id=UUID(r["workspace_id"]),
                        journal_path=Path(r["journal_path"]),
                        sequence=int(r["sequence"]),
                        status=r["status"],
                        started_at=datetime.fromisoformat(r["started_at"])
                        if r["started_at"]
                        else None,
                        # Left as None when the run never finished. A substitute clock here
                        # would report every interrupted run as having completed on read.
                        completed_at=datetime.fromisoformat(r["completed_at"])
                        if r["completed_at"]
                        else None,
                    )
                    for r in rows
                ]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def record_run_journal(self, journal: RunJournal) -> RunJournal:
        await self._ensure_schema()

        def _sync_record():
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO mission_run_journals
                    (id, workspace_id, mission_id, journal_path, sequence, status,
                     started_at, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (journal_path) DO UPDATE SET
                        status = excluded.status,
                        completed_at = excluded.completed_at
                    """,
                    (
                        str(journal.run_id),
                        str(journal.workspace_id),
                        str(journal.mission_id),
                        str(journal.journal_path),
                        journal.sequence,
                        journal.status,
                        journal.started_at.isoformat() if journal.started_at else None,
                        journal.completed_at.isoformat() if journal.completed_at else None,
                    ),
                )
                conn.commit()
                return journal
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_record)

    # ------------------------------------------------------------------
    # Probe outcomes and evidence qualifications (sql/023)
    # ------------------------------------------------------------------

    async def record_probe_outcomes(
        self, run_id: UUID, outcomes: Sequence[MissionProbeOutcome]
    ) -> int:
        """Resolve the journal scope and return the original atomic publication count."""
        rows = tuple(outcomes)
        if any(str(o.run_id) != str(run_id) for o in rows):
            raise InvalidEvidenceQualificationError(
                f"Every probe outcome recorded for run {run_id} must belong to that run."
            )
        receipt = await self._publish_probe_outcomes(run_id, rows)
        return receipt.outcome_count if receipt is not None else 0

    async def commit_probe_outcomes(
        self, command: ProbeOutcomeCommitCommand
    ) -> ProbeOutcomeCommitReceipt:
        """Commit admitted facts and their original typed receipt in one SQLite transaction."""
        if type(command) is not ProbeOutcomeCommitCommand:
            raise ValueError("A probe publication requires an admitted commit command.")
        receipt = await self._publish_probe_outcomes(command.run_id, command.outcomes, command)
        assert receipt is not None  # Admitted commands cannot contain an empty batch.
        return receipt

    @staticmethod
    def _probe_fact_value(value: Any) -> Any:
        """Encode the admitted recursive values without thawing caller-owned aliases."""
        if isinstance(value, Mapping):
            return {key: SqliteTrendRepository._probe_fact_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [SqliteTrendRepository._probe_fact_value(item) for item in value]
        if isinstance(value, Enum):
            return SqliteTrendRepository._probe_fact_value(value.value)
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return value

    async def _publish_probe_outcomes(
        self,
        run_id: UUID,
        rows: tuple[MissionProbeOutcome, ...],
        command: ProbeOutcomeCommitCommand | None = None,
    ) -> ProbeOutcomeCommitReceipt | None:
        """Keep schema setup outside the physical fact transaction and ownership until settlement."""
        await self._ensure_schema()
        await self._ensure_progress_schema()

        def _sync_record() -> ProbeOutcomeCommitReceipt | None:
            conn = self._get_connection()
            try:
                conn.execute("BEGIN IMMEDIATE")
                journal = conn.execute(
                    "SELECT mission_id FROM mission_run_journals WHERE id = ?", (str(run_id),)
                ).fetchone()
                if journal is None:
                    if command is None and not rows:
                        # The legacy empty call never admitted a fact or required a journal.
                        conn.rollback()
                        return None
                    raise RepositoryException("Probe publication requires a recorded run journal.")
                mission_id = UUID(journal["mission_id"])
                if command is not None and command.mission_id != mission_id:
                    raise RepositoryException("Probe command mission does not own its recorded run.")
                admitted = command
                if admitted is None and rows:
                    try:
                        admitted = ProbeOutcomeCommitCommand(
                            mission_id=mission_id, run_id=run_id, outcomes=rows
                        )
                    except ValueError as exc:
                        raise RepositoryException("Probe facts were refused before publication.") from exc
                if admitted is not None:
                    original = conn.execute(
                        "SELECT c.payload_fingerprint, c.outcome_count, e.*"
                        " FROM mission_progress_commands c JOIN mission_progress_events e"
                        " ON e.id = c.event_id AND e.mission_id = c.mission_id"
                        " WHERE c.mission_id = ? AND c.command_key = ?",
                        (str(mission_id), admitted.command_key),
                    ).fetchone()
                    if original is not None:
                        if original["payload_fingerprint"] != admitted.payload_fingerprint:
                            raise RepositoryException("Probe command conflicts with its original committed facts.")
                        receipt = ProbeOutcomeCommitReceipt(
                            command_key=admitted.command_key,
                            payload_fingerprint=original["payload_fingerprint"],
                            outcome_count=original["outcome_count"],
                            event=MissionProgressEvent(
                                event_id=UUID(original["id"]),
                                cursor=MissionRelayCursor(
                                    mission_id=mission_id, revision=original["revision"], ordinal=original["ordinal"]
                                ),
                                kind=MissionProgressKind(original["kind"]),
                                provenance=RelayProvenance(original["provenance"]),
                                recorded_at=datetime.fromisoformat(original["recorded_at"]),
                                causation_key=original["causation_key"],
                                run_id=UUID(original["run_id"]),
                            ),
                        )
                        # An identical retry performs no durable writes or cursor advance.
                        conn.rollback()
                        return receipt
                manifest_row = conn.execute(
                    "SELECT m.required_channels, m.optional_channels"
                    " FROM mission_run_journals j"
                    " JOIN mission_manifests m ON m.mission_id = j.mission_id"
                    " WHERE j.id = ?",
                    (str(run_id),),
                ).fetchone()
                if manifest_row is not None:
                    require_complete_channel_outcomes(
                        json.loads(manifest_row["required_channels"]),
                        json.loads(manifest_row["optional_channels"]),
                        admitted.outcomes if admitted is not None else rows,
                    )
                if admitted is None:
                    conn.rollback()
                    return None
                conn.executemany(
                    "INSERT INTO mission_probe_outcomes (id, run_id, platform, connector_surface,"
                    " status, signals_collected, queried_keywords, queried_window,"
                    " query_fingerprint, scope_attestation, note, collection_plan_digest,"
                    " evidence_contract_version, completed_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            str(o.outcome_id),
                            str(o.run_id),
                            o.platform,
                            o.connector_surface,
                            o.status.value,
                            o.signals_collected,
                            json.dumps(o.queried_keywords, ensure_ascii=False),
                            o.queried_window,
                            o.query_fingerprint,
                            (
                                json.dumps(
                                    self._probe_fact_value(o.scope_attestation),
                                    sort_keys=True, ensure_ascii=False, allow_nan=False,
                                    separators=(",", ":"),
                                )
                                if o.scope_attestation is not None
                                else None
                            ),
                            o.note,
                            o.collection_plan_digest,
                            2 if o.collection_plan_digest is not None else 1,
                            o.completed_at.isoformat(),
                        )
                        for o in admitted.outcomes
                    ],
                )
                conn.execute(
                    "INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (?, 1)"
                    " ON CONFLICT(mission_id) DO UPDATE SET revision = revision + 1",
                    (str(mission_id),),
                )
                revision = conn.execute(
                    "SELECT revision FROM mission_progress_revisions WHERE mission_id = ?",
                    (str(mission_id),),
                ).fetchone()["revision"]
                event = MissionProgressEvent(
                    event_id=uuid4(),
                    cursor=MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=1),
                    kind=MissionProgressKind.PROBE_OUTCOMES_RECORDED,
                    provenance=RelayProvenance.HARNESS_OBSERVED,
                    recorded_at=datetime.now(timezone.utc),
                    causation_key=admitted.command_key,
                    run_id=run_id,
                )
                receipt = ProbeOutcomeCommitReceipt(
                    command_key=admitted.command_key,
                    payload_fingerprint=admitted.payload_fingerprint,
                    outcome_count=len(admitted.outcomes), event=event,
                )
                conn.execute(
                    "INSERT INTO mission_progress_events (id, mission_id, revision, ordinal, kind,"
                    " provenance, recorded_at, causation_key, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(event.event_id), str(mission_id), revision, 1, event.kind.value,
                     event.provenance.value, event.recorded_at.isoformat(), event.causation_key, str(run_id)),
                )
                conn.execute(
                    "INSERT INTO mission_progress_commands (mission_id, command_key, payload_fingerprint,"
                    " outcome_count, run_id, event_id, revision, ordinal) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(mission_id), receipt.command_key, receipt.payload_fingerprint, receipt.outcome_count,
                     str(run_id), str(event.event_id), revision, 1),
                )
                conn.commit()
                return receipt
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise RepositoryException(
                    f"Probe outcomes for run {run_id} were refused and none was written: {exc}"
                ) from exc
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_record)

    async def get_latest_completed_probe_outcomes(
        self, mission_id: UUID
    ) -> List[MissionProbeOutcome]:
        await self._ensure_schema()

        def _sync_get():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT o.id, o.run_id, o.platform, o.connector_surface, o.status,"
                    " o.signals_collected, o.query_fingerprint, o.completed_at,"
                    " o.queried_keywords, o.queried_window, o.scope_attestation, o.note,"
                    " o.collection_plan_digest"
                    " FROM mission_probe_outcomes o"
                    " WHERE o.run_id = ("
                    "   SELECT j.id FROM mission_run_journals j"
                    "   WHERE j.mission_id = ? AND j.status = 'COMPLETED'"
                    "   ORDER BY j.started_at DESC, j.sequence DESC LIMIT 1)"
                    " ORDER BY o.connector_surface",
                    (str(mission_id),),
                ).fetchall()
                return [
                    MissionProbeOutcome(
                        outcome_id=UUID(r["id"]),
                        run_id=UUID(r["run_id"]),
                        platform=r["platform"],
                        connector_surface=r["connector_surface"],
                        status=r["status"],
                        signals_collected=int(r["signals_collected"]),
                        query_fingerprint=r["query_fingerprint"],
                        completed_at=datetime.fromisoformat(r["completed_at"]),
                        queried_keywords=tuple(json.loads(r["queried_keywords"] or "[]")),
                        queried_window=r["queried_window"],
                        scope_attestation=(
                            json.loads(r["scope_attestation"])
                            if r["scope_attestation"] is not None
                            else None
                        ),
                        note=r["note"],
                        collection_plan_digest=r["collection_plan_digest"],
                    )
                    for r in rows
                ]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_get)

    _QUALIFICATION_COLUMNS = (
        "SELECT mission_id, observation_id, brief_revision_id, frame_fingerprint, relation,"
        " purpose, confidence, reason_code, judged_by, model, hypothesis_target, evidence_role,"
        " evidence_contract_version, created_at"
        " FROM mission_evidence_qualifications"
    )

    @staticmethod
    def _qualification_from_row(row: Any) -> EvidenceQualification:
        return EvidenceQualification(
            mission_id=UUID(row["mission_id"]),
            observation_id=UUID(row["observation_id"]),
            brief_revision_id=_uuid_or_none(row["brief_revision_id"]),
            frame_fingerprint=row["frame_fingerprint"],
            relation=row["relation"],
            purpose=row["purpose"],
            confidence=row["confidence"],
            reason_code=row["reason_code"],
            judged_by=row["judged_by"],
            model=row["model"],
            hypothesis_target=row["hypothesis_target"],
            evidence_role=row["evidence_role"],
            evidence_contract_version=row["evidence_contract_version"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    async def list_evidence_qualifications(
        self, mission_id: UUID
    ) -> List[EvidenceQualification]:
        await self._ensure_schema()

        def _sync_list():
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    self._QUALIFICATION_COLUMNS + " WHERE mission_id = ? ORDER BY observation_id",
                    (str(mission_id),),
                ).fetchall()
                return [self._qualification_from_row(r) for r in rows]
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await asyncio.to_thread(_sync_list)

    async def save_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]
    ) -> int:
        """Persist one batch atomically; replay is idempotent, a rewrite is refused. See the port."""
        return await self._save_evidence_qualifications(mission_id, qualifications, progress=False)

    async def commit_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]
    ) -> int:
        """Commit new canonical judgments and one matching batch receipt atomically."""
        return await self._save_evidence_qualifications(mission_id, qualifications, progress=True)

    async def _save_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification], *, progress: bool
    ) -> int:
        batch = list(qualifications)
        if any(str(q.mission_id) != str(mission_id) for q in batch):
            raise InvalidEvidenceQualificationError(
                f"Every judgment in a batch for mission {mission_id} must name that mission."
            )
        if not batch:
            return 0
        await self._ensure_schema()
        if progress:
            await self._ensure_progress_schema()

        def _sync_save():
            conn = self._get_connection()
            try:
                if not conn.in_transaction:
                    conn.execute("BEGIN IMMEDIATE")
                if progress:
                    snapshot = self._commit_snapshot(conn, mission_id)
                    if snapshot.mission is None or any(
                        q.frame_fingerprint != compute_frame_fingerprint(snapshot.mission, snapshot.brief)
                        or q.brief_revision_id != (snapshot.brief.brief_revision_id if snapshot.brief else None)
                        for q in batch
                    ):
                        raise StaleEvidenceQualificationError("The submitted qualification frame is stale.")
                recorded = []
                now = datetime.now(timezone.utc).isoformat()
                for q in batch:
                    # Insert-or-keep, then compare: the unique pair decides a race, and the
                    # comparison decides whether the survivor says the same thing.
                    inserted = conn.execute(
                        "INSERT INTO mission_evidence_qualifications (id, mission_id,"
                        " observation_id, brief_revision_id, frame_fingerprint, relation, purpose,"
                        " confidence, reason_code, judged_by, model, hypothesis_target,"
                        " evidence_role, evidence_contract_version, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                        " ON CONFLICT (mission_id, observation_id) DO NOTHING",
                        (
                            str(uuid4()),
                            str(q.mission_id),
                            str(q.observation_id),
                            str(q.brief_revision_id) if q.brief_revision_id else None,
                            q.frame_fingerprint,
                            q.relation.value,
                            q.purpose.value,
                            q.confidence,
                            q.reason_code.value,
                            q.judged_by,
                            q.model,
                            q.hypothesis_target,
                            q.evidence_role.value if q.evidence_role else None,
                            q.evidence_contract_version,
                            now,
                        ),
                    ).rowcount
                    if inserted:
                        recorded.append(q)
                        continue
                    existing = conn.execute(
                        self._QUALIFICATION_COLUMNS + " WHERE mission_id = ? AND observation_id = ?",
                        (str(q.mission_id), str(q.observation_id)),
                    ).fetchone()
                    if existing is None or not self._qualification_from_row(existing).same_judgment(q):
                        raise EvidenceQualificationConflictError(
                            f"Observation {q.observation_id} already carries a different judgment "
                            f"for mission {mission_id}. A recorded judgment is not rewritten; a "
                            "different one needs a new mission or Market Brief revision."
                        )
                if progress and recorded:
                    refs = tuple(self._progress_reference(conn, mission_id, q.observation_id)
                                 for q in recorded)
                    self._record_progress(
                        conn, mission_id, MissionProgressKind.QUALIFICATION_RECORDED,
                        f"qualification:{mission_id}:{uuid4()}", references=refs,
                    )
                conn.commit()
                return len(batch)
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise InvalidEvidenceQualificationError(
                    f"The batch names evidence mission {mission_id} does not hold, so none of it "
                    f"was recorded: {exc}"
                ) from exc
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(_sync_save)

    async def _ensure_research_schema(self) -> None:
        """Only authorized writers install additive research storage."""
        from ignis.infrastructure.persistence.sqlite_research_schema import install_research_schema

        def setup():
            conn = self._get_connection()
            try:
                install_research_schema(conn)
            finally:
                if self._mem_conn is None:
                    conn.close()

        await self._run_write(setup)

    @staticmethod
    def _research_receipt(row):
        from ignis.application.ports.research_work_port import ResearchWorkCommitReceipt

        return ResearchWorkCommitReceipt(
            disposition=row["disposition"],
            reason_code=row["reason_code"],
            revision=row["revision"],
            work_version=row["work_version"],
            assignment_version=row["assignment_version"],
            receipt_id=UUID(row["receipt_id"]),
            event_ids=tuple(UUID(v) for v in json.loads(row["event_ids"])),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
        )

    def _research_snapshot(self, conn, mission_id):
        from ignis.application.ports.research_work_port import ResearchRecordedMetadata, ResearchWorkSnapshot
        from ignis.domain.research_work import (
            ResearchAuthority,
            ResearchAssignment,
            ResearchInputBindings,
            ResearchWorkItem,
        )
        from ignis.infrastructure.persistence.mission_relay_reader import _event

        scope = (str(mission_id),)
        revision_row = conn.execute(
            "SELECT revision FROM mission_progress_revisions WHERE mission_id=?", scope
        ).fetchone()
        revision = revision_row[0] if revision_row else 0
        pairs = tuple(
            (UUID(r[0]), UUID(r[1]))
            for r in conn.execute(
                "SELECT o.id,o.source_id FROM observations o JOIN mission_evidence e ON e.observation_id=o.id WHERE e.mission_id=? ORDER BY o.id",
                scope,
            )
        )
        events = tuple(
            _event(r)
            for r in conn.execute(
                "SELECT * FROM mission_progress_events WHERE mission_id=? ORDER BY revision,ordinal", scope
            )
        )
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_assignments'"
        ).fetchone()
        assignments, works, metadata = (), (), ()
        if exists:
            assignments = tuple(
                ResearchAssignment(
                    assignment_id=UUID(r["assignment_id"]),
                    mission_id=mission_id,
                    host_task_ref=r["host_task_ref"],
                    epoch=r["epoch"],
                    authority=ResearchAuthority(
                        actions=frozenset(json.loads(r["actions"])),
                        sources=frozenset(json.loads(r["sources"])),
                        deadline=datetime.fromisoformat(r["deadline"]),
                        quota_ceiling=r["quota_ceiling"],
                    ),
                    capability=r["capability"],
                    state=r["state"],
                    version=r["version"],
                )
                for r in conn.execute("SELECT * FROM research_assignments WHERE mission_id=? ORDER BY epoch", scope)
            )

            def bindings(input_id):
                r = conn.execute("SELECT * FROM research_input_sets WHERE input_id=?", (input_id,)).fetchone()
                return ResearchInputBindings(
                    mission_id=mission_id,
                    manifest_digest=r["manifest_digest"],
                    brief_digest=r["brief_digest"],
                    frame_digest=r["frame_digest"],
                    observation_ids=tuple(
                        UUID(o[0])
                        for o in conn.execute(
                            "SELECT observation_id FROM research_input_observations WHERE input_id=? ORDER BY ordinal",
                            (input_id,),
                        )
                    ),
                    finding_revisions=tuple(
                        (UUID(f[0]), f[1])
                        for f in conn.execute(
                            "SELECT finding_id,revision FROM research_input_findings WHERE input_id=? ORDER BY ordinal",
                            (input_id,),
                        )
                    ),
                )

            works = tuple(
                ResearchWorkItem(
                    work_id=UUID(r["work_id"]),
                    assignment_id=UUID(r["assignment_id"]),
                    mission_id=mission_id,
                    run_id=UUID(r["run_id"]) if r["run_id"] else None,
                    question=r["question"],
                    expertise=r["expertise"],
                    assignee_ref=r["assignee_ref"],
                    inputs=bindings(r["input_id"]),
                    dependencies=tuple(
                        UUID(d[0])
                        for d in conn.execute(
                            "SELECT dependency_work_id FROM research_work_dependencies WHERE work_id=? ORDER BY ordinal",
                            (r["work_id"],),
                        )
                    ),
                    epoch=r["epoch"],
                    state=r["state"],
                    version=r["version"],
                    ownership_fence=r["ownership_fence"],
                )
                for r in conn.execute("SELECT * FROM research_work_items WHERE mission_id=? ORDER BY rowid", scope)
            )
            metadata = tuple(
                ResearchRecordedMetadata(
                    record_kind=r["record_kind"],
                    record_id=UUID(r["record_id"]),
                    record_version=r["record_version"],
                    mission_revision=r["mission_revision"],
                    recorded_at=datetime.fromisoformat(r["recorded_at"]),
                    provenance=r["provenance"],
                )
                for r in conn.execute(
                    "SELECT * FROM research_recorded_metadata WHERE mission_id=? ORDER BY mission_revision,record_kind,record_id",
                    scope,
                )
            )
        return ResearchWorkSnapshot(
            mission_id=mission_id,
            revision=revision,
            current_epoch=max((a.epoch for a in assignments), default=0),
            assignments=assignments,
            work_items=works,
            handoffs=(),
            findings=(),
            acknowledgements=(),
            events=events,
            observation_sources=pairs,
            current_finding_revisions=(),
            recorded_metadata=metadata,
        )

    async def load_research_work(self, mission_id):
        """Read a held coherent physical transaction; never bootstrap on a read."""

        def read():
            conn = self._mem_conn
            owned = conn is None
            if owned:
                conn = sqlite3.connect(Path(self._db_path).resolve().as_uri() + "?mode=ro", uri=True)
                conn.row_factory = sqlite3.Row
            try:
                conn.execute("BEGIN")
                result = self._research_snapshot(conn, mission_id)
                conn.rollback()
                return result
            except BaseException:
                conn.rollback()
                raise
            finally:
                if owned:
                    conn.close()

        return await self._run_write(read)

    async def commit_research_work(self, command):
        """Admit and settle core lifecycle facts, event, metadata and original receipt together."""
        from ignis.application.ports.research_work_port import ResearchWorkCommitCommand, ResearchWorkCommitReceipt
        from ignis.domain.research_work import (
            ACTIONS,
            TERMINAL,
            ResearchWorkCommand,
            StartWorkPayload,
            transition_research_work,
        )
        from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
        from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text

        if type(command) is not ResearchWorkCommitCommand:
            raise ValueError("Invalid exact research command.")
        await self._ensure_schema()
        await self._ensure_progress_schema()
        await self._ensure_research_schema()

        def commit():
            conn = self._get_connection()
            now = datetime.now(timezone.utc)
            revision = 0
            initial_revision = 0

            def receipt(reason=None, work=None, assignment=None, event_ids=()):
                return ResearchWorkCommitReceipt(
                    disposition="REFUSED" if reason else "APPLIED",
                    reason_code=reason,
                    revision=revision,
                    work_version=work.version if work else None,
                    assignment_version=assignment.version if assignment else None,
                    receipt_id=uuid4(),
                    event_ids=event_ids,
                    recorded_at=now,
                )

            def persist(result):
                # Raw key is hashed; raw command fingerprint remains unchanged, including rejected text.
                conn.execute(
                    "INSERT INTO research_work_commands (mission_id,command_key,payload_fingerprint,operation,receipt_id,disposition,reason_code,revision,work_version,assignment_version,event_ids,recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        str(command.mission_id),
                        key,
                        command.fingerprint,
                        command.operation,
                        str(result.receipt_id),
                        result.disposition,
                        result.reason_code,
                        result.revision,
                        result.work_version,
                        result.assignment_version,
                        json.dumps([str(e) for e in result.event_ids]),
                        now.isoformat(),
                    ),
                )
                conn.commit()
                return result

            from hashlib import sha256

            key = sha256(command.idempotency_key.encode()).hexdigest()
            try:
                conn.execute("BEGIN IMMEDIATE")
                now = datetime.now(timezone.utc)
                conn.create_function("research_transaction_time", 0, lambda: now.isoformat())
                canonical = self._commit_snapshot(conn, command.mission_id)
                if canonical.mission is None:
                    conn.rollback()
                    return receipt("SCOPE_MISMATCH")
                original = conn.execute(
                    "SELECT * FROM research_work_commands WHERE mission_id=? AND command_key=?",
                    (str(command.mission_id), key),
                ).fetchone()
                state = self._research_snapshot(conn, command.mission_id)
                revision = state.revision
                initial_revision = revision
                if original:
                    result = (
                        self._research_receipt(original)
                        if original["payload_fingerprint"] == command.fingerprint
                        else receipt("IDEMPOTENCY_CONFLICT")
                    )
                    conn.rollback()
                    return result
                payload = command.payload

                def refuse(reason):
                    return persist(receipt(reason))

                if not command.host_authorized:
                    return refuse("UNAUTHORIZED_HOST")
                if command.expected_revision != revision:
                    return refuse("STALE_REVISION")
                operation = command.operation
                closure = (
                    operation == "ACK_STOP"
                    or operation == "END_WORK"
                    and payload.disposition in {"FAILED", "INTERRUPTED", "INSUFFICIENT_EVIDENCE"}
                )
                if operation == "ASSIGN_RESEARCH":
                    if payload.assignment.mission_id != command.mission_id:
                        return refuse("SCOPE_MISMATCH")
                    if (
                        payload.assignment.epoch != command.expected_epoch
                        or command.expected_epoch != state.current_epoch + 1
                    ):
                        return refuse("STALE_EPOCH")
                elif not closure and command.expected_epoch != state.current_epoch:
                    return refuse("STALE_EPOCH")
                # Result admission and immutable result decoders belong to T049.
                if operation in {"SUBMIT_HANDOFF", "ACK_HANDOFF"}:
                    return refuse("INVALID_TRANSITION")
                assignment = None
                work = None
                record_kind = None
                kind = None
                reason_text = None
                assignment_activated = False
                if operation == "ASSIGN_RESEARCH":
                    assignment = payload.assignment
                    manifest = canonical.manifest
                    brief = canonical.brief
                    if (
                        manifest is None
                        or brief is None
                        or manifest.manifest_digest != payload.expected_manifest_digest
                        or brief.brief_revision_id != payload.expected_brief_revision_id
                    ):
                        return refuse("STALE_INPUT_FRAME")
                    if assignment.state != "ASSIGNED" or assignment.version != 1:
                        return refuse("INVALID_TRANSITION")
                    if assignment.authority.deadline <= now:
                        return refuse("AUTHORITY_EXPIRED")
                    if (
                        not assignment.authority.actions <= ACTIONS
                        or not assignment.authority.sources
                        <= set(manifest.required_channels + manifest.optional_channels)
                        or assignment.authority.quota_ceiling > sum(manifest.quota_budget.values())
                    ):
                        return refuse("AUTHORITY_WIDENING")
                    if any(a.state not in TERMINAL for a in state.assignments):
                        return refuse("INVALID_TRANSITION")
                    if any(a.assignment_id == assignment.assignment_id for a in state.assignments):
                        return refuse("INVALID_INPUT")
                    try:
                        assignment = dataclasses.replace(
                            assignment,
                            host_task_ref=sanitize_pii_text(assignment.host_task_ref),
                            capability=sanitize_pii_text(assignment.capability),
                        )
                    except ValueError:
                        return refuse("INVALID_INPUT")
                    a = assignment
                    conn.execute(
                        "INSERT INTO research_assignments (assignment_id,mission_id,host_task_ref,epoch,actions,sources,deadline,quota_ceiling,capability,expected_manifest_digest,expected_brief_revision_id,state,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            str(a.assignment_id),
                            str(a.mission_id),
                            a.host_task_ref,
                            a.epoch,
                            json.dumps(sorted(a.authority.actions)),
                            json.dumps(sorted(a.authority.sources)),
                            a.authority.deadline.isoformat(),
                            a.authority.quota_ceiling,
                            a.capability,
                            payload.expected_manifest_digest,
                            str(payload.expected_brief_revision_id),
                            a.state,
                            a.version,
                        ),
                    )
                    record_kind = "ASSIGNMENT"
                    kind = MissionProgressKind.RESEARCH_ASSIGNED
                else:
                    if operation == "ASSIGN_WORK":
                        work = payload
                        assignment = next((a for a in state.assignments if a.assignment_id == work.assignment_id), None)
                    elif operation == "END_RESEARCH":
                        assignment = next(
                            (a for a in state.assignments if a.assignment_id == payload.assignment_id), None
                        )
                    else:
                        work = next((w for w in state.work_items if w.work_id == payload.work_id), None)
                        assignment = next(
                            (a for a in state.assignments if work and a.assignment_id == work.assignment_id), None
                        )
                    if assignment is None or work is None and operation != "END_RESEARCH":
                        return refuse("SCOPE_MISMATCH")
                    if not closure:
                        if assignment.epoch != state.current_epoch:
                            return refuse("STALE_EPOCH")
                        if assignment.state in TERMINAL:
                            return refuse("ASSIGNMENT_TERMINAL")
                        if operation != "END_RESEARCH" and assignment.authority.deadline <= now:
                            return refuse("AUTHORITY_EXPIRED")
                    if operation in {"ASSIGN_WORK", "START_WORK", "RESUME_WORK", "RECORD_ACTIVITY"}:
                        manifest = canonical.manifest
                        if (
                            manifest is None
                            or not assignment.authority.actions <= ACTIONS
                            or not assignment.authority.sources
                            <= set(manifest.required_channels + manifest.optional_channels)
                            or assignment.authority.quota_ceiling > sum(manifest.quota_budget.values())
                        ):
                            return refuse("AUTHORITY_WIDENING")
                    if operation in {"START_WORK", "RESUME_WORK", "RECORD_ACTIVITY"}:
                        if not set(work.inputs.observation_ids) <= set(dict(state.observation_sources)):
                            return refuse("INPUT_IDENTITY_MISMATCH")
                        if work.inputs.finding_revisions:
                            return refuse("STALE_DEPENDENCY_REVISION")
                        try:
                            current_frame = frame_from_snapshot(canonical).frame_digest
                        except InvalidMissionClaimError:
                            return refuse("STALE_INPUT_FRAME")
                        if (
                            canonical.brief is None
                            or work.inputs.manifest_digest != canonical.manifest.manifest_digest
                            or work.inputs.brief_digest != compute_frame_fingerprint(canonical.mission, canonical.brief)
                            or work.inputs.frame_digest != current_frame
                        ):
                            return refuse("STALE_INPUT_FRAME")
                    if operation == "END_RESEARCH":
                        if payload.expected_version != assignment.version:
                            return refuse("STALE_VERSION")
                        assignment = dataclasses.replace(
                            assignment, state=payload.disposition, version=assignment.version + 1
                        )
                        reason_text = sanitize_pii_text(payload.reason)
                        conn.execute(
                            "UPDATE research_assignments SET state=?,version=?,reason=? WHERE assignment_id=?",
                            (assignment.state, assignment.version, reason_text, str(assignment.assignment_id)),
                        )
                        record_kind = "ASSIGNMENT"
                        kind = MissionProgressKind.RESEARCH_ENDED
                    elif operation == "ASSIGN_WORK":
                        if work.mission_id != command.mission_id or work.epoch != assignment.epoch:
                            return refuse("SCOPE_MISMATCH")
                        if (
                            work.state != "ASSIGNED"
                            or work.version != 1
                            or any(w.work_id == work.work_id for w in state.work_items)
                        ):
                            return refuse("INVALID_TRANSITION")
                        if assignment.state == "CANCEL_PENDING":
                            return refuse("CANCELLATION_PENDING")
                        if "ANALYZE" not in assignment.authority.actions:
                            return refuse("ACTION_NOT_GRANTED")
                        if (
                            work.run_id
                            and not conn.execute(
                                "SELECT 1 FROM mission_run_journals WHERE id=? AND mission_id=?",
                                (str(work.run_id), str(command.mission_id)),
                            ).fetchone()
                        ):
                            return refuse("SCOPE_MISMATCH")
                        current_ids = dict(state.observation_sources)
                        if not set(work.inputs.observation_ids) <= set(current_ids):
                            return refuse("INPUT_IDENTITY_MISMATCH")
                        if work.inputs.finding_revisions:
                            return refuse("STALE_DEPENDENCY_REVISION")
                        try:
                            current_frame = frame_from_snapshot(canonical).frame_digest
                        except InvalidMissionClaimError:
                            return refuse("STALE_INPUT_FRAME")
                        if (
                            canonical.manifest is None
                            or canonical.brief is None
                            or work.inputs.manifest_digest != canonical.manifest.manifest_digest
                            or work.inputs.brief_digest != compute_frame_fingerprint(canonical.mission, canonical.brief)
                            or work.inputs.frame_digest != current_frame
                        ):
                            return refuse("STALE_INPUT_FRAME")
                        dependencies = {w.work_id: w for w in state.work_items}
                        if any(d not in dependencies or dependencies[d].epoch != work.epoch for d in work.dependencies):
                            return refuse("SCOPE_MISMATCH")
                        try:
                            work = dataclasses.replace(
                                work,
                                question=sanitize_pii_text(work.question),
                                expertise=sanitize_pii_text(work.expertise),
                                assignee_ref=sanitize_pii_text(work.assignee_ref),
                            )
                        except ValueError:
                            return refuse("INVALID_INPUT")
                        if sanitize_pii_text(work.ownership_fence) != work.ownership_fence:
                            return refuse("INVALID_INPUT")
                        input_id = str(uuid4())
                        b = work.inputs
                        conn.execute(
                            "INSERT INTO research_input_sets VALUES (?,?,?,?,?)",
                            (input_id, str(b.mission_id), b.manifest_digest, b.brief_digest, b.frame_digest),
                        )
                        for ordinal, o in enumerate(b.observation_ids, 1):
                            conn.execute(
                                "INSERT INTO research_input_observations VALUES (?,?,?,?,?)",
                                (ordinal, input_id, str(command.mission_id), str(o), str(current_ids[o])),
                            )
                        w = work
                        conn.execute(
                            "INSERT INTO research_work_items (work_id,assignment_id,mission_id,input_id,run_id,question,expertise,assignee_ref,epoch,state,version,ownership_fence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (
                                str(w.work_id),
                                str(w.assignment_id),
                                str(w.mission_id),
                                input_id,
                                str(w.run_id) if w.run_id else None,
                                w.question,
                                w.expertise,
                                w.assignee_ref,
                                w.epoch,
                                w.state,
                                w.version,
                                w.ownership_fence,
                            ),
                        )
                        for ordinal, d in enumerate(w.dependencies, 1):
                            conn.execute(
                                "INSERT INTO research_work_dependencies VALUES (?,?,?,?)",
                                (ordinal, str(w.mission_id), str(w.work_id), str(d)),
                            )
                        record_kind = "WORK"
                        kind = MissionProgressKind.WORK_ASSIGNED
                    else:
                        if closure and command.expected_epoch != work.epoch:
                            return refuse("STALE_EPOCH")
                        if operation in {"START_WORK", "RECORD_ACTIVITY"}:
                            r = payload.receipt
                            if r.epoch != work.epoch:
                                return refuse("STALE_EPOCH")
                            if operation == "START_WORK" and any(
                                next(w for w in state.work_items if w.work_id == d).state
                                not in {"COMPLETED", "HANDOFF_READY"}
                                for d in work.dependencies
                            ):
                                return refuse("DEPENDENCY_NOT_READY")
                            pure_payload = StartWorkPayload(
                                work_id=payload.work_id,
                                expected_version=payload.expected_version,
                                ownership_fence=payload.ownership_fence,
                                execution_ref=r.execution_ref,
                                occurred_at=r.occurred_at,
                                fresh_until=r.fresh_until,
                            )
                        else:
                            pure_payload = payload
                        pure = ResearchWorkCommand(
                            operation=operation,
                            idempotency_key=command.idempotency_key,
                            expected_revision=command.expected_revision,
                            expected_epoch=command.expected_epoch,
                            payload=pure_payload,
                        )
                        transition = transition_research_work(work=work, assignment=assignment, command=pure, now=now)
                        if transition.disposition != "APPLIED":
                            return refuse(transition.reason_code)
                        if (
                            operation == "ACK_STOP"
                            and sanitize_pii_text(payload.execution_ref) != payload.execution_ref
                        ):
                            return refuse("INVALID_INPUT")
                        if (
                            operation == "ACK_STOP"
                            and not conn.execute(
                                "SELECT 1 FROM research_activity_receipts WHERE work_id=? AND epoch=? AND ownership_fence=? AND execution_ref=?",
                                (
                                    str(work.work_id),
                                    work.epoch,
                                    work.ownership_fence,
                                    sanitize_pii_text(payload.execution_ref),
                                ),
                            ).fetchone()
                        ):
                            return refuse("EXECUTION_RECEIPT_NOT_CURRENT")
                        if (
                            operation in {"START_WORK", "RECORD_ACTIVITY"}
                            and sanitize_pii_text(r.execution_ref) != r.execution_ref
                        ):
                            return refuse("INVALID_INPUT")
                        work = transition.work
                        if operation == "START_WORK" and assignment.state == "ASSIGNED":
                            assignment = dataclasses.replace(assignment, state="ACTIVE", version=assignment.version + 1)
                            conn.execute(
                                "UPDATE research_assignments SET state=?,version=? WHERE assignment_id=?",
                                (assignment.state, assignment.version, str(assignment.assignment_id)),
                            )
                            assignment_activated = True
                        reason_text = sanitize_pii_text(payload.reason) if hasattr(payload, "reason") else None
                        conn.execute(
                            "UPDATE research_work_items SET state=?,version=?,reason=? WHERE work_id=?",
                            (work.state, work.version, reason_text, str(work.work_id)),
                        )
                        if operation in {"START_WORK", "RECORD_ACTIVITY"}:
                            conn.execute(
                                "INSERT INTO research_activity_receipts VALUES (?,?,?,?,?,?,?,?,?)",
                                (
                                    str(uuid4()),
                                    str(command.mission_id),
                                    str(work.work_id),
                                    r.epoch,
                                    r.ownership_fence,
                                    sanitize_pii_text(r.execution_ref),
                                    r.occurred_at.isoformat(),
                                    r.fresh_until.isoformat(),
                                    r.provenance,
                                ),
                            )
                        record_kind = "WORK"
                        kind = {
                            "START_WORK": MissionProgressKind.WORK_STARTED,
                            "RECORD_ACTIVITY": MissionProgressKind.WORK_ACTIVITY_RECORDED,
                            "WAIT_WORK": MissionProgressKind.WORK_WAITING,
                            "RESUME_WORK": MissionProgressKind.WORK_RESUMED,
                            "REQUEST_CANCEL": MissionProgressKind.CANCELLATION_REQUESTED,
                            "ACK_STOP": MissionProgressKind.CANCELLATION_ACKNOWLEDGED,
                            "END_WORK": MissionProgressKind.WORK_ENDED,
                        }[operation]
                revision = self._record_progress(
                    conn,
                    command.mission_id,
                    kind,
                    "research:" + key,
                    work_id=work.work_id if work else None,
                    reason=reason_text,
                )
                record = work if record_kind == "WORK" else assignment
                record_id = record.work_id if record_kind == "WORK" else record.assignment_id
                conn.execute(
                    "INSERT INTO research_recorded_metadata VALUES (?,?,?,?,?,?,?)",
                    (
                        str(command.mission_id),
                        record_kind,
                        str(record_id),
                        record.version,
                        revision,
                        now.isoformat(),
                        "HARNESS_OBSERVED",
                    ),
                )
                if assignment_activated:
                    conn.execute(
                        "INSERT INTO research_recorded_metadata VALUES (?,?,?,?,?,?,?)",
                        (
                            str(command.mission_id),
                            "ASSIGNMENT",
                            str(assignment.assignment_id),
                            assignment.version,
                            revision,
                            now.isoformat(),
                            "HARNESS_OBSERVED",
                        ),
                    )
                event_ids = tuple(
                    UUID(r[0])
                    for r in conn.execute(
                        "SELECT id FROM mission_progress_events WHERE mission_id=? AND revision=? ORDER BY ordinal",
                        (str(command.mission_id), revision),
                    )
                )
                return persist(receipt(work=work, assignment=assignment, event_ids=event_ids))
            except sqlite3.DatabaseError:
                conn.rollback()
                revision = initial_revision
                return receipt("STORAGE_FAILURE")
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self._mem_conn is None:
                    conn.close()

        return await self._run_write(commit)
