"""Requested ingress preserves source language for downstream evidence qualification."""

import pytest

from ignis.domain.value_objects import GeoCode

@pytest.mark.asyncio
async def test_an_agent_probe_fetches_foreign_language_content_freely():
    """An explicit question may legitimately reach Korean or Chinese sources."""
    from unittest.mock import AsyncMock

    from ignis.application.ports.connector_port import IConnectorPlugin
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType, Timeframe
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    class MultilingualPlugin(IConnectorPlugin):
        @property
        def platform(self):
            return PlatformType.YOUTUBE

        @property
        def name(self):
            return "Multilingual Probe"

        async def is_healthy(self):
            return True

        async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=None):
            return []

        async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
            return [
                TrendSignal(
                    platform=self.platform,
                    raw_title=title,
                    metric_value=100.0,
                    geo_code=GeoCode.VN,
                    source_url=f"https://example.test/{i}",
                    metadata={"keyword": keywords[0] if keywords else None},
                )
                for i, title in enumerate(
                    [
                        "Best AI agent frameworks for e-commerce",   # English, always fine
                        "K-beauty 스킨케어 루틴 추천",                   # Korean
                        "跨境电商 选品 技巧",                            # Chinese
                    ]
                )
            ]

    repo = AsyncMock()
    repo.log_event = AsyncMock()
    repo.get_self_accounts = AsyncMock(return_value=[])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(MultilingualPlugin())

    signals = await registry.search_across_all(keywords=["skincare"], geo=GeoCode.VN)

    assert len(signals) == 3, (
        "An agent probe must return what it found, whatever language it is in: "
        f"{[s.raw_title for s in signals]}"
    )


@pytest.mark.asyncio
async def test_a_requested_pass_preserves_the_languages_it_found():
    """Requested collection preserves source language for downstream qualification."""
    from unittest.mock import AsyncMock

    from ignis.application.ports.connector_port import IConnectorPlugin
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import IngressScope, PlatformType, Timeframe
    from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry

    class MixedLanguageFeed(IConnectorPlugin):
        @property
        def platform(self):
            return PlatformType.GOOGLE_TRENDS

        @property
        def name(self):
            return "Mixed Language Feed"

        async def is_healthy(self):
            return True

        async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=None):
            return [
                TrendSignal(
                    platform=self.platform,
                    raw_title=title,
                    metric_value=100.0,
                    geo_code=GeoCode.VN,
                    source_url=f"https://example.test/{i}",
                )
                for i, title in enumerate(["giá vàng hôm nay", "K-beauty 스킨케어 루틴"])
            ]

    def _registry():
        repo = AsyncMock()
        repo.log_event = AsyncMock()
        repo.get_self_accounts = AsyncMock(return_value=[])
        registry = ConnectorPluginRegistry(repository=repo)
        registry.register(MixedLanguageFeed())
        return registry

    requested = await _registry().fetch_from_all(
        geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET
    )
    assert len(requested) == 2, (
        f"An explicitly requested pass keeps what it found: {[s.raw_title for s in requested]}"
    )
