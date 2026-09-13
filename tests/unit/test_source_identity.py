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


# --- one object, two routes that disagreed until the value itself was canonicalised ------------


def test_a_tiktok_hashtag_is_one_object_whether_or_not_the_route_kept_the_hash():
    """Creative Center writes "#aothun" in metadata and .../tag/aothun in the URL.

    Same hashtag, same connector, same pass -- and until the value was canonicalised the two
    routes produced tag:#aothun and tag:aothun, so one hashtag occupied two rows.
    """
    assert identity_of("tiktok", "https://www.tiktok.com/tag/aothun", {"hashtag": "#aothun"}) == (
        identity_of("tiktok", "https://www.tiktok.com/tag/aothun")
    )
    assert identity_of("tiktok", None, {"hashtag": "#aothun"}) == "tiktok:tag:aothun"


def test_a_google_keyword_is_one_object_whether_it_arrived_encoded_or_not():
    """The explore URL percent-encodes the keyword the metadata carries verbatim."""
    assert identity_of(
        "google",
        "https://trends.google.com/trends/explore?geo=VN&q=AI%20Agent",
        {"keyword": "AI Agent"},
    ) == identity_of("google", "https://trends.google.com/trends/explore?geo=VN&q=AI%20Agent")
    assert identity_of("google", None, {"keyword": "AI Agent"}) == "google:keyword:AI Agent"


def test_a_google_keyword_encoded_with_plus_is_the_same_keyword():
    assert identity_of("google", "https://trends.google.com/trends/explore?q=AI+Agent") == (
        identity_of("google", None, {"keyword": "AI Agent"})
    )


# --- two identifier spaces that must not be filed as one --------------------------------------


def test_a_threads_numeric_id_and_a_shortcode_are_kept_in_separate_namespaces():
    """They are different identifier spaces, and this build has no lookup between them.

    The Graph API reports a numeric pk; a permalink carries a shortcode. Filing both under
    "post:" would be a claim that the two values are comparable, and a shortcode made only of
    digits would then silently collide with somebody else's pk. Keeping them apart states the
    truth: two rows, because the corpus cannot yet prove they are one object.
    """
    from_metadata = identity_of("threads", None, {"post_id": "123456789"})
    from_url = identity_of("threads", "https://www.threads.net/@a/post/123456789")

    assert from_metadata == "threads:post:123456789"
    assert from_url == "threads:post_shortcode:123456789"
    assert from_metadata != from_url


def test_an_instagram_reel_id_and_a_shortcode_are_kept_in_separate_namespaces():
    assert identity_of("reels", None, {"reel_id": "17912"}) == "reels:reel:17912"
    assert identity_of("reels", "https://www.instagram.com/reel/17912") == (
        "reels:reel_shortcode:17912"
    )


def test_the_two_instagram_url_shapes_still_agree_with_each_other():
    """Separating the namespaces must not undo what /reel/ and /p/ already agreed on."""
    assert identity_of("reels", "https://www.instagram.com/reel/XYZ") == identity_of(
        "reels", "https://www.instagram.com/p/XYZ"
    )
