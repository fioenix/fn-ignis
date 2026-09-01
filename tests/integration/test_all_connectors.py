from ignis.domain.value_objects import PlatformType
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.youtube.youtube_plugin import YouTubeDataPlugin
from ignis.infrastructure.connectors.tiktok.tiktok_plugin import TikTokPlugin
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin
from ignis.infrastructure.connectors.reels.reels_plugin import ReelsPlugin


def test_registry_registers_all_five_connectors():
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())
    registry.register(YouTubeDataPlugin(api_key="test_key"))
    registry.register(TikTokPlugin())
    registry.register(ThreadsPlugin())
    registry.register(ReelsPlugin())

    plugins = registry.list_plugins()
    assert len(plugins) == 5

    platforms = {p.platform for p in plugins}
    assert platforms == {
        PlatformType.GOOGLE_TRENDS,
        PlatformType.YOUTUBE,
        PlatformType.TIKTOK,
        PlatformType.THREADS,
        PlatformType.REELS,
    }
