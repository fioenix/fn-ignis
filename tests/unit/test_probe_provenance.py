"""Signals retrieved by the same keyword are about the same topic by construction.

Clustering ties signals together by title-token overlap, which is the only evidence available
for a signal that arrived in a trending feed. For a signal that arrived through a keyword probe
there is stronger evidence: the query that returned it. Every connector already records it, but
under three different metadata keys and nothing read any of them, so a YouTube video title and a
Threads post retrieved by the same keyword stayed in separate clusters whenever their wording
differed -- which is most of the time, and is why a topic-coupled pass still produced
single-platform clusters.
"""

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.probe_provenance import probe_keyword_of
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


def _signal(platform: PlatformType, title: str, **metadata) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=1000.0,
        growth_velocity=10.0,
        geo_code=GeoCode.VN,
        source_url=f"https://example.test/{abs(hash(title))}",
        metadata=metadata,
    )


@pytest.mark.parametrize("key", ["keyword", "matched_keyword", "probe_keyword"])
def test_every_connector_spelling_of_the_probe_key_is_understood(key):
    """Connectors disagree on the name; the domain must not care which one they picked."""
    assert probe_keyword_of(_signal(PlatformType.YOUTUBE, "t", **{key: " Mau Toc "})) == "mau toc"


def test_a_signal_from_a_trending_feed_has_no_probe_keyword():
    assert probe_keyword_of(_signal(PlatformType.GOOGLE_TRENDS, "t")) is None
    assert probe_keyword_of(_signal(PlatformType.GOOGLE_TRENDS, "t", keyword="   ")) is None


@pytest.mark.asyncio
async def test_differently_worded_titles_from_one_probe_land_in_one_cluster():
    signals = [
        _signal(PlatformType.YOUTUBE, "Huong dan tu tay lam mon nay tai nha", keyword="mau toc"),
        _signal(PlatformType.THREADS, "Ai biet cho minh xin cong thuc voi", keyword="mau toc"),
        _signal(PlatformType.TIKTOK, "Thu ngay xem sao nhe ca nha", matched_keyword="Mau Toc"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)

    assert len(clusters) == 1, "One probe keyword must yield one topic"
    assert len({s.platform for s in clusters[0].signals}) == 3
    assert clusters[0].cross_platform_score > 24.0, "Three platforms must earn the diversity term"


@pytest.mark.asyncio
async def test_two_probes_stay_two_topics_even_when_the_wording_overlaps():
    """Provenance separates topics that token overlap alone would have merged."""
    signals = [
        _signal(PlatformType.YOUTUBE, "Cach lam tai nha don gian nhat", keyword="mau toc"),
        _signal(PlatformType.YOUTUBE, "Cach lam tai nha don gian nhat", keyword="lai suat"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_signals_without_provenance_still_cluster_by_similarity():
    """Trending-feed signals carry no probe keyword and must keep the existing behaviour."""
    signals = [
        _signal(PlatformType.GOOGLE_TRENDS, "gia vang hom nay tang manh phien sang"),
        _signal(PlatformType.GOOGLE_TRENDS, "gia vang hom nay tang manh phien chieu"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)
    assert len(clusters) == 1


@pytest.mark.asyncio
async def test_a_probe_group_does_not_swallow_unrelated_feed_signals():
    signals = [
        _signal(PlatformType.YOUTUBE, "Nhuom mau toc tai nha", keyword="mau toc"),
        _signal(PlatformType.GOOGLE_TRENDS, "lai suat huy dong giam"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)
    assert len(clusters) == 2
