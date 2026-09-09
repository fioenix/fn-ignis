"""A market-listening pass must ingest signals about topics, not a national popularity chart.

The headline metric is a cross-platform momentum score, and 40 of its 100 points come from how
many platforms carry the same topic. That term can only ever fire when the platforms were asked
about the same subject. These tests pin the ingress contract that makes it possible:

  1. A connector declares whether its untargeted feed discovers topics or merely ranks whatever
     is popular. A popularity chart is never pulled untargeted during a public pass.
  2. Topics discovered in the pass are fanned out as keyword probes to the other connectors, so
     signals about one subject arrive from several platforms.
  3. The keyword fan-out stays inside a stated API unit budget.

They are written against the observable outcome rather than the call sequence: what matters is
that one pass yields clusters spanning more than one platform.
"""

from typing import Dict, List, Optional
from unittest.mock import AsyncMock

import pytest

from ignis.application.ports.connector_port import IConnectorPlugin
from ignis.application.use_cases.ingest_trends import IngestTrendsUseCase
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, IngressScope, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


def _signal(platform: PlatformType, title: str, url: str) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=1000.0,
        growth_velocity=10.0,
        geo_code=GeoCode.VN,
        source_url=url,
    )


class DiscoveryFeedPlugin(IConnectorPlugin):
    """Stands in for Google Trends: its feed is a list of what people are searching for."""

    def __init__(self, topics: List[str]):
        self._topics = topics
        self.fetch_calls = 0

    @property
    def platform(self) -> PlatformType:
        return PlatformType.GOOGLE_TRENDS

    @property
    def name(self) -> str:
        return "Discovery Feed"

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=IngressScope.PUBLIC_MARKET):
        self.fetch_calls += 1
        return [_signal(self.platform, t, f"https://trends.example/{i}") for i, t in enumerate(self._topics)]


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

    @property
    def feed_yields_candidate_topics(self) -> bool:
        return False

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
                out.append(_signal(self.platform, title, f"https://chart.example/{kw}/{i}"))
        return out


def _repository(lexicon_terms: Optional[List[str]] = None) -> AsyncMock:
    repo = AsyncMock()
    repo.log_event = AsyncMock()
    repo.get_domain_lexicons = AsyncMock(
        return_value=[{"domain": "ai", "term": t} for t in (lexicon_terms or [])]
    )
    repo.save_signals = AsyncMock(side_effect=lambda signals: len(signals))
    repo.get_self_accounts = AsyncMock(return_value=[])
    return repo


@pytest.mark.asyncio
async def test_public_pass_never_pulls_an_untargeted_popularity_chart():
    """The chart is 1 API unit and returns thousands of rows, which is exactly why it took over."""
    repo = _repository(["khoa hoc ai"])
    chart = PopularityChartPlugin(chart=["Bolero remix 2026"], by_keyword={})
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(DiscoveryFeedPlugin(["khoa hoc ai"]))
    registry.register(chart)

    signals = await registry.fetch_from_all(
        geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET, seed_keywords=["khoa hoc ai"]
    )

    assert chart.fetch_calls == 0, "A popularity chart must be probed by keyword, never pulled untargeted."
    assert "Bolero remix 2026" not in [s.raw_title for s in signals]


@pytest.mark.asyncio
async def test_topics_discovered_in_the_pass_are_fanned_out_to_the_other_platforms():
    """Stage 2 asks the remaining connectors about what stage 1 just found."""
    repo = _repository()
    chart = PopularityChartPlugin(chart=["Bolero remix 2026"], by_keyword={})
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(DiscoveryFeedPlugin(["dien thoai gap"]))
    registry.register(chart)

    await registry.fetch_from_all(geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET, seed_keywords=[])

    assert "dien thoai gap" in chart.searched_keywords, (
        "A topic found by the discovery feed must be handed to the keyword-capable connectors, "
        "otherwise each platform reports on a different subject and no cluster can span two."
    )


@pytest.mark.asyncio
async def test_one_pass_produces_clusters_that_span_more_than_one_platform():
    """The acceptance criterion: cross-platform momentum needs cross-platform clusters."""
    topic = "khoa hoc ai"
    repo = _repository([topic])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(DiscoveryFeedPlugin([topic]))
    registry.register(
        PopularityChartPlugin(
            chart=["Bolero remix 2026"],
            by_keyword={topic: ["Khoa hoc AI cho nguoi moi bat dau"]},
        )
    )

    use_case = IngestTrendsUseCase(registry=registry, repository=repo)
    result = await use_case.execute(geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET)

    signals = repo.save_signals.call_args.args[0]
    clusters = await SemanticClusterer().cluster_signals(signals)
    spanning = [c for c in clusters if len({s.platform for s in signals if s.cluster_id == c.id}) > 1]

    assert result["total_fetched"] > 0
    assert spanning, (
        "No cluster spans two platforms. Every connector reported on its own subject, so the "
        "40-point platform diversity term cannot fire."
    )


@pytest.mark.asyncio
async def test_keyword_fan_out_stays_within_the_stated_api_unit_budget():
    """YouTube search costs 100 units against a 10,000/day quota, so the fan-out must be capped."""
    from ignis.application.use_cases.ingest_trends import MAX_TOPIC_KEYWORDS

    repo = _repository([f"seed {i}" for i in range(40)])
    chart = PopularityChartPlugin(chart=[], by_keyword={})
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(DiscoveryFeedPlugin([f"discovered {i}" for i in range(40)]))
    registry.register(chart)

    await IngestTrendsUseCase(registry=registry, repository=repo).execute(geo=GeoCode.VN)

    assert len(chart.searched_keywords) <= MAX_TOPIC_KEYWORDS, (
        f"{len(chart.searched_keywords)} keywords probed in one pass; the budget allows "
        f"{MAX_TOPIC_KEYWORDS}."
    )


def test_quota_safe_interval_matches_the_published_api_costs():
    """Cadence and corpus quality trade against each other; the arithmetic must be explicit."""
    from ignis.application.use_cases.ingest_trends import (
        MAX_TOPIC_KEYWORDS,
        YOUTUBE_DAILY_QUOTA_UNITS,
        YOUTUBE_SEARCH_UNIT_COST,
        quota_safe_interval_seconds,
    )

    interval = quota_safe_interval_seconds()
    passes_per_day = 86_400 // interval
    assert passes_per_day * MAX_TOPIC_KEYWORDS * YOUTUBE_SEARCH_UNIT_COST <= YOUTUBE_DAILY_QUOTA_UNITS

    # A narrower fan-out buys back cadence, which is the knob an operator actually has.
    assert quota_safe_interval_seconds(keywords_per_pass=1) < interval


@pytest.mark.asyncio
async def test_lexicon_seeds_do_not_crowd_out_the_topics_the_pass_discovered():
    """With as many seeds as the budget allows, stage 1's findings must still get probed.

    This is what a live pass actually did: ten lexicon seeds filled a ten-keyword budget, so the
    ten topics Google Trends had just reported were collected and then never probed, and stage 2
    was topic-coupled to the lexicon alone.
    """
    from ignis.application.use_cases.ingest_trends import MAX_TOPIC_KEYWORDS

    seeds = [f"seed {i}" for i in range(MAX_TOPIC_KEYWORDS)]
    repo = _repository(seeds)
    chart = PopularityChartPlugin(chart=[], by_keyword={})
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register(DiscoveryFeedPlugin([f"discovered {i}" for i in range(MAX_TOPIC_KEYWORDS)]))
    registry.register(chart)

    await IngestTrendsUseCase(registry=registry, repository=repo).execute(geo=GeoCode.VN)

    probed = chart.searched_keywords
    assert len(probed) <= MAX_TOPIC_KEYWORDS
    assert any(kw.startswith("discovered") for kw in probed), (
        f"Only lexicon seeds were probed: {probed}"
    )
    assert any(kw.startswith("seed") for kw in probed), (
        f"Only discovered topics were probed: {probed}"
    )


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

    @property
    def feed_yields_candidate_topics(self) -> bool:
        return False

    async def is_healthy(self) -> bool:
        return True

    async def fetch_signals(self, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=50, scope=IngressScope.PUBLIC_MARKET):
        return []

    async def search_signals(self, keywords, geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=20):
        return [_signal(self.platform, t, f"https://f.example/{i}") for i, t in enumerate(self._titles)]


@pytest.mark.asyncio
async def test_a_vn_pass_does_not_store_titles_from_another_language():
    """A live VN pass stored Ukrainian and Arabic video titles: `q=` is not a region filter.

    The language detector already existed but was only wired into mission analysis, so nothing
    checked the signals the always-on radar wrote to the corpus.
    """
    repo = _repository(["mau toc"])
    registry = ConnectorPluginRegistry(repository=repo)
    registry.register_locale_vocabulary(terms=["mau toc", "salon"])
    registry.register(DiscoveryFeedPlugin(["mau toc"]))
    registry.register(
        ForeignLanguagePlugin(
            [
                "Nhuom mau toc tai nha khong can den salon",
                "Чи впливала погода на колір волосся?",
                "غيرو لون شعره واصبح لا يصدق",
            ]
        )
    )

    signals = await registry.fetch_from_all(
        geo=GeoCode.VN, scope=IngressScope.PUBLIC_MARKET, seed_keywords=["mau toc"]
    )

    titles = [s.raw_title for s in signals]
    assert "Nhuom mau toc tai nha khong can den salon" in titles
    assert not [t for t in titles if "погода" in t or "شعره" in t], (
        f"Foreign-language titles reached the corpus: {titles}"
    )
