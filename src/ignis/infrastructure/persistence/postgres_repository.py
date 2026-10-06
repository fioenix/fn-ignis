import asyncio
import dataclasses
import copy
import json
import logging
from collections.abc import Mapping
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID, uuid4

import psycopg
from psycopg import errors as pg_errors
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import AsyncConnectionPool

from ignis.application.cancellation import await_settled
from ignis.application.ports.mission_relay_port import (
    ProbeOutcomeCommitCommand,
    ProbeOutcomeCommitReceipt,
)
from ignis.domain.mission_relay import (
    MissionProgressEvent,
    MissionProgressKind,
    MissionRelayCursor,
    RelayProvenance,
    RelayEvidenceReference,
    EvidenceRole,
)
from ignis.application.ports.repository_port import (
    ITrendRepository,
    PlatformCredentialRecord,
    PlatformCredentialSummary,
)
from ignis.domain.entities import TopicCluster, TrendSignal, ResearchMission
from ignis.domain.exceptions import RepositoryException
from ignis.domain.research_workspace import (
    AuthorityBoundary,
    ClaimStatus,
    ClaimType,
    EvidenceDirection,
    QualificationRelation,
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
from ignis.infrastructure.persistence.migration_state import (
    UNBACKFILLED_CORPUS,
    is_unbackfilled,
)
from ignis.domain.cross_platform_score import cluster_rank_key, cross_platform_score
from ignis.domain.source_identity import (
    alias_namespace_prefix,
    resolve_identity_alias,
    resolve_source_identity,
)
from ignis.domain.value_objects import GeoCode, IngressTrigger, PlatformType, Timeframe, resolve_geo, resolve_platform, timeframe_to_days
from ignis.domain.youtube_quota import (
    YouTubeQuotaBucket,
    YouTubeQuotaReservation,
    YouTubeQuotaUsage,
)

from ignis.infrastructure.auth.crypto import encrypt_credentials, decrypt_credentials

logger = logging.getLogger(__name__)


class PostgresTimescaleRepository(ITrendRepository):
    """
    Persistence adapter for PostgreSQL / Supabase storage.
    Supports both topic-based Research Missions and time-series trend ingress.
    """


    def __init__(
        self,
        dsn: str,
        min_pool_size: int = 2,
        max_pool_size: int = 10,
        pool: Optional[AsyncConnectionPool] = None,
    ):
        self._dsn = dsn
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool = pool
        self._relay_fact_lock = asyncio.Lock()


    async def _get_pool(self) -> AsyncConnectionPool:
        if self._pool is not None:
            return self._pool
        # Built into a local, and only adopted once the gate has passed. Assigning first left a
        # live pool on the repository when the check raised, so the next call found it and
        # returned it without ever reaching the check -- the refusal held exactly once, and any
        # retry walked through it.
        pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
            open=False,
        )
        await pool.open()
        try:
            await self._refuse_an_unbackfilled_corpus(pool)
        except BaseException:
            await pool.close()
            raise
        self._pool = pool
        return self._pool

    async def _refuse_an_unbackfilled_corpus(self, pool) -> None:
        """Checked once, as the pool opens: the window is a deploy, not a query."""
        async with pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT"
                    " EXISTS (SELECT 1 FROM trend_signals),"
                    " EXISTS (SELECT 1 FROM observations)"
                )
            ).fetchone()
        if is_unbackfilled(*row):
            raise RepositoryException(UNBACKFILLED_CORPUS)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @staticmethod
    def _youtube_quota_usage_from_row(row) -> YouTubeQuotaUsage:
        return YouTubeQuotaUsage(
            quota_day=row[0],
            bucket=YouTubeQuotaBucket(row[1]),
            used=int(row[2]),
            scheduled_used=int(row[3]),
            exhausted=bool(row[4]),
            updated_at=row[5],
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
        if trigger != IngressTrigger.REQUESTED:
            raise ValueError("YouTube quota can only be reserved for requested work.")
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "INSERT INTO youtube_quota_buckets"
                    " (quota_day, bucket, used, scheduled_used, exhausted, created_at, updated_at)"
                    " SELECT %s, %s, %s, %s, FALSE, %s, %s"
                    " WHERE %s <= %s"
                    " ON CONFLICT (quota_day, bucket) DO UPDATE SET"
                    " used = youtube_quota_buckets.used + EXCLUDED.used,"
                    " scheduled_used = youtube_quota_buckets.scheduled_used + EXCLUDED.scheduled_used,"
                    " updated_at = EXCLUDED.updated_at"
                    " WHERE NOT youtube_quota_buckets.exhausted"
                    " AND youtube_quota_buckets.used + EXCLUDED.used <= %s"
                    " RETURNING quota_day, bucket, used, scheduled_used, exhausted, updated_at;",
                    (
                        quota_day,
                        bucket.value,
                        cost,
                        0,
                        now,
                        now,
                        cost,
                        daily_limit,
                        daily_limit,
                    ),
                )
                row = await cur.fetchone()
                admitted = row is not None
                if row is None:
                    await cur.execute(
                        "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                        " FROM youtube_quota_buckets WHERE quota_day = %s AND bucket = %s;",
                        (quota_day, bucket.value),
                    )
                    row = await cur.fetchone()
        usage = (
            self._youtube_quota_usage_from_row(row)
            if row is not None
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

    async def mark_youtube_quota_exhausted(
        self,
        quota_day: date,
        bucket: YouTubeQuotaBucket,
        now: datetime,
    ) -> YouTubeQuotaUsage:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "INSERT INTO youtube_quota_buckets"
                    " (quota_day, bucket, used, scheduled_used, exhausted, created_at, updated_at)"
                    " VALUES (%s, %s, 0, 0, TRUE, %s, %s)"
                    " ON CONFLICT (quota_day, bucket) DO UPDATE SET exhausted = TRUE,"
                    " updated_at = EXCLUDED.updated_at"
                    " RETURNING quota_day, bucket, used, scheduled_used, exhausted, updated_at;",
                    (quota_day, bucket.value, now, now),
                )
                row = await cur.fetchone()
        return self._youtube_quota_usage_from_row(row)

    async def get_youtube_quota_usage(self, quota_day: date) -> List[YouTubeQuotaUsage]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "SELECT quota_day, bucket, used, scheduled_used, exhausted, updated_at"
                    " FROM youtube_quota_buckets WHERE quota_day = %s ORDER BY bucket;",
                    (quota_day,),
                )
                rows = await cur.fetchall()
        return [self._youtube_quota_usage_from_row(row) for row in rows]

    async def _commit_relay_facts(self, mission_id: UUID, operation, *, analysis: bool = False):
        """Serialize local retries and hold the mission row through physical settlement."""
        async def commit():
            async with self._relay_fact_lock:
                pool = await self._get_pool()
                async with pool.connection() as conn:
                    async with conn.cursor(row_factory=tuple_row) as cur:
                        await self._lock_relay_tables(cur, analysis=analysis)
                        await cur.execute(
                            "INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (%s, 0)"
                            " ON CONFLICT (mission_id) DO NOTHING", (str(mission_id),),
                        )
                        await cur.execute(
                            "SELECT revision FROM mission_progress_revisions WHERE mission_id = %s FOR UPDATE",
                            (str(mission_id),),
                        )
                        revision = (await cur.fetchone())[0]
                        result, publish = await operation(conn, cur)
                        await cur.execute(
                            "SELECT revision FROM mission_progress_revisions WHERE mission_id = %s", (str(mission_id),),
                        )
                        if (await cur.fetchone())[0] == revision:
                            # A zero-delta retry must not leave a synthetic control row.
                            await conn.rollback()
                if publish is not None:
                    publish()
                return result

        return await await_settled(commit())

    @staticmethod
    async def _lock_relay_tables(cur, *, analysis: bool = False) -> None:
        # Legacy writers do not lock progress rows. Fence snapshot inputs until commit;
        # all progress writers take this gate before journal/revision locks to avoid
        # inversion. Analysis serializes across missions; collection remains concurrent.
        mode = "SHARE ROW EXCLUSIVE" if analysis else "ROW EXCLUSIVE"
        await cur.execute(
            "LOCK TABLE sources, observations, research_missions, mission_manifests,"
            " market_brief_revisions, mission_run_journals, mission_probe_outcomes,"
            " mission_evidence, mission_evidence_qualifications, mission_claims,"
            " mission_claim_evidence IN " + mode + " MODE"
        )

    @staticmethod
    async def _require_collection_run(cur, mission_id: UUID, run_id: UUID) -> None:
        await cur.execute(
            "SELECT j.mission_id, j.workspace_id, m.workspace_id"
            " FROM mission_run_journals j JOIN research_missions m ON m.id = j.mission_id"
            " WHERE j.id = %s FOR SHARE OF j, m", (str(run_id),),
        )
        row = await cur.fetchone()
        if row is None or str(row[0]) != str(mission_id) or row[1] != row[2]:
            raise RepositoryException("The recorded collection run does not belong to this mission scope.")

    async def _commit_snapshot(self, conn, mission_id: UUID):
        from ignis.infrastructure.persistence.evidence_snapshot import SnapshotConnectionPool, read_evidence_snapshot

        reader = copy.copy(self)
        reader._pool = SnapshotConnectionPool(conn)
        return await read_evidence_snapshot(reader, mission_id)

    @staticmethod
    async def _progress_reference(cur, mission_id: UUID, observation_id: UUID) -> RelayEvidenceReference:
        await cur.execute(
            "SELECT o.source_id, m.surface, q.relation, q.frame_fingerprint, q.evidence_role"
            " FROM mission_evidence e JOIN observations o ON o.id = e.observation_id"
            " JOIN research_missions m ON m.id = e.mission_id"
            " LEFT JOIN mission_evidence_qualifications q"
            " ON q.mission_id = e.mission_id AND q.observation_id = e.observation_id"
            " WHERE e.mission_id = %s AND e.observation_id = %s", (str(mission_id), str(observation_id)),
        )
        row = await cur.fetchone()
        if row is None:
            raise RepositoryException("A progress reference requires canonical mission membership.")
        role = {"ATTENTION": EvidenceRole.ATTENTION_CONTEXT, "MARKET": EvidenceRole.MARKET_EVIDENCE}.get(row[1])
        if role is None:
            raise RepositoryException("A relay commit requires a declared mission surface.")
        return RelayEvidenceReference(
            mission_id=mission_id, observation_id=observation_id, source_id=UUID(str(row[0])), evidence_role=role,
            direction=EvidenceDirection(row[4]) if row[4] else None,
            qualification_relation=QualificationRelation(row[2]) if row[2] else None,
            qualification_frame_fingerprint=row[3],
        )

    @staticmethod
    async def _record_progress(cur, mission_id: UUID, kind: MissionProgressKind, causation_key: str,
                               *, run_id=None, claim_id=None, references=(), reason=None, revision=None, ordinal=1,
                               work_id=None, handoff_id=None, finding_id=None):
        """Advance the held control row within the fact transaction, never a sequence."""
        if revision is None:
            await cur.execute(
                "UPDATE mission_progress_revisions SET revision = revision + 1 WHERE mission_id = %s RETURNING revision",
                (str(mission_id),),
            )
            revision = (await cur.fetchone())[0]
        event = MissionProgressEvent(
            event_id=uuid4(), cursor=MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=ordinal),
            kind=kind, provenance=RelayProvenance.HARNESS_OBSERVED, recorded_at=datetime.now(timezone.utc),
            causation_key=causation_key, run_id=run_id, claim_id=claim_id, evidence_references=references, reason=reason,
            work_id=work_id, handoff_id=handoff_id, finding_id=finding_id,
        )
        await cur.execute(
            "INSERT INTO mission_progress_events (id, mission_id, revision, ordinal, kind, provenance,"
            " recorded_at, causation_key, run_id, claim_id, evidence_references, reason, work_id, handoff_id, finding_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (str(event.event_id), str(mission_id), revision, ordinal, kind.value, event.provenance.value,
             event.recorded_at, causation_key, str(run_id) if run_id else None, str(claim_id) if claim_id else None,
             json.dumps([ref.to_payload() for ref in references]), reason,
             str(work_id) if work_id else None, str(handoff_id) if handoff_id else None,
             str(finding_id) if finding_id else None),
        )
        return revision

    async def commit_collection_state(self, mission: ResearchMission, run_id: UUID) -> None:
        """Commit the run-scoped collection state and its matching receipt together."""
        if mission.status not in ("RUNNING", "COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT"):
            raise RepositoryException("Unsupported collection state transition.")

        async def write(conn, cur):
            await self._require_collection_run(cur, mission.id, run_id)
            await cur.execute("SELECT status FROM research_missions WHERE id = %s", (str(mission.id),))
            status = (await cur.fetchone())[0]
            kind = (MissionProgressKind.COLLECTION_STARTED if mission.status == "RUNNING"
                    else MissionProgressKind.COLLECTION_STATE_CHANGED)
            await cur.execute(
                "SELECT id FROM mission_progress_events WHERE mission_id = %s AND run_id = %s AND kind = %s AND reason = %s",
                (str(mission.id), str(run_id), kind.value, mission.status),
            )
            if await cur.fetchone() is not None and status == mission.status:
                return None, None
            if status in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "INSUFFICIENT"):
                raise RepositoryException("Terminal collection cannot be reopened or rewritten.")
            await cur.execute(
                "UPDATE research_missions SET status = %s, summary = %s, updated_at = %s WHERE id = %s",
                (mission.status, mission.summary, datetime.now(timezone.utc), str(mission.id)),
            )
            await self._record_progress(cur, mission.id, kind, f"collection:{run_id}:{mission.status}",
                                        run_id=run_id, reason=mission.status)
            return None, None

        await self._commit_relay_facts(mission.id, write)

    async def commit_collection_observations(self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]) -> int:
        """Publish sightings, membership and canonical identities only after durable commit."""
        signals = tuple(signals)
        if any(signal.mission_id not in (None, mission_id) for signal in signals):
            raise RepositoryException("Collection signals cannot name another mission.")

        async def write(conn, cur):
            await self._require_collection_run(cur, mission_id, run_id)
            batch = [dataclasses.replace(signal, mission_id=mission_id) for signal in signals]
            fresh = []
            for signal in batch:
                if signal.observation_id is not None:
                    await self._progress_reference(cur, mission_id, signal.observation_id)
                    continue
                if await self._record_observations(cur, [signal]):
                    await cur.execute("SELECT source_id FROM observations WHERE id = %s", (str(signal.observation_id),))
                    signal.source_id = UUID(str((await cur.fetchone())[0]))
                    fresh.append(signal)
            if fresh:
                refs = tuple([await self._progress_reference(cur, mission_id, signal.observation_id) for signal in fresh])
                await self._record_progress(cur, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                                            f"observations:{run_id}:{uuid4()}", run_id=run_id, references=refs)

            def publish():
                for original, staged in zip(signals, batch):
                    if original.observation_id is None and staged.observation_id is not None:
                        for name in ("observation_id", "source_id", "identity_source", "time_provenance"):
                            setattr(original, name, getattr(staged, name))

            return len(fresh), publish

        return await self._commit_relay_facts(mission_id, write)

    async def commit_collection_membership(self, mission_id: UUID, run_id: UUID, signals: Sequence[TrendSignal]) -> int:
        """Reattach stored observations without creating another sighting."""
        identities = tuple(dict.fromkeys(signal.observation_id for signal in signals))
        if None in identities:
            raise RepositoryException("Membership commits require stored observation identities.")

        async def write(conn, cur):
            await self._require_collection_run(cur, mission_id, run_id)
            refs = []
            for identity in identities:
                await cur.execute(
                    "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)"
                    " ON CONFLICT (mission_id, observation_id) DO NOTHING", (str(mission_id), str(identity)),
                )
                if cur.rowcount:
                    refs.append(await self._progress_reference(cur, mission_id, identity))
            if refs:
                await self._record_progress(cur, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                    f"membership:{run_id}:{uuid4()}", run_id=run_id, references=tuple(refs), reason="MEMBERSHIP_REATTACHED")
            return len(refs), None

        return await self._commit_relay_facts(mission_id, write)

    async def commit_collection_pruning(self, mission_id: UUID, run_id: UUID, retained_observation_ids: Sequence[UUID]) -> int:
        """Prune memberships and record actual cascading ledger changes in one revision."""
        retained = set(retained_observation_ids)

        async def write(conn, cur):
            await self._require_collection_run(cur, mission_id, run_id)
            await cur.execute("SELECT observation_id FROM mission_evidence WHERE mission_id = %s ORDER BY observation_id",
                              (str(mission_id),))
            removed = [UUID(str(row[0])) for row in await cur.fetchall() if UUID(str(row[0])) not in retained]
            refs = tuple([await self._progress_reference(cur, mission_id, value) for value in removed])
            claims = await self._read_claims(mission_id, include_superseded=True, conn=conn)
            affected = [(claim, tuple(ref for ref in refs if any(b.observation_id == ref.observation_id
                         for b in claim.evidence_bindings))) for claim in claims]
            for identity in removed:
                await cur.execute("DELETE FROM mission_evidence WHERE mission_id = %s AND observation_id = %s",
                                  (str(mission_id), str(identity)))
            if removed:
                revision = await self._record_progress(cur, mission_id, MissionProgressKind.OBSERVATIONS_COMMITTED,
                    f"membership:{run_id}:{uuid4()}", run_id=run_id, references=refs, reason="MEMBERSHIP_PRUNED")
                ordinal = 1
                for claim, invalidated in affected:
                    if not invalidated:
                        continue
                    await cur.execute("SELECT status FROM mission_claims WHERE id = %s", (str(claim.claim_id),))
                    status = (await cur.fetchone())[0]
                    if status != claim.status.value:
                        ordinal += 1
                        await self._record_progress(cur, mission_id, MissionProgressKind.CLAIM_GATE_CHANGED,
                            f"claim-pruned:{claim.claim_id}:{uuid4()}", claim_id=claim.claim_id, references=invalidated,
                            reason=status, revision=revision, ordinal=ordinal)
            return len(removed), None

        return await self._commit_relay_facts(mission_id, write)

    async def commit_evidence_qualifications(self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]) -> int:
        """Recheck the frame and publish new judgments plus receipt on the held connection."""
        from ignis.infrastructure.persistence.evidence_snapshot import SnapshotConnectionPool
        batch = tuple(qualifications)
        if not batch:
            return 0
        if any(q.mission_id != mission_id for q in batch):
            raise InvalidEvidenceQualificationError("Every judgment must name the selected mission.")

        async def write(conn, cur):
            snapshot = await self._commit_snapshot(conn, mission_id)
            if snapshot.mission is None or any(
                q.frame_fingerprint != compute_frame_fingerprint(snapshot.mission, snapshot.brief)
                or q.brief_revision_id != (snapshot.brief.brief_revision_id if snapshot.brief else None) for q in batch
            ):
                raise StaleEvidenceQualificationError("The submitted qualification frame is stale.")
            reader = copy.copy(self)
            reader._pool = SnapshotConnectionPool(conn)
            recorded = {q.observation_id for q in snapshot.qualifications}
            result = await reader.save_evidence_qualifications(mission_id, batch)
            fresh = dict.fromkeys(q.observation_id for q in batch if q.observation_id not in recorded)
            refs = tuple([await self._progress_reference(cur, mission_id, identity) for identity in fresh])
            if refs:
                await self._record_progress(cur, mission_id, MissionProgressKind.QUALIFICATION_RECORDED,
                                            f"qualification:{mission_id}:{uuid4()}", references=refs)
            return result, None

        return await self._commit_relay_facts(mission_id, write, analysis=True)

    async def commit_mission_claims(self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]) -> List[MissionClaim]:
        """Keep legacy ledger validation inside the current-frame fact/event transaction."""
        from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot
        from ignis.infrastructure.persistence.evidence_snapshot import SnapshotConnectionPool
        batch = tuple(claims)
        if not batch:
            return []
        if any(c.mission_id != mission_id or c.frame_digest != frame_digest for c in batch):
            raise InvalidMissionClaimError("Every claim must name the requested mission and evidence frame.")

        async def write(conn, cur):
            snapshot = await self._commit_snapshot(conn, mission_id)
            if frame_from_snapshot(snapshot).frame_digest != frame_digest:
                raise StaleMissionClaimError("The submitted claim frame is stale.")
            recorded = {(c.frame_digest, c.client_claim_key) for c in snapshot.claims}
            reader = copy.copy(self)
            reader._pool = SnapshotConnectionPool(conn)
            result = await reader.save_mission_claims(mission_id, frame_digest, batch)
            revision = None
            ordinal = 0
            for claim in result:
                identity = (claim.frame_digest, claim.client_claim_key)
                if identity in recorded:
                    continue
                recorded.add(identity)
                ordinal += 1
                refs = tuple([await self._progress_reference(cur, mission_id, b.observation_id)
                              for b in claim.evidence_bindings if b.observation_id])
                revision = await self._record_progress(cur, mission_id, MissionProgressKind.CLAIM_GATE_CHANGED,
                    f"claim:{claim.claim_id}", claim_id=claim.claim_id, references=refs,
                    reason=claim.status.value, revision=revision, ordinal=ordinal)
            return result, None

        return await self._commit_relay_facts(mission_id, write, analysis=True)

    async def save_signals(self, signals: List[TrendSignal]) -> int:
        """Record each sighting in the source/observation model. Nothing else is written.

        trend_signals and signal_metrics are read-only from here on. They stay in the schema --
        the audit reads them, the backfill reads them, and they are the only record of what the
        corpus looked like before the migration -- but a write to them now would restart the
        divergence the migration closed.
        """
        if not signals:
            return 0

        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    recorded = await self._record_observations(cur, signals)
            logger.info(f"Recorded {recorded} observations from {len(signals)} signals.")
            return recorded
        except Exception as e:
            logger.error(f"Error saving signals to database: {e}", exc_info=True)
            raise RepositoryException(f"Failed to record observations: {e}") from e

    async def _record_observations(self, cur, signals: List[TrendSignal]) -> int:
        """Write each signal as one observation of one canonical source.

        Three properties this has to hold, each of them measured on the corpus rather than
        assumed:

        - A source is upserted on (platform, external_id) in a single statement. A SELECT
          followed by an INSERT is not the same thing: two ingress passes racing on one video
          would both see nothing and both insert, which is how the legacy table came to hold
          1,927 rows for 1,924 objects.
        - Every signal becomes an observation. Nothing is deduplicated on the payload, because
          two collection events are allowed to be identical on every field and only the
          surrogate id separates them.
        - A mission's claim goes to mission_evidence, never onto the source or the observation.
          One source is observed by many missions, and the legacy mission_id column could only
          record the last one, which is why the second mission lost its evidence.
        """
        written = 0
        for signal in signals:
            platform = (
                signal.platform.value if hasattr(signal.platform, "value") else str(signal.platform)
            )
            identity = resolve_source_identity(platform, signal.source_url, signal.metadata)
            if identity is None:
                # Nothing identifies this sighting. Counted by the audit rather than given an
                # invented key, and skipped here for the same reason.
                logger.warning("Signal has no resolvable external identity, skipped: %s", platform)
                continue

            identity = await self._reconcile_through_aliases(cur, platform, signal, identity)

            await cur.execute(
                "INSERT INTO sources (platform, external_id) VALUES (%s, %s)"
                " ON CONFLICT (platform, external_id) DO UPDATE SET platform = EXCLUDED.platform"
                " RETURNING id;",
                (identity.platform, identity.external_id),
            )
            source_id = (await cur.fetchone())[0]

            # A live write knows when it collected: the clock is this process's own. Only rows
            # written before sql/015 by a connector that stamped a publish time are legacy, and
            # those arrive through the backfill, not here.
            observed_at = signal.captured_at or datetime.now(timezone.utc)
            await cur.execute(
                "INSERT INTO observations (source_id, cluster_id, observed_at, published_at,"
                " time_provenance, identity_source, observed_title, metric_value,"
                " growth_velocity, geo_code, source_url, metadata)"
                " VALUES (%s, %s, %s, %s, 'exact_ingestion', %s, %s, %s, %s, %s, %s, %s)"
                " RETURNING id;",
                (
                    source_id,
                    str(signal.cluster_id) if signal.cluster_id else None,
                    observed_at,
                    signal.published_at,
                    identity.identity_source,
                    signal.raw_title,
                    signal.metric_value,
                    signal.growth_velocity,
                    signal.geo_code.value
                    if hasattr(signal.geo_code, "value")
                    else str(signal.geo_code),
                    signal.source_url,
                    json.dumps(signal.metadata or {}),
                ),
            )
            observation_id = (await cur.fetchone())[0]
            # The caller needs this to attach a cluster later without writing a second sighting.
            signal.observation_id = UUID(str(observation_id))
            signal.identity_source = identity.identity_source
            signal.time_provenance = "exact_ingestion"
            written += 1

            if signal.mission_id:
                await cur.execute(
                    "INSERT INTO mission_evidence (mission_id, observation_id) VALUES (%s, %s)"
                    " ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                    (str(signal.mission_id), str(observation_id)),
                )
        return written

    async def _reconcile_through_aliases(self, cur, platform, signal, identity):
        """The canonical identity for this sighting once the alias ledger has had its say.

        The same two cases as the SQLite path, restated here because the two backends speak
        different SQL. What is shared is the part that must never diverge: both decide an alias
        through ignis.domain.source_identity, and both treat a recorded alias as final.
        """
        alias = resolve_identity_alias(platform, signal.source_url, signal.metadata)
        if alias is not None:
            await self._register_identity_alias(cur, alias)
            return identity

        prefix = alias_namespace_prefix(platform)
        if prefix is None or not identity.external_id.startswith(prefix):
            return identity

        await cur.execute(
            "SELECT canonical_external_id FROM source_identity_aliases"
            " WHERE platform = %s AND alias_external_id = %s;",
            (platform, identity.external_id),
        )
        row = await cur.fetchone()
        if row is None:
            return identity
        return dataclasses.replace(identity, external_id=row[0])

    async def _register_identity_alias(self, cur, alias) -> None:
        """Record the alias unless one is already recorded for this shortcode.

        DO NOTHING, then read back what is stored. A second record claiming one shortcode for a
        different primary key cannot be reconciled, so the stored claim stands, the divergence is
        logged, and the conflicting record is written under its own primary key -- two rows the
        audit can measure rather than one merge nobody can undo.
        """
        await cur.execute(
            "INSERT INTO source_identity_aliases"
            " (platform, alias_external_id, canonical_external_id, witnessed_by)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (platform, alias_external_id) DO NOTHING;",
            (
                alias.platform,
                alias.alias_external_id,
                alias.canonical_external_id,
                alias.witnessed_by,
            ),
        )
        await cur.execute(
            "SELECT canonical_external_id FROM source_identity_aliases"
            " WHERE platform = %s AND alias_external_id = %s;",
            (alias.platform, alias.alias_external_id),
        )
        stored = (await cur.fetchone())[0]
        if stored != alias.canonical_external_id:
            logger.warning(
                "Conflicting alias claim on %s %s: ledger holds %s, this record claims %s."
                " Keeping the recorded alias and storing this record under its own identifier.",
                alias.platform,
                alias.alias_external_id,
                stored,
                alias.canonical_external_id,
            )

    async def prune_empty_clusters(self) -> int:
        """Remove clusters holding no observation at all.

        Membership, not recency: a cluster whose only observations are legacy ones outside the
        default analysis window still describes something the corpus contains. Pruning on the
        window would delete 17,118 observations' worth of topics on the first pass after the
        backfill.

        Referenced by the legacy corpus counts as referenced. sql/016 creates the new tables
        empty, so between the migration and the backfill every legacy membership looks like an
        empty cluster here -- and deleting those topics cascades trend_signals.cluster_id to
        NULL, destroying the very rows the backfill was going to read. After the backfill the
        guard changes nothing, because a legacy row that was carried over has an observation.
        """
        pool = await self._get_pool()
        query = """
            DELETE FROM topic_clusters tc
            WHERE NOT EXISTS (SELECT 1 FROM observations o WHERE o.cluster_id = tc.id)
              AND NOT EXISTS (SELECT 1 FROM trend_signals ts WHERE ts.cluster_id = tc.id);
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query)
                    return cur.rowcount or 0
        except Exception as e:
            logger.warning(f"Could not prune empty clusters: {e}")
            return 0

    @staticmethod
    def _deduplicate_clusters(clusters: List[TopicCluster]) -> Dict[str, TopicCluster]:
        """Merge clusters that normalise to the same canonical name, keyed by that name.

        A merged-away cluster is never persisted, so its signals must be re-pointed at the
        surviving cluster. Leaving them on the dropped id sent them to whatever row already
        carried it, and the surviving cluster was then stored with no signals at all — which is
        where the empty topic_clusters rows came from, roughly a dozen per ingress pass.
        """
        from ignis.domain.normalization import normalize_cluster_name

        deduped: Dict[str, TopicCluster] = {}
        for c in clusters:
            norm_name = normalize_cluster_name(c.canonical_name)
            target = deduped.get(norm_name)
            if target is None:
                c.canonical_name = norm_name
                deduped[norm_name] = c
                continue

            for signal in c.signals:
                signal.cluster_id = target.id
            target.signals.extend(c.signals)
            target.cross_platform_score = max(target.cross_platform_score, c.cross_platform_score)
        return deduped

    async def save_clusters(self, clusters: List[TopicCluster]) -> None:
        if not clusters:
            return

        pool = await self._get_pool()
        find_query = """
            SELECT id, canonical_name
            FROM topic_clusters
            WHERE id = %s OR LOWER(canonical_name) = LOWER(%s)
            LIMIT 1;
        """
        update_query = """
            UPDATE topic_clusters SET
                canonical_name = %s,
                topic_label = %s,
                summary_text = %s,
                category = %s,
                cross_platform_score = %s,
                last_updated_at = %s
            WHERE id = %s;
        """
        insert_query = """
            INSERT INTO topic_clusters (
                id,
                canonical_name,
                topic_label,
                summary_text,
                category,
                cross_platform_score,
                first_seen_at,
                last_updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """

        deduped = self._deduplicate_clusters(clusters)

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for c in deduped.values():
                        try:
                            async with conn.transaction():
                                # Passed through, including None. Substituting now() would
                                # give a cluster of legacy observations a first sighting dated
                                # to this run.
                                c_first_seen = c.first_seen_at
                                c_last_updated = c.last_updated_at or datetime.now(timezone.utc)
                                clean_name = c.canonical_name
                                c_id_str = str(c.id)

                                await cur.execute(find_query, (c_id_str, clean_name))
                                row = await cur.fetchone()

                                if row:
                                    actual_id = row[0]
                                    await cur.execute(
                                        update_query,
                                        (
                                            clean_name,
                                            c.topic_label,
                                            c.summary_text,
                                            c.category,
                                            c.cross_platform_score,
                                            c_last_updated,
                                            actual_id,
                                        ),
                                    )
                                else:
                                    actual_id = c.id
                                    await cur.execute(
                                        insert_query,
                                        (
                                            c_id_str,
                                            clean_name,
                                            c.topic_label,
                                            c.summary_text,
                                            c.category,
                                            c.cross_platform_score,
                                            c_first_seen,
                                            c_last_updated,
                                        ),
                                    )

                                c.id = actual_id
                                for s in c.signals:
                                    s.cluster_id = actual_id
                        except Exception as row_err:
                            logger.warning(
                                f"Failed to upsert individual cluster '{c.canonical_name}', rolling back savepoint: {row_err}"
                            )

            logger.info(f"Successfully upserted {len(deduped)} topic clusters.")
        except Exception as e:
            logger.error(f"Error upserting topic clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to upsert topic clusters: {e}") from e

    # The default analysis window admits only observations whose collection time is known.
    # published_at is not a substitute: for the 17,118 legacy observations it answers "when was
    # this posted", and a window built on it would report a two-year-old video as something seen
    # this week.
    _WINDOW_PREDICATE = (
        "o.time_provenance = 'exact_ingestion'"
        " AND o.observed_at IS NOT NULL"
        " AND o.observed_at >= NOW() - INTERVAL '{interval}'"
    )

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

    # One observation per source: the most recent in the window. A source polled hourly must not
    # outweigh one polled daily, because polling frequency is a property of the harness.
    _LATEST_PER_SOURCE = """
        -- Partitioned on (cluster_id, source_id), not on source_id alone. A source observed in
        -- one cluster and later in another would otherwise keep only its latest sighting
        -- anywhere, and the earlier membership would vanish from the reader entirely -- 175
        -- identities in the corpus sit under more than one cluster, which is why cluster_id is
        -- on the observation rather than on the source.
        SELECT DISTINCT ON (o.cluster_id, o.source_id)
            o.id AS observation_id, o.source_id, o.cluster_id, o.metric_value, o.growth_velocity,
            o.observed_at, o.published_at, o.time_provenance, o.identity_source, o.observed_title,
            o.geo_code, o.source_url, o.metadata, s.platform
        FROM observations o
        JOIN sources s ON s.id = o.source_id
        WHERE o.cluster_id IS NOT NULL AND {window} {cluster_filter}
        ORDER BY o.cluster_id, o.source_id, {latest_first}
    """

    async def get_top_clusters(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        limit: int = 10,
    ) -> List[TopicCluster]:
        """Rank clusters by what was observed in the window, from the new model only.

        Two statements for the same reason as the SQLite reader, restated here because the two
        backends speak different SQL: ranking needs one aggregate row per cluster in the window,
        the caller asked for `limit` of them, and JSON_AGG building the payload of every cluster
        only to discard all but ten is work nobody reads. What must never diverge is shared --
        the score is `cross_platform_score` and the order is `cluster_rank_key`, neither of them
        restated in SQL.
        """
        pool = await self._get_pool()
        # Built from the canonical day count rather than a local map. Four such maps existed,
        # each covering three of the five Timeframe members, each with a different silent
        # default -- which is how a ninety-day request came to be served a twenty-four hour
        # window with a successful status.
        interval = f"{timeframe_to_days(timeframe)} days"
        window = self._WINDOW_PREDICATE.format(interval=interval)

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    ranked = await self._rank_clusters(cur, window, limit)
                    if not ranked:
                        return []
                    return await self._read_cluster_payloads(cur, window, ranked)
        except Exception as e:
            logger.error(f"Error fetching top clusters: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch top clusters: {e}") from e

    async def _rank_clusters(self, cur, window: str, limit: int):
        """The cluster ids the caller asked for, strongest first, with their aggregates.

        The join to topic_clusters decides which clusters exist, so it belongs in the ranking as
        well as in the payload read: ranking without it could spend a slot on a cluster the
        payload read then drops, leaving the caller with fewer results than it asked for.
        """
        latest = self._LATEST_PER_SOURCE.format(
            window=window, latest_first=self._LATEST_FIRST, cluster_filter=""
        )
        await cur.execute(
            f"""
            WITH latest AS ({latest})
            SELECT
                l.cluster_id,
                COUNT(*) AS source_count,
                COUNT(DISTINCT l.platform) AS platform_count,
                COALESCE(SUM(l.metric_value), 0.0) AS total_metric,
                COALESCE(AVG(l.growth_velocity), 0.0) AS avg_velocity
            FROM latest l
            JOIN topic_clusters tc ON tc.id = l.cluster_id
            GROUP BY l.cluster_id
            """
        )
        scored = [
            (
                str(cluster_id),
                cross_platform_score(
                    distinct_platforms=int(platform_count or 0),
                    total_metric=float(total_metric or 0.0),
                    average_velocity=float(avg_velocity or 0.0),
                ),
                int(source_count or 0),
            )
            for cluster_id, source_count, platform_count, total_metric, avg_velocity
            in await cur.fetchall()
        ]
        scored.sort(key=lambda item: cluster_rank_key(item[1], item[2], item[0]), reverse=True)
        return scored[:limit]

    async def _read_cluster_payloads(self, cur, window: str, ranked):
        """Every signal of the ranked clusters, in the order ranking already decided."""
        cluster_ids = [cluster_id for cluster_id, _score, _count in ranked]
        # Pushed into the CTE, not applied to its output: with the ordering index leading on
        # cluster_id this becomes one range per chosen cluster instead of a scan of the window.
        latest = self._LATEST_PER_SOURCE.format(
            window=window,
            latest_first=self._LATEST_FIRST,
            cluster_filter="AND o.cluster_id = ANY(%s::uuid[])",
        )
        await cur.execute(
            f"""
            WITH latest AS ({latest})
            SELECT
                tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                tc.first_seen_at, tc.last_updated_at,
                COUNT(*) AS source_count,
                COUNT(DISTINCT l.platform) AS platform_count,
                JSON_AGG(JSON_BUILD_OBJECT(
                    'platform', l.platform,
                    'raw_title', l.observed_title,
                    'metric_value', l.metric_value,
                    'growth_velocity', l.growth_velocity,
                    'source_url', l.source_url,
                    'geo_code', l.geo_code,
                    'metadata', l.metadata,
                    'observed_at', l.observed_at,
                    'published_at', l.published_at,
                    'observation_id', l.observation_id,
                    'identity_source', l.identity_source,
                    'time_provenance', l.time_provenance
                )) AS signals
            FROM latest l
            JOIN topic_clusters tc ON tc.id = l.cluster_id
            GROUP BY tc.id, tc.canonical_name, tc.topic_label, tc.summary_text, tc.category,
                     tc.first_seen_at, tc.last_updated_at
            """,
            (cluster_ids,),
        )
        payloads = {}
        for row in await cur.fetchall():
            (
                c_id, name, label, summary, category, first_seen, last_updated,
                source_count, platform_count, sigs_raw,
            ) = row
            payloads[str(c_id)] = (
                name, label, summary, category, first_seen, last_updated,
                source_count, platform_count, sigs_raw,
            )

        clusters = []
        for cluster_id, score, _source_count in ranked:
            payload = payloads.get(cluster_id)
            if payload is None:
                continue
            (
                name, label, summary, category, first_seen, last_updated,
                source_count, platform_count, sigs_raw,
            ) = payload
            sigs_data = sigs_raw if isinstance(sigs_raw, list) else json.loads(sigs_raw or "[]")
            signals_list = [
                self._signal_from_observation(s_dict, UUID(cluster_id)) for s_dict in sigs_data
            ]
            cluster = TopicCluster(
                id=UUID(cluster_id),
                canonical_name=name,
                summary_text=summary
                or f"{source_count} sources across {platform_count} platforms.",
                category=category or "general",
                cross_platform_score=score,
                signals=signals_list,
                first_seen_at=first_seen,
                last_updated_at=last_updated,
            )
            cluster.topic_label = label
            clusters.append(cluster)
        return clusters

    @staticmethod
    def _signal_from_observation(data: Dict[str, Any], cluster_id: UUID) -> TrendSignal:
        observed_at = data.get("observed_at")
        if isinstance(observed_at, str):
            observed_at = datetime.fromisoformat(observed_at)
        published_at = data.get("published_at")
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at)
        metadata = data.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (TypeError, ValueError):
                metadata = {}
        observation_id = data.get("observation_id")
        return TrendSignal(
            platform=PlatformType(data["platform"]),
            raw_title=data.get("raw_title") or "",
            metric_value=float(data.get("metric_value") or 0.0),
            growth_velocity=float(data.get("growth_velocity") or 0.0),
            source_url=data.get("source_url"),
            geo_code=GeoCode(data.get("geo_code") or "VN"),
            cluster_id=cluster_id,
            metadata=metadata,
            captured_at=observed_at,
            published_at=published_at,
            observation_id=UUID(str(observation_id)) if observation_id else None,
            identity_source=data.get("identity_source"),
            time_provenance=data.get("time_provenance"),
        )

    async def get_cluster_signals(
        self,
        cluster_id: UUID,
        timeframe: Timeframe = Timeframe.LAST_7D,
    ) -> List[TrendSignal]:
        """One signal per source, the most recent observation of it in the window.

        Deduplication is on source_id now, not on the URL. A URL is what one sighting reported,
        and the corpus holds one source seen under two URL variants -- keying on it counted that
        source twice, and a feed-level URL shared by many items counted them as one.
        """
        pool = await self._get_pool()
        # Built from the canonical day count rather than a local map. Four such maps existed,
        # each covering three of the five Timeframe members, each with a different silent
        # default -- which is how a ninety-day request came to be served a twenty-four hour
        # window with a successful status.
        interval = f"{timeframe_to_days(timeframe)} days"
        window = self._WINDOW_PREDICATE.format(interval=interval)

        query = f"""
            SELECT DISTINCT ON (o.cluster_id, o.source_id)
                s.platform, o.observed_title, o.metric_value, o.growth_velocity, o.source_url,
                o.geo_code, o.metadata, o.observed_at, o.published_at, o.id, o.identity_source,
                o.time_provenance
            FROM observations o
            JOIN sources s ON s.id = o.source_id
            WHERE o.cluster_id = %s AND {window}
            ORDER BY o.cluster_id, o.source_id, {self._LATEST_FIRST};
        """

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(cluster_id),))
                    rows = await cur.fetchall()

            signals = [
                self._signal_from_observation(
                    {
                        "platform": row[0],
                        "raw_title": row[1],
                        "metric_value": row[2],
                        "growth_velocity": row[3],
                        "source_url": row[4],
                        "geo_code": row[5],
                        "metadata": row[6],
                        "observed_at": row[7],
                        "published_at": row[8],
                        "observation_id": row[9],
                        "identity_source": row[10],
                        "time_provenance": row[11],
                    },
                    cluster_id,
                )
                for row in rows
            ]
            signals.sort(key=lambda s: (s.captured_at is None, s.captured_at))
            return signals
        except Exception as e:
            logger.error(f"Error fetching signals for cluster {cluster_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch cluster signals: {e}") from e

    @staticmethod
    async def _write_mission_row(cur, mission: ResearchMission) -> None:
        """One mission insert, so every caller writes the same row the same way."""
        query = """
            INSERT INTO research_missions (
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                workspace_id,
                surface,
                parent_attention_mission_id,
                parent_cluster_id,
                brief_revision_id,
                revises_mission_id,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        platforms_str = [p.value if hasattr(p, "value") else str(p) for p in mission.platforms]
        await cur.execute(
            query,
            (
                str(mission.id),
                mission.title,
                mission.keywords,
                mission.shortcode,
                mission.agent,
                mission.session_id,
                platforms_str,
                mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
                mission.timeframe,
                mission.status,
                mission.summary,
                _uuid_text(mission.workspace_id),
                mission.surface,
                _uuid_text(mission.parent_attention_mission_id),
                _uuid_text(mission.parent_cluster_id),
                _uuid_text(mission.brief_revision_id),
                _uuid_text(mission.revises_mission_id),
                mission.created_at,
                mission.updated_at,
            ),
        )

    async def create_mission(self, mission: ResearchMission) -> ResearchMission:
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await self._write_mission_row(cur, mission)
            return mission
        except Exception as e:
            logger.error(f"Error creating research mission: {e}", exc_info=True)
            raise RepositoryException(f"Failed to create research mission: {e}") from e

    async def save_mission(self, mission: ResearchMission) -> ResearchMission:
        """Upsert a research mission (creates if not existing, otherwise updates)."""
        existing = await self.get_mission(mission.id)
        if existing:
            await self.update_mission(mission)
            return mission
        return await self.create_mission(mission)

    async def get_mission(self, identifier: Any) -> Optional[ResearchMission]:
        pool = await self._get_pool()
        raw_id = str(identifier).strip()
        
        query = """
            SELECT 
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                workspace_id,
                surface,
                parent_attention_mission_id,
                parent_cluster_id,
                brief_revision_id,
                revises_mission_id,
                created_at,
                updated_at
            FROM research_missions
            WHERE id::text = %s 
               OR UPPER(shortcode) = UPPER(%s)
               OR session_id = %s
               OR id::text ILIKE %s
            ORDER BY created_at DESC
            LIMIT 1;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (raw_id, raw_id, raw_id, f"{raw_id}%"))
                    row = await cur.fetchone()
            if not row:
                return None

            (m_id, title, kws, sc, agent_val, sess_id, plats, geo, tf, status, summary,
             ws_id, surface, parent_mission, parent_cluster, brief_id, revises_id,
             created, updated) = row
            return ResearchMission(
                id=UUID(str(m_id)),
                title=title,
                keywords=list(kws or []),
                shortcode=sc or str(m_id)[:8].upper(),
                agent=agent_val or "claude",
                session_id=sess_id,
                platforms=[resolve_platform(p) for p in (plats or [])],
                geo_code=resolve_geo(geo),
                timeframe=tf,

                status=status,
                summary=summary,
                workspace_id=_uuid_or_none(ws_id),
                surface=surface,
                parent_attention_mission_id=_uuid_or_none(parent_mission),
                parent_cluster_id=_uuid_or_none(parent_cluster),
                brief_revision_id=_uuid_or_none(brief_id),
                revises_mission_id=_uuid_or_none(revises_id),
                created_at=created,
                updated_at=updated,
            )
        except Exception as e:
            logger.error(f"Error getting research mission {identifier}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to get research mission: {e}") from e


    async def update_mission(self, mission: ResearchMission) -> None:
        pool = await self._get_pool()
        query = """
            UPDATE research_missions SET
                title = %s,
                keywords = %s,
                platforms = %s,
                geo_code = %s,
                timeframe = %s,
                status = %s,
                summary = %s,
                workspace_id = %s,
                parent_attention_mission_id = %s,
                parent_cluster_id = %s,
                brief_revision_id = %s,
                revises_mission_id = %s,
                updated_at = NOW()
            WHERE id = %s;
        """
        # `surface` is deliberately absent. A mission answers one question for its whole life,
        # and letting an update move it from ATTENTION to MARKET would re-label evidence that
        # was collected to answer the other one.
        platforms_str = [p.value if hasattr(p, "value") else str(p) for p in mission.platforms]
        params = (
            mission.title,
            mission.keywords,
            platforms_str,
            mission.geo_code.value if hasattr(mission.geo_code, "value") else str(mission.geo_code),
            mission.timeframe,
            mission.status,
            mission.summary,
            _uuid_text(mission.workspace_id),
            _uuid_text(mission.parent_attention_mission_id),
            _uuid_text(mission.parent_cluster_id),
            _uuid_text(mission.brief_revision_id),
            _uuid_text(mission.revises_mission_id),
            str(mission.id),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
        except Exception as e:
            logger.error(f"Error updating mission: {e}", exc_info=True)
            raise RepositoryException(f"Failed to update mission: {e}") from e

    async def list_missions(self, limit: int = 20) -> List[ResearchMission]:
        pool = await self._get_pool()
        query = """
            SELECT 
                id,
                title,
                keywords,
                shortcode,
                agent,
                session_id,
                platforms,
                geo_code,
                timeframe,
                status,
                summary,
                workspace_id,
                surface,
                parent_attention_mission_id,
                parent_cluster_id,
                brief_revision_id,
                revises_mission_id,
                created_at,
                updated_at
            FROM research_missions
            ORDER BY created_at DESC
            LIMIT %s;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (limit,))
                    rows = await cur.fetchall()

            missions = []
            for row in rows:
                (m_id, title, kws, sc, agent_val, sess_id, plats, geo, tf, status, summary,
                 ws_id, surface, parent_mission, parent_cluster, brief_id, revises_id,
             created, updated) = row
                mission = ResearchMission(
                    id=UUID(str(m_id)),
                    title=title,
                    keywords=list(kws or []),
                    shortcode=sc or str(m_id)[:8].upper(),
                    agent=agent_val or "claude",
                    session_id=sess_id,
                    platforms=[resolve_platform(p) for p in (plats or [])],
                    geo_code=resolve_geo(geo),
                    timeframe=tf,

                    status=status,
                    summary=summary,
                    workspace_id=_uuid_or_none(ws_id),
                    surface=surface,
                    parent_attention_mission_id=_uuid_or_none(parent_mission),
                    parent_cluster_id=_uuid_or_none(parent_cluster),
                    brief_revision_id=_uuid_or_none(brief_id),
                    revises_mission_id=_uuid_or_none(revises_id),
                    created_at=created,
                    updated_at=updated,
                )
                missions.append(mission)
            return missions
        except Exception as e:
            logger.error(f"Error listing research missions: {e}", exc_info=True)
            raise RepositoryException(f"Failed to list research missions: {e}") from e

    async def get_mission_signals(self, mission_id: UUID) -> List[TrendSignal]:
        """Read the mission's evidence through the ledger, not through a column on the source.

        mission_evidence -> observations -> sources. The legacy trend_signals.mission_id could
        hold one mission per source, so a source two missions had both observed belonged to
        whichever wrote last; this join returns exactly the observations this mission recorded.
        """
        pool = await self._get_pool()
        query = """
            SELECT
                s.platform,
                o.observed_title,
                o.metric_value,
                o.growth_velocity,
                o.source_url,
                o.geo_code,
                o.metadata,
                o.observed_at,
                o.published_at,
                o.cluster_id,
                e.mission_id,
                o.id,
                o.source_id,
                o.identity_source,
                o.time_provenance
            FROM mission_evidence e
            JOIN observations o ON o.id = e.observation_id
            JOIN sources s ON s.id = o.source_id
            WHERE e.mission_id = %s
            ORDER BY o.metric_value DESC, o.observed_at DESC;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (str(mission_id),))
                    rows = await cur.fetchall()

            signals = []
            for row in rows:
                (
                    platform_str, title, metric, velocity, url, geo_str, meta_json, observed,
                    published, c_id, m_id, o_id, src_id, route, provenance,
                ) = row
                meta = meta_json if isinstance(meta_json, dict) else json.loads(meta_json or "{}")
                sig = TrendSignal(
                    platform=PlatformType(platform_str),
                    raw_title=title,
                    metric_value=float(metric or 0.0),
                    growth_velocity=float(velocity or 0.0),
                    source_url=url,
                    geo_code=GeoCode(geo_str),
                    cluster_id=UUID(str(c_id)) if c_id else None,
                    mission_id=UUID(str(m_id)) if m_id else None,
                    observation_id=UUID(str(o_id)),
                    source_id=_uuid_or_none(src_id),
                    identity_source=route,
                    time_provenance=provenance,
                    metadata=meta,
                    # Passed through exactly as stored. NULL means the collection time was never
                    # recorded, and substituting one here would turn that into "collected now".
                    captured_at=observed,
                    published_at=published,
                )
                signals.append(sig)
            return signals
        except Exception as e:
            logger.error(f"Error fetching signals for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to fetch mission signals: {e}") from e

    async def assign_observation_clusters(self, signals: List[TrendSignal]) -> int:
        """Set the cluster on observations already written.

        Membership arrived after the sighting was stored -- the discovery pass clusters at the
        end. Putting the signals back through save_signals would record each of them a second
        time, so this is an UPDATE keyed on the observation the writer returned.
        """
        updates = [
            (str(s.cluster_id), str(s.observation_id))
            for s in signals
            if s.observation_id and s.cluster_id
        ]
        if not updates:
            return 0
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "UPDATE observations SET cluster_id = %s WHERE id = %s;", updates
                    )
            return len(updates)
        except Exception as e:
            logger.error(f"Error assigning clusters to observations: {e}", exc_info=True)
            raise RepositoryException(f"Failed to assign observation clusters: {e}") from e

    async def attach_mission_evidence(self, mission_id: UUID, signals: List[TrendSignal]) -> int:
        """Record that a mission used observations that already exist.

        The quota fallback needs this: when a connector returns nothing, the mission keeps the
        evidence it had. Re-submitting those observations through the writer would claim the
        harness polled a platform it could not reach.
        """
        rows = [
            (str(mission_id), str(s.observation_id)) for s in signals if s.observation_id
        ]
        if not rows:
            return 0
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.executemany(
                        "INSERT INTO mission_evidence (mission_id, observation_id)"
                        " VALUES (%s, %s) ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                        rows,
                    )
            return len(rows)
        except Exception as e:
            logger.error(f"Error attaching mission evidence: {e}", exc_info=True)
            raise RepositoryException(f"Failed to attach mission evidence: {e}") from e

    async def prune_mission_evidence(self, mission_id: UUID, retained_observation_ids) -> int:
        """Drop this mission's claims on anything outside the retained set.

        The replacement writes first and prunes last, so the window where a failure can hurt is
        a window where the mission holds too much rather than nothing. Stale evidence is
        recoverable on the next pass; deleted evidence is not.
        """
        retained = [str(observation_id) for observation_id in retained_observation_ids]
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    if retained:
                        await cur.execute(
                            "DELETE FROM mission_evidence"
                            " WHERE mission_id = %s AND NOT (observation_id = ANY(%s::uuid[]))",
                            (str(mission_id), retained),
                        )
                    else:
                        await cur.execute(
                            "DELETE FROM mission_evidence WHERE mission_id = %s",
                            (str(mission_id),),
                        )
                    removed = cur.rowcount or 0
                    await conn.commit()
            return removed
        except Exception as e:
            logger.error(f"Error pruning evidence for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to prune mission evidence: {e}") from e

    async def delete_mission_signals(self, mission_id: UUID) -> int:
        """Withdraw this mission's claims, and nothing else.

        The name is from when a mission owned its signals. It does not: a source and its
        observations are shared, and 1,301 legacy associations sit across sources that other
        missions also observed. Deleting them here would delete another mission's evidence and
        the cluster history built on it, so only the association rows go.
        """
        pool = await self._get_pool()
        query = "DELETE FROM mission_evidence WHERE mission_id = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (str(mission_id),))
                    deleted_count = cur.rowcount
                    await conn.commit()
            logger.info(f"Withdrew {deleted_count} evidence rows for mission {mission_id}.")
            return deleted_count
        except Exception as e:
            logger.error(f"Error deleting signals for mission {mission_id}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to delete mission signals: {e}") from e

    async def log_event(
        self,
        component: str,
        event_type: str,
        message: str,
        level: str = "INFO",
        details: Optional[dict] = None,
    ) -> None:
        from ignis.infrastructure.security.pii_sanitizer import sanitize_pii_text, sanitize_pii_data
        pool = await self._get_pool()
        query = """
            INSERT INTO system_audit_logs (level, component, event_type, message, details, created_at)
            VALUES (%s, %s, %s, %s, %s, %s);
        """
        params = (
            _log_level(level),
            component,
            event_type,
            sanitize_pii_text(message),
            json.dumps(sanitize_pii_data(details or {})),
            datetime.now(timezone.utc),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, params)
        except Exception as e:
            logger.error(f"Error writing audit log ({component}): {e}")

    async def get_recent_logs(
        self,
        level: Optional[str] = None,
        component: Optional[str] = None,
        limit: int = 50,
    ) -> List[dict]:
        pool = await self._get_pool()
        conditions = []
        params = []

        if level:
            # upper() on the column as well: rows written before the level was canonical are
            # still stored verbatim, and must stay findable by it.
            conditions.append("upper(level) = %s")
            params.append(_log_level(level))
        if component:
            conditions.append("component = %s")
            params.append(component)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"""
            SELECT id, level, component, event_type, message, details, created_at
            FROM system_audit_logs
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s;
        """
        params.append(limit)

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, tuple(params))
                    rows = await cur.fetchall()

            logs = []
            for r in rows:
                l_id, lvl, comp, evt, msg, dtl_json, created = r
                dtl = dtl_json if isinstance(dtl_json, dict) else json.loads(dtl_json or "{}")
                logs.append({
                    "id": l_id,
                    "level": _log_level(lvl),
                    "component": comp,
                    "event_type": evt,
                    "message": msg,
                    "details": dtl,
                    "created_at": created.isoformat() if created else None,
                })
            return logs
        except Exception as e:
            logger.error(f"Error querying audit logs: {e}", exc_info=True)
            return []

    async def save_platform_credentials(
        self,
        platform: str,
        auth_type: str,
        credentials_data: Dict[str, Any],
        is_active: bool = True,
        expires_at: Optional[datetime] = None,
    ) -> None:
        pool = await self._get_pool()
        # Zero-Knowledge Encryption before persisting to database
        payload_to_store = encrypt_credentials(credentials_data)

        query = """
            INSERT INTO platform_credentials (
                platform,
                auth_type,
                credentials_data,
                is_active,
                expires_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (platform) DO UPDATE SET
                auth_type = EXCLUDED.auth_type,
                credentials_data = EXCLUDED.credentials_data,
                is_active = EXCLUDED.is_active,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW();
        """
        key = _platform_key(platform)
        params = (
            key,
            auth_type,
            json.dumps(payload_to_store),
            is_active,
            # Aware and UTC before it is sent, so TIMESTAMPTZ never reads it in the session zone.
            _utc_datetime(expires_at),
        )
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    # A row stored under another casing is this platform's credential, so saving
                    # replaces it under the canonical key instead of adding a second row beside it.
                    await cur.execute(
                        "SELECT platform FROM platform_credentials"
                        " WHERE lower(trim(platform)) = %s;",
                        (key,),
                    )
                    stored = [r[0] for r in await cur.fetchall()]
                    if len(stored) > 1:
                        raise RepositoryException(_ambiguous_platform_message(key, stored))
                    if stored and stored[0] != key:
                        await cur.execute(
                            "UPDATE platform_credentials SET platform = %s WHERE platform = %s;",
                            (key, stored[0]),
                        )
                    await cur.execute(query, params)
            logger.info(f"Successfully saved encrypted credentials for platform [{platform}].")
        except RepositoryException:
            raise
        except Exception as e:
            logger.error(f"Error saving credentials for {platform}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to save credentials for {platform}: {e}") from e

    async def get_platform_credentials(self, platform: str) -> Optional[PlatformCredentialRecord]:
        pool = await self._get_pool()
        query = """
            SELECT platform, auth_type, credentials_data, is_active, expires_at, updated_at
            FROM platform_credentials
            WHERE lower(trim(platform)) = %s;
        """
        key = _platform_key(platform)
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (key,))
                    rows = await cur.fetchall()
            if len(rows) > 1:
                raise RepositoryException(
                    _ambiguous_platform_message(key, [r[0] for r in rows])
                )
            # Counted before the active filter: an inactive second row still means two
            # credentials for one platform, and save refuses the same pair.
            if not rows or rows[0][3] is not True:
                return None
            row = rows[0]

            plat, auth_type, creds_json, active, expires, updated = row
            raw_creds = creds_json if isinstance(creds_json, dict) else json.loads(creds_json or "{}")
            # Automatically decrypt ciphertext back to plaintext dictionary
            decrypted_creds = decrypt_credentials(raw_creds)
            return {
                "platform": key,
                "auth_type": auth_type,
                "credentials_data": decrypted_creds,
                "is_active": True,
                "expires_at": _utc_iso(expires),
                "updated_at": _utc_iso(updated),
            }
        except RepositoryException:
            raise
        except Exception as e:
            logger.error(f"Error retrieving credentials for {platform}: {e}", exc_info=True)
            return None

    async def list_platform_credentials(self) -> List[PlatformCredentialSummary]:
        pool = await self._get_pool()
        query = """
            SELECT platform, auth_type, is_active, expires_at, updated_at
            FROM platform_credentials
            ORDER BY updated_at DESC;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query)
                    rows = await cur.fetchall()
            result = []
            for r in rows:
                plat, auth_type, active, expires, updated = r
                result.append({
                    "platform": _platform_key(plat),
                    "auth_type": auth_type,
                    # The same test get applies, so a row lists as active only when it would
                    # also read as connected.
                    "is_active": active is True,
                    "expires_at": _utc_iso(expires),
                    "updated_at": _utc_iso(updated),
                })
            return result
        except Exception as e:
            logger.error(f"Error listing platform credentials: {e}", exc_info=True)
            return []

    async def delete_platform_credentials(self, platform: str) -> bool:
        """Delete the stored row, rather than marking it inactive.

        This used to run UPDATE ... SET is_active = FALSE. The row survived with its encrypted
        payload intact, so a credential the operator had been told was deleted was still
        recoverable from any copy of the database, and a second call kept returning True because
        there was always a row left to update. SQLite had always deleted, so the two backends
        disagreed about what the same method name meant.

        Deleting is also what the callers need: clearing a credential is what an operator reaches
        for after a leak, before decommissioning a machine, and as a step of key rotation. All
        three assume the material is gone.
        """
        pool = await self._get_pool()
        # Every row that normalizes to the platform, so erasure never leaves a legacy spelling of
        # the same secret behind.
        query = "DELETE FROM platform_credentials WHERE lower(trim(platform)) = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (_platform_key(platform),))
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting credentials for {platform}: {e}", exc_info=True)
            return False

    async def get_domain_lexicons(self, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        query = """
            SELECT domain, term, category, created_by, created_at
            FROM market_lexicons
        """
        params = []
        if domain:
            query += " WHERE domain = %s"
            params.append(domain.lower())
        query += " ORDER BY domain ASC, term ASC;"

        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, tuple(params) if params else None)
                    rows = await cur.fetchall()
            return [
                {
                    "domain": r[0],
                    "term": r[1],
                    "category": r[2],
                    "created_by": r[3],
                    "created_at": r[4].isoformat() if r[4] else None,
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching market lexicons: {e}")
            return []

    async def register_lexicon_terms(
        self,
        domain: str,
        terms: List[str],
        category: str = "vernacular",
        created_by: str = "agent",
    ) -> int:
        if not terms:
            return 0
        pool = await self._get_pool()
        clean_domain = domain.lower().strip()
        count = 0

        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    for t in terms:
                        clean_term = t.lower().strip()
                        if clean_term:
                            await cur.execute(
                                """
                                INSERT INTO market_lexicons (domain, term, category, created_by)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (domain, term) DO NOTHING;
                                """,
                                (clean_domain, clean_term, category, created_by)
                            )
                            count += 1
            return count
        except Exception as e:
            logger.error(f"Error registering lexicon terms: {e}", exc_info=True)
            raise RepositoryException(f"Failed to register lexicon terms: {e}") from e

    async def get_industry_taxonomies(self) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        query = "SELECT industry_code, industry_name, keywords FROM industry_taxonomies ORDER BY industry_code ASC;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query)
                    rows = await cur.fetchall()
            return [
                {
                    "industry_code": r[0],
                    "industry_name": r[1],
                    "keywords": r[2] if isinstance(r[2], list) else list(r[2] or []),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching industry taxonomies: {e}")
            return []

    async def get_runtime_config(self, key: str) -> Optional[str]:
        pool = await self._get_pool()
        query = "SELECT value FROM runtime_configs WHERE key = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, (key,))
                    row = await cur.fetchone()
                    return str(row[0]) if row else None
        except Exception as e:
            logger.error(f"Error fetching runtime config for {key}: {e}")
            return None

    async def get_all_runtime_configs(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        pool = await self._get_pool()
        if category:
            query = "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs WHERE category = %s ORDER BY key ASC;"
            params = (category,)
        else:
            query = "SELECT key, value, category, description, updated_by, created_at, updated_at FROM runtime_configs ORDER BY category ASC, key ASC;"
            params = ()
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await cur.execute(query, params)
                    rows = await cur.fetchall()
            return [
                {
                    "key": r[0],
                    "value": r[1],
                    "category": r[2],
                    "description": r[3],
                    "updated_by": r[4],
                    "created_at": str(r[5]),
                    "updated_at": str(r[6]),
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"Error fetching runtime configs: {e}")
            return []

    async def set_runtime_config(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        pool = await self._get_pool()
        query = """
            INSERT INTO runtime_configs (key, value, category, description, updated_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                category = COALESCE(EXCLUDED.category, runtime_configs.category),
                description = COALESCE(EXCLUDED.description, runtime_configs.description),
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW();
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (key, str(value), category, description, updated_by))
        except Exception as e:
            logger.error(f"Error setting runtime config for {key}: {e}")
            raise RepositoryException(f"Failed to set runtime config: {e}") from e

    async def delete_runtime_config(self, key: str) -> bool:
        pool = await self._get_pool()
        query = "DELETE FROM runtime_configs WHERE key = %s;"
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(query, (key,))
                    return cur.rowcount > 0
        except Exception as e:
            logger.error(f"Error deleting runtime config {key}: {e}")
            return False




    # ------------------------------------------------------------------
    # Research workspace scope (sql/017)
    # ------------------------------------------------------------------

    _WORKSPACE_COLUMNS = (
        "SELECT id, slug, name, root_path, format_version, status, created_at"
        " FROM research_workspaces"
    )

    _BRIEF_COLUMNS = (
        "SELECT id, workspace_id, mission_id, revision_number, decision, target_user, problem,"
        " geo, timeframe, hypothesis, falsifiers, alternative_hypotheses, null_hypothesis,"
        " kill_criteria, revision_rule, evidence_contract_version, confirmed_by, confirmed_at"
        " FROM market_brief_revisions"
    )

    @staticmethod
    def _workspace_from_row(row) -> ResearchWorkspace:
        ws_id, slug, name, root_path, format_version, status, created_at = row
        return ResearchWorkspace(
            slug=slug,
            root_path=Path(root_path),
            workspace_id=UUID(str(ws_id)),
            name=name,
            format_version=int(format_version),
            status=WorkspaceStatus(status),
            created_at=created_at,
        )

    @staticmethod
    def _brief_from_row(row) -> MarketBriefRevision:
        (
            rev_id, ws_id, mission_id, revision_number, decision, target_user, problem,
            geo, timeframe, hypothesis, falsifiers, alternative_hypotheses, null_hypothesis,
            kill_criteria, revision_rule, _contract_version, confirmed_by, confirmed_at,
        ) = row
        return MarketBriefRevision(
            brief_revision_id=UUID(str(rev_id)),
            workspace_id=UUID(str(ws_id)),
            mission_id=UUID(str(mission_id)),
            revision_number=int(revision_number),
            decision=decision,
            target_user=target_user,
            problem=problem,
            geo=geo,
            timeframe=timeframe,
            hypothesis=hypothesis,
            falsifiers=tuple(falsifiers or ()),
            alternative_hypotheses=(
                tuple(alternative_hypotheses) if alternative_hypotheses is not None else None
            ),
            null_hypothesis=null_hypothesis,
            kill_criteria=tuple(kill_criteria) if kill_criteria is not None else None,
            revision_rule=revision_rule,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at,
        )

    async def save_research_workspace(self, workspace: ResearchWorkspace) -> ResearchWorkspace:
        pool = await self._get_pool()
        query = """
            INSERT INTO research_workspaces
            (id, slug, name, root_path, format_version, status, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                format_version = EXCLUDED.format_version;
        """
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        query,
                        (
                            str(workspace.workspace_id),
                            workspace.slug,
                            workspace.name or workspace.slug,
                            str(workspace.root_path),
                            workspace.format_version,
                            workspace.status.value,
                            workspace.created_at,
                        ),
                    )
            return workspace
        except Exception as e:
            logger.error(f"Error saving research workspace {workspace.slug}: {e}", exc_info=True)
            raise RepositoryException(f"Failed to save research workspace: {e}") from e

    async def get_research_workspace(self, workspace_id: UUID) -> Optional[ResearchWorkspace]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(self._WORKSPACE_COLUMNS + " WHERE id = %s;", (str(workspace_id),))
                row = await cur.fetchone()
        return self._workspace_from_row(row) if row else None

    async def find_research_workspace_by_slug(
        self, slug: str, root_path: Optional[Path] = None
    ) -> Optional[ResearchWorkspace]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                if root_path is not None:
                    await cur.execute(
                        self._WORKSPACE_COLUMNS + " WHERE slug = %s AND root_path = %s;",
                        (slug, str(root_path)),
                    )
                else:
                    await cur.execute(
                        self._WORKSPACE_COLUMNS
                        + " WHERE slug = %s ORDER BY created_at DESC LIMIT 1;",
                        (slug,),
                    )
                row = await cur.fetchone()
        return self._workspace_from_row(row) if row else None

    async def list_research_workspaces(self, limit: int = 50) -> List[ResearchWorkspace]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    self._WORKSPACE_COLUMNS + " ORDER BY created_at DESC LIMIT %s;", (limit,)
                )
                rows = await cur.fetchall()
        return [self._workspace_from_row(r) for r in rows]

    @staticmethod
    async def _next_revision_number(cur, workspace_id: UUID) -> int:
        """The next number in this research line, read inside the writing transaction."""
        await cur.execute(
            "SELECT MAX(revision_number) FROM market_brief_revisions WHERE workspace_id = %s;",
            (str(workspace_id),),
        )
        row = await cur.fetchone()
        return int((row[0] if row else None) or 0) + 1

    @staticmethod
    async def _write_brief_revision_row(cur, revision: MarketBriefRevision) -> None:
        """A plain INSERT, never an upsert.

        A confirmed Brief is immutable, so a second write against the same mission or revision
        number is a caller trying to edit history rather than a retry to absorb.
        """
        await cur.execute(
            """
            INSERT INTO market_brief_revisions
            (id, workspace_id, mission_id, revision_number, decision, target_user, problem,
             geo, timeframe, hypothesis, falsifiers, alternative_hypotheses, null_hypothesis,
             kill_criteria, revision_rule, evidence_contract_version, confirmed_by, confirmed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
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
                list(revision.falsifiers),
                (
                    list(revision.alternative_hypotheses)
                    if revision.alternative_hypotheses is not None
                    else None
                ),
                revision.null_hypothesis,
                list(revision.kill_criteria) if revision.kill_criteria is not None else None,
                revision.revision_rule,
                revision.evidence_contract_version,
                revision.confirmed_by,
                revision.confirmed_at,
            ),
        )

    async def save_brief_revision(self, revision: MarketBriefRevision) -> MarketBriefRevision:
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await self._write_brief_revision_row(cur, revision)
            return revision
        except Exception as e:
            logger.error(f"Error saving Market Brief revision: {e}", exc_info=True)
            raise RepositoryException(
                "A confirmed Market Brief revision already exists for this mission, or the "
                f"revision could not be written: {e}"
            ) from e

    async def create_market_mission_with_brief(
        self, mission: ResearchMission, revision: MarketBriefRevision
    ) -> Tuple[ResearchMission, MarketBriefRevision]:
        """Write the Market mission and the Brief that authorizes it, or write neither.

        One connection and one transaction, because the two rows are one fact. Writing the
        mission first and the revision second left an orphan MARKET mission behind whenever the
        second write failed -- a mission that cannot run, because the execution gate refuses a
        Market mission with no confirmed Brief, and that nothing would ever clean up. A
        compensating delete is not the fix: research_missions cascades to mission_evidence, so a
        delete that raced anything would withdraw evidence rather than undo a half-write.
        """
        pool = await self._get_pool()
        try:
            # psycopg commits this block on a clean exit and rolls it back on any exception, so
            # the two statements land together or not at all.
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    # The owning workspace row is locked first, so the maximum is read inside
                    # the transaction that writes the next number. Reading it beforehand left a
                    # window in which two confirmations saw the same number, and the loser
                    # failed on the unique constraint reporting the Brief as already confirmed
                    # -- which is not what had happened. The workspace row is the lock even when
                    # the research has no revision yet, which is exactly the racing first write.
                    await cur.execute(
                        "SELECT id FROM research_workspaces WHERE id = %s FOR UPDATE;",
                        (str(revision.workspace_id),),
                    )
                    numbered = dataclasses.replace(
                        revision,
                        revision_number=await self._next_revision_number(
                            cur, revision.workspace_id
                        ),
                    )
                    await self._write_mission_row(cur, mission)
                    await self._write_brief_revision_row(cur, numbered)
            return mission, numbered
        except Exception as e:
            logger.error(
                f"Error confirming Market Brief for mission {mission.id}: {e}", exc_info=True
            )
            raise RepositoryException(
                f"Market Brief confirmation failed and nothing was written: {e}"
            ) from e

    async def create_attention_mission_with_manifest(
        self, mission: ResearchMission, manifest: MissionManifest
    ) -> Tuple[ResearchMission, MissionManifest]:
        """Write the surfaced mission and its authority contract in one transaction."""
        if manifest.mission_id != mission.id:
            raise InvalidMissionManifestError(
                "The persisted manifest must carry the mission it authorizes."
            )
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await self._write_mission_row(cur, mission)
                    await self._write_manifest_row(cur, manifest)
            return mission, manifest
        except Exception as exc:
            logger.error(
                "Error creating Attention mission %s with its manifest: %s",
                mission.id,
                exc,
                exc_info=True,
            )
            raise RepositoryException(
                f"Attention mission confirmation failed and nothing was written: {exc}"
            ) from exc

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
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id FROM research_workspaces WHERE id = %s FOR UPDATE;",
                        (str(revision.workspace_id),),
                    )
                    numbered = dataclasses.replace(
                        revision,
                        revision_number=await self._next_revision_number(
                            cur, revision.workspace_id
                        ),
                    )
                    await self._write_mission_row(cur, mission)
                    await self._write_brief_revision_row(cur, numbered)
                    await self._write_manifest_row(cur, manifest)
            return mission, numbered, manifest
        except Exception as exc:
            logger.error(
                "Error confirming Market mission %s with its manifest: %s",
                mission.id,
                exc,
                exc_info=True,
            )
            raise RepositoryException(
                f"Market mission confirmation failed and nothing was written: {exc}"
            ) from exc

    async def get_brief_revision(
        self, workspace_id: UUID, brief_revision_id: UUID
    ) -> Optional[MarketBriefRevision]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    self._BRIEF_COLUMNS + " WHERE id = %s;", (str(brief_revision_id),)
                )
                row = await cur.fetchone()
        if not row:
            return None
        if str(row[1]) != str(workspace_id):
            # An error, not an empty result. An empty result reads as "this research has no such
            # Brief", which is a different and much quieter untruth.
            raise WorkspaceScopeMismatchError(
                f"Brief revision {brief_revision_id} belongs to workspace {row[1]}, "
                f"not to {workspace_id}."
            )
        return self._brief_from_row(row)

    async def get_brief_revision_for_mission(
        self, mission_id: UUID
    ) -> Optional[MarketBriefRevision]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    self._BRIEF_COLUMNS + " WHERE mission_id = %s;", (str(mission_id),)
                )
                row = await cur.fetchone()
        return self._brief_from_row(row) if row else None

    async def next_brief_revision_number(self, workspace_id: UUID) -> int:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "SELECT MAX(revision_number) FROM market_brief_revisions WHERE workspace_id = %s;",
                    (str(workspace_id),),
                )
                row = await cur.fetchone()
        return int((row[0] if row else None) or 0) + 1

    async def list_workspace_missions(
        self, workspace_id: UUID, limit: int = 50
    ) -> List[ResearchMission]:
        pool = await self._get_pool()
        query = """
            SELECT id, title, keywords, shortcode, agent, session_id, platforms, geo_code,
                   timeframe, status, summary, workspace_id, surface,
                   parent_attention_mission_id, parent_cluster_id, brief_revision_id,
                   revises_mission_id, created_at, updated_at
            FROM research_missions
            WHERE workspace_id = %s
            ORDER BY created_at DESC
            LIMIT %s;
        """
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(query, (str(workspace_id), limit))
                rows = await cur.fetchall()

        missions: List[ResearchMission] = []
        for row in rows:
            (m_id, title, kws, sc, agent_val, sess_id, plats, geo, tf, status, summary,
             ws_id, surface, parent_mission, parent_cluster, brief_id, revises_id,
             created, updated) = row
            missions.append(
                ResearchMission(
                    id=UUID(str(m_id)),
                    title=title,
                    keywords=list(kws or []),
                    shortcode=sc or str(m_id)[:8].upper(),
                    agent=agent_val or "claude",
                    session_id=sess_id,
                    platforms=[resolve_platform(p) for p in (plats or [])],
                    geo_code=resolve_geo(geo),
                    timeframe=tf,
                    status=status,
                    summary=summary,
                    workspace_id=_uuid_or_none(ws_id),
                    surface=surface,
                    parent_attention_mission_id=_uuid_or_none(parent_mission),
                    parent_cluster_id=_uuid_or_none(parent_cluster),
                    brief_revision_id=_uuid_or_none(brief_id),
                    revises_mission_id=_uuid_or_none(revises_id),
                    created_at=created,
                    updated_at=updated,
                )
            )
        return missions

    @staticmethod
    def _manifest_from_row(row) -> MissionManifest:
        return MissionManifest(
            mission_id=UUID(str(row[0])),
            outcome=row[1],
            decision_context=row[2],
            required_channels=tuple(row[3]),
            optional_channels=tuple(row[4]),
            authority_boundary=AuthorityBoundary(**row[5]),
            quota_budget=dict(row[6]),
            output_type=row[7],
            stop_conditions=tuple(row[8]),
            analysis_policy=row[9],
            retention_policy=row[10],
            created_by=row[11],
            confirmed_at=row[12],
        )

    _MANIFEST_COLUMNS = (
        "SELECT mission_id, outcome, decision_context, required_channels, optional_channels,"
        " authority_boundary, quota_budget, output_type, stop_conditions, analysis_policy,"
        " retention_policy, created_by, confirmed_at, manifest_digest FROM mission_manifests"
    )

    @staticmethod
    async def _write_manifest_row(cur, manifest: MissionManifest) -> None:
        await cur.execute(
            "INSERT INTO mission_manifests"
            " (mission_id, outcome, decision_context, required_channels, optional_channels,"
            " authority_boundary, quota_budget, output_type, stop_conditions,"
            " analysis_policy, retention_policy, created_by, confirmed_at, manifest_digest)"
            " VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s);",
            (
                str(manifest.mission_id),
                manifest.outcome,
                manifest.decision_context,
                list(manifest.required_channels),
                list(manifest.optional_channels),
                json.dumps(manifest.authority_boundary.to_payload(), sort_keys=True),
                json.dumps(dict(manifest.quota_budget), sort_keys=True),
                manifest.output_type.value,
                list(manifest.stop_conditions),
                manifest.analysis_policy,
                manifest.retention_policy,
                manifest.created_by,
                manifest.confirmed_at,
                manifest.manifest_digest,
            ),
        )

    async def save_mission_manifest(self, manifest: MissionManifest) -> MissionManifest:
        if manifest.mission_id is None:
            raise InvalidMissionManifestError("A persisted manifest requires mission_id.")
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "INSERT INTO mission_manifests"
                    " (mission_id, outcome, decision_context, required_channels, optional_channels,"
                    " authority_boundary, quota_budget, output_type, stop_conditions,"
                    " analysis_policy, retention_policy, created_by, confirmed_at, manifest_digest)"
                    " VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s, %s, %s, %s)"
                    " ON CONFLICT (mission_id) DO NOTHING;",
                    (
                        str(manifest.mission_id),
                        manifest.outcome,
                        manifest.decision_context,
                        list(manifest.required_channels),
                        list(manifest.optional_channels),
                        json.dumps(manifest.authority_boundary.to_payload(), sort_keys=True),
                        json.dumps(dict(manifest.quota_budget), sort_keys=True),
                        manifest.output_type.value,
                        list(manifest.stop_conditions),
                        manifest.analysis_policy,
                        manifest.retention_policy,
                        manifest.created_by,
                        manifest.confirmed_at,
                        manifest.manifest_digest,
                    ),
                )
                await cur.execute(
                    self._MANIFEST_COLUMNS + " WHERE mission_id = %s;",
                    (str(manifest.mission_id),),
                )
                row = await cur.fetchone()
                stored = self._manifest_from_row(row)
                if row[13] != manifest.manifest_digest or stored.manifest_digest != manifest.manifest_digest:
                    raise InvalidMissionManifestError(
                        f"Mission {manifest.mission_id} already has a different immutable manifest."
                    )
        return stored

    async def get_mission_manifest(self, mission_id: UUID) -> Optional[MissionManifest]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    self._MANIFEST_COLUMNS + " WHERE mission_id = %s;", (str(mission_id),)
                )
                row = await cur.fetchone()
        return self._manifest_from_row(row) if row else None

    async def claim_mission_writer(self, mission_id: UUID, run_id: UUID) -> bool:
        pool = await self._get_pool()
        # One statement, and the primary key is what decides. A SELECT followed by an INSERT
        # would leave a window in which two runs both saw the slot free.
        query = """
            INSERT INTO mission_writer_claims (mission_id, run_id)
            VALUES (%s, %s)
            ON CONFLICT (mission_id) DO NOTHING;
        """
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, (str(mission_id), str(run_id)))
                return cur.rowcount > 0

    async def release_mission_writer(self, mission_id: UUID, run_id: UUID) -> None:
        pool = await self._get_pool()
        # Scoped to the run that holds it: a run that never claimed the slot must not be able to
        # release another run's claim.
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM mission_writer_claims WHERE mission_id = %s AND run_id = %s;",
                    (str(mission_id), str(run_id)),
                )

    async def get_mission_writer_claim(self, mission_id: UUID) -> Optional[MissionWriterClaim]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "SELECT mission_id, run_id, claimed_at FROM mission_writer_claims"
                    " WHERE mission_id = %s;",
                    (str(mission_id),),
                )
                row = await cur.fetchone()
        if not row:
            return None
        return MissionWriterClaim(
            mission_id=UUID(str(row[0])), run_id=UUID(str(row[1])), claimed_at=row[2]
        )

    async def list_run_journals(self, mission_id: UUID, limit: int = 20) -> List[RunJournal]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "SELECT id, workspace_id, mission_id, journal_path, sequence, status,"
                    " started_at, completed_at FROM mission_run_journals"
                    " WHERE mission_id = %s ORDER BY started_at DESC, sequence DESC LIMIT %s;",
                    (str(mission_id), limit),
                )
                rows = await cur.fetchall()
        return [
            RunJournal(
                run_id=UUID(str(r[0])),
                mission_id=UUID(str(r[2])),
                workspace_id=UUID(str(r[1])),
                journal_path=Path(r[3]),
                sequence=int(r[4]),
                status=r[5],
                started_at=r[6],
                # Left as stored. NULL means the run never finished, and filling it in at read
                # time would report every interrupted run as completed.
                completed_at=r[7],
            )
            for r in rows
        ]

    async def record_run_journal(self, journal: RunJournal) -> RunJournal:
        pool = await self._get_pool()
        query = """
            INSERT INTO mission_run_journals
            (id, workspace_id, mission_id, journal_path, sequence, status, started_at, completed_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (journal_path) DO UPDATE SET
                status = EXCLUDED.status,
                completed_at = EXCLUDED.completed_at;
        """
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    query,
                    (
                        str(journal.run_id),
                        str(journal.workspace_id),
                        str(journal.mission_id),
                        str(journal.journal_path),
                        journal.sequence,
                        journal.status,
                        journal.started_at,
                        journal.completed_at,
                    ),
                )
        return journal

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
        receipt = await await_settled(self._publish_probe_outcomes(run_id, rows))
        return receipt.outcome_count if receipt is not None else 0

    async def commit_probe_outcomes(
        self, command: ProbeOutcomeCommitCommand
    ) -> ProbeOutcomeCommitReceipt:
        """Settle one fact/event transaction before returning its original typed receipt."""
        if type(command) is not ProbeOutcomeCommitCommand:
            raise ValueError("A probe publication requires an admitted commit command.")
        receipt = await await_settled(
            self._publish_probe_outcomes(command.run_id, command.outcomes, command)
        )
        assert receipt is not None  # Admitted commands cannot contain an empty batch.
        return receipt

    @staticmethod
    def _probe_fact_value(value: Any) -> Any:
        """Encode immutable admitted values without retaining caller-owned aliases."""
        if isinstance(value, Mapping):
            return {key: PostgresTimescaleRepository._probe_fact_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [PostgresTimescaleRepository._probe_fact_value(item) for item in value]
        if isinstance(value, Enum):
            return PostgresTimescaleRepository._probe_fact_value(value.value)
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
        pool = await self._get_pool()
        try:
            # The pool context commits/rolls back on this same connection before reuse.
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    await self._lock_relay_tables(cur)
                    await cur.execute(
                        "SELECT mission_id FROM mission_run_journals WHERE id = %s FOR SHARE",
                        (str(run_id),),
                    )
                    journal = await cur.fetchone()
                    if journal is None:
                        if command is None and not rows:
                            return None
                        raise RepositoryException("Probe publication requires a recorded run journal.")
                    mission_id = journal[0]
                    if command is not None and command.mission_id != mission_id:
                        raise RepositoryException("Probe command mission does not own its recorded run.")
                    admitted = command
                    if admitted is None and rows:
                        try:
                            admitted = ProbeOutcomeCommitCommand(mission_id=mission_id, run_id=run_id, outcomes=rows)
                        except ValueError as exc:
                            raise RepositoryException("Probe facts were refused before publication.") from exc
                    if admitted is not None:
                        # Bootstrap and lock the mission control row in the fact transaction.
                        # Concurrent first publications serialize here before reading receipts.
                        await cur.execute(
                            "INSERT INTO mission_progress_revisions (mission_id, revision) VALUES (%s, 0)"
                            " ON CONFLICT (mission_id) DO NOTHING",
                            (str(mission_id),),
                        )
                        await cur.execute(
                            "SELECT revision FROM mission_progress_revisions WHERE mission_id = %s FOR UPDATE",
                            (str(mission_id),),
                        )
                        revision = (await cur.fetchone())[0]
                        await cur.execute(
                            "SELECT c.payload_fingerprint, c.outcome_count, e.id, e.revision, e.ordinal,"
                            " e.kind, e.provenance, e.recorded_at, e.causation_key, e.run_id"
                            " FROM mission_progress_commands c JOIN mission_progress_events e"
                            " ON e.id = c.event_id AND e.mission_id = c.mission_id"
                            " WHERE c.mission_id = %s AND c.command_key = %s",
                            (str(mission_id), admitted.command_key),
                        )
                        original = await cur.fetchone()
                        if original is not None:
                            if original[0] != admitted.payload_fingerprint:
                                raise RepositoryException("Probe command conflicts with its original committed facts.")
                            return ProbeOutcomeCommitReceipt(
                                command_key=admitted.command_key, payload_fingerprint=original[0],
                                outcome_count=original[1], event=MissionProgressEvent(
                                    event_id=original[2],
                                    cursor=MissionRelayCursor(mission_id=mission_id, revision=original[3], ordinal=original[4]),
                                    kind=MissionProgressKind(original[5]), provenance=RelayProvenance(original[6]),
                                    recorded_at=original[7], causation_key=original[8], run_id=original[9],
                                ),
                            )
                    await cur.execute(
                        "SELECT m.required_channels, m.optional_channels"
                        " FROM mission_run_journals j"
                        " JOIN mission_manifests m ON m.mission_id = j.mission_id"
                        " WHERE j.id = %s;",
                        (str(run_id),),
                    )
                    manifest_row = await cur.fetchone()
                    if manifest_row is not None:
                        require_complete_channel_outcomes(
                            manifest_row[0], manifest_row[1], admitted.outcomes if admitted is not None else rows
                        )
                    if admitted is None:
                        return None
                    await cur.executemany(
                        "INSERT INTO mission_probe_outcomes (id, run_id, platform, connector_surface,"
                        " status, signals_collected, queried_keywords, queried_window,"
                        " query_fingerprint, scope_attestation, note, collection_plan_digest,"
                        " evidence_contract_version, completed_at)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s);",
                        [
                            (
                                str(o.outcome_id),
                                str(o.run_id),
                                o.platform,
                                o.connector_surface,
                                o.status.value,
                                o.signals_collected,
                                list(o.queried_keywords),
                                o.queried_window,
                                o.query_fingerprint,
                                (
                                    json.dumps(
                                        self._probe_fact_value(o.scope_attestation), sort_keys=True,
                                        ensure_ascii=False, allow_nan=False, separators=(",", ":"),
                                    )
                                    if o.scope_attestation is not None
                                    else None
                                ),
                                o.note,
                                o.collection_plan_digest,
                                2 if o.collection_plan_digest is not None else 1,
                                o.completed_at,
                            )
                            for o in admitted.outcomes
                        ],
                    )
                    revision += 1
                    await cur.execute(
                        "UPDATE mission_progress_revisions SET revision = %s WHERE mission_id = %s",
                        (revision, str(mission_id)),
                    )
                    event = MissionProgressEvent(
                        event_id=uuid4(), cursor=MissionRelayCursor(mission_id=mission_id, revision=revision, ordinal=1),
                        kind=MissionProgressKind.PROBE_OUTCOMES_RECORDED, provenance=RelayProvenance.HARNESS_OBSERVED,
                        recorded_at=datetime.now(timezone.utc), causation_key=admitted.command_key, run_id=run_id,
                    )
                    receipt = ProbeOutcomeCommitReceipt(
                        command_key=admitted.command_key, payload_fingerprint=admitted.payload_fingerprint,
                        outcome_count=len(admitted.outcomes), event=event,
                    )
                    await cur.execute(
                        "INSERT INTO mission_progress_events (id, mission_id, revision, ordinal, kind,"
                        " provenance, recorded_at, causation_key, run_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (str(event.event_id), str(mission_id), revision, 1, event.kind.value,
                         event.provenance.value, event.recorded_at, event.causation_key, str(run_id)),
                    )
                    await cur.execute(
                        "INSERT INTO mission_progress_commands (mission_id, command_key, payload_fingerprint,"
                        " outcome_count, run_id, event_id, revision, ordinal) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (str(mission_id), receipt.command_key, receipt.payload_fingerprint, receipt.outcome_count,
                         str(run_id), str(event.event_id), revision, 1),
                    )
            return receipt
        except pg_errors.IntegrityError as exc:
            raise RepositoryException(
                f"Probe outcomes for run {run_id} were refused and none was written: {exc}"
            ) from exc

    async def get_latest_completed_probe_outcomes(
        self, mission_id: UUID
    ) -> List[MissionProbeOutcome]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    "SELECT o.id, o.run_id, o.platform, o.connector_surface, o.status,"
                    " o.signals_collected, o.query_fingerprint, o.completed_at,"
                    " o.queried_keywords, o.queried_window, o.scope_attestation, o.note,"
                    " o.collection_plan_digest"
                    " FROM mission_probe_outcomes o"
                    " WHERE o.run_id = ("
                    "   SELECT j.id FROM mission_run_journals j"
                    "   WHERE j.mission_id = %s AND j.status = 'COMPLETED'"
                    "   ORDER BY j.started_at DESC, j.sequence DESC LIMIT 1)"
                    " ORDER BY o.connector_surface;",
                    (str(mission_id),),
                )
                rows = await cur.fetchall()
        return [
            MissionProbeOutcome(
                outcome_id=UUID(str(r[0])),
                run_id=UUID(str(r[1])),
                platform=r[2],
                connector_surface=r[3],
                status=r[4],
                signals_collected=int(r[5]),
                query_fingerprint=r[6],
                completed_at=r[7],
                queried_keywords=tuple(r[8] or ()),
                queried_window=r[9],
                scope_attestation=r[10],
                note=r[11],
                collection_plan_digest=r[12],
            )
            for r in rows
        ]

    _QUALIFICATION_COLUMNS = (
        "SELECT mission_id, observation_id, brief_revision_id, frame_fingerprint, relation,"
        " purpose, confidence, reason_code, judged_by, model, hypothesis_target, evidence_role,"
        " evidence_contract_version, created_at"
        " FROM mission_evidence_qualifications"
    )

    @staticmethod
    def _qualification_from_row(row) -> EvidenceQualification:
        return EvidenceQualification(
            mission_id=UUID(str(row[0])),
            observation_id=UUID(str(row[1])),
            brief_revision_id=_uuid_or_none(row[2]),
            frame_fingerprint=row[3],
            relation=row[4],
            purpose=row[5],
            confidence=row[6],
            reason_code=row[7],
            judged_by=row[8],
            model=row[9],
            hypothesis_target=row[10],
            evidence_role=row[11],
            evidence_contract_version=row[12],
            created_at=row[13],
        )

    async def list_evidence_qualifications(
        self, mission_id: UUID
    ) -> List[EvidenceQualification]:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=tuple_row) as cur:
                await cur.execute(
                    self._QUALIFICATION_COLUMNS
                    + " WHERE mission_id = %s ORDER BY observation_id::text;",
                    (str(mission_id),),
                )
                rows = await cur.fetchall()
        return [self._qualification_from_row(r) for r in rows]

    async def save_evidence_qualifications(
        self, mission_id: UUID, qualifications: Sequence[EvidenceQualification]
    ) -> int:
        """Persist one batch atomically; replay is idempotent, a rewrite is refused."""
        batch = list(qualifications)
        if any(str(q.mission_id) != str(mission_id) for q in batch):
            raise InvalidEvidenceQualificationError(
                f"Every judgment in a batch for mission {mission_id} must name that mission."
            )
        if not batch:
            return 0
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    for q in batch:
                        # Insert-or-keep, then compare: the unique pair decides a race, and the
                        # comparison decides whether the survivor says the same thing.
                        await cur.execute(
                            "INSERT INTO mission_evidence_qualifications (mission_id,"
                            " observation_id, brief_revision_id, frame_fingerprint, relation,"
                            " purpose, confidence, reason_code, judged_by, model,"
                            " hypothesis_target, evidence_role, evidence_contract_version)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                            " ON CONFLICT (mission_id, observation_id) DO NOTHING;",
                            (
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
                            ),
                        )
                        if cur.rowcount:
                            continue
                        await cur.execute(
                            self._QUALIFICATION_COLUMNS
                            + " WHERE mission_id = %s AND observation_id = %s;",
                            (str(q.mission_id), str(q.observation_id)),
                        )
                        existing = await cur.fetchone()
                        if existing is None or not self._qualification_from_row(
                            existing
                        ).same_judgment(q):
                            raise EvidenceQualificationConflictError(
                                f"Observation {q.observation_id} already carries a different "
                                f"judgment for mission {mission_id}. A recorded judgment is not "
                                "rewritten; a different one needs a new mission or Market Brief "
                                "revision."
                            )
            return len(batch)
        except pg_errors.IntegrityError as exc:
            raise InvalidEvidenceQualificationError(
                f"The batch names evidence mission {mission_id} does not hold, so none of it was "
                f"recorded: {exc}"
            ) from exc

    @staticmethod
    def _claim_from_rows(row, binding_rows: Sequence[Any]) -> MissionClaim:
        bindings = tuple(
            MissionClaimEvidence(
                binding_id=UUID(str(binding[0])),
                claim_id=UUID(str(binding[1])),
                observation_id=_uuid_or_none(binding[2]),
                probe_outcome_id=_uuid_or_none(binding[3]),
                role=EvidenceDirection(binding[4]),
                hypothesis_target=binding[5],
            )
            for binding in binding_rows
        )
        return MissionClaim(
            claim_id=UUID(str(row[0])),
            mission_id=UUID(str(row[1])),
            brief_revision_id=_uuid_or_none(row[2]),
            frame_digest=row[3],
            client_claim_key=row[4],
            claim_type=ClaimType(row[5]),
            wording=row[6],
            inference_method=row[7],
            metric_denominator=row[8],
            metric_timeframe=row[9],
            confidence=row[10],
            limitations=tuple(row[11] or ()),
            change_conditions=tuple(row[12] or ()),
            status=ClaimStatus(row[13]),
            withheld_reasons=tuple(row[14] or ()),
            created_by=row[15],
            created_at=row[16],
            evidence_bindings=bindings,
        )

    _CLAIM_COLUMNS = (
        "SELECT id, mission_id, brief_revision_id, frame_digest, client_claim_key, claim_type,"
        " wording, inference_method, metric_denominator, metric_timeframe, confidence,"
        " limitations, change_conditions, status,"
        " withheld_reasons, created_by, created_at FROM mission_claims"
    )
    _BINDING_COLUMNS = (
        "SELECT id, claim_id, observation_id, probe_outcome_id, role, hypothesis_target"
        " FROM mission_claim_evidence"
    )

    async def _read_claims(
        self, mission_id: UUID, *, include_superseded: bool, conn=None
    ) -> List[MissionClaim]:
        pool = await self._get_pool()

        async def _read(active_conn):
            async with active_conn.cursor(row_factory=tuple_row) as cur:
                where = " WHERE mission_id = %s"
                if not include_superseded:
                    where += " AND status <> 'SUPERSEDED'"
                await cur.execute(
                    self._CLAIM_COLUMNS + where + " ORDER BY created_at, id;",
                    (str(mission_id),),
                )
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    await cur.execute(
                        self._BINDING_COLUMNS + " WHERE claim_id = %s ORDER BY id;",
                        (str(row[0]),),
                    )
                    result.append(self._claim_from_rows(row, await cur.fetchall()))
                return result

        if conn is not None:
            return await _read(conn)
        async with pool.connection() as active_conn:
            return await _read(active_conn)

    async def save_mission_claims(
        self, mission_id: UUID, frame_digest: str, claims: Sequence[MissionClaim]
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
        pool = await self._get_pool()
        try:
            async with pool.connection() as conn:
                async with conn.cursor(row_factory=tuple_row) as cur:
                    for claim in batch:
                        await cur.execute(
                            "INSERT INTO mission_claims"
                            " (id, mission_id, brief_revision_id, frame_digest, client_claim_key,"
                            " claim_type, wording, inference_method, metric_denominator,"
                            " metric_timeframe, confidence, limitations,"
                            " change_conditions, status, withheld_reasons, created_by, created_at)"
                            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                            " ON CONFLICT (mission_id, frame_digest, client_claim_key) DO NOTHING;",
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
                                list(claim.limitations),
                                list(claim.change_conditions),
                                claim.status.value,
                                list(claim.withheld_reasons),
                                claim.created_by,
                                claim.created_at,
                            ),
                        )
                        if cur.rowcount:
                            for binding in claim.evidence_bindings:
                                if binding.claim_id != claim.claim_id:
                                    raise InvalidMissionClaimError(
                                        "Every evidence binding must name the claim carrying it."
                                    )
                                await cur.execute(
                                    "INSERT INTO mission_claim_evidence"
                                    " (id, claim_id, observation_id, probe_outcome_id, role,"
                                    " hypothesis_target) VALUES (%s, %s, %s, %s, %s, %s);",
                                    (
                                        str(binding.binding_id),
                                        str(binding.claim_id),
                                        (
                                            str(binding.observation_id)
                                            if binding.observation_id
                                            else None
                                        ),
                                        (
                                            str(binding.probe_outcome_id)
                                            if binding.probe_outcome_id
                                            else None
                                        ),
                                        binding.role.value,
                                        binding.hypothesis_target,
                                    ),
                                )
                            continue
                        await cur.execute(
                            self._CLAIM_COLUMNS
                            + " WHERE mission_id = %s AND frame_digest = %s"
                            " AND client_claim_key = %s;",
                            (str(mission_id), frame_digest, claim.client_claim_key),
                        )
                        existing = await cur.fetchone()
                        await cur.execute(
                            self._BINDING_COLUMNS + " WHERE claim_id = %s ORDER BY id;",
                            (str(existing[0]),),
                        )
                        stored = self._claim_from_rows(existing, await cur.fetchall())
                        if stored.idempotency_payload() != claim.idempotency_payload():
                            raise InvalidMissionClaimError(
                                f"client_claim_key {claim.client_claim_key!r} already names a different claim."
                            )
                stored = await self._read_claims(
                    mission_id, include_superseded=True, conn=conn
                )
            by_identity = {
                (claim.frame_digest, claim.client_claim_key): claim for claim in stored
            }
            return [
                by_identity[(claim.frame_digest, claim.client_claim_key)] for claim in batch
            ]
        except pg_errors.IntegrityError as exc:
            raise InvalidMissionClaimError(
                f"The claim batch violates its evidence binding contract: {exc}"
            ) from exc

    async def list_mission_claims(
        self, mission_id: UUID, *, include_superseded: bool = False
    ) -> List[MissionClaim]:
        return await self._read_claims(
            mission_id, include_superseded=include_superseded
        )

    async def supersede_mission_claims(self, mission_id: UUID, current_frame_digest: str) -> int:
        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE mission_claims SET status = 'SUPERSEDED'"
                    " WHERE mission_id = %s AND frame_digest <> %s AND status <> 'SUPERSEDED';",
                    (str(mission_id), current_frame_digest),
                )
                return cur.rowcount

    async def load_mission_evidence_snapshot(self, mission_id: UUID):
        from ignis.infrastructure.persistence.evidence_snapshot import (
            SnapshotConnectionPool,
            read_evidence_snapshot,
        )

        pool = await self._get_pool()
        async with pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                reader = copy.copy(self)
                reader._pool = SnapshotConnectionPool(conn)
                return await read_evidence_snapshot(reader, mission_id)

    async def inventory_legacy_baseline(self) -> Dict[str, Any]:
        """Bypass runtime bootstrap guards with a dedicated read-only transaction."""

        def _sync_inventory() -> Dict[str, Any]:
            with psycopg.connect(self._dsn) as conn:
                conn.execute("SET TRANSACTION READ ONLY")
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
                            "id": str(row[0]),
                            "captured_at": row[1].isoformat() if row[1] else None,
                            "source_url_present": bool(row[2]),
                            "metadata_present": bool(row[3]),
                        }
                        for row in signals
                    ],
                    "metrics": [
                        {"id": int(row[0]), "signal_id": str(row[1])} for row in metrics
                    ],
                    "orphan_metric_ids": [int(row[0]) for row in orphans],
                    "excluded_mission_rows": int(excluded),
                }

        return await asyncio.to_thread(_sync_inventory)

    @staticmethod
    def _research_queries(conn):
        """Keep every relational decoder query on the held physical connection."""

        async def execute(statement, params=()):
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(statement, params)

        async def fetchone(statement, params=()):
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(statement, params)
                return await cursor.fetchone()

        async def fetchall(statement, params=()):
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(statement, params)
                return await cursor.fetchall()

        return execute, fetchone, fetchall

    async def load_research_work(self, mission_id):
        """Read one existing-schema snapshot without installing or migrating storage."""

        async def read():
            pool = await self._get_pool()
            async with pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                    return await self._research_snapshot(conn, mission_id)

        return await await_settled(read())

    @staticmethod
    def _research_receipt(row):
        from ignis.application.ports.research_work_port import ResearchWorkCommitReceipt

        return ResearchWorkCommitReceipt(
            disposition=row["disposition"],
            reason_code=row["reason_code"],
            revision=row["revision"],
            work_version=row["work_version"],
            assignment_version=row["assignment_version"],
            receipt_id=row["receipt_id"],
            event_ids=tuple(row["event_ids"]),
            recorded_at=row["recorded_at"],
        )

    async def _research_snapshot(self, conn, mission_id, *, canonical=None):
        _, fetchone, _ = self._research_queries(conn)
        if canonical is None and (await fetchone(
            "SELECT to_regclass('public.research_assignments') AS relation"
        ))["relation"]:
            canonical = await self._commit_snapshot(conn, mission_id)
        return await self._decode_research_snapshot(conn, mission_id, canonical=canonical)

    @staticmethod
    async def _decode_research_snapshot(conn, mission_id, *, canonical):
        from ignis.application.ports.research_work_port import ResearchRecordedMetadata, ResearchWorkSnapshot
        from ignis.domain.research_work import (
            ResearchAuthority,
            ResearchAssignment,
            ResearchInputBindings,
            ResearchWorkItem,
        )
        from ignis.infrastructure.persistence.mission_relay_reader import _pg_event

        execute, fetchone, fetchall = PostgresTimescaleRepository._research_queries(conn)
        scope = (str(mission_id),)
        revision_row = await fetchone("SELECT revision FROM mission_progress_revisions WHERE mission_id=%s", scope)
        revision = revision_row["revision"] if revision_row else 0
        pairs = tuple(
            [
                (r["id"], r["source_id"])
                for r in await fetchall(
                    "SELECT o.id,o.source_id FROM observations o JOIN mission_evidence e ON e.observation_id=o.id WHERE e.mission_id=%s ORDER BY o.id",
                    scope,
                )
            ]
        )
        events = tuple(
            [
                _pg_event(r)
                for r in await fetchall(
                    "SELECT * FROM mission_progress_events WHERE mission_id=%s ORDER BY revision,ordinal", scope
                )
            ]
        )
        exists = (await fetchone("SELECT to_regclass('public.research_assignments') AS relation"))["relation"]
        assignments, works, metadata = ((), (), ())
        handoffs, findings, acknowledgements, current_findings = ((), (), (), ())
        if exists:
            assignments = tuple(
                [
                    ResearchAssignment(
                        assignment_id=UUID(str(r["assignment_id"])),
                        mission_id=mission_id,
                        host_task_ref=r["host_task_ref"],
                        epoch=r["epoch"],
                        authority=ResearchAuthority(
                            actions=frozenset(r["actions"]),
                            sources=frozenset(r["sources"]),
                            deadline=r["deadline"],
                            quota_ceiling=r["quota_ceiling"],
                        ),
                        capability=r["capability"],
                        state=r["state"],
                        version=r["version"],
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_assignments WHERE mission_id=%s ORDER BY epoch", scope
                    )
                ]
            )

            async def bindings(input_id):
                r = await fetchone("SELECT * FROM research_input_sets WHERE input_id=%s", (input_id,))
                return ResearchInputBindings(
                    mission_id=mission_id,
                    manifest_digest=r["manifest_digest"],
                    brief_digest=r["brief_digest"],
                    frame_digest=r["frame_digest"],
                    observation_ids=tuple(
                        [
                            o["observation_id"]
                            for o in await fetchall(
                                "SELECT observation_id FROM research_input_observations WHERE input_id=%s ORDER BY ordinal",
                                (input_id,),
                            )
                        ]
                    ),
                    finding_revisions=tuple(
                        [
                            (f["finding_id"], f["revision"])
                            for f in await fetchall(
                                "SELECT finding_id,revision FROM research_input_findings WHERE input_id=%s ORDER BY ordinal",
                                (input_id,),
                            )
                        ]
                    ),
                )

            works = tuple(
                [
                    ResearchWorkItem(
                        work_id=UUID(str(r["work_id"])),
                        assignment_id=UUID(str(r["assignment_id"])),
                        mission_id=mission_id,
                        run_id=UUID(str(r["run_id"])) if r["run_id"] else None,
                        question=r["question"],
                        expertise=r["expertise"],
                        assignee_ref=r["assignee_ref"],
                        inputs=await bindings(r["input_id"]),
                        dependencies=tuple(
                            [
                                d["dependency_work_id"]
                                for d in await fetchall(
                                    "SELECT dependency_work_id FROM research_work_dependencies WHERE work_id=%s ORDER BY ordinal",
                                    (r["work_id"],),
                                )
                            ]
                        ),
                        epoch=r["epoch"],
                        state=r["state"],
                        version=r["version"],
                        ownership_fence=r["ownership_fence"],
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_work_items WHERE mission_id=%s ORDER BY (SELECT min(mission_revision) FROM research_recorded_metadata m WHERE m.record_kind='WORK' AND m.record_id=research_work_items.work_id),work_id",
                        scope,
                    )
                ]
            )
            from ignis.domain.research_findings import ResearchFindingRevision, ResearchHandoff
            from ignis.application.ports.research_work_port import ResearchHandoffAcknowledgement

            def optional_time(value):
                return value if value else None

            async def directions(row, direction):
                return tuple(
                    [
                        o["observation_id"]
                        for o in await fetchall(
                            "SELECT observation_id FROM research_finding_observations WHERE finding_id=%s AND revision=%s AND direction=%s ORDER BY ordinal",
                            (row["finding_id"], row["revision"], direction),
                        )
                    ]
                )

            findings = tuple(
                [
                    ResearchFindingRevision(
                        finding_id=UUID(str(r["finding_id"])),
                        revision=r["revision"],
                        predecessor_revision=r["predecessor_revision"],
                        work_id=UUID(str(r["work_id"])),
                        handoff_id=UUID(str(r["handoff_id"])),
                        inputs=await bindings(r["input_id"]),
                        result_type=r["result_type"],
                        statement=r["statement"],
                        limitations=tuple(r["limitations"]),
                        open_questions=tuple(r["open_questions"]),
                        supporting_observation_ids=await directions(r, "SUPPORT"),
                        contradicting_observation_ids=await directions(r, "CONTRADICTION"),
                        context_observation_ids=await directions(r, "CONTEXT"),
                        alternative_explanation=r["alternative_explanation"],
                        claim_id=UUID(str(r["claim_id"])) if r["claim_id"] else None,
                        recorded_at=optional_time(r["submitted_recorded_at"]),
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_finding_revisions WHERE mission_id=%s ORDER BY (SELECT min(mission_revision) FROM research_recorded_metadata m WHERE m.record_kind='HANDOFF' AND m.record_id=research_finding_revisions.handoff_id),handoff_ordinal",
                        scope,
                    )
                ]
            )

            async def references(handoff_id, kind):
                return tuple(
                    [
                        r["reference_id"]
                        for r in await fetchall(
                            "SELECT reference_id FROM research_handoff_references WHERE handoff_id=%s AND reference_kind=%s ORDER BY ordinal",
                            (handoff_id, kind),
                        )
                    ]
                )

            handoffs = tuple(
                [
                    ResearchHandoff(
                        handoff_id=UUID(str(r["handoff_id"])),
                        work_id=UUID(str(r["work_id"])),
                        expected_version=r["expected_version"],
                        ownership_fence=r["ownership_fence"],
                        consumer_ref=r["consumer_ref"],
                        inputs=await bindings(r["input_id"]),
                        observation_sources=tuple(
                            [
                                (o["observation_id"], o["source_id"])
                                for o in await fetchall(
                                    "SELECT observation_id,source_id FROM research_handoff_observations WHERE handoff_id=%s ORDER BY ordinal",
                                    (r["handoff_id"],),
                                )
                            ]
                        ),
                        outcome_ids=await references(r["handoff_id"], "OUTCOME"),
                        claim_ids=await references(r["handoff_id"], "CLAIM"),
                        result=r["result"],
                        limitations=tuple(r["limitations"]),
                        open_questions=tuple(r["open_questions"]),
                        findings=tuple([f for f in findings if f.handoff_id == r["handoff_id"]]),
                        occurred_at=optional_time(r["occurred_at"]),
                        recorded_at=optional_time(r["submitted_recorded_at"]),
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_handoffs WHERE mission_id=%s ORDER BY (SELECT min(mission_revision) FROM research_recorded_metadata m WHERE m.record_kind='HANDOFF' AND m.record_id=research_handoffs.handoff_id),handoff_id",
                        scope,
                    )
                ]
            )
            acknowledgements = tuple(
                [
                    ResearchHandoffAcknowledgement(
                        handoff_id=UUID(str(r["handoff_id"])),
                        consumer_ref=r["consumer_ref"],
                        expected_version=r["expected_version"],
                        disposition=r["disposition"],
                        reason_code=r["reason_code"],
                        inputs=await bindings(r["input_id"]),
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_handoff_acknowledgements WHERE mission_id=%s ORDER BY handoff_id", scope
                    )
                ]
            )
            from ignis.application.use_cases.current_evidence_frame import frame_from_snapshot

            try:
                frame = frame_from_snapshot(canonical).frame_digest
            except InvalidMissionClaimError:
                frame = None
            latest = {f.finding_id: f for f in findings}
            eligible = {
                i
                for i, f in latest.items()
                if canonical.manifest is not None
                and canonical.brief is not None
                and (frame is not None)
                and (f.inputs.manifest_digest == canonical.manifest.manifest_digest)
                and (f.inputs.brief_digest == compute_frame_fingerprint(canonical.mission, canonical.brief))
                and (f.inputs.frame_digest == frame)
                and (set(f.inputs.observation_ids) <= set(dict(pairs)))
            }
            current = set()
            while True:
                admitted = {
                    i
                    for i in eligible
                    if all([d in current and latest[d].revision == v for d, v in latest[i].inputs.finding_revisions])
                }
                if admitted == current:
                    break
                current = admitted
            current_findings = tuple([(i, f.revision) for i, f in latest.items() if i in current])
            metadata = tuple(
                [
                    ResearchRecordedMetadata(
                        record_kind=r["record_kind"],
                        record_id=UUID(str(r["record_id"])),
                        record_version=r["record_version"],
                        mission_revision=r["mission_revision"],
                        recorded_at=r["recorded_at"],
                        provenance=r["provenance"],
                    )
                    for r in await fetchall(
                        "SELECT * FROM research_recorded_metadata WHERE mission_id=%s ORDER BY mission_revision,record_kind,record_id",
                        scope,
                    )
                ]
            )
        return ResearchWorkSnapshot(
            mission_id=mission_id,
            revision=revision,
            current_epoch=max([a.epoch for a in assignments], default=0),
            assignments=assignments,
            work_items=works,
            handoffs=handoffs,
            findings=findings,
            acknowledgements=acknowledgements,
            events=events,
            observation_sources=pairs,
            current_finding_revisions=current_findings,
            recorded_metadata=metadata,
        )

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

        async def commit():
            pool = await self._get_pool()
            async with pool.connection() as conn:
                return await settle(conn)

        async def settle(conn):
            execute, fetchone, fetchall = self._research_queries(conn)
            cur = conn.cursor(row_factory=tuple_row)
            recorded_at = datetime.now(timezone.utc)
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
                    recorded_at=recorded_at,
                )

            async def persist(result):
                # Known-scope safe refusal is durable without inventing an event/revision.
                await execute(
                    "INSERT INTO research_work_commands (mission_id,command_key,payload_fingerprint,operation,receipt_id,disposition,reason_code,revision,work_version,assignment_version,event_ids,recorded_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                        list(result.event_ids),
                        recorded_at.isoformat(),
                    ),
                )
                await conn.commit()
                return result

            from hashlib import sha256

            key = sha256(command.idempotency_key.encode()).hexdigest()
            try:
                await self._lock_relay_tables(cur, analysis=True)
                recorded_at = (await fetchone("SELECT transaction_timestamp() AS timestamp"))["timestamp"]
                # Lock canonical inputs before the revision row; legacy writers share this gate.
                if not await fetchone("SELECT 1 FROM research_missions WHERE id=%s", (str(command.mission_id),)):
                    await conn.rollback()
                    return receipt("SCOPE_MISMATCH")
                await execute(
                    "INSERT INTO mission_progress_revisions (mission_id,revision) VALUES (%s,0) ON CONFLICT (mission_id) DO NOTHING",
                    (str(command.mission_id),),
                )
                await fetchone(
                    "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE",
                    (str(command.mission_id),),
                )
                canonical = await self._commit_snapshot(conn, command.mission_id)
                original = await fetchone(
                    "SELECT * FROM research_work_commands WHERE mission_id=%s AND command_key=%s",
                    (str(command.mission_id), key),
                )
                state = await self._research_snapshot(conn, command.mission_id, canonical=canonical)
                revision = state.revision
                initial_revision = revision
                if original:
                    result = (
                        self._research_receipt(original)
                        if original["payload_fingerprint"] == command.fingerprint
                        else receipt("IDEMPOTENCY_CONFLICT")
                    )
                    await conn.rollback()
                    return result
                payload = command.payload

                async def refuse(reason):
                    return await persist(receipt(reason))

                def input_reason(inputs):
                    latest = {f.finding_id: f.revision for f in state.findings}
                    if any([latest.get(i) != v for i, v in inputs.finding_revisions]):
                        return "STALE_DEPENDENCY_REVISION"
                    try:
                        frame = frame_from_snapshot(canonical).frame_digest
                    except InvalidMissionClaimError:
                        return "STALE_INPUT_FRAME"
                    if (
                        canonical.manifest is None
                        or canonical.brief is None
                        or inputs.manifest_digest != canonical.manifest.manifest_digest
                        or (inputs.brief_digest != compute_frame_fingerprint(canonical.mission, canonical.brief))
                        or (inputs.frame_digest != frame)
                        or (not set(inputs.observation_ids) <= set(dict(state.observation_sources)))
                    ):
                        return "STALE_INPUT_FRAME"
                    if not set(inputs.finding_revisions) <= set(state.current_finding_revisions):
                        return "STALE_DEPENDENCY_REVISION"
                    return None

                async def metadata(kind, identity, version):
                    await execute(
                        "INSERT INTO research_recorded_metadata VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            str(command.mission_id),
                            kind,
                            str(identity),
                            version,
                            revision,
                            recorded_at.isoformat(),
                            "HARNESS_OBSERVED",
                        ),
                    )

                if not command.host_authorized:
                    return await refuse("UNAUTHORIZED_HOST")
                if command.expected_revision != revision:
                    return await refuse("STALE_REVISION")
                # Transaction time predates lock waits; authority and freshness use admission time.
                admission_now = (await fetchone("SELECT clock_timestamp() AS timestamp"))["timestamp"]
                operation = command.operation
                closure = operation == "ACK_STOP" or (
                    operation == "END_WORK"
                    and payload.disposition in {"FAILED", "INTERRUPTED", "INSUFFICIENT_EVIDENCE"}
                )
                if operation == "ASSIGN_RESEARCH":
                    if payload.assignment.mission_id != command.mission_id:
                        return await refuse("SCOPE_MISMATCH")
                    if (
                        payload.assignment.epoch != command.expected_epoch
                        or command.expected_epoch != state.current_epoch + 1
                    ):
                        return await refuse("STALE_EPOCH")
                elif not closure and command.expected_epoch != state.current_epoch:
                    return await refuse("STALE_EPOCH")
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
                        or (brief.brief_revision_id != payload.expected_brief_revision_id)
                    ):
                        return await refuse("STALE_INPUT_FRAME")
                    if assignment.state != "ASSIGNED" or assignment.version != 1:
                        return await refuse("INVALID_TRANSITION")
                    if assignment.authority.deadline <= admission_now:
                        return await refuse("AUTHORITY_EXPIRED")
                    if (
                        not assignment.authority.actions <= ACTIONS
                        or not assignment.authority.sources
                        <= set(manifest.required_channels + manifest.optional_channels)
                        or assignment.authority.quota_ceiling > sum(manifest.quota_budget.values())
                    ):
                        return await refuse("AUTHORITY_WIDENING")
                    if any((a.state not in TERMINAL for a in state.assignments)):
                        return await refuse("INVALID_TRANSITION")
                    if any((a.assignment_id == assignment.assignment_id for a in state.assignments)):
                        return await refuse("INVALID_INPUT")
                    try:
                        assignment = dataclasses.replace(
                            assignment,
                            host_task_ref=sanitize_pii_text(assignment.host_task_ref),
                            capability=sanitize_pii_text(assignment.capability),
                        )
                    except ValueError:
                        return await refuse("INVALID_INPUT")
                    a = assignment
                    await execute(
                        "INSERT INTO research_assignments (assignment_id,mission_id,host_task_ref,epoch,actions,sources,deadline,quota_ceiling,capability,expected_manifest_digest,expected_brief_revision_id,state,version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            str(a.assignment_id),
                            str(a.mission_id),
                            a.host_task_ref,
                            a.epoch,
                            sorted(a.authority.actions),
                            sorted(a.authority.sources),
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
                        handoff = (
                            next((h for h in state.handoffs if h.handoff_id == payload.handoff_id), None)
                            if operation == "ACK_HANDOFF"
                            else None
                        )
                        work_id = handoff.work_id if handoff else getattr(payload, "work_id", None)
                        work = next((w for w in state.work_items if w.work_id == work_id), None)
                        assignment = next(
                            (a for a in state.assignments if work and a.assignment_id == work.assignment_id), None
                        )
                    if assignment is None or (work is None and operation != "END_RESEARCH"):
                        return await refuse("SCOPE_MISMATCH")
                    if not closure:
                        if assignment.epoch != state.current_epoch:
                            return await refuse("STALE_EPOCH")
                        if assignment.state in TERMINAL:
                            return await refuse("ASSIGNMENT_TERMINAL")
                        if operation != "END_RESEARCH" and assignment.authority.deadline <= admission_now:
                            return await refuse("AUTHORITY_EXPIRED")
                    if operation in {"ASSIGN_WORK", "START_WORK", "RESUME_WORK", "RECORD_ACTIVITY"}:
                        manifest = canonical.manifest
                        if (
                            manifest is None
                            or not assignment.authority.actions <= ACTIONS
                            or (
                                not assignment.authority.sources
                                <= set(manifest.required_channels + manifest.optional_channels)
                            )
                            or (assignment.authority.quota_ceiling > sum(manifest.quota_budget.values()))
                        ):
                            return await refuse("AUTHORITY_WIDENING")
                    if operation in {"START_WORK", "RESUME_WORK", "RECORD_ACTIVITY"}:
                        if not set(work.inputs.observation_ids) <= set(dict(state.observation_sources)):
                            return await refuse("INPUT_IDENTITY_MISMATCH")
                        if not set(work.inputs.finding_revisions) <= set(state.current_finding_revisions):
                            return await refuse("STALE_DEPENDENCY_REVISION")
                        try:
                            current_frame = frame_from_snapshot(canonical).frame_digest
                        except InvalidMissionClaimError:
                            return await refuse("STALE_INPUT_FRAME")
                        if (
                            canonical.brief is None
                            or work.inputs.manifest_digest != canonical.manifest.manifest_digest
                            or work.inputs.brief_digest != compute_frame_fingerprint(canonical.mission, canonical.brief)
                            or (work.inputs.frame_digest != current_frame)
                        ):
                            return await refuse("STALE_INPUT_FRAME")
                    if operation in {"SUBMIT_HANDOFF", "ACK_HANDOFF"}:
                        from ignis.application.ports.research_work_port import SAFE_REASONS

                        if payload.expected_version != work.version:
                            return await refuse("STALE_WORK_VERSION")
                        if operation == "SUBMIT_HANDOFF" and payload.ownership_fence != work.ownership_fence:
                            return await refuse("OWNERSHIP_FENCE_MISMATCH")
                        if assignment.state == "CANCEL_PENDING" or work.state == "CANCEL_PENDING":
                            return await refuse("CANCELLATION_PENDING")
                        if work.state in TERMINAL:
                            return await refuse("WORK_TERMINAL")
                        if "ANALYZE" not in assignment.authority.actions:
                            return await refuse("ACTION_NOT_GRANTED")
                        if payload.inputs.mission_id != command.mission_id:
                            return await refuse("SCOPE_MISMATCH")
                        if operation == "SUBMIT_HANDOFF":
                            if work.state not in {"RUNNING", "WAITING"}:
                                return await refuse("INVALID_TRANSITION")
                            sources = dict(state.observation_sources)
                            if any([sources.get(o) != source for o, source in payload.observation_sources]):
                                historical = dict(
                                    tuple(row.values())
                                    for row in await fetchall(
                                        "SELECT observation_id,source_id FROM research_input_observations WHERE input_id=(SELECT input_id FROM research_work_items WHERE work_id=%s)",
                                        (str(work.work_id),),
                                    )
                                )
                                if any(
                                    [
                                        historical.get(o) != source
                                        for o, source in payload.observation_sources
                                        if sources.get(o) != source
                                    ]
                                ):
                                    return await refuse("INPUT_IDENTITY_MISMATCH")
                        problem = input_reason(payload.inputs)
                        if problem:
                            return await refuse(problem)
                        if payload.inputs != work.inputs:
                            return await refuse("INPUT_REVISION_MISMATCH")
                        input_id = (
                            await fetchone(
                                "SELECT input_id FROM research_work_items WHERE work_id=%s", (str(work.work_id),)
                            )
                        )["input_id"]
                        if operation == "ACK_HANDOFF":
                            if payload.reason_code is not None and payload.reason_code not in SAFE_REASONS:
                                return await refuse("INVALID_REASON_CODE")
                            safe_consumer = sanitize_pii_text(payload.consumer_ref)
                            if payload.inputs != handoff.inputs or safe_consumer != handoff.consumer_ref:
                                return await refuse("INPUT_IDENTITY_MISMATCH")
                            if work.state != "HANDOFF_READY" or any(
                                [a.handoff_id == handoff.handoff_id for a in state.acknowledgements]
                            ):
                                return await refuse("INVALID_TRANSITION")
                            try:
                                ack = dataclasses.replace(payload, consumer_ref=safe_consumer)
                            except ValueError:
                                return await refuse("INVALID_INPUT")
                            await execute(
                                "INSERT INTO research_handoff_acknowledgements VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                (
                                    str(command.mission_id),
                                    str(ack.handoff_id),
                                    input_id,
                                    ack.consumer_ref,
                                    ack.expected_version,
                                    ack.disposition,
                                    ack.reason_code,
                                ),
                            )
                            work = dataclasses.replace(
                                work,
                                version=work.version + 1,
                                state="COMPLETED" if ack.disposition == "ACCEPTED" else "HANDOFF_READY",
                            )
                            await execute(
                                "UPDATE research_work_items SET state=%s,version=%s WHERE work_id=%s",
                                (work.state, work.version, str(work.work_id)),
                            )
                            revision = await self._record_progress(
                                cur,
                                command.mission_id,
                                MissionProgressKind.HANDOFF_ACKNOWLEDGED,
                                "research:" + key,
                                work_id=work.work_id,
                                handoff_id=handoff.handoff_id,
                                reason=ack.disposition,
                            )
                            if ack.disposition == "ACCEPTED":
                                await self._record_progress(
                                    cur,
                                    command.mission_id,
                                    MissionProgressKind.WORK_ENDED,
                                    "research:" + key,
                                    work_id=work.work_id,
                                    handoff_id=handoff.handoff_id,
                                    reason="COMPLETED",
                                    revision=revision,
                                    ordinal=2,
                                )
                        else:
                            if any([h.handoff_id == payload.handoff_id for h in state.handoffs]):
                                return await refuse("INVALID_INPUT")
                            for outcome_id in payload.outcome_ids:
                                if not await fetchone(
                                    "SELECT 1 FROM mission_probe_outcomes o JOIN mission_run_journals j ON j.id=o.run_id WHERE o.id=%s AND j.mission_id=%s",
                                    (str(outcome_id), str(command.mission_id)),
                                ):
                                    return await refuse("INPUT_IDENTITY_MISMATCH")
                            for claim_id in (*payload.claim_ids, *[f.claim_id for f in payload.findings if f.claim_id]):
                                if not await fetchone(
                                    "SELECT 1 FROM mission_claims WHERE id=%s AND mission_id=%s",
                                    (str(claim_id), str(command.mission_id)),
                                ):
                                    return await refuse("INPUT_IDENTITY_MISMATCH")
                            latest = {f.finding_id: f.revision for f in state.findings}
                            for finding in payload.findings:
                                global_latest = await fetchone(
                                    "SELECT mission_id,max(revision) FROM research_finding_revisions WHERE finding_id=%s GROUP BY mission_id",
                                    (str(finding.finding_id),),
                                )
                                if global_latest and tuple(global_latest.values())[0] != command.mission_id:
                                    return await refuse("SCOPE_MISMATCH")
                                if finding.revision != latest.get(finding.finding_id, 0) + 1:
                                    return await refuse("STALE_DEPENDENCY_REVISION")
                            try:
                                safe_findings = tuple(
                                    [
                                        dataclasses.replace(
                                            f,
                                            statement=sanitize_pii_text(f.statement),
                                            limitations=tuple([sanitize_pii_text(t) for t in f.limitations]),
                                            open_questions=tuple([sanitize_pii_text(t) for t in f.open_questions]),
                                            alternative_explanation=sanitize_pii_text(f.alternative_explanation),
                                        )
                                        for f in payload.findings
                                    ]
                                )
                                handoff = dataclasses.replace(
                                    payload,
                                    consumer_ref=sanitize_pii_text(payload.consumer_ref),
                                    result=sanitize_pii_text(payload.result),
                                    limitations=tuple([sanitize_pii_text(t) for t in payload.limitations]),
                                    open_questions=tuple([sanitize_pii_text(t) for t in payload.open_questions]),
                                    findings=safe_findings,
                                )
                            except ValueError:
                                return await refuse("INVALID_INPUT")
                            h = handoff
                            await execute(
                                "INSERT INTO research_handoffs VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                (
                                    str(h.handoff_id),
                                    str(command.mission_id),
                                    str(h.work_id),
                                    input_id,
                                    h.expected_version,
                                    h.ownership_fence,
                                    h.consumer_ref,
                                    h.result,
                                    list(h.limitations),
                                    list(h.open_questions),
                                    h.occurred_at.isoformat() if h.occurred_at else None,
                                    h.recorded_at.isoformat() if h.recorded_at else None,
                                ),
                            )
                            for ordinal, (observation_id, source_id) in enumerate(h.observation_sources, 1):
                                await execute(
                                    "INSERT INTO research_handoff_observations VALUES (%s,%s,%s,%s,%s,%s)",
                                    (
                                        ordinal,
                                        str(command.mission_id),
                                        str(h.handoff_id),
                                        input_id,
                                        str(observation_id),
                                        str(source_id),
                                    ),
                                )
                            for ref_kind, identities in (("OUTCOME", h.outcome_ids), ("CLAIM", h.claim_ids)):
                                for ordinal, identity in enumerate(identities, 1):
                                    await execute(
                                        "INSERT INTO research_handoff_references VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                        (
                                            ordinal,
                                            str(command.mission_id),
                                            str(h.handoff_id),
                                            ref_kind,
                                            str(identity),
                                            str(identity) if ref_kind == "CLAIM" else None,
                                            str(identity) if ref_kind == "OUTCOME" else None,
                                        ),
                                    )
                            for ordinal, f in enumerate(h.findings, 1):
                                await execute(
                                    "INSERT INTO research_finding_revisions VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                    (
                                        ordinal,
                                        str(f.finding_id),
                                        f.revision,
                                        f.predecessor_revision,
                                        str(command.mission_id),
                                        str(f.work_id),
                                        str(f.handoff_id),
                                        input_id,
                                        f.result_type,
                                        f.statement,
                                        list(f.limitations),
                                        list(f.open_questions),
                                        f.alternative_explanation,
                                        str(f.claim_id) if f.claim_id else None,
                                        f.recorded_at.isoformat() if f.recorded_at else None,
                                    ),
                                )
                                for direction, ids in (
                                    ("SUPPORT", f.supporting_observation_ids),
                                    ("CONTRADICTION", f.contradicting_observation_ids),
                                    ("CONTEXT", f.context_observation_ids),
                                ):
                                    for ref_ordinal, observation_id in enumerate(ids, 1):
                                        await execute(
                                            "INSERT INTO research_finding_observations VALUES (%s,%s,%s,%s,%s,%s)",
                                            (
                                                ref_ordinal,
                                                str(command.mission_id),
                                                str(f.finding_id),
                                                f.revision,
                                                str(observation_id),
                                                direction,
                                            ),
                                        )
                            work = dataclasses.replace(work, state="HANDOFF_READY", version=work.version + 1)
                            await execute(
                                "UPDATE research_work_items SET state=%s,version=%s WHERE work_id=%s",
                                (work.state, work.version, str(work.work_id)),
                            )
                            revision = await self._record_progress(
                                cur,
                                command.mission_id,
                                MissionProgressKind.HANDOFF_COMMITTED,
                                "research:" + key,
                                work_id=work.work_id,
                                handoff_id=h.handoff_id,
                            )
                            for ordinal, f in enumerate(h.findings, 2):
                                await self._record_progress(
                                    cur,
                                    command.mission_id,
                                    MissionProgressKind.FINDING_REVISED,
                                    "research:" + key,
                                    work_id=work.work_id,
                                    handoff_id=h.handoff_id,
                                    finding_id=f.finding_id,
                                    revision=revision,
                                    ordinal=ordinal,
                                )
                                await metadata("FINDING", f.finding_id, f.revision)
                            await metadata("HANDOFF", h.handoff_id, 1)
                        await metadata("WORK", work.work_id, work.version)
                        event_ids = tuple(
                            [
                                UUID(str(tuple(r.values())[0]))
                                for r in await fetchall(
                                    "SELECT id FROM mission_progress_events WHERE mission_id=%s AND revision=%s ORDER BY ordinal",
                                    (str(command.mission_id), revision),
                                )
                            ]
                        )
                        return await persist(receipt(work=work, assignment=assignment, event_ids=event_ids))
                    if operation == "END_RESEARCH":
                        if payload.expected_version != assignment.version:
                            return await refuse("STALE_VERSION")
                        assignment = dataclasses.replace(
                            assignment, state=payload.disposition, version=assignment.version + 1
                        )
                        reason_text = sanitize_pii_text(payload.reason)
                        await execute(
                            "UPDATE research_assignments SET state=%s,version=%s,reason=%s WHERE assignment_id=%s",
                            (assignment.state, assignment.version, reason_text, str(assignment.assignment_id)),
                        )
                        record_kind = "ASSIGNMENT"
                        kind = MissionProgressKind.RESEARCH_ENDED
                    elif operation == "ASSIGN_WORK":
                        if work.mission_id != command.mission_id or work.epoch != assignment.epoch:
                            return await refuse("SCOPE_MISMATCH")
                        if (
                            work.state != "ASSIGNED"
                            or work.version != 1
                            or any((w.work_id == work.work_id for w in state.work_items))
                        ):
                            return await refuse("INVALID_TRANSITION")
                        if assignment.state == "CANCEL_PENDING":
                            return await refuse("CANCELLATION_PENDING")
                        if "ANALYZE" not in assignment.authority.actions:
                            return await refuse("ACTION_NOT_GRANTED")
                        if work.run_id and (
                            not await fetchone(
                                "SELECT 1 FROM mission_run_journals WHERE id=%s AND mission_id=%s",
                                (str(work.run_id), str(command.mission_id)),
                            )
                        ):
                            return await refuse("SCOPE_MISMATCH")
                        current_ids = dict(state.observation_sources)
                        if not set(work.inputs.observation_ids) <= set(current_ids):
                            return await refuse("INPUT_IDENTITY_MISMATCH")
                        if not set(work.inputs.finding_revisions) <= set(state.current_finding_revisions):
                            return await refuse("STALE_DEPENDENCY_REVISION")
                        try:
                            current_frame = frame_from_snapshot(canonical).frame_digest
                        except InvalidMissionClaimError:
                            return await refuse("STALE_INPUT_FRAME")
                        if (
                            canonical.manifest is None
                            or canonical.brief is None
                            or work.inputs.manifest_digest != canonical.manifest.manifest_digest
                            or (
                                work.inputs.brief_digest
                                != compute_frame_fingerprint(canonical.mission, canonical.brief)
                            )
                            or (work.inputs.frame_digest != current_frame)
                        ):
                            return await refuse("STALE_INPUT_FRAME")
                        dependencies = {w.work_id: w for w in state.work_items}
                        if any(
                            (d not in dependencies or dependencies[d].epoch != work.epoch for d in work.dependencies)
                        ):
                            return await refuse("SCOPE_MISMATCH")
                        try:
                            work = dataclasses.replace(
                                work,
                                question=sanitize_pii_text(work.question),
                                expertise=sanitize_pii_text(work.expertise),
                                assignee_ref=sanitize_pii_text(work.assignee_ref),
                            )
                        except ValueError:
                            return await refuse("INVALID_INPUT")
                        if sanitize_pii_text(work.ownership_fence) != work.ownership_fence:
                            return await refuse("INVALID_INPUT")
                        input_id = str(uuid4())
                        b = work.inputs
                        await execute(
                            "INSERT INTO research_input_sets VALUES (%s,%s,%s,%s,%s)",
                            (input_id, str(b.mission_id), b.manifest_digest, b.brief_digest, b.frame_digest),
                        )
                        for ordinal, (finding_id, finding_revision) in enumerate(b.finding_revisions, 1):
                            await execute(
                                "INSERT INTO research_input_findings VALUES (%s,%s,%s,%s,%s)",
                                (ordinal, input_id, str(command.mission_id), str(finding_id), finding_revision),
                            )
                        for ordinal, o in enumerate(b.observation_ids, 1):
                            await execute(
                                "INSERT INTO research_input_observations VALUES (%s,%s,%s,%s,%s)",
                                (ordinal, input_id, str(command.mission_id), str(o), str(current_ids[o])),
                            )
                        w = work
                        await execute(
                            "INSERT INTO research_work_items (work_id,assignment_id,mission_id,input_id,run_id,question,expertise,assignee_ref,epoch,state,version,ownership_fence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                            await execute(
                                "INSERT INTO research_work_dependencies VALUES (%s,%s,%s,%s)",
                                (ordinal, str(w.mission_id), str(w.work_id), str(d)),
                            )
                        record_kind = "WORK"
                        kind = MissionProgressKind.WORK_ASSIGNED
                    else:
                        if closure and command.expected_epoch != work.epoch:
                            return await refuse("STALE_EPOCH")
                        if operation in {"START_WORK", "RECORD_ACTIVITY"}:
                            r = payload.receipt
                            if r.epoch != work.epoch:
                                return await refuse("STALE_EPOCH")
                            if operation == "START_WORK" and any(
                                (
                                    next((w for w in state.work_items if w.work_id == d)).state
                                    not in {"COMPLETED", "HANDOFF_READY"}
                                    for d in work.dependencies
                                )
                            ):
                                return await refuse("DEPENDENCY_NOT_READY")
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
                        if operation == "END_WORK" and payload.disposition == "COMPLETED":
                            from ignis.domain.research_work import _work_reason

                            problem = _work_reason(
                                assignment,
                                work,
                                admission_now,
                                command.expected_epoch,
                                payload.expected_version,
                                payload.ownership_fence,
                            )
                            if problem:
                                return await refuse(problem)
                            results = [h for h in state.handoffs if h.work_id == work.work_id]
                            if not results or work.state != "HANDOFF_READY":
                                return await refuse("RESULT_REQUIRED")
                            selected = results[-1]
                            if any(
                                [
                                    a.handoff_id == selected.handoff_id and a.disposition == "REJECTED"
                                    for a in state.acknowledgements
                                ]
                            ):
                                return await refuse("RESULT_REQUIRED")
                            problem = input_reason(selected.inputs)
                            if problem:
                                return await refuse(problem)
                            from ignis.domain.research_work import ResearchTransition

                            transition = ResearchTransition(
                                "APPLIED", dataclasses.replace(work, state="COMPLETED", version=work.version + 1)
                            )
                        else:
                            transition = transition_research_work(
                                work=work, assignment=assignment, command=pure, now=admission_now
                            )
                        if transition.disposition != "APPLIED":
                            return await refuse(transition.reason_code)
                        if (
                            operation == "ACK_STOP"
                            and sanitize_pii_text(payload.execution_ref) != payload.execution_ref
                        ):
                            return await refuse("INVALID_INPUT")
                        if operation == "ACK_STOP" and (
                            not await fetchone(
                                "SELECT 1 FROM research_activity_receipts WHERE work_id=%s AND epoch=%s AND ownership_fence=%s AND execution_ref=%s",
                                (
                                    str(work.work_id),
                                    work.epoch,
                                    work.ownership_fence,
                                    sanitize_pii_text(payload.execution_ref),
                                ),
                            )
                        ):
                            return await refuse("EXECUTION_RECEIPT_NOT_CURRENT")
                        if (
                            operation in {"START_WORK", "RECORD_ACTIVITY"}
                            and sanitize_pii_text(r.execution_ref) != r.execution_ref
                        ):
                            return await refuse("INVALID_INPUT")
                        work = transition.work
                        if operation == "START_WORK" and assignment.state == "ASSIGNED":
                            assignment = dataclasses.replace(assignment, state="ACTIVE", version=assignment.version + 1)
                            await execute(
                                "UPDATE research_assignments SET state=%s,version=%s WHERE assignment_id=%s",
                                (assignment.state, assignment.version, str(assignment.assignment_id)),
                            )
                            assignment_activated = True
                        reason_text = sanitize_pii_text(payload.reason) if hasattr(payload, "reason") else None
                        await execute(
                            "UPDATE research_work_items SET state=%s,version=%s,reason=%s WHERE work_id=%s",
                            (work.state, work.version, reason_text, str(work.work_id)),
                        )
                        if operation in {"START_WORK", "RECORD_ACTIVITY"}:
                            await execute(
                                "INSERT INTO research_activity_receipts VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
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
                revision = await self._record_progress(
                    cur,
                    command.mission_id,
                    kind,
                    "research:" + key,
                    work_id=work.work_id if work else None,
                    reason=reason_text,
                )
                record = work if record_kind == "WORK" else assignment
                record_id = record.work_id if record_kind == "WORK" else record.assignment_id
                await execute(
                    "INSERT INTO research_recorded_metadata VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (
                        str(command.mission_id),
                        record_kind,
                        str(record_id),
                        record.version,
                        revision,
                        recorded_at.isoformat(),
                        "HARNESS_OBSERVED",
                    ),
                )
                if assignment_activated:
                    await execute(
                        "INSERT INTO research_recorded_metadata VALUES (%s,%s,%s,%s,%s,%s,%s)",
                        (
                            str(command.mission_id),
                            "ASSIGNMENT",
                            str(assignment.assignment_id),
                            assignment.version,
                            revision,
                            recorded_at.isoformat(),
                            "HARNESS_OBSERVED",
                        ),
                    )
                event_ids = tuple(
                    (
                        r["id"]
                        for r in await fetchall(
                            "SELECT id FROM mission_progress_events WHERE mission_id=%s AND revision=%s ORDER BY ordinal",
                            (str(command.mission_id), revision),
                        )
                    )
                )
                return await persist(receipt(work=work, assignment=assignment, event_ids=event_ids))
            except psycopg.Error:
                await conn.rollback()
                revision = initial_revision
                return receipt("STORAGE_FAILURE")
            except BaseException:
                await conn.rollback()
                raise
            finally:
                await cur.close()

        return await await_settled(commit())
