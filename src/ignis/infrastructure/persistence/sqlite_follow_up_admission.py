"""Held SQLite follow-up facts, cumulative admission and immutable retry recovery."""

from ignis.infrastructure.persistence import follow_up_admission_rules as rules
from ignis.infrastructure.persistence.follow_up_admission_rules import encode, decode, input_reason, origin_reason
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from uuid import UUID, uuid4
from pathlib import Path
from ignis.domain.exceptions import RepositoryException

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
from ignis.domain.mission_follow_up import (
    FollowUpWork,
    FollowUpScope,
    FollowUpRelationship,
    FollowUpReservation,
)
from ignis.domain.research_work import ResearchInputBindings
from ignis.domain.research_workspace import compute_frame_fingerprint


def close(repository, conn):
    if repository._mem_conn is None:
        conn.close()


async def install(repository):
    from ignis.infrastructure.persistence.sqlite_follow_up_schema import install_follow_up_schema
    from ignis.infrastructure.persistence.sqlite_follow_up_admission_schema import install_admission_schema

    await repository._ensure_schema()
    await repository._ensure_research_schema()

    def setup():
        conn = repository._get_connection()
        try:
            install_follow_up_schema(conn)
            install_admission_schema(conn)
        finally:
            close(repository, conn)

    await repository._run_write(setup)


def state(repository, conn, mission_id):
    canonical = repository._commit_snapshot(conn, mission_id)
    research = repository._research_snapshot(conn, mission_id, canonical=canonical)
    return canonical, research


def fact(conn, table, key, value):
    row = conn.execute(f"SELECT * FROM {table} WHERE {key}=?", (str(value),)).fetchone()
    if row is None:
        return None
    result = decode(row["payload"])
    parent = UUID(row["parent_mission_id"])
    if type(result) is OperationalGap:
        valid = (
            result.gap_id == UUID(row["gap_id"])
            and result.parent_work_id == UUID(row["parent_work_id"])
            and result.inputs.mission_id == parent
        )
    elif type(result) is ParentBudget:
        valid = result.budget_id == UUID(row["budget_id"]) and result.mission_id == parent
    elif type(result) is AssignmentBudget:
        valid = (
            result.binding_id == UUID(row["binding_id"])
            and result.budget_id == UUID(row["budget_id"])
            and result.assignment_id == UUID(row["assignment_id"])
            and result.epoch == row["epoch"]
        )
    elif type(result) is WorkAuthority:
        valid = (
            result.work.work_id == UUID(row["work_id"])
            and result.work.inputs.mission_id == parent
            and result.work.gap_id == UUID(row["gap_id"])
            and result.budget_id == UUID(row["budget_id"])
            and result.binding_id == UUID(row["binding_id"])
        )
    else:
        valid = False
    if not valid:
        raise ValueError("Persisted admission identity mismatch.")
    return result


def authority_reason(authority, canonical, research, conn):
    return rules.authority_reason(
        authority,
        canonical,
        research,
        fact(conn, "mission_follow_up_gaps", "gap_id", authority.work.gap_id),
        fact(conn, "mission_follow_up_parent_budgets", "budget_id", authority.budget_id),
        fact(conn, "mission_follow_up_assignment_budgets", "binding_id", authority.binding_id),
        datetime.now(timezone.utc),
    )


async def record_fact(repository, command):
    if type(command) is not FollowUpFactCommand:
        raise ValueError("Exact private command required.")
    if command.host_authorized is not True:
        raise ValueError("Unauthorized host.")
    record = command.record
    verifier = getattr(repository, "_follow_up_verifier", None)
    await install(repository)

    def write():
        conn = repository._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            prior = original(repository, conn, command.mission_id, "FACT", command.idempotency_key, command.fingerprint)
            if prior:
                conn.rollback()
                return prior
            if revision(conn, command.mission_id) != command.expected_revision:
                raise ValueError("STALE_REVISION")
            if type(record) is not OperationalGap and (
                verifier is None or verifier.verify_owner(record.confirmation_ref, digest(record)) is not True
            ):
                raise ValueError("Explicit owner confirmation unavailable.")
            if type(record) is AssignmentBudget:
                root = fact(conn, "mission_follow_up_parent_budgets", "budget_id", record.budget_id)
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
            canonical, research = state(repository, conn, mission_id)
            if type(record) is OperationalGap:
                reason = input_reason(record.inputs, canonical, research) or origin_reason(record, research)
                table, key = "mission_follow_up_gaps", "gap_id"
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
                    k not in canonical.manifest.quota_budget or v > canonical.manifest.quota_budget[k]
                    for k, v in record.resources
                ):
                    reason = "AUTHORITY_WIDENING"
                table, key = "mission_follow_up_parent_budgets", "budget_id"
                values = (str(record.budget_id), str(mission_id), encode(record))
            elif type(record) is AssignmentBudget:
                assignment = next((a for a in research.assignments if a.assignment_id == record.assignment_id), None)
                reason = (
                    None
                    if assignment
                    and assignment.epoch == record.epoch
                    and assignment.version == record.assignment_version
                    and assignment.authority.quota_ceiling == record.assignment_quota
                    and record.quota_unit == root.quota_unit
                    and record.cost_ceiling <= root.cost_ceiling
                    else "AUTHORITY_WIDENING"
                )
                table, key = "mission_follow_up_assignment_budgets", "binding_id"
                values = (
                    str(record.binding_id),
                    str(mission_id),
                    str(record.budget_id),
                    str(record.assignment_id),
                    record.epoch,
                    encode(record),
                )
            else:
                reason = authority_reason(record, canonical, research, conn)
                table, key = "mission_follow_up_authorities", "work_id"
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
            existing = fact(conn, table, key, identity)
            if existing is not None:
                if existing != record:
                    raise ValueError("Immutable fact conflict.")
                conn.rollback()
                raise ValueError("Immutable fact already has an original command.")
            conn.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})", values)
            rev = advance_revision(conn, mission_id)
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
            persist(conn, mission_id, "FACT", command.idempotency_key, command.fingerprint, identity, result, command)
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
        finally:
            close(repository, conn)

    return await repository._run_write(write)


def work_from_row(repository, conn, row):
    original = conn.execute(
        "SELECT * FROM research_input_sets WHERE input_id=? AND mission_id=?",
        (row["input_id"], row["parent_mission_id"]),
    ).fetchone()
    owner = conn.execute(
        "SELECT input_id FROM research_work_items WHERE work_id=? AND mission_id=?",
        (row["work_id"], row["parent_mission_id"]),
    ).fetchone()
    if original is None or owner is None or owner[0] != row["input_id"]:
        raise ValueError("Original proposal input ownership mismatch.")
    inputs = ResearchInputBindings(
        mission_id=UUID(row["parent_mission_id"]),
        manifest_digest=original["manifest_digest"],
        brief_digest=original["brief_digest"],
        frame_digest=original["frame_digest"],
        observation_ids=tuple(
            UUID(r[0])
            for r in conn.execute(
                "SELECT observation_id FROM research_input_observations WHERE input_id=? ORDER BY ordinal",
                (row["input_id"],),
            )
        ),
        finding_revisions=tuple(
            (UUID(r[0]), r[1])
            for r in conn.execute(
                "SELECT finding_id,revision FROM research_input_findings WHERE input_id=? ORDER BY ordinal",
                (row["input_id"],),
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
        authority_deadline=datetime.fromisoformat(row["authority_deadline"]),
    )


def snapshot(repository, conn, mission_id):
    revision = conn.execute(
        "SELECT revision FROM mission_progress_revisions WHERE mission_id=?", (str(mission_id),)
    ).fetchone()
    exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='mission_follow_up_work'").fetchone()
    if not exists:
        return FollowUpSnapshot(
            mission_id=mission_id,
            revision=revision[0] if revision else 0,
            work_items=(),
            relationships=(),
            reservations=(),
            results=(),
        )
    works = tuple(
        work_from_row(repository, conn, r)
        for r in conn.execute(
            "SELECT * FROM mission_follow_up_work WHERE parent_mission_id=? ORDER BY work_id", (str(mission_id),)
        )
    )
    indexed = {str(w.work_id): w for w in works}
    links = tuple(
        FollowUpRelationship(
            follow_up_id=UUID(r["follow_up_id"]),
            work=indexed[r["work_id"]],
            child_mission_id=UUID(r["child_mission_id"]),
            child_manifest_digest=r["child_manifest_digest"],
            child_brief_digest=r["child_brief_digest"],
            reservation_id=UUID(r["reservation_id"]),
            idempotency_key=r["idempotency_key"],
        )
        for r in conn.execute(
            "SELECT * FROM mission_follow_ups WHERE parent_mission_id=? ORDER BY follow_up_id", (str(mission_id),)
        )
    )
    links_by_id = {str(r.follow_up_id): r for r in links}
    reservations = tuple(
        FollowUpReservation(
            relationship=links_by_id[r["follow_up_id"]],
            reserved_quota=r["reserved_quota"],
            reserved_cost=r["reserved_cost"],
            state=r["state"],
            measured_quota=r["measured_quota"],
            measured_cost=r["measured_cost"],
            measurement_receipt_id=UUID(r["measurement_receipt_id"]) if r["measurement_receipt_id"] else None,
        )
        for r in conn.execute(
            "SELECT * FROM mission_follow_up_reservations WHERE parent_mission_id=? ORDER BY reservation_id",
            (str(mission_id),),
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


async def load(repository, mission_id):
    mission_id = UUID(str(mission_id))

    def read():
        if repository._mem_conn is None:
            try:
                conn = sqlite3.connect(
                    Path(repository._db_path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False
                )
                conn.row_factory = sqlite3.Row
            except sqlite3.DatabaseError:
                raise RepositoryException("Follow-up storage is unavailable.") from None
        else:
            conn = repository._mem_conn
        try:
            conn.execute("BEGIN")
            result = snapshot(repository, conn, mission_id)
            conn.rollback()
            return result
        except (sqlite3.DatabaseError, ValueError, KeyError, TypeError):
            conn.rollback()
            raise RepositoryException("Follow-up storage cannot provide a coherent snapshot.") from None
        finally:
            close(repository, conn)

    return await repository._run_write(read)


def revision(conn, mission_id):
    row = conn.execute(
        "SELECT revision FROM mission_progress_revisions WHERE mission_id=?", (str(mission_id),)
    ).fetchone()
    return row[0] if row else 0


def advance_revision(conn, mission_id):
    # Dedicated immutable follow-up receipts are operational facts, not activity heartbeats.
    conn.execute(
        "INSERT INTO mission_progress_revisions VALUES (?,1) ON CONFLICT(mission_id) DO UPDATE SET revision=revision+1",
        (str(mission_id),),
    )
    return revision(conn, mission_id)


def refusal(conn, mission_id, reason):
    return FollowUpCommitReceipt(
        disposition="REFUSED",
        reason_code=reason,
        revision=revision(conn, mission_id),
        receipt_id=uuid4(),
        recorded_at=datetime.now(timezone.utc),
        relationship=None,
        reservation=None,
    )


def validated_receipt(repository, conn, row, mission_id):
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
        if fact(conn, table, key, work) != record:
            raise ValueError("Original fact is detached from recording.")
    if type(stored) is FollowUpWorkCommand and receipt.disposition == "APPLIED":
        proposal = conn.execute(
            "SELECT * FROM mission_follow_up_work WHERE work_id=? AND parent_mission_id=?", (str(work), str(mission_id))
        ).fetchone()
        if proposal is None or work_from_row(repository, conn, proposal) != stored.work:
            raise ValueError("Original proposal identity mismatch.")
    if type(receipt) is FollowUpCommitReceipt and receipt.relationship:
        r = receipt.relationship
        physical = conn.execute(
            "SELECT * FROM mission_follow_ups WHERE follow_up_id=?", (str(r.follow_up_id),)
        ).fetchone()
        proposal = conn.execute(
            "SELECT * FROM mission_follow_up_work WHERE work_id=? AND parent_mission_id=?", (str(work), str(mission_id))
        ).fetchone()
        envelope = fact(conn, "mission_follow_up_authorities", "work_id", work)
        root = fact(conn, "mission_follow_up_parent_budgets", "budget_id", envelope.budget_id) if envelope else None
        binding = (
            fact(conn, "mission_follow_up_assignment_budgets", "binding_id", envelope.binding_id) if envelope else None
        )
        allocation = conn.execute(
            "SELECT * FROM mission_follow_up_reservations WHERE reservation_id=?", (str(r.reservation_id),)
        ).fetchone()
        resources = conn.execute(
            "SELECT resource,allocated FROM mission_follow_up_reservation_resources WHERE reservation_id=?",
            (str(r.reservation_id),),
        ).fetchall()
        child = conn.execute(
            "SELECT workspace_id,surface FROM research_missions WHERE id=?", (str(r.child_mission_id),)
        ).fetchone()
        parent = conn.execute("SELECT workspace_id FROM research_missions WHERE id=?", (str(mission_id),)).fetchone()
        manifest_row = conn.execute(
            "SELECT * FROM mission_manifests WHERE mission_id=?", (str(r.child_mission_id),)
        ).fetchone()
        briefs = [
            repository._brief_from_row(b)
            for b in conn.execute(repository._BRIEF_COLUMNS + " WHERE mission_id=?", (str(r.child_mission_id),))
        ]
        rules.recovery_binding(
            receipt,
            mission_id,
            work,
            physical=physical,
            proposal=work_from_row(repository, conn, proposal) if proposal else None,
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


def original(repository, conn, mission_id, operation, key, fingerprint):
    row = conn.execute(
        "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=? AND operation=? AND command_key=?",
        (str(mission_id), operation, sha256(key.encode()).hexdigest()),
    ).fetchone()
    if row is None:
        return None
    try:
        receipt = validated_receipt(repository, conn, row, mission_id)
    except (ValueError, KeyError, TypeError, AttributeError):
        return refusal(conn, mission_id, "STORAGE_FAILURE")
    if row["fingerprint"] == fingerprint:
        return receipt
    if operation == "ADMIT":
        return refusal(conn, mission_id, "IDEMPOTENCY_CONFLICT")
    return ResearchWorkCommitReceipt(
        disposition="REFUSED",
        reason_code="IDEMPOTENCY_CONFLICT",
        revision=revision(conn, mission_id),
        work_version=None,
        assignment_version=None,
        receipt_id=uuid4(),
        event_ids=(),
        recorded_at=datetime.now(timezone.utc),
    )


def persist(conn, mission_id, operation, key, fingerprint, work_id, receipt, command):
    conn.execute(
        "INSERT INTO mission_follow_up_commands VALUES (?,?,?,?,?,?,?)",
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
    await install(repository)

    def write():
        conn = repository._get_connection()
        work = command.work
        mission_id = work.inputs.mission_id
        try:
            conn.execute("BEGIN IMMEDIATE")
            prior = original(repository, conn, mission_id, "RECORD", command.idempotency_key, command.fingerprint)
            if prior:
                conn.rollback()
                return prior
            canonical, research = state(repository, conn, mission_id)
            authority = fact(conn, "mission_follow_up_authorities", "work_id", work.work_id)
            reason = "STALE_REVISION" if command.expected_revision != research.revision else None
            if not reason:
                reason = (
                    "COLLECTION_AUTHORITY_REQUIRED"
                    if authority is None or authority.work != work
                    else authority_reason(authority, canonical, research, conn)
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
                row = conn.execute(
                    "SELECT input_id FROM research_work_items WHERE work_id=?", (str(work.work_id),)
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
                conn.execute("INSERT INTO mission_follow_up_work VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                rev = advance_revision(conn, mission_id)
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
            persist(
                conn, mission_id, "RECORD", command.idempotency_key, command.fingerprint, work.work_id, result, command
            )
            conn.commit()
            return result
        except BaseException:
            conn.rollback()
            raise
        finally:
            close(repository, conn)

    return await repository._run_write(write)


async def admit(repository, command):
    if type(command) is not FollowUpAdmissionCommand:
        raise ValueError("Exact command required.")
    mission_id = command.request.mission_id
    fingerprint = digest(command)

    def inspect():
        conn = repository._get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE")
            if not command.host_authorized:
                return refusal(conn, mission_id, "UNAUTHORIZED_HOST"), None
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE name='mission_follow_up_commands'").fetchone()
            if not exists:
                return refusal(conn, mission_id, "UNKNOWN_FOLLOW_UP"), None
            prior = original(repository, conn, mission_id, "ADMIT", command.request.idempotency_key, fingerprint)
            if prior:
                return prior, None
            prior_row = conn.execute(
                "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=? AND operation='ADMIT' AND work_id=? ORDER BY rowid",
                (str(mission_id), str(command.request.follow_up_work_id)),
            ).fetchall()
            for r in prior_row:
                try:
                    receipt = validated_receipt(repository, conn, r, mission_id)
                except (ValueError, KeyError, TypeError, AttributeError):
                    return refusal(conn, mission_id, "STORAGE_FAILURE"), None
                if receipt.disposition == "APPLIED":
                    result = replace(receipt, disposition="EXISTING")
                    persist(
                        conn,
                        mission_id,
                        "ADMIT",
                        command.request.idempotency_key,
                        fingerprint,
                        command.request.follow_up_work_id,
                        result,
                        command,
                    )
                    conn.commit()
                    return result, None
            return None, fact(conn, "mission_follow_up_authorities", "work_id", command.request.follow_up_work_id)
        except (ValueError, KeyError, TypeError, AttributeError):
            return refusal(conn, mission_id, "STORAGE_FAILURE"), None
        finally:
            conn.rollback()
            close(repository, conn)

    prior, authority = await repository._run_write(inspect)
    if prior:
        return prior
    verifier = getattr(repository, "_follow_up_verifier", None)
    if authority is None or verifier is None:
        return await commit_admission(repository, command, fingerprint, None, None)
    try:
        async with verifier.hold_current(authority) as lease:
            return await commit_admission(repository, command, fingerprint, authority, lease)
    except (ValueError, RuntimeError, AttributeError, TypeError):
        return await commit_admission(repository, command, fingerprint, authority, None)


async def commit_admission(repository, command, fingerprint, authority, lease):
    mission_id = command.request.mission_id

    def write():
        conn = repository._get_connection()
        try:
            # Hold the provider guard before SQLite: provider implementations never acquire database locks.
            with lease.guard() if lease else nullcontext():
                conn.execute("BEGIN IMMEDIATE")
                prior = original(repository, conn, mission_id, "ADMIT", command.request.idempotency_key, fingerprint)
                if prior:
                    conn.rollback()
                    return prior
                existing = conn.execute(
                    "SELECT * FROM mission_follow_up_commands WHERE parent_mission_id=? AND operation='ADMIT' AND work_id=?",
                    (str(mission_id), str(command.request.follow_up_work_id)),
                ).fetchall()
                for row in existing:
                    try:
                        receipt = validated_receipt(repository, conn, row, mission_id)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        conn.rollback()
                        return refusal(conn, mission_id, "STORAGE_FAILURE")
                    if receipt.disposition == "APPLIED":
                        result = replace(receipt, disposition="EXISTING")
                        persist(
                            conn,
                            mission_id,
                            "ADMIT",
                            command.request.idempotency_key,
                            fingerprint,
                            command.request.follow_up_work_id,
                            result,
                            command,
                        )
                        conn.commit()
                        return result
                canonical, research = state(repository, conn, mission_id)
                live = fact(conn, "mission_follow_up_authorities", "work_id", command.request.follow_up_work_id)
                if command.expected_revision != research.revision:
                    reason = "STALE_REVISION"
                elif command.request.expected_research_epoch != research.current_epoch:
                    reason = "STALE_EPOCH"
                elif (
                    live is None
                    or not conn.execute(
                        "SELECT 1 FROM mission_follow_up_work WHERE work_id=?",
                        (str(command.request.follow_up_work_id),),
                    ).fetchone()
                ):
                    reason = "UNKNOWN_FOLLOW_UP"
                else:
                    reason = authority_reason(live, canonical, research, conn)
                if not reason:
                    proof = lease.proof if lease else None
                    now = datetime.now(timezone.utc)
                    if (
                        authority != live
                        or type(proof) is not CapabilityProof
                        or not proof.allowed
                        or proof.envelope_digest != live.digest
                        or not proof.checked_at <= now < proof.fresh_until
                        or proof.sources != live.sources
                        or lease.is_current() is not True
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
                        v > dict(live.resources)[k] for k, v in proof.resources
                    ):
                        reason = "AUTHORITY_WIDENING"
                if not reason:
                    rows = conn.execute(
                        "SELECT * FROM mission_follow_up_reservations WHERE parent_mission_id=?", (str(mission_id),)
                    ).fetchall()
                    used_quota = used_cost = 0
                    used_resources = {}
                    for row in rows:
                        prior_authority = conn.execute(
                            "SELECT a.payload FROM mission_follow_up_authorities a JOIN mission_follow_ups f ON f.work_id=a.work_id WHERE f.follow_up_id=?",
                            (row["follow_up_id"],),
                        ).fetchone()
                        allocated = conn.execute(
                            "SELECT resource,allocated FROM mission_follow_up_reservation_resources WHERE reservation_id=?",
                            (row["reservation_id"],),
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
                    root = fact(conn, "mission_follow_up_parent_budgets", "budget_id", live.budget_id)
                    if not reason and any(
                        used_resources.get(k, 0) + v > dict(root.resources)[k] for k, v in live.resources
                    ):
                        reason = "QUOTA_EXHAUSTED"
                if reason:
                    result = refusal(conn, mission_id, reason)
                else:
                    work = live.work
                    child, brief, manifest = rules.child_records(
                        canonical,
                        live,
                        repository._next_revision_number(conn, canonical.mission.workspace_id),
                        uuid4(),
                        uuid4(),
                    )
                    child_id = child.id
                    repository._write_mission_row(conn.cursor(), child)
                    repository._write_brief_revision_row(conn.cursor(), brief)
                    repository._write_manifest_row(conn.cursor(), manifest)
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
                    conn.execute(
                        "INSERT INTO mission_follow_ups VALUES (?,?,?,?,?,?,?,?)",
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
                    conn.execute(
                        "INSERT INTO mission_follow_up_reservations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
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
                    conn.executemany(
                        "INSERT INTO mission_follow_up_reservation_resources VALUES (?,?,?)",
                        [(str(relation.reservation_id), k, v) for k, v in live.resources],
                    )
                    rev = advance_revision(conn, mission_id)
                    result = FollowUpCommitReceipt(
                        disposition="APPLIED",
                        reason_code=None,
                        revision=rev,
                        receipt_id=uuid4(),
                        recorded_at=datetime.now(timezone.utc),
                        relationship=relation,
                        reservation=reservation,
                    )
                persist(
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
                        conn.rollback()
                        return refusal(conn, mission_id, "SESSION_AUTHORITY_REQUIRED")
                    if live is not None and live.work.authority_deadline <= final_now:
                        conn.rollback()
                        return refusal(conn, mission_id, "AUTHORITY_EXPIRED")
                    if not reason:
                        current_assignment = next(
                            a for a in research.assignments if a.assignment_id == live.work.assignment_id
                        )
                        if current_assignment.authority.deadline <= final_now:
                            conn.rollback()
                            return refusal(conn, mission_id, "AUTHORITY_EXPIRED")
                conn.commit()
                return result
        except sqlite3.DatabaseError:
            conn.rollback()
            return refusal(conn, mission_id, "STORAGE_FAILURE")
        except BaseException:
            conn.rollback()
            raise
        finally:
            close(repository, conn)

    return await repository._run_write(write)
