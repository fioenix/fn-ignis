"""T003: the author identity policy strips every author field and keeps everything else."""

import copy
import json

import pytest

from ignis.domain.author_identity import AUTHOR_FIELD_KEYS, has_handle_segment, strip_author_identity
from ignis.domain.self_content import ACCOUNT_ID_METADATA_KEYS, AUTHOR_METADATA_KEYS
from tests.fixtures import author_identity_sentinels as s

PLATFORM_METADATA = {
    "youtube": s.youtube_metadata,
    "tiktok": s.tiktok_metadata,
    "threads": s.threads_metadata,
    "reels": s.reels_metadata,
    "google": s.google_trends_metadata,
    "host_browser": s.host_browser_metadata,
    "operator": s.operator_self_metadata,
}


def test_the_field_list_covers_research_r2_and_reuses_the_self_content_keys():
    expected = set(AUTHOR_METADATA_KEYS) | set(ACCOUNT_ID_METADATA_KEYS) | {
        "channel_id", "channel_title", "channel", "author_name", "nickname", "unique_id",
        "uniqueId", "user", "profile_url", "avatar",
    }
    assert expected <= set(AUTHOR_FIELD_KEYS)


@pytest.mark.parametrize("platform", sorted(PLATFORM_METADATA))
def test_no_sentinel_survives_stripping(platform):
    stripped = strip_author_identity(PLATFORM_METADATA[platform]())

    dumped = json.dumps(stripped, ensure_ascii=False)
    leaked = [value for value in s.undeclared_sentinels() if value in dumped]
    assert leaked == [], f"{platform} metadata still holds {leaked}"


@pytest.mark.parametrize("platform", sorted(PLATFORM_METADATA))
def test_every_author_key_is_removed_at_the_top_level(platform):
    stripped = strip_author_identity(PLATFORM_METADATA[platform]())

    assert set(stripped) & set(AUTHOR_FIELD_KEYS) == set()


def test_nested_comment_authors_are_removed_and_their_text_is_kept():
    stripped = strip_author_identity(s.tiktok_metadata())

    assert [comment.get("text") for comment in stripped["comments"]] == ["đẹp quá", s.MENTION_TEXT]
    for comment in stripped["comments"]:
        assert "author" not in comment and "author_id" not in comment


def test_a_comment_count_is_not_mistaken_for_a_comment_record():
    stripped = strip_author_identity(s.youtube_metadata())

    assert stripped["comments"] == 21


def test_a_handle_bearing_video_url_is_removed():
    stripped = strip_author_identity(s.tiktok_metadata())

    assert "video_url" not in stripped


def test_a_handle_free_video_url_is_kept():
    link = f"https://www.tiktok.com/share/video/{s.TIKTOK_ITEM_ID}"
    stripped = strip_author_identity({"item_id": s.TIKTOK_ITEM_ID, "video_url": link})

    assert stripped["video_url"] == link


@pytest.mark.parametrize("platform", sorted(PLATFORM_METADATA))
def test_non_author_metadata_is_preserved_unchanged(platform):
    original = PLATFORM_METADATA[platform]()
    stripped = strip_author_identity(original)

    for key, value in original.items():
        if key in AUTHOR_FIELD_KEYS or key in ("video_url", "comments"):
            continue
        assert stripped[key] == value, key


def test_the_input_is_not_mutated():
    original = s.tiktok_metadata()
    before = copy.deepcopy(original)

    strip_author_identity(original)

    assert original == before


@pytest.mark.parametrize(
    "url",
    [
        s.TIKTOK_HANDLE_URL,
        s.THREADS_HANDLE_URL,
        s.REELS_HANDLE_URL,
        s.SENTINEL_PROFILE_URL,
        "https://www.youtube.com/@sentinel.youtube",
        "https://www.youtube.com/channel/UCsentinel0yt0channel0id",
        "https://www.youtube.com/user/sentinelyoutube",
        "https://www.youtube.com/c/SentinelYoutube",
    ],
)
def test_handle_and_profile_segments_are_recognised(url):
    assert has_handle_segment(url) is True


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.tiktok.com/share/video/{s.TIKTOK_ITEM_ID}",
        f"https://www.threads.com/t/{s.THREADS_SHORTCODE}",
        f"https://www.instagram.com/reel/{s.REELS_SHORTCODE}/",
        f"https://www.youtube.com/watch?v={s.YOUTUBE_VIDEO_ID}",
        "https://vnexpress.net/matcha-latte-4800000.html",
        "",
        None,
    ],
)
def test_content_links_are_not_mistaken_for_handles(url):
    assert has_handle_segment(url) is False
