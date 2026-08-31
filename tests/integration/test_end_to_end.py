import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder
from ignis.interfaces.mcp.server import (
    handle_get_trending_topics,
    handle_generate_trend_artifact,
)


@pytest.mark.asyncio
async def test_end_to_end_pipeline():
    # 1. Giả lập tín hiệu thu thập từ 3 nền tảng khác nhau
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

    # 2. Gom cụm và chấm điểm
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
    assert c.canonical_name in dashboard_html
    assert "fn-ignis" in dashboard_html.lower()

    card_html = builder.build_topic_card_artifact(c, c.signals)
    assert "<!DOCTYPE html>" in card_html
    assert c.canonical_name in card_html
    assert "Giá vàng hôm nay 9999" in card_html
