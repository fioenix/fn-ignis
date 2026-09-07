import pytest

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
    
    # The gold-price cluster must hold two signals (Google + YouTube)
    gold_cluster = next(c for c in clusters if "vàng" in c.canonical_name.lower())
    assert len(gold_cluster.signals) == 2
    assert gold_cluster.cross_platform_score > 0
    assert {s.platform for s in gold_cluster.signals} == {PlatformType.GOOGLE_TRENDS, PlatformType.YOUTUBE}

    # The AI cluster must hold one signal
    ai_cluster = next(c for c in clusters if "ai" in c.canonical_name.lower() or "bot" in c.canonical_name.lower() or "coding" in c.canonical_name.lower())
    assert len(ai_cluster.signals) == 1


def test_clean_title_removes_hashtags_urls_emojis_emoticons():
    raw_1 = "dka chưa nghĩ ra cap=))#nhasangtaofreefire #freefire"
    clean_1 = SemanticClusterer._clean_title(raw_1)
    assert clean_1 == "dka chưa nghĩ ra cap"

    raw_2 = "🔥 Bánh mì nướng bơ tỏi tại nhà siêu giòn https://tiktok.com/@chef #cooking #food #fyp"
    clean_2 = SemanticClusterer._clean_title(raw_2)
    assert clean_2 == "Bánh mì nướng bơ tỏi tại nhà siêu giòn"

    raw_3 = "#0396男团 #fyp #foryou"
    clean_3 = SemanticClusterer._clean_title(raw_3)
    assert clean_3 == ""


@pytest.mark.asyncio
async def test_canonical_name_selection_rejects_pure_hashtags():
    clusterer = SemanticClusterer(similarity_threshold=0.25)

    signals = [
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="#0396男团 #fyp #foryou",
            metric_value=1000.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="Cách làm bánh mì nướng bơ tỏi thơm lừng giòn rụm #bepme #fyp",
            metric_value=2000.0,
            geo_code=GeoCode.VN,
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="Bánh mì nướng bơ tỏi tại nhà đơn giản",
            metric_value=5000.0,
            geo_code=GeoCode.VN,
        ),
    ]

    clusters = await clusterer.cluster_signals(signals)
    # The cluster grouping the banh mi signals must have a clean canonical name without '#bepme' or '#fyp'
    bm_cluster = next(c for c in clusters if "bánh mì" in c.canonical_name.lower())
    assert "#" not in bm_cluster.canonical_name
    assert "bánh mì" in bm_cluster.canonical_name.lower()

