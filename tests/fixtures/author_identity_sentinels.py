"""Recognisable author identities for the Spec 015 tests (T002).

Every value here is fictional and chosen so that a substring search over a database, a file, a
response or a log finds it unambiguously. The conformance test plants these values in every author
field a connector can emit and then asserts that none of them survives anywhere outside a declared
account.

The metadata dictionaries mirror the shapes the connectors produce today (field names are the
platforms' own and are matched verbatim). Non-author fields are included on purpose: the policy
must keep them unchanged.
"""

from __future__ import annotations

from typing import Dict, List

# One recognisable value per author field. Handles are lower case because handles are matched
# case-insensitively; display names carry Vietnamese diacritics because real ones do.
SENTINEL_YOUTUBE_CHANNEL_ID = "UCsentinel0yt0channel0id"
SENTINEL_YOUTUBE_CHANNEL_TITLE = "Kênh Sentinel Trần"
SENTINEL_TIKTOK_HANDLE = "sentinel.tiktok.author"
SENTINEL_TIKTOK_NICKNAME = "Sentinel Nguyễn Văn"
SENTINEL_TIKTOK_COMMENTER = "sentinel.tiktok.commenter"
SENTINEL_TIKTOK_COMMENTER_ID = "7700000000000000101"
SENTINEL_THREADS_HANDLE = "sentinel.threads.author"
SENTINEL_THREADS_USER_ID = "6300000000000000202"
SENTINEL_REELS_HANDLE = "sentinel.reels.author"
SENTINEL_REELS_USER_ID = "5100000000000000303"
SENTINEL_HOST_BROWSER_HANDLE = "sentinel.hostbrowser.author"
SENTINEL_MENTIONED_HANDLE = "sentinel.mention.linh"
SENTINEL_PROFILE_URL = "https://www.tiktok.com/@sentinel.profile.url"
SENTINEL_AVATAR_URL = "https://p16-sign.tiktokcdn.com/sentinel-avatar.jpeg"

# The operator's own connected account. Content from it is excluded before the identity policy
# runs, so its handle must not appear either.
SENTINEL_OPERATOR_HANDLE = "sentinel.operator.self"
SENTINEL_OPERATOR_USER_ID = "4200000000000000404"

# A brand account the requester declares for a mission. It is the only identity allowed to remain.
DECLARED_BRAND_HANDLE = "sentinel.brand.declared"
DECLARED_BRAND_NAME = "Brand Sentinel"

# Content identifiers taken from the live probe in research R5; they carry no identity.
TIKTOK_ITEM_ID = "7694797676306615583"
THREADS_SHORTCODE = "DeZtp-TkQHh"
THREADS_POST_ID = "3700000000000000505"
REELS_SHORTCODE = "DSentinelR1"
YOUTUBE_VIDEO_ID = "sentinelYT1"

# Handle-bearing links exactly as the connectors build them today.
TIKTOK_HANDLE_URL = f"https://www.tiktok.com/@{SENTINEL_TIKTOK_HANDLE}/video/{TIKTOK_ITEM_ID}"
THREADS_HANDLE_URL = f"https://www.threads.net/@{SENTINEL_THREADS_HANDLE}/post/{THREADS_SHORTCODE}"
REELS_HANDLE_URL = f"https://www.instagram.com/{SENTINEL_REELS_HANDLE}/reel/{REELS_SHORTCODE}/"
HOST_BROWSER_HANDLE_URL = f"https://www.tiktok.com/@{SENTINEL_HOST_BROWSER_HANDLE}/video/{TIKTOK_ITEM_ID}"

# Text that names an account inside the content itself (research R7).
MENTION_TEXT = f"@{SENTINEL_MENTIONED_HANDLE} mua ở đâu vậy, giá bao nhiêu?"
DECLARED_MENTION_TEXT = f"Áo của @{DECLARED_BRAND_HANDLE} mặc mát không mọi người?"


def youtube_metadata() -> Dict[str, object]:
    return {
        "video_id": YOUTUBE_VIDEO_ID,
        "channel_id": SENTINEL_YOUTUBE_CHANNEL_ID,
        "channel_title": SENTINEL_YOUTUBE_CHANNEL_TITLE,
        "views": 12000,
        "likes": 340,
        "comments": 21,
        "keyword": "áo khoác chống nắng",
    }


def tiktok_metadata() -> Dict[str, object]:
    return {
        "item_id": TIKTOK_ITEM_ID,
        "author": SENTINEL_TIKTOK_HANDLE,
        "author_name": SENTINEL_TIKTOK_NICKNAME,
        "nickname": SENTINEL_TIKTOK_NICKNAME,
        "unique_id": SENTINEL_TIKTOK_HANDLE,
        "uniqueId": SENTINEL_TIKTOK_HANDLE,
        "channel": SENTINEL_TIKTOK_HANDLE,
        "profile_url": SENTINEL_PROFILE_URL,
        "avatar": SENTINEL_AVATAR_URL,
        "video_url": TIKTOK_HANDLE_URL,
        "likes": 900,
        "comments": [
            {"text": "đẹp quá", "author": SENTINEL_TIKTOK_COMMENTER, "author_id": SENTINEL_TIKTOK_COMMENTER_ID},
            {"text": MENTION_TEXT, "author": SENTINEL_TIKTOK_COMMENTER, "author_id": SENTINEL_TIKTOK_COMMENTER_ID},
        ],
        "shares": 12,
        "keyword": "áo khoác chống nắng",
        "excerpt": "Review áo khoác chống nắng đi xe máy",
        "collection_path": "native_browser:tiktok-public-json",
    }


def threads_metadata() -> Dict[str, object]:
    return {
        "post_id": THREADS_POST_ID,
        "username": SENTINEL_THREADS_HANDLE,
        "user_id": SENTINEL_THREADS_USER_ID,
        "like_count": 45,
        "reply_count": 7,
        "excerpt": MENTION_TEXT,
        "source": "threads_browser_session",
    }


def reels_metadata() -> Dict[str, object]:
    return {
        "reel_id": REELS_SHORTCODE,
        "username": SENTINEL_REELS_HANDLE,
        "user_id": SENTINEL_REELS_USER_ID,
        "user": {"username": SENTINEL_REELS_HANDLE, "pk": SENTINEL_REELS_USER_ID},
        "comments": 3,
        "likes": 88,
    }


def google_trends_metadata() -> Dict[str, object]:
    # Google Trends carries a publisher, not a person; nothing here is author identity.
    return {"keyword": "matcha", "news_source": "VnExpress", "traffic": "2000+"}


def host_browser_metadata() -> Dict[str, object]:
    return {
        "item_id": TIKTOK_ITEM_ID,
        "author": SENTINEL_HOST_BROWSER_HANDLE,
        "excerpt": "Áo khoác nhẹ gấp gọn bỏ cốp xe",
    }


def operator_self_metadata() -> Dict[str, object]:
    return {
        "post_id": "3700000000000000999",
        "username": SENTINEL_OPERATOR_HANDLE,
        "user_id": SENTINEL_OPERATOR_USER_ID,
        "excerpt": "Bài của chính tài khoản vận hành",
    }


def undeclared_sentinels() -> List[str]:
    """Every value that must not survive anywhere once the policy has run."""
    return [
        SENTINEL_YOUTUBE_CHANNEL_ID,
        SENTINEL_YOUTUBE_CHANNEL_TITLE,
        SENTINEL_TIKTOK_HANDLE,
        SENTINEL_TIKTOK_NICKNAME,
        SENTINEL_TIKTOK_COMMENTER,
        SENTINEL_TIKTOK_COMMENTER_ID,
        SENTINEL_THREADS_HANDLE,
        SENTINEL_THREADS_USER_ID,
        SENTINEL_REELS_HANDLE,
        SENTINEL_REELS_USER_ID,
        SENTINEL_HOST_BROWSER_HANDLE,
        SENTINEL_PROFILE_URL,
        SENTINEL_AVATAR_URL,
        SENTINEL_OPERATOR_HANDLE,
        SENTINEL_OPERATOR_USER_ID,
    ]


def mention_sentinels() -> List[str]:
    """Handles that appear only inside content text; the scan adds these from T030 on."""
    return [SENTINEL_MENTIONED_HANDLE]
