import pytest
from statistics import pvariance
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


def test_bug05_variance_of_scores_is_non_zero():
    """Five topics with different metrics must produce different scores, not all saturate at 76.0."""
    clusterer = SemanticClusterer()
    
    # Five signal groups differing in metric volume and velocity
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
    
    # The previous formula hard-capped every topic at 40.0 + 20.0 + 16.0 = 76.0
    assert all(s != 76.0 for s in scores), f"A topic is stuck at the old saturated 76.0: {scores}"
    assert len(set(scores)) == len(scores), f"All five scores must differ: {scores}"
    variance = pvariance(scores)
    assert variance > 0.5, f"Variance must exceed 0.5, actual {variance}"


@pytest.mark.asyncio
async def test_bug05_sqlite_repository_dynamic_score_calculation(tmp_path):
    """SqliteTrendRepository computes a dynamic score when the cluster has none persisted."""
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
    # The dynamic score is computed, greater than 0, and not the old saturated 76.0
    assert top[0].cross_platform_score > 0
    assert top[0].cross_platform_score != 76.0


def test_scoring_contract_breakout_reachable_for_multi_platform_viral_topic():
    """Spec 003 US2: >= 3 platforms with high engagement must score >= 80 (BREAKOUT)."""
    clusterer = SemanticClusterer()
    viral = [
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="V", metric_value=100.0, growth_velocity=9000.0, geo_code=GeoCode.VN),
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="V", metric_value=60_000_000.0, growth_velocity=8000.0, geo_code=GeoCode.VN),
        TrendSignal(platform=PlatformType.TIKTOK, raw_title="V", metric_value=140_000_000.0, growth_velocity=12000.0, geo_code=GeoCode.VN),
    ]
    cluster = TopicCluster(canonical_name="V", cross_platform_score=clusterer._calculate_cross_platform_score(viral))
    assert cluster.cross_platform_score >= 80.0, f"Actual score: {cluster.cross_platform_score}"
    assert cluster.momentum_category.value == "breakout"


def test_scoring_weights_follow_platform_metric_velocity_contract():
    """The 40 (platform) / 40 (metric) / 20 (velocity) weights must not drift from spec 003."""
    clusterer = SemanticClusterer()
    platform_only = [
        TrendSignal(platform=p, raw_title="P", metric_value=0.0, growth_velocity=0.0, geo_code=GeoCode.VN)
        for p in (PlatformType.GOOGLE_TRENDS, PlatformType.YOUTUBE, PlatformType.TIKTOK, PlatformType.THREADS, PlatformType.REELS)
    ]
    assert clusterer._calculate_cross_platform_score(platform_only) == 40.0
