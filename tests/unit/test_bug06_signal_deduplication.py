import pytest
from datetime import datetime, timezone
from uuid import uuid4
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.interfaces.mcp.server import handle_get_topic_detail


async def _query(repo, sql: str):
    """Small read helper so these tests can assert on stored rows directly."""
    import asyncio, sqlite3

    def _run():
        conn = sqlite3.connect(repo._db_path)
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    return await asyncio.to_thread(_run)


@pytest.mark.asyncio
async def test_bug06_poll_same_url_twice_deduplicates_signal_and_records_metrics(tmp_path):
    """Polling the same URL twice leaves one signal row and two signal_metrics rows."""
    db_path = str(tmp_path / "test_dedup.db")
    repo = SqliteTrendRepository(db_path=db_path)
    
    url = "https://www.tiktok.com/@creator/video/123456789"
    s1 = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="Video viral mẫu",
        metric_value=1000.0,
        growth_velocity=10.0,
        source_url=url,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 9, 7, 10, 0, 0, tzinfo=timezone.utc),
    )
    
    # First poll
    await repo.save_signals([s1])
    
    # Second poll: same URL, higher metric and velocity
    s2 = TrendSignal(
        platform=PlatformType.TIKTOK,
        raw_title="Video viral mẫu",
        metric_value=2500.0,
        growth_velocity=25.0,
        source_url=url,
        geo_code=GeoCode.VN,
        captured_at=datetime(2026, 9, 7, 11, 0, 0, tzinfo=timezone.utc),
    )
    await repo.save_signals([s2])
    
    # trend_signals must hold exactly one row for this URL
    conn = repo._get_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM trend_signals WHERE source_url = ?", (url,))
    signal_count = cur.fetchone()[0]
    assert signal_count == 1, f"trend_signals must hold exactly one row, found {signal_count}"
    
    # signal_metrics must keep both time-series points
    cur.execute("SELECT count(*) FROM signal_metrics")
    metrics_count = cur.fetchone()[0]
    assert metrics_count == 2, f"signal_metrics must hold two rows, found {metrics_count}"
    
    # The metric on trend_signals is refreshed to the latest value
    cur.execute("SELECT metric_value FROM trend_signals WHERE source_url = ?", (url,))
    latest_metric = cur.fetchone()[0]
    assert latest_metric == 2500.0


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
    """Google Trends reports one RSS URL for every keyword it lists.

    Keying dedup on the URL alone collapsed every keyword onto a single row and overwrote it on
    each poll, so the identity has to include the title.
    """
    repo = SqliteTrendRepository(db_path=str(tmp_path / "feed_url.db"))
    feed_url = "https://trends.google.com/trending/rss?geo=VN"

    await repo.save_signals([
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="gia vang", metric_value=100.0,
                    source_url=feed_url, geo_code=GeoCode.VN),
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="us open", metric_value=200.0,
                    source_url=feed_url, geo_code=GeoCode.VN),
    ])
    # Re-polling the same two keywords must update in place, not append.
    await repo.save_signals([
        TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="gia vang", metric_value=150.0,
                    source_url=feed_url, geo_code=GeoCode.VN),
    ])

    rows = await _query(repo, "SELECT raw_title, metric_value FROM trend_signals ORDER BY raw_title;")
    assert [r[0] for r in rows] == ["gia vang", "us open"], f"Distinct keywords must survive: {rows}"
    assert dict(rows)["gia vang"] == 150.0
    assert dict(rows)["us open"] == 200.0


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
