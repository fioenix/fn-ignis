"""What the shared identity resolver must and must not fuse.

Both halves matter. Two routes into one namespace have to converge, or the same object is stored
twice; two namespaces on one platform have to stay apart, or two objects are stored once.
"""

from ignis.domain.source_identity import (
    IDENTITY_FROM_METADATA,
    IDENTITY_FROM_NORMALIZED_URL,
    IDENTITY_FROM_URL,
    resolve_source_identity,
)


def identity_of(platform, source_url=None, metadata=None):
    resolved = resolve_source_identity(platform, source_url, metadata)
    return None if resolved is None else resolved.canonical_identity


# --- one object, two routes -------------------------------------------------------------------


def test_metadata_and_url_resolve_one_youtube_video_to_one_identity():
    """The corpus holds 3 pairs like this; keying on the route filed each as two sources."""
    from_metadata = resolve_source_identity(
        "youtube", "https://www.youtube.com/watch?v=abc123", {"video_id": "abc123"}
    )
    from_url = resolve_source_identity("youtube", "https://www.youtube.com/watch?v=abc123", {})

    assert from_metadata.canonical_identity == from_url.canonical_identity == "youtube:video:abc123"
    # The route is still recorded -- just not in the key.
    assert from_metadata.identity_source == IDENTITY_FROM_METADATA
    assert from_url.identity_source == IDENTITY_FROM_URL


def test_a_short_link_resolves_to_the_same_video_as_the_watch_url():
    assert identity_of("youtube", "https://youtu.be/abc123") == identity_of(
        "youtube", "https://www.youtube.com/watch?v=abc123"
    )


def test_a_tiktok_item_id_and_its_video_url_are_one_object():
    assert identity_of("tiktok", "https://www.tiktok.com/@a/video/12345", {"item_id": "12345"}) == (
        identity_of("tiktok", "https://www.tiktok.com/@a/video/12345")
    )


def test_a_probe_keyword_is_the_same_keyword_as_a_trend_keyword():
    assert identity_of("google", None, {"probe_keyword": "ao thun"}) == identity_of(
        "google", None, {"keyword": "ao thun"}
    )


def test_an_instagram_shortcode_is_one_object_under_both_url_shapes():
    """Instagram serves one shortcode space, and /p/ on a reel's shortcode redirects to it."""
    assert identity_of("reels", "https://www.instagram.com/reel/XYZ") == identity_of(
        "reels", "https://www.instagram.com/p/XYZ"
    )


# --- two objects, one platform ----------------------------------------------------------------


def test_a_tiktok_tag_and_a_tiktok_video_sharing_a_value_stay_two_objects():
    """A hashtag named "12345" is not item 12345. This is why the namespace sits in the key."""
    tag = identity_of("tiktok", None, {"hashtag": "12345"})
    video = identity_of("tiktok", None, {"item_id": "12345"})
    assert tag == "tiktok:tag:12345"
    assert video == "tiktok:video:12345"
    assert tag != video


def test_the_same_identifier_on_two_platforms_is_two_objects():
    assert identity_of("youtube", None, {"video_id": "abc"}) != identity_of(
        "tiktok", None, {"item_id": "abc"}
    )


# --- what identity ignores --------------------------------------------------------------------


def test_a_title_takes_no_part_in_identity():
    """Ten URLs in the corpus reported two titles, so a title is observed, not identifying."""
    assert identity_of("youtube", "https://youtu.be/abc", {"video_id": "abc", "title": "one"}) == (
        identity_of("youtube", "https://youtu.be/abc", {"video_id": "abc", "title": "another"})
    )


def test_tracking_parameters_and_a_www_prefix_do_not_make_a_second_object():
    assert identity_of("threads", "https://www.threads.net/@a/post/P1?utm_source=x") == (
        identity_of("threads", "https://threads.net/@a/post/P1")
    )


def test_a_url_with_no_recoverable_identifier_falls_back_to_the_normalized_url():
    resolved = resolve_source_identity("threads", "https://threads.net/explore", {})
    assert resolved.identity_source == IDENTITY_FROM_NORMALIZED_URL
    assert resolved.canonical_identity == "threads:url:https://threads.net/explore"


def test_nothing_identifying_resolves_to_nothing():
    """The audit counts these rather than inventing a key for them."""
    assert resolve_source_identity("threads", None, {}) is None
    assert resolve_source_identity("threads", "", {"unrelated": "x"}) is None


def test_an_empty_metadata_value_does_not_win_over_the_url():
    resolved = resolve_source_identity("youtube", "https://youtu.be/abc123", {"video_id": "  "})
    assert resolved.external_id == "video:abc123"
    assert resolved.identity_source == IDENTITY_FROM_URL
