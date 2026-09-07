import logging
from typing import Any, Dict, List, Optional

from ignis.application.ports.repository_port import ITrendRepository
from ignis.domain.value_objects import GeoCode, IngressScope, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

logger = logging.getLogger(__name__)

# Lexicon domains that hold negative vocabulary rather than topics to probe for.
NON_TOPIC_LEXICON_DOMAINS = ("foreign_stopwords", "noise_blacklist")
# How many seed keywords a public pass hands to a connector that has no public feed of its own.
MAX_SEED_KEYWORDS = 10


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

        The pass is public-market by default: connectors whose only feed is the operator's own
        account are probed by keyword instead, seeded from the persisted market lexicon, and any
        self-authored signal that still slips through is dropped by the registry's scope guard.
        Callers wanting the operator's own posts ask for `IngressScope.OWN_PROFILE` explicitly.
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
            if str(item.get("domain") or "").strip().lower() in NON_TOPIC_LEXICON_DOMAINS:
                continue
            term = str(item.get("term") or "").strip()
            if term and term not in seeds:
                seeds.append(term)
        return seeds[:MAX_SEED_KEYWORDS]
