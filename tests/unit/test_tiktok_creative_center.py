import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from ignis.domain.value_objects import PlatformType, GeoCode, Timeframe
from ignis.infrastructure.connectors.tiktok.creative_center_plugin import TikTokCreativeCenterPlugin
from ignis.interfaces.mcp.server import handle_get_tiktok_creative_center_trends


@pytest.mark.asyncio
async def test_tiktok_creative_center_plugin_properties():
    plugin = TikTokCreativeCenterPlugin()
    assert plugin.platform == PlatformType.TIKTOK
    assert "Creative Center" in plugin.name
    assert await plugin.is_healthy() is True


def test_metric_number_parser():
    plugin = TikTokCreativeCenterPlugin()
    assert plugin._parse_metric_number("346.2K") == 346200.0
    assert plugin._parse_metric_number("1.9B") == 1900000000.0
    assert plugin._parse_metric_number("28M") == 28000000.0
    assert plugin._parse_metric_number("500") == 500.0
    assert plugin._parse_metric_number("") == 0.0


@pytest.mark.asyncio
async def test_tiktok_creative_center_fetch_signals_mocked():
    plugin = TikTokCreativeCenterPlugin()
    mock_data = [
        {
            "rank": 1,
            "hashtag": "#golivegrowfast",
            "category": "News & Entertainment",
            "posts": "346.2K",
            "views": "1.9B",
            "posts_count": 346200.0,
            "views_count": 1900000000.0,
        },
        {
            "rank": 2,
            "hashtag": "#tiktokshop99",
            "category": "Apparel & Accessories",
            "posts": "28K",
            "views": "120M",
            "posts_count": 28000.0,
            "views_count": 120000000.0,
        }
    ]

    with patch.object(plugin, "fetch_macro_trends", new_callable=AsyncMock) as mock_macro:
        mock_macro.return_value = mock_data

        signals = await plugin.fetch_signals(geo=GeoCode.VN, timeframe=Timeframe.LAST_7D, limit=10)
        assert len(signals) == 2
        assert signals[0].platform == PlatformType.TIKTOK
        assert signals[0].raw_title == "#golivegrowfast (News & Entertainment)"
        assert signals[0].metric_value == 1900000000.0
        assert signals[0].source_url == "https://www.tiktok.com/tag/golivegrowfast"
        assert signals[0].metadata["rank"] == 1
        assert signals[0].metadata["posts_formatted"] == "346.2K"


@pytest.mark.asyncio
async def test_handle_get_tiktok_creative_center_trends():
    mock_comp = {
        "registry": MagicMock(),
        "tiktok_auth_manager": AsyncMock(),
    }
    mock_comp["registry"]._plugins = {}

    with patch("ignis.interfaces.mcp.server.get_components", return_value=mock_comp):
        with patch.object(TikTokCreativeCenterPlugin, "fetch_macro_trends", new_callable=AsyncMock) as mock_macro:
            mock_macro.return_value = [
                {
                    "rank": 1,
                    "hashtag": "#golivegrowfast",
                    "category": "News & Entertainment",
                    "posts": "346.2K",
                    "views": "1.9B",
                }
            ]

            resp_json = await handle_get_tiktok_creative_center_trends(geo="VN", period=7, limit=10)
            resp = json.loads(resp_json)
            assert resp["status"] == "SUCCESS"
            assert resp["geo_code"] == "VN"
            assert resp["total_hashtags"] == 1
            assert resp["trending_hashtags"][0]["hashtag"] == "#golivegrowfast"


def _fake_row_lines(count: int) -> list:
    lines = ["Trending Hashtags", "Hashtag", "Posts", "Views"]
    for rank in range(1, count + 1):
        lines += [str(rank), f"#tag{rank}", "News & Entertainment", f"{rank}K", "POSTS", f"{rank}M", "VIEWS"]
    return lines


def test_bug10_parser_reads_every_rendered_row_not_only_three():
    plugin = TikTokCreativeCenterPlugin()
    rows = plugin._parse_trend_rows(_fake_row_lines(20), limit=30)
    assert len(rows) == 20, f"Parser only read {len(rows)} hashtags"
    assert rows[0]["hashtag"] == "#tag1"
    assert rows[-1]["rank"] == 20
    assert rows[4]["views_count"] == 5_000_000.0


def test_bug10_parser_respects_limit_and_industry_filter():
    plugin = TikTokCreativeCenterPlugin()
    assert len(plugin._parse_trend_rows(_fake_row_lines(20), limit=5)) == 5
    assert plugin._parse_trend_rows(_fake_row_lines(20), limit=30, industry="Apparel") == []


@pytest.mark.asyncio
async def test_bug10_load_all_rows_paginates_until_no_new_rows():
    """The page lazy-loads: scroll and click "View More" until no new row appears."""
    plugin = TikTokCreativeCenterPlugin()
    pages_text = [
        "\n".join(_fake_row_lines(3)),
        "\n".join(_fake_row_lines(9)),
        "\n".join(_fake_row_lines(15)),
        "\n".join(_fake_row_lines(15)),
    ]
    page = MagicMock()
    page.inner_text = AsyncMock(side_effect=pages_text)
    page.query_selector = AsyncMock(return_value=None)
    page.evaluate = AsyncMock()
    page.wait_for_timeout = AsyncMock()

    text = await plugin._load_all_rows(page, limit=30)
    rows = plugin._parse_trend_rows([t.strip() for t in text.split("\n") if t.strip()], limit=30)
    assert len(rows) == 15
    assert page.evaluate.await_count >= 2


def test_a_row_without_a_category_column_does_not_report_a_view_count_as_its_category():
    """The ranking table is parsed by position, so a missing column shifts a metric into place.

    Three live clusters ended up filed under the categories "27.6k", "6.4k" and "28k", which are
    view counts. `category` is taken from `lines[i + 2]`; when that row carries no category, the
    next line is the posts or views figure.
    """
    plugin = TikTokCreativeCenterPlugin.__new__(TikTokCreativeCenterPlugin)
    lines = [
        "1", "#vietnamvodich", "27.6K", "POSTS", "1.2M", "VIEWS",
        "2", "#tetnguyendan", "Sports", "3.4K", "POSTS", "5.6M", "VIEWS",
    ]

    rows = plugin._parse_trend_rows(lines, limit=10)
    by_hashtag = {r["hashtag"]: r for r in rows}

    assert by_hashtag["#vietnamvodich"]["category"] == "", (
        "A metric must not be reported as a category: "
        f"{by_hashtag['#vietnamvodich']['category']!r}"
    )
    assert by_hashtag["#tetnguyendan"]["category"] == "Sports", "A real category still survives"
