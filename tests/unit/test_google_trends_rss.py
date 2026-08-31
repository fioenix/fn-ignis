import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
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
