from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from ignis.application.ports.repository_port import ITrendRepository

logger = logging.getLogger(__name__)


class RuntimeConfigManager:
    """
    High-performance in-memory caching and persistent storage manager for dynamic runtime parameters.
    
    Prevents repeated SQLite I/O overhead by serving parameters directly from memory (0.01ms),
    while guaranteeing persistence through ITrendRepository and write-through updates.
    """

    _DEFAULTS: Dict[str, str] = {
        "threads_web_client_id": "238260118693652",
        "threads_graphql_endpoint": "https://www.threads.net/api/graphql",
        "threads_doc_id_trending_topics": "",
        "threads_doc_id_search_posts": "",
        "threads_doc_id_search_suggestions": "",
    }

    _singleton: Optional[RuntimeConfigManager] = None

    def __init__(self, repository: Optional[ITrendRepository] = None):
        self._repository = repository
        self._cache: Dict[str, str] = dict(self._DEFAULTS)
        self._lock = asyncio.Lock()
        self._loaded_from_db = False
        RuntimeConfigManager._singleton = self

    @classmethod
    def get_instance(cls) -> RuntimeConfigManager:
        if cls._singleton is None:
            cls._singleton = RuntimeConfigManager()
        return cls._singleton

    def set_repository(self, repository: ITrendRepository) -> None:
        self._repository = repository

    async def get(self, key: str, default: Optional[str] = None) -> str:
        """
        Fast lookup: returns from in-memory cache if present.
        On cache miss, loads from repository and populates cache.
        """
        if key in self._cache and self._cache[key]:
            return self._cache[key]

        if self._repository:
            try:
                db_val = await self._repository.get_runtime_config(key)
                if db_val is not None and db_val != "":
                    self._cache[key] = db_val
                    return db_val
            except Exception as e:
                logger.warning(f"Could not read runtime config '{key}' from repository: {e}")

        # Fallback to provided default or system default
        resolved = default if default is not None else self._DEFAULTS.get(key, "")
        if resolved:
            self._cache[key] = resolved
        return resolved

    def get_sync(self, key: str, default: Optional[str] = None) -> str:
        """Synchronous fast-read for hot paths without awaiting."""
        if key in self._cache and self._cache[key]:
            return self._cache[key]
        return default if default is not None else self._DEFAULTS.get(key, "")

    async def set(
        self,
        key: str,
        value: str,
        category: str = "connector",
        description: Optional[str] = None,
        updated_by: str = "system",
    ) -> None:
        """
        Write-Through update: persists immediately to SQLite and updates in-memory cache.
        """
        self._cache[key] = str(value)
        if self._repository:
            try:
                await self._repository.set_runtime_config(
                    key=key,
                    value=str(value),
                    category=category,
                    description=description,
                    updated_by=updated_by,
                )
                logger.info(f"Runtime config '{key}' updated by [{updated_by}].")
            except Exception as e:
                logger.error(f"Failed to persist runtime config '{key}' to repository: {e}")

    async def get_all(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve full list of configurations from repository with cache fallback."""
        if self._repository:
            try:
                records = await self._repository.get_all_runtime_configs(category=category)
                # Keep cache synchronized
                for r in records:
                    self._cache[r["key"]] = str(r["value"])
                return records
            except Exception as e:
                logger.warning(f"Failed to fetch runtime configs from repository: {e}")

        # Fallback to in-memory items
        return [
            {
                "key": k,
                "value": v,
                "category": "connector",
                "description": "In-memory default configuration",
                "updated_by": "memory",
            }
            for k, v in self._cache.items()
            if not category or category in k
        ]

    async def refresh(self) -> Dict[str, str]:
        """Invalidates in-memory cache and reloads all parameters from database."""
        async with self._lock:
            self._cache = dict(self._DEFAULTS)
            if self._repository:
                try:
                    records = await self._repository.get_all_runtime_configs()
                    for r in records:
                        self._cache[r["key"]] = str(r["value"])
                    self._loaded_from_db = True
                    logger.info(f"Refreshed {len(records)} runtime configurations into cache.")
                except Exception as e:
                    logger.error(f"Failed to refresh runtime configs from database: {e}")
            return dict(self._cache)

    async def delete(self, key: str) -> bool:
        """Delete config parameter from database and cache."""
        self._cache.pop(key, None)
        if self._repository:
            try:
                return await self._repository.delete_runtime_config(key)
            except Exception as e:
                logger.error(f"Failed to delete runtime config '{key}': {e}")
                return False
        return True
