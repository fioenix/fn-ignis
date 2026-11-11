"""Requested keyword collection preserves content and cross-platform clustering."""

from typing import Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


def _signal(platform: PlatformType, title: str, url: str, keyword: Optional[str] = None) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=1000.0,
        growth_velocity=10.0,
        geo_code=GeoCode.VN,
        source_url=url,
        metadata={"keyword": keyword} if keyword else {},
    )


class TopicSearchPlugin(IConnectorPlugin):
    """A keyword-capable surface returns the requested topics with provenance."""

    def __init__(self, topics: List[str]):
        self._topics = topics
        self.fetch_calls = 0

    @property
    def platform(self) -> PlatformType:
        return PlatformType.GOOGLE_TRENDS

    @property
    def name(self) -> str:
        return "Topic Search"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=IngressScope.PUBLIC_MARKET):
        self.fetch_calls += 1
        return [_signal(self.platform, t, f"https://trends.example/{i}") for i, t in enumerate(self._topics)]

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        return [_signal(self.platform, topic, f"https://trends.example/{i}", keyword=topic)
                for i, topic in enumerate(self._topics) if topic in keywords]


class PopularityChartPlugin(IConnectorPlugin):
    """Stands in for YouTube: an untargeted pull returns the national chart, whatever it is about.

    `_chart` is deliberately unrelated to any market topic, mirroring what the live corpus filled
    up with. If a public pass ever pulls this feed, the assertions below see the chart titles.
    """

    def __init__(self, chart: List[str], by_keyword: Dict[str, List[str]]):
        self._chart = chart
        self._by_keyword = by_keyword
        self.fetch_calls = 0
        self.searched_keywords: List[str] = []

    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    @property
    def name(self) -> str:
        return "Popularity Chart"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=IngressScope.PUBLIC_MARKET):
        self.fetch_calls += 1
        return [_signal(self.platform, t, f"https://chart.example/{i}") for i, t in enumerate(self._chart)]

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        self.searched_keywords.extend(keywords)
        out: List[TrendSignal] = []
        for kw in keywords:
            for i, title in enumerate(self._by_keyword.get(kw, [])):
                out.append(_signal(self.platform, title, f"https://chart.example/{kw}/{i}", keyword=kw))
        return out


def _repository(lexicon_terms: Optional[List[str]] = None) -> AsyncMock:
    repo = AsyncMock()
    repo.log_event = AsyncMock()
    repo.get_domain_lexicons = AsyncMock(
        return_value=[{"domain": "ai", "term": t} for t in (lexicon_terms or [])]
    )
    repo.save_signals = AsyncMock(side_effect=lambda signals: len(signals))
    repo.get_self_accounts = AsyncMock(return_value=[])
    # A mock keeps no request count, so it sets no daily ceiling.
    repo.reserve_connector_requests = AsyncMock(side_effect=NotImplementedError)
    return repo


@pytest.mark.asyncio
async def test_public_pass_never_pulls_an_untargeted_popularity_chart():
    """The chart is 1 API unit and returns thousands of rows, which is exactly why it took over."""
    repo = _repository(["khoa hoc ai"])
    chart = PopularityChartPlugin(chart=["Bolero remix 2026"], by_keyword={})
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(TopicSearchPlugin(["khoa hoc ai"]))
    registry.register(chart)

    result = await registry.search_with_outcomes(
        keywords=["khoa hoc ai"], geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET
    )
    signals = result.signals

    assert chart.fetch_calls == 0, "A popularity chart must be probed by keyword, never pulled untargeted."
    assert "Bolero remix 2026" not in [s.raw_title for s in signals]


@pytest.mark.asyncio
async def test_one_pass_produces_clusters_that_span_more_than_one_platform():
    """The acceptance criterion: cross-platform momentum needs cross-platform clusters."""
    topic = "khoa hoc ai"
    repo = _repository([topic])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(TopicSearchPlugin([topic]))
    registry.register(
        PopularityChartPlugin(
            chart=["Bolero remix 2026"],
            by_keyword={topic: ["Khoa hoc AI cho nguoi moi bat dau"]},
        )
    )

    result = await registry.search_with_outcomes(
        keywords=[topic], geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET,
    )
    signals = result.signals
    clusters = await SemanticClusterer().cluster_signals(signals)
    spanning = [c for c in clusters if len({s.platform for s in signals if s.cluster_id == c.id}) > 1]

    assert signals
    assert spanning, (
        "No cluster spans two platforms. Every connector reported on its own subject, so the "
        "40-point platform diversity term cannot fire."
    )


def test_retired_ingress_readers_are_absent():
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "src/ignis"
    assert not hasattr(ConnectorPluginRegistry, "fetch_from_all")
    assert not (src / "application/use_cases/ingest_trends.py").exists()
    assert not (src / "infrastructure/harness/refinement_orchestrator.py").exists()
    assert '"ingest_use_case"' not in (src / "interfaces/mcp/server.py").read_text()


class ForeignLanguagePlugin(IConnectorPlugin):
    """A keyword probe reaches the whole platform, not only the requested region."""

    def __init__(self, titles: List[str]):
        self._titles = titles

    @property
    def platform(self) -> PlatformType:
        return PlatformType.YOUTUBE

    @property
    def name(self) -> str:
        return "Foreign Language Feed"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=IngressScope.PUBLIC_MARKET):
        return []

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        return [
            _signal(self.platform, t, f"https://f.example/{i}", keyword=keywords[0] if keywords else None)
            for i, t in enumerate(self._titles)
        ]


@pytest.mark.asyncio
async def test_a_requested_vn_pass_preserves_foreign_language_results():
    """A geographic probe may find relevant titles in other languages."""
    repo = _repository(["mau toc"])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(TopicSearchPlugin(["mau toc"]))
    registry.register(
        ForeignLanguagePlugin(
            [
                "Nhuom mau toc tai nha khong can den salon",
                "Чи впливала погода на колір волосся?",
                "غيرو لون شعره واصبح لا يصدق",
            ]
        )
    )

    result = await registry.search_with_outcomes(
        keywords=["mau toc"], geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET
    )
    signals = result.signals

    titles = [s.raw_title for s in signals]
    assert "Nhuom mau toc tai nha khong can den salon" in titles
    assert any("погода" in title for title in titles)
    assert any("شعره" in title for title in titles)


@pytest.mark.asyncio
async def test_ingress_stores_an_off_topic_local_title_and_leaves_relevance_downstream():
    """Collection preserves local, English and foreign-script content for qualification."""
    repo = _repository()
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(TopicSearchPlugin(["mau toc"]))
    registry.register(
        ForeignLanguagePlugin(
            [
                "Nhuom mau toc tai nha khong can den salon",
                "Nhac tru tinh cover hay nhat 2026",       # local, off-topic, previously dropped
                "Best hair colour tools for salons 2026",  # English, previously dropped
                "워터밤 안가도 흠뻑 젖는 한강런",                    # wrong script for a VN pass
            ]
        )
    )

    result = await registry.search_with_outcomes(
        keywords=["mau toc"], geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET
    )
    signals = result.signals
    titles = [s.raw_title for s in signals]

    assert "Nhuom mau toc tai nha khong can den salon" in titles
    assert "Nhac tru tinh cover hay nhat 2026" in titles, (
        "Off-topic local content is a relevance question, and ingress must not decide it"
    )
    assert "Best hair colour tools for salons 2026" in titles, (
        "English titles are ordinary in the VN tech and fashion markets"
    )
    assert "워터밤 안가도 흠뻑 젖는 한강런" in titles, (
        "Requested collection preserves the source language for downstream qualification"
    )
    assert "foreign_script_filtered" not in registry.last_pass_report
