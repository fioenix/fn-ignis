from __future__ import annotations

import logging
from typing import Dict, Iterable, List, Optional, Tuple

import cachetools

from ignis.config import settings

logger = logging.getLogger(__name__)


class InsightsTTLCache:
    """
    Bounded in-memory TTL cache for Meta Graph API per-post insight metrics.

    The worker daemon re-scans the same window every 15 minutes, so without a cache
    each pass re-issues one insights request per post (N+1) against a 200 calls/user/hour
    budget. Post-level insights for already-published content move slowly, so a 2-hour
    TTL removes the repeat traffic without meaningfully ageing the numbers.
    """

    def __init__(self, maxsize: int = 5000, ttl_seconds: Optional[int] = None):
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.META_INSIGHTS_CACHE_TTL_SECONDS
        self._cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=maxsize, ttl=self._ttl)
        self._hits = 0
        self._misses = 0

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl)

    @staticmethod
    def _key(platform: str, post_id: str, metrics: str) -> Tuple[str, str, str]:
        return (platform, str(post_id), metrics)

    def get(self, platform: str, post_id: str, metrics: str) -> Optional[Dict[str, float]]:
        value = self._cache.get(self._key(platform, post_id, metrics))
        if value is None:
            self._misses += 1
            return None
        self._hits += 1
        return dict(value)

    def set(self, platform: str, post_id: str, metrics: str, value: Dict[str, float]) -> None:
        self._cache[self._key(platform, post_id, metrics)] = dict(value)

    def partition(
        self,
        platform: str,
        post_ids: Iterable[str],
        metrics: str,
    ) -> Tuple[Dict[str, Dict[str, float]], List[str]]:
        """Split the requested ids into already-cached metrics and the ids still to fetch."""
        cached: Dict[str, Dict[str, float]] = {}
        missing: List[str] = []
        for post_id in post_ids:
            hit = self.get(platform, post_id, metrics)
            if hit is None:
                missing.append(post_id)
            else:
                cached[post_id] = hit
        if cached:
            logger.info(
                f"Insights cache served {len(cached)} {platform} posts from memory "
                f"({len(missing)} still need a Graph API call)."
            )
        return cached, missing

    def stats(self) -> Dict[str, int]:
        return {
            "entries": len(self._cache),
            "maxsize": self._cache.maxsize,
            "ttl_seconds": self.ttl_seconds,
            "hits": self._hits,
            "misses": self._misses,
        }

    def clear(self) -> None:
        self._cache.clear()
        self._hits = 0
        self._misses = 0
