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


# --- the keyword search path -------------------------------------------------------------------
#
# SC-004 promises coverage for this plugin, and until now the whole `search_signals` half of it was
# untested: the Suggest probing, the demand index built on top of it, and the timeframe translation
# that decides which window Google is asked about. That half is what a research mission calls; the
# RSS feed half is what the scheduled worker calls.


def _suggest_response(suggestions):
    """One Google Suggest reply. The API answers `[echo_of_query, [suggestion, ...], ...]`."""
    response = MagicMock()
    response.status_code = 200
    response.json = MagicMock(return_value=["query", list(suggestions)])
    return response


@pytest.mark.asyncio
async def test_search_signals_scores_demand_from_the_probes_that_answered():
    """The demand index is evidence from Suggest, not a constant, so the parts have to be visible.

    Two probe templates, both answering, with one suggestion carrying a registered intent marker.
    The record has to say how many probes were active and which variants were seen, because a
    demand number nobody can decompose is a number nobody can dispute.
    """
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"VN": ["{}", "mua {}"], "DEFAULT": ["{}"]})
    plugin.register_intent_keywords(["mua", "giá"])

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response(["mua vàng", "vàng SJC", "Vàng SJC"])

        signals = await plugin.search_signals(["vàng"], geo=GeoCode.VN)

    assert len(signals) == 1
    signal = signals[0]
    assert signal.platform == PlatformType.GOOGLE_TRENDS
    assert signal.metadata["keyword"] == "vàng"
    assert signal.metadata["active_probes"] == 2, "both templates answered, so both are active"
    # Suggestions are lowercased and deduplicated before counting, so the two spellings of the
    # same query are one variant.
    assert signal.metadata["unique_variants"] == 2
    assert signal.metadata["related_queries"] == ["mua vàng", "vàng sjc"]
    assert signal.metadata["data_source"] == "google_search_dynamic_probes"
    assert signal.source_url == signal.metadata["explore_url"]
    assert "q=v%C3%A0ng" in signal.source_url


@pytest.mark.asyncio
async def test_a_keyword_nothing_answers_for_scores_the_documented_floor_not_zero():
    """An empty result is still a measurement, and the plugin reports it at the band's floor."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])

        signals = await plugin.search_signals(["zzzz"], geo=GeoCode.VN)

    assert signals[0].metric_value == 25.0
    assert signals[0].growth_velocity == 0.0
    assert signals[0].metadata["active_probes"] == 0
    assert signals[0].metadata["related_queries"] == []


@pytest.mark.asyncio
async def test_the_demand_index_never_leaves_its_band_however_much_suggest_returns():
    """Twenty variants, every one matching an intent marker, is still capped at 98."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})
    plugin.register_intent_keywords(["giá"])

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([f"giá vàng {n}" for n in range(40)])

        signals = await plugin.search_signals(["vàng"], geo=GeoCode.VN)

    assert 25.0 <= signals[0].metric_value <= 98.0
    assert signals[0].metric_value == 98.0
    # The record carries at most twelve related queries however many were seen.
    assert len(signals[0].metadata["related_queries"]) == 12
    assert signals[0].metadata["unique_variants"] == 40


@pytest.mark.asyncio
async def test_a_failing_suggest_probe_lowers_the_score_rather_than_failing_the_search():
    """Suggest is an unofficial endpoint. One refusing must not lose the whole mission."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}", "mua {}"]})

    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Network down")):
        signals = await plugin.search_signals(["vàng"], geo=GeoCode.VN)

    assert len(signals) == 1
    assert signals[0].metadata["active_probes"] == 0
    assert signals[0].metric_value == 25.0


@pytest.mark.asyncio
async def test_a_non_200_from_suggest_yields_no_variants():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        refused = MagicMock()
        refused.status_code = 429
        refused.json = MagicMock(return_value=["query", ["never read"]])
        mock_get.return_value = refused

        signals = await plugin.search_signals(["vàng"], geo=GeoCode.VN)

    assert signals[0].metadata["unique_variants"] == 0


def test_probe_templates_without_a_placeholder_are_refused_at_registration():
    """A template with no `{}` would probe the literal template instead of the keyword."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"vn": ["{}", "mua gì hôm nay"], "US": ["buy something"]})

    assert plugin._get_probe_patterns("VN") == ["{}"]
    # Every pattern for US was rejected, so US keeps no entry at all and falls back.
    assert plugin._get_probe_patterns("US") == [GoogleTrendsRssPlugin.BARE_KEYWORD_TEMPLATE]


def test_with_no_templates_registered_the_bare_keyword_is_the_only_probe():
    """The documented degraded mode: measurable, and it says so rather than returning nothing."""
    plugin = GoogleTrendsRssPlugin()
    assert plugin._get_probe_patterns("VN") == [GoogleTrendsRssPlugin.BARE_KEYWORD_TEMPLATE]


def test_intent_keywords_are_normalized_and_deduplicated_at_registration():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_intent_keywords([" Mua ", "mua", "GIÁ", "", "   ", None])
    assert plugin._intent_keywords == ["giá", "mua"]


@pytest.mark.parametrize(
    "requested,google",
    [
        ("1d", "now 1-d"),
        ("24h", "now 1-d"),
        ("now 1-d", "now 1-d"),
        ("7d", "now 7-d"),
        ("now 7-d", "now 7-d"),
        ("30d", "today 1-m"),
        ("1m", "today 1-m"),
        ("today 1-m", "today 1-m"),
        ("90d", "today 3-m"),
        ("3m", "today 3-m"),
        ("today 3-m", "today 3-m"),
        ("12m", "today 12-m"),
        ("1y", "today 12-m"),
        ("today 12-m", "today 12-m"),
        ("5y", "today 5-y"),
        ("today 5-y", "today 5-y"),
        # Unrecognized input: anything mentioning 90 lands on the quarter, everything else on the
        # week. Stated here because it is the branch a caller hits by typing a window that does not
        # exist, and it must not raise.
        ("last 90 days", "today 3-m"),
        ("whenever", "now 7-d"),
        ("", "now 7-d"),
    ],
)
def test_every_documented_timeframe_alias_maps_to_a_google_window(requested, google):
    assert GoogleTrendsRssPlugin()._normalize_timeframe(requested) == google


@pytest.mark.asyncio
async def test_a_custom_timeframe_overrides_the_enum_and_both_are_recorded():
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])
        signals = await plugin.search_signals(
            ["vàng"], geo=GeoCode.VN, timeframe=Timeframe.LAST_24H, custom_timeframe="12m"
        )

    meta = signals[0].metadata
    assert meta["timeframe_requested"] == "12m"
    assert meta["timeframe_google"] == "today 12-m"
    assert "date=today%2012-m" in meta["explore_url"]


# --- geo, parsing fallbacks and the failure contract --------------------------------------------


@pytest.mark.asyncio
async def test_a_global_search_carries_no_geo_restriction():
    """GLOBAL is the absence of a region, not a region code Google would recognize."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({"DEFAULT": ["{}"]})

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = _suggest_response([])
        signals = await plugin.search_signals(["ai"], geo=GeoCode.GLOBAL)

    assert "geo=&" in signals[0].metadata["explore_url"] + "&"


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
