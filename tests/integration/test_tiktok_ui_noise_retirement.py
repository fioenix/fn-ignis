"""T016: three ordinary words leave the TikTok UI-noise vocabulary on both repositories.

The grid guard rejected 46 real titles in a 15,771-title sample, and three rows did nearly all of
it: the English "live" (40) and the Vietnamese words for "notification" (3) and "message" (2).
They are everyday words, not TikTok UI strings, and the connector never crawls the notification or
inbox surface they were copied from, so the privacy promise rests on that structure rather than on
these rows. The Vietnamese live-broadcast badge fired once and was right, and the remaining phrases
are specific UI wording; all of those stay.

A data migration rather than a seed edit, because an existing database has to lose the rows too,
and the SQLite bootstrap re-inserts `013_tiktok_ui_noise.sql` on every start -- so on SQLite the
retirement has to run after that replay, or a restart puts the rows straight back.
"""
import re

import pytest

from ignis.infrastructure.config.vocabulary_loader import load_market_vocabulary

from conftest import REPO_SQL, all_postgres_migrations

DOMAIN = "tiktok_ui_noise"
RETIREMENT = "020_retire_ambiguous_tiktok_ui_noise.sql"
# Test data naming what T016 removes. The vocabulary itself stays in sql/.
RETIRED = {"live", "thông báo", "tin nhắn"}


def _seeded_ui_noise() -> set:
    """What 013 seeds for the domain, stripped the way the plugin strips at registration."""
    text = (REPO_SQL / "013_tiktok_ui_noise.sql").read_text(encoding="utf-8")
    return {
        term.strip()
        for domain, term, _category in re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", text)
        if domain == DOMAIN
    }


KEPT = _seeded_ui_noise() - RETIRED


def _terms(rows) -> set:
    return {term.strip() for _domain, term, _category, _by in rows}


async def _open_fresh(case):
    """A fresh SQLite bootstrap or a fresh portable PostgreSQL migration contract."""
    if case.name == "postgres":
        case.apply(*all_postgres_migrations())
    repository = case.repository()
    await load_market_vocabulary(repository)
    return repository


def test_the_seed_still_carries_the_retired_rows_so_the_premise_is_real():
    """013 has shipped and is not rewritten; the retirement is what removes the rows."""
    assert RETIRED <= _seeded_ui_noise()
    assert "đang phát trực tiếp" in KEPT


@pytest.mark.asyncio
async def test_a_fresh_repository_schema_ends_with_only_the_kept_rows(lexicon_case):
    repository = await _open_fresh(lexicon_case)
    await repository.close()

    stored = _terms(lexicon_case.rows(DOMAIN))

    assert stored == KEPT, f"retired={sorted(stored & RETIRED)} missing={sorted(KEPT - stored)}"


@pytest.mark.asyncio
async def test_an_existing_database_loses_exactly_the_three_rows(lexicon_case):
    """Only the three rows go: no other domain and no other tiktok_ui_noise term is touched."""
    if lexicon_case.name == "postgres":
        lexicon_case.apply(*(m for m in all_postgres_migrations() if m != RETIREMENT))
        before = lexicon_case.rows()
        lexicon_case.apply(RETIREMENT)
    else:
        # An older build's database: bootstrapped, and still holding the rows 013 put there.
        repository = lexicon_case.repository()
        await load_market_vocabulary(repository)
        await repository.close()
        for term in ("live ", "thông báo", "tin nhắn"):
            lexicon_case.execute(
                # OR IGNORE: before T016 the bootstrap already holds these rows.
                "INSERT OR IGNORE INTO market_lexicons"
                " (id, domain, term, category, created_by, created_at)"
                " VALUES (lower(hex(randomblob(16))), ?, ?, 'ui_noise', 'system', 'x')",
                "",
                (DOMAIN, term),
            )
        before = lexicon_case.rows()
        restarted = lexicon_case.repository()
        await load_market_vocabulary(restarted)
        await restarted.close()

    after = lexicon_case.rows()
    removed = sorted(set(before) - set(after))

    assert _terms(removed) == RETIRED
    assert len(removed) == 3
    assert set(after) <= set(before), "the retirement added rows"


@pytest.mark.asyncio
async def test_re_applying_and_restarting_never_bring_the_rows_back(lexicon_case):
    repository = await _open_fresh(lexicon_case)
    await repository.close()
    settled = lexicon_case.rows()

    if lexicon_case.name == "postgres":
        lexicon_case.apply(RETIREMENT, RETIREMENT)
        # 013 re-run by hand, as an operator replaying seeds would, then the retirement again.
        lexicon_case.apply("013_tiktok_ui_noise.sql", RETIREMENT)
    for _ in range(2):
        restarted = lexicon_case.repository()
        await load_market_vocabulary(restarted)
        await restarted.close()

    assert lexicon_case.rows() == settled
