import pytest
from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


@pytest.mark.asyncio
async def test_bug04_regression_trieu_dai_not_grouped_with_dai_hoc():
    clusterer = SemanticClusterer(similarity_threshold=0.25)
    s1 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Triều Đại Huyết Hắc Và Người Mạnh Nhất Bảng Xếp Hạng Siêu Anh Hùng 🤣 Hoàng ACC",
        metric_value=50000.0,
        geo_code=GeoCode.VN,
    )
    s2 = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="Đại học FPT tuyển sinh 2026",
        metric_value=10000.0,
        geo_code=GeoCode.VN,
    )
    clusters = await clusterer.cluster_signals([s1, s2])
    # Không được gộp chung vì chỉ trùng chữ 'đại'
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_bug04_regression_nguoi_lao_dong_not_grouped_with_nguoi_mau():
    clusterer = SemanticClusterer(similarity_threshold=0.25)
    s1 = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="người lao động",
        metric_value=20000.0,
        geo_code=GeoCode.VN,
    )
    s2 = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="người mẫu",
        metric_value=15000.0,
        geo_code=GeoCode.VN,
    )
    clusters = await clusterer.cluster_signals([s1, s2])
    # Không được gộp chung chỉ vì trùng chữ 'người'
    assert len(clusters) == 2


@pytest.mark.asyncio
async def test_bug04_ai_and_video_tao_bang_ai_grouped():
    clusterer = SemanticClusterer(similarity_threshold=0.25)
    s1 = TrendSignal(
        platform=PlatformType.GOOGLE_TRENDS,
        raw_title="AI",
        metric_value=50000.0,
        geo_code=GeoCode.VN,
    )
    s2 = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="Video tạo bằng AI đỉnh cao #xuhuong #fyp",
        metric_value=30000.0,
        geo_code=GeoCode.VN,
    )
    clusters = await clusterer.cluster_signals([s1, s2])
    # Phải gộp thành 1 cluster AI
    assert len(clusters) == 1
    assert "ai" in clusters[0].canonical_name.lower()
    assert len(clusters[0].signals) == 2


def test_bug04_canonical_name_constraints():
    # Không chứa emoji, hashtag, và <= 80 ký tự
    raw = "🔥🎉 #xuhuong #fyp Cách để chạy hong buồn ngủ … vừa chạy vừa hát😄😄 Ủa mấy a bộ con gái chạy là phải mệt hả mọi người ơi dài ngoằng ngoẵng hơn tám mươi ký tự luôn nè trời ơi"
    clean = SemanticClusterer._clean_title(raw)
    assert "#" not in clean
    assert "🔥" not in clean
    assert "😄" not in clean
    
    # Test canonical name builder
    s = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title=raw,
        metric_value=100.0,
        geo_code=GeoCode.VN,
    )
    canonical = SemanticClusterer._select_canonical_name([s])
    assert len(canonical) <= 80
    assert "#" not in canonical
