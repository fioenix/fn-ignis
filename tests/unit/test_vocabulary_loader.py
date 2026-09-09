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
    TEMPLATE_PREFIXES,
    load_market_vocabulary,
)
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.harness.language_detector import HeuristicLanguageDetector
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

SQL = Path(__file__).resolve().parents[2] / "sql"
# Both files the SQLite bootstrap re-applies. Keep in step with sqlite_repository.
SEEDS = (
    "012_vocabulary_from_constants.sql",
    "013_tiktok_ui_noise.sql",
    "014_language_detection_vocabulary.sql",
)


def _seeded_domains():
    domains = {}
    for name in SEEDS:
        text = (SQL / name).read_text(encoding="utf-8")
        for domain, term, _category in re.findall(
            r"\('([^']+)',\s*'([^']+)',\s*'([^']+)'", text
        ):
            domains.setdefault(domain, []).append(term)
    return domains


def test_the_seed_covers_every_domain_the_loader_reads():
    """A domain the loader looks for but nothing seeds is a mechanism switched off in silence."""
    seeded = set(_seeded_domains())
    expected = (MACHINERY_DOMAINS - {"foreign_stopwords", "noise_blacklist"}) | {
        "probe_templates_vn",
        "probe_templates_default",
        "tiktok_suggest_templates_vn",
        "tiktok_suggest_templates_default",
    }

    assert expected <= seeded, f"Domains missing from the seed: {sorted(expected - seeded)}"


def test_every_probe_template_has_a_substitution_slot():
    """A template without {} would probe a literal string instead of the keyword."""
    for domain, templates in _seeded_domains().items():
        if not any(domain.startswith(prefix) for prefix in TEMPLATE_PREFIXES):
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
        assert not any(domain.startswith(prefix) for prefix in TEMPLATE_PREFIXES)

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


@pytest.mark.asyncio
async def test_load_bearing_whitespace_survives_the_database_round_trip(tmp_path):
    """The TikTok live badge is seeded as "live " so it cannot match inside "livestream".

    An earlier version of the loader stripped every term, which passed the plugin's own unit
    test -- that one registers the list by hand -- and only showed up when the vocabulary came
    from a real database. So this assertion goes through the repository, not around it.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "whitespace.db"))
    vocabulary = await load_market_vocabulary(repo)

    assert "live " in vocabulary.tiktok_ui_noise

    plugin = TikTokPlugin()
    plugin.register_ui_noise(vocabulary.tiktok_ui_noise)

    assert plugin._is_private_or_notification("live  ngay bay gio") is True
    assert plugin._is_private_or_notification("livestream review") is False


@pytest.mark.asyncio
async def test_the_tiktok_grid_guard_is_armed_by_a_fresh_database(tmp_path):
    """Fail-closed only works if bootstrap actually arms it; otherwise ingress returns nothing."""
    repo = SqliteTrendRepository(db_path=str(tmp_path / "tiktok.db"))
    vocabulary = await load_market_vocabulary(repo)

    plugin = TikTokPlugin()
    plugin.register_ui_noise(vocabulary.tiktok_ui_noise)
    plugin.register_suggest_templates(vocabulary.tiktok_suggest_templates)

    assert plugin._is_private_or_notification("#congnghe2026 AI Agent sieu hot") is False
    assert plugin._intent_probe_templates("VN")
    assert plugin._intent_probe_templates("US") != plugin._intent_probe_templates("VN")


@pytest.mark.asyncio
async def test_a_fresh_database_arms_language_detection(tmp_path):
    """Without these two lists a Portuguese title reads as English and lands in a US corpus."""
    repo = SqliteTrendRepository(db_path=str(tmp_path / "language.db"))
    vocabulary = await load_market_vocabulary(repo)

    detector = HeuristicLanguageDetector()
    detector.register_foreign_phrases(vocabulary.foreign_phrases)
    detector.register_portuguese_words(vocabulary.portuguese_words)

    assert detector.is_localized("Como criar agentes autonomos para empresas", geo=GeoCode.US) is False
    assert detector.is_localized("Formation complete avec n8n", geo=GeoCode.US) is False
    assert detector.is_localized("Building autonomous AI agents with LangChain", geo=GeoCode.US) is True
