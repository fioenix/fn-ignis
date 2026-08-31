import pytest
from uuid import uuid4
from datetime import datetime, timezone

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


@pytest.mark.asyncio
async def test_semantic_clusterer_grouping():
    clusterer = SemanticClusterer(similarity_threshold=0.3)

    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="Giá vàng 9999 hôm nay biến động mạnh",
            metric_value=100000.0,
            geo_code=GeoCode.VN
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Thị trường giá vàng 9999 trong nước tăng sốc",
            metric_value=500000.0,
            geo_code=GeoCode.VN
        ),
        TrendSignal(
            platform=PlatformType.THREADS,
            raw_title="Kinh nghiệm đầu tư AI agent và coding bot",
            metric_value=2000.0,
            geo_code=GeoCode.VN
        ),
    ]

    clusters = await clusterer.cluster_signals(signals)
    
    assert len(clusters) == 2
    
    # Cụm vàng phải gom 2 signals (Google + YouTube)
    gold_cluster = next(c for c in clusters if "vàng" in c.canonical_name.lower())
    assert len(gold_cluster.signals) == 2
    assert gold_cluster.cross_platform_score > 0
    assert {s.platform for s in gold_cluster.signals} == {PlatformType.GOOGLE_TRENDS, PlatformType.YOUTUBE}

    # Cụm AI phải có 1 signal
    ai_cluster = next(c for c in clusters if "ai" in c.canonical_name.lower() or "bot" in c.canonical_name.lower() or "coding" in c.canonical_name.lower())
    assert len(ai_cluster.signals) == 1
