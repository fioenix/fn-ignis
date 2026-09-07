import pytest
from datetime import datetime, timezone
from uuid import uuid4
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository
from ignis.interfaces.mcp.server import handle_get_topic_detail


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
