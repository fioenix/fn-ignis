"""T038 review findings on the author identity policy, each pinned before its fix.

A handle hides in more link shapes than /@ascii: percent-encoded, Unicode, full-width at signs,
scheme-less hosts and Instagram story paths. A display name must never key a marker, and a tuple
must be stripped like a list.
"""

import pytest

from ignis.domain.author_identity import (
    AuthorState,
    assign_author,
    author_identity_violation,
    has_handle_segment,
    strip_author_identity,
)
from ignis.domain.source_identity import identity_free_source_url, resolve_source_identity

KEY = bytes(range(32))


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@Đạt",
        "https://www.youtube.com/%40%C4%90%E1%BA%A1t",
        "https://www.tiktok.com/%40nguyenvana/video/1",
        "https://www.tiktok.com/＠abc/video/1",
        "www.tiktok.com/@abc/video/1",
        "tiktok.com/@abc/video/1",
        "https://www.threads.com/@ngọc.anh",
        "https://www.instagram.com/stories/alice/1",
        "https://m.youtube.com/@kenh",
    ],
)
def test_every_shape_of_a_handle_link_is_recognised(url):
    assert has_handle_segment(url), url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.tiktok.com/share/video/1",
        "https://www.instagram.com/accounts/login/",
        "https://www.instagram.com/explore/tags/aothun/",
        "https://www.instagram.com/s/aGlnaGxpZ2h0",
        "https://www.instagram.com/direct/inbox/",
        "https://www.youtube.com/watch?v=abc123",
        "seller@example.test",
    ],
)
def test_content_and_service_paths_are_not_handles(url):
    assert not has_handle_segment(url), url


def test_two_instagram_stories_by_two_people_get_two_markers():
    alice = assign_author("reels", {}, "https://www.instagram.com/stories/alice/1", KEY)
    bob = assign_author("reels", {}, "https://www.instagram.com/stories/bob/2", KEY)

    assert alice.state is bob.state is AuthorState.KNOWN
    assert alice.marker != bob.marker


def test_a_unicode_or_encoded_handle_link_is_neither_a_key_nor_a_stored_link():
    assert resolve_source_identity("youtube", "https://www.youtube.com/@Đạt", {}) is None
    assert identity_free_source_url("tiktok", "https://www.tiktok.com/%40nguyenvana/video/1", {}) == (
        "https://www.tiktok.com/share/video/1"
    )
    assert identity_free_source_url("youtube", "https://www.youtube.com/@Đạt", {}) is None


def test_a_tuple_is_stripped_like_a_list():
    metadata = {"comments": ({"unique_id": "abc", "text": "đẹp"},)}

    assert strip_author_identity(metadata) == {"comments": [{"text": "đẹp"}]}
    assert author_identity_violation(metadata, None) is not None


def test_a_display_name_never_beats_the_handle_in_the_link():
    declared = {("tiktok", "brandx"): "declared-1"}

    assigned = assign_author(
        "tiktok", {"author": "Brand X Official"}, "https://www.tiktok.com/@brandx/video/1", KEY, declared=declared
    )

    assert (assigned.state, assigned.declared_account_id) == (AuthorState.DECLARED, "declared-1")


def test_two_creators_sharing_a_display_name_get_two_markers():
    one = assign_author("tiktok", {"author": "Shop Áo Đẹp"}, "https://www.tiktok.com/@shop.one/video/1", KEY)
    two = assign_author("tiktok", {"author": "Shop Áo Đẹp"}, "https://www.tiktok.com/@shop.two/video/2", KEY)

    assert one.marker != two.marker


@pytest.mark.parametrize(
    "metadata",
    [{"author": "Shop Áo Đẹp"}, {"author_name": "Nguyễn Văn A"}, {"nickname": "Bé Na"}, {"channel_title": "Kênh"}],
)
def test_a_display_name_alone_is_unknown(metadata):
    assert assign_author("tiktok", metadata, None, KEY).state is AuthorState.UNKNOWN
