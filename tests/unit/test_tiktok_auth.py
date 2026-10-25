import pytest
from unittest.mock import AsyncMock
from ignis.infrastructure.auth.tiktok_auth import TikTokAuthManager

@pytest.mark.asyncio
async def test_tiktok_auth_manager_is_authenticated_false():
    mock_repo = AsyncMock()
    mock_repo.get_platform_credentials.return_value = None

    auth_mgr = TikTokAuthManager(repository=mock_repo)
    assert await auth_mgr.is_authenticated() is False
    assert await auth_mgr.get_storage_state() is None

@pytest.mark.asyncio
async def test_tiktok_auth_manager_is_authenticated_true():
    mock_repo = AsyncMock()
    mock_repo.get_platform_credentials.return_value = {
        "platform": "tiktok",
        "is_active": True,
        "credentials_data": {"cookies": [{"name": "sessionid", "value": "xyz123"}]},
    }

    auth_mgr = TikTokAuthManager(repository=mock_repo)
    assert await auth_mgr.is_authenticated() is True
    state = await auth_mgr.get_storage_state()
    assert state is not None
    assert len(state["cookies"]) == 1

@pytest.mark.asyncio
async def test_tiktok_auth_manager_clear_auth():
    mock_repo = AsyncMock()
    mock_repo.delete_platform_credentials.return_value = True

    auth_mgr = TikTokAuthManager(repository=mock_repo)
    res = await auth_mgr.clear_auth()
    assert res is True
    mock_repo.delete_platform_credentials.assert_called_once_with("tiktok")


def _fake_playwright(cookies, url):
    """A Playwright stand-in whose single page sits on `url` with `cookies` in its context."""
    from unittest.mock import MagicMock

    page = AsyncMock()
    page.url = url
    page.query_selector.return_value = None
    context = AsyncMock()
    context.new_page.return_value = page
    context.cookies.return_value = cookies
    context.storage_state.return_value = {"cookies": cookies, "origins": []}
    browser = AsyncMock()
    browser.new_context.return_value = context
    p = MagicMock()
    p.chromium.launch = AsyncMock(return_value=browser)
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=p)
    manager.__aexit__ = AsyncMock(return_value=False)
    return MagicMock(return_value=manager)


@pytest.fixture
def fast_poll(monkeypatch):
    import asyncio

    real_sleep = asyncio.sleep

    async def short_sleep(_seconds):
        await real_sleep(0.01)

    monkeypatch.setattr(asyncio, "sleep", short_sleep)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cookies, url",
    [
        # 23/10/2026: a login abandoned in Instagram's OAuth window was stored as an active
        # TikTok session. The page had left /login and the context held Instagram's sessionid.
        (
            [
                {"name": "ttwid", "value": "x", "domain": ".tiktok.com"},
                {"name": "sessionid", "value": "x", "domain": ".instagram.com"},
            ],
            "https://www.instagram.com/oauth/authorize?redirect_uri=https%3A%2F%2Fwww.tiktok.com%2F",
        ),
        ([{"name": "ttwid", "value": "x", "domain": ".tiktok.com"}], "https://www.tiktok.com/foryou"),
        ([{"name": "sessionid", "value": "", "domain": ".tiktok.com"}], "https://www.tiktok.com/login"),
    ],
)
async def test_login_without_a_tiktok_session_cookie_is_not_stored(monkeypatch, fast_poll, cookies, url):
    import playwright.async_api

    monkeypatch.setattr(playwright.async_api, "async_playwright", _fake_playwright(cookies, url))
    mock_repo = AsyncMock()

    result = await TikTokAuthManager(repository=mock_repo).authenticate_interactive(timeout_seconds=0.05)

    assert result["success"] is False
    mock_repo.save_platform_credentials.assert_not_called()


@pytest.mark.asyncio
async def test_login_with_a_tiktok_session_cookie_is_stored(monkeypatch, fast_poll):
    import playwright.async_api

    cookies = [
        {"name": "ttwid", "value": "x", "domain": ".tiktok.com"},
        {"name": "sessionid", "value": "x", "domain": ".tiktok.com"},
    ]
    monkeypatch.setattr(
        playwright.async_api, "async_playwright", _fake_playwright(cookies, "https://www.tiktok.com/login")
    )
    mock_repo = AsyncMock()

    result = await TikTokAuthManager(repository=mock_repo).authenticate_interactive(timeout_seconds=5)

    assert result["success"] is True
    mock_repo.save_platform_credentials.assert_called_once()
    assert mock_repo.save_platform_credentials.call_args.kwargs["is_active"] is True
