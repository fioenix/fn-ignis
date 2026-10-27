"""Spec 020 foundation contracts on both stores; host ingestion follows in later tasks."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest

from ignis.application.use_cases.host_browser_search import AttributionVocabularyMissing, HostBrowserSearchService
from ignis.domain.entities import ResearchMission, TrendSignal
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

SEED = Path(__file__).resolve().parents[2] / "sql/036_threads_attribution.sql"


@contextmanager
def connection(case):
    if case.name == "sqlite":
        with sqlite3.connect(case.repository._db_path) as conn:
            yield conn
    else:
        with psycopg.connect(case.dsn) as conn:
            yield conn


def storage_snapshot(case):
    with connection(case) as conn:
        evidence = {table: conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
                    for table in ("sources", "observations", "mission_evidence")}
        if case.name == "sqlite":
            schema = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master "
                                  "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        else:
            schema = [
                conn.execute("SELECT table_name, column_name, data_type, is_nullable, column_default "
                             "FROM information_schema.columns WHERE table_schema='public' "
                             "ORDER BY table_name, ordinal_position").fetchall(),
                conn.execute("SELECT tablename, indexname, indexdef FROM pg_indexes "
                             "WHERE schemaname='public' ORDER BY tablename, indexname").fetchall(),
                conn.execute("SELECT conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                             "JOIN pg_namespace n ON n.oid=c.connamespace WHERE n.nspname='public' "
                             "ORDER BY conname, c.conrelid").fetchall(),
            ]
        lexicons = conn.execute("SELECT * FROM market_lexicons WHERE domain <> 'threads_attribution' "
                                "ORDER BY domain, term").fetchall()
    return evidence, schema, lexicons


async def replay_seed(case):
    if case.name == "sqlite":
        reopened = SqliteTrendRepository(case.repository._db_path)
        try:
            await reopened._ensure_schema()
        finally:
            await reopened.close()
    else:
        with connection(case) as conn:
            conn.execute(SEED.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_threads_seed_is_available_to_repository_mission_vocabulary(repository_case):
    vocabulary = await load_market_vocabulary(repository_case.repository)
    assert vocabulary.threads_attribution == ["Photo by {author} on"]
    rows = await repository_case.repository.get_domain_lexicons("threads_attribution")
    assert [(r["term"], r["category"], r["created_by"]) for r in rows] == [
        ("Photo by {author} on", "ui_attribution", "system")]
    assert "Photo by {author} on" not in vocabulary.positive_terms


@pytest.mark.asyncio
async def test_threads_seed_replay_is_idempotent_without_schema_or_evidence_changes(repository_case):
    assert SEED.is_file(), "The approved seed must exist before exercising its replay"
    repo = repository_case.repository
    mission = await repo.create_mission(ResearchMission(title="Synthetic seed parity", keywords=["synthetic"]))
    await repo.save_signals([TrendSignal(platform=PlatformType.TIKTOK, raw_title="Synthetic existing content",
        source_url="https://www.tiktok.com/share/video/7417820067028536584", metric_value=0,
        mission_id=mission.id, metadata={"metric_known": False})])
    assert repository_case.counts()["observations"] == 1
    with connection(repository_case) as conn:
        conn.execute("DELETE FROM market_lexicons WHERE domain = 'threads_attribution'")
    before = storage_snapshot(repository_case)
    await replay_seed(repository_case)
    assert storage_snapshot(repository_case) == before
    first = await repo.get_domain_lexicons("threads_attribution")
    assert len(first) == 1 and first[0]["term"] == "Photo by {author} on"
    await replay_seed(repository_case)
    assert await repo.get_domain_lexicons("threads_attribution") == first
    assert storage_snapshot(repository_case) == before


@pytest.mark.asyncio
async def test_missing_mission_source_vocabulary_clears_stale_templates(repository_case):
    service = HostBrowserSearchService()
    try:
        frozen = await service.refresh_attribution_templates(repository_case.repository, source="threads")
        assert frozen == ("Photo by {author} on",)
        with connection(repository_case) as conn:
            conn.execute("DELETE FROM market_lexicons WHERE domain = 'threads_attribution'")
        with pytest.raises(AttributionVocabularyMissing):
            await service.refresh_attribution_templates(repository_case.repository, source="threads")
        assert frozen == ("Photo by {author} on",)
        with pytest.raises(AttributionVocabularyMissing):
            service.attribution_templates_for("threads")
        assert service.attribution_templates_for("tiktok")
    finally:
        service.close()
