import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from ignis.domain.value_objects import GeoCode, Timeframe
from ignis.infrastructure.persistence.postgres_repository import PostgresTimescaleRepository


def _create_mock_pool(mock_cursor):
    mock_cursor_cm = MagicMock()
    mock_cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_cursor_cm.__aexit__ = AsyncMock(return_value=None)

    mock_conn = MagicMock()
    mock_conn.cursor = MagicMock(return_value=mock_cursor_cm)

    mock_conn_cm = MagicMock()
    mock_conn_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn_cm.__aexit__ = AsyncMock(return_value=None)

    mock_pool = MagicMock()
    mock_pool.connection = MagicMock(return_value=mock_conn_cm)
    return mock_pool


@pytest.mark.asyncio
async def test_save_signals_empty_list():
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    saved_count = await repo.save_signals([])
    assert saved_count == 0


@pytest.mark.asyncio
async def test_save_signals_batch_insert(sample_trend_signal):
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    mock_cursor = AsyncMock()
    repo._pool = _create_mock_pool(mock_cursor)

    count = await repo.save_signals([sample_trend_signal])
    
    assert count == 1
    assert mock_cursor.executemany.called
    query_arg, params_arg = mock_cursor.executemany.call_args[0]
    assert "INSERT INTO trend_signals" in query_arg
    assert len(params_arg) == 1
    assert params_arg[0][0] == sample_trend_signal.platform.value
    assert params_arg[0][1] == sample_trend_signal.raw_title


@pytest.mark.asyncio
async def test_save_clusters_upsert(sample_topic_cluster):
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    mock_cursor = AsyncMock()
    mock_cursor.fetchone.return_value = (sample_topic_cluster.id,)
    repo._pool = _create_mock_pool(mock_cursor)

    await repo.save_clusters([sample_topic_cluster])
    
    assert mock_cursor.execute.called
    query_arg, params_arg = mock_cursor.execute.call_args[0]
    assert "INSERT INTO topic_clusters" in query_arg
    assert "ON CONFLICT (canonical_name) DO UPDATE" in query_arg
    assert "RETURNING id" in query_arg
    assert params_arg[1] == sample_topic_cluster.canonical_name


@pytest.mark.asyncio
async def test_get_top_clusters():
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    
    cluster_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_rows = [
        (str(cluster_id), "AI Agent Trends", "Summary of AI agents", "technology", 92.0, now, now)
    ]
    
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
    repo._pool = _create_mock_pool(mock_cursor)

    clusters = await repo.get_top_clusters(geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, limit=5)
    
    assert len(clusters) == 1
    assert clusters[0].id == cluster_id
    assert clusters[0].canonical_name == "AI Agent Trends"
    assert clusters[0].cross_platform_score == 92.0


@pytest.mark.asyncio
async def test_get_cluster_signals(sample_trend_signal):
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    cluster_id = uuid4()
    now = datetime.now(timezone.utc)
    mock_rows = [
        (
            sample_trend_signal.platform.value,
            sample_trend_signal.raw_title,
            sample_trend_signal.metric_value,
            sample_trend_signal.growth_velocity,
            sample_trend_signal.source_url,
            sample_trend_signal.geo_code.value,
            '{"traffic": "50K+"}',
            now,
            str(cluster_id),
            None  # mission_id
        )
    ]
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=mock_rows)
    repo._pool = _create_mock_pool(mock_cursor)

    signals = await repo.get_cluster_signals(cluster_id=cluster_id, timeframe=Timeframe.LAST_7D)
    assert len(signals) == 1
    assert signals[0].raw_title == sample_trend_signal.raw_title
    assert signals[0].cluster_id == cluster_id


@pytest.mark.asyncio
async def test_platform_credentials_crud():
    repo = PostgresTimescaleRepository(dsn="postgresql://mock")
    mock_cursor = AsyncMock()
    repo._pool = _create_mock_pool(mock_cursor)

    # 1. Test save_platform_credentials
    await repo.save_platform_credentials(
        platform="tiktok",
        auth_type="session_cookies",
        credentials_data={"cookies": [{"name": "sessionid", "value": "123"}]},
    )
    assert mock_cursor.execute.called
    query_arg, params_arg = mock_cursor.execute.call_args[0]
    assert "INSERT INTO platform_credentials" in query_arg
    assert params_arg[0] == "tiktok"

    # 2. Test get_platform_credentials
    mock_cursor.fetchone = AsyncMock(return_value=("tiktok", "session_cookies", '{"cookies": []}', True, None, None))
    creds = await repo.get_platform_credentials("tiktok")
    assert creds is not None
    assert creds["platform"] == "tiktok"
    assert creds["is_active"] is True

    # 3. Test list_platform_credentials
    mock_cursor.fetchall = AsyncMock(return_value=[("tiktok", "session_cookies", True, None, None)])
    cred_list = await repo.list_platform_credentials()
    assert len(cred_list) == 1
    assert cred_list[0]["platform"] == "tiktok"

    # 4. Test delete_platform_credentials
    mock_cursor.rowcount = 1
    deleted = await repo.delete_platform_credentials("tiktok")
    assert deleted is True

