import pytest

from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.domain.entities import TrendSignal
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


TAXONOMIES = [
    {"industry_code": "tech", "industry_name": "Tech & Electronics", "keywords": ["ai", "software", "agent", "app"]},
    {"industry_code": "beauty", "industry_name": "Beauty & Personal Care", "keywords": ["skincare", "makeup", "serum"]},
]


@pytest.mark.asyncio
async def test_bug09_category_propagated_from_source_metadata():
    """Category tu TikTok Creative Center phai duoc giu nguyen, khong bi ghi de thanh 'general'."""
    clusterer = SemanticClusterer()
    signals = [
        TrendSignal(
            platform=PlatformType.TIKTOK,
            raw_title="Xu huong lam dep mua he 2026",
            geo_code=GeoCode.VN,
            metadata={"category": "Beauty & Personal Care"},
        )
    ]
    clusters = await clusterer.cluster_signals(signals)
    assert clusters[0].category == "beauty & personal care"


@pytest.mark.asyncio
async def test_bug09_category_inferred_from_registered_taxonomy():
    """Nguon khong co category thi phan loai bang industry_taxonomies trong DB."""
    clusterer = SemanticClusterer()
    clusterer.register_taxonomies(TAXONOMIES)
    signals = [
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Huong dan dung AI agent cho doanh nghiep", geo_code=GeoCode.VN),
    ]
    clusters = await clusterer.cluster_signals(signals)
    assert clusters[0].category == "tech"


@pytest.mark.asyncio
async def test_bug09_unknown_topic_is_unclassified_not_general():
    clusterer = SemanticClusterer()
    clusterer.register_taxonomies(TAXONOMIES)
    signals = [
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="Ket qua tran dau toi qua", geo_code=GeoCode.VN),
    ]
    clusters = await clusterer.cluster_signals(signals)
    assert clusters[0].category == "unclassified"


@pytest.mark.asyncio
async def test_bug09_sqlite_bootstrap_seeds_industry_taxonomies(tmp_path):
    from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository

    repo = SqliteTrendRepository(db_path=str(tmp_path / "tax.db"))
    taxonomies = await repo.get_industry_taxonomies()
    assert taxonomies, "SQLite bootstrap phai seed industry_taxonomies"
    assert all(t["keywords"] for t in taxonomies)


@pytest.mark.asyncio
async def test_bug09_taxonomy_match_is_diacritics_insensitive():
    """Lexicon luu khong dau ('khoa hoc'), tieu de co dau van phai khop."""
    clusterer = SemanticClusterer()
    clusterer.register_taxonomies([
        {"industry_code": "education", "industry_name": "Education", "keywords": ["khoa hoc", "dao tao"]},
    ])
    signals = [
        TrendSignal(platform=PlatformType.YOUTUBE, raw_title="Khóa học đào tạo marketing 2026", geo_code=GeoCode.VN),
    ]
    clusters = await clusterer.cluster_signals(signals)
    assert clusters[0].category == "education"
