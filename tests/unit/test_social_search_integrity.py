"""Regressions for unmeasured silence and evidence lost during social collection."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from ignis.application.ports.connector_port import SearchAttestation
from ignis.application.use_cases.get_evidence_qualification_batch import GetEvidenceQualificationBatchUseCase
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.connectors.threads.threads_plugin import ThreadsPlugin


def test_threads_qualification_preserves_full_text_and_publication_date():
    text = ("Office retail review. " * 30).strip()
    signal = ThreadsPlugin()._map_browser_post(
        {"pk": "123", "code": "post123", "caption": {"text": text},
         "taken_at": 1759276800, "user": {"username": "reviewer"}},
        geo=GeoCode.VN, keyword="office retail",
    )
    assert signal.published_at == datetime(2025, 10, 1, tzinfo=timezone.utc)
    evidence = GetEvidenceQualificationBatchUseCase._evidence(signal)
    assert evidence["excerpt"] == text
    assert evidence["published_at"] == "2025-10-01T00:00:00+00:00"
    # The evidence batch links to the post without the poster's handle (Spec 015).
    assert evidence["source_url"] == "https://www.threads.com/t/post123"


@pytest.mark.asyncio
async def test_graph_threads_preserves_full_text_and_publication_date():
    plugin = ThreadsPlugin()
    text = "Office retail review. " * 30 + "Contact person@example.com"
    with patch.object(plugin, "_fetch_insights_batch", AsyncMock(return_value={})):
        [signal] = await plugin._map_items([
            {"id": "123", "text": text, "timestamp": "2025-10-01T00:00:00Z"},
        ], "synthetic-token", GeoCode.VN)
    assert signal.published_at == datetime(2025, 10, 1, tzinfo=timezone.utc)
    assert len(signal.metadata["excerpt"]) > 200
    assert "person@example.com" not in signal.metadata["excerpt"]


@pytest.mark.asyncio
async def test_threads_never_collects_internally():
    queries = [f"retail-query-{index}" for index in range(12)]
    attestation = SearchAttestation()
    from ignis.domain.exceptions import ConnectorCapabilityUnavailableException
    with pytest.raises(ConnectorCapabilityUnavailableException, match="HOST_BROWSER_REQUIRED"):
        await ThreadsPlugin().search_signals(queries, attestation=attestation)
    assert attestation.queried == []


@pytest.mark.parametrize("publication,expected", [("exact", 100.0), ("missing", 0.0), ("future", 0.0)])
def test_threads_host_freshness_uses_exact_publication_never_capture(publication, expected):
    from datetime import timedelta
    from ignis.domain.entities import TrendSignal
    from ignis.domain.value_objects import PlatformType
    from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=1) if publication == "exact" else None
    if publication == "future":
        published = now + timedelta(days=1)
    signal = TrendSignal(platform=PlatformType.THREADS, raw_title="Synthetic public observation",
        metric_value=0, source_url="https://www.threads.com/t/Synthetic027", geo_code=GeoCode.VN,
        captured_at=now, published_at=published, metadata={"collection_path": "host_browser:threads-search-top-v1"})
    score = QualityEvaluator().evaluate_quality([signal], timeframe_days=7)
    assert score.data_freshness_score == expected
