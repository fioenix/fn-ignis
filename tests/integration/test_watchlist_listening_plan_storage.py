"""Spec 018: append-only plan storage, idempotence and owner-only PostgreSQL access."""
import asyncio
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from ignis.domain import watchlist
from ignis.domain.research_workspace import ResearchWorkspace

pytestmark = pytest.mark.asyncio


async def create(repository_case, tmp_path):
    repo = repository_case.repository
    workspace = ResearchWorkspace(slug='plans', root_path=tmp_path / 'plans')
    await repo.save_research_workspace(workspace)
    definition = watchlist.parse_watchlist_definition({'topics': [{'name': 'Demand', 'keywords': ['test']}]})
    saved = await repo.create_watchlist(workspace.workspace_id, 'Demand', definition)
    return repo, saved


async def test_history_is_ordered_and_identical_saves_insert_nothing(repository_case, tmp_path):
    repo, saved = await create(repository_case, tmp_path)
    assert hasattr(repo, 'save_listening_plan'), 'The repository must persist listening plans'
    assert await repo.list_listening_plans(saved.id) == []
    before = datetime.now(timezone.utc)
    plans, added = await repo.save_listening_plan(saved.id, 'Track demand.', 'week', 3)
    assert added and len(plans) == 1
    assert before <= plans[0].effective_from <= datetime.now(timezone.utc)
    same, added = await repo.save_listening_plan(saved.id, 'Track demand.', 'week', 3)
    assert not added and same == plans
    revised, added = await repo.save_listening_plan(saved.id, 'Track demand.', 'month', 4)
    assert added and [p.period_kind for p in revised] == ['week', 'month']
    assert revised == await repo.list_listening_plans(saved.id)
    assert revised[0].effective_from < revised[1].effective_from
    assert await repo.get_watchlist(saved.id) == saved


async def test_concurrent_identical_saves_are_idempotent(repository_case, tmp_path):
    repo, saved = await create(repository_case, tmp_path)
    assert hasattr(repo, 'save_listening_plan'), 'The repository must persist listening plans'
    results = await asyncio.gather(*(repo.save_listening_plan(saved.id, 'Track.', 'week', 3) for _ in range(4)))
    assert sum(added for _, added in results) == 1
    assert len(await repo.list_listening_plans(saved.id)) == 1


async def test_unknown_and_invalid_plans_write_nothing(repository_case, tmp_path):
    repo, saved = await create(repository_case, tmp_path)
    assert hasattr(repo, 'save_listening_plan'), 'The repository must persist listening plans'
    with pytest.raises(watchlist.WatchlistConflict) as caught:
        await repo.save_listening_plan(uuid4(), 'Track.', 'day', 1)
    assert caught.value.code == 'NOT_FOUND'
    with pytest.raises(ValueError) as caught:
        await repo.save_listening_plan(saved.id, 'Track.', 'day', 2)
    assert caught.value.code == 'INVALID_LISTENING_PLAN'
    assert await repo.list_listening_plans(saved.id) == []


async def test_updates_are_refused_and_deletion_cascades(repository_case, tmp_path):
    repo, saved = await create(repository_case, tmp_path)
    assert hasattr(repo, 'save_listening_plan'), 'The repository must persist listening plans'
    await repo.save_listening_plan(saved.id, 'Track.', 'week', 3)
    if repository_case.name == 'sqlite':
        with sqlite3.connect(repo._db_path) as conn:
            conn.execute('PRAGMA foreign_keys = ON')
            with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                conn.execute("UPDATE watchlist_listening_plans SET goal = 'Changed.'")
            conn.execute('DELETE FROM watchlists WHERE id = ?', (saved.id,))
    else:
        with psycopg.connect(repository_case.dsn, autocommit=True) as conn:
            with pytest.raises(psycopg.errors.CheckViolation, match='immutable'):
                conn.execute("UPDATE watchlist_listening_plans SET goal = 'Changed.'")
            conn.execute('DELETE FROM watchlists WHERE id = %s', (saved.id,))
    assert await repo.list_listening_plans(saved.id) == []


async def test_postgres_plans_enable_rls_and_revoke_client_grants(repository_case, tmp_path):
    if repository_case.name != 'postgres':
        pytest.skip('PostgreSQL RLS contract')
    await create(repository_case, tmp_path)
    with psycopg.connect(repository_case.dsn) as conn:
        assert conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'public.watchlist_listening_plans'::regclass").fetchone() == (True,)
        assert conn.execute("SELECT grantee FROM information_schema.table_privileges WHERE table_name = 'watchlist_listening_plans' AND grantee IN ('PUBLIC', 'anon', 'authenticated')").fetchall() == []
