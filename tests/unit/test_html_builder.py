from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


def test_build_dashboard_artifact(sample_topic_cluster):
    builder = HtmlArtifactBuilder()
    html = builder.build_dashboard_artifact([sample_topic_cluster], geo=GeoCode.VN)

    assert "<!DOCTYPE html>" in html
    assert "FN-IGNIS" in html
    assert "Generative AI" in html
    assert str(sample_topic_cluster.cross_platform_score) in html
    assert "VN" in html


def test_build_topic_card_artifact(sample_topic_cluster, sample_trend_signal):
    builder = HtmlArtifactBuilder()
    html = builder.build_topic_card_artifact(sample_topic_cluster, [sample_trend_signal])

    assert "<!DOCTYPE html>" in html
    assert "Generative AI" in html
    assert sample_trend_signal.raw_title in html


def test_build_mission_report_artifact_with_qualitative_sections(sample_trend_signal):
    from ignis.domain.entities import ResearchMission
    from datetime import datetime, timezone
    builder = HtmlArtifactBuilder()

    mission = ResearchMission(
        title="AI Agent Market Opportunity in Vietnam",
        keywords=["ai agent", "chatbot"],
        shortcode="IGN-TEST",
        geo_code=GeoCode.VN,
        created_at=datetime.now(timezone.utc),
    )

    customer_inquiries = [
        {
            "author": "Nguyen Van A",
            "inquiry": "Giá bao nhiêu vậy shop? Có dùng được cho Mac không?",
            "likes": 5,
            "video_title": "AI Agent Overview",
        }
    ]

    search_suggestions = [
        {
            "keyword": "ai agent",
            "suggestions": [
                {"query": "ai agent tiktok shop", "type": "search_guide"},
                {"query": "#xiaozhi", "type": "trending_hashtag"},
            ]
        }
    ]

    macro_trends = [
        {
            "rank": 1,
            "hashtag": "#golivegrowfast",
            "category": "News & Entertainment",
            "views": "1.9B",
            "posts": "346K",
        }
    ]

    html = builder.build_mission_report_artifact(
        mission=mission,
        signals=[sample_trend_signal],
        platform_breakdown={"google_trends": 1, "tiktok": 1},
        customer_inquiries=customer_inquiries,
        search_suggestions=search_suggestions,
        macro_trends=macro_trends,
    )

    assert "<!DOCTYPE html>" in html
    assert "Voice of Customer" in html
    assert "Giá bao nhiêu vậy shop?" in html
    assert "Derivative Search Demand" in html
    assert "ai agent tiktok shop" in html
    assert "Macro Radar" in html
    assert "#golivegrowfast" in html


def test_html_builder_multi_currency_and_number_filters():
    builder = HtmlArtifactBuilder()
    currency_fn = builder._env.filters["format_currency"]
    number_fn = builder._env.filters["format_number"]

    assert currency_fn(150000, GeoCode.VN) == "150.000 ₫"
    assert currency_fn(150, GeoCode.US) == "$150"
    assert currency_fn(150.5, GeoCode.GLOBAL) == "$150.50"
    assert currency_fn(200, "SG") == "S$200"
    assert currency_fn(99, "EU") == "€99.00"

    assert number_fn(1500000) == "1.5M"
    assert number_fn(25400) == "25.4K"
    assert number_fn(850) == "850"


