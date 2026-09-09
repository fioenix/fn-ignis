import pytest
import re
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, Timeframe
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


@pytest.mark.asyncio
async def test_bug07_summary_matches_signal_count_across_timeframes(tmp_path):
    """Across timeframes the number in the summary and signal_count move together and match."""
    db_path = str(tmp_path / "test_summary.db")
    repo = SqliteTrendRepository(db_path=db_path)
    
    cluster_id = uuid4()
    cluster = TopicCluster(id=cluster_id, canonical_name="Chủ đề AI 2026")
    await repo.save_clusters([cluster])
    
    now = datetime.now(timezone.utc)
    # 2 signals trong 24h
    s1 = TrendSignal(platform=PlatformType.GOOGLE_TRENDS, raw_title="AI 1", cluster_id=cluster_id, captured_at=now - timedelta(hours=2))
    s2 = TrendSignal(platform=PlatformType.YOUTUBE, raw_title="AI 2", cluster_id=cluster_id, captured_at=now - timedelta(hours=5))
    # Two signals inside 7d but outside 24h
    s3 = TrendSignal(platform=PlatformType.TIKTOK, raw_title="AI 3", cluster_id=cluster_id, captured_at=now - timedelta(days=3))
    s4 = TrendSignal(platform=PlatformType.THREADS, raw_title="AI 4", cluster_id=cluster_id, captured_at=now - timedelta(days=5))
    
    await repo.save_signals([s1, s2, s3, s4])
    
    # Query 24h
    clusters_24h = await repo.get_top_clusters(timeframe=Timeframe.LAST_24H)
    assert len(clusters_24h) == 1
    c24 = clusters_24h[0]
    assert len(c24.signals) == 2
    # Extract the signal count from the summary text
    match_24 = re.search(r"(\d+)\s+signals", c24.summary_text)
    assert match_24 is not None, f"summary_text phai chua so tin hieu: {c24.summary_text}"
    assert int(match_24.group(1)) == len(c24.signals) == 2
    
    # Query 7d
    clusters_7d = await repo.get_top_clusters(timeframe=Timeframe.LAST_7D)
    assert len(clusters_7d) == 1
    c7 = clusters_7d[0]
    assert len(c7.signals) == 4
    match_7 = re.search(r"(\d+)\s+signals", c7.summary_text)
    assert match_7 is not None
    assert int(match_7.group(1)) == len(c7.signals) == 4
