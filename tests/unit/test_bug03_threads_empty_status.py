import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from ignis.interfaces.mcp.server import (
    handle_get_threads_trending_topics,
    handle_get_threads_search_suggestions,
)


@pytest.mark.asyncio
async def test_bug03_threads_trending_topics_empty_returns_parse_empty():
    """AC-1: get_threads_trending_topics must report PARSE_EMPTY on zero topics, never SUCCESS."""
    mock_plugin = AsyncMock()
    mock_plugin.resolve_auth_tier.return_value = ("session_cookies", {"cookies": []})
    mock_plugin.fetch_trending_topics.return_value = []

    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = mock_plugin

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"registry": mock_registry}):
        res_str = await handle_get_threads_trending_topics(geo="VN", limit=10)
        res = json.loads(res_str)

        assert res["status"] == "PARSE_EMPTY"
        assert res["total_topics"] == 0
        assert "Today's Topics" in res["message"]


@pytest.mark.asyncio
async def test_bug03_threads_search_suggestions_empty_returns_parse_empty():
    """AC-2: get_threads_search_suggestions must report PARSE_EMPTY on zero suggestions, never SUCCESS."""
    mock_plugin = AsyncMock()
    mock_plugin.resolve_auth_tier.return_value = ("session_cookies", {"cookies": []})
    mock_plugin.fetch_search_suggestions.return_value = []

    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = mock_plugin

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"registry": mock_registry}):
        res_str = await handle_get_threads_search_suggestions(keyword="nonexistent keyword", geo="VN", limit=5)
        res = json.loads(res_str)

        assert res["status"] == "PARSE_EMPTY"
        assert res["total_suggestions"] == 0
        assert "No search suggestions returned" in res["message"]


@pytest.mark.asyncio
async def test_bug03_threads_unauthenticated_returns_auth_required():
    """AC-3: an unauthenticated platform (tier == 'none') reports AUTH_REQUIRED."""
    mock_plugin = AsyncMock()
    mock_plugin.resolve_auth_tier.return_value = ("none", None)

    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = mock_plugin

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"registry": mock_registry}):
        res_str = await handle_get_threads_trending_topics(geo="VN")
        res = json.loads(res_str)
        assert res["status"] == "AUTH_REQUIRED"
        assert "authenticate_threads" in res["message"]

        res_sug_str = await handle_get_threads_search_suggestions(keyword="ai agent", geo="VN")
        res_sug = json.loads(res_sug_str)
        assert res_sug["status"] == "AUTH_REQUIRED"
