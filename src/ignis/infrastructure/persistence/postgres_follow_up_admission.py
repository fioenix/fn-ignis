"""Native PostgreSQL guarded admission and immutable typed receipt recovery."""

from ignis.infrastructure.persistence import follow_up_admission_rules as rules
from ignis.infrastructure.persistence.follow_up_admission_rules import encode, decode, input_reason, origin_reason
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import asyncio
import json
import psycopg
from uuid import UUID, uuid4
from psycopg.rows import tuple_row
from ignis.application.cancellation import await_settled
from ignis.infrastructure.persistence.identifiers import utc_datetime as _utc_datetime
from ignis.application.ports.follow_up_admission_port import FollowUpFactCommand
from ignis.application.ports.research_work_port import (
    FollowUpAdmissionCommand,
    FollowUpCommitReceipt,
    FollowUpSnapshot,
    FollowUpWorkCommand,
    ResearchWorkCommitReceipt,
)
from ignis.domain.follow_up_admission import (
    AssignmentBudget,
    CapabilityProof,
    OperationalGap,
    ParentBudget,
    WorkAuthority,
    digest,
)
from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope, FollowUpRelationship, FollowUpReservation
from ignis.domain.research_work import ResearchInputBindings
from ignis.domain.research_workspace import compute_frame_fingerprint


class PhysicalRow(tuple):
    def __new__(cls, values, names):
        row = super().__new__(cls, values)
        row.names = names
        return row

    def __getitem__(self, key):
        return super().__getitem__(self.names.index(key) if isinstance(key, str) else key)


def physical_rows(cursor):
    names = [c.name for c in cursor.description or ()]
    return lambda values: PhysicalRow([str(v) if isinstance(v, UUID) else v for v in values], names)


async def lock(repository, conn, mission_id):
    await repository._lock_relay_tables(conn.cursor(row_factory=tuple_row), analysis=True)
    row = await (
        await conn.execute("SELECT id FROM research_missions WHERE id=%s FOR UPDATE", (str(mission_id),))
    ).fetchone()
    if row:
        await conn.execute(
            "INSERT INTO mission_progress_revisions(mission_id,revision) VALUES(%s,0) ON CONFLICT(mission_id) DO NOTHING",
            (str(mission_id),),
        )
        await conn.execute(
            "SELECT revision FROM mission_progress_revisions WHERE mission_id=%s FOR UPDATE", (str(mission_id),)
        )


@asynccontextmanager
async def connection(repository, *, readonly=False):
    pool = await repository._get_pool()
    async with pool.connection() as conn:
        previous = conn.row_factory
        conn.row_factory = physical_rows
        try:
            if readonly:
                await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            yield conn
        finally:
            await conn.rollback()
            conn.row_factory = previous


async def work_from_row(repository, conn, row):
    original = await (
        await conn.execute(
            "SELECT * FROM research_input_sets WHERE input_id=%s AND mission_id=%s",
            (row["input_id"], row["parent_mission_id"]),
        )
    ).fetchone()
    owner = await (
        await conn.execute(
            "SELECT input_id FROM research_work_items WHERE work_id=%s AND mission_id=%s",
            (row["work_id"], row["parent_mission_id"]),
        )
    ).fetchone()
    if original is None or owner is None or owner[0] != row["input_id"]:
        raise ValueError("Original proposal input ownership mismatch.")
    inputs = ResearchInputBindings(
        mission_id=UUID(row["parent_mission_id"]),
        manifest_digest=original["manifest_digest"],
        brief_digest=original["brief_digest"],
        frame_digest=original["frame_digest"],
        observation_ids=tuple(
            (
                UUID(r[0])
                for r in await (
                    await conn.execute(
                        "SELECT observation_id FROM research_input_observations WHERE input_id=%s ORDER BY ordinal",
                        (row["input_id"],),
                    )
                ).fetchall()
            )
        ),
        finding_revisions=tuple(
            (
                (UUID(r[0]), r[1])
                for r in await (
                    await conn.execute(
                        "SELECT finding_id,revision FROM research_input_findings WHERE input_id=%s ORDER BY ordinal",
                        (row["input_id"],),
                    )
                ).fetchall()
            )
        ),
    )
    return FollowUpWork(
        work_id=UUID(row["work_id"]),
        parent_work_id=UUID(row["parent_work_id"]),
        assignment_id=UUID(row["assignment_id"]),
        gap_id=UUID(row["gap_id"]),
        inputs=inputs,
        research_epoch=row["research_epoch"],
        assignment_version=row["assignment_version"],
        work_version=row["work_version"],
        brief_revision_id=UUID(row["brief_revision_id"]),
        approved_scope=FollowUpScope(
            queries=tuple(json.loads(row["approved_queries"])), sources=frozenset(json.loads(row["approved_sources"]))
        ),
        requested_scope=FollowUpScope(
            queries=tuple(json.loads(row["requested_queries"])), sources=frozenset(json.loads(row["requested_sources"]))
        ),
        authority_deadline=_utc_datetime(row["authority_deadline"]),
    )


async def advance_revision(conn, mission_id):
    await conn.execute(
        "INSERT INTO mission_progress_revisions VALUES (%s,1) ON CONFLICT(mission_id) DO UPDATE SET revision=mission_progress_revisions.revision+1",
        (str(mission_id),),
    )
    return await revision(conn, mission_id)


async def refusal(conn, mission_id, reason):
    return FollowUpCommitReceipt(
        disposition="REFUSED",
        reason_code=reason,
        revision=await revision(conn, mission_id),
        receipt_id=uuid4(),
        recorded_at=datetime.now(timezone.utc),
        relationship=None,
        reservation=None,
    )


async def original(repository, conn, mission_id, operation, key, fingerprint):
    row = await (
        await conn.execute(
            "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=%s AND operation=%s AND command_key=%s",
            (str(mission_id), operation, sha256(key.encode()).hexdigest()),
        )
    ).fetchone()
    if row is None:
        return None
    try:
        receipt = await validated_receipt(repository, conn, row, mission_id)
    except (ValueError, KeyError, TypeError, AttributeError):
        return await refusal(conn, mission_id, "STORAGE_FAILURE")
    if row["fingerprint"] == fingerprint:
        return receipt
    if operation == "ADMIT":
        return await refusal(conn, mission_id, "IDEMPOTENCY_CONFLICT")
    return ResearchWorkCommitReceipt(
        disposition="REFUSED",
        reason_code="IDEMPOTENCY_CONFLICT",
        revision=await revision(conn, mission_id),
        work_version=None,
        assignment_version=None,
        receipt_id=uuid4(),
        event_ids=(),
        recorded_at=datetime.now(timezone.utc),
    )


async def revision(conn, mission_id):
    row = await (
        await conn.execute("SELECT revision FROM mission_progress_revisions WHERE mission_id=%s", (str(mission_id),))
    ).fetchone()
    return row[0] if row else 0


async def persist(conn, mission_id, operation, key, fingerprint, work_id, receipt, command):
    await conn.execute(
        "INSERT INTO mission_follow_up_commands VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            str(mission_id),
            operation,
            sha256(key.encode()).hexdigest(),
            fingerprint,
            str(work_id),
            encode(command),
            encode(receipt),
        ),
    )


async def state(repository, conn, mission_id):
    canonical = await repository._commit_snapshot(conn, mission_id)
    research = await repository._research_snapshot(conn, mission_id, canonical=canonical)
    return (canonical, research)


async def snapshot(repository, conn, mission_id):
    revision = await (
        await conn.execute("SELECT revision FROM mission_progress_revisions WHERE mission_id=%s", (str(mission_id),))
    ).fetchone()
    exists = await (await conn.execute("SELECT to_regclass('public.mission_follow_up_work')")).fetchone()
    if not exists or not exists[0]:
        return FollowUpSnapshot(
            mission_id=mission_id,
            revision=revision[0] if revision else 0,
            work_items=(),
            relationships=(),
            reservations=(),
            results=(),
        )
    works = tuple(
        [
            await work_from_row(repository, conn, r)
            for r in await (
                await conn.execute(
                    "SELECT * FROM mission_follow_up_work WHERE parent_mission_id=%s ORDER BY work_id",
                    (str(mission_id),),
                )
            ).fetchall()
        ]
    )
    indexed = {str(w.work_id): w for w in works}
    links = tuple(
        (
            FollowUpRelationship(
                follow_up_id=UUID(r["follow_up_id"]),
                work=indexed[r["work_id"]],
                child_mission_id=UUID(r["child_mission_id"]),
                child_manifest_digest=r["child_manifest_digest"],
                child_brief_digest=r["child_brief_digest"],
                reservation_id=UUID(r["reservation_id"]),
                idempotency_key=r["idempotency_key"],
            )
            for r in await (
                await conn.execute(
                    "SELECT * FROM mission_follow_ups WHERE parent_mission_id=%s ORDER BY follow_up_id",
                    (str(mission_id),),
                )
            ).fetchall()
        )
    )
    links_by_id = {str(r.follow_up_id): r for r in links}
    reservations = tuple(
        (
            FollowUpReservation(
                relationship=links_by_id[r["follow_up_id"]],
                reserved_quota=r["reserved_quota"],
                reserved_cost=r["reserved_cost"],
                state=r["state"],
                measured_quota=r["measured_quota"],
                measured_cost=r["measured_cost"],
                measurement_receipt_id=UUID(r["measurement_receipt_id"]) if r["measurement_receipt_id"] else None,
            )
            for r in await (
                await conn.execute(
                    "SELECT * FROM mission_follow_up_reservations WHERE parent_mission_id=%s ORDER BY reservation_id",
                    (str(mission_id),),
                )
            ).fetchall()
        )
    )
    return FollowUpSnapshot(
        mission_id=mission_id,
        revision=revision[0] if revision else 0,
        work_items=works,
        relationships=links,
        reservations=reservations,
        results=(),
    )


async def fact(conn, table, key, value):
    row = await (await conn.execute(f"SELECT * FROM {table} WHERE {key}=%s", (str(value),))).fetchone()
    if row is None:
        return None
    result = decode(row["payload"])
    parent = UUID(row["parent_mission_id"])
    if type(result) is OperationalGap:
        valid = (
            result.gap_id == UUID(row["gap_id"])
            and result.parent_work_id == UUID(row["parent_work_id"])
            and (result.inputs.mission_id == parent)
        )
    elif type(result) is ParentBudget:
        valid = result.budget_id == UUID(row["budget_id"]) and result.mission_id == parent
    elif type(result) is AssignmentBudget:
        valid = (
            result.binding_id == UUID(row["binding_id"])
            and result.budget_id == UUID(row["budget_id"])
            and (result.assignment_id == UUID(row["assignment_id"]))
            and (result.epoch == row["epoch"])
        )
    elif type(result) is WorkAuthority:
        valid = (
            result.work.work_id == UUID(row["work_id"])
            and result.work.inputs.mission_id == parent
            and (result.work.gap_id == UUID(row["gap_id"]))
            and (result.budget_id == UUID(row["budget_id"]))
            and (result.binding_id == UUID(row["binding_id"]))
        )
    else:
        valid = False
    if not valid:
        raise ValueError("Persisted admission identity mismatch.")
    return result


async def validated_receipt(repository, conn, row, mission_id):
    stored, receipt, work = rules.command_identity(row, mission_id)
    if type(stored) is FollowUpFactCommand and receipt.disposition == "APPLIED":
        record = stored.record
        table, key = (
            ("mission_follow_up_gaps", "gap_id")
            if type(record) is OperationalGap
            else ("mission_follow_up_parent_budgets", "budget_id")
            if type(record) is ParentBudget
            else ("mission_follow_up_assignment_budgets", "binding_id")
            if type(record) is AssignmentBudget
            else ("mission_follow_up_authorities", "work_id")
        )
        if await fact(conn, table, key, work) != record:
            raise ValueError("Original fact is detached from recording.")
    if type(stored) is FollowUpWorkCommand and receipt.disposition == "APPLIED":
        proposal = await (
            await conn.execute(
                "SELECT * FROM mission_follow_up_work WHERE work_id=%s AND parent_mission_id=%s",
                (str(work), str(mission_id)),
            )
        ).fetchone()
        if proposal is None or await work_from_row(repository, conn, proposal) != stored.work:
            raise ValueError("Original proposal identity mismatch.")
    if type(receipt) is FollowUpCommitReceipt and receipt.relationship:
        r = receipt.relationship
        physical = await (
            await conn.execute("SELECT * FROM mission_follow_ups WHERE follow_up_id=%s", (str(r.follow_up_id),))
        ).fetchone()
        proposal = await (
            await conn.execute(
                "SELECT * FROM mission_follow_up_work WHERE work_id=%s AND parent_mission_id=%s",
                (str(work), str(mission_id)),
            )
        ).fetchone()
        envelope = await fact(conn, "mission_follow_up_authorities", "work_id", work)
        root = (
            await fact(conn, "mission_follow_up_parent_budgets", "budget_id", envelope.budget_id) if envelope else None
        )
        binding = (
            await fact(conn, "mission_follow_up_assignment_budgets", "binding_id", envelope.binding_id)
            if envelope
            else None
        )
        allocation = await (
            await conn.execute(
                "SELECT * FROM mission_follow_up_reservations WHERE reservation_id=%s", (str(r.reservation_id),)
            )
        ).fetchone()
        resources = await (
            await conn.execute(
                "SELECT resource,allocated FROM mission_follow_up_reservation_resources WHERE reservation_id=%s",
                (str(r.reservation_id),),
            )
        ).fetchall()
        child = await (
            await conn.execute(
                "SELECT workspace_id,surface FROM research_missions WHERE id=%s", (str(r.child_mission_id),)
            )
        ).fetchone()
        parent = await (
            await conn.execute("SELECT workspace_id FROM research_missions WHERE id=%s", (str(mission_id),))
        ).fetchone()
        manifest_row = await (
            await conn.execute(repository._MANIFEST_COLUMNS + " WHERE mission_id=%s", (str(r.child_mission_id),))
        ).fetchone()
        briefs = [
            repository._brief_from_row(b)
            for b in await (
                await conn.execute(repository._BRIEF_COLUMNS + " WHERE mission_id=%s", (str(r.child_mission_id),))
            ).fetchall()
        ]
        rules.recovery_binding(
            receipt,
            mission_id,
            work,
            physical=physical,
            proposal=await work_from_row(repository, conn, proposal) if proposal else None,
            envelope=envelope,
            root=root,
            binding=binding,
            allocation=allocation,
            allocated_resources=resources,
            child=child,
            parent_workspace=parent,
            manifest=repository._manifest_from_row(manifest_row) if manifest_row else None,
            manifest_digest=manifest_row["manifest_digest"] if manifest_row else None,
            original_briefs=briefs,
        )
    return receipt


async def authority_reason(authority, canonical, research, conn):
    return rules.authority_reason(
        authority,
        canonical,
        research,
        await fact(conn, "mission_follow_up_gaps", "gap_id", authority.work.gap_id),
        await fact(conn, "mission_follow_up_parent_budgets", "budget_id", authority.budget_id),
        await fact(conn, "mission_follow_up_assignment_budgets", "binding_id", authority.binding_id),
        datetime.now(timezone.utc),
    )


async def record_fact(repository, command):
    if type(command) is not FollowUpFactCommand:
        raise ValueError("Exact private command required.")
    if command.host_authorized is not True:
        raise ValueError("Unauthorized host.")
    record = command.record
    verifier = getattr(repository, "_follow_up_verifier", None)

    async def write():
        async with connection(repository) as conn:
            try:
                await lock(repository, conn, command.mission_id)
                prior = await original(
                    repository, conn, command.mission_id, "FACT", command.idempotency_key, command.fingerprint
                )
                if prior:
                    await conn.rollback()
                    return prior
                if await revision(conn, command.mission_id) != command.expected_revision:
                    raise ValueError("STALE_REVISION")
                if type(record) is not OperationalGap and (
                    verifier is None or verifier.verify_owner(record.confirmation_ref, digest(record)) is not True
                ):
                    raise ValueError("Explicit owner confirmation unavailable.")
                if type(record) is AssignmentBudget:
                    root = await fact(conn, "mission_follow_up_parent_budgets", "budget_id", record.budget_id)
                    if root is None:
                        raise ValueError("Unknown parent budget.")
                    mission_id = root.mission_id
                elif type(record) is WorkAuthority:
                    mission_id = record.work.inputs.mission_id
                elif type(record) is OperationalGap:
                    mission_id = record.inputs.mission_id
                else:
                    mission_id = record.mission_id
                if mission_id != command.mission_id:
                    raise ValueError("SCOPE_MISMATCH")
                canonical, research = await state(repository, conn, mission_id)
                if type(record) is OperationalGap:
                    reason = input_reason(record.inputs, canonical, research) or origin_reason(record, research)
                    table, key = ("mission_follow_up_gaps", "gap_id")
                    values = (str(record.gap_id), str(mission_id), str(record.parent_work_id), encode(record))
                elif type(record) is ParentBudget:
                    if canonical.manifest is None or canonical.brief is None:
                        raise ValueError("Missing parent authority.")
                    reason = (
                        None
                        if record.manifest_digest == canonical.manifest.manifest_digest
                        and record.brief_digest == compute_frame_fingerprint(canonical.mission, canonical.brief)
                        else "STALE_INPUT_FRAME"
                    )
                    if any(
                        (
                            k not in canonical.manifest.quota_budget or v > canonical.manifest.quota_budget[k]
                            for k, v in record.resources
                        )
                    ):
                        reason = "AUTHORITY_WIDENING"
                    table, key = ("mission_follow_up_parent_budgets", "budget_id")
                    values = (str(record.budget_id), str(mission_id), encode(record))
                elif type(record) is AssignmentBudget:
                    assignment = next(
                        (a for a in research.assignments if a.assignment_id == record.assignment_id), None
                    )
                    reason = (
                        None
                        if assignment
                        and assignment.epoch == record.epoch
                        and (assignment.version == record.assignment_version)
                        and (assignment.authority.quota_ceiling == record.assignment_quota)
                        and (record.quota_unit == root.quota_unit)
                        and (record.cost_ceiling <= root.cost_ceiling)
                        else "AUTHORITY_WIDENING"
                    )
                    table, key = ("mission_follow_up_assignment_budgets", "binding_id")
                    values = (
                        str(record.binding_id),
                        str(mission_id),
                        str(record.budget_id),
                        str(record.assignment_id),
                        record.epoch,
                        encode(record),
                    )
                else:
                    reason = await authority_reason(record, canonical, research, conn)
                    table, key = ("mission_follow_up_authorities", "work_id")
                    values = (
                        str(record.work.work_id),
                        str(mission_id),
                        str(record.work.gap_id),
                        str(record.budget_id),
                        str(record.binding_id),
                        encode(record),
                    )
                if reason:
                    raise ValueError(reason)
                identity = getattr(record, key) if type(record) is not WorkAuthority else record.work.work_id
                existing = await fact(conn, table, key, identity)
                if existing is not None:
                    if existing != record:
                        raise ValueError("Immutable fact conflict.")
                    await conn.rollback()
                    raise ValueError("Immutable fact already has an original command.")
                await conn.execute(f"INSERT INTO {table} VALUES ({','.join(('%s' for _ in values))})", values)
                rev = await advance_revision(conn, mission_id)
                result = ResearchWorkCommitReceipt(
                    disposition="APPLIED",
                    reason_code=None,
                    revision=rev,
                    work_version=None,
                    assignment_version=None,
                    receipt_id=uuid4(),
                    event_ids=(),
                    recorded_at=datetime.now(timezone.utc),
                )
                await persist(
                    conn, mission_id, "FACT", command.idempotency_key, command.fingerprint, identity, result, command
                )
                await conn.commit()
                return result
            except BaseException:
                await conn.rollback()
                raise

    return await await_settled(write())


async def record_work(repository, command):
    if type(command) is not FollowUpWorkCommand:
        raise ValueError("Exact command required.")
    if not command.host_authorized:
        return ResearchWorkCommitReceipt(
            disposition="REFUSED",
            reason_code="UNAUTHORIZED_HOST",
            revision=0,
            work_version=None,
            assignment_version=None,
            receipt_id=uuid4(),
            event_ids=(),
            recorded_at=datetime.now(timezone.utc),
        )

    async def write():
        async with connection(repository) as conn:
            work = command.work
            mission_id = work.inputs.mission_id
            try:
                await lock(repository, conn, mission_id)
                prior = await original(
                    repository, conn, mission_id, "RECORD", command.idempotency_key, command.fingerprint
                )
                if prior:
                    await conn.rollback()
                    return prior
                canonical, research = await state(repository, conn, mission_id)
                authority = await fact(conn, "mission_follow_up_authorities", "work_id", work.work_id)
                reason = "STALE_REVISION" if command.expected_revision != research.revision else None
                if not reason:
                    reason = (
                        "COLLECTION_AUTHORITY_REQUIRED"
                        if authority is None or authority.work != work
                        else await authority_reason(authority, canonical, research, conn)
                    )
                if reason:
                    safe = (
                        reason
                        if reason
                        in {
                            "STALE_REVISION",
                            "STALE_EPOCH",
                            "STALE_VERSION",
                            "AUTHORITY_WIDENING",
                            "AUTHORITY_EXPIRED",
                            "STALE_INPUT_FRAME",
                            "INPUT_IDENTITY_MISMATCH",
                        }
                        else "INVALID_INPUT"
                    )
                    result = ResearchWorkCommitReceipt(
                        disposition="REFUSED",
                        reason_code=safe,
                        revision=research.revision,
                        work_version=None,
                        assignment_version=None,
                        receipt_id=uuid4(),
                        event_ids=(),
                        recorded_at=datetime.now(timezone.utc),
                    )
                else:
                    row = await (
                        await conn.execute(
                            "SELECT input_id FROM research_work_items WHERE work_id=%s", (str(work.work_id),)
                        )
                    ).fetchone()
                    values = (
                        str(work.work_id),
                        str(mission_id),
                        str(work.parent_work_id),
                        str(work.assignment_id),
                        work.research_epoch,
                        work.assignment_version,
                        work.work_version,
                        row[0],
                        str(work.brief_revision_id),
                        str(work.gap_id),
                        json.dumps(work.approved_scope.queries),
                        json.dumps(sorted(work.approved_scope.sources)),
                        json.dumps(work.requested_scope.queries),
                        json.dumps(sorted(work.requested_scope.sources)),
                        work.authority_deadline.isoformat(),
                    )
                    await conn.execute(
                        "INSERT INTO mission_follow_up_work VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        values,
                    )
                    rev = await advance_revision(conn, mission_id)
                    events = ()
                    result = ResearchWorkCommitReceipt(
                        disposition="APPLIED",
                        reason_code=None,
                        revision=rev,
                        work_version=work.work_version,
                        assignment_version=work.assignment_version,
                        receipt_id=uuid4(),
                        event_ids=events,
                        recorded_at=datetime.now(timezone.utc),
                    )
                await persist(
                    conn,
                    mission_id,
                    "RECORD",
                    command.idempotency_key,
                    command.fingerprint,
                    work.work_id,
                    result,
                    command,
                )
                await conn.commit()
                return result
            except BaseException:
                await conn.rollback()
                raise

    return await await_settled(write())


async def commit_admission(repository, command, fingerprint, authority, lease):
    mission_id = command.request.mission_id

    async def write():
        async with connection(repository) as conn:
            try:
                await lock(repository, conn, mission_id)
                prior = await original(
                    repository, conn, mission_id, "ADMIT", command.request.idempotency_key, fingerprint
                )
                if prior:
                    await conn.rollback()
                    return prior
                existing = await (
                    await conn.execute(
                        "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=%s AND operation='ADMIT' AND work_id=%s",
                        (str(mission_id), str(command.request.follow_up_work_id)),
                    )
                ).fetchall()
                for row in existing:
                    try:
                        receipt = await validated_receipt(repository, conn, row, mission_id)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        await conn.rollback()
                        return await refusal(conn, mission_id, "STORAGE_FAILURE")
                    if receipt.disposition == "APPLIED":
                        result = replace(receipt, disposition="EXISTING")
                        await persist(
                            conn,
                            mission_id,
                            "ADMIT",
                            command.request.idempotency_key,
                            fingerprint,
                            command.request.follow_up_work_id,
                            result,
                            command,
                        )
                        await conn.commit()
                        return result
                canonical, research = await state(repository, conn, mission_id)
                live = await fact(conn, "mission_follow_up_authorities", "work_id", command.request.follow_up_work_id)
                if command.expected_revision != research.revision:
                    reason = "STALE_REVISION"
                elif command.request.expected_research_epoch != research.current_epoch:
                    reason = "STALE_EPOCH"
                elif (
                    live is None
                    or not await (
                        await conn.execute(
                            "SELECT 1 FROM mission_follow_up_work WHERE work_id=%s",
                            (str(command.request.follow_up_work_id),),
                        )
                    ).fetchone()
                ):
                    reason = "UNKNOWN_FOLLOW_UP"
                else:
                    reason = await authority_reason(live, canonical, research, conn)
                if not reason:
                    proof = lease.proof if lease else None
                    now = datetime.now(timezone.utc)
                    if (
                        authority != live
                        or type(proof) is not CapabilityProof
                        or (not proof.allowed)
                        or (proof.envelope_digest != live.digest)
                        or (not proof.checked_at <= now < proof.fresh_until)
                        or (proof.sources != live.sources)
                        or (lease.is_current() is not True)
                    ):
                        reason = "SESSION_AUTHORITY_REQUIRED"
                    elif proof.cancel_requested:
                        reason = "CANCEL_REQUESTED"
                    elif proof.stop_reached:
                        reason = "STOP_CONDITION_REACHED"
                    elif proof.quota_unit != live.quota_unit or proof.cost_unit != live.cost_unit:
                        reason = "AUTHORITY_WIDENING"
                    elif proof.quota_required > live.quota or proof.cost_required > live.cost:
                        reason = "AUTHORITY_WIDENING"
                    elif set(dict(proof.resources)) != set(dict(live.resources)) or any(
                        (v > dict(live.resources)[k] for k, v in proof.resources)
                    ):
                        reason = "AUTHORITY_WIDENING"
                if not reason:
                    rows = await (
                        await conn.execute(
                            "SELECT * FROM mission_follow_up_reservations WHERE parent_mission_id=%s",
                            (str(mission_id),),
                        )
                    ).fetchall()
                    used_quota = used_cost = 0
                    used_resources = {}
                    for row in rows:
                        prior_authority = await (
                            await conn.execute(
                                "SELECT a.payload FROM mission_follow_up_authorities a JOIN mission_follow_ups f ON f.work_id=a.work_id WHERE f.follow_up_id=%s",
                                (row["follow_up_id"],),
                            )
                        ).fetchone()
                        allocated = await (
                            await conn.execute(
                                "SELECT resource,allocated FROM mission_follow_up_reservation_resources WHERE reservation_id=%s",
                                (row["reservation_id"],),
                            )
                        ).fetchall()
                        if prior_authority is None or not allocated:
                            reason = "RECONCILIATION_REQUIRED"
                            break
                        past = decode(prior_authority[0])
                        if (
                            dict(allocated) != dict(past.resources)
                            or row["reserved_quota"] != past.quota
                            or row["reserved_cost"] != past.cost
                        ):
                            reason = "RECONCILIATION_REQUIRED"
                            break
                        if (
                            past.budget_id != live.budget_id
                            or past.quota_unit != live.quota_unit
                            or past.cost_unit != live.cost_unit
                        ):
                            reason = "RECONCILIATION_REQUIRED"
                            break
                        used_quota += (
                            row["measured_quota"]
                            if row["state"] == "SETTLED"
                            else max(row["reserved_quota"], row["measured_quota"] or 0)
                        )
                        used_cost += (
                            row["measured_cost"]
                            if row["state"] == "SETTLED"
                            else max(row["reserved_cost"], row["measured_cost"] or 0)
                        )
                        for key, value in allocated:
                            used_resources[key] = used_resources.get(key, 0) + value
                    if not reason and used_quota + live.quota > live.quota_ceiling:
                        reason = "QUOTA_EXHAUSTED"
                    if not reason and used_cost + live.cost > live.cost_ceiling:
                        reason = "COST_EXHAUSTED"
                    root = await fact(conn, "mission_follow_up_parent_budgets", "budget_id", live.budget_id)
                    if not reason and any(
                        (used_resources.get(k, 0) + v > dict(root.resources)[k] for k, v in live.resources)
                    ):
                        reason = "QUOTA_EXHAUSTED"
                    if not reason:
                        reason = rules.unverified_settlement_reason(row["state"] for row in rows)
                if reason:
                    result = await refusal(conn, mission_id, reason)
                else:
                    work = live.work
                    child, brief, manifest = rules.child_records(
                        canonical,
                        live,
                        await repository._next_revision_number(conn.cursor(), canonical.mission.workspace_id),
                        uuid4(),
                        uuid4(),
                    )
                    child_id = child.id
                    await repository._write_mission_row(conn.cursor(), child)
                    await repository._write_brief_revision_row(conn.cursor(), brief)
                    await repository._write_manifest_row(conn.cursor(), manifest)
                    relation = FollowUpRelationship(
                        follow_up_id=uuid4(),
                        work=work,
                        child_mission_id=child_id,
                        child_manifest_digest=manifest.manifest_digest,
                        child_brief_digest=compute_frame_fingerprint(child, brief),
                        reservation_id=uuid4(),
                        idempotency_key=command.request.idempotency_key,
                    )
                    reservation = FollowUpReservation(
                        relationship=relation,
                        reserved_quota=live.quota,
                        reserved_cost=live.cost,
                        state="RESERVED",
                        measured_quota=None,
                        measured_cost=None,
                        measurement_receipt_id=None,
                    )
                    await conn.execute(
                        "INSERT INTO mission_follow_ups VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            str(relation.follow_up_id),
                            str(mission_id),
                            str(child_id),
                            str(work.work_id),
                            str(relation.reservation_id),
                            relation.child_manifest_digest,
                            relation.child_brief_digest,
                            relation.idempotency_key,
                        ),
                    )
                    await conn.execute(
                        "INSERT INTO mission_follow_up_reservations VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            str(relation.reservation_id),
                            str(relation.follow_up_id),
                            str(mission_id),
                            str(child_id),
                            live.quota,
                            live.cost,
                            None,
                            None,
                            None,
                            "RESERVED",
                            1,
                        ),
                    )
                    await conn.cursor().executemany(
                        "INSERT INTO mission_follow_up_reservation_resources VALUES (%s,%s,%s)",
                        [(str(relation.reservation_id), k, v) for k, v in live.resources],
                    )
                    rev = await advance_revision(conn, mission_id)
                    result = FollowUpCommitReceipt(
                        disposition="APPLIED",
                        reason_code=None,
                        revision=rev,
                        receipt_id=uuid4(),
                        recorded_at=datetime.now(timezone.utc),
                        relationship=relation,
                        reservation=reservation,
                    )
                await persist(
                    conn,
                    mission_id,
                    "ADMIT",
                    command.request.idempotency_key,
                    fingerprint,
                    command.request.follow_up_work_id,
                    result,
                    command,
                )
                if lease:
                    final_now = datetime.now(timezone.utc)
                    if (
                        lease.is_current() is not True
                        or not lease.proof.checked_at <= final_now < lease.proof.fresh_until
                    ):
                        await conn.rollback()
                        return await refusal(conn, mission_id, "SESSION_AUTHORITY_REQUIRED")
                    if live is not None and live.work.authority_deadline <= final_now:
                        await conn.rollback()
                        return await refusal(conn, mission_id, "AUTHORITY_EXPIRED")
                    if not reason:
                        current_assignment = next(
                            (a for a in research.assignments if a.assignment_id == live.work.assignment_id)
                        )
                        if current_assignment.authority.deadline <= final_now:
                            await conn.rollback()
                            return await refusal(conn, mission_id, "AUTHORITY_EXPIRED")
                await conn.commit()
                return result
            except psycopg.Error:
                await conn.rollback()
                return await refusal(conn, mission_id, "STORAGE_FAILURE")
            except BaseException:
                await conn.rollback()
                raise

    return await write()


async def load(repository, mission_id):
    async def read():
        try:
            async with connection(repository, readonly=True) as conn:
                return await snapshot(repository, conn, UUID(str(mission_id)))
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError):
            from ignis.domain.exceptions import RepositoryException

            raise RepositoryException("Follow-up storage cannot provide a coherent snapshot.") from None

    return await await_settled(read())


async def recover(repository, conn, command, fingerprint):
    mission_id = command.request.mission_id
    prior = await original(repository, conn, mission_id, "ADMIT", command.request.idempotency_key, fingerprint)
    if prior:
        return prior
    rows = await (
        await conn.execute(
            "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=%s AND operation='ADMIT' AND work_id=%s ORDER BY command_key",
            (str(mission_id), str(command.request.follow_up_work_id)),
        )
    ).fetchall()
    for row in rows:
        receipt = await validated_receipt(repository, conn, row, mission_id)
        if receipt.disposition == "APPLIED":
            result = replace(receipt, disposition="EXISTING")
            await persist(
                conn,
                mission_id,
                "ADMIT",
                command.request.idempotency_key,
                fingerprint,
                command.request.follow_up_work_id,
                result,
                command,
            )
            await conn.commit()
            return result
    return None


async def admit(repository, command):
    if type(command) is not FollowUpAdmissionCommand:
        raise ValueError("Exact command required.")
    caller = asyncio.current_task()

    def require_uncancelled_caller():
        # Settlement shields the worker, so pre-token caller cancellation must be
        # observed explicitly before starting a protected physical mutation.
        if caller is not None and caller.cancelling():
            raise asyncio.CancelledError

    async def settle():
        mission_id = command.request.mission_id
        fingerprint = digest(command)
        try:
            async with connection(repository) as conn:
                if command.host_authorized is not True:
                    return await refusal(conn, mission_id, "UNAUTHORIZED_HOST")
                exists = await (
                    await conn.execute("SELECT to_regclass('public.mission_follow_up_commands')")
                ).fetchone()
                if not exists[0]:
                    return await refusal(conn, mission_id, "UNKNOWN_FOLLOW_UP")
                await lock(repository, conn, mission_id)
                require_uncancelled_caller()
                prior = await recover(repository, conn, command, fingerprint)
                if prior:
                    return prior
                authority = await fact(
                    conn, "mission_follow_up_authorities", "work_id", command.request.follow_up_work_id
                )
            verifier = getattr(repository, "_follow_up_verifier", None)
            require_uncancelled_caller()
            if authority is None or verifier is None:
                return await commit_admission(repository, command, fingerprint, authority, None)
            try:
                async with verifier.hold_current(authority) as lease:
                    require_uncancelled_caller()
                    if not callable(getattr(lease, "async_guard", None)):
                        return await commit_admission(repository, command, fingerprint, authority, None)
                    async with lease.async_guard():
                        require_uncancelled_caller()
                        return await commit_admission(repository, command, fingerprint, authority, lease)
            except (ValueError, RuntimeError, TypeError, AttributeError):
                return await commit_admission(repository, command, fingerprint, authority, None)
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError):
            async with connection(repository, readonly=True) as conn:
                return await refusal(conn, mission_id, "STORAGE_FAILURE")

    return await await_settled(settle())


async def execution_context(repository, mission_id, work_id, *, unresolved=False, request=None):
    """Pinned native context with full original bindings; unresolved retains every allocation."""
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionContext, FollowUpExecutionHistory
    from ignis.domain.exceptions import RepositoryException

    async def operation():
        try:
            async with connection(repository, readonly=not unresolved) as conn:
                if unresolved:
                    # Pin claim/history together before locks or the first MVCC read.
                    await conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    await lock(repository, conn, mission_id)
                canonical, research = await state(repository, conn, mission_id)
                retry_revision, retry_reason = None, None
                if request is not None:
                    retry = await (await conn.execute(
                        "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=%s AND operation='ADMIT' AND command_key=%s",
                        (str(mission_id), sha256(request.idempotency_key.encode()).hexdigest()),
                    )).fetchone()
                    if retry is not None:
                        prior = await validated_receipt(repository, conn, retry, mission_id)
                        submitted, _, _ = rules.command_identity(retry, mission_id)
                        retry_revision = submitted.expected_revision
                        retry_reason = ("IDEMPOTENCY_CONFLICT" if submitted.request != request
                                        else prior.reason_code if prior.disposition == "REFUSED" else None)
                authority = await fact(conn, "mission_follow_up_authorities", "work_id", work_id)
                if authority is not None and authority.work.inputs.mission_id != mission_id:
                    raise ValueError("Execution work belongs to another mission.")
                receipt = None
                rows = await (await conn.execute(
                    "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=%s AND operation='ADMIT'",
                    (str(mission_id),),
                )).fetchall()
                for row in rows:
                    candidate = await validated_receipt(repository, conn, row, mission_id)
                    if (candidate.relationship is not None and candidate.disposition == "APPLIED"
                        and candidate.relationship.work.work_id == work_id):
                        receipt = candidate
                reason = await authority_reason(authority, canonical, research, conn) if authority else "UNKNOWN_FOLLOW_UP"
                candidate = (
                    rules.child_records(canonical, authority, 1, uuid4(), uuid4())
                    if authority and canonical.mission and canonical.manifest and canonical.brief else (None, None, None)
                )
                current = await snapshot(repository, conn, mission_id)
                reservation = next((r for r in current.reservations
                                    if r.relationship == receipt.relationship), None) if receipt else None
                history = None
                if receipt is not None:
                    child_id = receipt.relationship.child_mission_id
                    actual = await repository._commit_snapshot(conn, child_id)
                    rows = await (await conn.execute("SELECT id,workspace_id,mission_id,journal_path,sequence,status,started_at,completed_at FROM mission_run_journals WHERE mission_id=%s", (str(child_id),))).fetchall()
                    claim = await (await conn.execute("SELECT mission_id,run_id,claimed_at FROM mission_writer_claims WHERE mission_id=%s", (str(child_id),))).fetchone()
                    history = FollowUpExecutionHistory.from_rows(actual.mission, rows, claim)
                if unresolved:
                    if receipt is None or reservation is None:
                        raise ValueError("Missing bound original reservation.")
                    if reservation.state == "RESERVED":
                        await conn.execute("UPDATE mission_follow_up_reservations SET state='UNRESOLVED',version=version+1 WHERE reservation_id=%s AND parent_mission_id=%s AND version=%s AND state='RESERVED'", (str(reservation.relationship.reservation_id), str(mission_id), (await (await conn.execute("SELECT version FROM mission_follow_up_reservations WHERE reservation_id=%s", (str(reservation.relationship.reservation_id),))).fetchone())[0]))
                    current = await snapshot(repository, conn, mission_id)
                    reservation = next(r for r in current.reservations if r.relationship == receipt.relationship)
                if authority and not reason:
                    allocations = await (await conn.execute('SELECT r.resource,r.allocated FROM mission_follow_up_reservation_resources r JOIN mission_follow_up_reservations a USING(reservation_id) WHERE a.parent_mission_id=%s', (str(mission_id),))).fetchall()
                    root = await fact(conn, "mission_follow_up_parent_budgets", "budget_id", authority.budget_id)
                    reason = rules.execution_budget_reason(authority, root, current.reservations, allocations,
                                                          admitted=receipt is not None)
                result = FollowUpExecutionContext(authority, canonical, research, receipt, reason, *candidate, reservation, retry_revision, retry_reason, history)
                if unresolved:
                    await conn.commit()
                return result
        except (psycopg.Error, ValueError, KeyError, TypeError, AttributeError):
            raise RepositoryException("Follow-up execution context is unavailable.") from None

    return await await_settled(operation())
