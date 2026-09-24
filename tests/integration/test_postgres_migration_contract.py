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

import re
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg import errors, sql

from conftest import (
    REPO_SQL,
    SUPABASE_ROLES,
    all_postgres_migrations,
    existing_supabase_roles,
)
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository

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
