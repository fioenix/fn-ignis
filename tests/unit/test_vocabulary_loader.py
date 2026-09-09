"""The vocabulary that used to be Python constants has to survive the trip through the database.

Four constants moved into market_lexicons. Each one drives a mechanism that fails quietly when
its rows are missing: clustering over-merges, demand is measured from the bare keyword, and no
comment is recognised as a question. These tests fail when a domain stops arriving.
"""

import re
from pathlib import Path

import pytest

from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.config.vocabulary_loader import (
    MACHINERY_DOMAINS,
    PROBE_TEMPLATE_PREFIX,
    load_market_vocabulary,
)
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

SEED = Path(__file__).resolve().parents[2] / "sql" / "012_vocabulary_from_constants.sql"


def _seeded_domains():
    rows = re.findall(r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", SEED.read_text(encoding="utf-8"))
    domains = {}
    for domain, term, _category in rows:
        domains.setdefault(domain, []).append(term)
    return domains


def test_the_seed_covers_every_domain_the_loader_reads():
    """A domain the loader looks for but nothing seeds is a mechanism switched off in silence."""
    seeded = set(_seeded_domains())
    expected = (MACHINERY_DOMAINS - {"foreign_stopwords", "noise_blacklist"}) | {
        "probe_templates_vn",
        "probe_templates_default",
    }

    assert expected <= seeded, f"Domains missing from the seed: {sorted(expected - seeded)}"


def test_every_probe_template_has_a_substitution_slot():
    """A template without {} would probe a literal string instead of the keyword."""
    for domain, templates in _seeded_domains().items():
        if not domain.startswith(PROBE_TEMPLATE_PREFIX):
            continue
        for template in templates:
            assert "{}" in template, f"{domain} template cannot take a keyword: {template!r}"


@pytest.mark.asyncio
async def test_a_fresh_database_arms_both_engines(tmp_path):
    """Bootstrap has to leave the clusterer and the Google Trends plugin usable, not empty."""
    repo = SqliteTrendRepository(db_path=str(tmp_path / "vocabulary.db"))
    vocabulary = await load_market_vocabulary(repo)

    clusterer = SemanticClusterer()
    clusterer.register_ambiguous_unigrams(vocabulary.ambiguous_unigrams)
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates(vocabulary.probe_templates)
    plugin.register_intent_keywords(vocabulary.search_intent)

    assert clusterer._ambiguous_unigrams, "clustering would merge on any single shared word"
    assert len(plugin._get_probe_patterns("VN")) > 1, "demand would rest on the bare keyword"
    assert plugin._get_probe_patterns("US") != plugin._get_probe_patterns("VN")
    assert plugin._intent_keywords, "commercial intent would always score zero"
    assert vocabulary.customer_inquiry, "no comment could be recognised as a question"


@pytest.mark.asyncio
async def test_an_existing_database_picks_up_the_vocabulary(tmp_path):
    """These domains are re-applied on every bootstrap, so a pre-012 file upgrades itself."""
    db_path = str(tmp_path / "existing.db")
    repo = SqliteTrendRepository(db_path=db_path)
    await load_market_vocabulary(repo)

    import sqlite3

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM market_lexicons WHERE domain IN "
            "('ambiguous_unigrams', 'search_intent', 'customer_inquiry') "
            "OR domain LIKE 'probe_templates_%'"
        )
        conn.commit()
    finally:
        conn.close()

    reopened = await load_market_vocabulary(SqliteTrendRepository(db_path=db_path))

    assert reopened.ambiguous_unigrams
    assert reopened.search_intent
    assert reopened.customer_inquiry
    assert reopened.probe_templates


@pytest.mark.asyncio
async def test_machinery_domains_never_become_evidence_of_relevance(tmp_path):
    """'new' and '?' drive mechanisms. Counting them as topic terms would inflate every score.

    A word may legitimately sit in both kinds of domain -- "review" is a real market term and
    also a question marker -- so what matters is which domain a term was counted under, not
    whether the word appears somewhere in the machinery lists.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "machinery.db"))
    vocabulary = await load_market_vocabulary(repo)

    for domain, _category in vocabulary.by_domain_and_category:
        assert domain not in MACHINERY_DOMAINS, f"{domain} is machinery, not market evidence"
        assert not domain.startswith(PROBE_TEMPLATE_PREFIX)

    # Terms that exist nowhere but a machinery domain must never reach the positive vocabulary.
    market_terms = {t for terms in vocabulary.by_domain_and_category.values() for t in terms}
    machinery_only = (
        set(vocabulary.ambiguous_unigrams) | set(vocabulary.customer_inquiry)
    ) - market_terms
    assert machinery_only, "the fixture proves nothing if every machinery term is also a topic"
    assert not (machinery_only & set(vocabulary.positive_terms))


def test_an_empty_registration_is_refused_rather_than_armed():
    """Registering nothing must not look like a successful load."""
    clusterer = SemanticClusterer()
    clusterer.register_ambiguous_unigrams([])

    assert clusterer._ambiguous_unigrams == set()
