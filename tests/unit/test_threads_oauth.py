import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ignis.domain.exceptions import (
    ConnectorAuthenticationException,
    EncryptionKeyMissingException,
)
from ignis.config import settings as crypto_settings
from ignis.infrastructure.auth.crypto import CryptoService, generate_new_key
from ignis.infrastructure.auth.meta_oauth import InstagramAuthManager, ThreadsAuthManager

FIXED_KEY = generate_new_key()

APP_KWARGS = {
    "client_id": "app-123",
    "client_secret": "secret-xyz",
    "redirect_uri": "https://finolabs.io/oauth/threads",
}


def _make_manager(repo=None, key: str | None = FIXED_KEY) -> ThreadsAuthManager:
    return ThreadsAuthManager(repository=repo, crypto_service=CryptoService(secret_key=key))


def _resp(status_code: int, payload=None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    if payload is None:
        resp.json.side_effect = ValueError("no json")
        resp.text = text
    else:
        resp.json.return_value = payload
        resp.text = json.dumps(payload)
    return resp


# --- OAuth 2.0 token exchange + long-lived upgrade ---


@pytest.mark.asyncio
async def test_exchange_code_upgrades_to_long_lived_token_and_persists_encrypted():
    repo = AsyncMock()
    mgr = _make_manager(repo)

    post_resp = _resp(200, {"access_token": "SHORT_LIVED_TOKEN", "user_id": "ig-user-9"})
    get_resp = _resp(200, {"access_token": "LONG_LIVED_TOKEN", "token_type": "bearer", "expires_in": 5183944})

    with patch("httpx.AsyncClient.post", return_value=post_resp) as mock_post, \
         patch("httpx.AsyncClient.get", return_value=get_resp) as mock_get:
        result = await mgr.exchange_code_for_token(auth_code="AUTH_CODE_ABC#_", **APP_KWARGS)

    # Meta appends '#_' to the redirected code; it must be stripped before exchange.
    posted = mock_post.call_args.kwargs["data"]
    assert posted["code"] == "AUTH_CODE_ABC"
    assert posted["grant_type"] == "authorization_code"
    assert posted["client_secret"] == "secret-xyz"

    # Short-lived token must be immediately upgraded via th_exchange_token.
    upgraded = mock_get.call_args.kwargs["params"]
    assert upgraded["grant_type"] == "th_exchange_token"
    assert upgraded["access_token"] == "SHORT_LIVED_TOKEN"

    # Persisted payload carries the long-lived token, key_version, and a ~60-day expiry.
    saved = repo.save_platform_credentials.await_args.kwargs
    assert saved["platform"] == "threads"
    assert saved["auth_type"] == "oauth2"
    record = saved["credentials_data"]
    assert record["access_token"] == "LONG_LIVED_TOKEN"
    assert record["client_secret"] == "secret-xyz"
    assert record["key_version"] == CryptoService.key_version
    assert record["long_lived"] is True
    assert 58 <= (saved["expires_at"] - datetime.now(timezone.utc)).days <= 60

    # The tool-facing response must never leak secret material.
    assert result["success"] is True
    assert result["encrypted_at_rest"] is True
    assert "access_token" not in result
    assert "client_secret" not in result
    assert "secret-xyz" not in json.dumps(result)


@pytest.mark.asyncio
async def test_exchange_code_fails_fast_without_persistent_encryption_key():
    repo = AsyncMock()
    mgr = _make_manager(repo, key=None)

    # Simulate an unconfigured deployment relying on the ephemeral in-memory key.
    with patch.object(crypto_settings, "IGNIS_ENCRYPTION_KEY", ""), \
         patch("httpx.AsyncClient.post") as mock_post:
        with pytest.raises(EncryptionKeyMissingException, match="IGNIS_ENCRYPTION_KEY"):
            await mgr.exchange_code_for_token(auth_code="AUTH_CODE", **APP_KWARGS)

    # The guard must trip before any token is requested or written.
    mock_post.assert_not_called()
    repo.save_platform_credentials.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_also_fails_fast_without_persistent_encryption_key():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = _stored(days_remaining=2)
    mgr = _make_manager(repo, key=None)

    with patch.object(crypto_settings, "IGNIS_ENCRYPTION_KEY", ""), \
         patch("httpx.AsyncClient.get") as mock_get:
        with pytest.raises(EncryptionKeyMissingException):
            await mgr.refresh_token_if_needed()

    mock_get.assert_not_called()


@pytest.mark.asyncio
async def test_exchange_code_requires_app_credentials():
    mgr = _make_manager(AsyncMock())
    with pytest.raises(ConnectorAuthenticationException, match="client_secret"):
        await mgr.exchange_code_for_token(auth_code="CODE", client_id="only-id", client_secret="")


@pytest.mark.asyncio
async def test_oauth_http_error_raises_and_writes_audit_log():
    repo = AsyncMock()
    mgr = _make_manager(repo)

    with patch("httpx.AsyncClient.post", return_value=_resp(400, {"error": {"message": "Invalid code"}})):
        with pytest.raises(ConnectorAuthenticationException, match="HTTP 400"):
            await mgr.exchange_code_for_token(auth_code="BAD_CODE", **APP_KWARGS)

    events = [c.kwargs["event_type"] for c in repo.log_event.await_args_list]
    assert "API_FAILURE" in events


# --- Long-lived token refresh loop ---


def _stored(days_remaining: float, token: str = "CURRENT_TOKEN", refresh_count: int = 0):
    expires_at = datetime.now(timezone.utc) + timedelta(days=days_remaining)
    return {
        "platform": "threads",
        "is_active": True,
        "credentials_data": {
            "access_token": token,
            "client_id": "app-123",
            "client_secret": "secret-xyz",
            "redirect_uri": APP_KWARGS["redirect_uri"],
            "scopes": ["threads_basic"],
            "key_version": "v1",
            "expires_at": expires_at.isoformat(),
            "refresh_count": refresh_count,
        },
    }


@pytest.mark.asyncio
async def test_refresh_skipped_while_token_is_still_fresh():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = _stored(days_remaining=45)
    mgr = _make_manager(repo)

    with patch("httpx.AsyncClient.get") as mock_get:
        result = await mgr.refresh_token_if_needed()

    assert result == {
        "refreshed": False,
        "reason": "TOKEN_STILL_FRESH",
        "days_remaining": result["days_remaining"],
        "threshold_days": 10,
    }
    assert result["days_remaining"] > 10
    mock_get.assert_not_called()
    repo.save_platform_credentials.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_triggered_when_under_ten_days_remaining():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = _stored(days_remaining=7, refresh_count=2)
    mgr = _make_manager(repo)

    refreshed = _resp(200, {"access_token": "REFRESHED_TOKEN", "expires_in": 5183944})
    with patch("httpx.AsyncClient.get", return_value=refreshed) as mock_get:
        result = await mgr.refresh_token_if_needed()

    params = mock_get.call_args.kwargs["params"]
    assert params["grant_type"] == "th_refresh_token"
    assert params["access_token"] == "CURRENT_TOKEN"
    assert mock_get.call_args.args[0] == ThreadsAuthManager.REFRESH_TOKEN_URL

    assert result["refreshed"] is True
    assert result["reason"] == "BELOW_THRESHOLD"
    assert result["refresh_count"] == 3

    record = repo.save_platform_credentials.await_args.kwargs["credentials_data"]
    assert record["access_token"] == "REFRESHED_TOKEN"
    # App credentials survive the rotation so future exchanges keep working.
    assert record["client_secret"] == "secret-xyz"


@pytest.mark.asyncio
async def test_refresh_returns_not_authenticated_without_stored_token():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = None
    mgr = _make_manager(repo)

    assert await mgr.refresh_token_if_needed() == {"refreshed": False, "reason": "NOT_AUTHENTICATED"}


@pytest.mark.asyncio
async def test_get_access_token_auto_refreshes_near_expiry():
    """A token inside the 10-day window is refreshed transparently before being handed out."""
    state = {"record": _stored(days_remaining=3)}

    repo = AsyncMock()

    async def _get(_platform):
        return state["record"]

    async def _save(**kwargs):
        state["record"] = {
            "platform": "threads",
            "is_active": True,
            "credentials_data": kwargs["credentials_data"],
        }

    repo.get_platform_credentials.side_effect = _get
    repo.save_platform_credentials.side_effect = _save
    mgr = _make_manager(repo)

    with patch("httpx.AsyncClient.get", return_value=_resp(200, {"access_token": "REFRESHED_TOKEN"})) as mock_get:
        token = await mgr.get_access_token()

    assert token == "REFRESHED_TOKEN"
    assert mock_get.call_args.kwargs["params"]["grant_type"] == "th_refresh_token"


@pytest.mark.asyncio
async def test_expired_token_is_not_returned_and_reports_unauthenticated():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = _stored(days_remaining=-1)
    mgr = _make_manager(repo)

    # Refresh attempt fails upstream -> must not hand back the dead token.
    with patch("httpx.AsyncClient.get", return_value=_resp(401, {"error": {"message": "expired"}})):
        assert await mgr.get_access_token() is None
        assert await mgr.is_authenticated() is False


# --- Status, clearing, audit ---


@pytest.mark.asyncio
async def test_auth_status_flags_refresh_due_and_hides_secrets():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = _stored(days_remaining=4)
    mgr = _make_manager(repo)

    status = await mgr.get_auth_status()
    assert status["authenticated"] is True
    assert status["status"] == "NEEDS_REFRESH"
    assert status["key_version"] == "v1"
    assert status["encryption_key_configured"] is True
    assert "secret-xyz" not in json.dumps(status)


@pytest.mark.asyncio
async def test_auth_status_when_not_connected():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = None
    mgr = _make_manager(repo)

    status = await mgr.get_auth_status()
    assert status["authenticated"] is False
    assert status["status"] == "NOT_CONNECTED"


@pytest.mark.asyncio
async def test_clear_auth_deletes_credentials_and_logs():
    repo = AsyncMock()
    repo.delete_platform_credentials.return_value = True
    mgr = _make_manager(repo)

    assert await mgr.clear_auth() is True
    repo.delete_platform_credentials.assert_awaited_once_with("threads")
    assert repo.log_event.await_args.kwargs["event_type"] == "OAUTH_TOKEN_CLEARED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code,expected_event,expected_level",
    [(401, "AUTH_REJECTED", "ERROR"), (403, "AUTH_REJECTED", "ERROR"), (429, "RATE_LIMITED", "WARNING")],
)
async def test_record_api_failure_classifies_soft_blocks(status_code, expected_event, expected_level):
    repo = AsyncMock()
    mgr = _make_manager(repo)

    await mgr.record_api_failure(status_code, "blocked", endpoint="https://graph.threads.net/v1.0/me/threads")

    kwargs = repo.log_event.await_args.kwargs
    assert kwargs["event_type"] == expected_event
    assert kwargs["level"] == expected_level
    assert kwargs["details"]["status_code"] == status_code


def test_build_authorization_url_includes_scopes_and_state():
    mgr = _make_manager()
    url = mgr.build_authorization_url(
        client_id="app-123",
        redirect_uri="https://finolabs.io/cb",
        state="csrf-token",
    )
    assert url.startswith(ThreadsAuthManager.AUTHORIZE_URL)
    assert "response_type=code" in url
    assert "threads_keyword_search" in url
    assert "state=csrf-token" in url


# --- Instagram variant reuses the same lifecycle with ig_* grant types ---


def test_instagram_manager_overrides_platform_and_grant_types():
    assert InstagramAuthManager.PLATFORM_NAME == "instagram"
    assert InstagramAuthManager.EXCHANGE_GRANT_TYPE == "ig_exchange_token"
    assert InstagramAuthManager.REFRESH_GRANT_TYPE == "ig_refresh_token"
    assert InstagramAuthManager.REFRESH_THRESHOLD_DAYS == 10


@pytest.mark.asyncio
async def test_instagram_refresh_uses_ig_grant_type():
    repo = AsyncMock()
    stored = _stored(days_remaining=5)
    stored["platform"] = "instagram"
    repo.get_platform_credentials.return_value = stored
    mgr = InstagramAuthManager(repository=repo, crypto_service=CryptoService(secret_key=FIXED_KEY))

    with patch("httpx.AsyncClient.get", return_value=_resp(200, {"access_token": "IG_REFRESHED"})) as mock_get:
        result = await mgr.refresh_token_if_needed()

    assert result["refreshed"] is True
    assert mock_get.call_args.kwargs["params"]["grant_type"] == "ig_refresh_token"
    assert repo.save_platform_credentials.await_args.kwargs["platform"] == "instagram"
