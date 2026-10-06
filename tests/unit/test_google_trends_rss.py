import pytest
from unittest.mock import patch, MagicMock
import httpx

from ignis.domain.exceptions import ConnectorExecutionException
from ignis.domain.value_objects import GeoCode, PlatformType, Timeframe
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin


SAMPLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
  <channel>
    <title>Daily Search Trends</title>
    <item>
      <title>Giá vàng hôm nay</title>
      <ht:approx_traffic>100,000+</ht:approx_traffic>
      <description>Giá vàng trong nước biến động mạnh</description>
      <link>https://trends.google.com/trending/story?geo=VN&amp;id=123</link>
      <pubDate>Mon, 31 Aug 2026 04:00:00 +0000</pubDate>
      <ht:news_item>
        <ht:news_item_title>Giá vàng 9999 tăng vọt</ht:news_item_title>
        <ht:news_item_snippet>Thị trường vàng ghi nhận khối lượng giao dịch đột biến...</ht:news_item_snippet>
        <ht:news_item_url>https://news.example.com/gold</ht:news_item_url>
        <ht:news_item_source>VnExpress</ht:news_item_source>
      </ht:news_item>
    </item>
    <item>
      <title>AI Trends 2026</title>
      <ht:approx_traffic>50K+</ht:approx_traffic>
      <description>Xu hướng trí tuệ nhân tạo</description>
      <link>https://trends.google.com/trending/story?geo=VN&amp;id=456</link>
      <pubDate>Mon, 31 Aug 2026 03:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_google_trends_rss_parse():
    plugin = GoogleTrendsRssPlugin()
    assert plugin.platform == PlatformType.GOOGLE_TRENDS
    assert "Google Trends" in plugin.name

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = SAMPLE_RSS_XML
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)

        assert len(signals) == 2
        
        # Test item 1
        s1 = signals[0]
        assert s1.platform == PlatformType.GOOGLE_TRENDS
        assert s1.raw_title == "Giá vàng hôm nay"
        assert s1.metric_value == 100000.0
        assert s1.geo_code == GeoCode.VN
        assert "Giá vàng 9999 tăng vọt" in s1.metadata.get("news_title", "")
        
        # Test item 2
        s2 = signals[1]
        assert s2.raw_title == "AI Trends 2026"
        assert s2.metric_value == 50000.0


@pytest.mark.asyncio
async def test_google_trends_rss_traffic_parser():
    plugin = GoogleTrendsRssPlugin()
    assert plugin._parse_traffic("100,000+") == 100000.0
    assert plugin._parse_traffic("50K+") == 50000.0
    assert plugin._parse_traffic("2M+") == 2000000.0
    assert plugin._parse_traffic("invalid") == 0.0


@pytest.mark.asyncio
async def test_google_trends_rss_is_healthy():
    plugin = GoogleTrendsRssPlugin()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp
        assert await plugin.is_healthy() is True

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network down")):
        assert await plugin.is_healthy() is False


@pytest.mark.asyncio
async def test_each_trending_topic_gets_its_own_url_not_the_feed_url():
    """Google repeats the feed URL in every item's <link>, which is not a per-topic identity."""
    rss = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
      <channel>
        <item>
          <title>gia vang</title>
          <link>https://trends.google.com/trending/rss?geo=VN</link>
          <ht:approx_traffic>50,000+</ht:approx_traffic>
        </item>
        <item>
          <title>us open</title>
          <link>https://trends.google.com/trending/rss?geo=VN</link>
          <ht:approx_traffic>20,000+</ht:approx_traffic>
        </item>
      </channel>
    </rss>"""

    plugin = GoogleTrendsRssPlugin()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = rss
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        signals = await plugin.fetch_signals(geo=GeoCode.VN, limit=10)

    urls = [s.source_url for s in signals]
    assert len(set(urls)) == len(urls), f"Every trending topic needs its own URL: {urls}"
    assert all("/trending/rss" not in (u or "") for u in urls)
    assert "q=gia%20vang" in urls[0]


# Autocomplete belongs to keyword expansion, not measured Trends observations.


def _suggest_response(suggestions):
    """One Google Suggest reply. The API answers `[echo_of_query, [suggestion, ...], ...]`."""
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value=["query", list(suggestions)])
    return response


@pytest.mark.asyncio
async def test_suggestions_preserve_the_queries_from_each_probe():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"VN": ["{}", "mua {}"], "DEFAULT": ["{}"]})
    plugin.register_intent_keywords(["mua", "giá"])

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response(["mua vàng", "vàng SJC", "Vàng SJC"])

        batches = await plugin.fetch_suggestions(["vàng"], geo=GeoCode.VN)

    assert len(batches) == 1
    batch = batches[0]
    assert batch["keyword"] == "vàng"
    assert batch["probes_executed"] == 2
    assert batch["suggestions_count"] == 2
    assert batch["suggestions"] == [
        {"query": "mua vàng", "type": "autocomplete"},
        {"query": "vàng SJC", "type": "autocomplete"},
    ]


@pytest.mark.asyncio
async def test_empty_suggestions_do_not_create_a_trend_signal():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])

        batch = (await plugin.fetch_suggestions(["zzzz"], geo=GeoCode.VN))[0]

    assert batch["suggestions_count"] == 0
    assert batch["status"] == "EMPTY_NO_DATA"
    assert "metric_value" not in batch


@pytest.mark.asyncio
async def test_suggestion_variants_are_not_scored_or_silently_truncated():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})
    plugin.register_intent_keywords(["giá"])

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([f"giá vàng {n}" for n in range(40)])

        batch = (await plugin.fetch_suggestions(["vàng"], geo=GeoCode.VN))[0]

    assert batch["suggestions_count"] == 40
    assert len(batch["suggestions"]) == 40
    assert "demand_index" not in batch


@pytest.mark.asyncio
async def test_failed_suggest_reports_a_gap_not_a_demand_score():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}", "mua {}"]})

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network down")):
        batch = (await plugin.fetch_suggestions(["vàng"], geo=GeoCode.VN))[0]

    assert batch["status"] == "DEGRADED"
    assert batch["suggestions_count"] is None
    assert batch["failed_probes"] == 2


@pytest.mark.asyncio
async def test_a_non_200_from_suggest_is_not_a_valid_empty_reply():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        refused = MagicMock()
        refused.status_code = 429
        refused.json = MagicMock(return_value=["query", ["never read"]])
        mock_get.return_value = refused

        batch = (await plugin.fetch_suggestions(["vàng"], geo=GeoCode.VN))[0]

    assert batch["status"] == "DEGRADED"
    assert batch["suggestions_count"] is None


def test_probe_templates_without_a_placeholder_are_refused_at_registration():
    """A template with no `{}` would probe the literal template instead of the keyword."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"vn": ["{}", "mua gì hôm nay"], "US": ["buy something"]})

    assert plugin._get_probe_patterns("VN") == ["{}"]
    # Every pattern for US was rejected, so US keeps no entry at all and falls back.
    assert plugin._get_probe_patterns("US") == [GoogleTrendsRssPlugin.BARE_KEYWORD_TEMPLATE]


def test_with_no_templates_registered_the_bare_keyword_is_the_only_probe():
    """The bare keyword can expand queries without stored market-specific phrasing."""
    plugin = GoogleTrendsRssPlugin()
    assert plugin._get_probe_patterns("VN") == [GoogleTrendsRssPlugin.BARE_KEYWORD_TEMPLATE]


def test_intent_keywords_are_normalized_and_deduplicated_at_registration():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_intent_keywords([" Mua ", "mua", "GIÁ", "", "   ", None])
    assert plugin._intent_keywords == ["giá", "mua"]


@pytest.mark.asyncio
async def test_a_custom_timeframe_cannot_turn_autocomplete_into_a_time_series():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])
        with pytest.raises(ConnectorExecutionException, match="unavailable"):
            await plugin.search_signals(
                ["vàng"], geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, custom_timeframe="12m"
            )


# --- geo, parsing fallbacks and the failure contract --------------------------------------------


@pytest.mark.asyncio
async def test_global_suggestions_disclose_the_requested_scope():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])
        batch = (await plugin.fetch_suggestions(["ai"], geo=GeoCode.GLOBAL))[0]

    assert batch["geo_code"] == "GLOBAL"
    assert "timeframe" not in batch


def test_traffic_and_publication_date_degrade_instead_of_raising():
    """A feed item missing either field is common, and it is not a reason to lose the item."""
    plugin = GoogleTrendsRssPlugin()

    assert plugin._parse_traffic(None) == 0.0
    assert plugin._parse_traffic("") == 0.0

    # An unparseable date falls back to now rather than propagating; the signal keeps a timestamp.
    fallback = plugin._parse_pub_date("not a date at all")
    assert fallback.tzinfo is not None
    assert plugin._parse_pub_date(None).tzinfo is not None
    assert plugin._parse_pub_date("Mon, 31 Aug 2026 04:00:00 +0000").year == 2026


@pytest.mark.asyncio
async def test_an_unreadable_feed_is_reported_as_a_connector_failure():
    """The registry's circuit breaker reads this exception type; a bare parse error would pass it."""
    plugin = GoogleTrendsRssPlugin()

    with patch("httpx.AsyncClient.get") as mock_get:
        broken = MagicMock()
        broken.status_code = 200
        broken.text = "<rss><channel><item>truncated"
        broken.raise_for_status = MagicMock()
        mock_get.return_value = broken

        with pytest.raises(ConnectorExecutionException):
            await plugin.fetch_signals(geo=GeoCode.VN)
