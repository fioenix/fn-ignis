import pytest
from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin


@pytest.mark.asyncio
async def test_tiktok_plugin_properties():
    plugin = TikTokPlugin()
    assert plugin.platform == PlatformType.TIKTOK
    assert "TikTok" in plugin.name


@pytest.mark.asyncio
async def test_retired_tiktok_collection_refuses_like_threads():
    """Explore and built-in search are retired; only the comment path stays live (Spec 027)."""
    plugin = TikTokPlugin()
    assert await plugin.is_healthy() is False
    assert plugin.supports_search is False
    with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
        await plugin.fetch_signals()
