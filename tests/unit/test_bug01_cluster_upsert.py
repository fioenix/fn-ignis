import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.normalization import normalize_cluster_name
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository


def test_normalize_cluster_name_case_and_whitespace():
    assert normalize_cluster_name("ừ cơm gà thì cơm gà ") == normalize_cluster_name("Ừ Cơm Gà  thì cơm gà")
    assert normalize_cluster_name("  AI  agent  ") == "ai agent"
    assert normalize_cluster_name("Bánh Mì Nướng ") == "bánh mì nướng"


@pytest.mark.asyncio
async def test_save_clusters_batch_with_duplicate_normalized_names():
    """Verify that a single batch containing duplicate normalized names is deduped into 1 cluster."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = None  # Mocking new cluster insertion

    mock_cursor_cm = MagicMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)
    mock_tx_cm = MagicMock()
    mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
    mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx_cm)

    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_cm)

    repo = PostgresTimescaleRepository(dsn="postgresql://mock", pool=mock_pool)

    sig1 = TrendSignal(
        platform=PlatformType.THREADS,
        raw_title="Signal 1",
        metric_value=10.0,
        geo_code=GeoCode.VN,
    )
    sig2 = TrendSignal(
        platform=PlatformType.YOUTUBE,
        raw_title="Signal 2",
        metric_value=20.0,
        geo_code=GeoCode.VN,
    )

    c1 = TopicCluster(
        id=uuid4(),
        canonical_name="ừ cơm gà thì cơm gà ",
        cross_platform_score=40.0,
        signals=[sig1],
    )
    c2 = TopicCluster(
        id=uuid4(),
        canonical_name="Ừ Cơm Gà  thì cơm gà",
        cross_platform_score=60.0,
        signals=[sig2],
    )

    await repo.save_clusters([c1, c2])

    # Should execute find once, then insert once because the batch deduplicated c1 and c2
    assert mock_cursor.execute.call_count == 2
    find_query = mock_cursor.execute.call_args_list[0][0][0]
    insert_query = mock_cursor.execute.call_args_list[1][0][0]
    assert "SELECT id, canonical_name" in find_query
    assert "INSERT INTO topic_clusters" in insert_query

    # Both signals should be preserved in the deduped cluster
    assert len(c1.signals) == 2


@pytest.mark.asyncio
async def test_save_clusters_idempotency_same_payload():
    """Calling save_clusters multiple times with same payload does not error and updates existing cluster."""
    mock_cursor = AsyncMock()
    existing_id = uuid4()
    # First call: not found -> insert. Second call: found -> update
    mock_cursor.fetchone.side_effect = [None, (existing_id,)]

    mock_cursor_cm = MagicMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)
    mock_tx_cm = MagicMock()
    mock_tx_cm.__aenter__ = AsyncMock(return_value=None)
    mock_tx_cm.__aexit__ = AsyncMock(return_value=None)
    mock_conn.transaction = MagicMock(return_value=mock_tx_cm)

    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_cm)

    repo = PostgresTimescaleRepository(dsn="postgresql://mock", pool=mock_pool)

    cluster = TopicCluster(
        id=existing_id,
        canonical_name="AI Agents Automation",
        cross_platform_score=75.0,
        signals=[],
    )

    # First pass: Insert
    await repo.save_clusters([cluster])
    assert mock_cursor.execute.call_count == 2
    assert "INSERT INTO topic_clusters" in mock_cursor.execute.call_args_list[1][0][0]

    # Second pass: Update (Idempotent)
    await repo.save_clusters([cluster])
    assert mock_cursor.execute.call_count == 4
    assert "UPDATE topic_clusters SET" in mock_cursor.execute.call_args_list[3][0][0]
