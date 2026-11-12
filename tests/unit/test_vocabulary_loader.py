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
# Vocabulary seeds replayed by SQLite bootstrap. Keep in step with sqlite_repository.
SEEDS = (
    "012_vocabulary_from_constants.sql",
    "013_tiktok_ui_noise.sql",
    "014_language_detection_vocabulary.sql",
    "034_tiktok_attribution.sql",
    "036_threads_attribution.sql",
    "037_threads_action_labels.sql",
    "038_tiktok_attribution_locales.sql",
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
    assert reopened.probe_templates



def test_an_empty_registration_is_refused_rather_than_armed():
    """Registering nothing must not look like a successful load."""
    clusterer = SemanticClusterer()
    clusterer.register_ambiguous_unigrams([])

    assert clusterer._ambiguous_unigrams == set()


@pytest.mark.asyncio
async def test_the_retired_live_term_does_not_come_back_through_the_database(tmp_path):
    """T016 retired "live" from the grid guard: it rejected 40 real public titles.

    013 still seeds it as "live " and the SQLite bootstrap replays 013 on every start, so the
    retirement in 020 has to run after that replay. A hand-registered list would not notice if it
    ran first; this goes through the repository, which is where the ordering lives.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "retired.db"))
    vocabulary = await load_market_vocabulary(repo)

    assert "live" not in {term.strip() for term in vocabulary.tiktok_ui_noise}

    plugin = TikTokPlugin()
    plugin.register_ui_noise(vocabulary.tiktok_ui_noise)

    assert plugin._is_private_or_notification("Studio 2.0 is live.") is False
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


def test_the_machinery_list_is_not_duplicated_in_the_use_cases():
    """Two copies of this list is what caused the leak; the second copy must stay gone."""
    src = Path(__file__).resolve().parents[2] / "src" / "ignis"
    offenders = [
        path.relative_to(src).as_posix()
        for path in src.rglob("*.py")
        if "__pycache__" not in path.parts
        and "NON_TOPIC_LEXICON_DOMAINS" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, (
        "MACHINERY_DOMAINS in vocabulary_loader is the only list of non-topic domains. "
        f"Found a second one in: {offenders}"
    )


@pytest.mark.asyncio
async def test_a_fresh_database_arms_the_tiktok_attribution_guard(tmp_path):
    """Host excerpts are cleaned only if bootstrap seeds the attribution templates (Spec 012 FR-012)."""
    from ignis.infrastructure.security.pii_sanitizer import strip_platform_attribution

    repo = SqliteTrendRepository(db_path=str(tmp_path / "attribution.db"))
    vocabulary = await load_market_vocabulary(repo)

    assert vocabulary.tiktok_attribution
    assert all("{author}" in template for template in vocabulary.tiktok_attribution)
    label = "Túi đẹp nha #tuidilam do Fixture Poster tạo với bản nhạc Peace"
    assert strip_platform_attribution(label, vocabulary.tiktok_attribution) == "Túi đẹp nha #tuidilam"


@pytest.mark.asyncio
async def test_the_synchronizer_does_not_promote_caller_templates_into_tactical_search(tmp_path):
    from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer

    repo = SqliteTrendRepository(db_path=str(tmp_path / "sync.db"))
    await repo.register_lexicon_terms("tiktok_attribution", ["created by {author} with"], "ui_attribution")
    service = HostBrowserSearchService()
    before = service.attribution_templates_for()
    try:
        await VocabularySynchronizer(repo).synchronize()
        assert service.attribution_templates_for() == before
        frozen = await service.refresh_attribution_templates(repo)
        assert "created by {author} with" in frozen
    finally:
        service.close()
        await repo.close()


@pytest.mark.asyncio
async def test_threads_attribution_is_loaded_as_machinery_not_positive_evidence(tmp_path):
    from ignis.infrastructure.security.pii_sanitizer import strip_platform_attribution

    repo = SqliteTrendRepository(str(tmp_path / "threads-vocabulary.db"))
    try:
        vocabulary = await load_market_vocabulary(repo)
        assert vocabulary.threads_attribution == ["Photo by {author} on"]
        assert strip_platform_attribution("Synthetic body Photo by Synthetic Sentinel on October 28",
                                          vocabulary.threads_attribution) == "Synthetic body"
    finally:
        await repo.close()


def test_tactical_threads_templates_come_from_the_packaged_seed_and_never_tiktok():
    from ignis.application.use_cases.host_browser_search import AttributionVocabularyMissing, HostBrowserSearchService

    service = HostBrowserSearchService()
    try:
        assert service.attribution_templates_for("threads") == ("Photo by {author} on",)
        service.register_attribution_templates([], source="threads")
        assert service.attribution_templates_for("tiktok")
        with pytest.raises(AttributionVocabularyMissing):
            service.attribution_templates_for("threads")
    finally:
        service.close()


@pytest.mark.asyncio
async def test_mission_refresh_freezes_local_templates_without_replacing_tactical_sources(tmp_path):
    import sqlite3
    from ignis.application.use_cases.host_browser_search import AttributionVocabularyMissing, HostBrowserSearchService

    repo = SqliteTrendRepository(str(tmp_path / "threads-refresh.db"))
    service = HostBrowserSearchService()
    try:
        await repo.register_lexicon_terms("threads_attribution", ["observed fixture {author} suffix"], "ui_attribution")
        frozen = await service.refresh_attribution_templates(repo, source="threads")
        assert frozen == ("Photo by {author} on", "observed fixture {author} suffix")
        with sqlite3.connect(repo._db_path) as conn:
            conn.execute("DELETE FROM market_lexicons WHERE domain = 'threads_attribution'")
        with pytest.raises(AttributionVocabularyMissing):
            await service.refresh_attribution_templates(repo, source="threads")
        assert frozen == ("Photo by {author} on", "observed fixture {author} suffix")
        assert service.attribution_templates_for("tiktok")
        assert service.attribution_templates_for("threads") == ("Photo by {author} on",)
    finally:
        service.close()
        await repo.close()


@pytest.mark.asyncio
async def test_synchronizer_missing_caller_vocabulary_leaves_packaged_templates_intact(tmp_path):
    import sqlite3
    from ignis.application.use_cases.host_browser_search import HostBrowserSearchService
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer

    repo = SqliteTrendRepository(str(tmp_path / "threads-sync.db"))
    service = HostBrowserSearchService()
    try:
        await repo.get_domain_lexicons()
        with sqlite3.connect(repo._db_path) as conn:
            conn.execute("DELETE FROM market_lexicons WHERE domain = 'threads_attribution'")
        await VocabularySynchronizer(repo).synchronize_vocabulary()
        assert service.attribution_templates_for("threads") == ("Photo by {author} on",)
        assert service.attribution_templates_for("tiktok")
    finally:
        service.close()
        await repo.close()


@pytest.mark.asyncio
async def test_missing_mission_tiktok_templates_fail_before_ticket_freeze_or_relay(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from ignis.application.use_cases import host_browser_search as module
    from ignis.application.use_cases import host_browser_mission

    repo = SqliteTrendRepository(str(tmp_path / "missing-tiktok.db"))
    service = module.HostBrowserSearchService()
    try:
        await repo.get_domain_lexicons()
        with sqlite3.connect(repo._db_path) as conn:
            conn.execute("DELETE FROM market_lexicons WHERE domain = 'tiktok_attribution'")
        monkeypatch.setattr(host_browser_mission, "prepare_scope", AsyncMock(return_value={
            "queries": ["synthetic"], "plan": {"plan_digest": "p" * 64}}))
        def forbid_relay(*args):
            pytest.fail("Missing source vocabulary must refuse before opening the relay")
        monkeypatch.setattr(module, "LoopbackRelay", forbid_relay)
        with pytest.raises(module.AttributionVocabularyMissing):
            await service.prepare_mission(SimpleNamespace(_repo=repo), "mission", "task", "session", 60, True)
    finally:
        service.close()
        await repo.close()


@pytest.mark.asyncio
async def test_mission_ticket_keeps_its_repository_templates_across_an_interleaved_refresh(tmp_path, monkeypatch):
    import sqlite3
    import runpy
    from types import SimpleNamespace
    from ignis.application.use_cases import host_browser_search as module
    from ignis.application.use_cases import host_browser_mission

    class NoSocketRelay:
        url = "http://127.0.0.1:0/synthetic-relay"
        tab_script = "synthetic script"

        def __init__(self, *args):
            pass

        def close(self):
            pass

    repo = SqliteTrendRepository(str(tmp_path / "interleaved-vocabulary.db"))
    service = module.HostBrowserSearchService()
    unit = runpy.run_path(str(Path(__file__).with_name("test_host_browser_search.py")))
    try:
        await repo.register_lexicon_terms("tiktok_attribution_en", ["created by {author} with"], "ui_attribution")
        async def interleaved_scope(*args):
            with sqlite3.connect(repo._db_path) as connection:
                connection.execute("DELETE FROM market_lexicons WHERE domain = 'tiktok_attribution_en'")
            await repo.register_lexicon_terms("tiktok_attribution_en", ["another wording {author} with"], "ui_attribution")
            return {"queries": ["túi đi làm"], "plan": {"plan_digest": "p" * 64}, "digest": "d" * 64,
                    "source": "tiktok", "host_sources": ("tiktok",), "required_host_sources": ("tiktok",)}
        monkeypatch.setattr(host_browser_mission, "prepare_scope", interleaved_scope)
        monkeypatch.setattr(module, "LoopbackRelay", NoSocketRelay)
        request = await service.prepare_mission(SimpleNamespace(_repo=repo, _registry=SimpleNamespace(self_identities=())), "mission", "task-1", "chrome-1", 60, True)
        payload = unit["answer"](request)
        payload["answers"][0]["locale"] = "en"
        payload["answers"][0]["records"][0]["excerpt"] = "Synthetic body created by Synthetic Sentinel with sound"
        current_locales = module.attribution_locales_from_rows(await repo.get_domain_lexicons())
        assert current_locales["en"] == ("another wording {author} with",)
        assert service._tickets[request["request_id"]]["attribution_locales"]["en"] == ("created by {author} with",)
        service.stage(request["request_id"], payload)
        held = service._tickets[request["request_id"]]["receipt"]
        assert held["observations"][0]["excerpt"] == "Synthetic body"
    finally:
        service.close()
        await repo.close()


@pytest.mark.asyncio
async def test_t058_mission_missing_locale_vocabulary_refuses_before_relay(tmp_path, monkeypatch):
    import sqlite3
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    from ignis.application.use_cases import host_browser_search as module
    from ignis.application.use_cases import host_browser_mission

    repo = SqliteTrendRepository(str(tmp_path / "missing-locales.db"))
    service = module.HostBrowserSearchService()
    relay = Mock(side_effect=AssertionError("Missing locales must refuse before relay creation"))
    monkeypatch.setattr(module, "LoopbackRelay", relay)
    scope = AsyncMock(return_value={"queries": ["synthetic"], "plan": {"plan_digest": "p" * 64},
                                   "digest": "d" * 64})
    monkeypatch.setattr(host_browser_mission, "prepare_scope", scope)
    try:
        await repo.get_domain_lexicons()
        with sqlite3.connect(repo._db_path) as connection:
            connection.execute("DELETE FROM market_lexicons WHERE domain GLOB 'tiktok_attribution_*'")
        assert await service.refresh_attribution_templates(repo)
        with pytest.raises(module.AttributionVocabularyMissing, match="attribution"):
            await service.prepare_mission(
                SimpleNamespace(_repo=repo, _registry=SimpleNamespace(self_identities=())),
                "mission", "task", "session", 60, True,
            )
        relay.assert_not_called()
        assert service._tickets == {}
    finally:
        service.close()
        await repo.close()


def test_review_synchronizer_cannot_receive_the_process_global_host_template_service():
    """Caller vocabulary sync must not retain a route into tactical packaged templates."""
    import inspect
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    assert "host_browser_search" not in inspect.signature(VocabularySynchronizer).parameters


@pytest.mark.asyncio
async def test_synchronizer_never_reads_taxonomy_and_preserves_machinery(tmp_path, monkeypatch):
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    repo = SqliteTrendRepository(str(tmp_path / 'retained.sqlite3'))
    async def forbidden():
        pytest.fail('taxonomy read is forbidden')
    monkeypatch.setattr(repo, 'get_industry_taxonomies', forbidden, raising=False)
    clusterer = SemanticClusterer()
    detector = HeuristicLanguageDetector()
    vocabulary = await VocabularySynchronizer(
        repo, clusterer=clusterer, language_detector=detector,
    ).synchronize_vocabulary()
    assert clusterer._ambiguous_unigrams and clusterer._custom_stopwords
    assert vocabulary.foreign_phrases and vocabulary.portuguese_words
    assert vocabulary.tiktok_ui_noise
    await repo.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("title,keyword", [
    ("Lazada sale 11.11 giảm giá", "shopee"),
    ("How to make bánh mì tại nhà", "n8n"),
])
async def test_market_buckets_do_not_expand_topic_keywords(tmp_path, title, keyword):
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
    repo = SqliteTrendRepository(str(tmp_path / "market.db"))
    try:
        await repo.register_lexicon_terms("ecommerce", ["shopee", "lazada"], "marketplace")
        await repo.register_lexicon_terms("tech", ["n8n", "make", "zapier", "chatbot"], "automation")
        reasoner = StrategicMarketReasoner()
        await VocabularySynchronizer(repo, strategic_reasoner=reasoner).synchronize_vocabulary()
        assert not reasoner._matches_topic_strictly(title, keyword)
        assert reasoner._matches_topic_strictly(f"Hướng dẫn {keyword}", keyword)
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_market_terms_do_not_count_as_vietnamese_core_words(tmp_path):
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
    repo = SqliteTrendRepository(str(tmp_path / "localization.db"))
    try:
        await repo.register_lexicon_terms("tech", ["make", "chatbot", "n8n", "zapier"], "automation")
        quality, reasoner = QualityEvaluator(), StrategicMarketReasoner()
        await VocabularySynchronizer(repo, quality_evaluator=quality, strategic_reasoner=reasoner).synchronize_vocabulary()
        title = "Make a chatbot with n8n and zapier"
        assert not quality.is_localized(title)
        assert not quality.is_vietnamese(title)
        assert not reasoner._is_vietnamese(title)
        assert quality.is_localized("Hướng dẫn tự động hóa công việc")
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_synchronization_preserves_machinery_registration(tmp_path):
    from ignis.infrastructure.config.vocabulary_loader import VocabularySynchronizer
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
    from unittest.mock import Mock
    repo = SqliteTrendRepository(str(tmp_path / "machinery-parity.db"))
    try:
        quality, reasoner = QualityEvaluator(), StrategicMarketReasoner()
        clusterer, detector = Mock(), Mock()
        vocabulary = await VocabularySynchronizer(
            repo, quality_evaluator=quality, strategic_reasoner=reasoner,
            clusterer=clusterer, language_detector=detector,
        ).synchronize_vocabulary()
        assert vocabulary.foreign_stopwords and vocabulary.noise_blacklist
        assert vocabulary.ambiguous_unigrams and vocabulary.foreign_phrases and vocabulary.portuguese_words
        for engine in (quality, reasoner):
            assert set(vocabulary.foreign_stopwords) <= engine._custom_stopwords
            assert set(vocabulary.noise_blacklist) <= engine._custom_noise
        clusterer.register_ambiguous_unigrams.assert_called_once_with(vocabulary.ambiguous_unigrams)
        detector.register_foreign_phrases.assert_called_once_with(vocabulary.foreign_phrases)
        detector.register_portuguese_words.assert_called_once_with(vocabulary.portuguese_words)
        assert clusterer.register_stopwords.call_count == 2
    finally:
        await repo.close()


MARKET_DOMAIN_COUNTS = {
    "tech": 24, "ecommerce": 21, "fashion": 15, "common_vi": 9,
    "global_saas_ai": 15, "global_ecommerce": 11, "global_fashion": 9,
}


@pytest.mark.asyncio
async def test_fresh_store_has_no_system_market_domain_vocabulary(tmp_path):
    repo = SqliteTrendRepository(str(tmp_path / "fresh-retired.db"))
    try:
        rows = await repo.get_domain_lexicons()
        assert [r for r in rows if r["domain"] in MARKET_DOMAIN_COUNTS and r["created_by"] == "system"] == []
        assert len([r for r in rows if r["domain"] == "foreign_stopwords"]) == 19
        assert len([r for r in rows if r["domain"] == "noise_blacklist"]) == 19
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_upgrade_retires_104_system_rows_but_preserves_operator_and_machinery(tmp_path):
    import sqlite3
    from uuid import uuid4
    path = str(tmp_path / "upgrade-retired.db")
    repo = SqliteTrendRepository(path)
    await repo._ensure_schema()
    await repo.close()
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM market_lexicons WHERE domain IN (%s)" % ','.join('?' for _ in MARKET_DOMAIN_COUNTS), tuple(MARKET_DOMAIN_COUNTS))
        conn.executemany(
            "INSERT INTO market_lexicons (id, domain, term, category, created_by, created_at) VALUES (?, ?, ?, 'fixture', 'system', '2026-11-11')",
            [(str(uuid4()), domain, f"legacy term {i}") for domain, count in MARKET_DOMAIN_COUNTS.items() for i in range(count)],
        )
        conn.execute("INSERT INTO market_lexicons (id, domain, term, created_by, created_at) VALUES (?, 'tech', 'operator term', 'operator', '2026-11-11')", (str(uuid4()),))
        before = conn.execute("SELECT * FROM market_lexicons WHERE domain NOT IN (%s) ORDER BY id" % ','.join('?' for _ in MARKET_DOMAIN_COUNTS), tuple(MARKET_DOMAIN_COUNTS)).fetchall()
        assert conn.execute("SELECT count(*) FROM market_lexicons WHERE category='fixture'").fetchone() == (104,)
    for _ in range(2):
        repo = SqliteTrendRepository(path)
        try:
            rows = await repo.get_domain_lexicons()
            assert [r for r in rows if r["domain"] in MARKET_DOMAIN_COUNTS and r["created_by"] == "system"] == []
            assert [(r["term"], r["created_by"]) for r in rows if r["domain"] == "tech"] == [("operator term", "operator")]
        finally:
            await repo.close()
        with sqlite3.connect(path) as conn:
            after = conn.execute("SELECT * FROM market_lexicons WHERE domain NOT IN (%s) ORDER BY id" % ','.join('?' for _ in MARKET_DOMAIN_COUNTS), tuple(MARKET_DOMAIN_COUNTS)).fetchall()
            assert after == before


def test_templates_are_keyed_by_source_name_not_platform(monkeypatch):
    """A source whose platform differs from its name (Instagram is `reels`) keeps its own templates."""
    import dataclasses
    from ignis.application.use_cases import host_browser_search as module
    from ignis.domain.host_browser_sources import get_source

    renamed = dataclasses.replace(get_source("threads"), platform="reels")
    real = module.get_source
    monkeypatch.setattr(module, "get_source", lambda source: renamed if source == "fixture" else real(source))
    service = module.HostBrowserSearchService()
    try:
        with pytest.raises(module.AttributionVocabularyMissing):
            service.attribution_templates_for("fixture")
        service.register_attribution_templates(["fixture {author} suffix"], source="fixture")
        assert service.attribution_templates_for("fixture") == ("fixture {author} suffix",)
        assert service.attribution_templates_for("threads") == ("Photo by {author} on",)
    finally:
        service.close()
