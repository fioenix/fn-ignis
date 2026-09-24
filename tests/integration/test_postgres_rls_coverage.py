"""T018: every public table has a declared access posture, on a fresh install and on an upgrade.

006 enables row-level security on the tables that existed when it ran. The tables 007-019 created
got none, and Supabase grants every new public table to `anon` and `authenticated` by default
privilege, so those client roles could read `sources` and write `observations`. 021 gives every
table the chain creates an explicit posture. Two layers are asserted, because each one misses
something the other catches:

- RLS with no policy hides rows from SELECT, UPDATE and DELETE and rejects INSERT, but it does not
  govern TRUNCATE, and TimescaleDB does not copy the RLS flag onto hypertable chunks, which inherit
  the hypertable's grants in a schema every role may use; and
- revoking the client roles' privileges closes both, and a REVOKE on a hypertable reaches its
  chunks.

The expected posture is declared below, table by table, and compared with the catalog, so a later
migration that adds a public table fails here until someone decides that table's posture.
Behaviour is measured by running statements as each role, never read from the SQL text.
"""

import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import errors, sql

from conftest import (
    REPO_SQL,
    RUNTIME_ROLE,
    SUPABASE_ROLES,
    all_postgres_migrations,
    existing_supabase_roles,
    runtime_owner,
)
from ignis.application.ports.research_workspace_port import RunJournal
from ignis.domain.entities import ResearchMission, TopicCluster, TrendSignal
from ignis.domain.research_workspace import MarketBriefRevision, ResearchWorkspace
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

# The last migration an installation could have run before T018; 021 onwards is the upgrade.
LAST_BEFORE_T018 = 20
# Client roles may read these, through the two SELECT policies 006 installs, and do nothing else.
CLIENT_READ_ONLY = ("industry_taxonomies", "market_lexicons")
# Only the owner -- the runtime -- may touch these. The value names the data, for the report.
OWNER_ONLY = {
    "market_brief_revisions": "Market Brief",
    "mission_evidence": "mission evidence",
    "mission_run_journals": "run journal",
    "mission_writer_claims": "writer claim",
    "observations": "observation",
    "platform_credentials": "platform credential",
    "research_missions": "mission",
    "research_workspaces": "research workspace",
    "runtime_configs": "runtime configuration",
    "signal_metrics": "signal metric (legacy)",
    "source_identity_aliases": "identity alias",
    "sources": "source",
    "system_audit_logs": "audit log",
    "topic_clusters": "cluster",
    "trend_signals": "signal (legacy)",
}
POSTURE = {
    **{table: "client read-only" for table in CLIENT_READ_ONLY},
    **{table: "owner only" for table in OWNER_ONLY},
}
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
STATEMENTS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
POLICY_QUERY = (
    "SELECT tablename, policyname, cmd, permissive, roles::text[], qual FROM pg_policies"
    " WHERE schemaname = 'public' ORDER BY tablename, policyname"
)
PUBLIC_TABLES = (
    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c"
    " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p') ORDER BY c.relname"
)

# Test data: one representative row per table, written by the owner in foreign-key order.
WORKSPACE = "00000000-0000-4000-8000-000000000001"
MISSION = "00000000-0000-4000-8000-000000000002"
SPARE_MISSION = "00000000-0000-4000-8000-000000000003"
CLUSTER = "00000000-0000-4000-8000-000000000004"
SOURCE = "00000000-0000-4000-8000-000000000005"
OBSERVATION = "00000000-0000-4000-8000-000000000006"
OWNER_ROWS = (
    f"INSERT INTO research_workspaces (id, slug, root_path) VALUES ('{WORKSPACE}', 't018', '/t018')",
    f"INSERT INTO topic_clusters (id, canonical_name) VALUES ('{CLUSTER}', 't018 cluster')",
    f"INSERT INTO research_missions (id, title, workspace_id) VALUES"
    f" ('{MISSION}', 't018 mission', '{WORKSPACE}'), ('{SPARE_MISSION}', 't018 spare', '{WORKSPACE}')",
    "INSERT INTO market_brief_revisions (workspace_id, mission_id, revision_number, decision,"
    " target_user, problem, geo, timeframe, hypothesis, falsifiers, confirmed_by) VALUES"
    f" ('{WORKSPACE}', '{MISSION}', 1, 'd', 'u', 'p', 'VN', '7d', 'h', ARRAY['f'], 'owner')",
    "INSERT INTO mission_run_journals (workspace_id, mission_id, journal_path, sequence) VALUES"
    f" ('{WORKSPACE}', '{MISSION}', '/t018/journal-1', 1)",
    f"INSERT INTO mission_writer_claims (mission_id, run_id) VALUES ('{MISSION}', '{uuid4()}')",
    f"INSERT INTO sources (id, platform, external_id) VALUES ('{SOURCE}', 'threads', 'post:1')",
    "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source)"
    f" VALUES ('{OBSERVATION}', '{SOURCE}', now(), 'exact_ingestion', 'metadata_external_id')",
    f"INSERT INTO mission_evidence (mission_id, observation_id) VALUES ('{MISSION}', '{OBSERVATION}')",
    "INSERT INTO source_identity_aliases (platform, alias_external_id, canonical_external_id,"
    " witnessed_by) VALUES ('threads', 'post_shortcode:abc', 'post:1', 'owner')",
    "INSERT INTO platform_credentials (platform, auth_type, credentials_data)"
    " VALUES ('threads', 'oauth', '{\"access_token\": \"t018\"}')",
    "INSERT INTO runtime_configs (key, value) VALUES ('t018.owner', 'owner')",
    "INSERT INTO system_audit_logs (component, event_type, message) VALUES ('t018', 'seed', 'owner')",
    "INSERT INTO trend_signals (platform, raw_title) VALUES ('tiktok', 't018 owner')",
    "INSERT INTO signal_metrics (signal_id) VALUES (1)",
)
# A valid row a client could write to each table, so an INSERT that is allowed actually lands.
# Ids are supplied rather than defaulted, so the outcome turns only on the table privilege and RLS
# under test; a client that wants to write can always send its own id.
CLIENT_ROWS = {
    "industry_taxonomies": "(industry_code, industry_name) VALUES ('t018-client', 'client')",
    "market_brief_revisions": "(id, workspace_id, mission_id, revision_number, decision,"
    " target_user, problem, geo, timeframe, hypothesis, falsifiers, confirmed_by) VALUES"
    f" ('{uuid4()}', '{WORKSPACE}', '{SPARE_MISSION}', 2, 'd', 'u', 'p', 'VN', '7d', 'h', ARRAY['f'], 'client')",
    "market_lexicons": "(domain, term) VALUES ('t018', 'written by a client')",
    "mission_evidence": "(id, mission_id, observation_id) VALUES"
    f" ('{uuid4()}', '{SPARE_MISSION}', '{OBSERVATION}')",
    "mission_run_journals": "(id, workspace_id, mission_id, journal_path, sequence) VALUES"
    f" ('{uuid4()}', '{WORKSPACE}', '{MISSION}', '/t018/journal-2', 2)",
    "mission_writer_claims": f"(mission_id, run_id) VALUES ('{SPARE_MISSION}', '{uuid4()}')",
    "observations": "(id, source_id, time_provenance, identity_source) VALUES"
    f" ('{uuid4()}', '{SOURCE}', 'unknown', 'metadata_external_id')",
    "platform_credentials": "(platform, auth_type, credentials_data) VALUES ('reels', 'oauth', '{}')",
    "research_missions": f"(id, title) VALUES ('{uuid4()}', 't018 client mission')",
    "research_workspaces": "(id, slug, root_path) VALUES"
    f" ('{uuid4()}', 't018-client', '/t018-client')",
    "runtime_configs": "(key, value) VALUES ('t018.client', 'client')",
    "signal_metrics": "(signal_id) VALUES (2)",
    "source_identity_aliases": "(id, platform, alias_external_id, canonical_external_id,"
    f" witnessed_by) VALUES ('{uuid4()}', 'threads', 'post_shortcode:def', 'post:2', 'client')",
    "sources": f"(id, platform, external_id) VALUES ('{uuid4()}', 'threads', 'post:2')",
    "system_audit_logs": "(component, event_type, message) VALUES ('t018', 'probe', 'client')",
    "topic_clusters": f"(id, canonical_name) VALUES ('{uuid4()}', 't018 client cluster')",
    "trend_signals": "(platform, raw_title) VALUES ('tiktok', 't018 client')",
}


def _apply(dsn: str, *migrations: str) -> None:
    for migration in migrations:
        try:
            with psycopg.connect(dsn) as conn:
                conn.execute((REPO_SQL / migration).read_text(encoding="utf-8"))
        except psycopg.Error as exc:
            first_line = str(exc).splitlines()[0]
            raise AssertionError(f"{migration} failed: {first_line}") from None


def _all(dsn: str, query: str, params: tuple = ()) -> list:
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()


def _prefix(name: str) -> int:
    return int(re.match(r"(\d{3})_", name).group(1))


def _through_020() -> tuple:
    return tuple(name for name in all_postgres_migrations() if _prefix(name) <= LAST_BEFORE_T018)


def _from_021() -> tuple:
    return tuple(name for name in all_postgres_migrations() if _prefix(name) > LAST_BEFORE_T018)


def _seed(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        for statement in OWNER_ROWS:
            conn.execute(statement)


def _posture_violations(dsn: str) -> list:
    """Every way the catalog departs from POSTURE, as readable lines; empty when it matches.

    Read from the catalog, not from the migration: the table list comes from pg_class, so a table
    nobody declared is a violation rather than something the check never looks at.
    """
    violations = []
    tables = {name: (rls, forced) for name, rls, forced in _all(dsn, PUBLIC_TABLES)}
    for name in sorted(set(tables) - set(POSTURE)):
        violations.append(f"{name}: public table with no declared posture")
    for name in sorted(set(POSTURE) - set(tables)):
        violations.append(f"{name}: declared but missing from the catalog")
    for name, (rls, forced) in sorted(tables.items()):
        if not rls:
            violations.append(f"{name}: row-level security is off")
        if forced:
            violations.append(f"{name}: FORCE ROW LEVEL SECURITY would lock the owner out")
    for role in existing_supabase_roles(dsn):
        for name in sorted(tables):
            for privilege in TABLE_PRIVILEGES:
                allowed = name in CLIENT_READ_ONLY and privilege == "SELECT"
                held = _all(
                    dsn,
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (role, f"public.{name}", privilege),
                )[0][0]
                if held != allowed:
                    verb = "holds" if held else "lacks"
                    violations.append(f"{name}: {role} {verb} {privilege}")
        for (sequence,) in _all(
            dsn,
            "SELECT c.oid::regclass::text FROM pg_class c"
            " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'S' ORDER BY 1",
        ):
            for privilege in SEQUENCE_PRIVILEGES:
                if _all(dsn, "SELECT has_sequence_privilege(%s, %s, %s)", (role, sequence, privilege))[0][0]:
                    violations.append(f"{sequence}: {role} holds {privilege} on the sequence")
        for (chunk,) in _hypertable_chunks(dsn):
            for privilege in TABLE_PRIVILEGES:
                if _all(dsn, "SELECT has_table_privilege(%s, %s, %s)", (role, chunk, privilege))[0][0]:
                    violations.append(f"{chunk}: {role} holds {privilege} on a hypertable chunk")
    return violations


def _hypertable_chunks(dsn: str) -> list:
    """Chunks of public hypertables. They keep the rows, carry no RLS flag, and copy the grants."""
    if not _all(dsn, "SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'"):
        return []
    return _all(
        dsn,
        "SELECT quote_ident(chunk_schema) || '.' || quote_ident(chunk_name)"
        " FROM timescaledb_information.chunks"
        " WHERE hypertable_schema = 'public' ORDER BY 1",
    )


def _attempt(dsn: str, role: str, table: str, statement: str) -> str:
    """Run one statement as `role` inside a transaction that is always rolled back.

    The outcome is what the role actually got: `denied` by a table privilege or by RLS, or how
    many rows it read or changed. Anything else -- a constraint, a function or sequence privilege
    -- is a fixture fault and is raised, because reporting it as a denial would make a broken
    probe look like a closed door.
    """
    column = _all(
        dsn,
        "SELECT quote_ident(attname) FROM pg_attribute"
        " WHERE attrelid = %s::regclass AND attnum = 1",
        (f"public.{table}",),
    )[0][0]
    text = {
        "SELECT": f"SELECT count(*) FROM public.{table}",
        "INSERT": f"INSERT INTO public.{table} {CLIENT_ROWS[table]}",
        "UPDATE": f"UPDATE public.{table} SET {column} = {column}",
        "DELETE": f"DELETE FROM public.{table}",
        "TRUNCATE": f"TRUNCATE public.{table} CASCADE",
    }[statement]
    with psycopg.connect(dsn) as conn:
        try:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
            cursor = conn.execute(text)
            if statement == "SELECT":
                return f"read {cursor.fetchone()[0]}"
            if statement == "TRUNCATE":
                return "truncated"
            return f"{statement.lower()} {cursor.rowcount}"
        except errors.InsufficientPrivilege as exc:
            message = str(exc).splitlines()[0]
            if message.startswith("permission denied for table") or "row-level security" in message:
                return "denied"
            raise AssertionError(f"{role} {statement} {table}: {message}") from None
        finally:
            conn.rollback()


def _role_matrix(dsn: str) -> dict:
    return {
        (role, table, statement): _attempt(dsn, role, table, statement)
        for role in SUPABASE_ROLES
        for table in sorted(POSTURE)
        for statement in STATEMENTS
    }


def _expected_matrix(dsn: str) -> dict:
    """Vocabulary reads return every seeded row; every other statement on every table is denied."""
    expected = {}
    for role in SUPABASE_ROLES:
        for table in sorted(POSTURE):
            for statement in STATEMENTS:
                expected[(role, table, statement)] = "denied"
        for table in CLIENT_READ_ONLY:
            rows = _all(dsn, f"SELECT count(*) FROM public.{table}")[0][0]
            assert rows > 0, f"{table} holds no seeded row, so a read proves nothing"
            expected[(role, table, "SELECT")] = f"read {rows}"
    return expected


def _differences(actual: dict, expected: dict) -> list:
    return [
        f"{role} {statement} {table}: got {actual[(role, table, statement)]!r},"
        f" expected {wanted!r}"
        for (role, table, statement), wanted in sorted(expected.items())
        if actual[(role, table, statement)] != wanted
    ]


def _state(dsn: str) -> dict:
    """Everything 021 governs, for idempotence: flags, policies, grants and effective access."""
    return {
        "tables": _all(dsn, PUBLIC_TABLES),
        "policies": _all(dsn, POLICY_QUERY),
        "acl": _all(
            dsn,
            "SELECT c.relname, c.relacl::text FROM pg_class c"
            " WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'S')"
            " ORDER BY c.relname",
        ),
        "matrix": _role_matrix(dsn),
    }


# --- A. a fresh Supabase-like database, full chain --------------------------------------------


def test_every_public_table_has_a_declared_posture_and_every_client_privilege_matches(
    supabase_like_dsn,
):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed(dsn)

    assert _hypertable_chunks(dsn), "trend_signals must be a hypertable with a chunk to inspect"
    assert _posture_violations(dsn) == []


def test_client_roles_read_the_vocabulary_and_are_denied_everything_else(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed(dsn)

    assert _differences(_role_matrix(dsn), _expected_matrix(dsn)) == []


def test_the_only_policies_are_the_two_vocabulary_reads(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())

    assert [(row[0], row[1], row[2], row[4]) for row in _all(dsn, POLICY_QUERY)] == [
        ("industry_taxonomies", "allow_read_industry_taxonomies", "SELECT", list(SUPABASE_ROLES)),
        ("market_lexicons", "allow_read_market_lexicons", "SELECT", list(SUPABASE_ROLES)),
    ]


def test_re_applying_021_and_then_the_whole_chain_changes_no_posture(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed(dsn)
    settled = _state(dsn)

    _apply(dsn, *_from_021())
    assert _state(dsn) == settled
    _apply(dsn, *all_postgres_migrations())
    assert _state(dsn) == settled
    assert _posture_violations(dsn) == []


# --- B. an existing database, migrated through 020 before 021 arrives -------------------------


def test_a_database_migrated_through_020_is_exposed_until_021_closes_it(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *_through_020())
    _seed(dsn)

    before = _role_matrix(dsn)
    # The reported defect, reproduced before the fix, so the fix is measured against it.
    for role in SUPABASE_ROLES:
        assert before[(role, "sources", "SELECT")] == "read 1", before[(role, "sources", "SELECT")]
        assert before[(role, "observations", "INSERT")] == "insert 1"
        assert before[(role, "market_lexicons", "TRUNCATE")] == "truncated", (
            "RLS from 006 does not govern TRUNCATE"
        )

    _apply(dsn, *_from_021())

    assert _differences(_role_matrix(dsn), _expected_matrix(dsn)) == []
    assert _posture_violations(dsn) == []


# --- C. plain TimescaleDB, where the Supabase roles do not exist ------------------------------


def test_the_whole_chain_runs_on_plain_timescaledb_and_creates_no_role(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    assert existing_supabase_roles(dsn) == [], "this contract needs a server without the roles"

    _apply(dsn, *all_postgres_migrations())
    _apply(dsn, *_from_021())

    assert existing_supabase_roles(dsn) == [], "a migration created a Supabase role"
    assert _all(dsn, POLICY_QUERY) == [], "no policy may name a role this server does not have"
    assert _posture_violations(dsn) == []


# --- D. the check itself: it must fail when one table loses its posture -----------------------


def test_the_check_reports_a_post_006_table_whose_rls_is_switched_off(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    with psycopg.connect(dsn) as conn:
        conn.execute("ALTER TABLE public.observations DISABLE ROW LEVEL SECURITY")

    assert _posture_violations(dsn) == ["observations: row-level security is off"]


def test_the_check_reports_a_client_grant_on_a_post_006_table(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute("GRANT SELECT ON public.sources TO anon")

    assert _posture_violations(dsn) == ["sources: anon holds SELECT"]
    # RLS still hides the rows, which is exactly why the privilege layer is checked on its own.
    assert _attempt(dsn, "anon", "sources", "SELECT") == "read 0"


# --- E. the runtime owner, as a role that is neither superuser nor BYPASSRLS -------------------

@pytest.fixture
def runtime_owner_dsn(supabase_like_dsn):
    """The full chain, then every public table handed to a plain role the runtime connects as.

    The role gets ownership and schema USAGE only. Until 022 it also needed EXECUTE on the public
    functions, because the id defaults called uuid-ossp's uuid_generate_v4() there and 006 had
    revoked EXECUTE from PUBLIC; that grant is gone, so this contract now fails if any default or
    repository path still depends on a function the posture withholds.
    """
    dsn = supabase_like_dsn
    _apply(dsn, *all_postgres_migrations())
    with runtime_owner(dsn) as owner_dsn:
        yield owner_dsn


@pytest.mark.asyncio
async def test_the_runtime_owner_reads_and_writes_every_table_class_after_021(
    runtime_owner_dsn, tmp_path
):
    dsn = runtime_owner_dsn
    who = _all(
        dsn,
        "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user",
    )
    assert who == [(RUNTIME_ROLE, False, False)], "the owner must be subject to RLS to prove this"
    assert _posture_violations(dsn) == []

    workspace = ResearchWorkspace(slug="t018-owner", root_path=tmp_path / "t018-owner")
    mission = ResearchMission(
        title="T018 owner", keywords=["t018"], workspace_id=workspace.workspace_id,
        surface="MARKET",
    )
    brief = MarketBriefRevision(
        decision="d", target_user="u", problem="p", geo="VN", timeframe="7d", hypothesis="h",
        falsifiers=("f",), confirmed_by="owner", workspace_id=workspace.workspace_id,
        mission_id=mission.id,
    )
    run_id = uuid4()
    signal = TrendSignal(
        platform=PlatformType.THREADS,
        raw_title="T018 owner",
        metric_value=1.0,
        source_url="https://www.threads.net/@t018/post/C2xT018Ownr",
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 9, 24, 1, 0, tzinfo=timezone.utc),
        metadata={"post_id": "3141592653589793"},
    )
    repository = PostgresTimescaleRepository(dsn=dsn, min_pool_size=1, max_pool_size=2)
    try:
        await repository.log_event(component="t018", event_type="owner", message="owner write")
        await repository.set_runtime_config("t018.owner", "yes")
        await repository.save_platform_credentials(
            platform="threads", auth_type="oauth", credentials_data={"access_token": "owner"}
        )
        registered = await repository.register_lexicon_terms("t018_owner", ["owner term"])
        await repository.save_research_workspace(workspace)
        await repository.create_market_mission_with_brief(mission, brief)
        assert await repository.save_signals([signal]) == 1
        cluster = TopicCluster(canonical_name="T018 owner cluster", signals=[signal])
        await repository.save_clusters([cluster])
        signal.cluster_id = cluster.id
        await repository.assign_observation_clusters([signal])
        await repository.attach_mission_evidence(mission.id, [signal])
        await repository.record_run_journal(
            RunJournal(
                run_id=run_id, mission_id=mission.id, workspace_id=workspace.workspace_id,
                journal_path=workspace.journal_dir / "run-0001.json", sequence=1,
                status="STARTED", started_at=datetime.now(timezone.utc),
            )
        )
        claimed = await repository.claim_mission_writer(mission.id, run_id)

        logs = await repository.get_recent_logs(component="t018")
        config = await repository.get_runtime_config("t018.owner")
        credential = await repository.get_platform_credentials("threads")
        vocabulary = await repository.get_domain_lexicons("t018_owner")
        taxonomies = await repository.get_industry_taxonomies()
        evidence = await repository.get_mission_signals(mission.id)
        stored_brief = await repository.get_brief_revision_for_mission(mission.id)
        journals = await repository.list_run_journals(mission.id)
        claim = await repository.get_mission_writer_claim(mission.id)
        await repository.release_mission_writer(mission.id, run_id)
        erased = await repository.delete_platform_credentials("threads")
    finally:
        await repository.close()

    assert [entry["message"] for entry in logs] == ["owner write"]
    assert config == "yes"
    assert credential["credentials_data"] == {"access_token": "owner"}
    assert registered == 1 and [row["term"] for row in vocabulary] == ["owner term"]
    assert taxonomies, "the owner could not read the seeded taxonomies"
    assert [UUID(str(s.observation_id)) for s in evidence] == [signal.observation_id]
    assert stored_brief is not None and stored_brief.brief_revision_id == brief.brief_revision_id
    assert [journal.run_id for journal in journals] == [run_id]
    assert claimed is True and claim.run_id == run_id
    assert erased is True
    assert _all(
        dsn, "SELECT count(*) FROM source_identity_aliases WHERE canonical_external_id = %s",
        ("post:3141592653589793",),
    ) == [(1,)], "the owner's write did not reach the alias ledger"
