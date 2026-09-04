from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from ignis.infrastructure.auth.meta_browser_auth import (
    InstagramBrowserAuthManager,
    ThreadsBrowserAuthManager,
)

MANAGERS = [
    (ThreadsBrowserAuthManager, "threads_browser"),
    (InstagramBrowserAuthManager, "instagram_browser"),
]


class _FakeContext:
    """Minimal stand-in for a Playwright BrowserContext."""

    def __init__(self, cookie_batches, storage_state):
        self._cookie_batches = list(cookie_batches)
        self._storage_state = storage_state

    async def cookies(self):
        return self._cookie_batches.pop(0) if self._cookie_batches else []

    async def storage_state(self):
        return self._storage_state


@pytest.mark.parametrize("manager_cls,platform", MANAGERS)
def test_browser_managers_use_distinct_platform_keys(manager_cls, platform):
    # Must not collide with the Tier 2 OAuth record for the same surface.
    assert manager_cls.PLATFORM_NAME == platform
    assert manager_cls.PLATFORM_NAME not in ("threads", "instagram")


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls,platform", MANAGERS)
async def test_get_storage_state_returns_none_without_credentials(manager_cls, platform):
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = None

    mgr = manager_cls(repository=repo)
    assert await mgr.get_storage_state() is None
    assert await mgr.is_authenticated() is False
    repo.get_platform_credentials.assert_awaited_with(platform)


@pytest.mark.asyncio
@pytest.mark.parametrize("manager_cls,platform", MANAGERS)
async def test_get_storage_state_returns_live_session(manager_cls, platform):
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = {
        "platform": platform,
        "is_active": True,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        "credentials_data": {"cookies": [{"name": "sessionid", "value": "abc"}]},
    }

    mgr = manager_cls(repository=repo)
    state = await mgr.get_storage_state()
    assert state is not None
    assert len(state["cookies"]) == 1
    assert await mgr.is_authenticated() is True


@pytest.mark.asyncio
async def test_expired_browser_session_is_not_authenticated():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = {
        "platform": "threads_browser",
        "is_active": True,
        "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "credentials_data": {"cookies": [{"name": "sessionid", "value": "abc"}]},
    }

    mgr = ThreadsBrowserAuthManager(repository=repo)
    assert await mgr.get_storage_state() is None
    status = await mgr.get_auth_status()
    assert status["status"] == "EXPIRED"
    assert status["authenticated"] is False


@pytest.mark.asyncio
async def test_auth_status_reports_not_connected_without_session():
    repo = AsyncMock()
    repo.get_platform_credentials.return_value = None

    status = await InstagramBrowserAuthManager(repository=repo).get_auth_status()
    assert status["status"] == "NOT_CONNECTED"
    assert status["authenticated"] is False


@pytest.mark.asyncio
async def test_clear_auth_deletes_the_browser_platform_row():
    repo = AsyncMock()
    repo.delete_platform_credentials.return_value = True

    assert await ThreadsBrowserAuthManager(repository=repo).clear_auth() is True
    repo.delete_platform_credentials.assert_awaited_once_with("threads_browser")


@pytest.mark.asyncio
async def test_poll_detects_session_cookie_after_the_user_signs_in():
    mgr = ThreadsBrowserAuthManager()
    context = _FakeContext(
        cookie_batches=[
            [{"name": "csrftoken", "value": "x"}],
            [{"name": "sessionid", "value": "SECRET"}],
        ],
        storage_state={},
    )

    assert await mgr._poll_for_session(context, SimpleNamespace(), timeout_seconds=30) is True


@pytest.mark.asyncio
async def test_poll_times_out_when_the_user_never_signs_in():
    mgr = ThreadsBrowserAuthManager()
    context = _FakeContext(cookie_batches=[[{"name": "csrftoken", "value": "x"}]], storage_state={})

    # A sub-poll-interval budget exits on the first pass without a session cookie.
    assert await mgr._poll_for_session(context, SimpleNamespace(), timeout_seconds=0) is False


@pytest.mark.asyncio
async def test_persist_stores_session_and_writes_an_audit_event():
    repo = AsyncMock()
    mgr = InstagramBrowserAuthManager(repository=repo)
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)

    await mgr._persist({"cookies": [{"name": "sessionid", "value": "s"}]}, expires_at)

    kwargs = repo.save_platform_credentials.await_args.kwargs
    assert kwargs["platform"] == "instagram_browser"
    assert kwargs["auth_type"] == "session_cookies"
    assert kwargs["expires_at"] == expires_at
    assert repo.log_event.await_args.kwargs["event_type"] == "BROWSER_SESSION_CAPTURED"


@pytest.mark.asyncio
async def test_persist_survives_a_failing_audit_log():
    repo = AsyncMock()
    repo.log_event.side_effect = RuntimeError("log backend down")

    await ThreadsBrowserAuthManager(repository=repo)._persist(
        {"cookies": []}, datetime.now(timezone.utc) + timedelta(days=1)
    )
    repo.save_platform_credentials.assert_awaited_once()
