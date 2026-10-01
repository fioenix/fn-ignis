"""An atomic probe returns auditable evidence without creating a Market mission."""

from datetime import datetime, timezone

import pytest

from ignis.application.ports.connector_port import SearchAttestation
from ignis.domain.entities import TrendSignal
from ignis.domain.harness_models import ChannelHealthStatus
from ignis.domain.value_objects import GeoCode, IngestRuntime, PlatformType, Timeframe
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry
from ignis.infrastructure.persistence.sqlite_repository import SqliteTrendRepository


class TacticalYouTubePlugin:
    name = "Synthetic YouTube Search"
    platform = PlatformType.YOUTUBE
    plugin_id = "youtube"
    supports_search = True
    connector_revision = "youtube-v3/test-double-v1"
    http_authority = "official_api"
    requires_paid_quota = False

    async def resolve_ingest_runtime(self):
        return IngestRuntime.HTTP_API

    async def search_signals(
        self,
        keywords,
        geo=GeoCode.VN,
        timeframe=Timeframe.LAST_24H,
        limit=20,
        attestation: SearchAttestation | None = None,
        custom_timeframe=None,
    ):
        for keyword in keywords:
            attestation.executed(keyword)
        attestation.window = custom_timeframe
        return [
            TrendSignal(
                platform=PlatformType.YOUTUBE,
                raw_title="Retail setup friction from a real operator",
                metric_value=4200,
                source_url="https://youtube.example/watch?v=evidence-1",
                geo_code=geo,
                captured_at=datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
                metadata={"source_id": "evidence-1"},
            )
        ]


@pytest.mark.asyncio
async def test_tactical_probe_returns_query_source_time_path_revision_without_market_side_effects(
    tmp_path,
):
    repository = SqliteTrendRepository(str(tmp_path / "tactical.db"))
    registry = ConnectorPluginRegistry(repository=repository)
    registry.register(TacticalYouTubePlugin())

    before = await repository.list_missions(limit=20)
    result = await registry.search_with_outcomes(
        keywords=["retail setup friction"],
        geo=GeoCode.VN,
        timeframe=Timeframe.LAST_7D,
        target_platforms=[PlatformType.YOUTUBE],
        target_surfaces=("youtube",),
        custom_timeframe="7d",
    )
    after = await repository.list_missions(limit=20)

    assert before == after == []
    assert len(result.signals) == 1
    assert result.signals[0].source_url == "https://youtube.example/watch?v=evidence-1"
    assert result.signals[0].captured_at == datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    assert result.signals[0].metadata["connector_surface"] == "youtube"
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert outcome.status is ChannelHealthStatus.HEALTHY
    assert outcome.queried_keywords == ("retail setup friction",)
    assert outcome.queried_window == "7d"
    assert outcome.scope_attestation == {
        "geo": "VN",
        "timeframe": "7d",
        "keywords": ["retail setup friction"],
    }
    assert outcome.authority_tier == "official_api"
    assert outcome.connector_path.endswith("TacticalYouTubePlugin.search_signals")
    assert outcome.connector_revision == "youtube-v3/test-double-v1"
    await repository.close()
