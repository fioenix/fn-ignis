import pytest
from ignis.domain.value_objects import GeoCode
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


def test_build_dashboard_artifact(sample_topic_cluster):
    builder = HtmlArtifactBuilder()
    html = builder.build_dashboard_artifact([sample_topic_cluster], geo=GeoCode.VN)

    assert "<!DOCTYPE html>" in html
    assert "fn-ignis" in html
    assert "Generative AI" in html
    assert str(sample_topic_cluster.cross_platform_score) in html
    assert "Geo: VN" in html


def test_build_topic_card_artifact(sample_topic_cluster, sample_trend_signal):
    builder = HtmlArtifactBuilder()
    html = builder.build_topic_card_artifact(sample_topic_cluster, [sample_trend_signal])

    assert "<!DOCTYPE html>" in html
    assert "Generative AI" in html
    assert sample_trend_signal.raw_title in html
    assert "Nguồn ↗" in html
