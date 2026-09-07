import pytest
import numpy as np
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def test_bug05_variance_of_scores_is_non_zero():
    """Phương sai điểm của 5 topic có số liệu khác nhau phải khác 0 (không bị bão hòa cùng 1 số 76.0)."""
    clusterer = SemanticClusterer()
    
    # Tạo 5 nhóm tín hiệu khác nhau về metric volume và velocity
    topics_signals = [
        [
            TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="T1", metric_value=10000.0, growth_velocity=50.0, geo_code=GeoCode.VN),
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title="T1", metric_value=2000000.0, growth_velocity=500.0, geo_code=GeoCode.VN),
        ],
        [
            TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="T2", metric_value=50000.0, growth_velocity=100.0, geo_code=GeoCode.VN),
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title="T2", metric_value=50000000.0, growth_velocity=2000.0, geo_code=GeoCode.VN),
        ],
        [
            TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="T3", metric_value=5000.0, growth_velocity=10.0, geo_code=GeoCode.VN),
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title="T3", metric_value=500000.0, growth_velocity=80.0, geo_code=GeoCode.VN),
        ],
        [
            TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="T4", metric_value=100000.0, growth_velocity=200.0, geo_code=GeoCode.VN),
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title="T4", metric_value=150000000.0, growth_velocity=10000.0, geo_code=GeoCode.VN),
        ],
        [
            TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="T5", metric_value=20000.0, growth_velocity=30.0, geo_code=GeoCode.VN),
            TrendSignal(platform=PlatformType.YOUTUBE, raw_title="T5", metric_value=10000000.0, growth_velocity=1200.0, geo_code=GeoCode.VN),
        ],
    ]
    
    scores = [clusterer._calculate_cross_platform_score(sigs) for sigs in topics_signals]
    
    # Ở phiên bản cũ bị hard cap 40.0 + 20.0 + 16.0 = 76.0 cho tất cả
    assert all(s != 76.0 for s in scores), f"Có topic bị kẹt ở điểm cũ 76.0: {scores}"
    assert len(set(scores)) == len(scores), f"Tất cả 5 scores phải khác biệt nhau: {scores}"
    variance = float(np.var(scores))
    assert variance > 0.5, f"Phương sai phải lớn hơn 0.5, thực tế là {variance}"


@pytest.mark.asyncio
async def test_bug05_sqlite_repository_dynamic_score_calculation(tmp_path):
    """SqliteTrendRepository tính dynamic score 4 thành phần khi cluster chưa có score."""
    db_path = str(tmp_path / "test_scoring.db")
    repo = SqliteTrendRepository(db_path=db_path)
    
    cluster = TopicCluster(
        canonical_name="Chủ đề thử nghiệm B",
        cross_platform_score=0.0,
    )
    await repo.save_clusters([cluster])
    
    s1 = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="Chủ đề thử nghiệm B",
        metric_value=50000.0,
        growth_velocity=15.0,
        cluster_id=cluster.id,
        geo_code=GeoCode.VN,
    )
    s2 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Chủ đề thử nghiệm B video",
        metric_value=200000.0,
        growth_velocity=300.0,
        cluster_id=cluster.id,
        geo_code=GeoCode.VN,
    )
    await repo.save_signals([s1, s2])
    
    top = await repo.get_top_clusters(geo=GeoCode.VN, timeframe=Timeframe.LAST_24H)
    assert len(top) == 1
    # Dynamic score được tính và > 0 và không bị gán 76.0
    assert top[0].cross_platform_score > 0
    assert top[0].cross_platform_score != 76.0
