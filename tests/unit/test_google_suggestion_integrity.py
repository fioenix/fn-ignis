"""Autocomplete may expand a query, never measure its demand or growth."""

from unittest.mock import patch

import httpx
import pytest

from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.connectors.registry import ConnectorPluginRegistry


def response(suggestions):
    return httpx.Response(200, json=["query", suggestions])


@pytest.mark.asyncio
async def test_autocomplete_cannot_emit_a_trends_measurement():
    plugin = GoogleTrendsRssPlugin()
    with patch("httpx.AsyncClient.get", return_value=response(["túi đi làm đẹp"])):
        with pytest.raises(ConnectorExecutionException, match="Autocomplete"):
            await plugin.search_signals(["túi đi làm"])


@pytest.mark.asyncio
async def test_suggestions_retain_variants_without_demand_or_velocity():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"VN": ["{}", "mua {}"]})
    with patch("httpx.AsyncClient.get", return_value=response(["Túi đi làm", "túi đi làm"])):
        batches = await plugin.fetch_suggestions(["túi"], geo=GeoCode.VN)
    assert len(batches) == 1
    batch = batches[0]
    assert batch["platform"] == "google_autocomplete"
    assert batch["data_source"] == "google_autocomplete"
    assert batch["measurement_type"] == "keyword_expansion"
    assert batch["status"] == "HEALTHY"
    assert batch["suggestions"] == [{"query": "Túi đi làm", "type": "autocomplete"}]
    assert batch["suggestions_count"] == 1
    assert batch["probes_executed"] == 2
    assert batch["failed_probes"] == 0
    assert "trends.google.com" not in batch["source_url"]
    assert not {"demand_index", "velocity", "metric_value", "growth_velocity", "timeframe"} & batch.keys()


@pytest.mark.asyncio
async def test_valid_empty_autocomplete_is_not_a_nonzero_demand_floor():
    plugin = GoogleTrendsRssPlugin()
    with patch("httpx.AsyncClient.get", return_value=response([])):
        batch = (await plugin.fetch_suggestions(["zzzz"]))[0]
    assert batch["status"] == "EMPTY_NO_DATA"
    assert batch["suggestions_count"] == 0
    assert batch["probes_executed"] == 1
    assert "demand_index" not in batch


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [
    httpx.Response(429), httpx.Response(200, json={}), response(None),
    response([{"unexpected": "value"}]), response(["valid suggestion", 123]),
])
async def test_refused_or_malformed_suggest_is_missing_not_measured_zero(reply):
    with patch("httpx.AsyncClient.get", return_value=reply):
        batch = (await GoogleTrendsRssPlugin().fetch_suggestions(["túi"]))[0]
    assert batch["status"] == "DEGRADED"
    assert batch["suggestions_count"] is None
    assert batch["probes_executed"] == 0
    assert batch["failed_probes"] == 1


@pytest.mark.asyncio
async def test_global_autocomplete_does_not_silently_request_vietnam():
    with patch("httpx.AsyncClient.get", return_value=response([])) as get:
        batch = (await GoogleTrendsRssPlugin().fetch_suggestions(["bags"], geo=GeoCode.GLOBAL))[0]
    params = get.call_args.kwargs["params"]
    assert "gl" not in params
    assert batch["geo_code"] == "GLOBAL"


@pytest.mark.asyncio
async def test_partial_autocomplete_failure_preserves_known_variants_and_gap():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"VN": ["{}", "mua {}"]})
    with patch("httpx.AsyncClient.get", side_effect=[response(["túi đi làm"]), httpx.ConnectError("offline")]):
        batch = (await plugin.fetch_suggestions(["túi"]))[0]
    assert batch["status"] == "DEGRADED"
    assert batch["suggestions_count"] == 1
    assert batch["probes_executed"] == 1
    assert batch["failed_probes"] == 1


@pytest.mark.asyncio
async def test_registry_reports_unavailable_keyword_trends_as_degraded_not_zero():
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())
    with patch("httpx.AsyncClient.get", return_value=response(["túi đi làm đẹp"])):
        result = await registry.search_with_outcomes(["túi"], target_platforms=[PlatformType.GOOGLE_TRENDS])
    assert result.signals == []
    assert len(result.outcomes) == 1
    assert result.outcomes[0].status.value == "DEGRADED"
    assert result.outcomes[0].queried_keywords == ()
    assert "Autocomplete" in result.outcomes[0].note


@pytest.mark.asyncio
async def test_unavailable_keyword_measurement_does_not_trip_the_working_rss_feed():
    registry = ConnectorPluginRegistry()
    registry.register(GoogleTrendsRssPlugin())
    for _ in range(3):
        search = await registry.search_with_outcomes(["túi"], target_platforms=[PlatformType.GOOGLE_TRENDS])
        assert search.outcomes[0].status.value == "DEGRADED"
    rss = b'''<rss xmlns:ht="https://trends.google.com/trending/rss"><channel><item>
    <title>Macro topic</title><ht:approx_traffic>1K+</ht:approx_traffic>
    <pubDate>Fri, 02 Oct 2026 04:00:00 +0000</pubDate>
    </item></channel></rss>'''
    reply = httpx.Response(200, content=rss, request=httpx.Request("GET", "https://trends.google.com/trending/rss?geo=VN"))
    with patch("httpx.AsyncClient.get", return_value=reply):
        signals = await registry.fetch_from_all()
    assert len(signals) == 1
    assert signals[0].raw_title == "Macro topic"
    assert signals[0].metric_value == 1000.0
