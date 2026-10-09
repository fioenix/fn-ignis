"""Typed physical T068 setup; no real social authorization or credentials."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from tests.unit.test_mission_claims import _eligible_mission
from tests.integration.test_follow_up_sqlite_admission import register, OfflineVerifier

async def bind_plan(repository, mission, authority, executor, factory):
    from ignis.application.ports.follow_up_execution_port import FollowUpExecutionContext
    from ignis.infrastructure.persistence.follow_up_admission_rules import child_records
    from ignis.infrastructure.persistence.workspace_repository import WorkspaceRepository
    canonical = await WorkspaceRepository(repository).load_mission_evidence_snapshot(mission.id)
    candidate = child_records(canonical, authority, 1, uuid4(), uuid4())
    context = FollowUpExecutionContext(authority, canonical, await repository.load_research_work(mission.id), None, None, *candidate)
    service = factory(repository, executor, selected_parent_id=mission.id, host_authorized=True)
    plan, _ = await service._plan(context)
    return replace(authority, sources=tuple(replace(s, plan_digest=plan.digest) for s in authority.sources))

async def ready(repository, tmp_path, executor, factory, *, budget=4, cost_budget=4, resource_budget=20):
    source_id, source_platform = "youtube", "youtube"
    from ignis.domain.follow_up_admission import (
        OperationalGap,
        ParentBudget,
        AssignmentBudget,
        SourceGrant,
        WorkAuthority,
    )
    from ignis.domain.research_work import (
        ResearchAssignment,
        ResearchAuthority,
        ResearchInputBindings,
        ResearchWorkItem,
    )
    from ignis.domain.mission_follow_up import FollowUpWork, FollowUpScope
    from ignis.application.ports.research_work_port import (
        ResearchWorkCommitCommand,
        ResearchAssignmentAdmission,
        FollowUpWorkCommand,
    )
    from ignis.domain.research_workspace import compute_frame_fingerprint

    from unittest.mock import patch
    from tests.unit.test_mission_claims import _manifest

    original_outcomes = repository.record_probe_outcomes

    async def record_outcomes(run_id, outcomes):
        if source_id != "youtube":
            outcomes = [
                *outcomes,
                replace(
                    outcomes[0],
                    connector_surface=source_id,
                    platform="tiktok",
                    status="EMPTY_NO_DATA",
                    note="Synthetic offline empty query",
                    outcome_id=uuid4(),
                    signals_collected=0,
                ),
            ]
        return await original_outcomes(run_id, outcomes)

    with (
        patch(
            "tests.unit.test_mission_claims._manifest",
            return_value=replace(
                _manifest(),
                required_channels=tuple(sorted({"google", "youtube", source_id})),
                quota_budget={"queries": 20, "youtube_search_calls": 20},
            ),
        ),
        patch.object(repository, "record_probe_outcomes", record_outcomes),
    ):
        _, store, mission, _, frame = await _eligible_mission(tmp_path, repository=repository)
    evidence = await store.load_mission_evidence_snapshot(mission.id)
    inputs = ResearchInputBindings(
        mission_id=mission.id,
        manifest_digest=evidence.manifest.manifest_digest,
        brief_digest=compute_frame_fingerprint(mission, evidence.brief),
        frame_digest=frame.frame_digest,
        observation_ids=tuple(sorted((s.observation_id for s in evidence.signals), key=str)),
        finding_revisions=(),
    )
    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    assignment = ResearchAssignment(
        assignment_id=uuid4(),
        mission_id=mission.id,
        host_task_ref="offline",
        epoch=1,
        authority=ResearchAuthority(
            actions=frozenset({"ANALYZE", "FOLLOW_UP"}),
            sources=frozenset({source_id}),
            deadline=deadline,
            quota_ceiling=budget,
        ),
        capability="SEQUENTIAL",
        state="ASSIGNED",
        version=1,
    )
    revision = (await repository.load_research_work(mission.id)).revision

    async def commit(operation, payload):
        nonlocal revision
        r = await repository.commit_research_work(
            ResearchWorkCommitCommand(
                mission_id=mission.id,
                operation=operation,
                payload=payload,
                expected_revision=revision,
                expected_epoch=1,
                idempotency_key=uuid4().hex,
                host_authorized=True,
            )
        )
        assert r.disposition == "APPLIED", r
        revision = r.revision

    await commit(
        "ASSIGN_RESEARCH",
        ResearchAssignmentAdmission(
            assignment=assignment,
            expected_manifest_digest=inputs.manifest_digest,
            expected_brief_revision_id=evidence.brief.brief_revision_id,
        ),
    )
    parent = ResearchWorkItem(
        work_id=uuid4(),
        assignment_id=assignment.assignment_id,
        mission_id=mission.id,
        run_id=None,
        question="Bounded operational gap",
        expertise="Synthesis",
        assignee_ref="offline",
        inputs=inputs,
        dependencies=(),
        epoch=1,
        state="ASSIGNED",
        version=1,
        ownership_fence="offline",
    )
    await commit("ASSIGN_WORK", parent)
    child = replace(parent, work_id=uuid4())
    await commit("ASSIGN_WORK", child)
    mission.status = "COMPLETED"
    await repository.update_mission(mission)
    verifier = OfflineVerifier()
    repository.configure_follow_up_verifier(verifier)
    gap = OperationalGap(gap_id=uuid4(), parent_work_id=parent.work_id, inputs=inputs, question=parent.question)
    root = ParentBudget(
        budget_id=uuid4(),
        mission_id=mission.id,
        manifest_digest=inputs.manifest_digest,
        brief_digest=inputs.brief_digest,
        quota_unit="query",
        cost_unit="offline_unit",
        quota_ceiling=budget,
        cost_ceiling=cost_budget,
        resources=(("queries", resource_budget), ("youtube_search_calls", resource_budget)),
        confirmation_ref="synthetic-owner-confirmation",
    )
    binding = AssignmentBudget(
        binding_id=uuid4(),
        budget_id=root.budget_id,
        assignment_id=assignment.assignment_id,
        epoch=1,
        assignment_version=1,
        assignment_quota=budget,
        quota_unit=root.quota_unit,
        cost_ceiling=cost_budget,
        confirmation_ref=root.confirmation_ref,
    )
    scope = FollowUpScope(queries=("retail stockout", *evidence.brief.falsifiers), sources=frozenset({source_id}))
    follow = FollowUpWork(
        work_id=child.work_id,
        parent_work_id=parent.work_id,
        assignment_id=assignment.assignment_id,
        gap_id=gap.gap_id,
        inputs=inputs,
        research_epoch=1,
        assignment_version=1,
        work_version=1,
        brief_revision_id=evidence.brief.brief_revision_id,
        approved_scope=scope,
        requested_scope=scope,
        authority_deadline=deadline,
    )
    source = SourceGrant(
        source=source_id,
        platform=source_platform,
        tier="public_http",
        paid=False,
        plan_digest="a" * 64,
        connector_revision="offline-v1",
        capability_id="offline-public",
        capability_epoch=1,
    )
    authority = WorkAuthority(
        work=follow,
        budget_id=root.budget_id,
        binding_id=binding.binding_id,
        quota_unit=root.quota_unit,
        cost_unit=root.cost_unit,
        quota=2,
        cost=2,
        quota_ceiling=budget,
        cost_ceiling=cost_budget,
        resources=(("queries", 2), ("youtube_search_calls", 2)),
        sources=(source,),
        confirmation_ref=root.confirmation_ref,
    )
    authority = await bind_plan(repository, mission, authority, executor, factory)
    for record in (gap, root, binding, authority):
        receipt = await register(repository, mission.id, record)
        assert receipt.disposition == "APPLIED", receipt
    revision = (await repository.load_research_work(mission.id)).revision
    receipt = await repository.record_follow_up_work(
        FollowUpWorkCommand(work=follow, expected_revision=revision, idempotency_key="record", host_authorized=True)
    )
    assert receipt.disposition == "APPLIED"
    return repository, mission, follow, authority, verifier



def corrupt_disposable(case, statements):
    """Explicit historical negative fixture; restore every physical guard before execution.

    The accepted typed registrar first persisted valid history. These scoped SQL
    mutations model invalid legacy rows. They never grant runtime/session proof.
    """
    import psycopg
    from psycopg import sql
    if case.name == "postgres":
        legacy = []
        with psycopg.connect(case.dsn) as conn:
            tables = sorted({table for table, _, _ in statements})
            guards = conn.execute(
                "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relnamespace='public'::regnamespace "
                "AND c.relname=ANY(%s) ORDER BY c.relname,t.tgname", (tables,)).fetchall()
            for table, _, parameters in statements:
                if table == "research_assignments" and parameters[0] == ["READ"]:
                    constraints = conn.execute(
                        "SELECT conname,pg_get_constraintdef(oid),convalidated FROM pg_constraint "
                        "WHERE conrelid='public.research_assignments'::regclass AND contype='c' "
                        "AND pg_get_constraintdef(oid) LIKE '%%actions%%'").fetchall()
                    assert len(constraints) == 1 and constraints[0][2] is True
                    original = conn.execute("SELECT actions FROM research_assignments WHERE assignment_id=%s",
                                            (parameters[1],)).fetchone()[0]
                    name, definition, _ = constraints[0]
                    legacy.append((name, definition, parameters[1], original))
                    conn.execute(sql.SQL("ALTER TABLE research_assignments DROP CONSTRAINT {}").format(
                        sql.Identifier(name)))
            for table in tables:
                conn.execute(sql.SQL("ALTER TABLE {} DISABLE TRIGGER USER").format(sql.Identifier(table)))
            try:
                for _, query, parameters in statements:
                    conn.execute(query.replace("?", "%s"), parameters)
            finally:
                for name, definition, _, _ in legacy:
                    from pathlib import Path
                    # Reparse the authoritative BETWEEN source, not its lossy
                    # deparsed AND form; the latter flattens the original AST.
                    migration = Path(__file__).resolve().parents[2] / "sql/028_research_work.sql"
                    clauses = [line.strip() for line in migration.read_text().splitlines()
                               if line.strip().startswith("actions TEXT[]")]
                    assert len(clauses) == 1
                    original_check = clauses[0][clauses[0].index("CHECK ("):].rstrip(",")
                    conn.execute(sql.SQL("ALTER TABLE research_assignments ADD CONSTRAINT {} ").format(
                        sql.Identifier(name)) + sql.SQL(original_check + " NOT VALID"))
                    restored_check = conn.execute(
                        "SELECT pg_get_constraintdef(oid),convalidated FROM pg_constraint "
                        "WHERE conrelid='public.research_assignments'::regclass AND conname=%s", (name,)).fetchone()
                    assert restored_check == (definition + " NOT VALID", False)

                for table, name, enabled, _ in guards:
                    mode = {"O": "ENABLE", "D": "DISABLE", "R": "ENABLE REPLICA", "A": "ENABLE ALWAYS"}[enabled]
                    conn.execute(sql.SQL("ALTER TABLE {} " + mode + " TRIGGER {}").format(
                        sql.Identifier(table), sql.Identifier(name)))
            restored = conn.execute(
                "SELECT c.relname,t.tgname,t.tgenabled,pg_get_triggerdef(t.oid) "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "WHERE NOT t.tgisinternal AND c.relnamespace='public'::regnamespace "
                "AND c.relname=ANY(%s) ORDER BY c.relname,t.tgname", (tables,)).fetchall()
            assert restored == guards
            for name, definition, assignment, original in legacy:
                # Exercise the restored CHECK independently of writer triggers.
                conn.execute("SAVEPOINT future_illegal_action")
                try:
                    conn.execute("ALTER TABLE research_assignments DISABLE TRIGGER USER")
                    conn.execute("UPDATE research_assignments SET actions=%s WHERE assignment_id=%s",
                                 (["READ"], assignment))
                except psycopg.errors.CheckViolation:
                    conn.execute("ROLLBACK TO SAVEPOINT future_illegal_action")
                else:
                    raise AssertionError("Restored historical actions CHECK admitted a future illegal write")
                conn.execute("RELEASE SAVEPOINT future_illegal_action")
        case._legacy_actions_cleanup = legacy
    else:
        repository = case.repository
        conn = repository._get_connection()
        tables = sorted({table for table, _, _ in statements})
        guards = []
        assert not conn.in_transaction, "Negative fixture must own its disposable transaction"
        try:
            conn.execute("BEGIN")
            for table in tables:
                guards += conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()
            for name, _ in guards:
                conn.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
            try:
                for _, query, parameters in statements:
                    conn.execute(query, parameters)
            finally:
                for _, definition in guards:
                    conn.execute(definition)
            restored = []
            for table in tables:
                restored += conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()
            assert sorted(map(tuple, restored)) == sorted(map(tuple, guards))
            conn.commit()
        except BaseException:
            conn.rollback()
            restored = []
            for table in tables:
                restored += conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchall()
            assert sorted(map(tuple, restored)) == sorted(map(tuple, guards))
            raise
        finally:
            if conn is not repository._mem_conn:
                conn.close()


async def sibling(repository, mission, authority):
    """One real sibling work and gap retains the exact stable parent budget."""
    from ignis.domain.follow_up_admission import OperationalGap
    from ignis.application.ports.research_work_port import ResearchWorkCommitCommand, FollowUpWorkCommand
    state = await repository.load_research_work(mission.id)
    old = authority.work
    source = next(w for w in state.work_items if w.work_id == old.work_id)
    new_work = replace(source, work_id=uuid4(), state="ASSIGNED", version=1)
    receipt = await repository.commit_research_work(ResearchWorkCommitCommand(
        mission_id=mission.id, operation="ASSIGN_WORK", payload=new_work,
        expected_revision=state.revision, expected_epoch=old.research_epoch,
        idempotency_key=uuid4().hex, host_authorized=True))
    assert receipt.disposition == "APPLIED", receipt
    following = replace(old, work_id=new_work.work_id, gap_id=uuid4(), work_version=1)
    parent_work = next(w for w in state.work_items if w.work_id == old.parent_work_id)
    gap = OperationalGap(gap_id=following.gap_id, parent_work_id=old.parent_work_id,
                         inputs=old.inputs, question=parent_work.question)
    grant = replace(authority, work=following)
    for record in (gap, grant):
        receipt = await register(repository, mission.id, record)
        assert receipt.disposition == "APPLIED", receipt
    receipt = await repository.record_follow_up_work(FollowUpWorkCommand(
        work=following, expected_revision=(await repository.load_research_work(mission.id)).revision,
        idempotency_key=uuid4().hex, host_authorized=True))
    assert receipt.disposition == "APPLIED", receipt
    return following


from contextlib import asynccontextmanager

@asynccontextmanager
async def postgres_case(case):
    """Install accepted follow-up schemas and transfer exact ownership; no broad grants."""
    from pathlib import Path
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    from tests.integration.conftest import runtime_owner, RUNTIME_ROLE, RepositoryCase
    from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
    root = Path(__file__).resolve().parents[2]
    with psycopg.connect(case.dsn) as installer:
        for name in ("029_mission_follow_up.sql", "030_mission_follow_up_admission.sql"):
            installer.execute((root / "sql" / name).read_text())
    with runtime_owner(case.dsn) as scoped_dsn:
        with psycopg.connect(case.dsn) as installer:
            for signature in (
                "follow_up_scope_valid(TEXT,BOOLEAN)", "validate_follow_up_record()",
                "preserve_follow_up_record()", "preserve_follow_up_mission_owner()",
                "preserve_follow_up_admission_history()", "validate_follow_up_admission_payload()",
            ):
                installer.execute(sql.SQL("ALTER FUNCTION public." + signature + " OWNER TO {}").format(
                    sql.Identifier(RUNTIME_ROLE)))
        repository = PostgresTimescaleRepository(make_conninfo(scoped_dsn, connect_timeout=5),
                                                 min_pool_size=1, max_pool_size=2)
        try:
            yield RepositoryCase("postgres", repository, scoped_dsn)
        finally:
            await repository.close()


def cleanup_disposable(case):
    """Restore the historical READ row and validate its original PG CHECK on teardown."""
    legacy = getattr(case, "_legacy_actions_cleanup", ())
    if not legacy:
        return
    import psycopg
    from psycopg import sql
    statements = [("research_assignments", "UPDATE research_assignments SET actions=? WHERE assignment_id=?",
                   (original, assignment)) for _, _, assignment, original in legacy]
    corrupt_disposable(case, statements)
    with psycopg.connect(case.dsn) as conn:
        for name, definition, assignment, original in legacy:
            conn.execute(sql.SQL("ALTER TABLE research_assignments VALIDATE CONSTRAINT {}").format(sql.Identifier(name)))
            row = conn.execute("SELECT pg_get_constraintdef(oid),convalidated FROM pg_constraint "
                               "WHERE conrelid='public.research_assignments'::regclass AND conname=%s", (name,)).fetchone()
            assert row == (definition, True), ("Validated CHECK differs from original", row, definition)
            assert conn.execute("SELECT actions FROM research_assignments WHERE assignment_id=%s",
                                (assignment,)).fetchone()[0] == original
    case._legacy_actions_cleanup = ()
