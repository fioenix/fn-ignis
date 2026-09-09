from ignis.domain.value_objects import PlatformType, GeoCode
from ignis.infrastructure.connectors.google_trends.rss_plugin import GoogleTrendsRssPlugin
from ignis.infrastructure.harness.quality_evaluator import QualityEvaluator
from ignis.infrastructure.harness.strategic_reasoner import StrategicMarketReasoner
from ignis.domain.entities import TrendSignal


def test_extensible_enums():
    # Extensible PlatformType without breaking enum
    custom_platform = PlatformType("reddit")
    assert custom_platform.value == "reddit"
    assert custom_platform.name == "REDDIT"

    # Extensible GeoCode without breaking enum
    custom_geo = GeoCode("JP")
    assert custom_geo.value == "JP"
    assert custom_geo.name == "JP"

    # Backward compatibility
    assert PlatformType.YOUTUBE.value == "youtube"
    assert GeoCode.VN.value == "VN"


def test_google_trends_probe_generalization():
    """A geo gets its own registered templates; every other geo falls back to DEFAULT."""
    plugin = GoogleTrendsRssPlugin()
    plugin.register_probe_templates({
        "VN": ["{}", "{} là gì"],
        "DEFAULT": ["{}", "what is {}"],
    })

    vn_probes = plugin._get_probe_patterns("VN")
    assert any("là gì" in p for p in vn_probes)

    us_probes = plugin._get_probe_patterns("US")
    assert any("what is" in p for p in us_probes)
    assert not any("là gì" in p for p in us_probes)


def test_google_trends_probes_fall_back_to_the_bare_keyword():
    """With no registered vocabulary the plugin probes the keyword itself, never a guess."""
    plugin = GoogleTrendsRssPlugin()

    assert plugin._get_probe_patterns("VN") == ["{}"]


def test_international_quality_and_strategic_reasoning():
    evaluator = QualityEvaluator()
    reasoner = StrategicMarketReasoner()

    # Verify English/International title for US market
    title_us = "How to build autonomous AI agents with Python"
    assert evaluator.is_localized(title_us, geo=GeoCode.US) is True

    # Run opportunity discovery for US market
    signals = [
        TrendSignal(
            platform=PlatformType.GOOGLE_TRENDS,
            raw_title="autonomous ai agents",
            metric_value=85.0,
            metadata={"keyword": "autonomous ai agents"},
        ),
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title="How to build autonomous AI agents with Python",
            metric_value=12000.0,
        ),
    ]

    opportunities = reasoner._discover_market_opportunities(
        signals=signals,
        target_keywords=["autonomous ai agents"],
        geo=GeoCode.US,
    )

    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp.topic == "autonomous ai agents"
    assert opp.search_interest_score == 85.0
    assert opp.content_supply_score > 0.0
    assert "No localized videos recorded" not in opp.supporting_signals[0]
