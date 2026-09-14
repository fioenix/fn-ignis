import pytest
from datetime import datetime, timezone
from uuid import uuid4
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


async def _query(repo, sql: str):
    """Small read helper so these tests can assert on stored rows directly."""
    import asyncio
    import sqlite3

    def _run():
        conn = sqlite3.connect(repo._db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    return await asyncio.to_thread(_run)


@pytest.mark.asyncio
async def test_polling_one_source_twice_keeps_one_source_and_both_metrics(tmp_path):
    """The original bug06 contract, asserted where the data now lives.

    It used to read: one trend_signals row, two signal_metrics rows, and the row refreshed to
    the latest metric. The same three statements about the corpus are now one source, two
    observations, and the later observation carrying the later metric -- with the difference
    that the earlier metric is a row of its own rather than a value overwritten in place.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "test_dedup.db"))
    url = "https://www.tiktok.com/@creator/video/123456789"

    for metric, velocity, hour in ((1000.0, 10.0, 10), (2500.0, 25.0, 11)):
        await repo.save_signals(
            [
                TrendSignal(
                    platform=PlatformType.TIKTOK,
                    raw_title="Video viral mẫu",
                    metric_value=metric,
                    growth_velocity=velocity,
                    source_url=url,
                    geo_code=GeoCode.VN,
                    captured_at=datetime(2026, 9, 7, hour, 0, 0, tzinfo=timezone.utc),
                    metadata={"item_id": "123456789"},
                )
            ]
        )

    sources = await _query(repo, "SELECT platform, external_id FROM sources;")
    assert sources == [("tiktok", "video:123456789")], "one external object, one row"

    observations = await _query(
        repo, "SELECT metric_value, growth_velocity FROM observations ORDER BY observed_at;"
    )
    assert observations == [(1000.0, 10.0), (2500.0, 25.0)], "both sightings survive"

    legacy = await _query(
        repo, "SELECT count(*) FROM trend_signals UNION ALL SELECT count(*) FROM signal_metrics;"
    )
    assert [row[0] for row in legacy] == [0, 0], "and the legacy tables are not written"


@pytest.mark.asyncio
async def test_bug06_get_cluster_signals_no_duplicate_urls(tmp_path):
    """get_cluster_signals never returns two signals sharing a source_url."""
    db_path = str(tmp_path / "test_dedup_cluster.db")
    repo = SqliteTrendRepository(db_path=db_path)
    
    cluster_id = uuid4()
    cluster = TopicCluster(id=cluster_id, canonical_name="Đánh cá vui cực")
    await repo.save_clusters([cluster])
    
    url = "https://youtube.com/watch?v=danh_ca_vui"
    s1 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Đánh cá vui cực tập 1",
        metric_value=100.0,
        source_url=url,
        cluster_id=cluster_id,
        geo_code=GeoCode.VN,
    )
    s2 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Đánh cá vui cực tập 1",
        metric_value=200.0,
        source_url=url,
        cluster_id=cluster_id,
        geo_code=GeoCode.VN,
    )
    
    await repo.save_signals([s1])
    await repo.save_signals([s2])
    
    signals = await repo.get_cluster_signals(cluster_id=cluster_id)
    urls = [s.source_url for s in signals if s.source_url]
    assert len(urls) == len(set(urls)), f"Duplicate URLs returned: {urls}"
    assert len(urls) == 1


@pytest.mark.asyncio
async def test_signals_sharing_a_feed_url_are_kept_apart(tmp_path):
    """Google Trends returns one RSS URL for every keyword it lists.

    The old writer kept them apart by adding the title to the identity. Identity is resolved
    from the keyword itself now, so the URL they share never brings them together, and
    re-polling one of them is a second observation of that keyword rather than an overwrite.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "feed.db"))
    feed_url = "https://trends.google.com/trending/rss?geo=VN"

    def probe(keyword: str, metric: float, hour: int) -> TrendSignal:
        return TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title=keyword,
            metric_value=metric,
            source_url=feed_url,
            geo_code=GeoCode.VN,
            captured_at=datetime(2026, 9, 7, hour, 0, 0, tzinfo=timezone.utc),
            metadata={"keyword": keyword},
        )

    await repo.save_signals([probe("gia vang", 100.0, 10), probe("us open", 200.0, 10)])
    await repo.save_signals([probe("gia vang", 150.0, 11)])

    sources = await _query(repo, "SELECT external_id FROM sources ORDER BY external_id;")
    assert [row[0] for row in sources] == ["keyword:gia vang", "keyword:us open"]

    per_keyword = await _query(
        repo,
        "SELECT s.external_id, o.metric_value FROM observations o"
        " JOIN sources s ON s.id = o.source_id ORDER BY s.external_id, o.observed_at;",
    )
    assert per_keyword == [
        ("keyword:gia vang", 100.0),
        ("keyword:gia vang", 150.0),
        ("keyword:us open", 200.0),
    ], "the re-poll is a second sighting of one keyword, not an overwrite"


@pytest.mark.asyncio
async def test_reclustering_does_not_leave_empty_clusters_behind(tmp_path):
    """A cluster whose last signal moved elsewhere is pruned, not accumulated."""
    from ignis.domain.entities import TopicCluster

    repo = SqliteTrendRepository(db_path=str(tmp_path / "prune.db"))
    stale = TopicCluster(canonical_name="stale topic")
    live = TopicCluster(canonical_name="live topic")
    await repo.save_clusters([stale, live])
    await repo.save_signals([
        TrendSignal(platform=PlatformType.THREADS, raw_title="still here", metric_value=1.0,
                    source_url="https://example.test/1", cluster_id=live.id, geo_code=GeoCode.VN),
    ])

    removed = await repo.prune_empty_clusters()

    assert removed == 1
    remaining = await _query(repo, "SELECT canonical_name FROM topic_clusters;")
    assert [r[0] for r in remaining] == ["live topic"]
    assert await repo.prune_empty_clusters() == 0, "Pruning must be idempotent"
