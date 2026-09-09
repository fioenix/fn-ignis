import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


@pytest.mark.asyncio
async def test_end_to_end_pipeline():
    # 1. Simulate signals ingested from three different platforms
    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Giá vàng hôm nay 9999",
            metric_value=120000.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Bản tin tài chính: Giá vàng 9999 lập đỉnh",
            metric_value=850000.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.THREADS,
            raw_title="Chia sẻ quan điểm về biến động giá vàng 9999",
            metric_value=5000.0,
            geo_code=GeoCode.VN,
        ),
    ]

    # 2. Cluster and score
    clusterer = SemanticClusterer()
    clusters = await clusterer.cluster_signals(signals)

    assert len(clusters) == 1
    c = clusters[0]
    assert "vàng" in c.canonical_name.lower()
    assert len(c.signals) == 3
    assert c.cross_platform_score >= 50.0  # Đa kênh (Google + YouTube + Threads)

    # 3. Sinh Artifact
    builder = HtmlArtifactBuilder()
    dashboard_html = builder.build_dashboard_artifact(clusters, geo=GeoCode.VN)
    assert "<!DOCTYPE html>" in dashboard_html
    # Artifacts show the display label, not the identity key: canonical_name is the longest raw
    # title in the cluster and stays untouched so the cluster UUID stays stable across passes.
    assert c.topic_label in dashboard_html
    assert "fn-ignis" in dashboard_html.lower()

    card_html = builder.build_topic_card_artifact(c, c.signals)
    assert "<!DOCTYPE html>" in card_html
    assert c.topic_label in card_html
    assert "Giá vàng hôm nay 9999" in card_html
