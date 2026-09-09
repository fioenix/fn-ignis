"""One reader for the vocabulary that used to be Python constants.

Both entrypoints load the same rows from `market_lexicons` and push them into the same engines,
so the grouping lives here instead of being written twice. It also keeps one list of the domains
that are machinery rather than market evidence: those must stay out of the positive relevance
vocabulary, otherwise a stopword like "new" would count as a reason a signal is on topic.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List

from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)

# Domains whose terms drive a mechanism rather than describing a market.
MACHINERY_DOMAINS = frozenset({
    "foreign_stopwords",
    "noise_blacklist",
    "ambiguous_unigrams",
    "search_intent",
    "customer_inquiry",
})

# Probe templates are per geo, so their domain carries the geo code: probe_templates_vn.
PROBE_TEMPLATE_PREFIX = "probe_templates_"


@dataclass(frozen=True)
class MarketVocabulary:
    """The persisted vocabulary, split by the mechanism each domain feeds."""

    positive_terms: List[str] = field(default_factory=list)
    foreign_stopwords: List[str] = field(default_factory=list)
    noise_blacklist: List[str] = field(default_factory=list)
    ambiguous_unigrams: List[str] = field(default_factory=list)
    search_intent: List[str] = field(default_factory=list)
    customer_inquiry: List[str] = field(default_factory=list)
    probe_templates: Dict[str, List[str]] = field(default_factory=dict)
    by_domain_and_category: Dict[tuple, List[str]] = field(default_factory=dict)


async def load_market_vocabulary(repository: ITrendRepository) -> MarketVocabulary:
    """Read every lexicon row once and group it by the mechanism it feeds."""
    rows = await repository.get_domain_lexicons() or []

    grouped: Dict[str, List[str]] = {}
    buckets: Dict[tuple, List[str]] = {}
    for row in rows:
        term = str(row.get("term") or "").strip()
        if not term:
            continue
        domain = str(row.get("domain") or "")
        grouped.setdefault(domain, []).append(term)
        if domain not in MACHINERY_DOMAINS and not domain.startswith(PROBE_TEMPLATE_PREFIX):
            buckets.setdefault((domain, row.get("category")), []).append(term)

    probe_templates = {
        domain[len(PROBE_TEMPLATE_PREFIX):].upper(): patterns
        for domain, patterns in grouped.items()
        if domain.startswith(PROBE_TEMPLATE_PREFIX)
    }

    return MarketVocabulary(
        positive_terms=[t for terms in buckets.values() for t in terms],
        foreign_stopwords=grouped.get("foreign_stopwords", []),
        noise_blacklist=grouped.get("noise_blacklist", []),
        ambiguous_unigrams=grouped.get("ambiguous_unigrams", []),
        search_intent=grouped.get("search_intent", []),
        customer_inquiry=grouped.get("customer_inquiry", []),
        probe_templates=probe_templates,
        by_domain_and_category=buckets,
    )
