"""Graph artifact: clusters are the navigable layer, signals are an aggregated density halo."""

import json
import re
from uuid import uuid4

import pytest

from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.templates.html_builder import HtmlArtifactBuilder


def _signals(platform: PlatformType, count: int, title: str = "signal"):
    return [
        TrendSignal(platform=platform, raw_title=f"{title} {i}", metric_value=1000.0, geo_code=GeoCode.VN)
        for i in range(count)
    ]


def _cluster(name: str, score: float, category: str, signals):
    return TopicCluster(
        id=uuid4(),
        canonical_name=name,
        summary_text=f"Aggregated topic from {len(signals)} signals.",
        category=category,
        cross_platform_score=score,
        signals=signals,
    )


def _graph_payload(html: str) -> dict:
    match = re.search(r"const GRAPH = (\{.*?\});", html, re.S)
    assert match, "The template must embed its dataset as a GRAPH constant"
    raw = match.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
    return json.loads(raw)


def test_graph_artifact_exposes_cluster_nodes_with_platform_breakdown():
    clusters = [
        _cluster("AI agent for customer service", 84.0, "tech", _signals(PlatformType.YOUTUBE, 3) + _signals(PlatformType.TIKTOK, 2)),
        _cluster("Gold price today", 55.0, "finance", _signals(PlatformType.GOOGLE_TRENDS, 4)),
    ]
    payload = _graph_payload(HtmlArtifactBuilder().build_graph_artifact(clusters, geo=GeoCode.VN))

    assert len(payload["nodes"]) == 2
    node = next(n for n in payload["nodes"] if n["label"].startswith("AI agent"))
    assert node["platforms"] == {"youtube": 3, "tiktok": 2}
    assert node["signal_count"] == 5
    assert node["momentum"] == "breakout"
    assert node["category"] == "tech"


def test_signal_layer_is_capped_so_dense_clusters_cannot_stall_the_canvas():
    """A cluster with hundreds of signals still renders a bounded number of dots."""
    heavy = _cluster("Dense topic", 70.0, "tech", _signals(PlatformType.TIKTOK, 400))
    payload = _graph_payload(HtmlArtifactBuilder().build_graph_artifact([heavy], geo=GeoCode.VN))

    node = payload["nodes"][0]
    assert node["signal_count"] == 400
    assert len(node["dots"]) == HtmlArtifactBuilder.MAX_SIGNAL_DOTS_PER_CLUSTER


def test_small_clusters_show_one_dot_per_signal():
    light = _cluster("Light topic", 40.0, "tech", _signals(PlatformType.THREADS, 3))
    payload = _graph_payload(HtmlArtifactBuilder().build_graph_artifact([light], geo=GeoCode.VN))
    assert payload["nodes"][0]["dots"] == ["threads"] * 3


def test_edges_link_similar_clusters_and_stay_bounded_per_node():
    clusters = [
        _cluster("AI agent automation guide", 70.0, "tech", _signals(PlatformType.YOUTUBE, 2)),
        _cluster("AI agent automation tutorial", 68.0, "tech", _signals(PlatformType.YOUTUBE, 2)),
        _cluster("Completely unrelated gardening topic", 30.0, "unclassified", _signals(PlatformType.THREADS, 1)),
    ]
    payload = _graph_payload(HtmlArtifactBuilder().build_graph_artifact(clusters, geo=GeoCode.VN))

    linked = {(e["source"], e["target"]) for e in payload["edges"]}
    assert linked, "Similar clusters must be linked"
    by_id = {n["id"]: n["label"] for n in payload["nodes"]}
    for source, target in linked:
        assert "gardening" not in by_id[source] and "gardening" not in by_id[target]

    per_node: dict = {}
    for edge in payload["edges"]:
        per_node[edge["source"]] = per_node.get(edge["source"], 0) + 1
        per_node[edge["target"]] = per_node.get(edge["target"], 0) + 1
    assert all(count <= HtmlArtifactBuilder.MAX_EDGES_PER_NODE for count in per_node.values())


def test_graph_artifact_is_a_self_contained_offline_file():
    html = HtmlArtifactBuilder().build_graph_artifact(
        [_cluster("Topic", 50.0, "tech", _signals(PlatformType.YOUTUBE, 1))], geo=GeoCode.VN
    )
    assert "<canvas" in html
    assert "src=\"http" not in html and "@import url(" not in html


def test_graph_artifact_sanitizes_pii_in_labels():
    cluster = _cluster("Contact me at nguyen.van.a@example.com now", 50.0, "tech", _signals(PlatformType.THREADS, 1))
    payload = _graph_payload(HtmlArtifactBuilder().build_graph_artifact([cluster], geo=GeoCode.VN))
    assert "nguyen.van.a@example.com" not in payload["nodes"][0]["label"]


@pytest.mark.asyncio
async def test_generate_trend_artifact_supports_graph_format(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock, patch

    from ignis.interfaces.mcp import server as srv

    clusters = [_cluster("Topic", 50.0, "tech", _signals(PlatformType.YOUTUBE, 2))]
    use_case = AsyncMock()
    use_case.execute.return_value = clusters
    components = {
        "artifact_builder": HtmlArtifactBuilder(),
        "top_clusters_use_case": use_case,
    }

    with patch.object(srv, "get_components", return_value=components), \
         patch.object(srv, "_get_secure_reports_dir", return_value=tmp_path):
        payload = json.loads(await srv.handle_generate_trend_artifact(geo="VN", format="graph"))

    assert payload["status"] == "SUCCESS"
    assert payload["type"] == "GRAPH"
    assert payload["total_signals"] == 2
    written = tmp_path / "trend_graph_vn.html"
    assert written.exists() and "<canvas" in written.read_text(encoding="utf-8")
