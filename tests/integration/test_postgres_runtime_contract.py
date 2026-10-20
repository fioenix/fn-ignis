"""T017: the PostgreSQL adapter works as the runtime owner on a database the whole sql/ chain built.

These tests check the repository's behaviour, not the migrations, so they carry no
`migration_chain` marker and run on every pull request. They still apply the full chain, because
that is the schema a fresh Compose install hands the runtime.
"""

import asyncio
from datetime import date, datetime, timezone

import psycopg
import pytest

from conftest import REPO_SQL, all_postgres_migrations
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository
from ignis.domain.value_objects import IngressTrigger
from ignis.domain.youtube_quota import YouTubeQuotaBucket


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
                    trigger=IngressTrigger.REQUESTED,
                    daily_limit=7,
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
    assert usage[0].scheduled_used == 0
