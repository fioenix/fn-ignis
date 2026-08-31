import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
from datetime import datetime, timezone

from ignis.application.use_cases.cluster_signals import ClusterSignalsUseCase
from ignis.domain.entities import TrendSignal, TopicCluster
from ignis.domain.value_objects import PlatformType, GeoCode


@pytest.mark.asyncio
async def test_cluster_signals_use_case():
    mock_repo = AsyncMock()
    mock_clusterer = AsyncMock()

    sample_cluster = TopicCluster(
        id=uuid4(),
        canonical_name="AI Agent Platform",
        cross_platform_score=85.0
    )
    mock_clusterer.cluster_signals = AsyncMock(return_value=[sample_cluster])
    mock_repo.save_clusters = AsyncMock()

    use_case = ClusterSignalsUseCase(clusterer=mock_clusterer, repository=mock_repo)

    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="AI Agent",
            metric_value=5000.0,
            geo_code=GeoCode.VN
        )
    ]

    result = await use_case.execute(signals)

    assert len(result) == 1
    assert result[0].canonical_name == "AI Agent Platform"
    assert mock_repo.save_clusters.called
