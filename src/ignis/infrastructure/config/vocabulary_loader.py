"""One reader for the vocabulary that used to be Python constants.

Both entrypoints load the same rows from `market_lexicons` and push them into the same engines,
so the grouping lives here instead of being written twice. It also keeps one list of the domains
that are machinery rather than market evidence: those must stay out of the positive relevance
vocabulary, otherwise a stopword like "new" would count as a reason a signal is on topic.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.exceptions import VocabularySynchronizationError

logger = logging.getLogger(__name__)

# Domains whose terms drive a mechanism rather than describing a market.
MACHINERY_DOMAINS = frozenset({
    "foreign_stopwords",
    "noise_blacklist",
    "ambiguous_unigrams",
    "search_intent",
    "customer_inquiry",
    "tiktok_ui_noise",
    "foreign_phrases",
    "portuguese_words",
})

# Probe templates are per geo, so their domain carries the geo code: probe_templates_vn.
PROBE_TEMPLATE_PREFIX = "probe_templates_"
TIKTOK_SUGGEST_TEMPLATE_PREFIX = "tiktok_suggest_templates_"

# Every domain holding query templates rather than terms. None of them is market evidence.
TEMPLATE_PREFIXES = (PROBE_TEMPLATE_PREFIX, TIKTOK_SUGGEST_TEMPLATE_PREFIX)


def _is_template_domain(domain: str) -> bool:
    return any(domain.startswith(prefix) for prefix in TEMPLATE_PREFIXES)


@dataclass(frozen=True)
class MarketVocabulary:
    """The persisted vocabulary, split by the mechanism each domain feeds."""

    positive_terms: List[str] = field(default_factory=list)
    foreign_stopwords: List[str] = field(default_factory=list)
    noise_blacklist: List[str] = field(default_factory=list)
    ambiguous_unigrams: List[str] = field(default_factory=list)
    search_intent: List[str] = field(default_factory=list)
    customer_inquiry: List[str] = field(default_factory=list)
    tiktok_ui_noise: List[str] = field(default_factory=list)
    foreign_phrases: List[str] = field(default_factory=list)
    portuguese_words: List[str] = field(default_factory=list)
    probe_templates: Dict[str, List[str]] = field(default_factory=dict)
    tiktok_suggest_templates: Dict[str, List[str]] = field(default_factory=dict)
    by_domain_and_category: Dict[tuple, List[str]] = field(default_factory=dict)


async def load_market_vocabulary(repository: ITrendRepository) -> MarketVocabulary:
    """Read every lexicon row once and group it by the mechanism it feeds."""
    rows = await repository.get_domain_lexicons() or []

    grouped: Dict[str, List[str]] = {}
    buckets: Dict[tuple, List[str]] = {}
    for row in rows:
        # Terms are passed on exactly as stored. Whitespace can be load-bearing: the TikTok
        # live badge is registered as "live " so it cannot match inside "livestream", and
        # stripping here silently removed that space. Each register_* normalises its own way.
        term = str(row.get("term") or "")
        if not term.strip():
            continue
        domain = str(row.get("domain") or "")
        grouped.setdefault(domain, []).append(term)
        if domain not in MACHINERY_DOMAINS and not _is_template_domain(domain):
            buckets.setdefault((domain, row.get("category")), []).append(term)

    def _templates_for(prefix: str) -> Dict[str, List[str]]:
        return {
            domain[len(prefix):].upper(): patterns
            for domain, patterns in grouped.items()
            if domain.startswith(prefix)
        }

    return MarketVocabulary(
        positive_terms=[t for terms in buckets.values() for t in terms],
        foreign_stopwords=grouped.get("foreign_stopwords", []),
        noise_blacklist=grouped.get("noise_blacklist", []),
        ambiguous_unigrams=grouped.get("ambiguous_unigrams", []),
        search_intent=grouped.get("search_intent", []),
        customer_inquiry=grouped.get("customer_inquiry", []),
        tiktok_ui_noise=grouped.get("tiktok_ui_noise", []),
        foreign_phrases=grouped.get("foreign_phrases", []),
        portuguese_words=grouped.get("portuguese_words", []),
        probe_templates=_templates_for(PROBE_TEMPLATE_PREFIX),
        tiktok_suggest_templates=_templates_for(TIKTOK_SUGGEST_TEMPLATE_PREFIX),
        by_domain_and_category=buckets,
    )


class VocabularySynchronizer:
    """Push the persisted vocabulary into the engines and connectors that depend on it.

    One synchronizer, called by every entry point that needs it, so the first mission after a
    process starts sees exactly what a process warmed by an earlier call would see. Every
    registration it performs replaces or unions, so calling it again changes nothing.

    Any engine left as None is skipped: a caller that holds only some of them synchronizes those.
    """

    def __init__(
        self,
        repository: ITrendRepository,
        *,
        quality_evaluator: Optional[Any] = None,
        strategic_reasoner: Optional[Any] = None,
        clusterer: Optional[Any] = None,
        google_trends_plugin: Optional[Any] = None,
        language_detector: Optional[Any] = None,
        tiktok_plugin: Optional[Any] = None,
        registry: Optional[Any] = None,
    ):
        self._repository = repository
        self._quality_evaluator = quality_evaluator
        self._strategic_reasoner = strategic_reasoner
        self._clusterer = clusterer
        self._google_trends_plugin = google_trends_plugin
        self._language_detector = language_detector
        self._tiktok_plugin = tiktok_plugin
        self._registry = registry
        self.self_identities: List[Any] = []

    async def synchronize(self) -> MarketVocabulary:
        """Synchronize everything, raising `VocabularySynchronizationError` on any failed read.

        The mission path calls this before a mission runs and lets the failure stop it.
        """
        vocabulary = await self.synchronize_vocabulary()
        await self.synchronize_self_identities()
        return vocabulary

    async def synchronize_vocabulary(self) -> MarketVocabulary:
        """Load market_lexicons and industry_taxonomies into every bound engine."""
        try:
            vocabulary = await load_market_vocabulary(self._repository)
            taxonomies = (
                await self._repository.get_industry_taxonomies()
                if self._clusterer is not None and hasattr(self._clusterer, "register_taxonomies")
                else None
            )
        except Exception as exc:
            raise VocabularySynchronizationError(
                f"Could not read the persisted vocabulary from the configured database: {exc}"
            ) from exc

        pos_terms = vocabulary.positive_terms
        stop_terms = vocabulary.foreign_stopwords
        noise_terms = vocabulary.noise_blacklist

        if pos_terms:
            for engine in (self._quality_evaluator, self._strategic_reasoner):
                if engine is not None:
                    engine.register_terms(pos_terms)
            if self._strategic_reasoner is not None:
                # Terms sharing a (domain, category) bucket are treated as expansions of each
                # other, so keyword matching uses the persisted vocabulary instead of hardcoded
                # synonyms.
                self._strategic_reasoner.register_synonym_groups(
                    [g for g in vocabulary.by_domain_and_category.values() if len(g) > 1]
                )
        if self._clusterer is not None:
            self._clusterer.register_ambiguous_unigrams(vocabulary.ambiguous_unigrams)
        if self._google_trends_plugin is not None:
            self._google_trends_plugin.register_probe_templates(vocabulary.probe_templates)
            self._google_trends_plugin.register_intent_keywords(vocabulary.search_intent)
        if self._language_detector is not None:
            self._language_detector.register_foreign_phrases(vocabulary.foreign_phrases)
            self._language_detector.register_portuguese_words(vocabulary.portuguese_words)
        if self._tiktok_plugin is not None:
            self._tiktok_plugin.register_ui_noise(vocabulary.tiktok_ui_noise)
            self._tiktok_plugin.register_suggest_templates(vocabulary.tiktok_suggest_templates)
        if stop_terms:
            for engine in (self._quality_evaluator, self._strategic_reasoner):
                if engine is not None:
                    engine.register_foreign_stopwords(stop_terms)
            if self._clusterer is not None and hasattr(self._clusterer, "register_stopwords"):
                self._clusterer.register_stopwords(stop_terms)
        if noise_terms:
            for engine in (self._quality_evaluator, self._strategic_reasoner):
                if engine is not None:
                    engine.register_noise_blacklist(noise_terms)
            if self._clusterer is not None and hasattr(self._clusterer, "register_stopwords"):
                self._clusterer.register_stopwords(noise_terms)
        if taxonomies:
            self._clusterer.register_taxonomies(taxonomies)
        return vocabulary

    async def synchronize_self_identities(self) -> List[Any]:
        """Bind the operator's own connected accounts so market passes can exclude their content."""
        if self._registry is None:
            return []
        # Imported here: the auth package reaches the credential store, which the vocabulary
        # half of this module has no reason to load.
        from ignis.infrastructure.auth.self_identity import SelfIdentityRegistry

        try:
            identities = await SelfIdentityRegistry(self._repository).load()
        except Exception as exc:
            raise VocabularySynchronizationError(
                f"Could not load the operator's own account identities: {exc}"
            ) from exc
        self._registry.register_self_identities(identities)
        self.self_identities = identities
        if identities:
            logger.info(
                "Self-content guard armed for: "
                + ", ".join(sorted({
                    f"{i.platform}:{i.normalized_username or i.normalized_account_id}"
                    for i in identities
                }))
            )
        else:
            logger.info(
                "No connected account identity is known, so self-authored content cannot be "
                "recognised. Set the 'self_accounts' runtime config to close that gap."
            )
        return identities
