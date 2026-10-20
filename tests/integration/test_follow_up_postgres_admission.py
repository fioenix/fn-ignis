"""T073 actual native PostgreSQL controls; proof providers are synthetic offline doubles."""

from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
import threading
import os
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest
import pytest_asyncio

from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from tests.integration.conftest import SCHEMA_MIGRATIONS, RUNTIME_ROLE, runtime_owner
from tests.integration.test_follow_up_sqlite_admission import OfflineVerifier, ready as sqlite_ready, command


class AsyncVerifier(OfflineVerifier):
    """Shared tokens protect one cross-thread generation; no actual auth/capability proof."""

    def __init__(self):
        super().__init__()
        self.condition = threading.Condition()
        self.tokens = set()
        self.publisher_pending = False
        self.max_tokens = 0
        self.publication_started = threading.Event()

    def acquire(self, expected):
        with self.condition:
            if self.publisher_pending or expected != self.generation:
                raise ValueError("Synthetic generation unavailable.")
            token = object()
            self.tokens.add(token)
            self.max_tokens = max(self.max_tokens, len(self.tokens))
            return token

    def publish(self, *, operational=False):
        with self.condition:
            self.publisher_pending = True
            self.publication_started.set()
            self.condition.wait_for(lambda: not self.tokens)
            if operational:
                self.operational_generation += 1
            else:
                self.generation += 1
            self.publisher_pending = False
            self.condition.notify_all()

    @asynccontextmanager
    async def hold_current(self, request):
        async with super().hold_current(request) as lease:
            verifier = self
            token = None
            expected = self.generation
            expected_operational = self.operational_generation

            @asynccontextmanager
            async def async_guard():
                nonlocal token
                token = self.acquire(expected)
                try:
                    yield lease
                finally:
                    with verifier.condition:
                        verifier.tokens.remove(token)
                        token = None
                        verifier.condition.notify_all()

            def is_current():
                with verifier.condition:
                    return (
                        token in verifier.tokens
                        and expected == verifier.generation
                        and expected_operational == verifier.operational_generation
                    )

            lease.async_guard = async_guard
            lease.is_current = is_current
            yield lease


@pytest.fixture(autouse=True)
def bounded_pg_connections(monkeypatch):
    dsn = os.environ.get("IGNIS_TEST_POSTGRES_DSN")
    if dsn:
        monkeypatch.setenv("IGNIS_TEST_POSTGRES_DSN", make_conninfo(dsn, connect_timeout=5))


@pytest_asyncio.fixture
async def pg_repository(supabase_like_dsn):
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(supabase_like_dsn) as conn:
        for name in (*SCHEMA_MIGRATIONS, "029_mission_follow_up.sql", "030_mission_follow_up_admission.sql"):
            conn.execute((root / "sql" / name).read_text())
    with runtime_owner(supabase_like_dsn) as dsn:
        with psycopg.connect(supabase_like_dsn) as installer:
            for signature in (
                "follow_up_scope_valid(TEXT,BOOLEAN)",
                "validate_follow_up_record()",
                "preserve_follow_up_record()",
                "preserve_follow_up_mission_owner()",
                "preserve_follow_up_admission_history()",
                "validate_follow_up_admission_payload()",
            ):
                installer.execute(
                    sql.SQL("ALTER FUNCTION public." + signature + " OWNER TO {}").format(sql.Identifier(RUNTIME_ROLE))
                )
        repo = PostgresTimescaleRepository(make_conninfo(dsn, connect_timeout=5), min_pool_size=1, max_pool_size=4)
        original = repo.record_follow_up_fact

        async def classified(command):
            try:
                return await original(command)
            except Exception as error:
                cause = error.__context__
                if isinstance(cause, psycopg.Error):
                    import json

                    classifier = Path(".handoff/spec014/t073/native-error-classifier.json")
                    # .handoff/ is gitignored, so a fresh checkout such as CI does not have it yet.
                    classifier.parent.mkdir(parents=True, exist_ok=True)
                    classifier.write_text(
                        json.dumps(
                            {
                                "operation": "record_fact",
                                "record_type": type(command.record).__name__,
                                "error_type": type(cause).__name__,
                                "sqlstate": cause.sqlstate,
                            }
                        )
                        + "\n"
                    )
                raise

        repo.record_follow_up_fact = classified
        try:
            yield repo
        finally:
            await repo.close()


async def ready(repository, tmp_path, **kwargs):
    async def installed():
        pass

    # Only fixture construction is translated; all evidence/research commands hit real PG.
    with (
        patch("tests.integration.test_follow_up_sqlite_admission.SqliteTrendRepository", return_value=repository),
        patch.object(repository, "_ensure_schema", installed, create=True),
    ):
        values = await sqlite_ready(tmp_path, **kwargs)
    verifier = AsyncVerifier()
    repository.configure_follow_up_verifier(verifier)
    return (*values[:4], verifier)


async def counts(repository):
    pool = await repository._get_pool()
    async with pool.connection() as conn:
        values = [
            (await (await conn.execute(f"SELECT count(*) FROM {table}")).fetchone())[0]
            for table in (
                "mission_follow_ups",
                "mission_follow_up_reservations",
                "mission_follow_up_reservation_resources",
            )
        ]
        return tuple(values)


@pytest.mark.asyncio
async def test_native_postgres_admission_retry_parent_and_physical_allocation(pg_repository, tmp_path):
    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    before = await repo.load_mission_evidence_snapshot(mission.id)
    revision = (await repo.load_research_work(mission.id)).revision
    cmd = command(mission, work, revision)
    receipt = await repo.admit_mission_follow_up(cmd)
    assert receipt.disposition == "APPLIED", receipt.reason_code
    assert await counts(repo) == (1, 1, 1)
    assert await repo.admit_mission_follow_up(cmd) == receipt
    alias = await repo.admit_mission_follow_up(replace(cmd, request=replace(cmd.request, idempotency_key="alias")))
    assert alias.disposition == "EXISTING" and alias.relationship == receipt.relationship
    assert verifier.calls == 1
    after = await repo.load_mission_evidence_snapshot(mission.id)
    assert after.mission.status == before.mission.status == "COMPLETED"
    assert after.manifest == before.manifest and after.brief == before.brief and after.signals == before.signals
    assert (await repo.load_mission_follow_ups(mission.id)).relationships == (receipt.relationship,)
    reopened = PostgresTimescaleRepository(repo._dsn, min_pool_size=1, max_pool_size=2)
    try:
        # Retry recovery is durable and needs no newly configured capability provider.
        assert await reopened.admit_mission_follow_up(cmd) == receipt
        assert await counts(reopened) == (1, 1, 1)
        assert (await reopened.load_mission_follow_ups(mission.id)).relationships == (receipt.relationship,)
    finally:
        await reopened.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["absent", "sync_only", "false"])
async def test_postgres_missing_async_capability_refuses_without_child(pg_repository, tmp_path, kind):
    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    if kind == "absent":
        repo.configure_follow_up_verifier(None)
    elif kind == "sync_only":
        repo.configure_follow_up_verifier(OfflineVerifier())
    else:
        verifier.allowed = False
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    result = await repo.admit_mission_follow_up(cmd)
    assert result.reason_code == "SESSION_AUTHORITY_REQUIRED"
    assert await counts(repo) == (0, 0, 0)


@pytest.mark.asyncio
async def test_cancellation_before_async_token_creates_no_child(pg_repository, tmp_path):
    import asyncio

    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    reached, release = asyncio.Event(), asyncio.Event()
    original_hold = verifier.hold_current

    @asynccontextmanager
    async def delayed(request):
        async with original_hold(request) as lease:
            original_guard = lease.async_guard

            @asynccontextmanager
            async def acquire():
                reached.set()
                await release.wait()
                async with original_guard():
                    yield lease

            lease.async_guard = acquire
            yield lease

    verifier.hold_current = delayed
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    pending = asyncio.create_task(repo.admit_mission_follow_up(cmd))
    await asyncio.wait_for(reached.wait(), 20)
    assert not verifier.tokens
    pending.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await counts(repo) == (0, 0, 0)
    assert not verifier.tokens


@pytest.mark.asyncio
async def test_cancellation_during_child_write_keeps_token_until_commit(pg_repository, tmp_path, monkeypatch):
    import asyncio

    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    reached, release = asyncio.Event(), asyncio.Event()
    original = repo._write_manifest_row

    async def pause_after_manifest(cursor, manifest):
        await original(cursor, manifest)
        reached.set()
        await release.wait()

    monkeypatch.setattr(repo, "_write_manifest_row", pause_after_manifest)
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    pending = asyncio.create_task(repo.admit_mission_follow_up(cmd))
    await asyncio.wait_for(reached.wait(), 20)
    assert len(verifier.tokens) == 1
    pending.cancel()
    await asyncio.sleep(0)
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done() and len(verifier.tokens) == 1
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not verifier.tokens
    assert await counts(repo) == (1, 1, 1)
    recovered = await repo.admit_mission_follow_up(cmd)
    assert recovered.disposition == "APPLIED"
    assert verifier.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("same_key", [False, True])
async def test_competing_connections_share_tokens_and_real_pg_lock_wait(pg_repository, tmp_path, monkeypatch, same_key):
    import asyncio
    from ignis.infrastructure.persistence import postgres_follow_up_admission as admission

    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    other = PostgresTimescaleRepository(repo._dsn, min_pool_size=1, max_pool_size=2)
    other.configure_follow_up_verifier(verifier)
    both_tokens, first_locked, release_first = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original_hold, original_lock = verifier.hold_current, admission.lock
    pids, waits = [], []

    @asynccontextmanager
    async def rendezvous(request):
        async with original_hold(request) as lease:
            guard = lease.async_guard

            @asynccontextmanager
            async def together():
                async with guard():
                    if len(verifier.tokens) == 2:
                        both_tokens.set()
                    await asyncio.wait_for(both_tokens.wait(), 20)
                    yield lease

            lease.async_guard = together
            yield lease

    async def contested(repository, conn, mission_id):
        if not both_tokens.is_set():
            return await original_lock(repository, conn, mission_id)
        pid = (await (await conn.execute("SELECT pg_backend_pid()")).fetchone())[0]
        pids.append(pid)
        if len(pids) == 1:
            await original_lock(repository, conn, mission_id)
            first_locked.set()
            await asyncio.wait_for(release_first.wait(), 20)
        else:
            await asyncio.wait_for(first_locked.wait(), 20)
            # An actual server lock wait times out while the other transaction holds
            # the same canonical gate; rollback only this diagnostic savepoint.
            try:
                async with conn.transaction():
                    await conn.execute("SET LOCAL lock_timeout='100ms'")
                    await original_lock(repository, conn, mission_id)
            except psycopg.errors.LockNotAvailable as error:
                waits.append(error.sqlstate)
            finally:
                release_first.set()
            await original_lock(repository, conn, mission_id)

    verifier.hold_current = rendezvous
    monkeypatch.setattr(admission, "lock", contested)
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    try:
        results = await asyncio.wait_for(
            asyncio.gather(
                repo.admit_mission_follow_up(cmd),
                other.admit_mission_follow_up(
                    cmd if same_key else replace(cmd, request=replace(cmd.request, idempotency_key="race-alias"))
                ),
            ),
            40,
        )
        assert sorted(result.disposition for result in results) == (
            ["APPLIED", "APPLIED"] if same_key else ["APPLIED", "EXISTING"]
        )
        assert results[0].relationship == results[1].relationship
        assert len(pids) == len(set(pids)) == 2
        assert waits == ["55P03"] and verifier.max_tokens == 2
        assert not verifier.tokens
        assert await counts(repo) == (1, 1, 1)
    finally:
        release_first.set()
        await other.close()


@pytest.mark.asyncio
async def test_cross_thread_operational_publication_waits_for_pg_commit(pg_repository, tmp_path, monkeypatch):
    import asyncio

    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    reached, release = asyncio.Event(), asyncio.Event()
    original = repo._write_manifest_row

    async def paused(cursor, manifest):
        await original(cursor, manifest)
        reached.set()
        await release.wait()

    monkeypatch.setattr(repo, "_write_manifest_row", paused)
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    admission = asyncio.create_task(repo.admit_mission_follow_up(cmd))
    await asyncio.wait_for(reached.wait(), 20)
    generation = verifier.operational_generation
    publication = asyncio.create_task(asyncio.to_thread(verifier.publish, operational=True))
    try:
        assert await asyncio.to_thread(verifier.publication_started.wait, 5)
        assert not publication.done() and len(verifier.tokens) == 1
        assert verifier.operational_generation == generation
        release.set()
        result = await admission
        await asyncio.wait_for(publication, 5)
        assert result.disposition == "APPLIED"
        assert verifier.operational_generation == generation + 1
        assert not verifier.tokens and await counts(repo) == (1, 1, 1)
    finally:
        release.set()
        await asyncio.gather(admission, publication, return_exceptions=True)


@pytest.mark.asyncio
async def test_late_expiry_and_native_write_failure_roll_back_every_allocation(pg_repository, tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone

    repo, mission, work, _, verifier = await ready(pg_repository, tmp_path)
    original_hold, original_write = verifier.hold_current, repo._write_manifest_row
    held = []

    @asynccontextmanager
    async def capture(request):
        async with original_hold(request) as lease:
            held.append(lease)
            yield lease

    verifier.hold_current = capture
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    before = await repo.load_mission_evidence_snapshot(mission.id)
    revision = (await repo.load_research_work(mission.id)).revision
    for mode, reason in (("expiry", "SESSION_AUTHORITY_REQUIRED"), ("storage", "STORAGE_FAILURE")):

        async def fail_after_manifest(cursor, manifest):
            await original_write(cursor, manifest)
            if mode == "expiry":
                held[-1].proof = replace(held[-1].proof, fresh_until=datetime.now(timezone.utc) - timedelta(seconds=1))
            else:
                raise psycopg.Error("Synthetic isolated write failure.")

        monkeypatch.setattr(repo, "_write_manifest_row", fail_after_manifest)
        result = await repo.admit_mission_follow_up(replace(cmd, request=replace(cmd.request, idempotency_key=mode)))
        assert result.reason_code == reason
        assert await counts(repo) == (0, 0, 0)
        assert (await repo.load_research_work(mission.id)).revision == revision
        assert not verifier.tokens
        after = await repo.load_mission_evidence_snapshot(mission.id)
        assert after.mission == before.mission and after.manifest == before.manifest and after.brief == before.brief


@pytest.mark.asyncio
async def test_all_epoch_partial_usage_and_settlement_keep_original_and_resources(pg_repository, tmp_path):
    from uuid import uuid4
    from tests.integration.test_follow_up_sqlite_admission import sibling

    repo, mission, work, authority, _ = await ready(pg_repository, tmp_path, budget=6, resource_budget=4)
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    first = await repo.admit_mission_follow_up(cmd)
    assert first.disposition == "APPLIED"
    pool = await repo._get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE mission_follow_up_reservations SET state='UNRESOLVED',measured_quota=1,measured_cost=1,version=2 WHERE reservation_id=%s",
            (first.relationship.reservation_id,),
        )
    following, grant = await sibling(repo, mission, work, authority, new_epoch=True)
    second = await repo.admit_mission_follow_up(
        command(mission, following, (await repo.load_research_work(mission.id)).revision, key="epoch-two")
    )
    assert second.disposition == "APPLIED"
    third, _ = await sibling(repo, mission, following, grant)
    revision = (await repo.load_research_work(mission.id)).revision
    denied = await repo.admit_mission_follow_up(command(mission, third, revision, key="partial-usage"))
    assert denied.reason_code == "QUOTA_EXHAUSTED"
    snapshot = await repo.load_mission_follow_ups(mission.id)
    assert {r.relationship.work.research_epoch for r in snapshot.reservations} == {1, 2}
    assert sum(r.encumbered[0] for r in snapshot.reservations) == 4
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE mission_follow_up_reservations SET state='SETTLED',measured_quota=1,measured_cost=1,measurement_receipt_id=%s,version=3 WHERE reservation_id=%s",
            (uuid4(), first.relationship.reservation_id),
        )
    denied = await repo.admit_mission_follow_up(
        command(mission, third, (await repo.load_research_work(mission.id)).revision, key="settled-resources")
    )
    assert denied.reason_code == "QUOTA_EXHAUSTED"
    current = await repo.load_mission_follow_ups(mission.id)
    assert sum(r.encumbered[0] for r in current.reservations) + authority.quota <= 6
    assert sum(r.encumbered[1] for r in current.reservations) + authority.cost <= 6
    assert await repo.admit_mission_follow_up(cmd) == first
    assert await counts(repo) == (2, 2, 2)
    async with pool.connection() as conn:
        assert (
            await (await conn.execute("SELECT sum(allocated) FROM mission_follow_up_reservation_resources")).fetchone()
        )[0] == 4


@pytest.mark.asyncio
async def test_native_history_rejects_two_child_splice_for_key_and_alias(pg_repository, tmp_path):
    from tests.integration.test_follow_up_sqlite_admission import sibling
    from ignis.infrastructure.persistence.follow_up_admission_rules import encode

    repo, mission, work, authority, _ = await ready(pg_repository, tmp_path)
    cmd = command(mission, work, (await repo.load_research_work(mission.id)).revision)
    first = await repo.admit_mission_follow_up(cmd)
    following, _ = await sibling(repo, mission, work, authority)
    second = await repo.admit_mission_follow_up(
        command(mission, following, (await repo.load_research_work(mission.id)).revision, key="second-child")
    )
    assert first.disposition == second.disposition == "APPLIED"
    spliced = replace(second.relationship, work=first.relationship.work)
    forged = replace(first, relationship=spliced, reservation=replace(second.reservation, relationship=spliced))
    pool = await repo._get_pool()
    async with pool.connection() as conn:
        # Corrupt only the disposable fixture; accepted immutable journals stay protected.
        await conn.execute("ALTER TABLE mission_follow_up_commands DISABLE TRIGGER admission_history_immutable")
        await conn.execute(
            "UPDATE mission_follow_up_commands SET receipt_payload=%s WHERE operation='ADMIT' AND work_id=%s",
            (encode(forged), work.work_id),
        )
        await conn.execute("ALTER TABLE mission_follow_up_commands ENABLE TRIGGER admission_history_immutable")
    repo.configure_follow_up_verifier(None)
    for request in (cmd, replace(cmd, request=replace(cmd.request, idempotency_key="splice-alias"))):
        result = await repo.admit_mission_follow_up(request)
        assert result.reason_code == "STORAGE_FAILURE" and result.relationship is None
        assert await counts(repo) == (2, 2, 2)
    async with pool.connection() as conn:
        assert (
            await (
                await conn.execute("SELECT count(*) FROM mission_follow_up_commands WHERE operation='ADMIT'")
            ).fetchone()
        )[0] == 2


@pytest.mark.asyncio
async def test_later_child_evidence_terminal_state_native_recovery(pg_repository, tmp_path, monkeypatch):
    from tests.integration import test_follow_up_sqlite_admission as accepted

    async def actual_pg_ready(path):
        return await ready(pg_repository, path)

    monkeypatch.setattr(accepted, "ready", actual_pg_ready)
    await accepted.test_later_child_evidence_and_terminal_state_preserve_original_recovery(tmp_path)


@pytest.mark.asyncio
async def test_native_registrars_reject_fabricated_units_gaps_and_budget_roots(pg_repository, tmp_path):
    from uuid import uuid4
    from tests.integration.test_follow_up_sqlite_admission import register
    from ignis.domain.follow_up_admission import OperationalGap
    from ignis.domain.exceptions import RepositoryException
    from ignis.infrastructure.persistence.follow_up_admission_rules import decode

    repo, mission, work, authority, verifier = await ready(pg_repository, tmp_path)
    pool = await repo._get_pool()
    async with pool.connection() as conn:
        root = decode(
            (await (await conn.execute("SELECT payload FROM mission_follow_up_parent_budgets")).fetchone())[0]
        )
        binding = decode(
            (await (await conn.execute("SELECT payload FROM mission_follow_up_assignment_budgets")).fetchone())[0]
        )
    candidates = (
        replace(authority, quota_unit="unrelated_unit"),
        replace(authority, work=replace(work, gap_id=uuid4())),
        OperationalGap(
            gap_id=uuid4(),
            parent_work_id=work.parent_work_id,
            inputs=replace(work.inputs, frame_digest="b" * 64),
            question="Bounded operational gap",
        ),
        replace(root, budget_id=uuid4(), quota_ceiling=99),
        replace(binding, binding_id=uuid4(), assignment_quota=99),
    )
    revision = (await repo.load_research_work(mission.id)).revision
    for candidate in candidates:
        expected = RepositoryException if type(candidate) is type(root) else ValueError
        with pytest.raises(expected):
            await register(repo, mission.id, candidate)
        assert await counts(repo) == (0, 0, 0)
        assert (await repo.load_research_work(mission.id)).revision == revision
    verifier.confirmed = False
    with pytest.raises(ValueError, match="Explicit owner confirmation unavailable"):
        await register(repo, mission.id, authority)
    assert await counts(repo) == (0, 0, 0)


@pytest.mark.asyncio
async def test_checked_tiktok_platform_native_child_is_narrow_and_no_activity(pg_repository, tmp_path):
    repo, mission, work, _, _ = await ready(
        pg_repository, tmp_path, source_id="tiktok_video_grid", source_platform="tiktok"
    )
    before = await repo.load_research_work(mission.id)
    result = await repo.admit_mission_follow_up(command(mission, work, before.revision))
    assert result.disposition == "APPLIED"
    child = await repo.get_mission(result.relationship.child_mission_id)
    from ignis.domain.value_objects import PlatformType

    assert child.platforms == [PlatformType.TIKTOK]
    assert child.status == "PENDING" and child.id != mission.id
    after = await repo.load_research_work(mission.id)
    assert after.events == before.events and after.work_items == before.work_items
    assert after.revision == before.revision + 1
    pool = await repo._get_pool()
    async with pool.connection() as conn:
        assert (await (await conn.execute("SELECT count(*) FROM research_activity_receipts")).fetchone())[0] == 0


@pytest.mark.asyncio
async def test_native_missing_or_mismatched_resource_history_refuses_new_sibling(pg_repository, tmp_path):
    from tests.integration.test_follow_up_sqlite_admission import sibling

    repo, mission, work, authority, _ = await ready(pg_repository, tmp_path)
    first = await repo.admit_mission_follow_up(
        command(mission, work, (await repo.load_research_work(mission.id)).revision)
    )
    following, _ = await sibling(repo, mission, work, authority)
    pool = await repo._get_pool()
    for mode in ("mismatch", "missing"):
        async with pool.connection() as conn:
            await conn.execute(
                "ALTER TABLE mission_follow_up_reservation_resources DISABLE TRIGGER admission_history_immutable"
            )
            if mode == "mismatch":
                await conn.execute("UPDATE mission_follow_up_reservation_resources SET allocated=1")
            else:
                await conn.execute("DELETE FROM mission_follow_up_reservation_resources")
            await conn.execute(
                "ALTER TABLE mission_follow_up_reservation_resources ENABLE TRIGGER admission_history_immutable"
            )
        result = await repo.admit_mission_follow_up(
            command(mission, following, (await repo.load_research_work(mission.id)).revision, key=mode)
        )
        assert result.reason_code == "RECONCILIATION_REQUIRED" and result.relationship is None
        assert (await counts(repo))[:2] == (1, 1)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO mission_follow_up_reservation_resources VALUES (%s,'queries',2)",
            (first.relationship.reservation_id,),
        )
    restored = await repo.admit_mission_follow_up(
        command(mission, following, (await repo.load_research_work(mission.id)).revision, key="restored")
    )
    assert restored.disposition == "APPLIED"
