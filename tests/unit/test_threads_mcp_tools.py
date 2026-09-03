import json
from unittest.mock import AsyncMock, patch

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
@pytest.mark.parametrize("cleared,expected_fragment", [(True, "revoked"), (False, "No active")])
async def test_clear_threads_auth_reports_outcome(cleared, expected_fragment):
    auth_mgr = AsyncMock()
    auth_mgr.clear_auth.return_value = cleared

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"threads_auth_manager": auth_mgr}):
        res = json.loads(await handle_clear_threads_auth())

    assert res["cleared"] is cleared
    assert expected_fragment in res["message"]
