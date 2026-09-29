"""T017: every file in sql/ runs on a fresh PostgreSQL, and Supabase keeps its RLS policies.

The Compose `db` service mounts the whole sql/ directory as its initdb scripts, and the entrypoint
stops at the first failing file. `006_supabase_security_hardening.sql` named the Supabase roles
`authenticated` and `anon` unconditionally, so on plain TimescaleDB init exited in 006 and 007-020
never ran. Two contracts follow from the fix, and each needs its own server state:

- on a server without those roles the whole directory runs and the runtime owner works; and
- on a server where Supabase created them, 006 still installs its read-only policies and revokes
  function EXECUTE, and re-running it neither duplicates nor weakens anything.

Behaviour is read from the catalog and from queries run as the roles, never from the SQL text.
"""

import asyncio
import re
from datetime import date, datetime, timezone

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
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.domain.value_objects import IngressTrigger
from ignis.domain.youtube_quota import YouTubeQuotaBucket

SECURITY_MIGRATION = "006_supabase_security_hardening.sql"
RETIREMENT = "020_retire_ambiguous_tiktok_ui_noise.sql"
# The objects later migrations add; if init stopped early, these are what is missing.
LATER_OBJECTS = (
    "public.sources",
    "public.observations",
    "public.mission_evidence",
    "public.research_workspaces",
    "public.market_brief_revisions",
    "public.mission_run_journals",
    "public.mission_writer_claims",
    "public.source_identity_aliases",
    "public.idx_observations_latest_per_source",
    "public.mission_probe_outcomes",
    "public.mission_evidence_qualifications",
    "public.youtube_quota_buckets",
)
# Test data: the T016 retirements, which only exist once 020 has run.
RETIRED_UI_NOISE = {"live", "thông báo", "tin nhắn"}
# Stand-in for a Supabase RPC function such as match_memories, which 006 exists to harden.
RPC_PROBE = "public.t017_rpc_probe()"
POLICY_QUERY = (
    "SELECT tablename, policyname, cmd, permissive, roles::text[], qual FROM pg_policies"
    " WHERE schemaname = 'public' ORDER BY tablename, policyname"
)


def _apply(dsn: str, *migrations: str) -> None:
    for migration in migrations:
        try:
            with psycopg.connect(dsn) as conn:
                conn.execute((REPO_SQL / migration).read_text(encoding="utf-8"))
        except psycopg.Error as exc:
            first_line = str(exc).splitlines()[0]
            raise AssertionError(f"{migration} failed: {first_line}") from None


def _one(dsn: str, query: str, params: tuple = ()):
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchone()


def _all(dsn: str, query: str, params: tuple = ()) -> list:
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchall()


def _security_state(dsn: str) -> dict:
    """What 006 governs: policies, RLS flags, and who may execute the probe function."""
    rls = _all(
        dsn,
        "SELECT c.relname, c.relrowsecurity FROM pg_class c"
        " JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY c.relname",
    )
    probe_acl = _one(
        dsn,
        "SELECT proacl::text FROM pg_proc WHERE oid = to_regprocedure(%s)",
        (RPC_PROBE,),
    )
    return {
        "policies": _all(dsn, POLICY_QUERY),
        "rls": rls,
        "probe_acl": probe_acl[0] if probe_acl else None,
    }


# --- A. plain PostgreSQL, the Compose init path -------------------------------------------------


def test_the_sql_directory_is_one_continuous_filename_ordered_sequence():
    names = all_postgres_migrations()
    prefixes = [int(re.match(r"(\d{3})_", name).group(1)) for name in names]

    assert prefixes == list(range(1, len(names) + 1)), "a gap or duplicate breaks initdb order"
    assert SECURITY_MIGRATION in names, "006 must run in the init path, not be special-cased"
    assert RETIREMENT in names, "020 must run in the init path"


def test_every_migration_runs_on_plain_postgres_and_leaves_the_final_schema(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    assert existing_supabase_roles(dsn) == [], (
        "this contract needs a server without Supabase roles; run it on plain PostgreSQL"
    )

    _apply(dsn, *all_postgres_migrations())

    for name in LATER_OBJECTS:
        assert _one(dsn, "SELECT to_regclass(%s)", (name,))[0] is not None, f"{name} is missing"
    ui_noise = {
        row[0].strip()
        for row in _all(dsn, "SELECT term FROM market_lexicons WHERE domain = 'tiktok_ui_noise'")
    }
    assert ui_noise and not ui_noise & RETIRED_UI_NOISE, "020 did not run after the earlier files"
    state = _security_state(dsn)
    assert dict(state["rls"])["market_lexicons"] is True, "006 must still enable RLS"
    assert dict(state["rls"])["platform_credentials"] is True
    assert state["policies"] == [], "no policy may name a role this server does not have"


def test_re_applying_006_and_the_whole_sequence_changes_nothing(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())
    settled = _security_state(dsn)
    lexicons = _all(dsn, "SELECT domain, term FROM market_lexicons ORDER BY domain, term")

    _apply(dsn, SECURITY_MIGRATION)
    _apply(dsn, *all_postgres_migrations())

    assert _security_state(dsn) == settled
    assert _all(dsn, "SELECT domain, term FROM market_lexicons ORDER BY domain, term") == lexicons


@pytest.mark.asyncio
async def test_the_runtime_owner_reads_and_writes_after_rls_is_enabled(empty_postgres_dsn):
    """Compose runs the worker as POSTGRES_USER, the owner of every table the init created.

    RLS with no policy denies everyone except the owner, so this is the check that enabling it
    did not lock the runtime out of its own tables.
    """
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())
    owner = _one(
        dsn,
        "SELECT pg_get_userbyid(relowner) = current_user, relrowsecurity FROM pg_class"
        " WHERE oid = 'public.platform_credentials'::regclass",
    )
    assert owner == (True, True), "the smoke test must run as the owner, with RLS on"

    repository = PostgresTimescaleRepository(dsn=dsn, min_pool_size=1, max_pool_size=2)
    try:
        await repository.log_event(
            component="t017", event_type="smoke", message="init smoke", level="info"
        )
        await repository.save_platform_credentials(
            platform="threads",
            auth_type="oauth",
            credentials_data={"access_token": "smoke"},
            expires_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        )
        logs = await repository.get_recent_logs(component="t017")
        stored = await repository.get_platform_credentials("threads")
        lexicons = await repository.get_domain_lexicons("tiktok_ui_noise")
        deleted = await repository.delete_platform_credentials("threads")
    finally:
        await repository.close()

    assert [entry["message"] for entry in logs] == ["init smoke"]
    assert stored["credentials_data"] == {"access_token": "smoke"}
    assert lexicons, "the owner could not read the seeded vocabulary"
    assert deleted is True


# --- B. a Supabase-like server, where the roles exist -------------------------------------------


def _apply_with_rpc_probe(dsn: str) -> None:
    """The real sequence, with an RPC function present before 006 as it is on Supabase."""
    names = all_postgres_migrations()
    split = names.index(SECURITY_MIGRATION)
    _apply(dsn, *names[:split])
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "CREATE FUNCTION public.t017_rpc_probe() RETURNS integer"
            " LANGUAGE sql AS 'SELECT 1'"
        )
    for role in SUPABASE_ROLES:
        assert _can_execute(dsn, role), (
            f"the probe must start executable by {role}, or the revoke proves nothing"
        )
    _apply(dsn, *names[split:])


def _as_role(dsn: str, role: str, query: str):
    with psycopg.connect(dsn) as conn:
        conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role)))
        cursor = conn.execute(query)
        return cursor.fetchone() if cursor.description else cursor.rowcount


def test_supabase_roles_get_exactly_the_two_read_only_policies(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)

    assert _all(dsn, POLICY_QUERY) == [
        (
            "industry_taxonomies",
            "allow_read_industry_taxonomies",
            "SELECT",
            "PERMISSIVE",
            ["anon", "authenticated"],
            "true",
        ),
        (
            "market_lexicons",
            "allow_read_market_lexicons",
            "SELECT",
            "PERMISSIVE",
            ["anon", "authenticated"],
            "true",
        ),
    ]


def test_supabase_roles_can_read_the_vocabulary_and_nothing_else(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO platform_credentials (platform, auth_type, credentials_data)"
            " VALUES ('threads', 'oauth', '{}')"
        )

    # Since 021 the client roles hold no privilege on these tables at all, so a read is refused
    # outright rather than answered with the empty result RLS alone would give.
    refused = (
        "SELECT count(*) FROM platform_credentials",
        "SELECT count(*) FROM research_missions",
        "UPDATE market_lexicons SET term = term",
        "INSERT INTO market_lexicons (domain, term) VALUES ('t017', 'written by a client')",
    )
    for role in SUPABASE_ROLES:
        assert _as_role(dsn, role, "SELECT count(*) FROM market_lexicons")[0] > 0
        assert _as_role(dsn, role, "SELECT count(*) FROM industry_taxonomies")[0] > 0
        for statement in refused:
            with pytest.raises(errors.InsufficientPrivilege):
                _as_role(dsn, role, statement)


def _can_execute(dsn: str, role: str) -> bool:
    return _one(dsn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, RPC_PROBE))[0]


def test_function_execute_is_revoked_from_public_and_from_every_client_role(supabase_like_dsn):
    """Supabase grants EXECUTE to both client roles directly, so revoking PUBLIC is not enough.

    Both are denied: 006 hardens RPC functions against every PostgREST client role, and an
    exception for signed-in users would have to be a stated decision, not a missing line.
    """
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)

    public_grants = _one(
        dsn,
        "SELECT count(*) FROM pg_proc p, aclexplode(p.proacl) a"
        " WHERE p.oid = to_regprocedure(%s) AND a.grantee = 0 AND a.privilege_type = 'EXECUTE'",
        (RPC_PROBE,),
    )[0]

    assert public_grants == 0, "PUBLIC can still execute the RPC function"
    for role in SUPABASE_ROLES:
        assert _can_execute(dsn, role) is False, f"{role} can still execute the RPC function"


def test_a_second_application_neither_duplicates_nor_weakens_supabase_security(
    supabase_like_dsn,
):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)
    settled = _security_state(dsn)

    _apply(dsn, SECURITY_MIGRATION)
    _apply(dsn, *all_postgres_migrations())

    assert _security_state(dsn) == settled
    assert len(settled["policies"]) == 2
    for role in SUPABASE_ROLES:
        assert _can_execute(dsn, role) is False


# --- C. UUID primary-key defaults, and the runtime owner that depends on them -------------------
#
# 001 installs uuid-ossp into public, and 001, 016, 017 and 018 default nine primary keys to its
# uuid_generate_v4(). 006 then revokes EXECUTE on every public function from PUBLIC, which is right
# for application RPCs and wrong for a column default: a runtime that owns the tables but is not a
# superuser cannot insert a row without supplying the id. 022 repoints those defaults at
# PostgreSQL's built-in gen_random_uuid(), which lives in pg_catalog and needs no grant, and leaves
# the 006 posture and uuid-ossp exactly as they were.

UUID_MIGRATION = "022_builtin_uuid_defaults.sql"
# The last migration an installation could have run before T020; 022 onwards is the upgrade.
LAST_BEFORE_T020 = 21
# The primary keys whose default called uuid_generate_v4() through 021, read back from the catalog
# by test_the_affected_uuid_defaults_are_discovered_from_the_schema_at_021.
UUID_DEFAULT_TABLES = (
    "market_brief_revisions",
    "mission_evidence",
    "mission_run_journals",
    "observations",
    "research_missions",
    "research_workspaces",
    "source_identity_aliases",
    "sources",
    "topic_clusters",
)
# 003 already used the built-in generator for these two.
BUILTIN_SINCE_003 = ("industry_taxonomies", "market_lexicons")
# 023 creates its two tables with the built-in generator from the start.
BUILTIN_SINCE_023 = ("mission_evidence_qualifications", "mission_probe_outcomes")
UUID_DEFAULTS = (
    "SELECT c.relname, a.attname, pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d"
    " JOIN pg_class c ON c.oid = d.adrelid"
    " JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum"
    " WHERE c.relnamespace = 'public'::regnamespace AND a.atttypid = 'uuid'::regtype"
    " ORDER BY c.relname, a.attname"
)
# Column defaults anywhere in the database that depend on a function uuid-ossp provides.
UUID_OSSP_DEPENDENT_DEFAULTS = (
    "SELECT count(*) FROM pg_depend dep"
    " WHERE dep.classid = 'pg_attrdef'::regclass AND dep.refclassid = 'pg_proc'::regclass"
    " AND dep.refobjid IN ("
    "   SELECT ext.objid FROM pg_depend ext"
    "   WHERE ext.classid = 'pg_proc'::regclass AND ext.refclassid = 'pg_extension'::regclass"
    "   AND ext.refobjid = (SELECT oid FROM pg_extension WHERE extname = 'uuid-ossp'))"
)
V4_FUNCTION = "public.uuid_generate_v4()"
V4_DENIED = "permission denied for function uuid_generate_v4"

# Test data: the parents a defaulted child row needs, written by the migration login with ids.
T020_WORKSPACE = "00000000-0000-4000-8000-000000000201"
T020_MISSION = "00000000-0000-4000-8000-000000000202"
T020_SOURCE = "00000000-0000-4000-8000-000000000203"
T020_OBSERVATION = "00000000-0000-4000-8000-000000000204"
T020_PARENTS = (
    f"INSERT INTO research_workspaces (id, slug, root_path) VALUES ('{T020_WORKSPACE}', 't020', '/t020')",
    f"INSERT INTO research_missions (id, title, workspace_id) VALUES"
    f" ('{T020_MISSION}', 't020 mission', '{T020_WORKSPACE}')",
    f"INSERT INTO sources (id, platform, external_id) VALUES ('{T020_SOURCE}', 'threads', 'post:t020')",
    "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source)"
    f" VALUES ('{T020_OBSERVATION}', '{T020_SOURCE}', now(), 'exact_ingestion', 'metadata_external_id')",
)
# One valid row per affected table with the id left out, so only the column default can supply it.
DEFAULTED_ID_ROWS = {
    "market_brief_revisions": "(workspace_id, mission_id, revision_number, decision, target_user,"
    " problem, geo, timeframe, hypothesis, falsifiers, confirmed_by) VALUES"
    f" ('{T020_WORKSPACE}', '{T020_MISSION}', 1, 'd', 'u', 'p', 'VN', '7d', 'h', ARRAY['f'], 'owner')",
    "mission_evidence": f"(mission_id, observation_id) VALUES ('{T020_MISSION}', '{T020_OBSERVATION}')",
    "mission_run_journals": "(workspace_id, mission_id, journal_path, sequence) VALUES"
    f" ('{T020_WORKSPACE}', '{T020_MISSION}', '/t020/journal-1', 1)",
    "observations": "(source_id, observed_at, time_provenance, identity_source) VALUES"
    f" ('{T020_SOURCE}', now(), 'exact_ingestion', 'metadata_external_id')",
    "research_missions": f"(title, workspace_id) VALUES ('t020 defaulted', '{T020_WORKSPACE}')",
    "research_workspaces": "(slug, root_path) VALUES ('t020-defaulted', '/t020-defaulted')",
    "source_identity_aliases": "(platform, alias_external_id, canonical_external_id, witnessed_by)"
    " VALUES ('threads', 'post_shortcode:t020', 'post:t020', 'owner')",
    "sources": "(platform, external_id) VALUES ('threads', 'post:t020-defaulted')",
    "topic_clusters": "(canonical_name) VALUES ('t020 defaulted cluster')",
}


def _through(last: int) -> tuple:
    return tuple(name for name in all_postgres_migrations() if int(name[:3]) <= last)


def _executes(dsn: str, function: str, role: str | None = None) -> bool:
    """Whether `role` -- or, without one, the session's current role -- may execute `function`."""
    if role is None:
        return _one(dsn, "SELECT has_function_privilege(%s, 'EXECUTE')", (function,))[0]
    return _one(dsn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", (role, function))[0]


def _seed_t020_parents(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        for statement in T020_PARENTS:
            conn.execute(statement)


def _defaulted_insert(dsn: str, table: str) -> str:
    """Insert one row with the id omitted, always rolled back; say what happened.

    `inserted` only when the default produced a version-4 UUID. A function-privilege refusal is
    reported by its message, because that is the outcome under test. Anything else -- a constraint,
    a table privilege, a missing relation -- is a fixture fault and is raised, so a broken probe
    cannot pass for the failure it is meant to measure.
    """
    with psycopg.connect(dsn) as conn:
        try:
            (new_id,) = conn.execute(
                f"INSERT INTO public.{table} {DEFAULTED_ID_ROWS[table]} RETURNING id"
            ).fetchone()
            return "inserted" if new_id.version == 4 else f"id {new_id} is not version 4"
        except errors.InsufficientPrivilege as exc:
            message = str(exc).splitlines()[0]
            if message.startswith("permission denied for function"):
                return message
            raise AssertionError(f"{table}: {message}") from None
        finally:
            conn.rollback()


def _defaulted_inserts(dsn: str) -> dict:
    return {table: _defaulted_insert(dsn, table) for table in UUID_DEFAULT_TABLES}


def _uuid_state(dsn: str) -> dict:
    """What 022 governs, and what it must leave alone, for the idempotence contract."""
    return {
        "defaults": _all(dsn, UUID_DEFAULTS),
        "uuid_ossp": _all(
            dsn,
            "SELECT e.extversion, n.nspname FROM pg_extension e"
            " JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'uuid-ossp'",
        ),
        "uuid_ossp_acl": _all(
            dsn,
            "SELECT p.oid::regprocedure::text, p.proacl::text FROM pg_proc p"
            " JOIN pg_depend d ON d.classid = 'pg_proc'::regclass AND d.objid = p.oid"
            " WHERE d.refclassid = 'pg_extension'::regclass"
            " AND d.refobjid = (SELECT oid FROM pg_extension WHERE extname = 'uuid-ossp')"
            " ORDER BY 1",
        ),
    }


def test_the_affected_uuid_defaults_are_discovered_from_the_schema_at_021(empty_postgres_dsn):
    """The set 022 repairs is read from the catalog of a 021 install, not assumed."""
    dsn = empty_postgres_dsn
    _apply(dsn, *_through(LAST_BEFORE_T020))

    calling_v4 = sorted(
        table for table, column, expression in _all(dsn, UUID_DEFAULTS)
        if "uuid_generate_v4" in expression and column == "id"
    )
    assert calling_v4 == list(UUID_DEFAULT_TABLES)
    other_uuid_ossp_defaults = [
        (table, column) for table, column, expression in _all(dsn, UUID_DEFAULTS)
        if "uuid_generate" in expression and column != "id"
    ]
    assert other_uuid_ossp_defaults == [], "a non-key column also defaults to uuid-ossp"


def test_a_fresh_install_defaults_every_uuid_key_to_the_builtin_generator(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())

    assert _all(dsn, UUID_DEFAULTS) == [
        (table, "id", "gen_random_uuid()")
        for table in sorted(UUID_DEFAULT_TABLES + BUILTIN_SINCE_003 + BUILTIN_SINCE_023)
    ]
    assert _one(dsn, UUID_OSSP_DEPENDENT_DEFAULTS)[0] == 0, "a default still calls uuid-ossp"
    # Left installed, in place, for anything outside Ignis that calls it.
    assert _uuid_state(dsn)["uuid_ossp"] == [("1.1", "public")]
    # Still withheld from PUBLIC: the fix is a different default, not a wider grant.
    assert _executes(dsn, V4_FUNCTION, "public") is False
    assert existing_supabase_roles(dsn) == [], "a migration created a Supabase role"


def test_a_non_superuser_owner_inserts_every_defaulted_id_after_the_full_chain(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed_t020_parents(dsn)

    with runtime_owner(dsn) as owner_dsn:
        who = _one(
            owner_dsn,
            "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles"
            " WHERE rolname = current_user",
        )
        assert who == (RUNTIME_ROLE, False, False), "the owner must hold no bypass to prove this"
        assert _executes(owner_dsn, V4_FUNCTION) is False, (
            "the owner was granted uuid_generate_v4(), so this contract would pass without 022"
        )
        outcomes = _defaulted_inserts(owner_dsn)

    assert outcomes == {table: "inserted" for table in UUID_DEFAULT_TABLES}


def test_an_install_at_021_is_repaired_by_applying_022_as_the_table_owner(supabase_like_dsn):
    """The upgrade: the failure reproduced on a 021 install, then 022 and nothing else fixes it."""
    dsn = supabase_like_dsn
    names = _through(LAST_BEFORE_T020)
    split = names.index(SECURITY_MIGRATION)
    _apply(dsn, *names[:split])
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "CREATE FUNCTION public.t017_rpc_probe() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
        )
    _apply(dsn, *names[split:])
    _seed_t020_parents(dsn)

    with runtime_owner(dsn) as owner_dsn:
        assert _defaulted_inserts(owner_dsn) == {table: V4_DENIED for table in UUID_DEFAULT_TABLES}

        # Applied as the owner the runtime connects as, which is what a Supabase upgrade has.
        _apply(owner_dsn, UUID_MIGRATION)

        assert _defaulted_inserts(owner_dsn) == {table: "inserted" for table in UUID_DEFAULT_TABLES}
        assert _executes(owner_dsn, V4_FUNCTION) is False, "022 must not work by granting v4"

    # The 006 and 021 boundary is unchanged by the upgrade.
    for role in ("public", *SUPABASE_ROLES):
        assert _executes(dsn, RPC_PROBE, role) is False, f"{role} can execute the RPC probe"
    for role in SUPABASE_ROLES:
        for statement in (
            f"INSERT INTO sources (id, platform, external_id)"
            f" VALUES (gen_random_uuid(), 'threads', 'post:{role}')",
            "UPDATE observations SET time_provenance = time_provenance",
            "DELETE FROM research_missions",
        ):
            with pytest.raises(errors.InsufficientPrivilege):
                _as_role(dsn, role, statement)


def test_re_applying_022_and_the_whole_chain_changes_no_uuid_or_function_state(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)
    settled = (_uuid_state(dsn), _security_state(dsn))

    _apply(dsn, UUID_MIGRATION)
    assert (_uuid_state(dsn), _security_state(dsn)) == settled
    _apply(dsn, *all_postgres_migrations())
    assert (_uuid_state(dsn), _security_state(dsn)) == settled


# --- D. 023: mission probe outcomes and evidence qualifications ---------------------------------
#
# Two additive tables. A probe outcome records what one connector surface did during one run; a
# qualification records the semantic judgment one mission made about one observation it holds.
# Nothing existing is rewritten and nothing is backfilled, because a migration cannot know
# historical connector health or a semantic judgment nobody made.

QUALIFICATION_MIGRATION = "023_evidence_qualification.sql"
LAST_BEFORE_023 = 22
NEW_TABLES = ("mission_evidence_qualifications", "mission_probe_outcomes")
# Test data: one of every parent the two new tables reference.
Q_WORKSPACE = "00000000-0000-4000-8000-000000000301"
Q_MISSION = "00000000-0000-4000-8000-000000000302"
Q_OTHER_MISSION = "00000000-0000-4000-8000-000000000303"
Q_SOURCE = "00000000-0000-4000-8000-000000000304"
Q_OBSERVATION = "00000000-0000-4000-8000-000000000305"
Q_RUN = "00000000-0000-4000-8000-000000000306"
Q_BRIEF = "00000000-0000-4000-8000-000000000307"
Q_PARENTS = (
    f"INSERT INTO research_workspaces (id, slug, root_path) VALUES ('{Q_WORKSPACE}', 't008', '/t008')",
    f"INSERT INTO research_missions (id, title, workspace_id, surface) VALUES"
    f" ('{Q_MISSION}', 't008 mission', '{Q_WORKSPACE}', 'MARKET'),"
    f" ('{Q_OTHER_MISSION}', 't008 other', '{Q_WORKSPACE}', 'MARKET')",
    "INSERT INTO market_brief_revisions (id, workspace_id, mission_id, revision_number, decision,"
    " target_user, problem, geo, timeframe, hypothesis, falsifiers, confirmed_by) VALUES"
    f" ('{Q_BRIEF}', '{Q_WORKSPACE}', '{Q_MISSION}', 1, 'd', 'u', 'p', 'VN', '7d', 'h',"
    " ARRAY['f'], 'owner')",
    f"INSERT INTO sources (id, platform, external_id) VALUES ('{Q_SOURCE}', 'youtube', 'video:t008')",
    "INSERT INTO observations (id, source_id, observed_at, time_provenance, identity_source)"
    f" VALUES ('{Q_OBSERVATION}', '{Q_SOURCE}', now(), 'exact_ingestion', 'metadata_external_id')",
    f"INSERT INTO mission_evidence (mission_id, observation_id) VALUES ('{Q_MISSION}', '{Q_OBSERVATION}')",
    "INSERT INTO mission_run_journals (id, workspace_id, mission_id, journal_path, sequence, status)"
    f" VALUES ('{Q_RUN}', '{Q_WORKSPACE}', '{Q_MISSION}', '/t008/journal-1', 1, 'COMPLETED')",
)
PROBE_OUTCOME = (
    "INSERT INTO mission_probe_outcomes (run_id, platform, connector_surface, status,"
    " signals_collected, queried_keywords, query_fingerprint, completed_at) VALUES"
    " ('{run}', 'youtube', '{surface}', '{status}', {count}, {queried}, 'fp', now())"
)
QUALIFICATION = (
    "INSERT INTO mission_evidence_qualifications (mission_id, observation_id, brief_revision_id,"
    " frame_fingerprint, relation, purpose, confidence, reason_code, judged_by) VALUES"
    " ('{mission}', '{observation}', '{brief}', 'frame', '{relation}', '{purpose}', {confidence},"
    " '{reason}', 'agent')"
)
# The rows every existing table holds before 023 runs, digested so a rewrite is visible.
EXISTING_DIGEST = (
    "SELECT md5(string_agg(t.row, '|' ORDER BY t.row)) FROM ("
    " SELECT 'source:' || id::text || platform || external_id AS row FROM sources"
    " UNION ALL SELECT 'observation:' || id::text || source_id::text FROM observations"
    " UNION ALL SELECT 'evidence:' || mission_id::text || observation_id::text FROM mission_evidence"
    " UNION ALL SELECT 'mission:' || id::text || title || coalesce(surface, '') FROM research_missions"
    " UNION ALL SELECT 'brief:' || id::text || mission_id::text || hypothesis FROM market_brief_revisions"
    " UNION ALL SELECT 'journal:' || id::text || status || journal_path FROM mission_run_journals"
    ") t"
)


def _seed_qualification_parents(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        for statement in Q_PARENTS:
            conn.execute(statement)


def _refused(dsn: str, statement: str):
    """The SQLSTATE class a statement is refused with, or None when it lands (rolled back)."""
    with psycopg.connect(dsn) as conn:
        try:
            conn.execute(statement)
            return None
        except psycopg.Error as exc:
            return type(exc).__name__
        finally:
            conn.rollback()


def _qualification_catalog(dsn: str) -> dict:
    """What 023 governs, for the idempotence contract: columns, constraints, RLS and grants."""
    return {
        "columns": _all(
            dsn,
            "SELECT table_name, column_name, data_type, is_nullable, column_default"
            " FROM information_schema.columns WHERE table_schema = 'public'"
            " AND table_name = ANY(%s) ORDER BY table_name, ordinal_position",
            (list(NEW_TABLES),),
        ),
        "constraints": _all(
            dsn,
            "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = ANY(ARRAY[to_regclass('public.mission_probe_outcomes'),"
            " to_regclass('public.mission_evidence_qualifications')]) ORDER BY 1, 2",
        ),
        "rls": _all(
            dsn,
            "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
            " WHERE relnamespace = 'public'::regnamespace AND relname = ANY(%s) ORDER BY relname",
            (list(NEW_TABLES),),
        ),
        "grants": _all(
            dsn,
            "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants"
            " WHERE table_schema = 'public' AND table_name = ANY(%s)"
            " AND grantee IN ('anon', 'authenticated', 'PUBLIC') ORDER BY 1, 2, 3",
            (list(NEW_TABLES),),
        ),
        "policies": _all(
            dsn,
            "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public'"
            " AND tablename = ANY(%s)",
            (list(NEW_TABLES),),
        ),
    }


def test_023_creates_both_tables_owner_only_with_rls_and_builtin_uuid_defaults(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)

    catalog = _qualification_catalog(dsn)
    assert catalog["rls"] == [(table, True, False) for table in sorted(NEW_TABLES)]
    assert catalog["grants"] == [], "a client role or PUBLIC holds a privilege on a 023 table"
    assert catalog["policies"] == [], "a 023 table must have no policy"
    defaults = {
        (table, column): default
        for table, column, _type, _nullable, default in catalog["columns"]
        if column == "id"
    }
    assert defaults == {(table, "id"): "gen_random_uuid()" for table in NEW_TABLES}
    for role in SUPABASE_ROLES:
        for table in NEW_TABLES:
            with pytest.raises(errors.InsufficientPrivilege):
                _as_role(dsn, role, f"SELECT count(*) FROM {table}")


def test_023_enforces_evidence_ownership_value_checks_and_cascades(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())
    _seed_qualification_parents(dsn)

    def qualification(**overrides):
        values = {
            "mission": Q_MISSION, "observation": Q_OBSERVATION, "brief": Q_BRIEF,
            "relation": "QUALIFIED_SUPPORT", "purpose": "SUPPLY", "confidence": "0.9",
            "reason": "DIRECT_TO_FRAME",
        }
        values.update(overrides)
        return QUALIFICATION.format(**values)

    # A mission may only qualify an observation it holds: the composite key names mission_evidence.
    assert _refused(dsn, qualification(mission=Q_OTHER_MISSION)) == "ForeignKeyViolation"
    # Relation and purpose must agree, confidence is a probability, and an unassessed row is honest.
    assert _refused(dsn, qualification(purpose="CONTEXT")) == "CheckViolation"
    assert _refused(dsn, qualification(relation="CONTEXT_ONLY")) == "CheckViolation"
    assert _refused(dsn, qualification(confidence="1.5")) == "CheckViolation"
    assert _refused(dsn, qualification(relation="UNASSESSED", reason="EVALUATOR_UNAVAILABLE")) == (
        "CheckViolation"
    ), "an unassessed row cannot carry a confidence"
    assert _refused(
        dsn, qualification(relation="UNASSESSED", confidence="NULL", reason="DIRECT_TO_FRAME")
    ) == "CheckViolation"
    assert _refused(dsn, qualification(relation="RELEVANT")) == "CheckViolation"
    assert _refused(dsn, qualification(reason="FREE_TEXT")) == "CheckViolation"
    assert _refused(dsn, qualification()) is None

    probe = dict(run=Q_RUN, surface="youtube", status="EMPTY_NO_DATA", count=0, queried="ARRAY['t008']")
    assert _refused(dsn, PROBE_OUTCOME.format(**{**probe, "count": 3})) == "CheckViolation", (
        "an empty surface cannot report collected signals"
    )
    assert _refused(dsn, PROBE_OUTCOME.format(**{**probe, "status": "FINE"})) == "CheckViolation"
    assert _refused(dsn, PROBE_OUTCOME.format(**{**probe, "queried": "ARRAY[]::text[]"})) == (
        "CheckViolation"
    ), "an empty answer must name the query it measured"
    assert _refused(dsn, PROBE_OUTCOME.format(**{**probe, "count": -1})) == "CheckViolation"
    assert _refused(
        dsn, PROBE_OUTCOME.format(**{**probe, "run": "00000000-0000-4000-8000-000000000399"})
    ) == "ForeignKeyViolation"

    with psycopg.connect(dsn) as conn:
        conn.execute(qualification())
        conn.execute(PROBE_OUTCOME.format(**probe))
    assert _refused(dsn, qualification(relation="EXCLUDED_IRRELEVANT")) == "UniqueViolation"
    assert _refused(dsn, PROBE_OUTCOME.format(**probe)) == "UniqueViolation"

    # Pruning the evidence association removes its judgment; deleting a run removes its outcomes.
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "DELETE FROM mission_evidence WHERE mission_id = %s AND observation_id = %s",
            (Q_MISSION, Q_OBSERVATION),
        )
        conn.execute("DELETE FROM mission_run_journals WHERE id = %s", (Q_RUN,))
    assert _one(dsn, "SELECT count(*) FROM mission_evidence_qualifications")[0] == 0
    assert _one(dsn, "SELECT count(*) FROM mission_probe_outcomes")[0] == 0
    # The immutable observation outlives both.
    assert _one(dsn, "SELECT count(*) FROM observations WHERE id = %s", (Q_OBSERVATION,))[0] == 1


def test_023_upgrades_an_existing_database_without_changing_or_backfilling_a_row(
    empty_postgres_dsn,
):
    dsn = empty_postgres_dsn
    _apply(dsn, *_through(LAST_BEFORE_023))
    _seed_qualification_parents(dsn)
    before = _one(dsn, EXISTING_DIGEST)[0]

    _apply(dsn, QUALIFICATION_MIGRATION)

    assert _one(dsn, EXISTING_DIGEST)[0] == before, "023 rewrote an existing row"
    for table in NEW_TABLES:
        assert _one(dsn, f"SELECT count(*) FROM {table}")[0] == 0, f"023 backfilled {table}"


def test_re_applying_023_and_the_whole_chain_changes_no_qualification_state(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)
    settled = (_qualification_catalog(dsn), _security_state(dsn), _uuid_state(dsn))

    _apply(dsn, QUALIFICATION_MIGRATION)
    assert (_qualification_catalog(dsn), _security_state(dsn), _uuid_state(dsn)) == settled
    _apply(dsn, *all_postgres_migrations())
    assert (_qualification_catalog(dsn), _security_state(dsn), _uuid_state(dsn)) == settled


# --- E. 024: shared YouTube quota ledger -------------------------------------------------------

QUOTA_MIGRATION = "024_youtube_quota_ledger.sql"


def test_024_creates_an_owner_only_constrained_rls_ledger(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)

    assert _one(
        dsn,
        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
        " WHERE oid = 'public.youtube_quota_buckets'::regclass",
    ) == (True, False)
    assert _all(
        dsn,
        "SELECT grantee, privilege_type FROM information_schema.role_table_grants"
        " WHERE table_schema = 'public' AND table_name = 'youtube_quota_buckets'"
        " AND grantee IN ('anon', 'authenticated', 'PUBLIC')",
    ) == []
    assert _all(
        dsn,
        "SELECT policyname FROM pg_policies"
        " WHERE schemaname = 'public' AND tablename = 'youtube_quota_buckets'",
    ) == []

    with pytest.raises(errors.CheckViolation):
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO youtube_quota_buckets"
                " (quota_day, bucket, used, scheduled_used) VALUES (current_date, 'unknown', 0, 0)"
            )
    with pytest.raises(errors.CheckViolation):
        with psycopg.connect(dsn) as conn:
            conn.execute(
                "INSERT INTO youtube_quota_buckets"
                " (quota_day, bucket, used, scheduled_used)"
                " VALUES (current_date, 'search_list', 1, 2)"
            )


@pytest.mark.asyncio
async def test_postgres_quota_reservation_never_overspends_under_concurrency(empty_postgres_dsn):
    dsn = empty_postgres_dsn
    _apply(dsn, *all_postgres_migrations())
    repo = PostgresTimescaleRepository(dsn=dsn)
    now = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)

    try:
        reservations = await asyncio.gather(
            *(
                repo.reserve_youtube_quota(
                    quota_day=date(2026, 9, 29),
                    bucket=YouTubeQuotaBucket.SEARCH_LIST,
                    cost=1,
                    trigger=IngressTrigger.SCHEDULED,
                    daily_limit=100,
                    scheduled_limit=7,
                    now=now,
                )
                for _ in range(20)
            )
        )
        usage = await repo.get_youtube_quota_usage(date(2026, 9, 29))
    finally:
        await repo.close()

    assert sum(item.admitted for item in reservations) == 7
    assert len(usage) == 1
    assert usage[0].used == 7
    assert usage[0].scheduled_used == 7


def test_re_applying_024_and_the_whole_chain_changes_no_quota_state(supabase_like_dsn):
    dsn = supabase_like_dsn
    _apply_with_rpc_probe(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(
            "INSERT INTO youtube_quota_buckets"
            " (quota_day, bucket, used, scheduled_used, exhausted)"
            " VALUES (DATE '2026-09-29', 'search_list', 8, 3, TRUE)"
        )
    settled = _one(
        dsn,
        "SELECT quota_day, bucket, used, scheduled_used, exhausted"
        " FROM youtube_quota_buckets WHERE quota_day = DATE '2026-09-29'",
    )

    _apply(dsn, QUOTA_MIGRATION)
    assert _one(
        dsn,
        "SELECT quota_day, bucket, used, scheduled_used, exhausted"
        " FROM youtube_quota_buckets WHERE quota_day = DATE '2026-09-29'",
    ) == settled
    _apply(dsn, *all_postgres_migrations())
    assert _one(
        dsn,
        "SELECT quota_day, bucket, used, scheduled_used, exhausted"
        " FROM youtube_quota_buckets WHERE quota_day = DATE '2026-09-29'",
    ) == settled
