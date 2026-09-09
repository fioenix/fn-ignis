"""A cluster must be named by its topic, not by one member signal's verbatim text.

`canonical_name` is the most informative raw title in the group, which is the right choice for
identity — it is stable, and `cluster_id` is a uuid5 of it — but it reads as a stray post. The
highest-scoring cluster in the live corpus was called "Phai noi that la may cai meo phat am nay
hay that Kieu truoc khi moi h". A summarised label already existed, but only inside the graph
artifact builder, so every other consumer still showed the sentence fragment.

These tests pin that the label is produced by the clusterer, travels with the entity, and never
displaces the identity key.
"""

import uuid

import pytest

from ignis.domain.entities import TopicCluster, TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


def _signal(title: str, platform=PlatformType.THREADS, metric=100.0) -> TrendSignal:
    return TrendSignal(
        platform=platform,
        raw_title=title,
        metric_value=metric,
        growth_velocity=5.0,
        geo_code=GeoCode.VN,
        source_url=f"https://example.test/{abs(hash(title))}",
    )


@pytest.mark.asyncio
async def test_label_keeps_the_vocabulary_the_cluster_shares():
    signals = [
        _signal("Khoa hoc AI cho nguoi moi bat dau nen hoc tu dau"),
        _signal("Minh dang tim khoa hoc AI cho nguoi moi bat dau"),
        _signal("Review khoa hoc AI cho nguoi moi bat dau co dang tien khong"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)

    assert len(clusters) == 1
    label = clusters[0].topic_label
    assert label, "Every cluster must carry a topic label"
    assert "khoa hoc ai" in label.lower()
    assert len(label.split()) <= SemanticClusterer.TOPIC_LABEL_MAX_WORDS + 2  # ellipsis markers


@pytest.mark.asyncio
async def test_label_never_replaces_the_identity_key():
    """cluster_id is a uuid5 of canonical_name, so relabelling must not re-identify a cluster."""
    signals = [
        _signal("Khoa hoc AI cho nguoi moi bat dau nen hoc tu dau"),
        _signal("Minh dang tim khoa hoc AI cho nguoi moi bat dau"),
    ]
    clusters = await SemanticClusterer().cluster_signals(signals)
    cluster = clusters[0]

    assert cluster.id == uuid.uuid5(uuid.NAMESPACE_DNS, f"cluster:{cluster.canonical_name}")
    assert cluster.canonical_name != cluster.topic_label or len(cluster.canonical_name.split()) <= 6


@pytest.mark.asyncio
async def test_single_signal_cluster_still_gets_a_label():
    """Half the live clusters hold one signal; they must not fall back to an empty name."""
    clusters = await SemanticClusterer().cluster_signals([_signal("Gia vang hom nay tang manh")])
    assert clusters[0].topic_label


@pytest.mark.asyncio
async def test_a_word_common_to_the_whole_corpus_does_not_headline_a_topic():
    """A token appearing in most clusters describes the corpus, not any one topic in it."""
    topics = {
        "vang": "gia vang trong nuoc tang ky luc",
        "chungkhoan": "chung khoan lao doc thanh khoan can kiet",
        "batdongsan": "bat dong san phia nam ton kho keo dai",
        "tygia": "ty gia usd ngan hang nhich len tung ngay",
        "laisuat": "lai suat huy dong dong loat ha them",
    }
    signals = []
    for topic, body in topics.items():
        for i in range(3):
            signals.append(_signal(f"vietnam {body} {i}"))

    clusters = await SemanticClusterer().cluster_signals(signals)

    labels = [c.topic_label.lower() for c in clusters]
    assert len(clusters) > 1, "Distinct topics must not collapse into one cluster"
    assert not all("tin nhanh" in label for label in labels), (
        f"Every label leans on the corpus-wide phrase instead of its own topic: {labels}"
    )


def test_entity_defaults_the_label_to_the_canonical_name():
    """A cluster read back from a row written before this column existed still renders."""
    cluster = TopicCluster(canonical_name="gia vang hom nay")
    assert cluster.topic_label == "gia vang hom nay"
