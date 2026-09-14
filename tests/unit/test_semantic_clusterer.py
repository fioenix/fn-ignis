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



# --- a cluster's first sighting, when some sightings have no clock ------------------------------
#
# After the backfill a group can mix the two kinds: observations this harness collected, which
# carry an exact ingestion time, and the 17,118 written before sql/015, whose collection time was
# never recorded. min() over both raises, and every way of filling the gap is a fabrication --
# published_at answers a different question and now() is simply false.


def _signal(title: str, captured_at, **overrides):
    from datetime import datetime, timezone  # noqa: F401  (imported for callers' literals)

    return TrendSignal(
        platform=overrides.pop("platform", PlatformType.YOUTUBE),
        raw_title=title,
        metric_value=overrides.pop("metric_value", 100.0),
        geo_code=GeoCode.VN,
        captured_at=captured_at,
        **overrides,
    )


@pytest.mark.asyncio
async def test_a_cluster_is_first_seen_at_its_earliest_exact_ingestion():
    """Observations with no clock are skipped, not defaulted into the answer."""
    from datetime import datetime, timezone

    early = datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc)
    late = datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc)
    clusterer = SemanticClusterer(similarity_threshold=0.3)

    clusters = await clusterer.cluster_signals(
        [
            _signal("Gia vang 9999 hom nay bien dong manh", captured_at=None),
            _signal("Thi truong gia vang 9999 trong nuoc tang soc", captured_at=late),
            _signal("Gia vang 9999 va xu huong dau tu", captured_at=early),
        ]
    )

    assert clusters, "the group still clusters; a missing clock is not a missing signal"
    assert clusters[0].first_seen_at == early


@pytest.mark.asyncio
async def test_a_cluster_of_only_legacy_observations_has_no_first_seen_time():
    """Nothing in the group was ever timestamped, so the cluster cannot claim a first sighting."""
    clusterer = SemanticClusterer(similarity_threshold=0.3)

    clusters = await clusterer.cluster_signals(
        [
            _signal("Gia vang 9999 hom nay bien dong manh", captured_at=None),
            _signal("Thi truong gia vang 9999 trong nuoc tang soc", captured_at=None),
        ]
    )

    assert clusters
    assert clusters[0].first_seen_at is None
