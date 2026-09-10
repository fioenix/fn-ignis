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
# This is an API budget, not a tuning knob. A YouTube `search.list` call costs 100 quota units
# against a default 10,000 units/day, so 10 keywords is 1,000 units per pass and the daily quota
# covers 10 passes, which is where the worker's default 8640-second tick comes from. A
# 15-minute cadence would want 96 passes a day and blow the quota by mid-morning.
# An untargeted chart pull costs 1 unit, which is exactly why it was affordable and useless.
MAX_TOPIC_KEYWORDS = 10

# YouTube Data API v3 published costs: a `search.list` query is 100 units against a project's
# default allowance of 10,000 units/day. Both are Google's numbers, not tuning choices.
YOUTUBE_SEARCH_UNIT_COST = 100
YOUTUBE_DAILY_QUOTA_UNITS = 10_000


def quota_safe_interval_seconds(keywords_per_pass: int = MAX_TOPIC_KEYWORDS) -> int:
    """Shortest ingress cadence whose keyword probes still fit inside one day's YouTube quota.

    A topic-coupled pass spends real quota, so cadence and corpus quality trade against each
    other directly. The scheduler uses this to tell an operator when their configured interval
    will exhaust the daily allowance before the day is over.
    """
    per_pass = max(1, keywords_per_pass) * YOUTUBE_SEARCH_UNIT_COST
    passes_per_day = max(1, YOUTUBE_DAILY_QUOTA_UNITS // per_pass)
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
