import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.exceptions import EncryptionKeyMissingException
from ignis.interfaces.mcp.server import (
    handle_authenticate_threads,
    handle_clear_threads_auth,
    handle_get_threads_auth_status,
)


@pytest.mark.asyncio
async def test_authenticate_threads_returns_secret_free_success_payload():
    auth_mgr = AsyncMock()
    auth_mgr.exchange_code_for_token.return_value = {
        "success": True,
        "platform": "threads",
        "auth_type": "oauth2",
        "message": "Threads OAuth 2.0 authentication successful.",
        "key_version": "v1",
        "days_remaining": 59.98,
        "encrypted_at_rest": True,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"threads_auth_manager": auth_mgr}):
        res = json.loads(await handle_authenticate_threads(auth_code="CODE_ABC"))

    assert res["success"] is True
    assert res["encrypted_at_rest"] is True
    assert auth_mgr.exchange_code_for_token.await_args.kwargs["auth_code"] == "CODE_ABC"


@pytest.mark.asyncio
async def test_authenticate_threads_surfaces_missing_encryption_key_instead_of_crashing():
    auth_mgr = AsyncMock()
    auth_mgr.exchange_code_for_token.side_effect = EncryptionKeyMissingException(
        "Threads OAuth 2.0 credential storage requires a persistent IGNIS_ENCRYPTION_KEY."
    )

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"threads_auth_manager": auth_mgr}):
        res = json.loads(await handle_authenticate_threads(auth_code="CODE_ABC"))

    assert res["success"] is False
    assert res["error_type"] == "EncryptionKeyMissingException"
    assert "IGNIS_ENCRYPTION_KEY" in res["message"]


@pytest.mark.asyncio
async def test_get_threads_auth_status_passes_through_manager_report():
    auth_mgr = AsyncMock()
    auth_mgr.get_auth_status.return_value = {
        "platform": "threads",
        "authenticated": True,
        "status": "NEEDS_REFRESH",
        "days_remaining": 4.1,
        "refresh_threshold_days": 10,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"threads_auth_manager": auth_mgr}):
        res = json.loads(await handle_get_threads_auth_status())

    assert res["status"] == "NEEDS_REFRESH"
    assert res["refresh_threshold_days"] == 10


@pytest.mark.asyncio
# "revoked" was the old wording and was wrong: nothing is sent to Meta, so the token stayed
# valid while the operator was told otherwise. The success path now states local deletion.
@pytest.mark.parametrize("cleared,expected_fragment", [(True, "deleted from local"), (False, "No stored")])
async def test_clear_threads_auth_reports_outcome(cleared, expected_fragment):
    auth_mgr = AsyncMock()
    auth_mgr.clear_auth.return_value = cleared

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"threads_auth_manager": auth_mgr}):
        res = json.loads(await handle_clear_threads_auth())

    assert res["cleared"] is cleared
    assert expected_fragment in res["message"]


@pytest.mark.asyncio
async def test_get_threads_trending_topics_mcp_tool():
    from ignis.interfaces.mcp.server import handle_get_threads_trending_topics

    mock_plugin = AsyncMock()
    mock_plugin.fetch_trending_topics.return_value = [
        {"topic": "AI Coding", "post_count": 5000, "post_count_label": "5K posts"}
    ]
    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = mock_plugin

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"registry": mock_registry}):
        res = json.loads(await handle_get_threads_trending_topics(geo="VN", limit=5))

    assert res["status"] == "SUCCESS"
    assert res["platform"] == "THREADS"
    assert res["total_topics"] == 1
    assert res["topics"][0]["topic"] == "AI Coding"


@pytest.mark.asyncio
async def test_get_threads_search_suggestions_mcp_tool():
    from ignis.interfaces.mcp.server import handle_get_threads_search_suggestions

    mock_plugin = AsyncMock()
    mock_plugin.fetch_search_suggestions.return_value = [
        "ai coding agent",
        "ai coding assistant",
    ]
    mock_registry = MagicMock()
    mock_registry.get_plugin.return_value = mock_plugin

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"registry": mock_registry}):
        res = json.loads(await handle_get_threads_search_suggestions(keyword="ai coding", geo="VN", limit=5))

    assert res["status"] == "SUCCESS"
    assert res["keyword"] == "ai coding"
    assert res["total_suggestions"] == 2
    assert "ai coding agent" in res["suggestions"]

