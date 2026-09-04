import json
from unittest.mock import AsyncMock, patch

import pytest

from ignis.domain.exceptions import EncryptionKeyMissingException
from ignis.interfaces.mcp.server import (
    handle_authenticate_instagram,
    handle_authenticate_threads,
    handle_clear_instagram_auth,
    handle_get_instagram_auth_status,
)


def _components(oauth, browser=None):
    return {
        "instagram_auth_manager": oauth,
        "instagram_browser_auth_manager": browser,
        "threads_auth_manager": oauth,
        "threads_browser_auth_manager": browser,
    }


@pytest.mark.asyncio
async def test_authenticate_instagram_runs_the_oauth_flow_when_given_a_code():
    oauth = AsyncMock()
    oauth.exchange_code_for_token.return_value = {
        "success": True,
        "platform": "instagram",
        "auth_type": "oauth2",
        "days_remaining": 59.9,
        "encrypted_at_rest": True,
    }
    browser = AsyncMock()

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_authenticate_instagram(auth_code="IGQW..."))

    assert res["success"] is True
    assert res["encrypted_at_rest"] is True
    assert oauth.exchange_code_for_token.await_args.kwargs["auth_code"] == "IGQW..."
    browser.authenticate_interactive.assert_not_awaited()


@pytest.mark.asyncio
async def test_authenticate_instagram_forwards_explicit_app_credentials():
    oauth = AsyncMock()
    oauth.exchange_code_for_token.return_value = {"success": True, "platform": "instagram"}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth)):
        await handle_authenticate_instagram(
            auth_code="CODE",
            client_id="APP_ID",
            client_secret="APP_SECRET",
            redirect_uri="http://localhost:8000/oauth/callback",
        )

    kwargs = oauth.exchange_code_for_token.await_args.kwargs
    assert kwargs["client_id"] == "APP_ID"
    assert kwargs["client_secret"] == "APP_SECRET"
    assert kwargs["redirect_uri"] == "http://localhost:8000/oauth/callback"


@pytest.mark.asyncio
async def test_authenticate_instagram_surfaces_missing_encryption_key_instead_of_crashing():
    oauth = AsyncMock()
    oauth.exchange_code_for_token.side_effect = EncryptionKeyMissingException(
        "Instagram OAuth 2.0 credential storage requires a persistent IGNIS_ENCRYPTION_KEY."
    )

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth)):
        res = json.loads(await handle_authenticate_instagram(auth_code="CODE"))

    assert res["success"] is False
    assert res["error_type"] == "EncryptionKeyMissingException"
    assert res["tier"] == "TIER_2_GRAPH_API"
    assert "IGNIS_ENCRYPTION_KEY" in res["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"auth_code": "   "}, {"auth_code": "CODE", "browser_login": True}],
    ids=["no_args", "blank_code", "explicit_browser_login"],
)
async def test_tier1_browser_capture_is_chosen_without_a_usable_auth_code(kwargs):
    oauth = AsyncMock()
    browser = AsyncMock()
    browser.authenticate_interactive.return_value = {
        "success": True,
        "platform": "instagram_browser",
        "tier": "TIER_1_BROWSER_SESSION",
        "cookies_count": 7,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_authenticate_instagram(**kwargs))

    assert res["tier"] == "TIER_1_BROWSER_SESSION"
    assert res["cookies_count"] == 7
    oauth.exchange_code_for_token.assert_not_awaited()
    browser.authenticate_interactive.assert_awaited_once()


@pytest.mark.asyncio
async def test_threads_tool_shares_the_same_dual_ux_routing():
    oauth = AsyncMock()
    browser = AsyncMock()
    browser.authenticate_interactive.return_value = {"success": True, "tier": "TIER_1_BROWSER_SESSION"}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_authenticate_threads(browser_login=True, headless=True, timeout_seconds=45))

    assert res["tier"] == "TIER_1_BROWSER_SESSION"
    kwargs = browser.authenticate_interactive.await_args.kwargs
    assert kwargs == {"headless": True, "timeout_seconds": 45}


@pytest.mark.asyncio
async def test_browser_capture_failure_is_reported_not_raised():
    oauth = AsyncMock()
    browser = AsyncMock()
    browser.authenticate_interactive.side_effect = RuntimeError("Playwright is not installed.")

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_authenticate_instagram())

    assert res["success"] is False
    assert res["tier"] == "TIER_1_BROWSER_SESSION"
    assert res["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_get_instagram_auth_status_merges_both_tiers():
    oauth = AsyncMock()
    oauth.get_auth_status.return_value = {
        "platform": "instagram",
        "authenticated": True,
        "status": "ACTIVE",
        "days_remaining": 42.0,
    }
    browser = AsyncMock()
    browser.get_auth_status.return_value = {
        "platform": "instagram_browser",
        "authenticated": True,
        "status": "ACTIVE",
        "cookies_count": 9,
    }

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_get_instagram_auth_status())

    assert res["status"] == "ACTIVE"
    assert res["browser_session"]["cookies_count"] == 9


@pytest.mark.asyncio
async def test_get_instagram_auth_status_works_without_a_browser_manager():
    oauth = AsyncMock()
    oauth.get_auth_status.return_value = {"platform": "instagram", "status": "NOT_CONNECTED"}

    with patch("ignis.interfaces.mcp.server.get_components", return_value={"instagram_auth_manager": oauth}):
        res = json.loads(await handle_get_instagram_auth_status())

    assert res["status"] == "NOT_CONNECTED"
    assert "browser_session" not in res


@pytest.mark.asyncio
@pytest.mark.parametrize("cleared,expected_fragment", [(True, "revoked"), (False, "No active")])
async def test_clear_instagram_auth_clears_both_tiers(cleared, expected_fragment):
    oauth = AsyncMock()
    oauth.clear_auth.return_value = cleared
    browser = AsyncMock()
    browser.clear_auth.return_value = cleared

    with patch("ignis.interfaces.mcp.server.get_components", return_value=_components(oauth, browser)):
        res = json.loads(await handle_clear_instagram_auth())

    assert res["platform"] == "instagram"
    assert res["cleared"] is cleared
    assert res["browser_session_cleared"] is cleared
    assert expected_fragment in res["message"]
