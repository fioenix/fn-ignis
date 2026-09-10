"""A topic label has to read as a topic.

Measured across the 40 stored clusters before this change: 24 labels were wrapped in ellipses,
several were trimmed to a stranded two-word fragment ("bao so" out of a weather bulletin, "ba
ve" out of a family story), three were a dot-joined token list, and one carried half a quoted
phrase. Fixture titles below are Vietnamese because that is the subject under test.
"""

import pytest

from ignis.domain.entities import TrendSignal
from ignis.domain.value_objects import GeoCode, PlatformType
from ignis.infrastructure.clustering.semantic_clusterer import SemanticClusterer


def _signals(titles):
    return [
        TrendSignal(
            platform=PlatformType.YOUTUBE,
            raw_title=title,
            metric_value=1000.0,
            geo_code=GeoCode.VN,
        )
        for title in titles
    ]


def _label(clusterer, canonical, titles, doc_freq=None, total=20):
    return clusterer._build_topic_label(
        canonical, _signals(titles), doc_freq or {}, total
    )


def test_a_label_is_never_wrapped_in_ellipses():
    """The label is a summary already; marking it as an excerpt only looks broken."""
    clusterer = SemanticClusterer()
    titles = [
        "hồi hộp hơn cả thi hoa hậu là match day 2026 của các trường",
        "match day 2026 đã kết thúc rồi mọi người",
        "chờ match day 2026 mãi mới tới",
    ]

    label = _label(clusterer, titles[0], titles)

    assert "…" not in label
    assert "match day 2026" in label


def test_trimming_to_the_shared_tokens_leaves_a_readable_phrase():
    """It used to shrink to exactly two words, which reads as nothing on its own."""
    clusterer = SemanticClusterer()
    titles = [
        "nhắm vào đất liền bão số 6 dự báo thời tiết hôm nay",
        "tin bão số 6 mới nhất",
        "đường đi của bão số 6",
    ]

    label = _label(clusterer, titles[0], titles)

    assert len(label.split()) >= SemanticClusterer.TOPIC_LABEL_MIN_WORDS
    assert "bão số" in label


def test_the_fallback_never_headlines_a_generic_word():
    """A word that cannot identify a topic cannot label one either.

    The clusterer already holds this vocabulary for the similarity guard. Before it was
    consulted here, a label came out as three function words joined with a separator.
    """
    clusterer = SemanticClusterer()
    clusterer.register_ambiguous_unigrams(["cho", "cách", "của"])
    titles = [
        "có ai dùng dầu cá này cho bé chưa cách dùng thế nào",
        "cho bé uống dầu cá cách nào chuẩn",
        "dầu cá cho bé cách dùng",
    ]

    label = _label(clusterer, titles[0], titles)

    assert "cho" not in label.split(" · ")
    assert "cách" not in label.split(" · ")


def test_a_run_of_tokens_is_returned_as_the_phrase_it_forms():
    """A park named "le thi rieng" is one name, not three keywords.

    Exercised directly: reaching the fallback through _build_topic_label needs every token
    excluded from the shared set at once, which makes for a fixture that proves less than it
    obscures.
    """
    words = "công viên văn hoá lê thị riêng có gì chơi".split()
    normalized = [w.lower() for w in words]

    phrase = SemanticClusterer._contiguous_phrase(words, normalized, ["lê", "thị", "riêng"])

    assert phrase == "lê thị riêng"


def test_scattered_tokens_do_not_pretend_to_be_a_phrase():
    """Two tokens at opposite ends of a title are not a name, and must stay a token list."""
    words = "lê hôm nay đi chơi rất riêng".split()
    normalized = [w.lower() for w in words]

    assert SemanticClusterer._contiguous_phrase(words, normalized, ["lê", "riêng"]) is None


def test_the_fallback_prefers_the_phrase_over_a_dot_list():
    """The whole path, with a doc frequency that keeps every token out of the shared set.

    A token joins `shared` only when it recurs at quorum AND is rare across clusters. Handing
    the target tokens a document frequency above the ceiling keeps them out, which is what
    drives the label into the fallback while leaving them distinctive enough to rank.
    """
    clusterer = SemanticClusterer()
    canonical = "lê thị riêng lê thị riêng"
    titles = [canonical, canonical, canonical]
    doc_freq = {"lê": 4, "thị": 4, "riêng": 4}

    label = _label(clusterer, canonical, titles, doc_freq=doc_freq, total=20)

    assert "·" not in label, f"a run of tokens must not be dot-joined: {label!r}"
    assert "lê thị riêng" in label


@pytest.mark.parametrize("canonical,forbidden", [
    ('ác mộng đẹp đạt g chapter 3 đẹp album "ác mộng đẹp phần hai', '"'),
    ("như một người dưng (jerk drill x synth club remix bản đầy đủ", "("),
])
def test_a_window_never_keeps_half_a_quoted_phrase(canonical, forbidden):
    """A symmetric quote needs a parity test, not a comparison of two counts.

    Comparing count('"') with count('"') is always equal, so the first version of this check
    never fired and 'album "ac mong dep' kept its dangling quote.
    """
    clusterer = SemanticClusterer()
    titles = [canonical, canonical.replace("đầy đủ", "ngắn"), canonical]

    label = _label(clusterer, canonical, titles)

    if forbidden == '"':
        assert label.count('"') % 2 == 0, f"dangling quote in {label!r}"
    else:
        assert label.count("(") == label.count(")"), f"dangling bracket in {label!r}"


def test_a_short_title_is_left_alone():
    """Nothing to summarise means nothing to trim."""
    clusterer = SemanticClusterer()

    assert _label(clusterer, "xe đầu kéo", ["xe đầu kéo"]) == "xe đầu kéo"


def test_a_single_signal_cluster_keeps_its_own_words():
    """With one signal there is no shared vocabulary, so the title is all there is to show."""
    clusterer = SemanticClusterer()
    canonical = "màn tông xe tắt đèn đúng nghĩa đen giữa đêm tối"

    label = _label(clusterer, canonical, [canonical])

    assert "…" not in label
    assert label and label in canonical
