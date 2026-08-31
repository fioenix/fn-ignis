import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
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
