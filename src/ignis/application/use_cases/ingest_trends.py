import logging
from typing import Any, Dict, List

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.value_objects import GeoCode, IngressScope, Timeframe
from ignis.infrastructure.config.vocabulary_loader import (
    MACHINERY_DOMAINS,
    TEMPLATE_PREFIXES,
)
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)

# Lexicon domains that hold negative vocabulary rather than topics to probe for.
# Which lexicon domains are not topics is decided in one place, by the vocabulary loader.
# Keeping a second copy here is what let eight machinery domains added on 2026-09-09 fall
# straight through into the probe seeds: every seed a public pass probed with was a Vietnamese
# function word, because ambiguous_unigrams sorts first alphabetically and filled the budget.
# How many seed keywords a public pass hands to a connector that has no public feed of its own.
MAX_SEED_KEYWORDS = 10
# Total keywords one pass may probe with, lexicon seeds and freshly discovered topics combined.
#
# Each YouTube keyword consumes one `search.list` call. Google accounts for those calls in their
# own 100-call daily bucket; fn-ignis reserves 70 of them for scheduled work and leaves at least
# 30 for requested research. The persisted admission ledger is authoritative. The arithmetic
# below is only an operator warning and intentionally does not change the existing cadence.
MAX_TOPIC_KEYWORDS = 10

YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT = 70


def quota_safe_interval_seconds(
    keywords_per_pass: int = MAX_TOPIC_KEYWORDS,
    scheduled_search_daily_limit: int = YOUTUBE_SCHEDULED_SEARCH_DAILY_LIMIT,
) -> int:
    """Shortest advisory cadence that fits the scheduled search-call allocation.

    The database ledger remains the hard boundary because worker and MCP calls share one key and
    a scheduler tick can land at any point in the provider's Pacific-Time quota day.
    """
    passes_per_day = max(1, scheduled_search_daily_limit // max(1, keywords_per_pass))
    return 86_400 // passes_per_day


class IngestTrendsUseCase:
    """
    Use Case orchestrating automated trend signal ingress across all registered Connector Plugins.
    Enforces Zero-Token Ingress and strict Error Isolation.
    """

    def __init__(self, registry: ConnectorPluginRegistry, repository: ITrendRepository):
        self._registry = registry
        self._repo = repository

    async def execute(
        self,
        geo: GeoCode = GeoCode.VN,
        timeframe: Timeframe = Timeframe.LAST_24H,
        scope: IngressScope = IngressScope.PUBLIC_MARKET,
    ) -> Dict[str, Any]:
        """Run one ingress pass.

        The pass is public-market by default and runs topic-coupled: the feeds that discover
        topics are pulled first, then those topics plus the persisted market lexicon are probed
        by keyword across the remaining connectors, so several platforms report on the same
        subject and a cluster can span them. Connectors whose only feed is the operator's own
        account take the same keyword route, and any self-authored signal that still slips
        through is dropped by the registry's scope guard. Callers wanting the operator's own
        posts ask for `IngressScope.OWN_PROFILE` explicitly.
        """
        logger.info(
            f"Starting Ingest pipeline for geo={geo.value}, timeframe={timeframe.value}, scope={scope.value}..."
        )

        seed_keywords = await self.load_seed_keywords() if scope.includes_public else []
        signals = await self._registry.fetch_from_all(
            geo=geo,
            timeframe=timeframe,
            scope=scope,
            seed_keywords=seed_keywords,
            max_probe_keywords=MAX_TOPIC_KEYWORDS,
        )
        saved_count = await self._repo.save_signals(signals)

        result = {
            "geo": geo.value,
            "timeframe": timeframe.value,
            "scope": scope.value,
            "total_fetched": len(signals),
            "total_saved": saved_count,
            "seed_keywords_used": len(seed_keywords),
            "scope_guard": dict(getattr(self._registry, "last_pass_report", {}) or {}),
        }
        logger.info(f"Ingest pipeline completed: {result}")
        return result

    async def load_seed_keywords(self) -> List[str]:
        """Read probe seeds from the persisted market lexicon, never from a constant in code."""
        try:
            lexicons = await self._repo.get_domain_lexicons()
        except Exception as e:
            logger.warning(f"Could not load seed keywords from the market lexicon: {e}")
            return []

        seeds: List[str] = []
        for item in lexicons or []:
            domain = str(item.get("domain") or "").strip().lower()
            if domain in MACHINERY_DOMAINS or domain.startswith(TEMPLATE_PREFIXES):
                continue
            term = str(item.get("term") or "").strip()
            if term and term not in seeds:
                seeds.append(term)
        return seeds[:MAX_SEED_KEYWORDS]
