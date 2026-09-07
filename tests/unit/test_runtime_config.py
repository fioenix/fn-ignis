from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from ignis.infrastructure.config.runtime_config_manager import RuntimeConfigManager
from ignis.infrastructure.connectors.meta_browser_ingress import (
    get_threads_graphql_endpoint,
    get_threads_web_client_id,
)
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.mark.asyncio
async def test_sqlite_runtime_configs_crud_and_initial_seeds():
    repo = SqliteTrendRepository("sqlite:///:memory:")
    try:
        # Check initial seeds
        client_id = await repo.get_runtime_config("threads_web_client_id")
        assert client_id == "238260118693652"

        endpoint = await repo.get_runtime_config("threads_graphql_endpoint")
        assert endpoint == "https://www.threads.net/api/graphql"

        all_configs = await repo.get_all_runtime_configs()
        assert len(all_configs) >= 5

        # Update / Insert config
        await repo.set_runtime_config(
            key="test_param",
            value="123456",
            category="test",
            description="Test parameter",
            updated_by="tester",
        )
        val = await repo.get_runtime_config("test_param")
        assert val == "123456"

        test_configs = await repo.get_all_runtime_configs(category="test")
        assert len(test_configs) == 1
        assert test_configs[0]["key"] == "test_param"

        # Delete config
        deleted = await repo.delete_runtime_config("test_param")
        assert deleted is True
        assert await repo.get_runtime_config("test_param") is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_runtime_config_manager_caching_and_write_through():
    mock_repo = AsyncMock()
    mock_repo.get_runtime_config.return_value = "custom_client_id_999"

    mgr = RuntimeConfigManager(repository=mock_repo)
    # Clear cache for key
    mgr._cache.pop("threads_web_client_id", None)

    # First read: cache miss, calls repository
    val = await mgr.get("threads_web_client_id")
    assert val == "custom_client_id_999"
    mock_repo.get_runtime_config.assert_awaited_once_with("threads_web_client_id")

    # Second read: cache hit, does not call repository again
    mock_repo.get_runtime_config.reset_mock()
    val2 = await mgr.get("threads_web_client_id")
    assert val2 == "custom_client_id_999"
    mock_repo.get_runtime_config.assert_not_awaited()

    # Synchronous read
    sync_val = mgr.get_sync("threads_web_client_id")
    assert sync_val == "custom_client_id_999"

    # Write-Through: set updates both cache and DB
    await mgr.set("threads_web_client_id", "new_client_id_888", updated_by="agent")
    assert mgr.get_sync("threads_web_client_id") == "new_client_id_888"
    mock_repo.set_runtime_config.assert_awaited_once()

    # Refresh
    mock_repo.get_all_runtime_configs.return_value = [
        {"key": "threads_web_client_id", "value": "refreshed_id_777"}
    ]
    refreshed = await mgr.refresh()
    assert refreshed["threads_web_client_id"] == "refreshed_id_777"


@pytest.mark.asyncio
async def test_runtime_config_mcp_tools():
    from ignis.interfaces.mcp.server import (
        handle_get_runtime_config,
        handle_refresh_runtime_config_cache,
        handle_update_runtime_config,
    )

    mock_mgr = AsyncMock()
    mock_mgr.get.return_value = "238260118693652"
    mock_mgr.get_all.return_value = [{"key": "threads_web_client_id", "value": "238260118693652"}]
    mock_mgr.refresh.return_value = {"threads_web_client_id": "238260118693652"}

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"runtime_config_manager": mock_mgr}):
        # 1. get single key
        res_single = json.loads(await handle_get_runtime_config(key="threads_web_client_id"))
        assert res_single["status"] == "SUCCESS"
        assert res_single["value"] == "238260118693652"

        # 2. get all configs
        res_all = json.loads(await handle_get_runtime_config())
        assert res_all["status"] == "SUCCESS"
        assert res_all["total_configs"] == 1

        # 3. update config
        res_update = json.loads(
            await handle_update_runtime_config(
                key="threads_web_client_id",
                value="updated_999",
                category="threads",
            )
        )
        assert res_update["status"] == "SUCCESS"
        mock_mgr.set.assert_awaited_once()

        # 4. refresh cache
        res_refresh = json.loads(await handle_refresh_runtime_config_cache())
        assert res_refresh["status"] == "SUCCESS"
        assert "threads_web_client_id" in res_refresh["cached_keys"]


def test_meta_browser_ingress_dynamic_parameters():
    mgr = RuntimeConfigManager.get_instance()
    mgr._cache["threads_web_client_id"] = "dynamic_client_id_456"
    mgr._cache["threads_graphql_endpoint"] = "https://www.threads.net/custom/graphql"

    assert get_threads_web_client_id() == "dynamic_client_id_456"
    assert get_threads_graphql_endpoint() == "https://www.threads.net/custom/graphql"
